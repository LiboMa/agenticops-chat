"""The only writer for pull-connector observations (MVP-2.6.1 spec §3.B.2). Deterministic, no LLM.

- entities: upsert into cloud_resources by (account_id, provider, resource_id); scanned_at = now,
  absent_since cleared. The build-written raw_data["unresolved_refs"] survives the overwrite. An existing row
  whose content hash moved gets content_changed_at = now (the RCA evidence reads it; Plan C).
- absent: only for a (scope, kind) the connector listed completely, rows of that kind under the scope that
  were not seen get absent_since = now. Never deletes; a partial kind is never touched, and neither is a row some
  writer touched after this run's listing began (scanned_at >= started_at): the seen set is stale for it.
- signals: each through signal_gate.process_signal (fail-soft per signal).
- one connector_runs row per call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_

from agenticops.connectors.base import CollectResult, Connector, Target
from agenticops.galaxy.hashing import content_hash
from agenticops.models import CloudResource, ConnectorRun, get_db_session
from agenticops.services.inventory import mark_seen, mark_unseen_absent

logger = logging.getLogger(__name__)

SUCCESS_STATUSES = ("complete", "partial")  # a partial run still refreshed every complete kind
_PRESERVED_RAW_KEYS = ("unresolved_refs",)  # written by the Galaxy build (Plan A), not by the connector
_IN_CHUNK = 500


@dataclass
class IngestResult:
    run_id: int
    status: str     # complete | partial | failed
    changed: bool   # structure changed: a row created, absent-flipped, returned, or its content hash moved
    counts: dict    # created / updated / absent / returned / signals / signal_errors


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _hash(rtype: str, rid: str, name: str, tags: dict, raw: dict) -> str:
    return content_hash({"resource_type": rtype, "resource_id": rid, "name": name, "tags": tags, "raw_data": raw})


def in_scope(scope: str):
    """resource_id starts with '<scope>/'. substr, not LIKE: a '_' or '%' in a scope is literal."""
    prefix = f"{scope}/"
    return func.substr(CloudResource.resource_id, 1, len(prefix)) == prefix


def run_status(result: CollectResult) -> str:
    kinds = result.completeness.values()
    if not any(kinds) and not result.entities:
        return "failed"
    if kinds and all(kinds) and not result.errors:
        return "complete"
    return "partial"


def ingest(connector: Connector, target: Target, result: CollectResult, *, trigger: str,
           started_at: Optional[datetime] = None) -> IngestResult:
    now = datetime.now(timezone.utc)
    acct = target.account.id
    status = run_status(result)
    counts = {"created": 0, "updated": 0, "absent": 0, "returned": 0, "signals": 0, "signal_errors": 0}
    per_kind: dict[str, dict] = {}
    for (scope, kind), complete in result.completeness.items():
        if scope == target.scope:
            per_kind[kind] = {"complete": bool(complete), "count": 0}
    changed = False

    obs = {e.resource_id: e for e in result.entities if e.resource_id}  # last one wins on a repeated id
    for e in obs.values():
        per_kind.setdefault(e.resource_type, {"complete": False, "count": 0})["count"] += 1

    with get_db_session() as s:
        ids = list(obs)
        existing: dict[str, CloudResource] = {}
        for i in range(0, len(ids), _IN_CHUNK):
            for row in s.query(CloudResource).filter(
                    CloudResource.account_id == acct, CloudResource.provider == connector.provider,
                    CloudResource.resource_id.in_(ids[i:i + _IN_CHUNK])):
                existing[row.resource_id] = row
        for rid, e in obs.items():
            row = existing.get(rid)
            if row is None:
                s.add(CloudResource(account_id=acct, provider=connector.provider, region=e.region,
                                    resource_type=e.resource_type, resource_id=rid, name=e.name, tags=dict(e.tags),
                                    raw_data=dict(e.raw_data), status=e.status, managed=True, scanned_at=now))
                counts["created"] += 1
                changed = True
                continue
            old_raw = row.raw_data if isinstance(row.raw_data, dict) else {}
            raw = dict(e.raw_data)
            for key in _PRESERVED_RAW_KEYS:
                if key in old_raw and key not in raw:
                    raw[key] = old_raw[key]
            before = _hash(row.resource_type, rid, row.name, row.tags or {}, old_raw)
            after = _hash(e.resource_type, rid, e.name, e.tags, raw)
            if row.absent_since is not None:
                counts["returned"] += 1
                changed = True
            if before != after:
                changed = True
                row.content_changed_at = now
            row.resource_type, row.name, row.region = e.resource_type, e.name, e.region
            row.tags, row.raw_data, row.status = dict(e.tags), raw, e.status
            mark_seen(row, now)
            counts["updated"] += 1

        listed_from = started_at or now
        for (scope, kind), complete in result.completeness.items():
            if not complete or scope != target.scope:
                continue
            marked = mark_unseen_absent(
                s, account_id=acct, provider=connector.provider, resource_type=kind, seen=obs, now=now,
                criteria=(in_scope(target.scope),
                          or_(CloudResource.scanned_at.is_(None), CloudResource.scanned_at < listed_from)))
            counts["absent"] += marked
            if marked > 0:
                changed = True

    for sig in result.signals:
        try:
            from agenticops.services.signal_gate import process_signal

            process_signal(sig)
            counts["signals"] += 1
        except Exception as exc:  # one bad signal must not lose the run record
            counts["signal_errors"] += 1
            logger.warning("connector %s: signal %r failed: %s", connector.name, sig.title, exc)

    with get_db_session() as s:
        run = ConnectorRun(connector=connector.name, account_id=acct, scope=target.scope, trigger=trigger,
                           started_at=started_at or now, finished_at=datetime.now(timezone.utc), status=status,
                           counts=counts, per_kind=per_kind,
                           error="; ".join(result.errors)[:4000] or None)
        s.add(run)
        s.flush()
        run_id = run.id
    return IngestResult(run_id=run_id, status=status, changed=changed, counts=counts)


def last_success_at(session, connector: str, account_id: int, scope: str) -> Optional[datetime]:
    """finished_at (aware UTC) of the newest complete-or-partial run for this target, or None. Plan C's RCA
    recollect reads it to decide whether the cluster data is fresh enough."""
    value = (session.query(func.max(ConnectorRun.finished_at))
             .filter(ConnectorRun.connector == connector, ConnectorRun.account_id == account_id,
                     ConnectorRun.scope == scope, ConnectorRun.status.in_(SUCCESS_STATUSES))
             .scalar())
    return _utc(value)
