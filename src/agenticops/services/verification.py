"""Post-execution verification and human acceptance (MVP-2.6.1, spec §3.D.4) — one verdict for a fix and a
change execution.

evaluate() is pure: the execution's own outcome and results plus the plan's post_checks in, (verdict, reason)
out. The business status (HealthIssue / ChangeRequest), the execution status (fix_executions.status) and this
verdict (fix_executions.verification_status) are three separate facts; a `failed` verdict does not mean the
change was rolled back (fix_executions.rollback_results says that).

accept_execution() records a human's verdict on a `pending_acceptance` execution: a fix moves its HealthIssue
(fix_executed → resolved | root_cause_identified); a change goes through change_service.resolve_review, which
stays the only human writer of a change's terminal state and stamps the execution in the same transaction.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from agenticops.auth.actor import Actor

logger = logging.getLogger(__name__)

PASSED, FAILED, PENDING = "passed", "failed", "pending_acceptance"

_PASS = {"pass", "passed", "ok", "succeeded", "success", "true"}
_WARN = {"warn", "warning"}


class AcceptanceError(Exception):
    status_code = 409


class AcceptanceNotFound(AcceptanceError):
    status_code = 404


class AcceptanceForbidden(AcceptanceError):
    status_code = 403


class AcceptanceInvalid(AcceptanceError):
    status_code = 422


def _outcome(item) -> str:
    """pass | warning | fail | missing (a result that reports no status at all)."""
    status = item.get("status", item.get("result", item.get("passed"))) if isinstance(item, dict) else item
    if status is None:
        return "missing"
    value = str(status).strip().lower()
    return "pass" if value in _PASS else "warning" if value in _WARN else "fail"


def as_results(value) -> list:
    """The one shape of a results value: a list. A dict is one entry and a JSON string is parsed first;
    anything else (a bool, a number, None, unparseable text) is no entries — missing, never a pass."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def decode_legacy_json(value, want: type):
    """A plan JSON column as a `want` (list or dict). Legacy rows hold it as a JSON *string*, sometimes encoded
    more than once; up to three layers are decoded. None is empty; anything else is kept, wrapped — never
    dropped. FixPlanResponse reads plan columns with this, so the API and the verdict see the same checks."""
    for _ in range(3):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            break
    if value is None:
        return want()
    if isinstance(value, want):
        return value
    return {"raw": value} if want is dict else [value]


def declared_checks(post_checks) -> list:
    """The plan's post-checks as a list — the one reading used by the verdict, the executor's view and the API."""
    return decode_legacy_json(post_checks, list)


def check_ids(post_checks) -> list[str]:
    """A declared check's id is its position, pc-1 … pc-n. post_checks is in the content hash, so the list is
    frozen once approved; identical checks still get distinct ids."""
    return [f"pc-{i}" for i in range(1, len(declared_checks(post_checks)) + 1)]


def check_label(item) -> str:
    """What a declared check says, for people (mirrors the frontend CheckItem)."""
    if isinstance(item, dict):
        for key in ("check", "description", "action", "name", "command"):
            if item.get(key):
                return str(item[key])
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    return str(item)


def annotated_checks(post_checks) -> list[dict]:
    """The declared checks with their check_id, as the executor is shown them (never stored)."""
    out = []
    for cid, item in zip(check_ids(post_checks), declared_checks(post_checks)):
        out.append({"check_id": cid, **item} if isinstance(item, dict) else {"check_id": cid, "check": str(item)})
    return out


def _result_id(item) -> Optional[str]:
    if isinstance(item, dict) and item.get("check_id") is not None:
        cid = str(item["check_id"]).strip().lower()
        return cid or None
    return None


def bind_results(post_checks, post_check_results) -> list[dict]:
    """Pair each declared check with the results that name it: one row per declared check in order, then one
    per stray result. problem: None (bound once), missing, duplicate, undeclared (names no declared check) or
    unbound (carries no check_id). result_status is the bound result's outcome (pass | warning | fail |
    missing), None when nothing is bound."""
    checks = declared_checks(post_checks)
    ids = check_ids(post_checks)
    results = as_results(post_check_results)
    by_id: dict[str, list] = {}
    strays = []
    for r in results:
        cid = _result_id(r)
        if cid in ids:
            by_id.setdefault(cid, []).append(r)
        else:
            strays.append((cid, r))
    rows = []
    for cid, item in zip(ids, checks):
        bound = by_id.get(cid, [])
        rows.append({
            "check_id": cid, "check": check_label(item),
            "result_status": _outcome(bound[0]) if bound else None,
            "results": len(bound),
            "problem": None if len(bound) == 1 else "missing" if not bound else "duplicate",
        })
    for cid, r in strays:
        rows.append({"check_id": cid, "check": None, "result_status": _outcome(r), "results": 1,
                     "problem": "undeclared" if cid else "unbound"})
    return rows


