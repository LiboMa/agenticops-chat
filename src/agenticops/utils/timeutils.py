"""Timezone-safe UTC helpers.

``datetime.utcnow()`` is deprecated in Python 3.12+.  This module provides
a drop-in replacement that silences the warning while keeping naive-UTC
semantics (required by SQLite / SQLAlchemy without timezone columns).
"""

from datetime import datetime, timezone

__all__ = ["utc_now"]


def utc_now() -> datetime:
    """Return the current UTC time as a **naive** datetime.

    Equivalent to the deprecated ``datetime.utcnow()`` but without the
    deprecation warning.  The result is naive (tzinfo=None) so it stays
    compatible with existing SQLite columns and SQLAlchemy comparisons.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
