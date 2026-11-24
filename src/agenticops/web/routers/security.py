"""Security review API — posture scores, findings, recommendations, attack paths.

Every route takes `account_id` (cloud_accounts.id — the top bar's account scope) and is a plain `def`: AgenticOps is
one process, and a blocking database read never runs inside an `async def` handler.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/api/security/summary")
def api_security_summary(account_id: Optional[int] = None):
    from agenticops.services import security_service
    return security_service.security_summary(account_id=account_id)


@router.get("/api/security/trend")
def api_security_trend(days: int = Query(30), account_id: Optional[int] = None):
    from agenticops.services import security_service
    try:
        return security_service.security_trend(days=days, account_id=account_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/api/security/findings")
def api_security_findings(account_id: Optional[int] = None,
                          severity: Optional[str] = Query(None, description="comma list: critical,high,medium,low"),
                          status: str = Query("open", description="open | all"),
                          reachability: Optional[str] = Query(None, description="reachable | undetermined | not_reachable"),
                          q: Optional[str] = Query(None, max_length=200),
                          limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    from agenticops.services import security_service
    wanted = [part.strip() for part in (severity or "").split(",") if part.strip()] or None
    try:
        return security_service.security_findings(
            account_id=account_id, severity=wanted, status=status, reachability=reachability or None,
            q=(q or "").strip() or None, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/api/security/recommendations")
def api_security_recommendations(status: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                                 account_id: Optional[int] = None):
    from agenticops.services import security_service
    return security_service.security_recommendations(status=status, limit=limit, account_id=account_id)


@router.get("/api/security/attack-paths")
def api_security_attack_paths(account_id: Optional[int] = None):
    from agenticops.services import security_service
    return security_service.attack_paths(account_id=account_id)
