"""Load, merge and save the repo records under data/.

Facts that rarely change (name, owner, review) live in data/repos/<first-seen month>.jsonl.
Numbers that change every week live in data/stats.jsonl, so weekly commits stay small.

A record's `status` is one of:
  tracked   in the traction pool, not reviewed yet (only reviewed when it would be shown)
  pending   waiting for a Claude review
  listed    reviewed and kept (or allowlisted): shown in the lists
  rejected  reviewed and dropped
Flags `blocked`, `excluded` (a free-rule reason, e.g. archived later), `gone` (date) and
`frozen` hide or stop tracking a record without losing it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from .locations import Place

STABLE_FIELDS = (
    "full_name", "url", "description", "homepage", "language", "license", "topics",
    "created_at", "owner",
)


class Store:
    def __init__(self, repos: dict[str, dict] | None = None, stats: dict[str, dict] | None = None):
        self.repos = repos or {}
        self.stats = stats or {}

    @classmethod
    def load(cls, data_dir: Path) -> "Store":
        repos: dict[str, dict] = {}
        for path in sorted((data_dir / "repos").glob("*.jsonl")):
            for rec in _read_jsonl(path):
                repos[rec["id"]] = rec
        stats = {row["id"]: row for row in _read_jsonl(data_dir / "stats.jsonl")}
        return cls(repos, stats)

    def save(self, data_dir: Path) -> None:
        shards: dict[str, list[dict]] = defaultdict(list)
        for rec in self.repos.values():
            shards[rec["first_seen"][:7]].append(rec)
        for month, recs in shards.items():
            _write_jsonl(data_dir / "repos" / f"{month}.jsonl", sorted(recs, key=lambda r: r["id"]))
        _write_jsonl(data_dir / "stats.jsonl", sorted(self.stats.values(), key=lambda r: r["id"]))

    def upsert(self, snap: dict, place: Place, lanes: set[str], today: date) -> dict:
        """Add a discovered repo, or update the one we already have."""
        rec = self.repos.get(snap["id"])
        if rec is None:
            rec = {
                "id": snap["id"], "first_seen": today.isoformat(), "lanes": [],
                "status": "tracked", "review": None, "review_attempts": 0,
                "traction_rank": None, "allowlisted": False, "blocked": False,
                "excluded": None, "frozen": False, "gone": None,
            }
            self.repos[snap["id"]] = rec
            _set_place(rec, place)
        elif rec["status"] in ("tracked", "pending"):
            _set_place(rec, place)  # not listed yet, so follow the owner's latest location
        rec["lanes"] = sorted(set(rec["lanes"]) | lanes)
        rec["gone"] = None
        for key in STABLE_FIELDS:
            rec[key] = snap[key]
        if rec["status"] == "tracked" and "new" in lanes:
            rec["status"] = "pending"
        self.set_stats(snap, today)
        return rec

    def refresh(self, snap: dict, today: date) -> None:
        rec = self.repos[snap["id"]]
        for key in STABLE_FIELDS:
            rec[key] = snap[key]  # picks up renames and new descriptions
        rec["gone"] = None
        self.set_stats(snap, today)

    def mark_gone(self, repo_id: str, today: date) -> None:
        rec = self.repos[repo_id]
        if not rec.get("gone"):
            rec["gone"] = today.isoformat()

    def set_stats(self, snap: dict, today: date) -> None:
        row = self.stats.setdefault(snap["id"], {"id": snap["id"], "snapshots": []})
        row.update(
            stars=snap["stars"], forks=snap["forks"], pushed_at=snap["pushed_at"],
            refreshed=today.isoformat(),
        )

    def stars(self, repo_id: str) -> int:
        return self.stats.get(repo_id, {}).get("stars", 0)

    def find(self, full_name: str) -> dict | None:
        name = full_name.lower()
        return next((r for r in self.repos.values() if r["full_name"].lower() == name), None)

    def review_queue(self, max_attempts: int) -> list[dict]:
        """Repos waiting for review, most important first."""
        waiting = [
            r for r in self.repos.values()
            if r["status"] == "pending" and not hidden(r) and not r["frozen"]
            and r["review_attempts"] < max_attempts
        ]
        return sorted(waiting, key=self._priority)

    def _priority(self, rec: dict) -> tuple:
        # SF Bay Area first, then the rest of the US, then traction candidates, then everyone else
        new = "new" in rec["lanes"]
        if rec["allowlisted"]:
            tier = 0
        elif new and rec["section"] == "sf-bay-area":
            tier = 1
        elif new and rec["section"] == "rest-of-us":
            tier = 2
        elif rec.get("traction_rank") is not None:
            tier = 3
        else:
            tier = 4
        return (tier, rec.get("traction_rank") or 0, -self.stars(rec["id"]), rec["id"])


def hidden(rec: dict) -> bool:
    return bool(rec["blocked"] or rec["gone"] or rec.get("excluded"))


def is_listed(rec: dict) -> bool:
    return rec["status"] == "listed" and not hidden(rec)


def _set_place(rec: dict, place: Place) -> None:
    rec["section"], rec["state"], rec["country"] = place.section, place.state, place.country


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
