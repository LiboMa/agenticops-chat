"""MVP-2.9.0 N14: «request changes» — one request sends a fix plan back AND asks the plan agent for the next one.

Until now a reviewer who wanted a different plan did two things: reject it with a reason, then — on the «replan»
brief the item came back as — ask the agent for a new plan. The reason already reaches that agent
(sre_agent.rejection_feedback); what was missing is one step that does both, or neither: a plan sent back with
no new one on the way waits on the same person again, and an agent started while the old plan still waits for
approval would be writing beside it.
"""
import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services import agent_runs
from tests.test_agent_runs import _Agent, _events

ALICE = Actor("user", "alice", 1, ("read", "write"))


@pytest.fixture(autouse=True)
def _clean():
    agent_runs.clear()
    yield
    agent_runs.clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    models_mod._engine = None
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/changes.db")
    Base.metadata.create_all(models_mod.get_engine())
    app.dependency_overrides[deps.current_actor] = lambda: ALICE
    yield TestClient(app)
    app.dependency_overrides.clear()
    models_mod._engine = None


def _plan(status="pending_approval", issue_status="fix_planned", kind="fix"):
    s = get_session()
    try:
        if kind == "change":
            cr = ChangeRequest(title="c", description="d", requested_by="user:bob", status="planned")
            s.add(cr); s.flush()
            plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s", status=status)
            s.add(plan); s.commit()
            return None, plan.id
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status=issue_status, resource_id="i-1")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s", status=status,
                       steps=[{"action": "restart", "command": "kubectl rollout restart deploy/web -n shop"}])
        s.add(plan); s.flush()
        from agenticops.services.plan_content import stamp_content
        stamp_content(s, plan); s.commit()
        return issue.id, plan.id
    finally:
        s.close()


def _row(pid):
    s = get_session()
    try:
        p = s.get(FixPlan, pid)
        return p.status, p.rejected_by, p.rejection_reason
    finally:
        s.close()


def _audit(pid):
    from agenticops.audit.models import AuditLog
    s = get_session()
    try:
        return [a.action for a in s.query(AuditLog).filter_by(entity_type="fix_plan", entity_id=str(pid)).order_by(AuditLog.id)]
    finally:
        s.close()


def test_one_request_sends_the_plan_back_and_starts_the_plan_agent(client, monkeypatch):
    iid, pid = _plan()
    agent = _Agent(monkeypatch)
    r = client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "the rollback restarts the whole service"})
    assert r.status_code == 202, r.text
    assert r.json()["health_issue_id"] == iid and r.json()["fix_plan_id"] == pid
    assert agent.started.wait(10)
    assert _row(pid) == ("rejected", "user:alice", "the rollback restarts the whole service")
    busy = agent_runs.get(iid)
    assert busy is not None and (busy.agent, busy.requested_by) == ("sre", "user:alice")   # the issue is the plan agent's now
    agent.finish()
    assert agent.calls == [("sre", iid)]
    asked = [(s, d) for t, s, _a, d in _events(iid) if t == "fix_plan_requested"]
    assert asked[0][0] == "started"
    assert asked[0][1]["trigger"] == "manual" and asked[0][1]["requested_by"] == "user:alice" and asked[0][1]["after_plan"] == pid
    assert _audit(pid) == ["plan.rejected"]
    assert agent_runs.get(iid) is None                                                      # released when the agent ended


def test_the_agent_asked_for_the_next_plan_is_given_the_reason(client, monkeypatch):
    from agenticops.agents.sre_agent import rejection_feedback
    iid, pid = _plan()
    agent = _Agent(monkeypatch)
    client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "do not touch the database, restart only the web tier"})
    agent.started.wait(10)
    said = rejection_feedback(iid)
    agent.finish()
    assert "<reviewer_feedback>" in said and "do not touch the database, restart only the web tier" in said
    assert "user:alice" in said


def test_it_is_refused_while_an_agent_is_on_the_issue_and_nothing_is_written(client, monkeypatch):
    iid, pid = _plan()
    agent = _Agent(monkeypatch)
    other = agent_runs.begin("rca", iid, "user:bob")
    r = client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "wrong order"})
    assert r.status_code == 409 and r.json()["code"] == "agent_run_in_flight" and r.json()["agent"] == "rca"
    assert _row(pid) == ("pending_approval", None, None)            # the plan still waits for approval: not half done
    assert _events(iid) == [] and _audit(pid) == [] and agent.calls == []
    assert agent_runs.get(iid) is other                              # and the run that was on it is untouched


@pytest.mark.parametrize("status", ["approved", "rejected", "executing", "executed", "failed"])
def test_only_a_plan_that_waits_for_approval_can_be_sent_back_this_way(client, monkeypatch, status):
    iid, pid = _plan(status=status, issue_status="fix_approved" if status == "approved" else "fix_planned")
    agent = _Agent(monkeypatch)
    r = client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "no"})
    assert r.status_code == 409 and r.json()["code"] == "not_awaiting_approval", r.text
    assert _row(pid)[0] == status and agent_runs.running() == [] and agent.calls == [] and _events(iid) == []


