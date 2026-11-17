"""Weekly star snapshots and the two traction rankings: Biggest gains and Fastest growing.

GitHub doesn't expose when stars were given, so growth comes from the star counts this tool
records on each weekly run. On the first run there is nothing to compare against, so repos
are ranked by stars per day since creation instead (`week_one`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .common import SECTIONS, age_days
from .config import Config
from .store import Store, hidden

ACTIVE = ("pending", "tracked", "listed")


@dataclass
class Mover:
    rec: dict
    stars: int
    gain: int | None = None       # stars added over the last week
    growth: float | None = None   # that gain as a share of last week's stars
    per_day: float = 0.0          # stars per day since creation


@dataclass
class Rankings:
    biggest: dict[str, list[Mover]]
    fastest: dict[str, list[Mover]]
    week_one: bool


def record_snapshot(row: dict, today: date, cfg: Config) -> None:
    """Add this run's star count; a second run in the same week replaces that week's count."""
    snaps = row.setdefault("snapshots", [])
    entry = [today.isoformat(), row["stars"]]
    if snaps and (today - date.fromisoformat(snaps[-1][0])).days < cfg.min_days_between_snapshots:
        snaps[-1] = entry
    else:
        snaps.append(entry)
    del snaps[:-cfg.snapshots_kept]


def weekly_gain(row: dict, cfg: Config) -> tuple[int, int] | None:
    """(stars gained per week, stars a week earlier), from the two latest snapshots."""
    snaps = row.get("snapshots") or []
    if len(snaps) < 2:
        return None
    last_day, last_stars = date.fromisoformat(snaps[-1][0]), snaps[-1][1]
    for day, stars in reversed(snaps[:-1]):
        days = (last_day - date.fromisoformat(day)).days
        if days >= cfg.min_days_between_snapshots:
            # If a weekly run was missed, scale the gap back to one week
            return round((last_stars - stars) * 7 / max(days, 7)), stars
    return None


def rank(store: Store, today: date, cfg: Config) -> Rankings:
    movers = []
    for rec in store.repos.values():
        if rec["status"] not in ACTIVE or hidden(rec) or rec["frozen"]:
            continue
        age = age_days(rec["created_at"], today)
        row = store.stats.get(rec["id"])
        if age > cfg.traction_window_days or not row:
            continue
        mover = Mover(rec, row["stars"], per_day=row["stars"] / max(1, age))
        gain = weekly_gain(row, cfg)
        if gain is not None:
            mover.gain, before = gain
            mover.growth = mover.gain / before if before > 0 else None
        movers.append(mover)

    week_one = not any(m.gain is not None for m in movers)
    biggest: dict[str, list[Mover]] = {}
    fastest: dict[str, list[Mover]] = {}
    for section in SECTIONS:
        pool = [m for m in movers if m.rec["section"] == section]
        if week_one:
            biggest[section] = sorted(pool, key=lambda m: (-m.per_day, m.rec["id"]))
            fastest[section] = []
            continue
        biggest[section] = sorted(
            (m for m in pool if m.gain and m.gain > 0), key=lambda m: (-m.gain, m.rec["id"])
        )
        fastest[section] = sorted(
            (m for m in pool if m.gain is not None and m.gain >= cfg.fastest_min_gain
             and m.growth is not None),
            key=lambda m: (-m.growth, m.rec["id"]),
        )
    return Rankings(biggest, fastest, week_one)


def pick(movers: list[Mover], top_n: int, lookahead: int) -> tuple[list[Mover], list[tuple[int, dict]]]:
    """The listed repos to show, plus unreviewed repos near the top that need a review."""
    shown: list[Mover] = []
    to_review: list[tuple[int, dict]] = []
    for position, mover in enumerate(movers):
        if len(shown) >= top_n:
            break
        status = mover.rec["status"]
        if status == "listed":
            shown.append(mover)
        elif position < lookahead and status in ("pending", "tracked"):
            to_review.append((position, mover.rec))
    return shown, to_review
