"""What agents are doing now, what is scheduled next, and what ended lately (MVP-2.9.0, NewUI «现场»).

Built only from state that can be checked:

  running   a run a person asked for that this process is still on (services/agent_runs); an issue whose status
            says it is being diagnosed (`investigating`) or executed (`fix_executing`); a fix run row that is pending
            or running; an approved plan whose run has started (the timeline's execution_started with no end yet);
            a change under review or executing; a schedule run that is running; a graph build that is running
  upcoming  the next runs of the enabled schedules
  recent    fix runs, diagnoses, fix plans and schedule runs that ended in the last day

An `open` issue is NOT an agent at work — hundreds of them wait for nothing. `since` is when the work started, or
null when nothing on record says; `overdue` marks work that outlived its own watchdog, so a stuck one stands out.
`basis` says how we know. No model call, no cloud call, a fixed number of queries.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from agenticops.config import settings
from agenticops.models import ChangeRequest, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult, get_db_session
from agenticops.services import agent_runs
from agenticops.services import work_phases as wp

RECENT_HOURS = 24
RECENT_MAX = 20
UPCOMING_MAX = 5
GRAPH_BUILD_LIMIT_SECONDS = 1800          # a build takes minutes; one still «running» after this is stuck
_RUN_IN_FLIGHT = ("pending", "running")
_AGENT_KIND = {"rca": "diagnosis", "sre": "plan"}


def _aware(ts: Optional[datetime]) -> Optional[datetime]:
    return None if ts is None else (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))


def _iso(ts: Optional[datetime]) -> Optional[str]:
    ts = _aware(ts)
    return None if ts is None else ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ref(item: Optional[str]) -> Optional[str]:
    return f"{item[0]}#{item[1:]}" if item else None


def _route(item: Optional[str]) -> Optional[str]:
    if not item:
        return None
    return f"/app/issues/{item[1:]}" if item[0] == "I" else f"/app/changes/{item[1:]}"


def _lane(lane_id: str, kind: str, agent: str, title: str, *, now: datetime, basis: str, item: Optional[str] = None,
          account_id: Optional[int] = None, since: Optional[datetime] = None, limit: Optional[float] = None,
          requested_by: Optional[str] = None, route: Optional[str] = None) -> dict:
    since = _aware(since)
    return {"id": lane_id, "kind": kind, "agent": agent, "item": item, "ref": _ref(item), "title": title,
            "account_id": account_id, "since": _iso(since), "basis": basis, "requested_by": requested_by,
            "overdue": bool(since is not None and limit and (now - since).total_seconds() > limit),
            "route": route if route is not None else _route(item)}


def _newest(events, issue_id: int, event_type: str) -> Optional[datetime]:
    times = [_aware(e.created_at) for e in events.get(issue_id, []) if e.event_type == event_type]
    return max((t for t in times if t is not None), default=None)


def activity(actor, *, account_id: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """The three lists for this actor. Every signed-in person may read it (issue and change titles are not private);
    `account_id` keeps that account's work and the jobs that belong to no account (schedules, graph builds)."""
    from agenticops.galaxy.models import GalaxyBuild
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution

    now = now or datetime.now(timezone.utc)
    since_recent = now - timedelta(hours=RECENT_HOURS)
    rca_limit, run_limit = settings.rca_timeout_seconds, settings.executor_total_timeout
    running: list[dict] = []
    recent: list[dict] = []
    with get_db_session() as s:
        moving = s.query(HealthIssue).filter(HealthIssue.status.in_(("investigating", "fix_executing", "fix_approved")))
        if account_id is not None:
            moving = moving.filter(HealthIssue.account_id == account_id)
        issues = {i.id: i for i in moving.all()}
        events: dict[int, list] = {}
        if issues:
            for e in s.query(PipelineEvent).filter(
                    PipelineEvent.health_issue_id.in_(list(issues)),
                    PipelineEvent.event_type.in_(("rca_started", "execution_started", "execution_completed"))):
                events.setdefault(e.health_issue_id, []).append(e)
        approved = [i for i in issues.values() if i.status == "fix_approved"]
        plans: dict[int, list] = {}
        if approved:
            for p in s.query(FixPlan).filter(FixPlan.health_issue_id.in_([i.id for i in approved]), FixPlan.plan_kind == "fix"):
                plans.setdefault(p.health_issue_id, []).append(p)
        run_rows = s.query(FixExecution).filter(FixExecution.status.in_(_RUN_IN_FLIGHT)).all()
        manual = agent_runs.running(now=now)

        ended_runs = (s.query(FixExecution).filter(FixExecution.completed_at >= since_recent,
                                                   FixExecution.status.notin_(_RUN_IN_FLIGHT))
                      .order_by(FixExecution.completed_at.desc()).limit(RECENT_MAX).all())
        new_rcas = (s.query(RCAResult).filter(RCAResult.created_at >= since_recent)
                    .order_by(RCAResult.created_at.desc()).limit(RECENT_MAX).all())
        new_plans = (s.query(FixPlan).filter(FixPlan.created_at >= since_recent, FixPlan.plan_kind == "fix")
                     .order_by(FixPlan.created_at.desc()).limit(RECENT_MAX).all())

        # every issue named above that is not loaded yet, in one query
        wanted = ({r.issue_id for r in manual} | {x.health_issue_id for x in (*run_rows, *ended_runs, *new_rcas, *new_plans)}) - {None}
        missing = wanted - set(issues)
        named = dict(issues)
        if missing:
            named.update({i.id: i for i in s.query(HealthIssue).filter(HealthIssue.id.in_(missing))})

        def mine(issue_id) -> Optional[HealthIssue]:
            issue = named.get(issue_id)
            return issue if issue is not None and (account_id is None or issue.account_id == account_id) else None

        taken: set[int] = set()        # issues that already have their lane: the best evidence wins
        for r in manual:               # a person asked, this process is on it
            issue = mine(r.issue_id)
            if issue is None:
                continue
            taken.add(issue.id)
            running.append(_lane(f"I{issue.id}:{_AGENT_KIND.get(r.agent, r.agent)}", _AGENT_KIND.get(r.agent, r.agent), r.agent,
                                 issue.title, now=now, basis="requested", item=f"I{issue.id}", account_id=issue.account_id,
                                 since=r.started_at, requested_by=r.requested_by))
        for x in run_rows:             # a run row that is pending or running
            issue = mine(x.health_issue_id)
            if issue is None or issue.id in taken:
                continue
            taken.add(issue.id)
            running.append(_lane(f"I{issue.id}:run", "run", "executor", issue.title, now=now, basis="run", item=f"I{issue.id}",
                                 account_id=issue.account_id, since=x.started_at or x.created_at, limit=run_limit))
        for issue in issues.values():
            if issue.id in taken:
                continue
            if issue.status == "investigating":
                running.append(_lane(f"I{issue.id}:diagnosis", "diagnosis", "rca", issue.title, now=now, basis="status",
                                     item=f"I{issue.id}", account_id=issue.account_id,
                                     since=_newest(events, issue.id, "rca_started"), limit=rca_limit))
            elif issue.status == "fix_executing":
                running.append(_lane(f"I{issue.id}:run", "run", "executor", issue.title, now=now, basis="status",
                                     item=f"I{issue.id}", account_id=issue.account_id,
                                     since=_newest(events, issue.id, "execution_started"), limit=run_limit))
            else:                      # approved: a lane only when the timeline says its run has started and not ended
                plan = wp.current_fix_plan(plans.get(issue.id, []))
                started = None if plan is None or plan.status != "approved" else wp.in_flight_auto_run(
                    events.get(issue.id, []), plan.id, timeout_seconds=run_limit, now=now)
                if started is not None:
                    running.append(_lane(f"I{issue.id}:run", "run", "executor", issue.title, now=now, basis="event",
                                         item=f"I{issue.id}", account_id=issue.account_id, since=started, limit=run_limit))

        if settings.change_management_enabled:
            changes = s.query(ChangeRequest).filter(ChangeRequest.status.in_(("under_review", "executing")))
            if account_id is not None:
                changes = changes.filter(ChangeRequest.account_id == account_id)
            for cr in changes:
                review = cr.status == "under_review"
                running.append(_lane(f"C{cr.id}:{'change_review' if review else 'change_run'}",
                                     "change_review" if review else "change_run", "sre" if review else "executor", cr.title,
                                     now=now, basis="status", item=f"C{cr.id}", account_id=cr.account_id,
                                     since=cr.updated_at or cr.created_at,
                                     limit=settings.change_review_timeout_seconds if review else run_limit))

        for ex, schedule in (s.query(ScheduleExecution, Schedule).join(Schedule, Schedule.id == ScheduleExecution.schedule_id)
                             .filter(ScheduleExecution.status.in_(("running", "retrying")))):
            running.append(_lane(f"S{schedule.id}", "schedule", "scheduler", schedule.name, now=now, basis="schedule",
                                 since=ex.started_at, route=f"/app/schedules/{schedule.id}"))
        for build in s.query(GalaxyBuild).filter(GalaxyBuild.status == "running"):
            running.append(_lane(f"G{build.id}", "graph_build", "galaxy", f"build #{build.id} ({build.trigger})", now=now,
                                 basis="build", since=build.started_at, limit=GRAPH_BUILD_LIMIT_SECONDS, route="/app/galaxy"))

        upcoming = [{"id": f"S{sc.id}", "kind": "schedule", "agent": "scheduler", "title": sc.name, "at": _iso(sc.next_run_at),
                     "route": f"/app/schedules/{sc.id}"}
                    for sc in (s.query(Schedule).filter(Schedule.is_enabled.is_(True), Schedule.next_run_at > now)
                               .order_by(Schedule.next_run_at, Schedule.id).limit(UPCOMING_MAX))]

        def ended(lane_id, kind, agent, issue_id, at, outcome):
            issue = mine(issue_id)
            if issue is not None:
                recent.append({"id": lane_id, "kind": kind, "agent": agent, "item": f"I{issue.id}", "ref": f"I#{issue.id}",
                               "title": issue.title, "account_id": issue.account_id, "at": _iso(at), "outcome": outcome,
                               "route": f"/app/issues/{issue.id}"})

        for x in ended_runs:
            ok = x.status in ("succeeded", "success")
            ended(f"X{x.id}", "run", "executor", x.health_issue_id, x.completed_at,
                  "failed" if not ok or x.verification_status == "failed" else "done" if x.verification_status == "passed" else "needs_you")
        for r in new_rcas:
            ended(f"R{r.id}", "diagnosis", "rca", r.health_issue_id, r.created_at, "done")
        for p in new_plans:
            ended(f"P{p.id}", "plan", "sre", p.health_issue_id, p.created_at, "done")
        for ex, schedule in (s.query(ScheduleExecution, Schedule).join(Schedule, Schedule.id == ScheduleExecution.schedule_id)
                             .filter(ScheduleExecution.completed_at >= since_recent,
                                     ScheduleExecution.status.notin_(("running", "retrying")))
                             .order_by(ScheduleExecution.completed_at.desc()).limit(RECENT_MAX)):
            recent.append({"id": f"SE{ex.id}", "kind": "schedule", "agent": "scheduler", "item": None, "ref": None,
                           "title": schedule.name, "account_id": None, "at": _iso(ex.completed_at),
                           "outcome": "done" if ex.status == "completed" else "failed", "route": f"/app/schedules/{schedule.id}"})

    running.sort(key=lambda l: (l["since"] is None, l["since"] or "", l["id"]))      # the longest-running first
    recent.sort(key=lambda l: (l["at"] or "", l["id"]), reverse=True)
    return {"running": running, "upcoming": upcoming, "recent": recent[:RECENT_MAX], "generated_at": _iso(now)}
