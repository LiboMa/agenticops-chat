"""Audit log API endpoints — extracted from app.py.

MVP-2.6.0: one read gate for all four endpoints (`_require_audit_reader`) and the tool-layer
command ledger (`GET /api/command-audits`).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.web.deps import current_actor, require_authenticated_user
from agenticops.web.schemas import AuditLogResponse, CommandAuditResponse

router = APIRouter()


async def _require_audit_reader(request: Request, current: Actor, *, admin: bool = True) -> None:
    """audit.read gate. Auth on → the pre-2.6.0 HARD check (admin; entity history: any authenticated
    user), independent of rbac_enforce. Auth off → the RBAC matrix (the anonymous web actor holds admin,
    i.e. today's open trust level of an unauthenticated deployment)."""
    if settings.api_auth_enabled:
        await require_authenticated_user(request, admin=admin)
        return
    from agenticops.auth import authz
    try:
        authz.check(current, "audit.read")
    except authz.AuthzDenied as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/api/audit", response_model=List[AuditLogResponse])
async def api_list_audit_logs(
    request: Request,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[int] = None,
    hours: int = Query(24, le=2160),
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
    current: Actor = Depends(current_actor),
):
    """List audit log entries (requires admin)."""
    from agenticops.audit import AuditService

    await _require_audit_reader(request, current)

    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    logs = AuditService.query(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        start_time=start_time,
        limit=limit,
        offset=offset,
    )

    return [AuditLogResponse.model_validate(log) for log in logs]


@router.get("/api/audit/entity/{entity_type}/{entity_id}", response_model=List[AuditLogResponse])
async def api_get_entity_audit(
    request: Request,
    entity_type: str,
    entity_id: str,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
    current: Actor = Depends(current_actor),
):
    """Get audit history for a specific entity."""
    from agenticops.audit import AuditService

    await _require_audit_reader(request, current, admin=False)

    logs = AuditService.get_entity_history(
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )

    return [AuditLogResponse.model_validate(log) for log in logs]


@router.get("/api/audit/stats")
async def api_get_audit_stats(request: Request, hours: int = Query(24, le=2160),
                              current: Actor = Depends(current_actor)):
    """Get audit statistics (requires admin)."""
    from agenticops.audit import AuditService

    await _require_audit_reader(request, current)

    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    return {
        "period_hours": hours,
        "total_events": AuditService.count_actions(start_time=start_time),
        "creates": AuditService.count_actions(action="create", start_time=start_time),
        "updates": AuditService.count_actions(action="update", start_time=start_time),
        "deletes": AuditService.count_actions(action="delete", start_time=start_time),
        "logins": AuditService.count_actions(action="login", start_time=start_time),
        "login_failures": AuditService.count_actions(action="login_failed", start_time=start_time),
    }


@router.get("/api/command-audits", response_model=List[CommandAuditResponse])
async def api_list_command_audits(
    request: Request,
    actor: Optional[str] = None, tool: Optional[str] = None, outcome: Optional[str] = None,
    fix_plan_id: Optional[int] = None, change_request_id: Optional[int] = None,
    period: Optional[str] = Query(None, pattern="^(7d|30d|90d)$"),
    limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0),
    current: Actor = Depends(current_actor),
):
    """Tool-layer ledger of write-tier command attempts (needs audit.read; see _require_audit_reader)."""
    await _require_audit_reader(request, current)
    from agenticops.models import CommandAudit, get_db_session
    with get_db_session() as session:
        q = session.query(CommandAudit).order_by(CommandAudit.created_at.desc())
        if actor:
            q = q.filter(CommandAudit.actor == actor)
        if tool:
            q = q.filter(CommandAudit.tool == tool)
        if outcome:
            q = q.filter(CommandAudit.outcome == outcome)
        if fix_plan_id is not None:
            q = q.filter(CommandAudit.fix_plan_id == fix_plan_id)
        if change_request_id is not None:
            q = q.filter(CommandAudit.change_request_id == change_request_id)
        if period:
            q = q.filter(CommandAudit.created_at >= datetime.now(timezone.utc) - {"7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}[period])
        return [CommandAuditResponse.model_validate(r) for r in q.offset(offset).limit(limit).all()]
