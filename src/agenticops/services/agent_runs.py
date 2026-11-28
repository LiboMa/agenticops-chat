"""Agent runs on an issue while they are in flight: the ones a person asked for, and the plan run the pipeline itself
starts after a diagnosis passes its gate (MVP-2.9.0).

A person asks for a diagnosis (POST /api/health-issues/{id}/rca) or a fix plan (…/generate-fix-plan) and the agent
then works in a background thread for minutes. Nothing used to record that it had started: the page went on saying
«waits on you», a reload forgot the click, and a second click started a second agent on the same issue. The pipeline's
own plan run (services/pipeline_service.trigger_auto_sre) left no record either — with auto-fix on that is the common
path, and for those minutes the issue «waited on the agent» with no agent on record.

AgenticOps is ONE process (CLAUDE.md «Core trust»), so an in-process registry is the truth for «is an agent on this
issue»: the route claims the issue before it starts the thread, the thread releases it in its `finally`. A process
that dies takes its runs — and this registry — with it. One run per issue at a time, whichever agent: a plan written
while the diagnosis is being redone would be a plan for the old diagnosis. The timeline keeps the record:
`rca_started {trigger: manual}` / `fix_plan_requested {trigger: manual | auto}`.

A claim past the RCA watchdog (`rca_timeout_seconds`) is OVERDUE, not gone (MVP-2.9.0 N11): its thread may be alive
— a hung model call cannot be killed — so the live page keeps listing it, flagged. It no longer blocks: the next
`begin` takes the issue over, and the claim it replaced rides on the new one (`replaced`) so the caller can put
«abandoned» on the timeline. Until N11 an overdue claim simply read as no claim, and a second agent started beside
the first without a word.

`begin` is for a request that can be refused (a person's, the auto-diagnosis, an agent called from a chat). `take`
is for the pipeline's next stage and never is: the pipeline must not wait on, or be stopped by, this bookkeeping.
`enter` is what rca_agent / sre_agent call when they start: the claim their caller already holds (the Run Context
carries it), or a claim of their own — or a refusal when another run is on the issue.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from agenticops.config import settings
from agenticops.utils.timeutils import iso_z


@dataclass(frozen=True, eq=False)        # eq=False: a claim is itself, never «equal» to a later one for the same issue
class AgentRun:
    agent: str               # "rca" | "sre"
    issue_id: int
    requested_by: str        # the actor key of the person who asked
    started_at: datetime     # aware, UTC
    replaced: Optional["AgentRun"] = None    # the overdue claim this one took the issue over from, if any


PIPELINE = "agent:auto-pipeline"     # `requested_by` of a run the pipeline itself started (its Run Context actor)

_lock = threading.Lock()
_runs: dict[int, AgentRun] = {}


# `rca_timeout_seconds: 0` means «no watchdog» — it must not mean «a claim is never overdue»: a run whose thread hangs
# would then answer 409 to every request on its issue and keep it out of every person's queue until the process
# restarts (round-2 review B-m7). Without a watchdog a claim, and a diagnosis that started and never ended, is
# overdue after this long.
CLAIM_LIMIT_WITHOUT_WATCHDOG = 3600


def limit_seconds() -> float:
    """How long an agent run on an issue may take before it counts as overdue: the RCA watchdog's limit, or
    CLAIM_LIMIT_WITHOUT_WATCHDOG when there is no watchdog."""
    return float(settings.rca_timeout_seconds or 0) or float(CLAIM_LIMIT_WITHOUT_WATCHDOG)


def overdue(run: AgentRun, *, now: Optional[datetime] = None) -> bool:
    """Whether the run has outlived its limit: it may be hung, and no longer keeps the issue to itself."""
    return ((now or datetime.now(timezone.utc)) - run.started_at).total_seconds() >= limit_seconds()


def begin(agent: str, issue_id: int, requested_by: str, *, now: Optional[datetime] = None) -> Optional[AgentRun]:
    """Claim the issue for one agent run; None when a run on it is in flight and within its time limit (the route
    answers 409). An overdue claim is taken over: the new run's `replaced` names it."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        held = _runs.get(issue_id)
        if held is not None and not overdue(held, now=now):
            return None
        run = _runs[issue_id] = AgentRun(agent, issue_id, requested_by, now, replaced=held)
        return run


