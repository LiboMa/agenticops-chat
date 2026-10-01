"""The single write path for HealthIssue.status (MVP-2.6.1).

transition_issue() validates the edge, moves the row with a conditional UPDATE keyed on the status the caller
saw (so two writers cannot both move it from the same status), and adds a `status_changed` timeline event in
the CALLER's session — the event commits or rolls back together with the change. The caller commits.

tests/test_issue_status_writes.py scans src/ for any other write of a HealthIssue status.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm.attributes import set_committed_value

from agenticops.models import (
    _ISSUE_TRANSITIONS, HealthIssue, InvalidStatusTransition, PipelineEvent, validate_status_transition,
)


class IssueNotFound(LookupError):
    """The HealthIssue does not exist."""


class IssueStatusConflict(InvalidStatusTransition):
    """The issue is no longer in the status the caller expected — a concurrent writer moved it first (409)."""


def transition_issue(session, issue_id: int, new_status: str, *, actor: str, reason: str,
                     expected: Optional[str] = None) -> str:
    """Move HealthIssue `issue_id` to `new_status`; returns the status it moved from.

    `expected` is the status the caller read; None = the loaded row's status. A same-status request writes
    nothing (no row, no event). `actor` is an actor key string (`user:alice`, `agent:executor`, `system`).

    Raises IssueNotFound, ValueError (unknown status), InvalidStatusTransition (illegal edge) and
    IssueStatusConflict (the row is no longer in `expected`).
    """
    issue = session.get(HealthIssue, issue_id)
    if issue is None:
        raise IssueNotFound(f"HealthIssue #{issue_id} not found")
    current = expected if expected is not None else issue.status
    validate_status_transition(current, new_status)
    if current == new_status:
        return current
    values = {"status": new_status}
    if new_status == "resolved":
        values["resolved_at"] = datetime.now(timezone.utc)
    changed = (
        session.query(HealthIssue)
        .filter(HealthIssue.id == issue_id, HealthIssue.status == current)
        .update(values, synchronize_session=False)
    )
    if changed != 1:
        raise IssueStatusConflict(f"HealthIssue #{issue_id} is no longer '{current}'; it was changed concurrently")
    for key, value in values.items():  # the bulk UPDATE bypassed the loaded row; mirror it without dirtying it
        set_committed_value(issue, key, value)
    session.add(PipelineEvent(
        health_issue_id=issue_id, event_type="status_changed", stage="issue", status="completed",
        detail=json.dumps({"from": current, "to": new_status, "reason": (reason or "")[:500]}),
        actor=actor[:100] if actor else actor, trace_id=issue.trace_id,  # the column is String(100)
    ))
    return current


def advance_issue(session, issue_id: int, new_status: str, *, actor: str, reason: str) -> Optional[str]:
    """transition_issue for an issue that follows its fix plan (plan saved / approved / executing / executed).

    An `open` issue first hops through `investigating` when only that hop reaches `new_status`. An edge the
    issue still cannot take — it was resolved or dismissed meanwhile, or moved concurrently — leaves it where
    it is and returns why, so the plan-side action that drives it is not undone by the issue's state.
    Returns None when the issue is (now) at `new_status`.
    """
    try:
        issue = session.get(HealthIssue, issue_id)
        if issue is None:
            raise IssueNotFound(f"HealthIssue #{issue_id} not found")
        if issue.status == "open" and new_status not in _ISSUE_TRANSITIONS["open"] | {"open"}:
            try:  # hop only when the hop gets there
                validate_status_transition("investigating", new_status)
            except InvalidStatusTransition:
                validate_status_transition(issue.status, new_status)  # the refusal names the issue's real status
                raise
            transition_issue(session, issue_id, "investigating", actor=actor, reason=reason)
        transition_issue(session, issue_id, new_status, actor=actor, reason=reason)
        return None
    except (IssueNotFound, InvalidStatusTransition) as e:
        return str(e)


def closed_issue_refusal(session, issue_id: Optional[int]) -> Optional[str]:
    """Why a plan of this issue may not be approved: a resolved or dismissed issue is reopened first, so no
    approval (human, agent or auto) puts a fix in motion for it. None = approvable (or a change plan)."""
    issue = session.get(HealthIssue, issue_id) if issue_id else None
    if issue is not None and issue.status in ("resolved", "dismissed"):
        return f"HealthIssue #{issue_id} is '{issue.status}'; reopen it before approving its plan"
    return None
