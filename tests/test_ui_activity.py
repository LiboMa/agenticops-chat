"""GET /api/ui/activity (MVP-2.9.0, NewUI «现场»): what agents are doing now, what is scheduled next, what ended lately.

Built only from state that can be checked — a run row that is running, a status that means «being worked on», a
manual run this process started — never from a guess. An `open` issue is not an agent at work.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import (Base, ChangeRequest, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult,
                               get_session)
from agenticops.services import activity, agent_runs

ALICE = Actor("user", "alice", 1, ("read", "write"))
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
ago = lambda **kw: NOW - timedelta(**kw)  # noqa: E731


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    import agenticops.galaxy.models  # noqa: F401
    import agenticops.scheduler.scheduler  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/act.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "rca_timeout_seconds", 900)
    monkeypatch.setattr(settings, "executor_total_timeout", 600)
    monkeypatch.setattr(settings, "change_review_timeout_seconds", 600)
    Base.metadata.create_all(models_mod.get_engine())
    agent_runs.clear()
    yield settings
    agent_runs.clear()


def _add(*rows):
    s = get_session()
    try:
        for r in rows:
            s.add(r); s.flush()
        ids = [r.id for r in rows]
        s.commit()
        return ids if len(ids) > 1 else ids[0]
    finally:
        s.close()


def _issue(status, title="t", account_id=None):
    return _add(HealthIssue(title=title, description="d", severity="high", source="test", status=status, resource_id="i-1",
                            account_id=account_id))


def _event(issue_id, event_type, at, detail=None, status="started"):
    return _add(PipelineEvent(health_issue_id=issue_id, event_type=event_type, stage="x", status=status,
                              detail=json.dumps(detail or {}), actor="system", created_at=at))


def _plan(issue_id, status="approved", created=None):
    rca = _add(RCAResult(health_issue_id=issue_id, root_cause="x", confidence=0.9, created_at=ago(days=3)))
    return _add(FixPlan(health_issue_id=issue_id, rca_result_id=rca, risk_level="L1", title="p", summary="s", status=status,
                        created_at=created or ago(days=3)))


def _change(status, updated, account_id=None, title="Tag web"):
    return _add(ChangeRequest(source="web", title=title, description="d", status=status, requested_by="user:alice",
                              risk_level="L1", account_id=account_id, updated_at=updated))


def _lanes(part="running", **kw):
    return activity.activity(ALICE, now=NOW, **kw)[part]


def _by_kind(lanes):
    return {l["kind"]: l for l in lanes}


def test_running_lanes_come_from_state_that_can_be_checked(db):
    from agenticops.galaxy.models import GalaxyBuild
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution
    diag = _issue("investigating", "disk full")
    _event(diag, "rca_started", ago(minutes=3))
    exe = _issue("fix_executing", "restart nginx")
    pid = _plan(exe, "executing")
    _add(FixExecution(fix_plan_id=pid, health_issue_id=exe, status="running", started_at=ago(minutes=2), created_at=ago(minutes=2)))
    review = _change("under_review", ago(minutes=1))
    crun = _change("executing", ago(minutes=4), title="Scale out")
    sid = _add(Schedule(name="security-posture", pipeline_name="SecurityPostureSnapshot", cron_expression="0 * * * *"))
    _add(ScheduleExecution(schedule_id=sid, status="running", started_at=ago(seconds=40)))
    build = _add(GalaxyBuild(status="running", trigger="auto", started_at=ago(minutes=5)))
    lanes = _by_kind(_lanes())
    assert set(lanes) == {"diagnosis", "run", "change_review", "change_run", "schedule", "graph_build"}
    assert lanes["diagnosis"] | {} == {
        "id": f"I{diag}:diagnosis", "kind": "diagnosis", "agent": "rca", "item": f"I{diag}", "ref": f"I#{diag}", "title": "disk full",
        "account_id": None, "since": "2026-11-17T11:57:00Z", "basis": "status", "requested_by": None, "overdue": False,
        "route": f"/app/issues/{diag}"}
    assert (lanes["run"]["item"], lanes["run"]["agent"], lanes["run"]["basis"], lanes["run"]["since"]) == (f"I{exe}", "executor", "run", "2026-11-17T11:58:00Z")
    assert (lanes["change_review"]["item"], lanes["change_review"]["agent"], lanes["change_review"]["route"]) == (f"C{review}", "sre", f"/app/changes/{review}")
    assert (lanes["change_run"]["item"], lanes["change_run"]["title"]) == (f"C{crun}", "Scale out")
    assert (lanes["schedule"]["id"], lanes["schedule"]["title"], lanes["schedule"]["item"], lanes["schedule"]["agent"]) == (f"S{sid}", "security-posture", None, "scheduler")
    assert (lanes["graph_build"]["id"], lanes["graph_build"]["agent"], lanes["graph_build"]["since"]) == (f"G{build}", "galaxy", "2026-11-17T11:55:00Z")


def test_an_open_issue_or_one_that_waits_on_a_person_is_not_an_agent_at_work(db):
    for status in ("open", "acknowledged", "root_cause_identified", "fix_planned", "fix_executed", "resolved", "dismissed"):
        _issue(status)
    _plan(_issue("fix_approved"))                       # approved, nothing started: it waits on a person
    _change("draft", ago(hours=1)); _change("planned", ago(hours=1)); _change("completed", ago(hours=1))
    assert _lanes() == []


def test_a_diagnosis_that_ended_while_the_status_stayed_is_not_an_agent_at_work(db):
    """An issue can be left at `investigating` after its diagnosis ended without a result (the timeline's
    rca_completed is newer than rca_started). Nothing is working on it: the lane says the diagnosis STOPPED, since
    when — it must not read «diagnosing for 42 days»."""
    stuck = _issue("investigating", title="left behind")
    _event(stuck, "rca_started", ago(days=42, minutes=1))
    _event(stuck, "rca_completed", ago(days=42), {"reason": "no_result"}, status="failed")
    retried = _issue("investigating", title="started again")
    _event(retried, "rca_started", ago(days=2))
    _event(retried, "rca_completed", ago(days=2) + timedelta(minutes=3), {"reason": "no_result"}, status="failed")
    _event(retried, "rca_started", ago(minutes=4))                       # a newer start: this one is at work
    by = {l["item"]: l for l in _lanes()}
    assert (by[f"I{stuck}"]["basis"], by[f"I{stuck}"]["kind"], by[f"I{stuck}"]["overdue"]) == ("stopped", "diagnosis", True)
    assert by[f"I{stuck}"]["since"] == "2026-10-06T12:00:00Z"            # when it ended
    assert (by[f"I{retried}"]["basis"], by[f"I{retried}"]["overdue"]) == ("status", False)
    assert by[f"I{retried}"]["since"] == "2026-11-17T11:56:00Z"


def test_a_run_a_person_asked_for_is_a_lane_with_who_asked(db):
    iid = _issue("root_cause_identified", "port 22 open")
    agent_runs.begin("sre", iid, "user:alice", now=ago(minutes=2))
    lane, = _lanes()
    assert (lane["id"], lane["kind"], lane["agent"], lane["basis"], lane["requested_by"], lane["since"]) == (
        f"I{iid}:plan", "plan", "sre", "requested", "user:alice", "2026-11-17T11:58:00Z")
    # the same issue also «investigating» is still ONE diagnosis lane — the request is the better evidence
    other = _issue("investigating")
    agent_runs.begin("rca", other, "user:bob", now=ago(minutes=1))
    assert sorted((l["id"], l["basis"]) for l in _lanes()) == [(f"I{iid}:plan", "requested"), (f"I{other}:diagnosis", "requested")]


def test_the_plan_run_the_pipeline_started_is_a_lane_that_says_so(db):
    """After a diagnosis passes its gate the pipeline hands the issue to the SRE agent (auto-fix on). The issue's
    status does not move while the plan is written, so nothing else can show that an agent is on it."""
    iid = _issue("root_cause_identified", title="gate passed")
    agent_runs.take("sre", iid, agent_runs.PIPELINE, now=ago(minutes=2))
    lane = _lanes()[0]
    assert (lane["id"], lane["kind"], lane["agent"], lane["basis"], lane["since"]) == (
        f"I{iid}:plan", "plan", "sre", "pipeline", "2026-11-17T11:58:00Z")
    assert lane["requested_by"] is None                    # nobody asked: the basis says who started it


def test_an_approved_plan_whose_run_started_is_a_run_lane(db):
    iid = _issue("fix_approved")
    pid = _plan(iid)
    _event(iid, "execution_started", ago(minutes=1), {"plan_id": pid})
    lane, = _lanes()
    assert (lane["kind"], lane["basis"], lane["since"]) == ("run", "event", "2026-11-17T11:59:00Z")
    _event(iid, "execution_completed", ago(seconds=20), {"plan_id": pid}, status="completed")
    assert _lanes() == []


def test_what_outlived_its_watchdog_is_marked_overdue(db):
    a = _issue("investigating"); _event(a, "rca_started", ago(seconds=901))
    b = _issue("investigating"); _event(b, "rca_started", ago(seconds=899))
    c = _issue("investigating")                                              # no start on record: since unknown, never «overdue»
    review = _change("under_review", ago(seconds=601))
    got = {l["id"]: (l["overdue"], l["since"] is not None) for l in _lanes()}
    assert got == {f"I{a}:diagnosis": (True, True), f"I{b}:diagnosis": (False, True), f"I{c}:diagnosis": (False, False),
                   f"C{review}:change_review": (True, True)}


def test_the_account_scope_keeps_its_own_work_and_the_jobs_that_belong_to_no_account(db):
    from agenticops.models import CloudAccount
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution
    acct, other = _add(CloudAccount(name="prod", provider="aws", credentials={}), CloudAccount(name="lab", provider="aws", credentials={}))
    mine = _issue("investigating", account_id=acct); theirs = _issue("investigating", account_id=other)
    _change("under_review", ago(minutes=1), account_id=other)
    sid = _add(Schedule(name="scan", pipeline_name="ResourceScan", cron_expression="0 * * * *"))
    _add(ScheduleExecution(schedule_id=sid, status="running", started_at=ago(seconds=10)))
    assert sorted(l["id"] for l in _lanes(account_id=acct)) == sorted([f"I{mine}:diagnosis", f"S{sid}"])
    assert len(_lanes()) == 4 and f"I{theirs}:diagnosis" in [l["id"] for l in _lanes()]


def test_upcoming_is_the_next_enabled_schedules(db):
    from agenticops.scheduler.scheduler import Schedule
    for name, at, on in (("late", NOW + timedelta(hours=5), True), ("soon", NOW + timedelta(minutes=5), True),
                         ("off", NOW + timedelta(minutes=1), False), ("past", ago(minutes=1), True), ("never", None, True)):
        _add(Schedule(name=name, pipeline_name="P", cron_expression="* * * * *", is_enabled=on, next_run_at=at))
    up = _lanes("upcoming")
    assert [(l["title"], l["at"]) for l in up] == [("soon", "2026-11-17T12:05:00Z"), ("late", "2026-11-17T17:00:00Z")]
    assert up[0]["kind"] == "schedule" and up[0]["agent"] == "scheduler"


def test_recent_is_what_ended_in_the_last_day_newest_first(db):
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution
    a = _issue("fix_executed", "restart nginx")
    pid = _plan(a, "executed", created=ago(hours=5))
    _add(FixExecution(fix_plan_id=pid, health_issue_id=a, status="succeeded", verification_status="pending_acceptance",
                      completed_at=ago(minutes=10), created_at=ago(minutes=12)))
    _add(FixExecution(fix_plan_id=pid, health_issue_id=a, status="failed", completed_at=ago(days=2), created_at=ago(days=2)))
    b = _issue("root_cause_identified", "disk full")
    _add(RCAResult(health_issue_id=b, root_cause="x", confidence=0.4, created_at=ago(minutes=30)))
    sid = _add(Schedule(name="scan", pipeline_name="ResourceScan", cron_expression="0 * * * *"))
    _add(ScheduleExecution(schedule_id=sid, status="failed", started_at=ago(hours=2), completed_at=ago(hours=2), error="boom"))
    recent = _lanes("recent")
    assert [(l["kind"], l["item"], l["outcome"], l["at"]) for l in recent] == [
        ("run", f"I{a}", "needs_you", "2026-11-17T11:50:00Z"),
        ("diagnosis", f"I{b}", "done", "2026-11-17T11:30:00Z"),
        ("schedule", None, "failed", "2026-11-17T10:00:00Z"),
        ("plan", f"I{a}", "done", "2026-11-17T07:00:00Z"),
    ]
    assert all(l["title"] for l in recent)


def test_recent_is_capped(db):
    iid = _issue("root_cause_identified")
    _add(*[RCAResult(health_issue_id=iid, root_cause="x", confidence=0.4, created_at=ago(minutes=m)) for m in range(1, 40)])
    assert len(_lanes("recent")) == activity.RECENT_MAX == 20


def test_a_scoped_recent_list_is_cut_after_the_scope_not_before(db):
    """Final review: the newest 20 were taken across every account and the scope applied afterwards — a quiet
    account beside a busy one saw an empty list."""
    busy, quiet = _issue("root_cause_identified", "busy", account_id=1), _issue("root_cause_identified", "quiet", account_id=2)
    _add(*[RCAResult(health_issue_id=busy, root_cause="x", confidence=0.4, created_at=ago(minutes=m)) for m in range(1, 26)])
    _add(RCAResult(health_issue_id=quiet, root_cause="x", confidence=0.4, created_at=ago(hours=3)),
         RCAResult(health_issue_id=quiet, root_cause="x", confidence=0.4, created_at=ago(hours=4)))
    pid = _plan(quiet, "executed", created=ago(days=2))
    _add(FixExecution(fix_plan_id=pid, health_issue_id=quiet, status="succeeded", verification_status="passed",
                      completed_at=ago(hours=5), created_at=ago(hours=5)))
    out = activity.activity(ALICE, now=NOW, account_id=2)
    assert [(l["kind"], l["item"]) for l in out["recent"]] == [("diagnosis", f"I{quiet}"), ("diagnosis", f"I{quiet}"), ("run", f"I{quiet}")]
    assert out["recent_total"] == {"work": 3, "schedules": 0}


def test_a_run_that_belongs_to_no_issue_takes_no_place_in_the_list(db):
    """A change plan's run has no issue: it has its own lane on the change, and is not an issue's «ended» row."""
    iid = _issue("fix_executed", "restart nginx")
    pid = _plan(iid, "executed", created=ago(days=2))
    _add(*[FixExecution(fix_plan_id=pid, health_issue_id=None, status="succeeded", completed_at=ago(minutes=m), created_at=ago(minutes=m))
           for m in range(1, 26)])
    _add(FixExecution(fix_plan_id=pid, health_issue_id=iid, status="succeeded", verification_status="passed",
                      completed_at=ago(hours=6), created_at=ago(hours=6)))
    out = activity.activity(ALICE, now=NOW)
    assert [(l["kind"], l["item"]) for l in out["recent"]] == [("run", f"I{iid}")]
    assert out["recent_total"]["work"] == 1


def test_schedule_runs_do_not_crowd_agent_work_out_and_the_cut_is_said(db):
    """With the default schedules about fifteen runs end every hour: twenty rows of one list covered eighty minutes,
    and a diagnosis from two hours ago was not under «ended in the last day»."""
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution
    iid = _issue("root_cause_identified", "disk full")
    _add(*[RCAResult(health_issue_id=iid, root_cause="x", confidence=0.4, created_at=ago(hours=h)) for h in (2, 5, 9)])
    sid = _add(Schedule(name="poll", pipeline_name="SecurityIncrementalPoll", cron_expression="*/10 * * * *"))
    _add(*[ScheduleExecution(schedule_id=sid, status="completed", started_at=ago(minutes=m), completed_at=ago(minutes=m))
           for m in range(1, 31)])
    out = activity.activity(ALICE, now=NOW)
    kinds = [l["kind"] for l in out["recent"]]
    assert kinds.count("diagnosis") == 3 and kinds.count("schedule") == activity.RECENT_SCHEDULES_MAX == 10
    assert out["recent_total"] == {"work": 3, "schedules": 30}                      # what the page needs to say «10 of 30»
    assert [l["at"] for l in out["recent"]] == sorted((l["at"] for l in out["recent"]), reverse=True)


def test_the_total_says_how_much_work_ended_when_the_list_is_cut(db):
    iid = _issue("root_cause_identified")
    _add(*[RCAResult(health_issue_id=iid, root_cause="x", confidence=0.4, created_at=ago(minutes=m)) for m in range(1, 40)])
    out = activity.activity(ALICE, now=NOW)
    assert len(out["recent"]) == 20 and out["recent_total"] == {"work": 39, "schedules": 0}


def test_a_running_graph_build_is_listed_without_loading_its_graph(db):
    """The running build's row holds the whole rule graph while the model phase runs; the lane needs three columns."""
    from agenticops.galaxy.models import GalaxyBuild
    bid = _add(GalaxyBuild(status="running", trigger="manual", started_at=ago(minutes=4)))
    import agenticops.models as models_mod
    seen = []
    eng = models_mod.get_engine()
    listener = lambda conn, cur, statement, *a: seen.append(statement)  # noqa: E731
    event.listen(eng, "before_cursor_execute", listener)
    try:
        lanes = activity.activity(ALICE, now=NOW)["running"]
    finally:
        event.remove(eng, "before_cursor_execute", listener)
    assert [(l["id"], l["kind"], l["since"]) for l in lanes] == [(f"G{bid}", "graph_build", "2026-11-17T11:56:00Z")]
    build_sql = [q for q in seen if "galaxy_builds" in q]
    assert build_sql and all("rule_graph" not in q for q in build_sql)


