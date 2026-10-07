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


def issue_phase(status: str, *, rca: Any = UNKNOWN, threshold: Any = None, plan: Any = UNKNOWN,
                latest_run: Any = UNKNOWN, auto_run_in_flight: bool = False,
                auto_fix_enabled: Optional[bool] = None) -> Phase:
    run = None if latest_run is UNKNOWN else latest_run
    if status in ("open", "investigating", "acknowledged"):
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
        if _get(rca, "human_verdict") == "correct":
            return Phase("toGenerate", "you", "generatePlan")
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