def test_a_draft_plan_waits_for_approval_too(client, monkeypatch):
    iid, pid = _plan(status="draft")
    agent = _Agent(monkeypatch)
    assert client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "no"}).status_code == 202
    agent.started.wait(10); agent.finish()
    assert _row(pid)[0] == "rejected" and agent.calls == [("sre", iid)]


def test_a_change_plan_belongs_to_its_change_request(client, monkeypatch):
    _none, pid = _plan(kind="change")
    agent = _Agent(monkeypatch)
    r = client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "no"})
    assert r.status_code == 409
    assert _row(pid)[0] == "pending_approval" and agent.calls == []


@pytest.mark.parametrize("closed", ["resolved", "dismissed"])
def test_the_plan_of_a_closed_issue_gets_no_new_plan(client, monkeypatch, closed):
    iid, pid = _plan(issue_status=closed)
    agent = _Agent(monkeypatch)
    r = client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "no"})
    assert r.status_code == 409 and r.json()["code"] == "issue_closed"
    assert _row(pid) == ("pending_approval", None, None) and agent_runs.running() == [] and agent.calls == []


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "x" * 2001}])
def test_a_reason_is_required(client, monkeypatch, body):
    iid, pid = _plan()
    agent = _Agent(monkeypatch)
    assert client.post(f"/api/fix-plans/{pid}/request-changes", json=body).status_code == 422
    assert _row(pid)[0] == "pending_approval" and agent.calls == []


def test_a_reason_of_blanks_only_is_no_reason(client, monkeypatch):
    iid, pid = _plan()
    agent = _Agent(monkeypatch)
    assert client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "   \n "}).status_code == 422
    assert _row(pid)[0] == "pending_approval" and agent.calls == []


def test_an_unknown_plan_is_404(client):
    assert client.post("/api/fix-plans/99999/request-changes", json={"reason": "no"}).status_code == 404


def test_a_request_through_an_api_key_is_refused_like_a_rejection(client, monkeypatch):
    """Sending a plan back is a person's decision (rbac no-api-key-human-decisions); the claim taken for the plan
    agent must not outlive the refusal."""
    from agenticops.web import deps
    from agenticops.web.app import app
    iid, pid = _plan()
    agent = _Agent(monkeypatch)
    app.dependency_overrides[deps.current_actor] = lambda: Actor("user", "alice", 1, ("read", "write"), via_api_key=True)
    r = client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "no"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "human_session_required", r.text
    assert _row(pid) == ("pending_approval", None, None) and agent_runs.running() == [] and agent.calls == []


def test_a_plan_agent_that_cannot_start_leaves_the_issue_free(client):
    """The plan is sent back (that part is done and on record); the claim must not stay on the issue with nobody on
    it — the item then waits on the person as «replan», and asking again works."""
    from unittest.mock import patch
    iid, pid = _plan()
    with patch("threading.Thread") as thread:
        thread.return_value.start.side_effect = RuntimeError("can't start new thread")
        with pytest.raises(RuntimeError):
            client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "no"})
    assert agent_runs.get(iid) is None
    assert _row(pid)[0] == "rejected"


# ── the page is told whether it may offer it ───────────────────────────────────

def _actions(client, pid):
    return {a["action"]: a for a in client.get(f"/api/fix-plans/{pid}").json()["available_actions"]}


def test_a_plan_that_waits_for_approval_offers_it(client):
    _iid, pid = _plan()
    a = _actions(client, pid)["request_changes"]
    assert a["allowed"] is True and a["effect"] == "reject_and_request_plan"


def test_a_closed_issues_plan_says_why_not(client):
    _iid, pid = _plan(issue_status="dismissed")
    a = _actions(client, pid)["request_changes"]
    assert a["allowed"] is False and a["reason_code"] == "issue_closed"


def test_an_approved_plan_does_not_offer_it(client):
    _iid, pid = _plan(status="approved", issue_status="fix_approved")
    assert "request_changes" not in _actions(client, pid)


# ── the plan that comes back is never approved without a person (round-2 review, C1) ─────────────────
#
# save_fix_plan runs the auto-approval after every save. A reviewer who asked for «the exact command in step 3» got
# a plan whose every step is an exact command — which is what removes the floor that held the first plan for a
# person: with the committed defaults an L0 / L1 redo was approved and run with nobody having seen it, while the
# page had said «the new plan comes back to you for approval».

STEP = [{"action": "restart", "command": "kubectl rollout restart deploy/web -n shop"}]


