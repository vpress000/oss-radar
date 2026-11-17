"""The run modes: the weekly full run, catch-up reviews, and render-only."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Protocol

from .common import age_days, chunks, to_date
from .config import Config
from .locations import classify
from .render import Renderer, existing_weeks, write_pages
from .reviewer import BadReply, ReviewStopped, Verdict
from .rules import listed_in, load_list, rejection_reason
from .store import Store, is_listed
from .traction import ACTIVE, Rankings, pick, rank, record_snapshot

log = logging.getLogger(__name__)


class Source(Protocol):
    points_used: int

    def discover_new(self, today: date) -> list[dict]: ...
    def discover_traction(self, today: date) -> list[dict]: ...
    def fetch_nodes(self, ids: list[str]) -> dict[str, dict | None]: ...
    def fetch_by_name(self, full_names: list[str]) -> dict[str, dict | None]: ...
    def fetch_details(self, ids: list[str]) -> dict[str, dict]: ...


class ReviewerLike(Protocol):
    model: str
    calls: int
    equivalent_usd: float
    credential_expires_at: str | None

    def review(self, items: list[dict]) -> list[Verdict]: ...


@dataclass
class Paths:
    root: Path  # the repo: config, curation lists, review prompt, templates
    out: Path   # where data/, lists/ and README.md are read and written

    @property
    def data(self) -> Path:
        return self.out / "data"


@dataclass
class Report:
    mode: str
    date: str
    found_new: int = 0
    found_traction: int = 0
    added: int = 0
    refreshed: int = 0
    gone: int = 0
    frozen: int = 0
    reviewed: int = 0
    kept: int = 0
    dropped: int = 0
    waiting: int = 0
    listed: int = 0
    github_points: int = 0
    claude_calls: int = 0
    claude_equivalent_usd: float = 0.0
    review_stop: str | None = None
    review_stop_detail: str | None = None
    credential_expires_at: str | None = None


def run_full(paths: Paths, cfg: Config, source: Source, reviewer: ReviewerLike | None,
             today: date, max_reviews: int) -> Report:
    report = Report("full", today.isoformat())
    store = Store.load(paths.data)
    allow, block = _curation(paths)
    _apply_curation(store, allow, block)

    # 1. Find: both lanes plus allowlisted repos
    found: dict[str, dict] = {}
    lanes_found: dict[str, set[str]] = defaultdict(set)
    allow_names = sorted(entry for entry in allow if "/" in entry)
    batches = [
        ("new", source.discover_new(today)),
        ("traction", source.discover_traction(today)),
        ("allow", [s for s in source.fetch_by_name(allow_names).values() if s] if allow_names else []),
    ]
    for lane, snaps in batches:
        for snap in snaps:
            found[snap["id"]] = snap
            lanes_found[snap["id"]].add(lane)
    report.found_new, report.found_traction = len(batches[0][1]), len(batches[1][1])

    # 2. Place, filter and store
    for repo_id, snap in found.items():
        allowlisted = listed_in(snap["full_name"], allow)
        reason = None if allowlisted else rejection_reason(snap, block, cfg)
        if reason:
            if repo_id in store.repos:
                store.repos[repo_id]["excluded"] = reason
            continue
        place = classify(snap["owner"]["location"])
        lanes = _lanes(snap, place.section, lanes_found[repo_id], allowlisted, cfg, today)
        if not lanes and repo_id not in store.repos:
            continue
        is_new = repo_id not in store.repos
        rec = store.upsert(snap, place, lanes, today)
        rec["allowlisted"] = allowlisted
        rec["excluded"] = None
        if allowlisted and rec["status"] in ("tracked", "rejected"):
            rec["status"] = "pending" if rec["status"] == "tracked" else "listed"
        report.added += is_new

    # 3. Refresh tracked repos the searches didn't return; spot deleted ones
    stale = [
        repo_id for repo_id, rec in store.repos.items()
        if repo_id not in found and rec["status"] in ACTIVE and not rec["frozen"] and not rec["gone"]
    ]
    for repo_id, snap in source.fetch_nodes(stale).items():
        if snap is None:
            store.mark_gone(repo_id, today)
            report.gone += 1
            continue
        store.refresh(snap, today)
        rec = store.repos[repo_id]
        rec["excluded"] = None if rec["allowlisted"] else rejection_reason(snap, block, cfg)
        report.refreshed += 1

    # 4. Freeze repos past the traction window; re-open old rejections that took off
    cutoff = today - timedelta(days=cfg.re_review_after_days)
    for rec in store.repos.values():
        if not rec["frozen"] and age_days(rec["created_at"], today) >= cfg.traction_window_days:
            rec["frozen"] = True
            report.frozen += 1
        if (rec["status"] == "rejected" and not rec["frozen"] and rec["review"]
                and store.stars(rec["id"]) >= cfg.re_review_min_stars
                and to_date(rec["review"]["date"]) <= cutoff):
            rec["status"] = "pending"
        if rec["status"] == "pending":
            rec["review_attempts"] = 0  # unreadable replies get a fresh try each week

    # 5. Weekly star snapshot, then rankings; queue unreviewed repos near the top
    for rec in store.repos.values():
        row = store.stats.get(rec["id"])
        if (rec["status"] in ACTIVE and not rec["frozen"] and not rec["gone"] and row
                and row.get("refreshed") == today.isoformat()):
            record_snapshot(row, today, cfg)
    rankings = rank(store, today, cfg)
    _queue_traction_candidates(store, rankings, cfg)

    # 6. Review, then write everything
    if reviewer:
        run_reviews(store, cfg, source, reviewer, today, max_reviews, report,
                    checkpoint=lambda: store.save(paths.data))
    _finish(paths, cfg, store, today, rankings, report, source)
    return report


def run_catch_up(paths: Paths, cfg: Config, source: Source, reviewer: ReviewerLike | None,
                 today: date, max_reviews: int, include: list[str] | None = None) -> Report:
    """Review repos still waiting (plus any named ones first) and re-render."""
    report = Report("catch-up", today.isoformat())
    store = Store.load(paths.data)
    allow, block = _curation(paths)
    _apply_curation(store, allow, block)
    first = _include(store, source, include or [], cfg, today)
    if reviewer:
        run_reviews(store, cfg, source, reviewer, today, max_reviews, report, first=first,
                    checkpoint=lambda: store.save(paths.data))
    _finish(paths, cfg, store, today, rank(store, today, cfg), report, source)
    return report


def run_render(paths: Paths, cfg: Config, today: date) -> Report:
    report = Report("render-only", today.isoformat())
    store = Store.load(paths.data)
    allow, block = _curation(paths)
    _apply_curation(store, allow, block)
    _finish(paths, cfg, store, today, rank(store, today, cfg), report, None)
    return report


def backlog(paths: Paths, cfg: Config) -> int:
    return len(Store.load(paths.data).review_queue(cfg.review_max_attempts))


def run_reviews(store: Store, cfg: Config, source: Source, reviewer: ReviewerLike, today: date,
                limit: int, report: Report, first: list[dict] | None = None,
                checkpoint: Callable[[], None] | None = None) -> None:
    first = first or []
    first_ids = {rec["id"] for rec in first}
    queue = first + [rec for rec in store.review_queue(cfg.review_max_attempts) if rec["id"] not in first_ids]
    queue = queue[:max(0, limit)]
    if not queue:
        return
    log.info("Reviewing %d repos (%d waiting in total)", len(queue),
             len(store.review_queue(cfg.review_max_attempts)))
    details = source.fetch_details([rec["id"] for rec in queue])
    for batch in chunks(queue, cfg.review_batch_size):
        items = [review_item(rec, store.stats.get(rec["id"], {}), details.get(rec["id"], {}))
                 for rec in batch]
        try:
            verdicts = reviewer.review(items)
        except ReviewStopped as stop:
            report.review_stop, report.review_stop_detail = stop.reason, stop.detail
            log.warning("Reviews stopped for this run: %s", stop)
            break
        except BadReply as err:
            log.warning("Skipping a batch of %d: %s", len(batch), err)
            for rec in batch:
                rec["review_attempts"] += 1
            continue
        by_id = {v.repo_id: v for v in verdicts}
        for rec in batch:
            verdict = by_id.get(rec["id"])
            if verdict is None:
                rec["review_attempts"] += 1
                continue
            rec["review"] = {
                "verdict": "keep" if verdict.keep else "drop",
                "what_it_solves": verdict.what_it_solves,
                "category": verdict.category,
                "reason": verdict.reason,
                "date": today.isoformat(),
                "model": reviewer.model,
            }
            rec["status"] = "listed" if verdict.keep or rec["allowlisted"] else "rejected"
            rec["review_attempts"] = 0
            report.reviewed += 1
            report.kept += verdict.keep
            report.dropped += not verdict.keep
        if checkpoint:
            checkpoint()
    report.claude_calls = reviewer.calls
    report.claude_equivalent_usd = round(reviewer.equivalent_usd, 2)
    report.credential_expires_at = reviewer.credential_expires_at


def review_item(rec: dict, row: dict, details: dict) -> dict:
    """What Claude sees about one repo."""
    owner = rec["owner"]
    return {
        "id": rec["id"],
        "repo": rec["full_name"],
        "description": rec["description"],
        "topics": rec["topics"],
        "language": rec["language"],
        "license": rec["license"],
        "homepage": rec["homepage"],
        "created": rec["created_at"][:10],
        "stars": row.get("stars"),
        "forks": row.get("forks"),
        "owner": {
            "login": owner["login"],
            "type": owner["type"],
            "name": owner.get("name"),
            "location": owner.get("location"),
            "followers": details.get("followers"),
            "bio": details.get("bio"),
            "company": details.get("company"),
            "top_repos": details.get("top_repos", []),
        },
        "readme_excerpt": details.get("readme", ""),
    }


def _lanes(snap: dict, section: str, found_in: set[str], allowlisted: bool, cfg: Config,
           today: date) -> set[str]:
    age = age_days(snap["created_at"], today)
    lanes = set()
    if ("new" in found_in or allowlisted) and age < cfg.new_window_days and (
            allowlisted or snap["stars"] >= cfg.bars[section]):
        lanes.add("new")
    if ("traction" in found_in or allowlisted) and age < cfg.traction_window_days and (
            allowlisted or snap["stars"] >= cfg.traction_min_stars):
        lanes.add("traction")
    return lanes


def _queue_traction_candidates(store: Store, rankings: Rankings, cfg: Config) -> None:
    """Only review traction-pool repos once they'd actually appear in a ranking."""
    for rec in store.repos.values():
        rec["traction_rank"] = None
        if rec["status"] == "pending" and "new" not in rec["lanes"] and not rec["allowlisted"]:
            rec["status"] = "tracked"
    for ranking in (rankings.biggest, rankings.fastest):
        for movers in ranking.values():
            for position, rec in pick(movers, cfg.traction_file_top_n, cfg.traction_lookahead)[1]:
                rec["status"] = "pending"
                if rec["traction_rank"] is None or position < rec["traction_rank"]:
                    rec["traction_rank"] = position


