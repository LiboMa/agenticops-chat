"""Time utility functions."""

from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def as_utc(ts: Optional[datetime]) -> Optional[datetime]:
    """The same moment as an aware UTC time: a naive one is taken as UTC (the database columns are naive UTC);
    None stays None."""
    if ts is None:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def iso_z(ts: Optional[datetime], timespec: str = "auto") -> Optional[str]:
    """ISO 8601 in UTC with a «Z» — `2026-11-26T09:30:05.123456Z` (`timespec` as `datetime.isoformat`); None stays
    None. What the API answers for a time."""
    ts = as_utc(ts)
    return None if ts is None else ts.replace(tzinfo=None).isoformat(timespec=timespec) + "Z"
