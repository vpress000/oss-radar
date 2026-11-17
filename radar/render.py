"""Write the Markdown pages: README dashboard, monthly section files, weekly traction file."""

from __future__ import annotations

import re
import string
from datetime import date, timedelta
from pathlib import Path

from .common import CATEGORIES, SECTION_TITLES, SECTIONS, iso_week, to_date
from .config import Config
from .store import Store, is_listed
from .traction import Mover, Rankings, pick, weekly_gain

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+!|~])")


def md_text(value: object, limit: int | None = None) -> str:
    """Untrusted text on one line, with Markdown and HTML characters escaped."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    text = _MD_SPECIAL.sub(r"\\\1", text)
    return re.sub(r"^(\d+)\.", r"\1\\.", text).replace("\n", " ")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def month_title(month: str) -> str:
    return date.fromisoformat(month + "-01").strftime("%B %Y")


class Renderer:
    def __init__(self, store: Store, cfg: Config, today: date, rankings: Rankings,
                 templates: Path, existing_weeks: list[str]):
        self.store = store
        self.cfg = cfg
        self.today = today
        self.rankings = rankings
        self.templates = templates
        self.week = iso_week(today)
        self.weeks = sorted(set(existing_weeks) | {self.week}, reverse=True)
        self.shown = self._shown()

    # --- shared pieces ---------------------------------------------------------------------

    def _shown(self) -> dict[str, dict[str, list[Mover]]]:
        """Reviewed repos to show per section, for each ranking."""
        shown: dict[str, dict[str, list[Mover]]] = {}
        for section in SECTIONS:
            shown[section] = {
                "biggest": pick(self.rankings.biggest[section], self.cfg.traction_file_top_n,
                                self.cfg.traction_lookahead)[0],
                "fastest": pick(self.rankings.fastest[section], self.cfg.traction_file_top_n,
                                self.cfg.traction_lookahead)[0],
            }
        return shown

    def card(self, rec: dict, level: int, mover: Mover | None = None, growth: bool = False) -> str:
        row = self.store.stats.get(rec["id"], {})
        review = rec.get("review") or {}
        lines = [f"{'#' * level} [{rec['full_name']}]({rec['url']})"]
        what = []
        if review.get("what_it_solves"):
            what.append(f"**What it solves:** {md_text(review['what_it_solves'])}")
        if review.get("category"):
            what.append(f"`{review['category']}`")
        if what:
            lines.append(" · ".join(what))
        if rec.get("description"):
            lines += ["", "> " + md_text(rec["description"], self.cfg.description_max_chars)]
        lines.append("")

        gain = mover.gain if mover else None
        if gain is None and not mover:
            weekly = weekly_gain(row, self.cfg) if row else None
            gain = weekly[0] if weekly else None
        stars = f"★ {row.get('stars', 0):,}"
        if gain:
            extra = f"+{gain:,} this week"
            if growth and mover and mover.growth is not None:
                extra += f", +{mover.growth:.0%}"
            stars += f" ({extra})"
        details = [f"`{md_text(rec['language'])}`"] if rec.get("language") else []
        license_text = {None: "no license", "Other": "other license"}.get(rec.get("license"))
        details += [
            stars,
            f"{row.get('forks', 0):,} forks",
            license_text or md_text(rec["license"]),
            f"created {rec['created_at'][:10]}",
            f"last push {str(row.get('pushed_at') or rec['created_at'])[:10]}",
        ]
        lines.append(" · ".join(details) + "\\")
        lines.append(self._owner(rec))
        return "\n".join(lines)

    @staticmethod
    def _owner(rec: dict) -> str:
        owner = rec["owner"]
        who = f"by **{md_text(owner['login'])}**"
        extra = []
        if owner.get("name") and owner["name"] != owner["login"]:
            extra.append(md_text(owner["name"], 60))
        if owner.get("type") == "org":
            extra.append("org")
        if extra:
            who += f" ({' · '.join(extra)})"
        if owner.get("location"):
            who += f" · 📍 {md_text(owner['location'], 80)}"
        return who

    def _template(self, name: str) -> str:
        path = self.templates / name
        if not path.exists():
            return ""
        values = {
            "repo": self.cfg.repo,
            "new_window_days": self.cfg.new_window_days,
            "bar_us": self.cfg.bars["rest-of-us"],
            "bar_other": self.cfg.bars["outside-us"],
            "traction_min_stars": f"{self.cfg.traction_min_stars:,}",
            "traction_months": round(self.cfg.traction_window_days / 30.4),
            "fastest_min_gain": self.cfg.fastest_min_gain,
            "max_reviews": self.cfg.review_max_per_run,
        }
        return string.Template(path.read_text(encoding="utf-8")).safe_substitute(values).strip()

    def _months(self) -> list[str]:
        months = {
            rec["first_seen"][:7] for rec in self.store.repos.values()
            if is_listed(rec) and "new" in rec["lanes"]
        }
        months.add(self.today.isoformat()[:7])
        return sorted(months, reverse=True)

    # --- pages -----------------------------------------------------------------------------

    def pages(self) -> dict[str, str]:
        """Every page to write, keyed by path relative to the output folder."""
        pages = {"README.md": self.readme()}
        for month in self._months():
            for name, text in self.month_pages(month).items():
                pages[f"lists/new/{month}/{name}"] = text
        pages[f"lists/traction/{self.week}.md"] = self.traction_page()
        return pages

    def month_pages(self, month: str) -> dict[str, str]:
        pages: dict[str, str] = {}
        for section in SECTIONS:
            recs = [
                rec for rec in self.store.repos.values()
                if is_listed(rec) and "new" in rec["lanes"] and rec["first_seen"].startswith(month)
                and rec["section"] == section
            ]
            pages.update(self._section_pages(month, section, recs))
        return pages

    def _section_pages(self, month: str, section: str, recs: list[dict]) -> dict[str, str]:
        blocks: list[tuple[str, str]] = []
        for category in CATEGORIES:
            members = sorted(
                (r for r in recs if _category(r) == category),
                key=lambda r: (-self.store.stars(r["id"]), r["full_name"].lower()),
            )
            blocks += [(category, self.card(rec, 3)) for rec in members]
        parts = _split(blocks, self.cfg.max_file_bytes)
        names = [f"{section}.md"] + [f"{section}-part{n}.md" for n in range(2, len(parts) + 1)]
        sections_nav = " · ".join(
            f"[{SECTION_TITLES[s]}]({s}.md)" if s != section else f"**{SECTION_TITLES[s]}**"
            for s in SECTIONS
        )
        pages = {}
        for index, part in enumerate(parts):
            title = f"# New & notable · {SECTION_TITLES[section]} · {month_title(month)}"
            if len(parts) > 1:
                title += f" (part {index + 1} of {len(parts)})"
            lines = [
                title, "",
                f"[← Back to the README](../../../README.md) · Sections: {sections_nav}", "",
                f"{len(recs):,} repos first found this month, each created no more than "
                f"{self.cfg.new_window_days} days earlier. Grouped by category and sorted by stars; "
                f"stars as of {self.today.isoformat()}.",
                "",
            ]
            if len(parts) > 1:
                lines += ["Parts: " + " · ".join(
                    f"[{n + 1}]({names[n]})" if n != index else f"**{n + 1}**"
                    for n in range(len(parts))
                ), ""]
            if not recs:
                lines.append("_Nothing listed yet._")
            categories = [c for c in CATEGORIES if any(cat == c for cat, _ in part)]
            if categories:
                lines += ["**Categories:** " + " · ".join(
                    f"[{c}](#{slug(c)}) ({sum(1 for cat, _ in part if cat == c)})" for c in categories
                ), ""]
            for category in categories:
                lines += [f"## {category}", ""]
                lines += [text + "\n" for cat, text in part if cat == category]
            pages[names[index]] = "\n".join(lines).rstrip() + "\n"
        return pages

    def traction_page(self) -> str:
        start = self.today - timedelta(days=self.today.weekday())
        lines = [
            f"# Gaining traction · {self.week}", "",
            "[← Back to the README](../../README.md)", "",
            f"Repos up to {round(self.cfg.traction_window_days / 30.4)} months old, per section. "
            f"Week of {start.isoformat()}; stars as of {self.today.isoformat()}.", "",
        ]
        if self.rankings.week_one:
            lines += [
                "> **First week:** there are no earlier star counts to compare with yet, so repos "
                "are ranked by stars per day since they were created. Weekly gains start next week.",
                "",
            ]
        for section in SECTIONS:
            lines += [f"## {SECTION_TITLES[section]}", ""]
            lines += self._ranking_lines(section, self.cfg.traction_file_top_n, level=4)
        return "\n".join(lines).rstrip() + "\n"

    def _ranking_lines(self, section: str, top_n: int, level: int) -> list[str]:
        shown = self.shown[section]
        heading = "#" * (level - 1)
        lines: list[str] = []
        if self.rankings.week_one:
            groups = [("Most stars per day since creation", shown["biggest"], False)]
        else:
            groups = [
                ("Biggest gains", shown["biggest"], False),
                (f"Fastest growing (at least +{self.cfg.fastest_min_gain} stars)", shown["fastest"], True),
            ]
        for label, movers, growth in groups:
            lines += [f"{heading} {label}", ""]
            if not movers:
                lines += ["_Nothing to show yet._", ""]
            for mover in movers[:top_n]:
                lines += [self.card(mover.rec, level, mover, growth), ""]
        return lines

    def readme(self) -> str:
        repos = self.store.repos.values()
        listed = sum(1 for r in repos if is_listed(r))
        tracked = sum(1 for r in repos if not r["frozen"] and not r["gone"] and r["status"] != "rejected")
        waiting = len(self.store.review_queue(self.cfg.review_max_attempts))
        lines = [self._template("readme_header.md"), ""]
        lines += [
            f"_Updated {self.today.isoformat()} · {listed:,} repos listed · {tracked:,} tracked · "
            f"{waiting:,} waiting for review_", "",
        ]
        if waiting:
            lines += [
                f"> ⏳ **{waiting:,} repos are waiting for review.** Claude checks up to "
                f"{self.cfg.review_max_per_run} a night, and each repo appears here once it passes.",
                "",
            ]

        lines += ["## 🔥 Gaining traction this week", ""]
        if self.rankings.week_one:
            lines += ["_First week: ranked by stars per day since creation; weekly gains start next week._", ""]
        for section in SECTIONS:
            lines += [f"### {SECTION_TITLES[section]}", ""]
            lines += self._ranking_lines(section, self.cfg.traction_readme_top_n, level=5)
        lines += [f"→ [Full ranking for {self.week}](lists/traction/{self.week}.md)", ""]

        month = self.today.isoformat()[:7]
        since = self.today - timedelta(days=self.cfg.readme_new_days)
        lines += ["## 🆕 New & notable this week", ""]
        for section in SECTIONS:
            lines += [f"### {SECTION_TITLES[section]}", ""]
            fresh = sorted(
                (r for r in repos if is_listed(r) and "new" in r["lanes"]
                 and r["section"] == section and to_date(r["first_seen"]) > since),
                key=lambda r: (-self.store.stars(r["id"]), r["full_name"].lower()),
            )[: self.cfg.readme_new_top_n]
            if not fresh:
                lines += ["_Nothing new this week yet._", ""]
            lines += [part for rec in fresh for part in (self.card(rec, 4), "")]
            lines += [f"→ [All {SECTION_TITLES[section]} repos found in {month_title(month)}]"
                      f"(lists/new/{month}/{section}.md)", ""]

        lines += ["## 📚 Archive", "", "**New & notable by month**", ""]
        for m in self._months():
            links = " · ".join(f"[{SECTION_TITLES[s]}](lists/new/{m}/{s}.md)" for s in SECTIONS)
            lines.append(f"- {month_title(m)}: {links}")
        lines += ["", "**Gaining traction by week**", ""]
        lines.append(" · ".join(f"[{w}](lists/traction/{w}.md)" for w in self.weeks))
        lines += ["", self._template("readme_footer.md")]
        return "\n".join(lines).rstrip() + "\n"


def _category(rec: dict) -> str:
    category = (rec.get("review") or {}).get("category")
    return category if category in CATEGORIES else "Other"


def _split(blocks: list[tuple[str, str]], limit: int) -> list[list[tuple[str, str]]]:
    """Group cards into pages that each stay under `limit` bytes."""
    parts: list[list[tuple[str, str]]] = [[]]
    size = 0
    for category, text in blocks:
        n = len(text.encode("utf-8")) + 2
        if parts[-1] and size + n > limit:
            parts.append([])
            size = 0
        parts[-1].append((category, text))
        size += n
    return parts


def existing_weeks(out: Path) -> list[str]:
    folder = out / "lists" / "traction"
    return sorted(p.stem for p in folder.glob("*-W*.md")) if folder.exists() else []


def write_pages(out: Path, pages: dict[str, str]) -> None:
    """Write pages, and remove leftover part files from sections that got shorter."""
    for relative, text in pages.items():
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    written = {(out / relative).resolve() for relative in pages}
    for relative in {r for r in pages if r.startswith("lists/new/")}:
        folder = (out / relative).parent
        for stale in folder.glob("*-part*.md"):
            if stale.resolve() not in written:
                stale.unlink()
