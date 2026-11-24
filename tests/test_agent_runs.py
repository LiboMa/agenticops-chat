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

    def test_a_claim_past_the_watchdog_is_kept_but_no_longer_blocks(self, monkeypatch):
        """MVP-2.9.0 N11: until then an overdue claim read as no claim, and a second agent started beside the first
        without a word. Its thread may be alive, so it stays listed; the next request takes the issue over — on record."""
        from agenticops.config import settings
        monkeypatch.setattr(settings, "rca_timeout_seconds", 900)
        old = agent_runs.begin("rca", 12, "user:alice", now=T0)
        assert old.replaced is None
        assert agent_runs.in_time(12, now=T0 + timedelta(seconds=899)) is old and not agent_runs.overdue(old, now=T0 + timedelta(seconds=899))
        late = T0 + timedelta(seconds=900)
        assert agent_runs.get(12, now=late) is old                                          # still claimed: its thread may be alive
        assert agent_runs.overdue(old, now=late) and agent_runs.in_time(12, now=late) is None
        new = agent_runs.begin("rca", 12, "user:bob", now=T0 + timedelta(seconds=901))
        assert new is not None and new.replaced is old                                      # a hung call does not block for good
        agent_runs.end(old)                                                                 # the old thread ending late …
        assert agent_runs.get(12) is new                                                    # … does not free the new claim

    def test_running_lists_every_claim_oldest_first_an_overdue_one_too(self, monkeypatch):
        from agenticops.config import settings
        monkeypatch.setattr(settings, "rca_timeout_seconds", 900)
        a = agent_runs.begin("rca", 12, "user:alice", now=T0)
        b = agent_runs.begin("sre", 7, "user:bob", now=T0 - timedelta(hours=3))             # long past its limit
        assert agent_runs.running(now=T0 + timedelta(seconds=1)) == [b, a]


class TestEnter:
    """What rca_agent / sre_agent hold when they start (MVP-2.9.0 N11): a run started from a chat used to claim
    nothing — the page said nobody was on the issue, and a person could start a second agent beside it."""

    def _ctx(self, **kw):
        from agenticops.run_context import RunContext, set_run_context
        return set_run_context(RunContext(actor="user:carol", **kw))

    def test_the_callers_own_claim_is_used_as_it_is(self):
        from agenticops.run_context import reset_run_context
        mine = agent_runs.begin("rca", 12, "user:alice", now=T0)
        token = self._ctx(agent_run=mine)
        try:
            assert agent_runs.enter("rca", 12) == (mine, False)                             # not made here: not released here
        finally:
            reset_run_context(token)

    def test_a_run_started_without_a_claim_makes_one(self):
        from agenticops.run_context import reset_run_context
        token = self._ctx()
        try:
            run, owned = agent_runs.enter("sre", 12)
            assert owned and agent_runs.get(12) is run and (run.agent, run.requested_by) == ("sre", "user:carol")
        finally:
            reset_run_context(token)

    def test_it_is_refused_while_another_run_is_on_the_issue(self):
        from agenticops.run_context import reset_run_context
        theirs = agent_runs.begin("rca", 12, "user:alice")
        token = self._ctx()
        try:
            assert agent_runs.enter("rca", 12) == (None, False)
            assert agent_runs.get(12) is theirs                                             # untouched
        finally:
            reset_run_context(token)


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


# ── MVP-2.9.0 N11: every way an agent starts on an issue claims it ───────────

def test_taking_over_an_overdue_claim_is_said_on_the_timeline(client, monkeypatch):
    from agenticops.config import settings
    monkeypatch.setattr(settings, "rca_timeout_seconds", 900)
    iid = _issue()
    old = agent_runs.begin("rca", iid, agent_runs.PIPELINE, now=datetime.now(timezone.utc) - timedelta(minutes=40))
    agent = _Agent(monkeypatch)
    assert client.post(f"/api/health-issues/{iid}/rca").status_code == 202                 # not 409: the old one is overdue
    assert agent.started.wait(10)
    [gone] = [d for t, _s, _a, d in _events(iid) if t == "agent_run_abandoned"]
    assert gone["agent"] == "rca" and gone["requested_by"] == agent_runs.PIPELINE and gone["started_at"].endswith("Z")
    assert gone["replaced_by"].startswith(("web:", "user:"))
    assert agent_runs.get(iid) is not old
    agent.finish()


def _agent_patches(module):
    from unittest.mock import MagicMock, patch
    return [patch(f"{module}.BedrockModel"),
            patch("agenticops.config.get_agent_model_config", return_value=("m", 16384)),
            patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()),
            patch("agenticops.services.agent_log_service.track_agent")]


