"""Plans & Changes statistics API (MVP-2.6.0).

An audit surface: the stats aggregate the decision ledger (who approved / was denied) and the command
ledger, so the endpoint takes the /api/audit/stats read gate. It is NOT gated by change_management_enabled —
fix-plan statistics and historical change rows stay readable with the flag off.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request

from agenticops.auth.actor import Actor
from agenticops.web.deps import current_actor
from agenticops.web.routers.audit import _require_audit_reader

router = APIRouter(tags=["plans"])

_PERIOD = {"7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}


@router.get("/api/plans/stats")
async def api_plan_stats(
    request: Request,
    period: str = Query("30d", pattern="^(7d|30d|90d)$"),
    kind: str = Query("all", pattern="^(all|fix|change)$"),
    bucket: str = Query("day", pattern="^(day|week)$"),
    current: Actor = Depends(current_actor),
):
    """Plans & changes statistics over the last `period` (what each block counts: services/plan_stats_service)."""
    await _require_audit_reader(request, current)
    from agenticops.services.plan_stats_service import plan_stats
    end = datetime.now(timezone.utc)
    return plan_stats(end - _PERIOD[period], end, kind=kind, bucket=bucket)
