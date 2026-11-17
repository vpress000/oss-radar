from radar.rules import listed_in, load_list, looks_star_farmed, rejection_reason

from helpers import make_snap


def test_clean_repo_passes(cfg):
    assert rejection_reason(make_snap(), set(), cfg) is None


def test_forks_archives_mirrors_templates_are_dropped(cfg):
    for flag in ("is_fork", "is_archived", "is_mirror", "is_template"):
        assert rejection_reason(make_snap(**{flag: True}), set(), cfg)


def test_profile_and_pages_repos_are_dropped(cfg):
    assert rejection_reason(make_snap(full_name="jdoe/jdoe"), set(), cfg) == "profile repo"
    assert rejection_reason(make_snap(full_name="jdoe/jdoe.github.io"), set(), cfg) == "GitHub Pages site"


def test_blocklist_matches_repo_or_owner(cfg):
    snap = make_snap(full_name="Acme/Tool")
    assert rejection_reason(snap, {"acme/tool"}, cfg) == "blocklist"
    assert rejection_reason(snap, {"acme"}, cfg) == "blocklist"
    assert rejection_reason(snap, {"acme/other"}, cfg) is None


def test_star_farm_needs_new_owner_no_activity_and_no_forks(cfg):
    farmed = make_snap(forks=0, created="2026-11-10T00:00:00Z", pushed="2026-11-10T02:00:00Z",
                       owner_created="2026-11-09T00:00:00Z")
    assert looks_star_farmed(farmed, cfg)
    assert not looks_star_farmed({**farmed, "forks": 3}, cfg)
    assert not looks_star_farmed({**farmed, "pushed_at": "2026-11-14T00:00:00Z"}, cfg)
    assert not looks_star_farmed(
        {**farmed, "owner": {**farmed["owner"], "created_at": "2024-01-01T00:00:00Z"}}, cfg)


def test_load_list_ignores_comments_and_urls(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# comment\nAcme/Tool  # trailing\n\nhttps://github.com/Other\n", encoding="utf-8")
    assert load_list(path) == {"acme/tool", "other"}
    assert load_list(tmp_path / "missing.txt") == set()
    assert listed_in("other/x", {"other"})
