"""MVP-2.9.0: a diagnosis or a fix plan a person asked for is recorded, and cannot be started twice.

Until now the manual triggers (POST /api/health-issues/{id}/rca, …/generate-fix-plan) recorded nothing: the page
went on saying «waits on you», a reload forgot the click, and a second click started a second agent on the same
issue. AgenticOps is one process, so an in-process claim per issue is the truth for «is an agent on it»; the
timeline keeps the record.
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


class TestRegistry:
    def test_an_issue_is_claimed_once(self):
        run = agent_runs.begin("rca", 12, "user:alice", now=T0)
        assert run is not None and (run.agent, run.issue_id, run.requested_by, run.started_at) == ("rca", 12, "user:alice", T0)
        assert agent_runs.begin("rca", 12, "user:bob", now=T0 + timedelta(seconds=5)) is None
        assert agent_runs.begin("sre", 12, "user:bob", now=T0 + timedelta(seconds=5)) is None   # one agent per issue at a time
        assert agent_runs.begin("rca", 13, "user:bob", now=T0) is not None                      # another issue is free

    def test_ending_a_run_frees_the_issue(self):
        run = agent_runs.begin("sre", 12, "user:alice", now=T0)
        agent_runs.end(run)
        assert agent_runs.get(12, now=T0) is None
        assert agent_runs.begin("rca", 12, "user:alice", now=T0) is not None

    def test_a_claim_older_than_the_watchdog_is_abandoned(self, monkeypatch):
        from agenticops.config import settings
        monkeypatch.setattr(settings, "rca_timeout_seconds", 900)
        old = agent_runs.begin("rca", 12, "user:alice", now=T0)
        assert agent_runs.get(12, now=T0 + timedelta(seconds=899)) is old
        assert agent_runs.get(12, now=T0 + timedelta(seconds=900)) is None               # a hung call does not block for good
        new = agent_runs.begin("rca", 12, "user:bob", now=T0 + timedelta(seconds=901))
        assert new is not None
        agent_runs.end(old)                                                                 # the old thread ending late …
        assert agent_runs.get(12, now=T0 + timedelta(seconds=902)) is new                  # … does not free the new claim

    def test_running_lists_the_live_claims_oldest_first(self):
        a = agent_runs.begin("rca", 12, "user:alice", now=T0)
        b = agent_runs.begin("sre", 7, "user:bob", now=T0 - timedelta(minutes=3))
        assert agent_runs.running(now=T0 + timedelta(seconds=1)) == [b, a]


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/runs.db")
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    models_mod._engine = None


def _issue(rca=True, plan=None):
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status="root_cause_identified", resource_id="i-1")
        s.add(issue); s.flush()
        r = None
        if rca:
            r = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
            s.add(r); s.flush()
        if plan:
            s.add(FixPlan(health_issue_id=issue.id, rca_result_id=r.id if r else None, risk_level="L1", title="p", summary="s",
                          status=plan))
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


class _Agent:
    """Stands in for the agent call: blocks until released, so a test can look at the world while it «runs»."""
    def __init__(self, monkeypatch, fail=False):
        import agenticops.web.app as app_mod
        self.started, self.release, self.calls, self.fail = threading.Event(), threading.Event(), [], fail
        monkeypatch.setattr(app_mod, "_invoke_issue_agent", self)

    def __call__(self, agent_name, issue_id):
        self.calls.append((agent_name, issue_id))
        self.started.set()
        assert self.release.wait(10)
        if self.fail:
            raise RuntimeError("model unavailable")
        return "done"

    def finish(self):
        self.release.set()
        for t in threading.enumerate():
            if t.name.startswith(("rca-trigger-", "fixplan-trigger-")):
                t.join(10)


def test_a_second_request_is_refused_while_the_first_runs(client, monkeypatch):
    iid = _issue()
    agent = _Agent(monkeypatch)
    assert client.post(f"/api/health-issues/{iid}/rca").status_code == 202
    assert agent.started.wait(10)
    again = client.post(f"/api/health-issues/{iid}/rca")
    assert again.status_code == 409 and again.json()["code"] == "agent_run_in_flight"
    assert again.json()["agent"] == "rca" and again.json()["started_at"].endswith("Z")
    assert client.post(f"/api/issues/{iid}/generate-fix-plan").status_code == 409        # the other agent, the alias route: also refused
    agent.finish()
    assert agent.calls == [("rca", iid)]                                                  # one agent ran, not three
    assert client.post(f"/api/health-issues/{iid}/generate-fix-plan").status_code == 202  # free again once it ended
    agent.finish()


def test_the_request_is_on_the_timeline_with_who_asked(client, monkeypatch):
    iid = _issue()
    agent = _Agent(monkeypatch)
    client.post(f"/api/health-issues/{iid}/rca"); agent.started.wait(10); agent.finish()
    agent2 = _Agent(monkeypatch)
    client.post(f"/api/health-issues/{iid}/generate-fix-plan"); agent2.started.wait(10); agent2.finish()
    events = _events(iid)
    assert ("rca_started", "started") in [(t, s) for t, s, _a, _d in events]
    rca = next(d for t, _s, _a, d in events if t == "rca_started")
    assert rca["trigger"] == "manual" and rca["requested_by"].startswith(("web:", "user:"))
    plan = next((s, d) for t, s, _a, d in events if t == "fix_plan_requested")
    assert plan[0] == "started" and plan[1]["requested_by"] == rca["requested_by"]


def test_a_failed_run_frees_the_issue_and_says_so_on_the_timeline(client, monkeypatch):
    iid = _issue()
    agent = _Agent(monkeypatch, fail=True)
    assert client.post(f"/api/health-issues/{iid}/rca").status_code == 202
    agent.started.wait(10); agent.finish()
    assert agent_runs.get(iid) is None
    assert ("rca_completed", "failed") in [(t, s) for t, s, _a, _d in _events(iid)]
    agent2 = _Agent(monkeypatch, fail=True)
    assert client.post(f"/api/health-issues/{iid}/generate-fix-plan").status_code == 202
    agent2.started.wait(10); agent2.finish()
    assert ("fix_plan_requested", "failed") in [(t, s) for t, s, _a, _d in _events(iid)]


def test_a_request_the_route_refuses_claims_nothing(client, monkeypatch):
    agent = _Agent(monkeypatch)
    no_rca = _issue(rca=False)
    assert client.post(f"/api/health-issues/{no_rca}/generate-fix-plan").status_code == 400     # needs a diagnosis first
    locked = _issue(plan="pending_approval")
    assert client.post(f"/api/health-issues/{locked}/generate-fix-plan").status_code == 409     # a plan already waits
    assert client.post("/api/health-issues/99999/rca").status_code == 404
    assert agent_runs.running() == [] and agent.calls == []
    assert _events(no_rca) == [] and _events(locked) == []


class TestStartFailure:
    def test_a_thread_that_cannot_start_does_not_leave_the_issue_claimed(self, client):
        """The claim is released by the agent thread. A thread that never started would never release it, and the
        issue would answer «an agent is already working on it» for the whole watchdog time with nobody on it."""
        from unittest.mock import patch
        iid = _issue()
        with patch("threading.Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("can't start new thread")
            with pytest.raises(RuntimeError):
                client.post(f"/api/health-issues/{iid}/rca")
        assert agent_runs.get(iid) is None
