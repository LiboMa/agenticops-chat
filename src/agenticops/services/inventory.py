"""Inventory presence (MVP-2.6.1): one definition of a "present" row and the two helpers every writer uses.

A row is present while absent_since IS NULL. A writer that saw a row calls mark_seen; a writer that listed an
(account, provider, type[, criteria]) unit completely calls mark_unseen_absent for the rows it did not see.
Rows are never deleted: a row seen again returns, because mark_seen clears absent_since."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from agenticops.models import CloudResource

PRESENT = CloudResource.absent_since.is_(None)


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
