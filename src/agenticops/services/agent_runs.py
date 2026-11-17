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
while the diagnosis is being redone would be a plan for the old diagnosis. A claim older than the RCA watchdog
(`rca_timeout_seconds`) is abandoned, so a hung model call cannot block an issue for good. The timeline keeps the
record: `rca_started {trigger: manual}` / `fix_plan_requested {trigger: manual | auto}`.

`begin` is for a person's request and can be refused. `take` is for the pipeline's next stage and never is: the
pipeline must not wait on, or be stopped by, this bookkeeping.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from agenticops.config import settings


@dataclass(frozen=True, eq=False)        # eq=False: a claim is itself, never «equal» to a later one for the same issue
class AgentRun:
    agent: str               # "rca" | "sre"
    issue_id: int
    requested_by: str        # the actor key of the person who asked
    started_at: datetime     # aware, UTC


PIPELINE = "agent:auto-pipeline"     # `requested_by` of a run the pipeline itself started (its Run Context actor)

_lock = threading.Lock()
_runs: dict[int, AgentRun] = {}


def _live(run: Optional[AgentRun], now: datetime) -> Optional[AgentRun]:
    ttl = float(settings.rca_timeout_seconds or 0)
    if run is None or (ttl > 0 and (now - run.started_at).total_seconds() >= ttl):
        return None
    return run


def begin(agent: str, issue_id: int, requested_by: str, *, now: Optional[datetime] = None) -> Optional[AgentRun]:
    """Claim the issue for one agent run; None when a run on it is still in flight (the route answers 409)."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        if _live(_runs.get(issue_id), now) is not None:
            return None
        run = _runs[issue_id] = AgentRun(agent, issue_id, requested_by, now)
        return run


def take(agent: str, issue_id: int, requested_by: str, *, now: Optional[datetime] = None) -> AgentRun:
    """Claim the issue for the stage the pipeline starts next, whatever holds it now. The stage before it — a
    diagnosis that has just been saved — is ending; its own `end` then finds this claim in place and leaves it."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        run = _runs[issue_id] = AgentRun(agent, issue_id, requested_by, now)
        return run


def end(run: AgentRun) -> None:
    """Release a claim — only its own: a run that outlived the watchdog and was replaced does not free the new one."""
    with _lock:
        if _runs.get(run.issue_id) is run:
            del _runs[run.issue_id]


def get(issue_id: int, *, now: Optional[datetime] = None) -> Optional[AgentRun]:
    """The run in flight on this issue, if any."""
    with _lock:
        return _live(_runs.get(issue_id), now or datetime.now(timezone.utc))


def running(*, now: Optional[datetime] = None) -> list[AgentRun]:
    """Every run in flight, the oldest first."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        live = [r for r in _runs.values() if _live(r, now) is not None]
    return sorted(live, key=lambda r: (r.started_at, r.issue_id))


def clear() -> None:
    """Forget every claim (tests)."""
    with _lock:
        _runs.clear()