def in_time(issue_id: int, *, now: Optional[datetime] = None) -> Optional[AgentRun]:
    """The run in flight on this issue that is still within its time limit — «an agent is on it, leave it be»."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        run = _runs.get(issue_id)
    return run if run is not None and not overdue(run, now=now) else None


def log_replaced(run: Optional[AgentRun], *, by: str) -> None:
    """Say on the timeline that `run` took the issue over from a claim that had outlived its limit (best-effort)."""
    old = run.replaced if run is not None else None
    if old is None:
        return
    try:
        from agenticops.services.pipeline_events import log_event
        log_event(run.issue_id, "agent_run_abandoned", "rca" if old.agent == "rca" else "plan", "failed",
                  detail={"agent": old.agent, "started_at": iso_z(old.started_at),
                          "requested_by": old.requested_by, "replaced_by": by}, actor=by)
    except Exception:  # bookkeeping: never in the way of the run that is starting
        pass


def enter(agent: str, issue_id: int) -> tuple[Optional[AgentRun], bool]:
    """What an agent function holds when it starts: (the claim, whether it made it here and must release it).
    The caller's own claim — a route's or the pipeline's thread carries it in its Run Context — is used as it is.
    Otherwise the issue is claimed now (a run started from a chat, the CLI, a schedule); (None, False) when another
    run is on the issue and within its limit: the caller refuses."""
    from agenticops.run_context import get_run_context
    rc = get_run_context()
    with _lock:
        held = _runs.get(issue_id)
    if held is not None and held is rc.agent_run:
        return held, False
    run = begin(agent, issue_id, rc.actor or "system")
    if run is None:
        return None, False
    log_replaced(run, by=rc.actor or "system")
    return run, True


def take(agent: str, issue_id: int, requested_by: str, *, now: Optional[datetime] = None) -> AgentRun:
    """Claim the issue for the stage the pipeline starts next, whatever holds it now. The stage before it — a
    diagnosis that has just been saved — is ending; its own `end` then finds this claim in place and leaves it."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        run = _runs[issue_id] = AgentRun(agent, issue_id, requested_by, now)
        return run


def holds(run: Optional[AgentRun]) -> bool:
    """Whether `run` is still the claim on its issue. False once it was taken over (it had outlived its limit and
    somebody asked again): what such a run still produces is saved, but it hands the issue on to nobody — the issue
    belongs to the run that replaced it, or to whoever that run left it with (round-2 review B-I2)."""
    if run is None:
        return False
    with _lock:
        return _runs.get(run.issue_id) is run


def end(run: AgentRun) -> None:
    """Release a claim — only its own: a run that outlived the watchdog and was replaced does not free the new one."""
    with _lock:
        if _runs.get(run.issue_id) is run:
            del _runs[run.issue_id]


def may_note(run: Optional[AgentRun], actor) -> bool:
    """Whether `actor` may say a word to the run that holds the issue (MVP-2.9.0 N26). A run a PERSON asked for —
    from a page, a chat (which may be private), the IM bot — takes a word from that person and from an
    administrator. A run the pipeline started, and a run with no claim on record, from anyone who may write notes,
    as before. (Whether the account may write notes at all is the route's own check.)"""
    from agenticops.services.plan_content import HUMAN_ACTORS
    from agenticops.services.ui_actions import is_admin
    if run is None or not (run.requested_by or "").startswith(HUMAN_ACTORS):
        return True
    return run.requested_by == actor.key or is_admin(actor)


def refusal(issue_id: int) -> str:
    """What an agent function answers when another run is on the issue: who, which agent, since when."""
    held = get(issue_id)
    if held is None:
        return f"REJECTED: an agent run on issue #{issue_id} is in flight; wait for it to finish."
    left = ("the fix plan it is writing (get_plan)" if held.agent == "sre"
            else "the diagnosis it is making (get_health_issue)")
    return (f"REJECTED: the {held.agent} agent is already working on issue #{issue_id} "
            f"(asked by {held.requested_by}, since {held.started_at.isoformat(timespec='seconds').replace('+00:00', 'Z')}). "
            f"Wait for it to finish — one agent run per issue at a time. Do not start it again: tell the person it "
            f"is under way, and when it has finished read {left} instead.")


def get(issue_id: int, *, now: Optional[datetime] = None) -> Optional[AgentRun]:
    """The run claimed on this issue, if any — overdue or not (`overdue` / `in_time` tell them apart)."""
    with _lock:
        return _runs.get(issue_id)


def running(*, now: Optional[datetime] = None) -> list[AgentRun]:
    """Every claimed run, the oldest first — an overdue one too: its thread may still be alive."""
    with _lock:
        live = list(_runs.values())
    return sorted(live, key=lambda r: (r.started_at, r.issue_id))


def clear() -> None:
    """Forget every claim (tests)."""
    with _lock:
        _runs.clear()
