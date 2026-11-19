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
                     expected: Optional[str] = None, note: Optional[str] = None) -> str:
    """Move HealthIssue `issue_id` to `new_status`; returns the status it moved from.

    `expected` is the status the caller read; None = the loaded row's status. A same-status request writes
    nothing (no row, no event). `actor` is an actor key string (`user:alice`, `agent:executor`, `system`).
    `reason` says why and is often the code's own sentence; `note` is what a PERSON typed with the decision, and
    is given only then — a page quotes `note` under their name, never `reason` (MVP-2.9.0).

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
    detail = {"from": current, "to": new_status, "reason": (reason or "")[:2000]}
    if note and note.strip():
        detail["note"] = note.strip()[:2000]     # a person's own words, kept whole, as a plan's rejection reason is
    session.add(PipelineEvent(
        health_issue_id=issue_id, event_type="status_changed", stage="issue", status="completed",
        detail=json.dumps(detail),
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


def closed_issue_refusal(session, issue_id: Optional[int], doing: str = "approving") -> Optional[str]:
    """Why a plan of this issue may not be approved — or, since MVP-2.9.0 N26, run (`doing="running"`): a resolved
    or dismissed issue is reopened first, so no approval (human, agent or auto) and no run puts a fix in motion for
    it. An approved plan whose issue was closed afterwards could still be executed until N26. None = it may (or it
    is a change plan)."""
    issue = session.get(HealthIssue, issue_id) if issue_id else None
    if issue is not None and issue.status in ("resolved", "dismissed"):
        return f"HealthIssue #{issue_id} is '{issue.status}'; reopen it before {doing} its plan"
    return None


def run_refusal(session, issue_id: Optional[int], *, claimed: bool = False) -> Optional[str]:
    """Why a fix plan of this issue may not start a run — None = it may (or it is a change plan: no issue).

    A run moves its issue `fix_approved → fix_executing`, and its result moves it on from there. An issue that is
    anywhere else cannot follow the run: a passed run would not resolve it, an acceptance would be refused, a
    failed run would not give it back. So a plan runs only while its issue waits for exactly that (MVP-2.9.0 N27,
    review). N26 refused a closed issue's plan with «reopen it before running its plan» — but a reopened issue is
    `open` (it starts again from its diagnosis) and a resolved one cannot be reopened; that sentence is gone.

    `claimed` = a queued ticket being claimed: the issue moved to `fix_executing` when the ticket was queued, so
    it is still on this run there (or at `fix_approved`, where a path that did not move it left it: the result
    moves it from either) — a ticket whose issue was closed, or moved elsewhere, while it waited is not run.

    The issue is read as it is NOW (`populate_existing`): a session that already has it in hand — the command
    line's, across its confirmation prompt, which waits without limit — would otherwise answer from that copy."""
    issue = session.get(HealthIssue, issue_id, populate_existing=True) if issue_id else None
    if issue is None:
        return None
    if issue.status in (("fix_executing", "fix_approved") if claimed else ("fix_approved",)):
        return None
    if issue.status in ("resolved", "dismissed"):
        return (f"HealthIssue #{issue_id} is '{issue.status}': its approved plan is not run. A dismissed issue that "
                f"is reopened starts again from its diagnosis.")
    return (f"HealthIssue #{issue_id} is '{issue.status}', not waiting for this plan's run: the plan was approved "
            f"for the issue as it stood then. Withdraw the plan and plan again from where the issue is now.")
