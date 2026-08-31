"""Security review query layer for /api/security/* (mirrors cost_service's role)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agenticops.models import (
    HealthIssue,
    SecurityRecommendation,
    SecuritySnapshot,
    get_db_session,
)

_SECURITY_DETECTORS = ("security_poll", "security_posture")


def _latest_snapshots(session) -> list[SecuritySnapshot]:
    """Newest snapshot per account."""
    snaps: dict[str, SecuritySnapshot] = {}
    for snap in session.query(SecuritySnapshot).order_by(SecuritySnapshot.created_at.asc()):
        snaps[snap.account_id] = snap  # later rows overwrite -> newest wins
    return list(snaps.values())


def security_summary() -> dict:
    with get_db_session() as session:
        rows = (session.query(HealthIssue)
                .filter(HealthIssue.detected_by.in_(_SECURITY_DETECTORS))
                .filter(HealthIssue.status != "resolved").all())
        total_open = len(rows)
        accounts = []
        for snap in _latest_snapshots(session):
            reachable = sum(1 for p in (snap.exposure_paths or [])
                            if p.get("reachability") == "reachable")
            accounts.append({
                "account_id": snap.account_id,
                "overall_score": snap.overall_score,
                "category_scores": snap.category_scores or {},
                "created_at": snap.created_at.isoformat() if snap.created_at else None,
                "reachable_paths": reachable,
                "open_findings": total_open,
            })
        return {"accounts": accounts,
                "generated_at": datetime.now(timezone.utc).isoformat()}


def security_trend(days: int = 30, account: str | None = None) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    with get_db_session() as session:
        q = (session.query(SecuritySnapshot)
             .filter(SecuritySnapshot.created_at >= cutoff)
             .order_by(SecuritySnapshot.created_at.asc()))
        if account:
            q = q.filter(SecuritySnapshot.account_id == account)
        return [{"account_id": s.account_id,
                 "created_at": s.created_at.isoformat() if s.created_at else None,
                 "overall_score": s.overall_score} for s in q]


def security_findings(limit: int = 100) -> list[dict]:
    with get_db_session() as session:
        q = (session.query(HealthIssue)
             .filter(HealthIssue.detected_by.in_(_SECURITY_DETECTORS))
             .order_by(HealthIssue.last_seen.desc()).limit(max(1, int(limit))))
        return [{"id": i.id, "title": i.title, "severity": i.severity,
                 "status": i.status, "resource_id": i.resource_id,
                 "issue_type": i.issue_type, "detected_by": i.detected_by,
                 "last_seen": i.last_seen.isoformat() if i.last_seen else None,
                 "reachability": (i.metric_data or {}).get("reachability")}
                for i in q]


def security_recommendations(status: str | None = None, limit: int = 100) -> list[dict]:
    with get_db_session() as session:
        q = (session.query(SecurityRecommendation)
             .order_by(SecurityRecommendation.created_at.desc())
             .limit(max(1, int(limit))))
        if status:
            q = (session.query(SecurityRecommendation)
                 .filter(SecurityRecommendation.status == status)
                 .order_by(SecurityRecommendation.created_at.desc())
                 .limit(max(1, int(limit))))
        return [{"id": r.id, "account_id": r.account_id, "category": r.category,
                 "title": r.title, "detail": r.detail, "severity": r.severity,
                 "critic_verdict": r.critic_verdict, "confidence": r.confidence,
                 "status": r.status,
                 "created_at": r.created_at.isoformat() if r.created_at else None}
                for r in q]


def attack_paths() -> list[dict]:
    with get_db_session() as session:
        out: list[dict] = []
        for snap in _latest_snapshots(session):
            for p in snap.exposure_paths or []:
                out.append({"account_id": snap.account_id, **p})
        return out
