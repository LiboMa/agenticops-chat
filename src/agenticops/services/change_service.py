"""Change Management service — the ONLY owner of ChangeRequest state and transactions (MVP-2.6.0).

Every write path (chat, web, CLI, agent tools) lands here:
  authz.check → validate_change_transition → audit_logs (same transaction) → pipeline_events → notify.
Terminal states are written only by on_execution_result() / resolve_review().
All public functions accept and return plain dicts (snapshots) so callers on other threads
never touch detached ORM rows.
"""

from __future__ import annotations

import logging
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from agenticops.auth import authz
from agenticops.auth.actor import Actor, agent_actor
from agenticops.audit.service import Actions, AuditService, EntityTypes
from agenticops.config import generate_trace_id, get_trace_id, set_trace_id, settings
from agenticops.models import (  # noqa: F401  (CHANGE_TERMINAL_STATUSES / transition_plan: later stages)
    CHANGE_TERMINAL_STATUSES, ChangeRequest, CloudAccount, CloudResource, FixPlan, InvalidStatusTransition,
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

# The review attempt this thread's SRE run belongs to. `_run_review` publishes it here (RunContext is
# fixed-shape, so it cannot carry it); `submit_review` reads it to key its status claim. Strands copies
# the context into the tool thread, so a value SET here BEFORE the agent runs is visible to submit_review
# called within — and the direct/manual path (no _run_review) reads the None default, keying on status
# only, which is safe because the stale-run race is structurally impossible without a _run_review restart.
_review_attempt_var: ContextVar[Optional[int]] = ContextVar("change_review_attempt", default=None)


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


def _as_utc(v: datetime) -> datetime:
    """Stamp UTC on a naive datetime. Every timestamp this service writes is UTC, but SQLite's
    DATETIME drops the offset, so the SAME field is aware on a fresh object and naive once re-read —
    and a naive ISO string is read as local time by a JS consumer."""
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


def _age_seconds(v: Optional[datetime]) -> float:
    """Seconds since a stored timestamp (0.0 when there is none)."""
    if not isinstance(v, datetime):
        return 0.0
    return (datetime.now(timezone.utc) - _as_utc(v)).total_seconds()


def to_dict(cr: ChangeRequest) -> dict:
    def _iso(v):
        return _as_utc(v).isoformat() if isinstance(v, datetime) else v
    return {
        "id": cr.id, "title": cr.title, "description": cr.description, "justification": cr.justification,
        "source": cr.source, "requested_by": cr.requested_by, "requester_user_id": cr.requester_user_id,
        "requested_at": _iso(cr.requested_at), "account_id": cr.account_id,
        "target_hints": list(cr.target_hints or []), "target_resources": list(cr.target_resources or []),
        "requested_change_type": cr.requested_change_type, "effective_change_type": cr.effective_change_type,
        "risk_level": cr.risk_level, "action_type": cr.action_type, "status": cr.status,
        "review_verdict": cr.review_verdict, "review_reasons": list(cr.review_reasons or []),
        "review_attempt": cr.review_attempt or 0,
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
        try:
            globals()["start_review"](snap["id"], sync=False)  # the parameter shadows the function name
        except Exception:
            # The row is already committed: raising here would make a retrying client file duplicate
            # drafts. The CR stays a draft and restart_review can (re)submit it — same shape as notify.
            logger.warning("start_review failed for new ChangeRequest #%s — it stays a draft",
                           snap["id"], exc_info=True)
    return snap


# ── Review lifecycle ──────────────────────────────────────────────────

def start_review(cr_id: int, *, sync: bool) -> Optional[str]:
    """draft|needs_clarification → under_review, then run the SRE change review.

    sync=True  : run in this thread and return the SRE's text (Main agent's review_change tool).
    sync=False : daemon watchdog thread that STARTS and then JOINS the daemon worker → returns None.

    Every entry into under_review bumps `review_attempt`. That number keys this attempt's rollbacks, so
    a late actor from an earlier attempt can never roll back a later one — which only holds because the
    entry itself is an atomic claim (`_claim_for_review`): two concurrent starts cannot both win, so one
    attempt number identifies exactly one review run.
    """
    with _session() as s:
        cr = _load(s, cr_id)  # 404s a missing CR
        old = cr.status
        trace_id = cr.trace_id
        claimed, attempt = _claim_for_review(s, cr_id)
        if not claimed:
            raise ChangeStateError(
                f"ChangeRequest #{cr_id} cannot start review from '{old}' "
                f"(only a draft or a clarified request can, and only one review at a time)"
            )
        cr = _load(s, cr_id)  # the refreshed row, for the audit snapshot
        _audit(s, Actions.CHANGE_REVIEWED, cr, agent_actor("sre"),
               details={"phase": "started", "attempt": attempt}, old_status=old, new_status="under_review")
    _event(cr_id, "change_review_started", "review", "started", detail={"attempt": attempt},
           actor="agent:sre", trace_id=trace_id)
    if sync:
        return _run_review(cr_id, trace_id, attempt)
    try:
        worker = threading.Thread(target=_run_review, args=(cr_id, trace_id, attempt), daemon=True,
                                  name=f"change-review-{cr_id}")
        threading.Thread(target=_watchdog_join, args=(cr_id, attempt, worker, settings.change_review_timeout_seconds),
                         daemon=True, name=f"change-review-watchdog-{cr_id}").start()
    except BaseException:
        # Nothing is armed to finish the review, so it must not stay under_review. The worker is started
        # by the watchdog, so a failure here means no worker is running either.
        _review_failed(cr_id, attempt, "review could not be started (thread spawn failed)")
        raise
    return None


def restart_review(cr_id: int, *, actor: Actor) -> dict:
    """Human (re)start of a review (Main forgot to call review_change, or the watchdog rolled back).

    A draft is the normal case. An `under_review` CR older than change_review_timeout_seconds is a
    stale review — its watchdog died with its process — so it is rolled back first and then restarted;
    a review still inside the timeout is refused so a live one is never cut short.
    """
    _check(actor, "change.request")
    stale: Optional[str] = None
    stale_attempt = 0
    with _session() as s:
        cr = _load(s, cr_id)
        stale_attempt = cr.review_attempt or 0
        if cr.status == "under_review":
            age = _age_seconds(cr.updated_at or cr.created_at)
            if age < settings.change_review_timeout_seconds:
                raise ChangeStateError(
                    f"ChangeRequest #{cr_id} has been under review for {age:.0f}s "
                    f"(< {settings.change_review_timeout_seconds}s) — wait for that review to finish"
                )
            stale = f"stale review recovered after {age:.0f}s (no live watchdog — process restart?)"
        elif cr.status != "draft":
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', only drafts can be (re)submitted for review")
    if stale:
        # Keyed to the attempt we just read: a same-process watchdog for that orphan firing a moment
        # later is a 0-row no-op, because the restart below bumps the attempt.
        _review_failed(cr_id, stale_attempt, stale, phase="stale_recovery")
    # 409s by itself if a verdict landed in the meantime, or if a concurrent start won the claim
    start_review(cr_id, sync=False)
    return get_change(cr_id)


def _run_review(cr_id: int, trace_id: Optional[str], attempt: int) -> Optional[str]:
    """Thread body: set context, run the SRE Mode C agent, enforce 'a review must end with a verdict'.

    sync=True runs this in the CALLER's thread (CLI /change, Main's review_change tool), so both the
    trace id and the Run Context are set through tokens and reset in finally — leaving agent:sre behind
    would mis-attribute every later write in that thread. A CR without a trace keeps the caller's.

    `attempt` is OUR attempt number: every rollback below is keyed to it, so a worker that returns long
    after its own attempt timed out cannot roll back the attempt a human started in the meantime.
    """
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    _tid_token = set_trace_id(trace_id) if trace_id else None
    _rc_token = set_run_context(RunContext(actor="agent:sre", trace_id=trace_id, agent_name="sre",
                                           change_request_id=cr_id))
    _ra_token = _review_attempt_var.set(attempt)  # so submit_review keys its claim on OUR attempt
    result: Optional[str] = None
    try:
        try:
            from agenticops.agents.sre_agent import sre_agent_review_change
            result = str(sre_agent_review_change(cr_id))
        except Exception as e:
            logger.exception("Change review crashed for CR #%d", cr_id)
            _review_failed(cr_id, attempt, f"review crashed: {e}")
            return result
        except BaseException as e:
            # ^C in the CLI, a SystemExit, a killed worker: roll back so the CR is not stuck
            # under_review, then let it through — a BaseException is not ours to swallow.
            logger.warning("Change review aborted for CR #%d (%s)", cr_id, type(e).__name__)
            _review_failed(cr_id, attempt, f"review aborted: {type(e).__name__}")
            raise
        # No read-then-check: the keyed conditional UPDATE IS the check (a verdict, a deleted row or a
        # later attempt all make it a 0-row no-op).
        _review_failed(cr_id, attempt, "review ended without a verdict (submit_change_review was not called)")
        return result
    finally:
        _review_attempt_var.reset(_ra_token)
        reset_run_context(_rc_token)
        if _tid_token is not None:
            _tid_token.var.reset(_tid_token)  # contextvars.Token.var is the ContextVar the token came from


def _watchdog_join(cr_id: int, attempt: int, worker: threading.Thread, timeout: float) -> None:
    """Guard ONE review attempt: start its worker, then join it (the executor_service watchdog pattern).

    The watchdog owns the start, so a worker can never run without the thread that guards it, and a
    watchdog that waits on its own worker cannot outlive the attempt it guards.
    """
    try:
        worker.start()
    except BaseException:
        logger.exception("change review worker for CR #%d could not be started", cr_id)
        _review_failed(cr_id, attempt, "review could not be started (thread spawn failed)")
        raise
    worker.join(timeout=timeout)
    if worker.is_alive():
        _watchdog_fire(cr_id, attempt)


def _watchdog_fire(cr_id: int, attempt: int) -> None:
    try:
        _review_failed(cr_id, attempt, f"review timed out after {settings.change_review_timeout_seconds}s")
    except Exception:
        logger.debug("change review watchdog failed for CR #%d", cr_id, exc_info=True)


def _claim_for_review(session, cr_id: int) -> tuple[bool, int]:
    """Atomically move draft|needs_clarification → under_review AND bump review_attempt, in one
    conditional UPDATE. Returns (claimed, attempt). Two concurrent starts cannot both win — the loser
    gets (False, 0) — so every winning attempt number identifies exactly one review run. The WHERE's
    source set IS the transition-validity check (the two states validate_change_transition allows into
    under_review), so no separate validate call is needed."""
    changed = (
        session.query(ChangeRequest)
        .filter(ChangeRequest.id == cr_id,
                ChangeRequest.status.in_(("draft", "needs_clarification")))
        .update({"status": "under_review",
                 "review_attempt": ChangeRequest.review_attempt + 1,
                 "updated_at": datetime.now(timezone.utc)},
                synchronize_session=False)
    )
    if not changed:
        return (False, 0)
    session.refresh(session.get(ChangeRequest, cr_id))  # bulk UPDATE left the identity-map row stale
    cr = session.get(ChangeRequest, cr_id)
    return (True, cr.review_attempt)


def _review_failed(cr_id: int, attempt: int, error: str, *, phase: str = "failed") -> None:
    """under_review → draft (never stuck), review_failed event, notification.

    The rollback is a CONDITIONAL update keyed on (status, review_attempt): `under_review` is the only
    legal source of this edge, and `review_attempt` says WHICH attempt is being rolled back. Both halves
    are needed — a verdict committed inside this window must win (status), and a late actor from an
    earlier attempt must not roll back the attempt a human started since (attempt). 0 rows changed means
    exactly one of those happened: then nothing at all is written — no audit row, no event, no
    notification, and review_reasons is left as its owner wrote it.
    """
    reason = error[:500]
    with _session() as s:
        changed = (
            s.query(ChangeRequest)
            .filter(ChangeRequest.id == cr_id, ChangeRequest.status == "under_review",
                    ChangeRequest.review_attempt == attempt)
            .update({"status": "draft", "updated_at": datetime.now(timezone.utc)},
                    synchronize_session=False)
        )
        if not changed:
            logger.info("review rollback for CR #%d attempt %d skipped: not under_review or a later attempt",
                        cr_id, attempt)
            return
        cr = _load(s, cr_id)
        cr.review_reasons = [reason]  # ORM write: goes through the flush-time secret redaction
        _audit(s, Actions.CHANGE_REVIEWED, cr, agent_actor("sre"),
               details={"phase": phase, "attempt": attempt, "error": reason},
               old_status="under_review", new_status="draft")
        snap = to_dict(cr)
    _event(cr_id, "review_failed", "review", "failed", detail={"error": reason, "attempt": attempt},
           actor="agent:sre", trace_id=snap["trace_id"])
    try:
        notify_change_result(snap, "review_failed")
    except Exception:
        logger.debug("notify_change_result failed", exc_info=True)


# ── Review: grounding, policy, verdict ────────────────────────────────

DESCRIBE_BY_TYPE: dict[str, str] = {
    "ec2:instance": "aws ec2 describe-instances --instance-ids {rid}",
    "ec2:security-group": "aws ec2 describe-security-groups --group-ids {rid}",
    "ec2:subnet": "aws ec2 describe-subnets --subnet-ids {rid}",
    "ec2:vpc": "aws ec2 describe-vpcs --vpc-ids {rid}",
    "ec2:volume": "aws ec2 describe-volumes --volume-ids {rid}",
    "rds:db": "aws rds describe-db-instances --db-instance-identifier {rid}",
    "eks:cluster": "aws eks describe-cluster --name {rid}",
    "s3:bucket": "aws s3api head-bucket --bucket {rid}",
    "lambda:function": "aws lambda get-function --function-name {rid}",
    "autoscaling:group": "aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names {rid}",
    "elbv2:load-balancer": "aws elbv2 describe-load-balancers --load-balancer-arns {rid}",
}
_ARN_DESCRIBE = "aws resourcegroupstaggingapi get-resources --resource-arn-list {rid}"


def _claim(session, cr_id: int, from_status: str, to_status: str, *, attempt: Optional[int] = None) -> bool:
    """Conditional status transition; returns True iff it moved the row. When `attempt` is given, ALSO require
    review_attempt==attempt, so a stale SRE run (whose attempt was already rolled back and restarted) cannot
    land its verdict on the newer attempt. synchronize_session=False leaves the loaded row's in-memory status
    unchanged, so the subsequent _transition(cr, to_status) still validates the edge and stamps
    updated_at/closed_at on the ORM row (same-status validate is a no-op — established by the T5 note)."""
    q = session.query(ChangeRequest).filter(ChangeRequest.id == cr_id, ChangeRequest.status == from_status)
    if attempt is not None:
        q = q.filter(ChangeRequest.review_attempt == attempt)
    changed = q.update({"status": to_status, "updated_at": datetime.now(timezone.utc)},
                       synchronize_session=False)
    return bool(changed)


def _account_name(session, cr: ChangeRequest) -> str:
    if not cr.account_id:
        return ""
    return session.query(CloudAccount.name).filter_by(id=cr.account_id).scalar() or ""


def _hint_matches(hint: str, r: CloudResource) -> bool:
    h = hint.lower()
    rid = (r.resource_id or "").lower()
    if h == rid or (h.startswith("arn:") and rid and (h.endswith("/" + rid) or h.endswith(":" + rid))):
        return True
    if (r.name or "").lower() == h:
        return True
    tags = r.tags or {}
    return str(tags.get("Name", "")).lower() == h


def ground_targets(cr_id: int) -> dict:
    """Deterministic: match target_hints against the inventory (account-scoped); write matches."""
    with _session() as s:
        cr = _load(s, cr_id)
        q = s.query(CloudResource)
        if cr.account_id:
            q = q.filter(CloudResource.account_id == cr.account_id)
        rows = q.all()
        existing = {t.get("resource_id") for t in (cr.target_resources or [])}
        grounded, unresolved = [], []
        for hint in cr.target_hints or []:
            match = next((r for r in rows if _hint_matches(hint, r)), None)
            if match is None:
                if not any(hint.lower() == str(t.get("resource_id", "")).lower() for t in (cr.target_resources or [])):
                    unresolved.append(hint)
                continue
            item = {"resource_id": match.resource_id, "resource_type": match.resource_type, "db_id": match.id,
                    "region": match.region, "evidence": "inventory", "hint": hint}
            grounded.append(item)
            if match.resource_id not in existing:
                cr.target_resources = list(cr.target_resources or []) + [item]
                existing.add(match.resource_id)
        cr.updated_at = datetime.now(timezone.utc)
        return {"grounded": grounded, "unresolved": unresolved, "target_resources": list(cr.target_resources or [])}


def attach_target(cr_id: int, resource_id: str, resource_type: str, *, actor: Actor, region: str = "",
                  hint: str = "") -> dict:
    """Attach a target NOT in the inventory — only after a CODE-executed read-only describe succeeds.
    `hint` names the requester's original wording this target resolves (so submit_review stops treating
    that hint as unresolved); defaults to the resource_id itself."""
    from agenticops.tools.aws_cli_tool import _execute_aws_cli
    resource_id = (resource_id or "").strip()
    if not resource_id:
        raise ChangeValidationError("resource_id is required")
    template = _ARN_DESCRIBE if resource_id.startswith("arn:") else DESCRIBE_BY_TYPE.get(resource_type)
    if template is None:
        raise ChangeValidationError(
            f"unknown resource_type {resource_type!r}; use one of {sorted(DESCRIBE_BY_TYPE)} or pass the resource ARN"
        )
    # LOAD-BEARING (credential 铁律 §3): resource_id / region are LLM-supplied and get str.format-ed into a
    # CLI command that _execute_aws_cli runs verbatim. A value like "i-0abc --profile other" would smuggle a
    # --profile flag → botocore reads ~/.aws instead of the injected FROZEN creds → a read on the WRONG
    # account. Reject anything that is not a bare id/ARN (no whitespace, no leading '-'); ARNs keep ':' '/'.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*", resource_id):
        raise ChangeValidationError(f"invalid resource_id {resource_id!r}")
    if region and not re.fullmatch(r"[a-z]{2}(-gov)?-[a-z]+-\d", region):
        raise ChangeValidationError(f"invalid region {region!r}")
    with _session() as s:
        cr = _load(s, cr_id)
        account = _account_name(s, cr)
    command = template.format(rid=resource_id) + (f" --region {region}" if region else "")
    result = _execute_aws_cli(command, account)
    if not result or result.startswith("Error") or result == "(no output)":
        raise ChangeValidationError(f"target {resource_id!r} could not be verified: {(result or '')[:200]}")
    item = {"resource_id": resource_id, "resource_type": resource_type, "db_id": None, "region": region or None,
            "evidence": {"command": command, "excerpt": result[:300]}, "hint": (hint or resource_id)}
    with _session() as s:
        cr = _load(s, cr_id)
        if not any(t.get("resource_id") == resource_id for t in (cr.target_resources or [])):
            cr.target_resources = list(cr.target_resources or []) + [item]
        if resource_id not in (cr.target_hints or []):
            cr.target_hints = list(cr.target_hints or []) + [resource_id]
        cr.updated_at = datetime.now(timezone.utc)
        _audit(s, Actions.CHANGE_REVIEWED, cr, actor, details={"phase": "target_attached", "resource_id": resource_id,
                                                              "resource_type": resource_type, "command": command})
    return item


def evaluate_policy(cr_id: int, risk_level: str, action_type: Optional[str]):
    """Deterministic policy decision for a change (plan_kind=change, emergency, freeze, blast radius)."""
    from agenticops.services.policy_engine import estimate_blast_radius, get_policy_engine
    with _session() as s:
        cr = _load(s, cr_id)
        provider = native_account = None
        if cr.account_id:
            acct = s.get(CloudAccount, cr.account_id)
            if acct:
                provider = acct.provider
                native_account = (acct.credentials or {}).get("account_id") or None
        targets = list(cr.target_resources or [])
        emergency = cr.requested_change_type == "emergency"
        trace_id = cr.trace_id
    first = targets[0]["resource_id"] if targets else None
    decision = get_policy_engine().evaluate(
        risk_level=risk_level, provider=provider, resource_id=first,
        blast_radius=estimate_blast_radius(first, native_account), plan_kind="change",
        emergency=emergency, action_type=action_type,
    )
    _event(cr_id, "policy_decision", "approval", decision.action,
           detail={"risk_level": risk_level, "action_type": action_type, "policy_decision": decision.to_dict()},
           actor="policy-engine", trace_id=trace_id)
    return decision


def _effective_change_type(decision, requested: str) -> str:
    if requested == "emergency":
        return "emergency"
    if decision.itsm_change_type in ("standard", "normal", "emergency"):
        return decision.itsm_change_type
    return "standard" if decision.action == "auto_approve" else "normal"


def submit_review(cr_id: int, *, verdict: str, risk_level: Optional[str] = None, action_type: Optional[str] = None,
                  reasons: Optional[list[str]] = None, actor: Actor) -> dict:
    """SRE verdict → code decides state. Policy is re-evaluated here; the LLM's reading is advisory.

    Every status move is an attempt-keyed conditional claim (`_claim`), not a read-then-write: the attempt
    is the one `_run_review` published for THIS SRE run (None on the direct/manual path). A stale run whose
    attempt was already rolled back and restarted therefore loses the claim and raises INSIDE the session —
    so its `reviewed_by` / verdict / policy field writes all roll back and leave no trace on the newer
    attempt. That is why the approved_for_planning path validates read-only first and writes the CR fields
    only in the SAME transaction as the claim (an early write would survive a lost claim → a leak).
    """
    _check(actor, "change.review")
    if verdict not in REVIEW_VERDICTS:
        raise ChangeValidationError(f"verdict must be one of {REVIEW_VERDICTS}")
    reasons = [str(r)[:500] for r in (reasons or [])][:20]
    if verdict == "approved_for_planning":
        if risk_level not in ("L0", "L1", "L2", "L3"):
            raise ChangeValidationError("risk_level must be L0-L3 for approved_for_planning")
        if action_type not in CHANGE_ACTION_TYPES:
            raise ChangeValidationError(f"action_type must be one of {CHANGE_ACTION_TYPES}")

    # THIS run's attempt (agent path) or None (direct/manual). Read ONCE; keys every claim below. Never
    # re-read cr.review_attempt at submit time — that would read the newer attempt and defeat the guard.
    current_attempt = _review_attempt_var.get()
    stale = (f"ChangeRequest #{cr_id} is no longer under_review at attempt {current_attempt} "
             f"(concurrent rollback/restart or verdict)")

    if verdict != "approved_for_planning":
        # Field writes + attempt-keyed claim + transition in ONE transaction: a lost claim rolls the field
        # writes back too, so a stale/superseded verdict leaves no trace.
        with _session() as s:
            cr = _load(s, cr_id)
            if cr.status != "under_review":  # fast, friendly fail (the claim is the real guard)
                raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', not under_review")
            cr.reviewed_by = actor.key
            cr.reviewed_at = datetime.now(timezone.utc)
            cr.review_verdict = verdict
            cr.review_reasons = reasons
            if verdict == "needs_clarification":
                if not _claim(s, cr_id, "under_review", "needs_clarification", attempt=current_attempt):
                    raise ChangeStateError(stale)
                _transition(cr, "needs_clarification")
                _audit(s, Actions.CHANGE_REVIEWED, cr, actor, details={"verdict": verdict, "reasons": reasons},
                       old_status="under_review", new_status="needs_clarification")
                outcome = "needs_clarification"
            else:  # rejected
                if not _claim(s, cr_id, "under_review", "rejected", attempt=current_attempt):
                    raise ChangeStateError(stale)
                _transition(cr, "rejected")
                cr.rejected_by, cr.rejected_at = actor.key, datetime.now(timezone.utc)
                cr.rejection_reason = "; ".join(reasons) or "rejected by review"
                _audit(s, Actions.CHANGE_REJECTED, cr, actor, details={"verdict": verdict, "reasons": reasons},
                       old_status="under_review", new_status="rejected")
                outcome = "rejected"
            snap = to_dict(cr)
        _event(cr_id, "change_reviewed", "review", outcome, detail={"verdict": verdict, "reasons": reasons},
               actor=actor.key, trace_id=snap["trace_id"])
        try:
            notify_change_result(snap, outcome)
        except Exception:
            logger.debug("notify_change_result failed", exc_info=True)
        return snap

    # approved_for_planning — validate READ-ONLY (no CR field write yet), then policy, then apply.
    with _session() as s:
        cr = _load(s, cr_id)
        if cr.status != "under_review":  # fast, friendly fail
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', not under_review")
        unresolved = [h for h in (cr.target_hints or [])
                      if not any(str(t.get("hint", "")).lower() == h.lower() or str(t.get("resource_id", "")).lower() == h.lower()
                                 for t in (cr.target_resources or []))]
        if not cr.target_resources or unresolved:
            raise ChangeStateError(f"all targets must be grounded before planning; unresolved: {unresolved or 'none grounded'}")
        plan = active_plan_for(s, cr_id)
        if plan is None or plan.status != "draft":
            raise ChangeStateError("a draft change plan (save_fix_plan plan_kind=change) is required before submitting the verdict")
        if not plan.rollback_plan or not plan.post_checks:
            raise ChangeStateError("the change plan must have a non-empty rollback_plan and non-empty post_checks")
        plan_id = plan.id
        plan_dict = {"id": plan.id, "title": plan.title, "risk_level": risk_level, "summary": plan.summary}

    decision = evaluate_policy(cr_id, risk_level, action_type)
    with _session() as s:
        cr = _load(s, cr_id)
        plan = s.get(FixPlan, plan_id)
        # All CR/plan field writes happen HERE, before the claim, so a lost claim rolls them ALL back
        # (no reviewed_by / verdict / policy leak onto a newer attempt).
        cr.reviewed_by = actor.key
        cr.reviewed_at = datetime.now(timezone.utc)
        cr.review_verdict = verdict
        cr.risk_level = risk_level
        cr.action_type = action_type
        plan.risk_level = risk_level
        cr.policy_rule = decision.rule_name
        cr.policy_action = decision.action
        cr.effective_change_type = _effective_change_type(decision, cr.requested_change_type)
        cr.review_reasons = reasons + [f"policy:{decision.rule_name}:{decision.action}"] + list(decision.reasons)[:5]
        if decision.action == "block":
            if not _claim(s, cr_id, "under_review", "rejected", attempt=current_attempt):
                raise ChangeStateError(stale)
            _transition(cr, "rejected")
            transition_plan(plan, "rejected")
            plan.rejected_by, plan.rejected_at, plan.rejection_reason = "policy-engine", datetime.now(timezone.utc), decision.rule_name
            cr.rejected_by, cr.rejected_at = "policy-engine", datetime.now(timezone.utc)
            cr.rejection_reason = f"blocked by policy rule {decision.rule_name}: " + "; ".join(decision.reasons)
            _audit(s, Actions.CHANGE_REJECTED, cr, actor, details={"policy_decision": decision.to_dict()},
                   old_status="under_review", new_status="rejected")
            snap = to_dict(cr)
            outcome = "rejected"
        else:
            if not _claim(s, cr_id, "under_review", "planned", attempt=current_attempt):
                raise ChangeStateError(stale)
            _transition(cr, "planned")
            transition_plan(plan, "pending_approval")
            _audit(s, Actions.CHANGE_REVIEWED, cr, actor,
                   details={"verdict": verdict, "risk_level": risk_level, "action_type": action_type,
                            "reasons": reasons, "policy_decision": decision.to_dict(), "plan_id": plan_id},
                   old_status="under_review", new_status="planned")
            snap = to_dict(cr)
            outcome = "planned"
    _event(cr_id, "change_reviewed", "review", outcome,
           detail={"verdict": verdict, "risk_level": risk_level, "action_type": action_type, "plan_id": plan_id,
                   "policy_decision": decision.to_dict()}, actor=actor.key, trace_id=snap["trace_id"])

    if outcome == "rejected":
        try:
            notify_change_result(snap, "rejected")
        except Exception:
            logger.debug("notify_change_result failed", exc_info=True)
        return snap

    if decision.action == "auto_approve" and settings.change_auto_approve_standard:
        auto = agent_actor("auto-pipeline")
        globals()["approve"](cr_id, actor=auto, reason=f"policy rule {decision.rule_name} (standard change, auto-approved)")
        globals()["request_execution"](cr_id, actor=auto)
        return get_change(cr_id)

    try:
        notify_change_pending_approval(snap, plan_dict)
    except Exception:
        logger.debug("notify_change_pending_approval failed", exc_info=True)
    return snap


# ── Approval + execution handoff (Task 5 implements the bodies) ────────
# submit_review's auto-approve branch reaches these via globals()[...] (deferred lookup) and the Task-4
# tests patch them. They must EXIST as module attributes now so patch.object(cs, "approve") can bind — a
# missing attribute makes patch.object raise AttributeError at setup. Until Task 5 they fail loud; the
# branch is reachable only when settings.change_auto_approve_standard is true (default false).

def approve(cr_id: int, *, actor: Actor, reason: str = "") -> dict:
    raise NotImplementedError("approve() is implemented in Task 5 (approval + execution handoff)")


def request_execution(cr_id: int, *, actor: Actor) -> dict:
    raise NotImplementedError("request_execution() is implemented in Task 5 (approval + execution handoff)")
