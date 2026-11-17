"""Free checks that run before any Claude review, and the curation lists."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from .common import parse_ts
from .config import Config


def load_list(path: Path) -> set[str]:
    """Read a curation file: one owner or owner/repo per line; '#' starts a comment."""
    if not path.exists():
        return set()
    entries = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip().lower()
        entry = entry.removeprefix("https://").removeprefix("github.com/").strip("/")
        if entry:
            entries.add(entry)
    return entries


def listed_in(full_name: str, entries: set[str]) -> bool:
    """True when the repo, or its whole owner, is on the list."""
    name = full_name.lower()
    return name in entries or name.split("/", 1)[0] in entries


def rejection_reason(repo: dict, blocklist: set[str], cfg: Config) -> str | None:
    """Why a repo is dropped before review, or None when it may go on."""
    if repo["is_fork"] or repo["is_archived"] or repo["is_mirror"] or repo["is_template"]:
        return "fork, archived, mirror or template"
    if repo["is_private"]:
        return "private"
    owner, name = repo["full_name"].lower().split("/", 1)
    if name == owner:
        return "profile repo"
    if name.endswith((".github.io", ".github.com")):
        return "GitHub Pages site"
    if listed_in(repo["full_name"], blocklist):
        return "blocklist"
    if looks_star_farmed(repo, cfg):
        return "likely star farm"
    return None


def looks_star_farmed(repo: dict, cfg: Config) -> bool:
    """Brand-new owner account, nothing pushed after day one, and no forks."""
    created = parse_ts(repo["created_at"])
    owner_created = parse_ts(repo["owner"]["created_at"])
    pushed = parse_ts(repo["pushed_at"])
    if not (created and owner_created and pushed):
        return False
    new_owner = created - owner_created <= timedelta(days=cfg.star_farm_owner_age_days)
    idle = pushed - created <= timedelta(hours=cfg.star_farm_max_push_hours)
    return new_owner and idle and repo["forks"] == 0
