"""Token & cost summary API — real-time aggregation over agent_logs."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter()

_PERIOD = {
    "7d": (timedelta(days=7), "day"),
    "30d": (timedelta(days=30), "day"),
    "day": (timedelta(days=30), "day"),
    "month": (timedelta(days=365), "month"),
    "year": (timedelta(days=365 * 3), "year"),
}


@router.get("/api/cost/summary")
async def api_cost_summary(
    period: str = Query("30d"),
    bucket: Optional[str] = None,
    group_by: str = Query("agent"),
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    model_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    from agenticops.services import cost_service

    delta, default_bucket = _PERIOD.get(period, _PERIOD["30d"])
    end_dt = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)
    start_dt = datetime.fromisoformat(start) if start else (end_dt - delta)
    filters = {k: v for k, v in {
        "actor_type": actor_type, "actor_id": actor_id,
        "agent_name": agent_name, "model_id": model_id,
    }.items() if v}
    return cost_service.cost_summary(
        start=start_dt, end=end_dt,
        bucket=bucket or default_bucket, group_by=group_by, filters=filters,
    )
