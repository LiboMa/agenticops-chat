"""Who a work item waits on — the server's copy of the web pages' rules (MVP-2.7.0 S3).

A line-for-line port of frontend lib/issuePhases.ts (issuePhases, currentFixPlan), lib/changePhases.ts
(changePhases) and lib/issueDetail.ts (inFlightAutoRun, notQueuedFrom). tests/fixtures/work_item_phase_cases.json
and auto_run_cases.json are read by both test suites, so the copies cannot drift. Inputs are dicts or ORM rows; an
argument left at UNKNOWN means "not known" (the pages' list mode), None means "known: there is none".
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional
from agenticops.utils.timeutils import as_utc

AUTO_RUN_START_GRACE_SECONDS = 30   # lib/issueDetail.AUTO_RUN_START_GRACE_MS
HUMAN = frozenset({"you", "approver", "requester", "acceptor"})
UNKNOWN: Any = object()
_ABSENT: Any = object()
_APPROVABLE = frozenset({"draft", "pending_approval"})
_IN_FLIGHT = frozenset({"pending", "running"})
_TERMINAL_PLAN = frozenset({"executed", "failed", "rejected"})
_ENDED_CHANGE = {"failed": "failed", "rolled_back": "rolledBack", "rejected": "rejected", "cancelled": "cancelled"}
_CHANGE = {
    "draft": ("draft", "requester", "startReview"),
    "under_review": ("reviewing", "sre_agent", None),
    "needs_clarification": ("needsClarification", "requester", "answerReviewer"),
    "planned": ("awaitingApproval", "approver", "approveAndRun"),
    "approved": ("notQueued", "you", "retryExecution"),
    "executing": ("executing", "executor", None),
    "needs_review": ("awaitingAcceptance", "acceptor", "markCompleted"),
    "completed": ("completed", None, None),
}


@dataclass(frozen=True)
class Phase:
    sub: str
    waiting_for: Optional[str]
    primary: Optional[str]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _ts(value: Any) -> Optional[datetime]:
    """An API/ORM time as an aware UTC datetime (naive = UTC, as the backend stores it)."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _detail(raw: Any) -> Any:
    """An event's detail: a dict, None, or _ABSENT-like garbage (a JSON text from the ORM is parsed first)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return raw  # unreadable: not evidence
    return raw


def gate_passed(rca: Any, threshold: Any) -> Optional[bool]:
    """lib/rcaQuality.confidenceBreakdown(...).gatePassed: None when the threshold is not known."""
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        return None
    conf = _get(rca, "confidence")
    final = conf if isinstance(conf, (int, float)) and not isinstance(conf, bool) else 0
    return final >= threshold and _get(rca, "critic_verdict") != "refuted"


_DIAGNOSING = ("open", "investigating", "acknowledged")


def left_diagnosing_at(events: Iterable) -> Optional[datetime]:
    """The last time the issue's status moved to or from a status OUTSIDE the three it is diagnosed in — what
    rca_stopped_at takes as `moved_at`. A move among open / investigating / acknowledged (Main's status tool, the
    CLI, the API, a late thread) leaves a stopped diagnosis stopped; a dismissal and a reopening do not (round-2
    review B-m11: until then ANY later move took a failed diagnosis back out of every queue). An event that does
    not say where from and where to counts, as it did before."""
    newest = None
    for e in events or ():
        if _get(e, "event_type") != "status_changed":
            continue
        at = _ts(_get(e, "created_at"))
        if at is None:
            continue
        detail = _get(e, "detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except ValueError:
                detail = None
        if isinstance(detail, Mapping) and detail.get("from") in _DIAGNOSING and detail.get("to") in _DIAGNOSING:
            continue
        if newest is None or at > newest:
            newest = at
    return newest


def rca_stopped_at(status: str, events: Iterable, *, now: Optional[datetime] = None,
                   limit_seconds: Optional[float] = None, moved_at: Optional[datetime] = None) -> Optional[datetime]:
    """Since when the newest diagnosis of an issue that is still waiting for one is not going to produce anything
    (MVP-2.9.0 N11), or None: none has been tried, one is under way, or the issue is past diagnosis.

    Two ways a diagnosis stops without moving the issue. It ENDED — it failed, it timed out, or it ended and the
    status stayed (a saved diagnosis moves the issue before its end is logged, so an end that left the issue here
    left nothing to act on): the time is that end. Or it STARTED AND NEVER ENDED and its time limit passed — the run
    died with its process, or hangs: the time is when it should have ended at the latest (`now` and `limit_seconds`
    are needed to tell; without them only an end counts).

    `moved_at` = the last time the issue left or re-entered the diagnosing statuses (left_diagnosing_at). One AFTER
    that time voids it: the issue has been somewhere else since (diagnosed, planned, dismissed, reopened …) and
    stands here again for another reason than that old diagnosis.

    `events` = the issue's timeline (rows or dicts; only rca_started / rca_completed are read). Whether an agent is on
    the issue NOW is the caller's question (services/agent_runs): the timeline cannot answer it."""
    if status not in _DIAGNOSING:
        return None
    started = ended = None
    for e in events or ():
        kind, at = _get(e, "event_type"), _ts(_get(e, "created_at"))
        if at is None:
            continue
        if kind == "rca_started" and (started is None or at > started):
            started = at
        elif kind == "rca_completed" and (ended is None or at > ended):
            ended = at
    stopped = None
    if ended is not None and (started is None or ended >= started):
        stopped = ended
    elif started is not None and now is not None and limit_seconds and limit_seconds > 0:
        due = started + timedelta(seconds=limit_seconds)
        if as_utc(now) >= due:
            stopped = due
    moved = _ts(moved_at)
    return None if stopped is not None and moved is not None and moved > stopped else stopped


