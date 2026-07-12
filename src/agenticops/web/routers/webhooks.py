"""Webhook API endpoints — extracted from app.py (no logic change)."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from agenticops.config import settings
from agenticops.models import AlertEvent, get_db_session
from agenticops.web.schemas import AlertEventResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/webhooks/alert")
async def api_webhook_alert_auto(request: Request):
    """Receive an alert from any external monitoring system (auto-detect source).

    Accepts JSON from Datadog, PagerDuty, Grafana, or generic format.
    Creates an AlertEvent record, optionally creates a HealthIssue, and triggers RCA.
    """
    body = await request.json()
    return await _process_webhook_alert(body)


@router.post("/api/webhooks/alert/{source}")
async def api_webhook_alert_explicit(source: str, request: Request):
    """Receive an alert with explicit source type.

    Args:
        source: One of datadog, pagerduty, grafana, prometheus, cloudwatch, generic.
    """
    valid_sources = {"datadog", "pagerduty", "grafana", "prometheus", "cloudwatch", "generic"}
    if source.lower() not in valid_sources:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Valid: {', '.join(sorted(valid_sources))}",
        )
    body = await request.json()
    return await _process_webhook_alert(body, source=source.lower())


@router.get("/api/webhooks/alert/events", response_model=List[AlertEventResponse])
async def api_list_alert_events(
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List recent alert events from webhooks."""
    with get_db_session() as session:
        query = session.query(AlertEvent).order_by(AlertEvent.received_at.desc())
        if source:
            query = query.filter_by(source=source)
        if status:
            query = query.filter_by(status=status)
        events = query.offset(offset).limit(limit).all()
        return [AlertEventResponse.model_validate(e) for e in events]


@router.get("/api/webhooks/alert/events/{event_id}", response_model=AlertEventResponse)
async def api_get_alert_event(event_id: int):
    """Get a specific alert event by ID."""
    with get_db_session() as session:
        event = session.query(AlertEvent).filter_by(id=event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Alert event not found")
        return AlertEventResponse.model_validate(event)


async def _process_webhook_alert(body: dict, source: str = "") -> JSONResponse:
    """Process an inbound webhook alert: parse, dedup, create HealthIssue, trigger RCA."""
    if settings.alert_pipeline_mode == "channel_driven":
        raise HTTPException(
            status_code=503,
            detail="Event-driven pipeline disabled (mode=channel_driven)",
        )

    from agenticops.config import generate_trace_id, set_trace_id
    from agenticops.integrations.parsers import parse_alert
    from agenticops.integrations.alert_processor import process_alert

    # Generate trace_id at alert entry point
    trace_id = generate_trace_id()
    set_trace_id(trace_id)

    try:
        alert = parse_alert(body, source=source)
    except Exception as e:
        logger.warning("Failed to parse webhook alert: %s", e)
        raise HTTPException(status_code=400, detail=f"Failed to parse alert: {e}")

    result = process_alert(alert, trace_id=trace_id)

    if result.action == "error":
        raise HTTPException(status_code=500, detail=result.message)

    is_dedup = result.action == "deduplicated"
    return JSONResponse(
        status_code=200 if is_dedup else 201,
        content={
            "message": result.message,
            "alert_event_id": result.alert_event_id,
            "health_issue_id": result.health_issue_id,
            "deduplicated": is_dedup,
            "trace_id": trace_id,
        },
    )
