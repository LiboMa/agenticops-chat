"""Change Management service — the ONLY owner of ChangeRequest state and transactions (MVP-2.6.0).

Every write path (chat, web, CLI, agent tools) lands here:
  authz.check → validate_change_transition → audit_logs (same transaction) → pipeline_events → notify.
Terminal states are written only by on_execution_result() / resolve_review().
All public functions accept and return plain dicts (snapshots) so callers on other threads
never touch detached ORM rows.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone  # noqa: F401  (timezone: later lifecycle stamps)
from typing import Any, Iterator, Optional

from agenticops.auth import authz
from agenticops.auth.actor import Actor, agent_actor
from agenticops.audit.service import Actions, AuditService, EntityTypes
from agenticops.config import generate_trace_id, get_trace_id, set_trace_id, settings
from agenticops.models import (  # noqa: F401  (CHANGE_TERMINAL_STATUSES / transition_plan: later stages)
    CHANGE_TERMINAL_STATUSES, ChangeRequest, CloudAccount, FixPlan, InvalidStatusTransition,
    get_db_session, transition_change, transition_plan,
)
from agenticops.services.notification_service import (  # noqa: F401  (pending_approval: approval stage)
    notify_change_pending_approval, notify_change_requested, notify_change_result,
)
from agenticops.services.pipeline_events import log_event

logger = logging.getLogger(__name__)

CHANGE_SOURCES = {"chat", "web", "cli", "im", "webhook", "api"}
REQUESTED_CHANGE_TYPES = {"normal", "emergency"}
REVIEW_VERDICTS = ("approved_for_planning", "needs_clarification", "rejected")
CHANGE_ACTION_TYPES = ("tag", "scale", "config", "network", "iam", "delete", "other")


# ── Errors (mapped to HTTP by the router) ─────────────────────────────

class ChangeError(Exception):
    status_code = 400


class ChangeNotFound(ChangeError):
    status_code = 404


class ChangeStateError(ChangeError):
    status_code = 409


class ChangeValidationError(ChangeError):
    status_code = 422


class ChangeForbidden(ChangeError):
    status_code = 403


# ── Helpers ───────────────────────────────────────────────────────────

@contextmanager
def _session() -> Iterator[Any]:
    with get_db_session() as s:
        yield s


def _check(actor: Actor, permission: str, subject: Any = None) -> None:
    try:
        authz.check(actor, permission, subject=subject)
    except authz.AuthzDenied as e:
        raise ChangeForbidden(str(e)) from e


def _require_enabled() -> None:
    if not settings.change_management_enabled:
        raise ChangeStateError("Change management is disabled (change_management_enabled=false)")


def _load(session, cr_id: int) -> ChangeRequest:
    cr = session.get(ChangeRequest, cr_id)
    if cr is None:
        raise ChangeNotFound(f"ChangeRequest #{cr_id} not found")
    return cr


def _transition(cr: ChangeRequest, new_status: str) -> None:
    try:
        transition_change(cr, new_status)
    except InvalidStatusTransition as e:
        raise ChangeStateError(str(e)) from e


def _audit(session, action: str, cr: ChangeRequest, actor: Actor, *, details: Optional[dict] = None,
           old_status: Optional[str] = None, new_status: Optional[str] = None) -> None:
    AuditService.log(
        action, EntityTypes.CHANGE_REQUEST, str(cr.id), entity_name=cr.title, actor=actor.key,
        user_id=actor.user_id, details=details or {},
        old_values={"status": old_status} if old_status else None,
        new_values={"status": new_status} if new_status else None, session=session,
    )


def _event(cr_id: int, event_type: str, stage: str, status: str = "completed", *, detail: Optional[dict] = None,
           actor: str = "system", trace_id: Optional[str] = None) -> None:
    log_event(None, event_type, stage, status, detail=detail, actor=actor, trace_id=trace_id, change_request_id=cr_id)


def to_dict(cr: ChangeRequest) -> dict:
    def _iso(v):
        return v.isoformat() if isinstance(v, datetime) else v
    return {
        "id": cr.id, "title": cr.title, "description": cr.description, "justification": cr.justification,
        "source": cr.source, "requested_by": cr.requested_by, "requester_user_id": cr.requester_user_id,
        "requested_at": _iso(cr.requested_at), "account_id": cr.account_id,
        "target_hints": list(cr.target_hints or []), "target_resources": list(cr.target_resources or []),
        "requested_change_type": cr.requested_change_type, "effective_change_type": cr.effective_change_type,
        "risk_level": cr.risk_level, "action_type": cr.action_type, "status": cr.status,
        "review_verdict": cr.review_verdict, "review_reasons": list(cr.review_reasons or []),
        "reviewed_by": cr.reviewed_by, "reviewed_at": _iso(cr.reviewed_at),
        "policy_rule": cr.policy_rule, "policy_action": cr.policy_action,
        "approved_by": cr.approved_by, "approver_user_id": cr.approver_user_id, "approved_at": _iso(cr.approved_at),
        "approval_reason": cr.approval_reason, "rejected_by": cr.rejected_by, "rejected_at": _iso(cr.rejected_at),
        "rejection_reason": cr.rejection_reason, "closed_at": _iso(cr.closed_at), "trace_id": cr.trace_id,
        "chat_session_id": cr.chat_session_id, "created_at": _iso(cr.created_at), "updated_at": _iso(cr.updated_at),
    }


def get_change(cr_id: int) -> dict:
    with _session() as s:
        return to_dict(_load(s, cr_id))


def list_changes(*, status: Optional[str] = None, account_id: Optional[int] = None, requested_by: Optional[str] = None,
                 since: Optional[datetime] = None, limit: int = 50, offset: int = 0) -> list[dict]:
    with _session() as s:
        q = s.query(ChangeRequest).order_by(ChangeRequest.created_at.desc())
        if status:
            q = q.filter(ChangeRequest.status == status)
        if account_id is not None:
            q = q.filter(ChangeRequest.account_id == account_id)
        if requested_by:
            q = q.filter(ChangeRequest.requested_by == requested_by)
        if since is not None:
            q = q.filter(ChangeRequest.created_at >= since)
        return [to_dict(c) for c in q.offset(offset).limit(limit).all()]


def active_plan_for(session, cr_id: int) -> Optional[FixPlan]:
    """Latest non-terminal change plan for a request (None when there is none)."""
    from agenticops.models import FIXPLAN_TERMINAL_STATUSES
    return (
        session.query(FixPlan)
        .filter(FixPlan.change_request_id == cr_id, FixPlan.plan_kind == "change",
                FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES))
        .order_by(FixPlan.created_at.desc())
        .first()
    )


# ── Intake ────────────────────────────────────────────────────────────

def create_change_request(
    *, source: str, actor: Actor, title: str, description: str, account_name: Optional[str] = None,
    targets: Optional[list[str]] = None, requested_change_type: str = "normal", justification: str = "",
    chat_session_id: Optional[str] = None, start_review: bool = True,
) -> dict:
    """Unified intake for chat / web / cli / im / (P2 webhook). Returns the CR snapshot."""
    _require_enabled()
    _check(actor, "change.request")
    if source not in CHANGE_SOURCES:
        raise ChangeValidationError(f"invalid source {source!r}; expected one of {sorted(CHANGE_SOURCES)}")
    if requested_change_type not in REQUESTED_CHANGE_TYPES:
        raise ChangeValidationError(f"invalid requested_change_type {requested_change_type!r}; expected normal|emergency")
    title = (title or "").strip()
    description = (description or "").strip()
    if not title or not description:
        raise ChangeValidationError("title and description are required")
    hints = [str(t).strip() for t in (targets or []) if str(t).strip()]

    trace_id = get_trace_id() or generate_trace_id()
    with _session() as s:
        account_id = None
        if account_name:
            acct = s.query(CloudAccount).filter_by(name=account_name, is_enabled=True).first()
            if acct is None:
                raise ChangeValidationError(f"account {account_name!r} not found or disabled")
            account_id = acct.id
        cr = ChangeRequest(
            title=title[:300], description=description, justification=justification or "", source=source,
            requested_by=actor.key, requester_user_id=actor.user_id, account_id=account_id, target_hints=hints,
            target_resources=[], requested_change_type=requested_change_type, status="draft", trace_id=trace_id,
            chat_session_id=chat_session_id,
        )
        s.add(cr)
        s.flush()
        _audit(s, Actions.CHANGE_REQUESTED, cr, actor,
               details={"source": source, "requested_change_type": requested_change_type, "targets": hints},
               new_status="draft")
        snap = to_dict(cr)
    _event(snap["id"], "change_requested", "intake", detail={"source": source, "targets": hints}, actor=actor.key, trace_id=trace_id)
    try:
        notify_change_requested(snap)
    except Exception:
        logger.debug("notify_change_requested failed", exc_info=True)
    if start_review:
        globals()["start_review"](snap["id"], sync=False)  # the parameter shadows the function name
    return snap


# ── Review lifecycle ──────────────────────────────────────────────────

def start_review(cr_id: int, *, sync: bool) -> Optional[str]:
    """draft|needs_clarification → under_review, then run the SRE change review.

    sync=True  : run in this thread and return the SRE's text (Main agent's review_change tool).
    sync=False : daemon thread + watchdog Timer(change_review_timeout_seconds) → returns None.
    """
    with _session() as s:
        cr = _load(s, cr_id)
        old = cr.status
        _transition(cr, "under_review")
        trace_id = cr.trace_id
        _audit(s, Actions.CHANGE_REVIEWED, cr, agent_actor("sre"), details={"phase": "started"},
               old_status=old, new_status="under_review")
    _event(cr_id, "change_review_started", "review", "started", actor="agent:sre", trace_id=trace_id)
    if sync:
        return _run_review(cr_id, trace_id)
    threading.Thread(target=_run_review, args=(cr_id, trace_id), daemon=True, name=f"change-review-{cr_id}").start()
    t = threading.Timer(settings.change_review_timeout_seconds, _watchdog_fire, args=(cr_id,))
    t.daemon = True
    t.start()
    return None


def restart_review(cr_id: int, *, actor: Actor) -> dict:
    """Human (re)start of a review for a draft (Main forgot to call review_change, or the watchdog rolled back)."""
    _check(actor, "change.request")
    with _session() as s:
        cr = _load(s, cr_id)
        if cr.status != "draft":
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', only drafts can be (re)submitted for review")
    start_review(cr_id, sync=False)
    return get_change(cr_id)


def _run_review(cr_id: int, trace_id: Optional[str]) -> Optional[str]:
    """Thread body: set context, run the SRE Mode C agent, enforce 'a review must end with a verdict'.

    sync=True runs this in the CALLER's thread (CLI /change, Main's review_change tool), so both the
    trace id and the Run Context are set through tokens and reset in finally — leaving agent:sre behind
    would mis-attribute every later write in that thread. A CR without a trace keeps the caller's.
    """
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    _tid_token = set_trace_id(trace_id) if trace_id else None
    _rc_token = set_run_context(RunContext(actor="agent:sre", trace_id=trace_id, agent_name="sre",
                                           change_request_id=cr_id))
    result: Optional[str] = None
    try:
        try:
            from agenticops.agents.sre_agent import sre_agent_review_change
            result = str(sre_agent_review_change(cr_id))
        except Exception as e:
            logger.exception("Change review crashed for CR #%d", cr_id)
            _review_failed(cr_id, f"review crashed: {e}")
            return result
        try:
            status = get_change(cr_id)["status"]
        except ChangeNotFound:
            return result
        if status == "under_review":
            _review_failed(cr_id, "review ended without a verdict (submit_change_review was not called)")
        return result
    finally:
        reset_run_context(_rc_token)
        if _tid_token is not None:
            _tid_token.var.reset(_tid_token)  # contextvars.Token.var is the ContextVar the token came from


def _watchdog_fire(cr_id: int) -> None:
    try:
        if get_change(cr_id)["status"] == "under_review":
            _review_failed(cr_id, f"review timed out after {settings.change_review_timeout_seconds}s")
    except ChangeNotFound:
        pass
    except Exception:
        logger.debug("change review watchdog failed for CR #%d", cr_id, exc_info=True)


def _review_failed(cr_id: int, error: str) -> None:
    """under_review → draft (never stuck), review_failed event, notification."""
    with _session() as s:
        cr = _load(s, cr_id)
        if cr.status != "under_review":
            return
        _transition(cr, "draft")
        cr.review_reasons = [error[:500]]
        _audit(s, Actions.CHANGE_REVIEWED, cr, agent_actor("sre"), details={"phase": "failed", "error": error[:500]},
               old_status="under_review", new_status="draft")
        snap = to_dict(cr)
    _event(cr_id, "review_failed", "review", "failed", detail={"error": error[:500]}, actor="agent:sre", trace_id=snap["trace_id"])
    try:
        notify_change_result(snap, "review_failed")
    except Exception:
        logger.debug("notify_change_result failed", exc_info=True)