def test_a_diagnosis_started_from_a_chat_claims_the_issue_while_it_runs(client):
    """rca_agent called as Main's tool: no route claimed the issue for it."""
    from contextlib import ExitStack
    from unittest.mock import patch
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    iid = _issue()
    seen = {}

    def invoke(agent, prompt, **kw):
        held = agent_runs.get(iid)
        seen["during"] = (held.agent, held.requested_by) if held else None
        return "done"

    ra = "agenticops.agents.rca_agent"
    token = set_run_context(RunContext(actor="user:carol", agent_name="main"))
    try:
        with ExitStack() as stack:
            for p in _agent_patches(ra):
                stack.enter_context(p)
            agent_cls = stack.enter_context(patch(f"{ra}.Agent"))
            stack.enter_context(patch(f"{ra}.resolve_rca_effort", return_value=(0, None)))
            stack.enter_context(patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke))
            stack.enter_context(patch("agenticops.services.rca_quality.run_post_rca_pipeline"))
            agent_cls.return_value.messages = []
            from agenticops.agents.rca_agent import rca_agent
            assert rca_agent(issue_id=iid) == "done"
    finally:
        reset_run_context(token)
    assert seen["during"] == ("rca", "user:carol")
    assert agent_runs.get(iid) is None                                                      # released when it ended


def test_an_agent_called_from_a_chat_is_refused_while_a_run_is_on_the_issue(client):
    from unittest.mock import patch
    from agenticops.agents.rca_agent import rca_agent
    from agenticops.agents.sre_agent import sre_agent
    iid = _issue()
    theirs = agent_runs.begin("rca", iid, "user:alice")
    with patch("agenticops.agents.rca_agent.Agent") as rca_cls, patch("agenticops.agents.sre_agent._create_sre_agent") as sre_new:
        said = rca_agent(issue_id=iid)
        also = sre_agent(issue_id=iid)
    assert said.startswith("REJECTED") and "alice" in said and f"#{iid}" in said
    assert also.startswith("REJECTED") and "alice" in also
    rca_cls.assert_not_called(); sre_new.assert_not_called()                                # no model was built
    assert agent_runs.get(iid) is theirs
    assert _events(iid) == []                                                               # a refusal is not a failed run


def test_the_automatic_diagnosis_claims_its_issue_and_stands_back_when_one_is_on_it(client, monkeypatch):
    from unittest.mock import patch
    from agenticops.config import settings
    from agenticops.services import rca_service
    monkeypatch.setattr(settings, "rca_timeout_seconds", 0)                                 # the direct path: no watchdog thread
    iid = _issue(rca=False)
    seen = {}

    def fake_rca(issue_id):
        held = agent_runs.get(issue_id)
        seen["during"] = (held.agent, held.requested_by) if held else None
        return "done"

    with patch("agenticops.agents.rca_agent.rca_agent", side_effect=fake_rca) as rca:
        rca_service._run_auto_rca(iid)
        assert seen["during"] == ("rca", agent_runs.PIPELINE) and agent_runs.get(iid) is None
        assert rca.call_count == 1
        theirs = agent_runs.begin("rca", iid, "user:alice")                                 # a person asked in the meantime
        rca_service._run_auto_rca(iid)
        assert rca.call_count == 1                                                          # no second agent beside theirs
        assert agent_runs.get(iid) is theirs
    assert [t for t, _s, _a, _d in _events(iid)].count("rca_started") == 1                  # the skipped one left no «started»


def test_a_timed_out_automatic_diagnosis_keeps_its_claim_while_its_thread_lives(client, monkeypatch):
    """The watchdog gives up and says so; the agent's thread cannot be killed. Its claim goes when IT ends."""
    from unittest.mock import patch
    from agenticops.config import settings
    from agenticops.services import rca_service
    monkeypatch.setattr(settings, "rca_timeout_seconds", 0.2)
    iid = _issue(rca=False)
    release = threading.Event()

    def slow_rca(issue_id):
        assert release.wait(10)
        return "late"

    with patch("agenticops.agents.rca_agent.rca_agent", side_effect=slow_rca):
        rca_service._run_auto_rca(iid)                                                      # returns at the timeout
        assert ("rca_completed", "failed") in [(t, s) for t, s, _a, _d in _events(iid)]
        held = agent_runs.get(iid)
        assert held is not None and held.requested_by == agent_runs.PIPELINE               # still claimed: the thread is alive
        release.set()
        for t in threading.enumerate():
            if t.name.startswith("auto-rca-run-"):
                t.join(10)
    assert agent_runs.get(iid) is None


# ── round-2 review ───────────────────────────────────────────────────────────────────────────────────
#
# B-I2. «A late run cannot take over the run a person asked for after it» was half kept: `end` lets go only of its
# own claim, but a diagnosis that came back after it had been taken over still ran the hand-on — trigger_auto_sre
# → take() — and that replaced the claim of the diagnosis in flight. A plan agent then wrote (and, at L0 / L1,
# the pipeline approved and ran) a plan from the abandoned run's diagnosis while the one the person asked for was
# still under way, and the issue was no longer theirs.

