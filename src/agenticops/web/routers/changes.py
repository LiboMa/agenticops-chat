"""Change Management API (MVP-2.6.0) — pure routing over services.change_service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from agenticops.auth.actor import Actor
from agenticops.auth.signatures import verify_hmac_signature
from agenticops.config import settings
from agenticops.models import VALID_CHANGE_STATUSES, FixExecution, FixPlan, get_db_session
from agenticops.services import change_service as cs
from agenticops.services.pipeline_events import get_timeline
from agenticops.web.deps import current_actor
from agenticops.web.schemas import (
    ChangeApproveBody, ChangeClarifyBody, ChangeIntakeBody, ChangeReasonBody, ChangeRequestCreate, ChangeRequestDetail,
    ChangeRequestResponse,
    ChangeResolveReviewBody, ChangeTimelineEntry, FixExecutionResponse, FixPlanResponse,
)

_PERIOD = {"7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}
_INTAKE_PATH = "/api/changes/intake"


def is_change_intake(method: str, path: str) -> bool:
    """POST /api/changes/intake: its HMAC is its authentication, so APIAuthMiddleware lets it through."""
    return method == "POST" and path == _INTAKE_PATH


def _enabled() -> None:
    if not settings.change_management_enabled:
        raise HTTPException(status_code=404, detail="Change management is disabled (change_management_enabled=false)")


# A router dependency runs before parameter/body validation, so with the flag off even invalid input gets the 404
# (only malformed JSON still gets 422 — FastAPI decodes the body before any dependency runs)
router = APIRouter(prefix="/api/changes", tags=["changes"], dependencies=[Depends(_enabled)])


def _call(fn, *args, **kwargs):
    """Run a change_service call, its ChangeError as an HTTP error. The handlers are plain `def` (FastAPI's
    threadpool): service calls can resolve targets live and notify, which must not hold the event loop."""
    try:
        return fn(*args, **kwargs)
    except cs.ChangeError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _last_policy_decision(cr_id: int) -> Optional[dict]:
    """The decision of the LAST policy_decision pipeline event (None when the review never reached the policy)."""
    events = [e for e in get_timeline(change_request_id=cr_id) if e["event_type"] == "policy_decision"]
    return (events[-1]["detail"] or {}).get("policy_decision") if events else None


@router.post("", response_model=ChangeRequestResponse, status_code=201)
def api_create_change(data: ChangeRequestCreate, request: Request, actor: Actor = Depends(current_actor)):
    """Open a change request; the SRE review starts in the background (poll GET /api/changes/{id})."""
    # APIAuthMiddleware sets request.state.api_key only for aiops_* API keys; the Web UI signs in with a session token
    source = "api" if getattr(request.state, "api_key", None) is not None else "web"
    return _call(cs.create_change_request, source=source, actor=actor, title=data.title, description=data.description,
                 account_name=data.account_name, targets=data.targets, requested_change_type=data.requested_change_type,
                 justification=data.justification, start_review=True,
                 proposed_steps=[step.model_dump() for step in data.proposed_steps] if data.proposed_steps else None,
                 external_ref=data.external_ref.model_dump(exclude_none=True) if data.external_ref else None)


@router.post("/intake", response_model=ChangeRequestResponse, status_code=201,
             responses={200: {"description": "The still-open request for the same external ticket"}})
async def api_intake_change(request: Request, response: Response):
    """An external system opens a change here (spec §3.D.3) — no UI by design; the request shows on the change pages.

    404 until change_intake_secret is set. The raw body must be signed: X-AIOps-Signature: sha256=<hex HMAC-SHA256
    of X-AIOps-Timestamp + "." + body>, the timestamp inside intake_signature_window_seconds — else 401. The
    requester is webhook:<external_ref.system>; a still-open request for the same ticket comes back with 200."""
    secret = settings.change_intake_secret
    if not secret:
        raise HTTPException(status_code=404, detail="Change intake is not configured (change_intake_secret)")
    body = await request.body()
    if not verify_hmac_signature(secret, request.headers.get("x-aiops-timestamp", ""),
                                 request.headers.get("x-aiops-signature", ""), body,
                                 window_seconds=settings.intake_signature_window_seconds):
        raise HTTPException(status_code=401, detail="valid X-AIOps-Signature and X-AIOps-Timestamp required")
    try:  # validated only once signed: an unsigned caller learns nothing about the body shape
        data = ChangeIntakeBody.model_validate_json(body.decode("utf-8"))  # the 422 echoes it, so it must be text
    except UnicodeDecodeError as e:
        raise RequestValidationError([{"type": "json_invalid", "loc": ("body",),
                                       "msg": f"body is not UTF-8 (byte {e.start})"}]) from e
    except ValidationError as e:
        raise RequestValidationError([{**err, "loc": ("body", *err["loc"])}
                                      for err in e.errors(include_url=False, include_context=False)]) from e
    cr, created = await asyncio.to_thread(_call, cs.intake_change, title=data.title, description=data.description,
                        account_name=data.account, targets=data.target_hints, justification=data.justification,
                        proposed_steps=[step.model_dump() for step in data.proposed_steps] if data.proposed_steps else None,
                        external_ref=data.external_ref.model_dump(exclude_none=True), requested_by=data.requested_by)
    if not created:
        response.status_code = 200
    return cr


@router.get("", response_model=List[ChangeRequestResponse])
def api_list_changes(
    status: Optional[str] = None, account_id: Optional[int] = None, requested_by: Optional[str] = None,
    period: Optional[str] = Query(None, pattern="^(7d|30d|90d)$"),
    limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
):
    if status and status not in VALID_CHANGE_STATUSES:
        # a typo must not look like an empty list
        raise HTTPException(status_code=422,
                            detail=f"invalid status '{status}'; expected one of {sorted(VALID_CHANGE_STATUSES)}")
    since = datetime.now(timezone.utc) - _PERIOD[period] if period else None
    return cs.list_changes(status=status, account_id=account_id, requested_by=requested_by, since=since, limit=limit, offset=offset)


@router.get("/{cr_id}", response_model=ChangeRequestDetail)
def api_get_change(cr_id: int):
    snap = _call(cs.get_change, cr_id)
    with get_db_session() as session:
        plans = session.query(FixPlan).filter_by(change_request_id=cr_id).order_by(FixPlan.created_at.desc()).all()
        plan_ids = [p.id for p in plans]
        executions = (session.query(FixExecution).filter(FixExecution.fix_plan_id.in_(plan_ids))
                      .order_by(FixExecution.created_at.desc()).all()) if plan_ids else []
        # a change plan has no HealthIssue — it belongs to its change request's account
        snap["plans"] = [FixPlanResponse.model_validate(p).model_copy(update={"account_id": snap["account_id"]})
                         for p in plans]
        snap["executions"] = [FixExecutionResponse.model_validate(e) for e in executions]
    snap["policy_decision"] = _last_policy_decision(cr_id)
    return snap


@router.post("/{cr_id}/approve", response_model=ChangeRequestResponse)
def api_approve_change(cr_id: int, body: ChangeApproveBody, actor: Actor = Depends(current_actor)):
    """Approve the reviewed implementation plan and queue its run (a change runs on approval, as a fix plan does);
    a run that cannot be queued leaves the change approved — POST /execute is the retry."""
    return _call(cs.approve_and_execute, cr_id, actor=actor, reason=body.reason, content_hash=body.content_hash)


@router.post("/{cr_id}/reject", response_model=ChangeRequestResponse)
def api_reject_change(cr_id: int, body: ChangeReasonBody, actor: Actor = Depends(current_actor)):
    return _call(cs.reject, cr_id, actor=actor, reason=body.reason)


@router.post("/{cr_id}/cancel", response_model=ChangeRequestResponse)
def api_cancel_change(cr_id: int, body: ChangeReasonBody, actor: Actor = Depends(current_actor)):
    return _call(cs.cancel, cr_id, actor=actor, reason=body.reason)


@router.post("/{cr_id}/clarify", response_model=ChangeRequestResponse, status_code=202)
def api_clarify_change(cr_id: int, body: ChangeClarifyBody, actor: Actor = Depends(current_actor)):
    return _call(cs.clarify, cr_id, actor=actor, message=body.message)


@router.post("/{cr_id}/review", response_model=ChangeRequestResponse, status_code=202)
def api_review_change(cr_id: int, actor: Actor = Depends(current_actor)):
    """(Re)start the SRE review of a draft — e.g. after a watchdog rollback."""
    return _call(cs.restart_review, cr_id, actor=actor)


@router.post("/{cr_id}/execute", response_model=FixExecutionResponse, status_code=202)
def api_execute_change(cr_id: int, actor: Actor = Depends(current_actor)):
    out = _call(cs.request_execution, cr_id, actor=actor)
    with get_db_session() as session:
        return FixExecutionResponse.model_validate(session.get(FixExecution, out["execution_id"]))


@router.post("/{cr_id}/resolve-review", response_model=ChangeRequestResponse)
def api_resolve_review(cr_id: int, body: ChangeResolveReviewBody, actor: Actor = Depends(current_actor)):
    return _call(cs.resolve_review, cr_id, actor=actor, outcome=body.outcome, reason=body.reason)


@router.get("/{cr_id}/timeline", response_model=List[ChangeTimelineEntry])
def api_change_timeline(cr_id: int):
    _call(cs.get_change, cr_id)  # 404 guard
    return cs.change_timeline(cr_id)
