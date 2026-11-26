"""Ask the diagnosis or the plan agent to work on an issue — POST /api/health-issues/{id}/rca and
/generate-fix-plan, the claim, the background run (split from web/app.py)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from agenticops.auth.actor import Actor
from agenticops.models import FixPlan, get_db_session, HealthIssue, RCAResult
from agenticops.utils.timeutils import iso_z
from agenticops.web.deps import current_actor
from agenticops.web.schemas import RCAResponse

router = APIRouter()
logger = logging.getLogger(__name__)


_ISSUE_AGENT_LABELS = {
    "rca": ("RCA triggered", "RCA trigger failed"),
    "sre": ("Fix plan generated", "Fix plan generation failed"),
}


# What a manual agent run leaves on the issue's timeline (MVP-2.9.0): (event, stage) when it is asked for, and
# (event, stage) when the agent call itself fails — a finished diagnosis / plan writes its own events.
_ISSUE_AGENT_EVENTS = {
    "rca": (("rca_started", "rca"), ("rca_completed", "rca")),
    "sre": (("fix_plan_requested", "plan"), ("fix_plan_requested", "plan")),
}


def _invoke_issue_agent(agent_name: str, issue_id: int):
    """The agent call of a manual trigger, on its own so a test can stand in for the model."""
    if agent_name == "rca":
        from agenticops.agents.rca_agent import rca_agent as agent
    else:
        from agenticops.agents.sre_agent import sre_agent as agent
    return agent(issue_id=issue_id)


def _run_issue_agent(agent_name: str, issue_id: int, trace_id: Optional[str], on_behalf_of: str, run=None) -> None:
    """Thread target for the manual RCA / fix-plan triggers (POST /api/health-issues/{id}/rca and
    /generate-fix-plan). ContextVars do not cross threading.Thread, so THIS thread sets the issue's trace
    and a Run Context — agent:rca | agent:sre acting on behalf of the requesting web actor — and resets
    both in finally (the pipeline-thread pattern of rca_service / pipeline_service). Failures are logged
    and written to the timeline, never raised out of the thread. `run` is the route's claim on the issue
    (services/agent_runs): released here, whatever happened."""
    from agenticops.config import set_trace_id
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    _tid_token = set_trace_id(trace_id)
    _rc_token = set_run_context(RunContext(actor=f"agent:{agent_name}", on_behalf_of=on_behalf_of,
                                           trace_id=trace_id, agent_name=agent_name, agent_run=run))
    done_label, failed_label = _ISSUE_AGENT_LABELS[agent_name]
    try:
        result = _invoke_issue_agent(agent_name, issue_id)
        logger.info("%s for issue #%d: %s", done_label, issue_id, str(result)[:200])
    except Exception:
        logger.exception("%s for issue #%d", failed_label, issue_id)
        from agenticops.services.pipeline_events import log_event
        event, stage = _ISSUE_AGENT_EVENTS[agent_name][1]
        log_event(issue_id, event, stage, "failed", detail={"trigger": "manual", "reason": "agent error"},
                  actor=f"agent:{agent_name}", trace_id=trace_id)
    finally:
        if run is not None:
            from agenticops.services import agent_runs
            agent_runs.end(run)
        reset_run_context(_rc_token)
        _tid_token.var.reset(_tid_token)  # contextvars.Token.var is the ContextVar the token came from


def claim_issue(agent_name: str, issue_id: int, actor: Actor):
    """(the claim, None) — or (None, the 409 `agent_run_in_flight` answer) while an agent is on this issue and
    within its time limit."""
    from agenticops.services import agent_runs
    run = agent_runs.begin(agent_name, issue_id, actor.key)
    if run is not None:
        return run, None
    busy = agent_runs.get(issue_id)
    return None, JSONResponse(status_code=409, content={
        "detail": f"An agent is already working on issue #{issue_id}; wait for it to finish.",
        "code": "agent_run_in_flight",
        "agent": busy.agent if busy else agent_name,
        "started_at": iso_z(busy.started_at) if busy else None,
        "requested_by": busy.requested_by if busy else None,
    })


def launch_issue_agent(agent_name: str, issue_id: int, trace_id: Optional[str], actor: Actor, run,
                        detail: Optional[dict] = None) -> None:
    """Write the request onto the issue's timeline and start the agent thread under `run`, the caller's claim —
    released here when the thread cannot start (the thread releases it otherwise; one that never started never
    would). `detail` adds to the event what the request was about."""
    import threading
    from agenticops.services import agent_runs
    from agenticops.services.pipeline_events import log_event
    event, stage = _ISSUE_AGENT_EVENTS[agent_name][0]
    prefix = "rca-trigger" if agent_name == "rca" else "fixplan-trigger"
    try:
        agent_runs.log_replaced(run, by=actor.key)     # it took the issue over from a run past its limit: say so (N11)
        log_event(issue_id, event, stage, "started", detail={"trigger": "manual", "requested_by": actor.key, **(detail or {})},
                  actor=actor.key, trace_id=trace_id)
        threading.Thread(target=_run_issue_agent, args=(agent_name, issue_id, trace_id, actor.key, run),
                         daemon=True, name=f"{prefix}-{issue_id}").start()
    except BaseException:
        agent_runs.end(run)
        raise


def _start_issue_agent(agent_name: str, issue_id: int, trace_id: Optional[str], actor: Actor):
    """Claim the issue, write the request onto its timeline and start the agent thread — or answer 409 when an
    agent a person asked for is still working on this issue (MVP-2.9.0: a second click started a second agent)."""
    run, busy = claim_issue(agent_name, issue_id, actor)
    if busy is not None:
        return busy
    launch_issue_agent(agent_name, issue_id, trace_id, actor, run)
    return None


@router.post("/api/health-issues/{issue_id}/rca", response_model=RCAResponse, status_code=202)
def api_trigger_rca(issue_id: int, actor: Actor = Depends(current_actor)):
    """Trigger RCA analysis for a health issue via the rca_agent. A plain `def` (so are its aliases): it writes the
    start record, and a database write must not wait for a lock on the event loop.

    Runs the rca_agent in a background thread (agent:rca on behalf of the requesting actor,
    under the issue's trace) and returns immediately. 409 `agent_run_in_flight` while an agent a person
    asked for is still working on this issue (MVP-2.9.0).
    """
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")
        issue_trace_id = issue.trace_id

    busy = _start_issue_agent("rca", issue_id, issue_trace_id, actor)
    if busy is not None:
        return busy

    # Return a placeholder — the RCA will be available after the agent completes
    return JSONResponse(
        status_code=202,
        content={
            "message": f"RCA analysis triggered for issue #{issue_id}. Refresh to see results.",
            "health_issue_id": issue_id,
        },
    )


@router.post("/api/health-issues/{issue_id}/generate-fix-plan", status_code=202)
def api_trigger_fix_plan(issue_id: int, actor: Actor = Depends(current_actor)):
    """Trigger fix plan generation for a health issue via the sre_agent.

    Requires an existing RCA result. Runs sre_agent in a background thread (agent:sre on behalf
    of the requesting actor, under the issue's trace). 409 `agent_run_in_flight` while an agent a person
    asked for is still working on this issue (MVP-2.9.0).
    """
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")
        issue_trace_id = issue.trace_id

        rca = (
            session.query(RCAResult)
            .filter_by(health_issue_id=issue_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )
        if not rca:
            raise HTTPException(status_code=400, detail="No RCA result found. Run RCA first.")

        # Guard: reject if issue has a locked fix plan (pending_approval/approved/executing)
        from agenticops.models import FIXPLAN_LOCKED_STATUSES
        locked = (
            session.query(FixPlan)
            .filter_by(health_issue_id=issue_id)
            .filter(FixPlan.status.in_(FIXPLAN_LOCKED_STATUSES))
            .first()
        )
        if locked:
            raise HTTPException(
                status_code=409,
                detail=f"Issue #{issue_id} already has FixPlan #{locked.id} in '{locked.status}' state. "
                       f"Wait for it to complete or reject it first.",
            )

    busy = _start_issue_agent("sre", issue_id, issue_trace_id, actor)
    if busy is not None:
        return busy

    return JSONResponse(
        status_code=202,
        content={
            "message": f"Fix plan generation triggered for issue #{issue_id}. Refresh to see results.",
            "health_issue_id": issue_id,
        },
    )