def test_a_claim_that_was_taken_over_no_longer_holds_its_issue():
    old = agent_runs.begin("rca", 7, agent_runs.PIPELINE, now=datetime.now(timezone.utc) - timedelta(hours=1))
    assert agent_runs.holds(old)
    new = agent_runs.begin("rca", 7, "user:alice")                       # the old one is overdue: taken over
    assert new is not None and agent_runs.holds(new) and not agent_runs.holds(old)
    agent_runs.end(new)
    assert not agent_runs.holds(old)                                     # replaced stays replaced when the newer run ends


def _late_diagnosis(iid, *, taken_over):
    """rca_agent as the pipeline's thread runs it; while the model «works», a person's diagnosis takes the issue
    over (or not). → whether the post-RCA pipeline was told to hand the issue on."""
    from contextlib import ExitStack
    from unittest.mock import patch
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    claim = agent_runs.begin("rca", iid, agent_runs.PIPELINE, now=datetime.now(timezone.utc) - timedelta(hours=1))

    def invoke(agent, prompt, **kw):
        if taken_over:
            assert agent_runs.begin("rca", iid, "user:alice") is not None
        return "done"

    ra = "agenticops.agents.rca_agent"
    token = set_run_context(RunContext(actor=agent_runs.PIPELINE, agent_name="rca", agent_run=claim))
    try:
        with ExitStack() as stack:
            for p in _agent_patches(ra):
                stack.enter_context(p)
            agent_cls = stack.enter_context(patch(f"{ra}.Agent"))
            stack.enter_context(patch(f"{ra}.resolve_rca_effort", return_value=(0, None)))
            stack.enter_context(patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke))
            post = stack.enter_context(patch("agenticops.services.rca_quality.run_post_rca_pipeline"))
            agent_cls.return_value.messages = []
            from agenticops.agents.rca_agent import rca_agent
            assert rca_agent(issue_id=iid) == "done"
    finally:
        reset_run_context(token)
    return post.call_args.kwargs.get("hand_on")


def test_a_diagnosis_that_still_holds_its_issue_hands_it_on(client):
    assert _late_diagnosis(_issue(), taken_over=False) is True


def test_a_diagnosis_that_was_taken_over_while_it_worked_hands_nothing_on(client):
    iid = _issue()
    assert _late_diagnosis(iid, taken_over=True) is False
    held = agent_runs.get(iid)
    assert held is not None and held.requested_by == "user:alice"        # the issue is still the newer run's


def test_the_gate_does_not_start_a_plan_for_a_run_that_was_replaced(client, monkeypatch):
    """The other half, in the post-RCA pipeline itself: a result that passes the gate, from a run that no longer
    holds the issue, starts no plan run — and the timeline says why."""
    from unittest.mock import patch
    from agenticops.config import settings
    from agenticops.services import rca_quality
    monkeypatch.setattr(settings, "rca_critic_enabled", False)
    monkeypatch.setattr(settings, "rca_min_confidence_for_autofix", 0.6)
    iid = _issue()                                                       # has a diagnosis with confidence 0.9
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    with patch("agenticops.services.pipeline_service.trigger_auto_sre") as plan_run, \
         patch("agenticops.services.notification_service.notify_rca_completed"), \
         patch("agenticops.services.notification_service.notify_im_origin"):
        rca_quality.run_post_rca_pipeline(iid, [], started, hand_on=False)
        plan_run.assert_not_called()
        assert [t for t, _s, _a, _d in _events(iid)].count("rca_superseded") == 1
        rca_quality.run_post_rca_pipeline(iid, [], started)              # the usual case: it does
        plan_run.assert_called_once()


# B-m7. `rca_timeout_seconds: 0` is a supported value («no watchdog»). A claim then never became overdue: a run
# whose thread hung answered 409 to every request on its issue and — by the N14 rule — kept the issue out of every
# person's queue until the process restarted.

def test_without_a_watchdog_a_claim_still_has_a_limit(monkeypatch):
    from agenticops.config import settings
    monkeypatch.setattr(settings, "rca_timeout_seconds", 0)
    fresh = agent_runs.begin("rca", 8, "user:alice")
    assert not agent_runs.overdue(fresh) and agent_runs.in_time(8) is fresh
    long_ago = datetime.now(timezone.utc) - timedelta(seconds=agent_runs.CLAIM_LIMIT_WITHOUT_WATCHDOG + 60)
    agent_runs.clear()
    stuck = agent_runs.begin("rca", 8, "user:alice", now=long_ago)
    assert agent_runs.overdue(stuck) and agent_runs.in_time(8) is None
    assert agent_runs.begin("rca", 8, "user:bob") is not None            # … and the next request takes it over


def test_the_refusal_tells_the_caller_to_read_what_the_run_leaves(monkeypatch):
    """B-m10. In a chat, «diagnose I#12 and plan a fix»: the diagnosis hands the issue to the pipeline's plan run,
    and Main's own sre_agent call is then refused — rightly — with «wait». It must also say what to do next."""
    agent_runs.take("sre", 12, agent_runs.PIPELINE)
    said = agent_runs.refusal(12)
    assert "REJECTED" in said and "get_plan" in said and "do not" in said.lower()
