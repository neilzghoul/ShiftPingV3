"""Week date helpers (Israel week: Sunday–Saturday)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import config


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def week_start(d: date | None = None) -> date:
    """Return Sunday of the week containing *d*."""
    if d is None:
        d = now_local().date()
    # Python weekday: Mon=0 … Sun=6 → Sunday-based offset
    return d - timedelta(days=(d.weekday() + 1) % 7)


def week_id(d: date | None = None) -> str:
    """ISO-like week id: YYYY-Www based on Sunday week start."""
    start = week_start(d)
    # Use ISO year of the Thursday of that week for stability
    thursday = start + timedelta(days=4)
    iso_year, iso_week, _ = thursday.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def week_dates(week: str | None = None) -> list[date]:
    """Return 7 dates (Sun–Sat) for a week id or current week."""
    if week:
        # Parse YYYY-Www
        year_str, week_str = week.split("-W")
        year = int(year_str)
        week_num = int(week_str)
        # Find Thursday of ISO week, then back to Sunday
        jan4 = date(year, 1, 4)
        start_iso = jan4 - timedelta(days=jan4.isoweekday() - 1)
        thursday = start_iso + timedelta(weeks=week_num - 1, days=3)
        start = week_start(thursday)
    else:
        start = week_start()
    return [start + timedelta(days=i) for i in range(7)]


def next_week_id() -> str:
    return week_id(now_local().date() + timedelta(days=7))


def format_date_he(d: date) -> str:
    return d.strftime("%d/%m/%Y")