def test_it_reads_in_a_bounded_number_of_queries(db):
    import agenticops.models as models_mod
    for i in range(12):
        iid = _issue("investigating"); _event(iid, "rca_started", ago(minutes=i + 1))
        _change("under_review", ago(minutes=i + 1))
    counted = []
    eng = models_mod.get_engine()
    listener = lambda *a: counted.append(1)  # noqa: E731
    event.listen(eng, "before_cursor_execute", listener)
    try:
        out = activity.activity(ALICE, now=NOW)
    finally:
        event.remove(eng, "before_cursor_execute", listener)
    assert len(out["running"]) == 24 and len(counted) <= 18


def test_the_endpoint_serves_any_signed_in_user_and_nobody_else(db):
    from types import SimpleNamespace
    from agenticops.web import deps
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    _issue("investigating", "disk full")
    client = TestClient(app)
    assert client.get("/api/ui/activity").status_code == 401                      # not signed in
    viewer = Actor("user", "rita", 4, ("read",))
    app.dependency_overrides[deps.current_actor] = lambda: viewer
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=4)
    try:
        body = client.get("/api/ui/activity").json()                             # a read-only account may look
        assert set(body) == {"running", "upcoming", "recent", "recent_total", "generated_at"} and body["generated_at"].endswith("Z")
        assert [l["title"] for l in body["running"]] == ["disk full"]
        assert client.get("/api/ui/activity?account_id=0").status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_a_run_lane_names_its_run_record_and_says_when_a_person_stopped_it(db):
    """MVP-2.9.0 N9: «现场» can only stop a run it can name — and must say so when somebody already did."""
    exe = _issue("fix_executing", "restart nginx")
    pid = _plan(exe, "executing")
    ex = _add(FixExecution(fix_plan_id=pid, health_issue_id=exe, status="running", started_at=ago(minutes=2), created_at=ago(minutes=2)))
    crun = _change("executing", ago(minutes=4), title="Scale out")
    cplan = _add(FixPlan(plan_kind="change", change_request_id=crun, risk_level="L1", title="p", summary="s", status="executing"))
    cex = _add(FixExecution(fix_plan_id=cplan, status="running", started_at=ago(minutes=4), created_at=ago(minutes=4),
                            stop_requested_at=ago(seconds=30), stop_requested_by="user:alice"))
    diag = _issue("investigating", "disk full")
    _event(diag, "rca_started", ago(minutes=3))
    lanes = _by_kind(_lanes())
    assert lanes["run"]["execution"] == {"id": ex, "status": "running", "stop_requested_at": None, "stop_requested_by": None}
    assert lanes["change_run"]["execution"] == {"id": cex, "status": "running", "stop_requested_at": "2026-11-17T11:59:30Z",
                                                "stop_requested_by": "user:alice"}
    assert "execution" not in lanes["diagnosis"]                     # only a run has a run record
