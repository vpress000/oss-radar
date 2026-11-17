"""Find repos on GitHub and fetch the extra details a review needs."""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, timedelta

from .common import chunks
from .config import Config
from .github_api import RATE_FIELDS, GitHubClient

log = logging.getLogger(__name__)

SEARCH_CAP = 1000  # GitHub returns at most this many results for one search
SEARCH_FILTERS = "fork:false archived:false mirror:false template:false is:public sort:stars-desc"

REPO_FIELDS = """
id nameWithOwner url description homepageUrl createdAt pushedAt
stargazerCount forkCount isFork isArchived isMirror isTemplate isPrivate
primaryLanguage { name }
licenseInfo { spdxId }
repositoryTopics(first: 8) { nodes { topic { name } } }
owner {
  __typename login
  ... on User { name location createdAt }
  ... on Organization { name location createdAt }
}
"""

SEARCH_QUERY = (
    "query($q: String!, $after: String) {"
    " search(type: REPOSITORY, query: $q, first: 100, after: $after) {"
    " repositoryCount pageInfo { hasNextPage endCursor }"
    " nodes { ... on Repository { " + REPO_FIELDS + " } } } " + RATE_FIELDS + " }"
)
NODES_QUERY = (
    "query($ids: [ID!]!) { nodes(ids: $ids) { ... on Repository { " + REPO_FIELDS + " } } "
    + RATE_FIELDS + " }"
)

README_NAMES = (
    "README.md", "readme.md", "Readme.md", "README.MD", "README.markdown", "README.rst",
    "README.txt", "README",
)
DETAILS_QUERY = (
    "query($ids: [ID!]!) { nodes(ids: $ids) { ... on Repository { id "
    + " ".join(
        f'r{i}: object(expression: "HEAD:{name}") {{ ... on Blob {{ text }} }}'
        for i, name in enumerate(README_NAMES)
    )
    + " owner { login"
    " ... on User { followers { totalCount } bio company }"
    " ... on Organization { description }"
    " repositories(first: 4, orderBy: {field: STARGAZERS, direction: DESC},"
    " ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false)"
    " { nodes { nameWithOwner stargazerCount } } } } } " + RATE_FIELDS + " }"
)


def normalize(node: dict) -> dict:
    """Flatten a GraphQL Repository node into the snapshot dict the rest of the code uses."""
    owner = node.get("owner") or {}
    spdx = (node.get("licenseInfo") or {}).get("spdxId")
    return {
        "id": node["id"],
        "full_name": node["nameWithOwner"],
        "url": node["url"],
        "description": (node.get("description") or "").strip(),
        "homepage": node.get("homepageUrl") or None,
        "created_at": node["createdAt"],
        "pushed_at": node.get("pushedAt") or node["createdAt"],
        "stars": node["stargazerCount"],
        "forks": node["forkCount"],
        "is_fork": node["isFork"],
        "is_archived": node["isArchived"],
        "is_mirror": node["isMirror"],
        "is_template": node["isTemplate"],
        "is_private": node["isPrivate"],
        "language": (node.get("primaryLanguage") or {}).get("name"),
        "license": "Other" if spdx == "NOASSERTION" else spdx,
        "topics": [t["topic"]["name"] for t in (node.get("repositoryTopics") or {}).get("nodes", [])],
        "owner": {
            "login": owner.get("login"),
            "type": "org" if owner.get("__typename") == "Organization" else "user",
            "name": owner.get("name"),
            "location": owner.get("location"),
            "created_at": owner.get("createdAt"),
        },
    }


def search(client: GitHubClient, query: str, lo: int, hi: int | None = None) -> list[dict]:
    """Every repo matching `query` with lo..hi stars, splitting the star range past the cap."""
    stars = f"stars:>={lo}" if hi is None else f"stars:{lo}..{hi}"
    q = f"{query} {stars} {SEARCH_FILTERS}"
    page = client.graphql(SEARCH_QUERY, {"q": q, "after": None}, search=True)["search"]
    nodes = [n for n in page["nodes"] if n and n.get("id")]
    total = page["repositoryCount"]
    if total > SEARCH_CAP:
        # Results are sorted by stars, so the first one shows the top of the range
        top = hi if hi is not None else (nodes[0]["stargazerCount"] if nodes else lo)
        if top > lo:
            mid = min(max(lo, int(math.sqrt(lo * top))), top - 1)
            log.info("%s: %d results; splitting stars %d..%d at %d", query, total, lo, top, mid)
            return search(client, query, lo, mid) + search(client, query, mid + 1, top)
        log.warning("%s: %d results at %d stars; keeping the first %d", query, total, lo, SEARCH_CAP)
    while page["pageInfo"]["hasNextPage"] and len(nodes) < SEARCH_CAP:
        cursor = page["pageInfo"]["endCursor"]
        page = client.graphql(SEARCH_QUERY, {"q": q, "after": cursor}, search=True)["search"]
        nodes.extend(n for n in page["nodes"] if n and n.get("id"))
    return [normalize(n) for n in nodes]