def _include(store: Store, source: Source, names: list[str], cfg: Config, today: date) -> list[dict]:
    """Records for named repos (fetched if new to us), marked for review first."""
    first = []
    missing = [name for name in names if not store.find(name)]
    fetched = source.fetch_by_name(missing) if missing else {}
    for name in names:
        rec = store.find(name)
        if rec is None and fetched.get(name):
            snap = fetched[name]
            place = classify(snap["owner"]["location"])
            rec = store.upsert(snap, place, _lanes(snap, place.section, {"new", "traction"},
                                                   False, cfg, today), today)
        if rec is None:
            log.warning("Can't find %s on GitHub", name)
            continue
        rec["status"] = "pending"
        rec["review_attempts"] = 0
        first.append(rec)
    return first


def _curation(paths: Paths) -> tuple[set[str], set[str]]:
    folder = paths.root / "curation"
    return load_list(folder / "allowlist.txt"), load_list(folder / "blocklist.txt")


def _apply_curation(store: Store, allow: set[str], block: set[str]) -> None:
    for rec in store.repos.values():
        rec["blocked"] = listed_in(rec["full_name"], block)
        rec["allowlisted"] = listed_in(rec["full_name"], allow)
        if rec["allowlisted"] and rec["status"] == "rejected":
            rec["status"] = "listed"


def _finish(paths: Paths, cfg: Config, store: Store, today: date, rankings: Rankings,
            report: Report, source: Source | None) -> None:
    queue = store.review_queue(cfg.review_max_attempts)
    report.waiting = len(queue)
    report.listed = sum(1 for rec in store.repos.values() if is_listed(rec))
    report.github_points = source.points_used if source else 0
    store.save(paths.data)
    renderer = Renderer(store, cfg, today, rankings, paths.root / "templates", existing_weeks(paths.out))
    write_pages(paths.out, renderer.pages())
    _write_json(paths.data / "review-queue.json", {
        "updated": today.isoformat(),
        "waiting": len(queue),
        "next": [
            {"repo": rec["full_name"], "section": rec["section"],
             "why": "new" if "new" in rec["lanes"] else "traction"}
            for rec in queue[:50]
        ],
    })
    with (paths.data / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(asdict(report), sort_keys=True) + "\n")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
