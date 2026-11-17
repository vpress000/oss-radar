import dataclasses
import json
from datetime import date, timedelta

from radar.pipeline import Paths, backlog, run_catch_up, run_full, run_render
from radar.store import Store

from helpers import FakeReviewer, FakeSource, make_project, make_snap

TODAY = date(2026, 11, 16)


def new_lane():
    return [
        make_snap("R_sf", "bay/tool", stars=60, location="San Francisco, CA"),
        make_snap("R_us", "tex/tool", stars=60, location="Austin, TX"),
        make_snap("R_de_small", "ber/small", stars=100, location="Berlin"),  # under the 250 bar
        make_snap("R_jp", "tok/tool", stars=300, location="Tokyo, Japan"),
        make_snap("R_unknown", "anon/tool", stars=300, location=""),
        make_snap("R_fork", "fork/tool", stars=500, location="SF", is_fork=True),
        make_snap("R_tut", "learn/tutorial", stars=80, location="Seattle, WA"),
    ]


def test_full_run_reviews_lists_and_renders(tmp_path, cfg):
    project = make_project(tmp_path)
    paths = Paths(project, project)
    reviewer = FakeReviewer(drop={"learn/tutorial"})
    report = run_full(paths, cfg, FakeSource(new=new_lane()), reviewer, TODAY, 300)

    store = Store.load(paths.data)
    assert set(store.repos) == {"R_sf", "R_us", "R_jp", "R_unknown", "R_tut"}
    assert store.repos["R_tut"]["status"] == "rejected"
    assert report.added == 5 and report.kept == 4 and report.dropped == 1 and report.waiting == 0
    # SF Bay Area first, then the rest of the US (by stars), then everyone else
    assert reviewer.seen[:3] == ["bay/tool", "learn/tutorial", "tex/tool"]

    month = project / "lists" / "new" / "2026-11"
    assert "bay/tool" in (month / "sf-bay-area.md").read_text(encoding="utf-8")
    assert "tex/tool" in (month / "rest-of-us.md").read_text(encoding="utf-8")
    assert "tok/tool" in (month / "outside-us.md").read_text(encoding="utf-8")
    assert "anon/tool" in (month / "location-unknown.md").read_text(encoding="utf-8")
    assert "learn/tutorial" not in (month / "rest-of-us.md").read_text(encoding="utf-8")
    readme = (project / "README.md").read_text(encoding="utf-8")
    assert "bay/tool" in readme and "First week" in readme
    assert (project / "lists" / "traction" / "2026-W47.md").exists()
    runs = (paths.data / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(runs[-1])["kept"] == 4


def test_second_week_adds_no_duplicates_and_measures_gains(tmp_path, cfg):
    project = make_project(tmp_path)
    paths = Paths(project, project)
    run_full(paths, cfg, FakeSource(new=new_lane()), FakeReviewer(), TODAY, 300)

    grown = [dict(s, stars=s["stars"] + 100) for s in new_lane()]
    report = run_full(paths, cfg, FakeSource(new=grown), FakeReviewer(), TODAY + timedelta(days=7), 300)
    store = Store.load(paths.data)
    assert report.added == 0
    assert len(store.repos) == 5
    assert store.stats["R_sf"]["snapshots"] == [["2026-11-16", 60], ["2026-11-23", 160]]
    traction = (project / "lists" / "traction" / "2026-W48.md").read_text(encoding="utf-8")
    assert "+100 this week" in traction and "Biggest gains" in traction


def test_deleted_repos_are_marked_gone_and_hidden(tmp_path, cfg):
    project = make_project(tmp_path)
    paths = Paths(project, project)
    run_full(paths, cfg, FakeSource(new=new_lane()), FakeReviewer(), TODAY, 300)
    nodes = {s["id"]: s for s in new_lane() if s["id"] != "R_sf"}
    report = run_full(paths, cfg, FakeSource(nodes=nodes), FakeReviewer(), TODAY + timedelta(days=7), 300)
    store = Store.load(paths.data)
    assert report.gone == 1 and store.repos["R_sf"]["gone"] == "2026-11-23"
    month = project / "lists" / "new" / "2026-11" / "sf-bay-area.md"
    assert "bay/tool" not in month.read_text(encoding="utf-8")


def test_usage_limit_leaves_the_rest_waiting(tmp_path, cfg):
    project = make_project(tmp_path)
    paths = Paths(project, project)
    small_batches = dataclasses.replace(cfg, review_batch_size=1)
    report = run_full(paths, small_batches, FakeSource(new=new_lane()), FakeReviewer(stop_after=2), TODAY, 300)
    assert report.review_stop == "usage_limit"
    assert report.reviewed == 2 and report.waiting == 3
    assert backlog(paths, cfg) == 3

    # A catch-up run picks up where it stopped
    report = run_catch_up(paths, cfg, FakeSource(), FakeReviewer(), TODAY + timedelta(days=1), 300)
    assert report.reviewed == 3 and report.waiting == 0


def test_review_cap_per_run(tmp_path, cfg):
    project = make_project(tmp_path)
    paths = Paths(project, project)
    report = run_full(paths, cfg, FakeSource(new=new_lane()), FakeReviewer(), TODAY, 2)
    assert report.reviewed == 2 and report.waiting == 3


def test_traction_pool_is_reviewed_only_near_the_top(tmp_path, cfg):
    project = make_project(tmp_path)
    paths = Paths(project, project)
    pool = [make_snap(f"T_{i}", f"big/r{i}", stars=1000 + i * 10, created="2026-06-01T00:00:00Z",
                      location="Austin, TX") for i in range(60)]
    report = run_full(paths, cfg, FakeSource(traction=pool), FakeReviewer(), TODAY, 300)
    store = Store.load(paths.data)
    statuses = [rec["status"] for rec in store.repos.values()]
    assert statuses.count("tracked") == 60 - report.reviewed
    assert report.reviewed <= cfg.traction_lookahead


def test_blocklist_and_allowlist(tmp_path, cfg):
    project = make_project(tmp_path, allow="ber/small\n", block="tok\n")
    paths = Paths(project, project)
    run_full(paths, cfg, FakeSource(new=new_lane()), FakeReviewer(drop={"ber/small"}), TODAY, 300)
    store = Store.load(paths.data)
    assert store.repos["R_de_small"]["status"] == "listed"  # allowlisted: under the bar, dropped, still listed
    assert "R_jp" not in store.repos  # blocked owner is never stored
    outside = (project / "lists" / "new" / "2026-11" / "outside-us.md").read_text(encoding="utf-8")
    assert "ber/small" in outside and "tok/tool" not in outside


def test_catch_up_include_reviews_named_repos_first(tmp_path, cfg):
    project = make_project(tmp_path)
    paths = Paths(project, project)
    run_full(paths, cfg, FakeSource(new=new_lane()), None, TODAY, 300)  # discover only
    orca = make_snap("R_orca", "stablyai/orca", stars=126_000, created="2026-03-17T00:00:00Z",
                     location="United States of America")
    reviewer = FakeReviewer()
    report = run_catch_up(paths, cfg, FakeSource(by_name={"stablyai/orca": orca}), reviewer,
                          TODAY, 2, include=["stablyai/orca"])
    assert reviewer.seen == ["stablyai/orca", "bay/tool"]
    assert report.reviewed == 2
    assert Store.load(paths.data).repos["R_orca"]["status"] == "listed"


def test_render_only_rewrites_pages(tmp_path, cfg):
    project = make_project(tmp_path)
    paths = Paths(project, project)
    run_full(paths, cfg, FakeSource(new=new_lane()), FakeReviewer(), TODAY, 300)
    (project / "README.md").unlink()
    run_render(paths, cfg, TODAY)
    assert "bay/tool" in (project / "README.md").read_text(encoding="utf-8")