def discover_new(client: GitHubClient, cfg: Config, today: date) -> list[dict]:
    """Repos created in the new-lane window, one search per creation day."""
    found: dict[str, dict] = {}
    for offset in range(cfg.new_window_days):
        day = today - timedelta(days=offset)
        for repo in search(client, f"created:{day.isoformat()}", cfg.new_search_min_stars):
            found[repo["id"]] = repo
    log.info("New lane: %d repos with %d+ stars", len(found), cfg.new_search_min_stars)
    return list(found.values())


def discover_traction(client: GitHubClient, cfg: Config, today: date) -> list[dict]:
    """Repos in the traction pool, one search per 30 days of creation dates."""
    found: dict[str, dict] = {}
    start = today - timedelta(days=cfg.traction_window_days - 1)
    while start <= today:
        end = min(start + timedelta(days=29), today)
        query = f"created:{start.isoformat()}..{end.isoformat()}"
        for repo in search(client, query, cfg.traction_min_stars):
            found[repo["id"]] = repo
        start = end + timedelta(days=1)
    log.info("Traction lane: %d repos with %d+ stars", len(found), cfg.traction_min_stars)
    return list(found.values())


def fetch_nodes(client: GitHubClient, ids: list[str]) -> dict[str, dict | None]:
    """Current state of known repos; None for repos that are gone or now private."""
    out: dict[str, dict | None] = {}
    for batch in chunks(ids, 100):
        nodes = client.graphql(NODES_QUERY, {"ids": batch}, allow_not_found=True).get("nodes") or []
        for repo_id, node in zip(batch, nodes):
            out[repo_id] = normalize(node) if node and node.get("id") else None
    return out


def fetch_by_name(client: GitHubClient, full_names: list[str]) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    for batch in chunks(full_names, 20):
        fields = []
        for i, full_name in enumerate(batch):
            owner, name = full_name.split("/", 1)
            fields.append(
                f"r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)})"
                f" {{ {REPO_FIELDS} }}"
            )
        data = client.graphql("query { " + " ".join(fields) + " " + RATE_FIELDS + " }",
                              allow_not_found=True)
        for i, full_name in enumerate(batch):
            node = data.get(f"r{i}")
            out[full_name] = normalize(node) if node else None
    return out


def fetch_details(client: GitHubClient, ids: list[str], readme_chars: int) -> dict[str, dict]:
    """README excerpt and owner track record for the repos about to be reviewed."""
    out: dict[str, dict] = {}
    for batch in chunks(ids, 10):  # READMEs can be large, so keep batches small
        nodes = client.graphql(DETAILS_QUERY, {"ids": batch}, allow_not_found=True).get("nodes") or []
        for node in nodes:
            if not node or not node.get("id"):
                continue
            readme = next(
                (node[f"r{i}"]["text"] for i in range(len(README_NAMES))
                 if (node.get(f"r{i}") or {}).get("text")),
                "",
            )
            owner = node.get("owner") or {}
            out[node["id"]] = {
                "readme": clean_readme(readme, readme_chars),
                "followers": (owner.get("followers") or {}).get("totalCount"),
                "bio": (owner.get("bio") or owner.get("description") or "")[:200],
                "company": owner.get("company"),
                "top_repos": [
                    [r["nameWithOwner"], r["stargazerCount"]]
                    for r in (owner.get("repositories") or {}).get("nodes", [])
                ],
            }
    return out


def clean_readme(text: str, limit: int) -> str:
    """README text without HTML, badges and link targets, cut to `limit` characters."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", " ", text)  # linked badges
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)  # images
    text = re.sub(r"<[^>]+>", " ", text)  # HTML tags
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # links: keep the text
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:limit]


class GitHubSource:
    """Everything the pipeline asks of GitHub, in one place (tests use a fake)."""

    def __init__(self, client: GitHubClient, cfg: Config):
        self.client = client
        self.cfg = cfg

    def discover_new(self, today: date) -> list[dict]:
        return discover_new(self.client, self.cfg, today)

    def discover_traction(self, today: date) -> list[dict]:
        return discover_traction(self.client, self.cfg, today)

    def fetch_nodes(self, ids: list[str]) -> dict[str, dict | None]:
        return fetch_nodes(self.client, ids)

    def fetch_by_name(self, full_names: list[str]) -> dict[str, dict | None]:
        return fetch_by_name(self.client, full_names)

    def fetch_details(self, ids: list[str]) -> dict[str, dict]:
        return fetch_details(self.client, ids, self.cfg.readme_chars)

    @property
    def points_used(self) -> int:
        return self.client.points_used