def _redone(prev_status="rejected", rejected_by="user:alice", reason="restart only the web tier", risk="L1"):
    """An issue whose first plan ended as given (None = it has none), and the L1 draft written after it."""
    from agenticops.services.plan_content import stamp_content
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status="fix_planned", resource_id="i-1")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        prev_id = None
        if prev_status:
            prev = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p1", summary="s",
                           status=prev_status, steps=STEP, rejected_by=rejected_by, rejection_reason=reason)
            s.add(prev); s.flush()
            prev_id = prev.id
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk, title="p2", summary="s",
                       status="draft", steps=STEP)
        s.add(plan); s.flush()
        stamp_content(s, plan); s.commit()
        return issue.id, plan.id, prev_id
    finally:
        s.close()


def _auto_approve(monkeypatch, pid, policy_engine=False):
    from agenticops.config import settings
    from agenticops.services import pipeline_service
    monkeypatch.setattr(settings, "auto_fix_enabled", True)
    monkeypatch.setattr(settings, "executor_auto_approve_l0_l1", True)
    monkeypatch.setattr(settings, "policy_engine_enabled", policy_engine)
    ran = []
    monkeypatch.setattr(pipeline_service, "trigger_auto_execute", lambda plan_id, trace_id=None: ran.append(plan_id))
    pipeline_service.trigger_auto_approve(pid)
    return ran


def _held(iid):
    return [d["policy_decision"] for (kind, _status, _actor, d) in _events(iid)
            if kind == "policy_decision" and d["policy_decision"]["rule"] == "reviewer_requested_changes"]


def test_an_issues_first_low_risk_plan_is_auto_approved_as_before(client, monkeypatch):
    iid, pid, _ = _redone(prev_status=None)
    assert _auto_approve(monkeypatch, pid) == [pid]
    assert _row(pid)[0] == "approved" and _held(iid) == []


@pytest.mark.parametrize("policy_engine", [False, True])
def test_a_plan_redone_after_a_person_sent_the_last_one_back_waits_for_a_person(client, monkeypatch, policy_engine):
    iid, pid, prev = _redone()
    assert _auto_approve(monkeypatch, pid, policy_engine) == []          # nothing runs
    assert _row(pid)[0] == "draft"                                       # and it is still a person's to approve
    [decision] = _held(iid)
    assert decision["action"] == "require_human"
    assert f"#{prev}" in decision["reasons"][0] and "user:alice" in decision["reasons"][0]


def test_a_person_who_said_no_without_a_reason_is_asked_again_too(client, monkeypatch):
    iid, pid, _ = _redone(reason=None)
    assert _auto_approve(monkeypatch, pid) == []
    assert _row(pid)[0] == "draft" and len(_held(iid)) == 1


@pytest.mark.parametrize("prev_status,rejected_by,reason", [
    ("rejected", "agent:sre", "superseded"),                                    # code said no, not a person
    ("rejected", "policy:blocked-command", "blocked command"),
    ("rejected", "user:alice", "content changed after approval"),               # withdrawn by code under her key
    ("failed", None, None),                                                     # it ran and failed: a new situation
    ("executed", None, None),
])
def test_only_a_persons_no_holds_the_next_plan(client, monkeypatch, prev_status, rejected_by, reason):
    iid, pid, _ = _redone(prev_status=prev_status, rejected_by=rejected_by, reason=reason)
    assert _auto_approve(monkeypatch, pid) == [pid]
    assert _row(pid)[0] == "approved" and _held(iid) == []


# ── the reason is about the plan the reviewer was shown (round-2 review, C-S2) ────────────────────────

def _hash(pid):
    s = get_session()
    try:
        return s.get(FixPlan, pid).content_hash
    finally:
        s.close()


def test_a_request_that_names_the_plan_it_was_shown_goes_through(client, monkeypatch):
    iid, pid = _plan()
    agent = _Agent(monkeypatch)
    r = client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "no", "content_hash": _hash(pid)})
    assert r.status_code == 202, r.text
    assert agent.started.wait(10)
    agent.finish()


def test_a_plan_rewritten_since_the_page_loaded_is_not_sent_back_with_a_reason_about_the_old_one(client, monkeypatch):
    iid, pid = _plan()
    shown = _hash(pid)
    s = get_session()                                            # the draft is rewritten in place: the same row, new content
    try:
        from agenticops.services.plan_content import stamp_content
        plan = s.get(FixPlan, pid)
        plan.steps = [{"action": "scale", "command": "kubectl scale deploy/web --replicas=6 -n shop"}]
        stamp_content(s, plan); s.commit()
    finally:
        s.close()
    agent = _Agent(monkeypatch)
    r = client.post(f"/api/fix-plans/{pid}/request-changes", json={"reason": "step 1 restarts too much", "content_hash": shown})
    assert r.status_code == 409 and r.json()["code"] == "plan_changed", r.text
    assert _row(pid)[0] == "pending_approval"                    # not sent back
    assert agent_runs.get(iid) is None and agent.calls == []     # and nobody was asked for a new plan
