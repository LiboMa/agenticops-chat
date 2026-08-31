"""Security review API — posture scores, findings, recommendations, attack paths."""

from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/api/security/summary")
async def api_security_summary():
    from agenticops.services import security_service
    return security_service.security_summary()


@router.get("/api/security/trend")
async def api_security_trend(days: int = Query(30), account: Optional[str] = None):
    from agenticops.services import security_service
    return security_service.security_trend(days=days, account=account)


@router.get("/api/security/findings")
async def api_security_findings(limit: int = Query(100)):
    from agenticops.services import security_service
    return security_service.security_findings(limit=limit)


@router.get("/api/security/recommendations")
async def api_security_recommendations(status: Optional[str] = None, limit: int = Query(100)):
    from agenticops.services import security_service
    return security_service.security_recommendations(status=status, limit=limit)


@router.get("/api/security/attack-paths")
async def api_security_attack_paths():
    from agenticops.services import security_service
    return security_service.attack_paths()