def reopened_at(status: str, events: Iterable) -> Optional[datetime]:
    """Since when an issue that waits for a diagnosis stands there because a person REOPENED it (MVP-2.9.0 N26), or
    None. The newest move that brought it into the diagnosing statuses came from `dismissed`, and no diagnosis has
    been started since. Nothing diagnoses a reopened issue by itself — the automatic diagnosis runs when an issue is
    created — so it is a person's turn; it used to read «waits on the RCA agent» for good.

    A diagnosis from before the dismissal does not count. One started since makes it that diagnosis's turn — and
    when that one stopped, rca_stopped_at says so. `events` = the issue's timeline (rows or dicts; only
    status_changed and rca_started are read). Whether an agent is on the issue NOW is the caller's question."""
    if status not in _DIAGNOSING:
        return None
    entered = came_from = started = None
    for e in events or ():
        kind, at = _get(e, "event_type"), _ts(_get(e, "created_at"))
        if at is None:
            continue
        if kind == "rca_started":
            if started is None or at > started:
                started = at
        elif kind == "status_changed":
            detail = _detail(_get(e, "detail"))
            if (isinstance(detail, Mapping) and detail.get("to") in _DIAGNOSING and detail.get("from") not in _DIAGNOSING
                    and (entered is None or at > entered)):
                entered, came_from = at, detail.get("from")
    if entered is None or came_from != "dismissed":
        return None
    return None if started is not None and started >= entered else entered


_PLAN_WRITTEN = ("fix_plan_created", "fix_plan_updated")


