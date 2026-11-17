"""Load config.toml into a typed, read-only settings object."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .common import SECTIONS


@dataclass(frozen=True)
class Config:
    repo: str
    new_window_days: int
    new_search_min_stars: int
    traction_window_days: int
    traction_min_stars: int
    bars: dict[str, int]
    star_farm_owner_age_days: int
    star_farm_max_push_hours: int
    review_model: str
    review_effort: str
    review_batch_size: int
    review_max_per_run: int
    readme_chars: int
    re_review_after_days: int
    re_review_min_stars: int
    review_max_attempts: int
    snapshots_kept: int
    min_days_between_snapshots: int
    fastest_min_gain: int
    traction_file_top_n: int
    traction_readme_top_n: int
    traction_lookahead: int
    readme_new_top_n: int
    readme_new_days: int
    max_file_bytes: int
    description_max_chars: int


def load_config(path: Path) -> Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    bars = {section: int(raw["bars"][section]) for section in SECTIONS}
    discovery, rules, review = raw["discovery"], raw["rules"], raw["review"]
    traction, readme, render = raw["traction"], raw["readme"], raw["render"]
    return Config(
        repo=raw["site"]["repo"],
        new_window_days=discovery["new_window_days"],
        new_search_min_stars=min(discovery["new_search_min_stars"], *bars.values()),
        traction_window_days=discovery["traction_window_days"],
        traction_min_stars=discovery["traction_min_stars"],
        bars=bars,
        star_farm_owner_age_days=rules["star_farm_owner_age_days"],
        star_farm_max_push_hours=rules["star_farm_max_push_hours"],
        review_model=review["model"],
        review_effort=review["effort"],
        review_batch_size=review["batch_size"],
        review_max_per_run=review["max_per_run"],
        readme_chars=review["readme_chars"],
        re_review_after_days=review["re_review_after_days"],
        re_review_min_stars=review["re_review_min_stars"],
        review_max_attempts=review["max_attempts"],
        snapshots_kept=traction["snapshots_kept"],
        min_days_between_snapshots=traction["min_days_between_snapshots"],
        fastest_min_gain=traction["fastest_min_gain"],
        traction_file_top_n=traction["file_top_n"],
        traction_readme_top_n=traction["readme_top_n"],
        traction_lookahead=traction["lookahead"],
        readme_new_top_n=readme["new_top_n"],
        readme_new_days=readme["new_days"],
        max_file_bytes=render["max_file_bytes"],
        description_max_chars=render["description_max_chars"],
    )
