"""Fast-frequency security incremental poll job (SecurityIncrementalPoll).

Cursor-based GuardDuty / SecurityHub / CloudTrail high-risk-event polling.
Every source is fail-soft: on error the source is skipped for this round and
its cursor is NOT advanced (retry next round, no data loss). All AWS calls go
through the provider layer for the target account — never ambient.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_BACKFILL_HOURS = 24  # first run: bounded backfill window


def _get_cursor(session, account: str, source: str, region: str) -> str:
    """Stored cursor, or now-24h ISO on first run (bounded backfill)."""
    from agenticops.models import SecurityPollCursor
    row = (session.query(SecurityPollCursor)
           .filter_by(account_id=account, source=source, region=region).first())
    if row and row.cursor:
        return row.cursor
    return (datetime.now(timezone.utc) - timedelta(hours=_BACKFILL_HOURS)).isoformat()


def _set_cursor(session, account: str, source: str, region: str, value: str) -> None:
    from agenticops.models import SecurityPollCursor
    row = (session.query(SecurityPollCursor)
           .filter_by(account_id=account, source=source, region=region).first())
    if row:
        row.cursor = value
    else:
        session.add(SecurityPollCursor(
            account_id=account, source=source, region=region, cursor=value))


def run_incremental_poll() -> int:
    """Return the number of new findings emitted. Filled in by Task 4.5."""
    return 0
