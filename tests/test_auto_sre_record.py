"""MVP-2.9.0: the plan-writing run the pipeline itself starts is on record too.

A diagnosis that passes the gate hands the issue to the SRE agent (services/pipeline_service.trigger_auto_sre). With
auto-fix on that is the common path, and nothing recorded that the agent had started: for the minutes it takes the
issue «waits on the agent» with no agent on record, the live page shows nothing, and a person pressing «generate the
plan» starts a second agent on the same issue. The pipeline now claims the issue (services/agent_runs) and writes
`fix_plan_requested {trigger: auto}` — bookkeeping only: it never refuses or delays the pipeline's own next stage.
"""
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, FixPlan, HealthIssue, PipelineEvent, RCAResult, get_session
from agenticops.services import agent_runs

T0 = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    agent_runs.clear()
    yield
    agent_runs.clear()


class TestTake:
    def test_the_pipeline_takes_the_issue_from_the_stage_that_is_ending(self):
        """The diagnosis a person asked for has just been saved; its thread is still wrapping up when the gate hands
        the issue on. The plan run takes the claim, and the diagnosis ending a moment later does not free it."""
        rca = agent_runs.begin("rca", 12, "user:alice", now=T0)
        sre = agent_runs.take("sre", 12, agent_runs.PIPELINE, now=T0 + timedelta(seconds=90))
        assert (sre.agent, sre.issue_id, sre.requested_by) == ("sre", 12, "agent:auto-pipeline")
        assert agent_runs.get(12, now=T0 + timedelta(seconds=91)) is sre
        agent_runs.end(rca)
        assert agent_runs.get(12, now=T0 + timedelta(seconds=92)) is sre
        assert agent_runs.begin("sre", 12, "user:bob", now=T0 + timedelta(seconds=93)) is None      # a person cannot start a second one
        agent_runs.end(sre)
        assert agent_runs.get(12, now=T0 + timedelta(seconds=94)) is None

    def test_a_taken_claim_is_overdue_after_the_watchdog_like_any_other(self, monkeypatch):
        """MVP-2.9.0 N11: past its limit a claim is kept (its thread may be alive) but no longer keeps the issue to
        itself — until then it simply read as no claim."""
        from agenticops.config import settings
        monkeypatch.setattr(settings, "rca_timeout_seconds", 900)
        run = agent_runs.take("sre", 12, agent_runs.PIPELINE, now=T0)
        late = T0 + timedelta(seconds=900)
        assert agent_runs.get(12, now=late) is run and agent_runs.overdue(run, now=late)
        assert agent_runs.in_time(12, now=late) is None
        assert agent_runs.begin("sre", 12, "user:alice", now=late).replaced is run


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/auto-sre.db")
    monkeypatch.setattr(settings, "auto_fix_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    yield
    models_mod._engine = None


def _issue(plan=None):
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status="root_cause_identified", resource_id="i-1")
        s.add(issue); s.flush()
        r = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(r); s.flush()
        if plan:
            s.add(FixPlan(health_issue_id=issue.id, rca_result_id=r.id, risk_level="L1", title="p", summary="s", status=plan))
        s.commit()
        return issue.id
    finally:
        s.close()


def _events(issue_id):
    s = get_session()
    try:
        return [(e.event_type, e.status, e.actor, json.loads(e.detail) if isinstance(e.detail, str) else e.detail) for e in
                s.query(PipelineEvent).filter_by(health_issue_id=issue_id).order_by(PipelineEvent.id)]
    finally:
        s.close()


class _Sre:
    """Stands in for the SRE agent: blocks until released, so a test can look at the world while it «runs»."""
    def __init__(self, monkeypatch, fail=False):
        import agenticops.agents.sre_agent as sre_mod
        self.started, self.release, self.calls, self.fail = threading.Event(), threading.Event(), [], fail
        monkeypatch.setattr(sre_mod, "sre_agent", self)

    def __call__(self, issue_id):
        self.calls.append(issue_id)
        self.started.set()
        assert self.release.wait(10)
        if self.fail:
            raise RuntimeError("model unavailable")
        return "plan saved"

    def finish(self):
        self.release.set()
        for t in threading.enumerate():
            if t.name.startswith("auto-sre-"):
                t.join(10)