def binding_problems(post_checks, post_check_results) -> list[str]:
    """Why the results do not cover the declared checks one to one; [] when they do."""
    rows = bind_results(post_checks, post_check_results)
    missing = [r["check_id"] for r in rows if r["problem"] == "missing"]
    duplicate = [r["check_id"] for r in rows if r["problem"] == "duplicate"]
    undeclared = [r["check_id"] for r in rows if r["problem"] == "undeclared"]
    unbound = sum(1 for r in rows if r["problem"] == "unbound")
    silent = [r["check_id"] for r in rows if r["problem"] is None and r["result_status"] == "missing"]
    parts = []
    if missing:
        parts.append(f"no result for post-check {', '.join(missing)}")
    if duplicate:
        parts.append(f"post-check {', '.join(duplicate)} reported more than once")
    if undeclared:
        parts.append(f"result for undeclared check {', '.join(undeclared)}")
    if unbound:
        parts.append(f"{unbound} result{'s' if unbound > 1 else ''} without a check_id")
    if silent:
        parts.append(f"post-check {', '.join(silent)} reported no status")
    return parts


def evaluate(execution_status: str, post_checks, post_check_results=None, step_results=None,
             error: str = "", plan_changed: bool = False) -> tuple[str, str]:
    """The verdict on one execution: `passed` only when it succeeded and each declared post-check has exactly
    one result naming its check_id, and every one of them passed.

    A run that did not succeed, or any post-check result that failed, is `failed`. A succeeded run is
    otherwise `pending_acceptance` — no post-checks, a plan changed after approval, a declared check with no
    result or with more than one, a result for an undeclared check or with no check_id, a warning, or a step
    that did not report success — and a human accepts or rejects it. Results are never matched by position
    or by count: a repeated result cannot cover a missing check.
    """
    if execution_status != "succeeded":
        default = "execution rolled back" if execution_status == "rolled_back" else f"execution {execution_status}"
        return FAILED, error or default
    results = as_results(post_check_results)
    outcomes = [_outcome(r) for r in results]
    if "fail" in outcomes:
        i = outcomes.index("fail")
        return FAILED, f"post-check {_result_id(results[i]) or i + 1} failed"
    if not declared_checks(post_checks):
        return PENDING, "the plan has no post-checks"
    if plan_changed:
        return PENDING, "the plan changed after approval; its post-checks cannot vouch for this run"
    problems = binding_problems(post_checks, results)
    if problems:
        return PENDING, "; ".join(problems)
    if "warning" in outcomes:
        return PENDING, f"post-check {_result_id(results[outcomes.index('warning')])} reported a warning"
    steps = [_outcome(s) for s in as_results(step_results)]
    unclear = next((i for i, o in enumerate(steps) if o != "pass"), None)
    if unclear is not None:
        return PENDING, f"step {unclear + 1} did not report success"
    return PASSED, "all post-checks passed"


