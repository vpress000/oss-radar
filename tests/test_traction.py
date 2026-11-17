from datetime import date

from radar.locations import Place
from radar.store import Store
from radar.traction import pick, rank, record_snapshot, weekly_gain

from helpers import make_snap

TODAY = date(2026, 11, 16)


def test_snapshot_same_week_replaces_and_old_ones_roll_off(cfg):
    row = {"stars": 10, "snapshots": []}
    record_snapshot(row, date(2026, 11, 2), cfg)
    row["stars"] = 20
    record_snapshot(row, date(2026, 11, 4), cfg)  # same week: replaces
    assert row["snapshots"] == [["2026-11-04", 20]]
    for week in range(20):
        row["stars"] = week
        record_snapshot(row, date(2026, 11, 9) + (date(2026, 11, 16) - date(2026, 11, 9)) * week, cfg)
    assert len(row["snapshots"]) == cfg.snapshots_kept


def test_weekly_gain_and_missed_week(cfg):
    assert weekly_gain({"snapshots": [["2026-11-09", 100]]}, cfg) is None
    assert weekly_gain({"snapshots": [["2026-11-09", 100], ["2026-11-16", 400]]}, cfg) == (300, 100)
    # A skipped week: 14 days of growth scaled back to one week
    assert weekly_gain({"snapshots": [["2026-11-02", 100], ["2026-11-16", 500]]}, cfg) == (200, 100)


def store_with(*specs):
    """specs: (id, section, status, stars last week, stars now)"""
    store = Store()
    for repo_id, section, status, before, now in specs:
        snap = make_snap(repo_id, f"o/{repo_id}", stars=now, created="2026-09-01T00:00:00Z")
        rec = store.upsert(snap, Place(section), {"traction"}, TODAY)
        rec["status"] = status
        store.stats[repo_id]["snapshots"] = [["2026-11-09", before], ["2026-11-16", now]]
    return store


def test_rank_orders_gains_and_growth(cfg):
    store = store_with(
        ("A", "rest-of-us", "listed", 100_000, 110_000),  # +10,000 (+10%)
        ("B", "rest-of-us", "listed", 300, 900),          # +600 (+200%)
        ("C", "rest-of-us", "listed", 1000, 1050),        # +50: too small for fastest
        ("D", "outside-us", "listed", 10, 20),
        ("E", "rest-of-us", "rejected", 10, 99_999),      # rejected: never ranked
    )
    rankings = rank(store, TODAY, cfg)
    assert not rankings.week_one
    assert [m.rec["id"] for m in rankings.biggest["rest-of-us"]] == ["A", "B", "C"]
    assert [m.rec["id"] for m in rankings.fastest["rest-of-us"]] == ["B", "A"]
    assert rankings.biggest["sf-bay-area"] == []


def test_first_week_ranks_by_stars_per_day(cfg):
    store = Store()
    for repo_id, created, stars in (("A", "2026-11-06T00:00:00Z", 1000), ("B", "2026-05-01T00:00:00Z", 5000)):
        snap = make_snap(repo_id, f"o/{repo_id}", stars=stars, created=created)
        store.upsert(snap, Place("rest-of-us"), {"traction"}, TODAY)["status"] = "listed"
        store.stats[repo_id]["snapshots"] = [["2026-11-16", stars]]
    rankings = rank(store, TODAY, cfg)
    assert rankings.week_one
    assert [m.rec["id"] for m in rankings.biggest["rest-of-us"]] == ["A", "B"]


def test_pick_shows_listed_and_queues_unreviewed_near_the_top(cfg):
    store = store_with(
        ("A", "rest-of-us", "tracked", 0, 900),
        ("B", "rest-of-us", "listed", 0, 800),
        ("C", "rest-of-us", "tracked", 0, 700),
    )
    movers = rank(store, TODAY, cfg).biggest["rest-of-us"]
    shown, to_review = pick(movers, top_n=5, lookahead=2)
    assert [m.rec["id"] for m in shown] == ["B"]
    assert [(pos, rec["id"]) for pos, rec in to_review] == [(0, "A")]
