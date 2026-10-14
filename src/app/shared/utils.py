"""Small helpers shared by repositories and services."""

from datetime import UTC, date, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def today_utc() -> date:
    return utc_now().date()


def start_of_month_utc() -> datetime:
    return utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def like_pattern(search: str) -> str:
    """Build an ILIKE pattern, escaping wildcard characters typed by the user."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
