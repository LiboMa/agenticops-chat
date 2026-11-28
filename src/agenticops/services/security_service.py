"""Security review query layer for /api/security/* (mirrors cost_service's role).

Everything is per account (MVP-2.9.0 N20 — the 2.8.0 spec's S3). A snapshot or a recommendation names its account by
NAME — the platform's account-addressing key at collection time — while a finding (a HealthIssue) holds the
account's primary key. This module maps the two: every row it returns carries `account_id` (cloud_accounts.id;
None when the name matches no account any more) and `account_name`, and every filter takes the primary key — the
value of the top bar's account scope. Times are UTC, written with a trailing Z.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, case, func, or_

from agenticops.models import (
    CloudAccount,
    CloudResource,
    HealthIssue,
    SecurityRecommendation,
    SecuritySnapshot,
    get_db_session,
)
from agenticops.services.listing import like_pattern, ref_number
from agenticops.services.signal_gate import OPEN_ISSUE_STATUSES, SECURITY_DETECTORS
from agenticops.utils.timeutils import as_utc, iso_z

_SECURITY_DETECTORS = SECURITY_DETECTORS

SEVERITIES = ("critical", "high", "medium", "low")              # the list's order: most severe first
REACHABILITY = ("reachable", "undetermined", "not_reachable")
FINDING_STATUSES = ("open", "all")
TREND_DAYS = (7, 30, 90)


def partition_of(regions, credentials) -> str:
    """The cloud partition an account lives in — `aws`, `aws-cn` or `aws-us-gov` — from what its row states: the
    role it is reached through, else its regions."""
    arn = str((credentials or {}).get("role_arn") or "") if isinstance(credentials, dict) else ""
    names = [str(r) for r in (regions or [])]
    if arn.startswith("arn:aws-cn:") or any(r.startswith("cn-") for r in names):
        return "aws-cn"
    if arn.startswith("arn:aws-us-gov:") or any(r.startswith("us-gov-") for r in names):
        return "aws-us-gov"
    return "aws"


class _Accounts:
    """cloud_accounts by name and by primary key (read once per request)."""

    def __init__(self, session):
        rows = session.query(CloudAccount.id, CloudAccount.name, CloudAccount.regions, CloudAccount.credentials).all()
        self._by_name = {r.name: r for r in rows}
        self._by_id = {r.id: r for r in rows}

    def id_of(self, name: str) -> Optional[int]:
        row = self._by_name.get(name)
        return row.id if row else None

    def name_of(self, pk: Optional[int]) -> Optional[str]:
        row = self._by_id.get(pk)
        return row.name if row else None

    def partition(self, name: str) -> Optional[str]:
        row = self._by_name.get(name)
        return partition_of(row.regions, row.credentials) if row else None


def _latest_snapshots(session) -> list[SecuritySnapshot]:
    """Newest snapshot per account (by its time; two at the same instant → the later row)."""
    newest = (session.query(SecuritySnapshot.account_id, func.max(SecuritySnapshot.created_at).label("at"))
              .group_by(SecuritySnapshot.account_id).subquery())
    rows = (session.query(SecuritySnapshot)
            .join(newest, and_(SecuritySnapshot.account_id == newest.c.account_id,
                               SecuritySnapshot.created_at == newest.c.at))
            .order_by(SecuritySnapshot.id.asc()))
    return list({snap.account_id: snap for snap in rows}.values())


def _is_finding():
    return HealthIssue.detected_by.in_(SECURITY_DETECTORS)


def open_high_findings() -> int:
    """Open security findings of high or critical severity (MVP-2.8.0: the sidebar's «安全» number)."""
    with get_db_session() as session:
        return (session.query(HealthIssue)
                .filter(_is_finding())
                .filter(HealthIssue.status.in_(OPEN_ISSUE_STATUSES))
                .filter(HealthIssue.severity.in_(("critical", "high"))).count())


def _collection(snap: SecuritySnapshot) -> tuple[Optional[str], list[dict]]:
    """A snapshot's collection status and the sources that failed; (None, []) on one written before it was recorded."""
    health = snap.collection_health if isinstance(snap.collection_health, dict) else None
    if not health:
        return None, []
    sources = health.get("sources") if isinstance(health.get("sources"), dict) else {}
    errors = [{"source": name, "error": str(state.get("error") or "")}
              for name, state in sorted(sources.items()) if isinstance(state, dict) and not state.get("ok")]
    return health.get("status"), errors


def security_summary(account_id: Optional[int] = None) -> dict:
    """One row per account that has a snapshot — its newest. `open_findings` counts THAT account's open findings
    (it equals `security_findings(account_id=…)["total"]`); the ones no account holds are `unassigned_open_findings`.
    A snapshot of an account nobody could read has `overall_score: null` and `collection: "failed"`.
    `reachable_paths` is null — not 0 — when the security groups were not read and none was seen; `exposure_read`
    false with a number means «at least that many»."""
    with get_db_session() as session:
        accounts = _Accounts(session)
        open_by = dict(session.query(HealthIssue.account_id, func.count(HealthIssue.id))
                       .filter(_is_finding(), HealthIssue.status.in_(OPEN_ISSUE_STATUSES))
                       .group_by(HealthIssue.account_id).all())
        rows = []
        for snap in _latest_snapshots(session):
            pk = accounts.id_of(snap.account_id)
            if account_id is not None and pk != account_id:
                continue
            status, errors = _collection(snap)
            # Whether the security groups — what a reachable path is made of — were read (N27, review): «0
            # reachable paths» said of an account whose groups were not read is a false all-clear. None on a
            # snapshot from before collection was recorded.
            exposure_read = None if status is None else not any(e["source"] == "network" for e in errors)
            reachable = sum(1 for p in (snap.exposure_paths or []) if p.get("reachability") == "reachable")
            rows.append({
                "account_id": pk,
                "account_name": snap.account_id,
                "partition": accounts.partition(snap.account_id),
                "overall_score": snap.overall_score,
                "category_scores": snap.category_scores or {},
                "created_at": iso_z(snap.created_at),
                "reachable_paths": None if exposure_read is False and reachable == 0 else reachable,
                "exposure_read": exposure_read,
                "open_findings": open_by.get(pk, 0) if pk is not None else 0,
                "collection": status,
                "collection_errors": errors,
            })
        rows.sort(key=lambda r: r["account_name"])
        return {"accounts": rows,
                "unassigned_open_findings": open_by.get(None, 0),
                "generated_at": iso_z(datetime.now(timezone.utc))}


def security_trend(days: int = 30, account_id: Optional[int] = None) -> dict:
    """`{days, accounts: [{account_id, account_name, points: [{day, score, partial}]}]}` — one point per account per
    UTC day: that day's LAST score. A day with no snapshot, or with none that has a score, has no point (nothing is
    interpolated); an account whose snapshots in the window all lack a score is listed with no points. The window is
    whole UTC days: today and the `days - 1` before it."""
    if days not in TREND_DAYS:
        raise ValueError(f"days must be one of {list(TREND_DAYS)}")
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today - timedelta(days=days - 1)
    with get_db_session() as session:
        accounts = _Accounts(session)
        q = (session.query(SecuritySnapshot.account_id, SecuritySnapshot.created_at, SecuritySnapshot.overall_score,
                           SecuritySnapshot.collection_health)
             .filter(SecuritySnapshot.created_at >= cutoff)
             .order_by(SecuritySnapshot.created_at.asc(), SecuritySnapshot.id.asc()))
        if account_id is not None:
            q = q.filter(SecuritySnapshot.account_id == (accounts.name_of(account_id) or ""))
        series: dict[str, dict[str, dict]] = {}
        for name, at, value, health in q:
            points = series.setdefault(name, {})
            if value is None or at is None:
                continue
            day = as_utc(at).strftime("%Y-%m-%d")
            partial = isinstance(health, dict) and health.get("status") == "partial"
            points[day] = {"day": day, "score": value, "partial": partial}      # a later one that day overwrites
        return {"days": days,
                "accounts": [{"account_id": accounts.id_of(name), "account_name": name,
                              "points": [series[name][day] for day in sorted(series[name])]}
                             for name in sorted(series)]}


def _reach(metric_data) -> Optional[str]:
    """A finding's reachability as the page says it: the word; an evidence object (some findings carry one) reads
    as undetermined — the engine's conservative bias for what it cannot read; nothing → None."""
    value = metric_data.get("reachability") if isinstance(metric_data, dict) else None
    if value is None or value == "":
        return None
    return value if isinstance(value, str) else "undetermined"


def security_findings(account_id: Optional[int] = None, severity: Optional[list[str]] = None, status: str = "open",
                      reachability: Optional[str] = None, q: Optional[str] = None,
                      limit: int = 50, offset: int = 0) -> dict:
    """`{items, total}` — the security detectors' issues, most severe first, then last seen. `total` is of the
    filter, not of the page. `status`: open (default) | all. Every row names its issue (`issue_ref`), its account,
    and — when the issue is anchored to an inventory row — that row's region and type."""
    if status not in FINDING_STATUSES:
        raise ValueError(f"status must be one of {list(FINDING_STATUSES)}")
    unknown = sorted(set(severity or []) - set(SEVERITIES))
    if unknown:
        raise ValueError(f"invalid severity {unknown}; one of {list(SEVERITIES)}")
    if reachability is not None and reachability not in REACHABILITY:
        raise ValueError(f"reachability must be one of {list(REACHABILITY)}")
    limit, offset = max(1, int(limit)), max(0, int(offset))
    term = (q or "").strip()

    with get_db_session() as session:
        base = session.query(HealthIssue.id).filter(_is_finding())
        if status == "open":
            base = base.filter(HealthIssue.status.in_(OPEN_ISSUE_STATUSES))
        if severity:
            base = base.filter(HealthIssue.severity.in_(severity))
        if account_id is not None:
            base = base.filter(HealthIssue.account_id == account_id)
        if term:
            pattern = like_pattern(term)
            match = [HealthIssue.title.ilike(pattern, escape="\\"), HealthIssue.resource_id.ilike(pattern, escape="\\")]
            number = ref_number(term, "Ii")
            if number is not None:
                match.append(HealthIssue.id == number)
            base = base.filter(or_(*match))
        rank = case(*[(HealthIssue.severity == name, at) for at, name in enumerate(SEVERITIES)], else_=len(SEVERITIES))
        ordered = base.order_by(rank, HealthIssue.last_seen.desc(), HealthIssue.id.desc())

        if reachability is None:
            total = base.count()
            ids = [row.id for row in ordered.offset(offset).limit(limit)]
        else:   # the value lives inside a JSON column and may be an object: read in Python, then page
            hits = [row.id for row in ordered.add_columns(HealthIssue.metric_data) if _reach(row.metric_data) == reachability]
            total, ids = len(hits), hits[offset:offset + limit]

        rows = {row.id: row for row in session.query(
            HealthIssue.id, HealthIssue.title, HealthIssue.severity, HealthIssue.status, HealthIssue.resource_id,
            HealthIssue.issue_type, HealthIssue.detected_by, HealthIssue.last_seen, HealthIssue.metric_data,
            HealthIssue.account_id, HealthIssue.resource_ref).filter(HealthIssue.id.in_(ids))} if ids else {}
        refs = {row.resource_ref for row in rows.values() if row.resource_ref is not None}
        placed = {r.id: r for r in session.query(CloudResource.id, CloudResource.region, CloudResource.resource_type)
                  .filter(CloudResource.id.in_(refs))} if refs else {}
        accounts = _Accounts(session)

        def item(row) -> dict:
            where = placed.get(row.resource_ref)
            return {"id": row.id, "issue_ref": f"I#{row.id}", "title": row.title, "severity": row.severity,
                    "status": row.status, "resource_id": row.resource_id, "issue_type": row.issue_type,
                    "detected_by": row.detected_by, "last_seen": iso_z(row.last_seen),
                    "reachability": _reach(row.metric_data),
                    "account_id": row.account_id, "account_name": accounts.name_of(row.account_id),
                    "region": where.region if where else None,
                    "resource_type": where.resource_type if where else None}

        return {"items": [item(rows[i]) for i in ids if i in rows], "total": total}


def security_recommendations(status: str | None = None, limit: int = 100, account_id: Optional[int] = None) -> list[dict]:
    with get_db_session() as session:
        accounts = _Accounts(session)
        q = session.query(SecurityRecommendation)
        if status:
            q = q.filter(SecurityRecommendation.status == status)
        if account_id is not None:
            q = q.filter(SecurityRecommendation.account_id == (accounts.name_of(account_id) or ""))
        q = q.order_by(SecurityRecommendation.created_at.desc()).limit(max(1, int(limit)))
        return [{"id": r.id, "account_id": accounts.id_of(r.account_id), "account_name": r.account_id,
                 "category": r.category,
                 "title": r.title, "detail": r.detail, "severity": r.severity,
                 "critic_verdict": r.critic_verdict, "confidence": r.confidence,
                 "status": r.status,
                 "created_at": iso_z(r.created_at)}
                for r in q]


def attack_paths(account_id: Optional[int] = None) -> list[dict]:
    with get_db_session() as session:
        accounts = _Accounts(session)
        out: list[dict] = []
        for snap in sorted(_latest_snapshots(session), key=lambda s: s.account_id):
            pk = accounts.id_of(snap.account_id)
            if account_id is not None and pk != account_id:
                continue
            for p in snap.exposure_paths or []:
                out.append({"account_id": pk, "account_name": snap.account_id, **p})
        return out
