"""Builders and fakes shared by the tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from radar.reviewer import ReviewStopped, Verdict

ROOT = Path(__file__).resolve().parents[1]


def make_snap(repo_id="R_1", full_name="acme/tool", *, stars=100, forks=5,
              created="2026-11-10T00:00:00Z", pushed="2026-11-15T00:00:00Z",
              location="San Francisco, CA", owner_created="2020-01-01T00:00:00Z",
              owner_type="org", description="A useful tool", language="Python", license="MIT",
              topics=("cli",), **flags):
    owner = full_name.split("/")[0]
    snap = {
        "id": repo_id, "full_name": full_name, "url": f"https://github.com/{full_name}",
        "description": description, "homepage": None, "created_at": created, "pushed_at": pushed,
        "stars": stars, "forks": forks, "is_fork": False, "is_archived": False,
        "is_mirror": False, "is_template": False, "is_private": False, "language": language,
        "license": license, "topics": list(topics),
        "owner": {"login": owner, "type": owner_type, "name": None, "location": location,
                  "created_at": owner_created},
    }
    snap.update(flags)
    return snap


def make_project(tmp_path: Path, allow: str = "", block: str = "") -> Path:
    """A throwaway copy of the repo's config, templates and prompt, with its own curation lists."""
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(ROOT / "config.toml", project / "config.toml")
    shutil.copytree(ROOT / "templates", project / "templates")
    shutil.copytree(ROOT / "prompts", project / "prompts")
    (project / "curation").mkdir()
    (project / "curation" / "allowlist.txt").write_text(allow, encoding="utf-8")
    (project / "curation" / "blocklist.txt").write_text(block, encoding="utf-8")
    return project


class FakeSource:
    def __init__(self, new=(), traction=(), nodes=None, by_name=None, details=None):
        self.new = list(new)
        self.traction = list(traction)
        self.nodes = dict(nodes or {})
        self.by_name = dict(by_name or {})
        self.details = dict(details or {})
        self.points_used = 0
        self.fetched_nodes: list[str] = []

    def discover_new(self, today):
        return list(self.new)

    def discover_traction(self, today):
        return list(self.traction)

    def fetch_nodes(self, ids):
        self.fetched_nodes.extend(ids)
        return {repo_id: self.nodes.get(repo_id) for repo_id in ids}

    def fetch_by_name(self, names):
        return {name: self.by_name.get(name) for name in names}

    def fetch_details(self, ids):
        empty = {"readme": "", "followers": 1, "bio": "", "company": None, "top_repos": []}
        return {repo_id: self.details.get(repo_id, empty) for repo_id in ids}


class FakeReviewer:
    model = "test-model"

    def __init__(self, drop=(), stop_after=None, category="Developer Tools"):
        self.drop = set(drop)
        self.stop_after = stop_after
        self.category = category
        self.calls = 0
        self.equivalent_usd = 0.0
        self.credential_expires_at = None
        self.seen: list[str] = []

    def review(self, items):
        self.calls += 1
        if self.stop_after is not None and self.calls > self.stop_after:
            raise ReviewStopped("usage_limit", "Claude usage limit reached")
        self.seen.extend(item["repo"] for item in items)
        return [
            Verdict(item["id"], item["repo"] not in self.drop, f"Solves things for {item['repo']}",
                    self.category, "ok")
            for item in items
        ]
