"""Inventory presence (MVP-2.6.1): one definition of a "present" row and the two helpers every writer uses.

A row is present while absent_since IS NULL. A writer that saw a row calls mark_seen; a writer that listed an
(account, provider, type[, criteria]) unit completely calls mark_unseen_absent for the rows it did not see.
Rows are never deleted: a row seen again returns, because mark_seen clears absent_since."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from agenticops.models import CloudResource

PRESENT = CloudResource.absent_since.is_(None)


HEALTH_REASONS = ("open_issue", "absent", "never_observed", "stale", "no_open_issue")


def health_reason(*, open_issues: int, absent_since: Optional[datetime], scanned_at: Optional[datetime],
                  now: datetime, stale_after: timedelta) -> str:
    """Why a resource's health reads as it does (MVP-2.9.0 N24, the 2.8.0 spec's S7) — the first that applies:
    an open issue is anchored on it; it is gone; it was never observed; it was last observed longer ago than
    `stale_after`; else «no open issue» — which is not «healthy». A time without a zone is UTC."""
    if open_issues > 0:
        return "open_issue"
    if absent_since is not None:
        return "absent"
    if scanned_at is None:
        return "never_observed"
    seen = scanned_at if scanned_at.tzinfo else scanned_at.replace(tzinfo=timezone.utc)
    return "stale" if now - seen > stale_after else "no_open_issue"


def mark_seen(row: CloudResource, now: datetime) -> None:
    row.scanned_at, row.absent_since = now, None


def mark_unseen_absent(session, *, account_id: int, provider: str, resource_type: str, seen, now: datetime,
                       criteria: Iterable = ()) -> int:
    """absent_since = now on every present row of this account / provider / type that matches criteria and
    whose resource_id is not in seen. Compares in Python (seen can be large). Never deletes; returns the count."""
    q = session.query(CloudResource).filter(
        CloudResource.account_id == account_id, CloudResource.provider == provider,
        CloudResource.resource_type == resource_type, PRESENT, *criteria)
    marked = 0
    for row in q:
        if row.resource_id not in seen:
            row.absent_since = now
            marked += 1
    return marked