def accept_execution(execution_id: int, *, actor: Actor, decision: str, reason: str) -> dict:
    """A human's verdict on an execution pending acceptance: `accepted` or `rejected`, with a reason.

    Identity is the caller's authenticated actor. Authorized as the approval of the plan's kind
    (plan.approve / change.approve), so webhook:* is refused even in shadow mode — and before the run's
    state is checked (404 → 403 → 409), so a caller who may not accept learns nothing about it. Returns
    {"execution_id", "decision", "kind", "status"} — status is the issue's or the change request's.
    """
    from agenticops.auth import authz
    from agenticops.models import ChangeRequest, FixExecution, FixPlan, get_session

    if decision not in ("accepted", "rejected"):
        raise AcceptanceInvalid("decision must be accepted or rejected")
    reason = (reason or "").strip()[:2000]
    if not reason:
        raise AcceptanceInvalid("a reason is required")
    session = get_session()
    try:
        execution = session.get(FixExecution, execution_id)
        plan = session.get(FixPlan, execution.fix_plan_id) if execution is not None else None
        if plan is None:
            raise AcceptanceNotFound(f"Execution #{execution_id} not found")
        if plan.plan_kind == "change":
            cr_id = plan.change_request_id
            cr = session.get(ChangeRequest, cr_id) if cr_id is not None else None
            if cr is None:
                raise AcceptanceNotFound(f"Execution #{execution_id}'s change plan names no change request")
            permission, subject = "change.approve", cr  # as resolve_review checks it
        else:
            cr_id, permission, subject = None, "plan.approve", plan
        try:
            authz.check(actor, permission, subject=subject)
        except authz.AuthzDenied as e:
            raise AcceptanceForbidden(str(e)) from e
        if execution.verification_status != PENDING:
            raise AcceptanceError(f"Execution #{execution_id} is not pending acceptance "
                                  f"(verification: {execution.verification_status or 'none'})")
        if cr_id is None:
            status = _accept_fix(session, execution, plan, actor=actor, decision=decision, reason=reason)
    finally:
        session.close()
    if cr_id is not None:
        from agenticops.services import change_service as cs
        try:
            snap = cs.resolve_review(cr_id, actor=actor, outcome="completed" if decision == "accepted" else "failed",
                                     reason=reason)
        except cs.ChangeError as e:
            err = AcceptanceError(str(e))
            err.status_code = e.status_code
            raise err from e
        return {"execution_id": execution_id, "decision": decision, "kind": "change", "status": snap["status"]}
    return {"execution_id": execution_id, "decision": decision, "kind": "fix", "status": status}


def _accept_fix(session, execution, plan, *, actor: Actor, decision: str, reason: str) -> str:
    """Stamp the execution and move its issue from fix_executed, in one transaction; returns the issue status."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from sqlalchemy import func

    from agenticops.models import FixExecution, FixPlan, InvalidStatusTransition
    from agenticops.services.issue_state import transition_issue
    from agenticops.tools.metadata_tools import dispute_rca, log_rca_disputed

    issue_id = plan.health_issue_id
    # Only the issue's latest run speaks for it: an older run left pending when the issue was re-fixed
    # still finds it at fix_executed, and must not close it on the old fix.
    latest = (session.query(func.max(FixExecution.id)).join(FixPlan, FixExecution.fix_plan_id == FixPlan.id)
              .filter(FixPlan.health_issue_id == issue_id).scalar())
    if latest != execution.id:
        session.rollback()
        raise AcceptanceError(f"Execution #{execution.id} is not the latest run for HealthIssue #{issue_id} "
                              f"(latest: #{latest}); accept that one")
    target = "resolved" if decision == "accepted" else "root_cause_identified"
    stamped = (
        session.query(FixExecution)
        .filter(FixExecution.id == execution.id, FixExecution.verification_status == PENDING)
        .update({"verification_status": PASSED if decision == "accepted" else FAILED, "accepted_by": actor.key,
                 "accepted_at": datetime.now(timezone.utc), "acceptance_note": reason}, synchronize_session=False)
    )
    if stamped != 1:
        session.rollback()
        raise AcceptanceError(f"Execution #{execution.id} was accepted or rejected concurrently")
    try:
        transition_issue(session, issue_id, target, actor=actor.key, expected="fix_executed",
                         reason=f"Execution #{execution.id} {decision}: {reason}")
    except InvalidStatusTransition as e:  # the issue moved on since the run (resolved / dismissed / re-planned)
        session.rollback()
        raise AcceptanceError(f"HealthIssue #{issue_id} is no longer fix_executed: {e}") from e
    rca = dispute_rca(session, issue_id, execution.id, f"rejected at acceptance by {actor.key}: {reason}") \
        if decision == "rejected" else None
    action = Actions.EXECUTION_ACCEPTED if decision == "accepted" else Actions.EXECUTION_REJECTED
    AuditService.log(action, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key, user_id=actor.user_id,
                     details={"execution_id": execution.id, "health_issue_id": issue_id, "reason": reason},
                     old_values={"verification_status": PENDING, "issue_status": "fix_executed"},
                     new_values={"verification_status": PASSED if decision == "accepted" else FAILED,
                                 "issue_status": target}, session=session)
    session.commit()
    if rca is not None:
        log_rca_disputed(issue_id, rca.id, execution.id, reason)
    if decision == "accepted":
        try:
            from agenticops.services.resolution_service import trigger_post_resolution
            trigger_post_resolution(issue_id)
        except Exception as e:
            logger.warning("Failed to trigger post-resolution pipeline: %s", e)
    return target