def test_the_run_the_pipeline_starts_is_on_record_while_it_works(db, monkeypatch):
    from agenticops.services.pipeline_service import trigger_auto_sre
    iid = _issue()
    sre = _Sre(monkeypatch)
    trigger_auto_sre(iid)
    assert sre.started.wait(10)
    run = agent_runs.get(iid)
    assert run is not None and (run.agent, run.requested_by) == ("sre", "agent:auto-pipeline")
    asked = [(s, a, d) for t, s, a, d in _events(iid) if t == "fix_plan_requested"]
    assert asked == [("started", "agent:auto-pipeline", {"trigger": "auto"})]
    sre.finish()
    assert agent_runs.get(iid) is None and sre.calls == [iid]


def test_a_person_cannot_start_a_second_plan_run_meanwhile(db, monkeypatch):
    from agenticops.services.pipeline_service import trigger_auto_sre
    from agenticops.web.app import app
    iid = _issue()
    sre = _Sre(monkeypatch)
    trigger_auto_sre(iid)
    assert sre.started.wait(10)
    again = TestClient(app).post(f"/api/health-issues/{iid}/generate-fix-plan")
    assert again.status_code == 409 and again.json()["code"] == "agent_run_in_flight"
    assert again.json()["agent"] == "sre" and again.json()["requested_by"] == "agent:auto-pipeline"
    sre.finish()
    assert sre.calls == [iid]


def test_a_failed_run_frees_the_issue_and_says_so_on_the_timeline(db, monkeypatch):
    from agenticops.services.pipeline_service import trigger_auto_sre
    iid = _issue()
    sre = _Sre(monkeypatch, fail=True)
    trigger_auto_sre(iid)
    assert sre.started.wait(10)
    sre.finish()
    assert agent_runs.get(iid) is None
    assert [(s, d) for t, s, _a, d in _events(iid) if t == "fix_plan_requested"] == [
        ("started", {"trigger": "auto"}), ("failed", {"trigger": "auto", "reason": "agent error"})]


def test_a_thread_that_cannot_start_does_not_leave_the_issue_claimed(db, monkeypatch):
    from unittest.mock import patch
    from agenticops.services.pipeline_service import trigger_auto_sre
    iid = _issue()
    with patch("threading.Thread") as thread:
        thread.return_value.start.side_effect = RuntimeError("can't start new thread")
        with pytest.raises(RuntimeError):
            trigger_auto_sre(iid)
    assert agent_runs.get(iid) is None


def test_a_trigger_that_does_not_start_an_agent_records_nothing(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.services.pipeline_service import trigger_auto_sre
    sre = _Sre(monkeypatch)
    waiting = _issue(plan="pending_approval")
    trigger_auto_sre(waiting)                                  # a plan already waits: the guard skips the agent
    monkeypatch.setattr(settings, "auto_fix_enabled", False)
    off = _issue()
    trigger_auto_sre(off)                                      # auto-fix off: nothing is handed to the agent
    assert agent_runs.running() == [] and sre.calls == []
    assert _events(waiting) == [] and _events(off) == []


def test_the_bookkeeping_never_stops_the_pipeline(db, monkeypatch):
    """The record is a courtesy to the people watching; if it cannot be written the plan is still written."""
    from agenticops.services import pipeline_service
    from agenticops.services.pipeline_service import trigger_auto_sre
    iid = _issue()
    sre = _Sre(monkeypatch)
    monkeypatch.setattr(agent_runs, "take", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("registry broken")))
    trigger_auto_sre(iid)
    assert sre.started.wait(10)
    sre.finish()
    assert sre.calls == [iid]
    assert pipeline_service is not None