def plan_stopped_at(status: str, events: Iterable, *, now: Optional[datetime] = None,
                    limit_seconds: Optional[float] = None, moved_at: Optional[datetime] = None) -> Optional[datetime]:
    """Since when the newest plan run of a diagnosed issue is not going to produce a plan (MVP-2.9.0 N26), or None:
    none was asked for, one is under way, a plan was written since, or the issue is not at «diagnosed».

    The same two ways as a diagnosis (rca_stopped_at). It ENDED without a plan — `fix_plan_requested` with status
    `failed`: the agent raised, was refused, or gave up (`no_plan`); a run asked for in a chat has no start on
    record, only that end. Or it STARTED AND NEVER ENDED and its time limit passed. A plan written at or after that
    time (`fix_plan_created` / `fix_plan_updated`) means the run is not where the issue stands; so does a status move
    after it (`moved_at` = the issue's last status move: it was diagnosed again since).

    With auto-fix on, such an issue used to read «waits on the SRE agent» for good — nothing was on it, and it was
    in nobody's queue. `events` = the issue's timeline (only fix_plan_requested / fix_plan_created / fix_plan_updated
    are read). Whether an agent is on the issue NOW is the caller's question."""
    if status != "root_cause_identified":
        return None
    started = failed = written = None
    for e in events or ():
        kind, at = _get(e, "event_type"), _ts(_get(e, "created_at"))
        if at is None:
            continue
        if kind == "fix_plan_requested":
            if _get(e, "status") == "failed":
                failed = at if failed is None or at > failed else failed
            else:
                started = at if started is None or at > started else started
        elif kind in _PLAN_WRITTEN:
            written = at if written is None or at > written else written
    stopped = None
    if failed is not None and (started is None or failed >= started):
        stopped = failed
    elif started is not None and now is not None and limit_seconds and limit_seconds > 0:
        due = started + timedelta(seconds=limit_seconds)
        if as_utc(now) >= due and (written is None or written < started):
            stopped = due
    if stopped is None or (written is not None and written >= stopped):
        return None
    moved = _ts(moved_at)
    return None if moved is not None and moved > stopped else stopped


def issue_phase(status: str, *, rca: Any = UNKNOWN, threshold: Any = None, plan: Any = UNKNOWN,
                latest_run: Any = UNKNOWN, auto_run_in_flight: bool = False,
                auto_fix_enabled: Optional[bool] = None, rca_stopped: bool = False, reopened: bool = False,
                plan_stopped: bool = False) -> Phase:
    run = None if latest_run is UNKNOWN else latest_run
    if status in _DIAGNOSING:
        # its diagnosis ended without a result and no agent is on it: nothing will move it — a person does (N11)
        if rca_stopped:
            return Phase("rcaStopped", "you", "rerunRca")
        # a person reopened it and nothing has diagnosed it since: nothing will, by itself (N26)
        if reopened:
            return Phase("reopened", "you", "rerunRca")
        return Phase("running", "rca_agent", None)
    if status == "root_cause_identified":
        if run is not None and (_get(run, "verification_status") == "failed"
                                or _get(run, "status") in ("failed", "aborted", "rolled_back")):
            return Phase("needsNewPlan", "you", "generatePlan")
        if rca is UNKNOWN:
            return Phase("reviewOrPlan", "you", None)
        if rca is None:
            return Phase("needsReview", "you", "rerunRca")
        if _get(rca, "human_verdict") == "incorrect":
            return Phase("rcaRejected", "you", "rerunRca")
        # the diagnosis stands (a person confirmed it, or it passes the gate): the next step is a plan. Its plan run
        # ended without one and no agent is on it — nothing will write the plan by itself: a person asks again (N26)
        stopped = Phase("planStopped", "you", "generatePlan")
        if _get(rca, "human_verdict") == "correct":
            return stopped if plan_stopped else Phase("toGenerate", "you", "generatePlan")
        gate = gate_passed(rca, threshold)
        if gate is None:
            return Phase("reviewOrPlan", "you", None)
        if not gate:
            return Phase("needsReview", "you", "reviewRca")
        # a plan of THIS diagnosis was rejected (or withdrawn): nothing asks the SRE agent again — you do
        known_plan = plan is not UNKNOWN and plan is not None
        if (known_plan and _get(plan, "status") == "rejected" and _get(rca, "id") is not None
                and _get(plan, "rca_result_id") == _get(rca, "id")):
            return Phase("planRejected", "you", "generatePlan")
        if plan_stopped:
            return stopped
        # auto-fix off: trigger_auto_sre returns early, so a passing RCA is handed to nobody — you generate the plan
        return Phase("toGenerate", "you" if auto_fix_enabled is False else "sre_agent", "generatePlan")
    if status == "fix_planned":
        known = plan is not UNKNOWN and plan is not None
        if known and _get(plan, "status") == "rejected":
            return Phase("planRejected", "you", "generatePlan")
        return Phase("awaitingApproval", "approver",
                     "approveAndRun" if known and _get(plan, "status") in _APPROVABLE else None)
    if status == "fix_approved":
        if latest_run is UNKNOWN or (run is not None and _get(run, "status") in _IN_FLIGHT) or auto_run_in_flight:
            return Phase("executing", "executor", None)
        return Phase("notQueued", "you", "retryExecution")
    if status == "fix_executing":
        return Phase("executing", "executor", None)
    if status == "fix_executed":
        verdict = _get(run, "verification_status") if run is not None else None
        if verdict == "pending_acceptance":
            return Phase("awaitingAcceptance", "acceptor", "acceptResult")
        if verdict == "passed":
            return Phase("passed", "you", "markResolved")
        return Phase("unverified", "you", "markResolved" if run is not None else None)
    if status in ("resolved", "dismissed"):
        return Phase(status, None, None)
    return Phase("unknown", None, None)


