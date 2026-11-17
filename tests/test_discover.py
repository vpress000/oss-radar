import re
from datetime import date, timedelta

from radar import discover
from radar.discover import clean_readme, discover_traction, normalize, search


def node(i, stars):
    return {
        "id": f"R_{i}", "nameWithOwner": f"o{i}/r{i}", "url": f"https://github.com/o{i}/r{i}",
        "description": " desc ", "homepageUrl": "", "createdAt": "2026-11-10T00:00:00Z",
        "pushedAt": None, "stargazerCount": stars, "forkCount": 1, "isFork": False,
        "isArchived": False, "isMirror": False, "isTemplate": False, "isPrivate": False,
        "primaryLanguage": {"name": "Go"}, "licenseInfo": {"spdxId": "NOASSERTION"},
        "repositoryTopics": {"nodes": [{"topic": {"name": "cli"}}]},
        "owner": {"__typename": "Organization", "login": f"o{i}", "name": "O",
                  "location": "SF", "createdAt": "2020-01-01T00:00:00Z"},
    }


class FakeSearchClient:
    """Answers search queries from an in-memory list of star counts, 100 per page."""

    def __init__(self, stars):
        self.repos = [node(i, s) for i, s in enumerate(stars)]
        self.queries = []

    def graphql(self, query, variables=None, *, search=False, allow_not_found=False):
        q = variables["q"]
        self.queries.append(q)
        lo, hi = _star_range(q)
        hits = sorted((r for r in self.repos if lo <= r["stargazerCount"] <= hi),
                      key=lambda r: -r["stargazerCount"])
        start = int(variables["after"] or 0)
        page = hits[start:start + 100][: max(0, 1000 - start)]
        more = start + 100 < min(len(hits), 1000)
        return {"search": {"repositoryCount": len(hits), "nodes": page,
                           "pageInfo": {"hasNextPage": more, "endCursor": str(start + 100)}}}


def _star_range(q):
    if m := re.search(r"stars:(\d+)\.\.(\d+)", q):
        return int(m[1]), int(m[2])
    return int(re.search(r"stars:>=(\d+)", q)[1]), 10**9


def test_normalize_flattens_a_node():
    snap = normalize(node(1, 77))
    assert snap["full_name"] == "o1/r1"
    assert snap["license"] == "Other"  # GitHub's NOASSERTION
    assert snap["owner"]["type"] == "org"
    assert snap["topics"] == ["cli"]
    assert snap["description"] == "desc"
    assert snap["pushed_at"] == snap["created_at"]


def test_search_pages_through_results():
    client = FakeSearchClient([60 + i for i in range(250)])
    assert len(search(client, "created:2026-11-10", 50)) == 250
    assert len(client.queries) == 3


def test_search_splits_star_ranges_past_the_cap():
    stars = [50 + (i % 400) for i in range(2600)] + [5000, 9000]
    client = FakeSearchClient(stars)
    found = search(client, "created:2026-11-10", 50)
    assert len({r["id"] for r in found}) == len(stars)
    assert any(".." in q for q in client.queries)


def test_traction_windows_cover_every_day_once(cfg):
    calls = []

    def fake_search(client, query, lo, hi=None):
        calls.append(query)
        return []

    original = discover.search
    discover.search = fake_search
    try:
        discover_traction(None, cfg, date(2026, 11, 16))
    finally:
        discover.search = original
    days = set()
    for query in calls:
        start, end = (date.fromisoformat(d) for d in query.removeprefix("created:").split(".."))
        span = {start + timedelta(days=n) for n in range((end - start).days + 1)}
        assert not days & span
        days |= span
    assert len(days) == cfg.traction_window_days
    assert max(days) == date(2026, 11, 16)


def test_clean_readme_strips_markup():
    text = ('<h1 align="center"><img src="x.png"></h1>\n[![badge](b.svg)](ci)\n'
            "![shot](s.png)\nUse [the docs](https://x.dev) to start.\n\n\n<!-- hidden -->Done")
    assert clean_readme(text, 1000) == "Use the docs to start.\n Done"
    assert len(clean_readme("x" * 50, 10)) == 10
