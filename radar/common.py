"""Constants and small helpers shared across the package."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterator, Sequence, TypeVar

SECTIONS = ("sf-bay-area", "rest-of-us", "outside-us", "location-unknown")
SECTION_TITLES = {
    "sf-bay-area": "SF Bay Area",
    "rest-of-us": "Rest of US",
    "outside-us": "Outside US",
    "location-unknown": "Location unknown",
}
CATEGORIES = (
    "AI & ML",
    "Developer Tools",
    "Infrastructure & DevOps",
    "Data & Databases",
    "Security",
    "Web & Frontend",
    "Mobile & Desktop",
    "Science & Research",
    "Hardware & IoT",
    "Finance & Crypto",
    "Games & Media",
    "Other",
)

T = TypeVar("T")


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_date(value: str) -> date:
    """Date part of an ISO date or timestamp string."""
    return date.fromisoformat(value[:10])


def age_days(created_at: str, today: date) -> int:
    return (today - to_date(created_at)).days


def iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def chunks(items: Sequence[T], size: int) -> Iterator[list[T]]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])