def change_phase(cr: Any) -> Phase:
    status = _get(cr, "status")
    if status in _CHANGE:
        return Phase(*_CHANGE[status])
    if status in _ENDED_CHANGE:
        return Phase(_ENDED_CHANGE[status], None, "copyAsNew")
    return Phase("unknown", None, None)


def current_fix_plan(plans: Iterable[Any]) -> Any:
    """The plan the issue page shows and approves: the newest not executed / failed / rejected, else the newest."""
    ordered = sorted(plans, key=lambda p: (_ts(_get(p, "created_at")) or datetime.min.replace(tzinfo=timezone.utc),
                                           _get(p, "id") or 0), reverse=True)
    return next((p for p in ordered if _get(p, "status") not in _TERMINAL_PLAN), ordered[0] if ordered else None)


def in_flight_auto_run(events: Iterable[Any], plan_id: Optional[int], *, timeout_seconds: Optional[float] = None,
                       now: Optional[datetime] = None) -> Optional[datetime]:
    """When the approval's auto-run of this plan started, if it is under way (no run row exists until it ends)."""
    if plan_id is None:
        return None
    now = now or datetime.now(timezone.utc)
    newest = sorted(events, key=lambda e: (_ts(_get(e, "created_at")), _get(e, "id") or 0), reverse=True)
    for e in newest:
        if _get(e, "event_type") == "execution_completed":
            return None
        detail = _detail(_get(e, "detail"))
        if _get(e, "event_type") != "execution_started" or not isinstance(detail, dict) or detail.get("plan_id") != plan_id:
            continue
        started = _ts(_get(e, "created_at"))
        if timeout_seconds is not None and (now - started).total_seconds() >= timeout_seconds:
            return None
        return started
    return None


def not_queued_from(events: Iterable[Any], plan_id: int, approved_at: Any) -> Optional[datetime]:
    """From when an approved plan with no run row may be called "not queued": None = at once (a run of it showed
    since the approval, or no approval time to anchor on); else approved_at + the grace."""
    approved = _ts(approved_at)
    if approved is None:
        return None
    for e in events:
        kind = _get(e, "event_type")
        if kind not in ("execution_started", "execution_completed") or _ts(_get(e, "created_at")) < approved:
            continue
        detail = _detail(_get(e, "detail"))
        if detail is not None and not isinstance(detail, dict):
            continue
        pid = detail.get("plan_id", _ABSENT) if isinstance(detail, dict) else _ABSENT
        if pid == plan_id or (kind == "execution_completed" and pid is _ABSENT):
            return None
    return approved + timedelta(seconds=AUTO_RUN_START_GRACE_SECONDS)
