"""Webhook API endpoints — extracted from app.py.

With `webhook_secret` set, the two alert-intake routes need the shared token or an HMAC signature (MVP-2.6.1
spec §3.B.5) instead of APIAuthMiddleware's Bearer: CloudWatch-via-SNS and Alertmanager cannot log in.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from agenticops.config import settings
from agenticops.models import AlertEvent, get_db_session
from agenticops.web.schemas import AlertEventResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_INTAKE_PATH = "/api/webhooks/alert"


def is_webhook_intake(method: str, path: str) -> bool:
    """POST to one of the two alert-intake routes. Reading /api/webhooks/alert/events stays behind Bearer auth.

    `{source}` is exactly one non-empty segment, as the router matches it, so a POST to any deeper path (no intake
    route there today) keeps the Bearer check instead of skipping both."""
    head, _, source = path.rpartition("/")
    return method == "POST" and (path == _INTAKE_PATH or (head == _INTAKE_PATH and source != ""))


def warn_if_unauthenticated() -> None:
    """Startup: say so when the intake routes take alerts from anyone who can reach them."""
    if not settings.webhook_secret:
        logger.warning("webhook: webhook_secret is not set — POST %s[/{source}] is not token-checked "
                       "(set AIOPS_WEBHOOK_SECRET)", _INTAKE_PATH)


async def require_webhook_token(request: Request) -> None:
    """The shared token as `Authorization: Bearer`, `X-AIOps-Token` or `?token=`, or an X-AIOps-Signature HMAC
    over X-AIOps-Timestamp + "." + body inside intake_signature_window_seconds. No secret set = no check."""
    from agenticops.auth.signatures import token_matches, verify_hmac_signature

    secret = settings.webhook_secret
    if not secret:
        return
    auth = request.headers.get("authorization", "")
    candidates = (auth[7:] if auth.startswith("Bearer ") else "", request.headers.get("x-aiops-token", ""),
                  request.query_params.get("token", ""))
    if any(token_matches(secret, c) for c in candidates):
        return
    timestamp, signature = request.headers.get("x-aiops-timestamp", ""), request.headers.get("x-aiops-signature", "")
    # The body is read only for a complete signature: a bare unauthenticated POST is refused without it
    if timestamp and signature and verify_hmac_signature(secret, timestamp, signature, await request.body(),
                                                         window_seconds=settings.intake_signature_window_seconds):
        return
    raise HTTPException(status_code=401, detail="webhook token or signature required")


@router.post("/api/webhooks/alert", dependencies=[Depends(require_webhook_token)])
async def api_webhook_alert_auto(request: Request):
    """Receive an alert from any external monitoring system (auto-detect source).

    Accepts JSON from Datadog, PagerDuty, Grafana, or generic format.
    Creates an AlertEvent record, optionally creates a HealthIssue, and triggers RCA.
    """
    body = await request.json()
    return await _process_webhook_alert(body)


@router.post("/api/webhooks/alert/{source}", dependencies=[Depends(require_webhook_token)])
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
    from agenticops.integrations.parsers import parse_alerts
    from agenticops.integrations.alert_processor import process_alert

    # Generate trace_id at alert entry point
    trace_id = generate_trace_id()
    set_trace_id(trace_id)

    try:
        alerts = parse_alerts(body, source=source)
    except Exception as e:
        logger.warning("Failed to parse webhook alert: %s", e)
        raise HTTPException(status_code=400, detail=f"Failed to parse alert: {e}")

    # Multi-alert payloads (Prometheus/Grafana groups) → one signal each.
    results = [process_alert(alert, trace_id=trace_id) for alert in alerts]

    if all(r.action == "error" for r in results):
        raise HTTPException(status_code=500, detail=results[0].message)

    primary = next((r for r in results if r.action == "created"), results[0])
    is_dedup = primary.action != "created"
    content = {
        "message": primary.message,
        "alert_event_id": primary.alert_event_id,
        "health_issue_id": primary.health_issue_id,
        "deduplicated": primary.action == "deduplicated",
        "trace_id": trace_id,
    }
    if len(results) > 1:
        content["signals"] = [
            {"action": r.action, "alert_event_id": r.alert_event_id,
             "health_issue_id": r.health_issue_id}
            for r in results
        ]
    return JSONResponse(status_code=200 if is_dedup else 201, content=content)
