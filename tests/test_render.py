import dataclasses
from datetime import date

from radar.locations import Place
from radar.render import Renderer, md_text, slug, write_pages
from radar.store import Store
from radar.traction import rank

from helpers import ROOT, make_snap

TODAY = date(2026, 11, 16)


def listed_store(count=1, **snap_args):
    store = Store()
    for i in range(count):
        snap = make_snap(f"R_{i}", f"acme/tool{i}", **snap_args)
        rec = store.upsert(snap, Place("sf-bay-area", "CA"), {"new"}, TODAY)
        rec["status"] = "listed"
        rec["review"] = {"verdict": "keep", "what_it_solves": "Speeds up | builds",
                         "category": "Developer Tools", "reason": "", "date": "2026-11-16",
                         "model": "m"}
    return store


def renderer(store, cfg):
    return Renderer(store, cfg, TODAY, rank(store, TODAY, cfg), ROOT / "templates", [])


def test_md_text_escapes_markdown_and_html():
    assert md_text("a|b <script>*x*") == r"a\|b \<script\>\*x\*"
    assert md_text("1. starts like a list") == r"1\. starts like a list"
    assert md_text("x" * 20, 10) == "x" * 9 + "…"
    assert md_text("line\nbreak") == "line break"


def test_slug_matches_github_anchors():
    assert slug("AI & ML") == "ai--ml"
    assert slug("Developer Tools") == "developer-tools"


def test_card_shows_every_field(cfg):
    store = listed_store(location="San Francisco, CA", description="Fast <b>builds</b>")
    card = renderer(store, cfg).card(store.repos["R_0"], 3)
    assert card.startswith("### [acme/tool0](https://github.com/acme/tool0)")
    assert "**What it solves:** Speeds up \\| builds · `Developer Tools`" in card
    assert "> Fast \\<b\\>builds\\</b\\>" in card
    assert "`Python` · ★ 100 · 5 forks · MIT · created 2026-11-10 · last push 2026-11-15\\" in card
    assert card.endswith("by **acme** (org) · 📍 San Francisco, CA")


def test_license_wording(cfg):
    store = listed_store(license=None)
    assert "· no license ·" in renderer(store, cfg).card(store.repos["R_0"], 3)
    store = listed_store(license="Other")
    assert "· other license ·" in renderer(store, cfg).card(store.repos["R_0"], 3)


def test_pages_include_readme_month_sections_and_week(cfg):
    pages = renderer(listed_store(), cfg).pages()
    assert "README.md" in pages
    assert "lists/new/2026-11/sf-bay-area.md" in pages
    assert "lists/new/2026-11/outside-us.md" in pages
    assert "lists/traction/2026-W47.md" in pages
    assert "acme/tool0" in pages["lists/new/2026-11/sf-bay-area.md"]
    assert "[Developer Tools](#developer-tools) (1)" in pages["lists/new/2026-11/sf-bay-area.md"]
    readme = pages["README.md"]
    assert "acme/tool0" in readme  # new this week
    assert "written by AI" in readme
    assert "$" not in readme  # every template value filled in


def test_large_sections_split_into_parts(cfg, tmp_path):
    small = dataclasses.replace(cfg, max_file_bytes=2000)
    pages = renderer(listed_store(12), small).month_pages("2026-11")
    parts = sorted(name for name in pages if name.startswith("sf-bay-area"))
    assert len(parts) > 1 and "sf-bay-area-part2.md" in parts
    assert "(part 1 of" in pages["sf-bay-area.md"]
    assert all(f"acme/tool{i}" in "".join(pages.values()) for i in range(12))

    # A later run with fewer cards removes the leftover part files
    stale = tmp_path / "lists" / "new" / "2026-11" / "sf-bay-area-part9.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")
    write_pages(tmp_path, {f"lists/new/2026-11/{name}": text for name, text in pages.items()})
    assert not stale.exists()
    assert (tmp_path / "lists" / "new" / "2026-11" / "sf-bay-area-part2.md").exists()


def test_hidden_repos_are_not_listed(cfg):
    store = listed_store(2)
    store.repos["R_0"]["gone"] = "2026-11-16"
    store.repos["R_1"]["blocked"] = True
    pages = renderer(store, cfg).pages()
    assert "acme/tool" not in pages["lists/new/2026-11/sf-bay-area.md"]
