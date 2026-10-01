# tests/test_execution_verification.py
"""One post-execution verdict for a fix and a change, and the human acceptance of a pending one
(MVP-2.6.1 Plan D, spec §3.D.4): passed → resolved / completed, failed → root_cause_identified (RCA disputed)
/ failed | rolled_back | needs_review, pending_acceptance → fix_executed / needs_review until a human decides."""
import json
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor, webhook_actor
from agenticops.config import settings
from agenticops.models import (
    Base, ChangeRequest, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult, get_session,
)
from agenticops.services import change_service as cs
from agenticops.services import notification_service as ns
from agenticops.services import plan_content as pc
from agenticops.services import verification as vf
from agenticops.services.verification import FAILED, PASSED, PENDING, evaluate

BOB = Actor("user", "bob", 2, ("read", "write"))
NOTIFY_PENDING = ns.notify_execution_pending_acceptance  # the real one (the autouse fixture patches it)
CHECK = {"check": "healthy", "command": "aws ec2 describe-instance-status --instance-ids i-0abc"}
OK = {"check": "healthy", "status": "passed"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/verify.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "executor_auto_resolve", True)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def quiet():
    """No real notification or post-resolution pipeline; the pending-acceptance notice is recorded."""
    with patch.object(ns, "notify_event") as event, \
         patch("agenticops.services.resolution_service.trigger_post_resolution") as post, \
         patch.object(ns, "notify_execution_pending_acceptance") as pending, \
         patch.object(cs, "notify_execution_pending_acceptance", pending):
        yield {"event": event, "post": post, "pending": pending}


def _fix(db, post_checks=(CHECK,), issue_status="fix_approved", plan_status="approved"):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status=issue_status,
                        resource_id="i-0abc")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   steps=[{"command": "aws ec2 reboot-instances --instance-ids i-0abc"}],
                   post_checks=list(post_checks), status=plan_status, approved_by="user:alice")
    db.add(plan); db.flush()
    pc.stamp_content(db, plan)
    pc.stamp_approval(db, plan)
    db.commit()
    return issue.id, plan.id, rca.id


def _save(plan_id, status="succeeded", post=(), steps=({"status": "succeeded"},), error=""):
    from agenticops.tools.metadata_tools import save_execution_result
    return save_execution_result(fix_plan_id=plan_id, status=status, post_check_results=json.dumps(list(post)),
                                 step_results=json.dumps(list(steps)), error_message=error)


def _fresh(model, pk):
    s = get_session()
    try:
        return s.get(model, pk)
    finally:
        s.close()


def _only_execution(plan_id):
    s = get_session()
    try:
        return s.query(FixExecution).filter_by(fix_plan_id=plan_id).one()
    finally:
        s.close()


def _audit_actions(db):
    from agenticops.audit.models import AuditLog
    db.expire_all()
    return [a.action for a in db.query(AuditLog).order_by(AuditLog.id)]


# ── the verdict ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,checks,results,steps,expected", [
    ("failed", [CHECK], [OK], [], (FAILED, "boom")),
    ("rolled_back", [CHECK], [], [], (FAILED, "execution rolled back")),
    ("aborted", [CHECK], [], [], (FAILED, "execution aborted")),
    ("succeeded", [CHECK, CHECK], [OK, {"status": "failed"}], [], (FAILED, "post-check 2 failed")),
    ("succeeded", [CHECK, CHECK], [{"status": "warning"}, {"status": "error"}], [], (FAILED, "post-check 2 failed")),
    ("succeeded", [], [{"status": "failed"}], [], (FAILED, "post-check 1 failed")),  # a failure is never pending
    ("succeeded", [], [], [], (PENDING, "the plan has no post-checks")),
    ("succeeded", [CHECK, CHECK], [OK], [], (PENDING, "post-check results missing or incomplete")),
    ("succeeded", [CHECK], [{"check": "healthy"}], [], (PENDING, "post-check results missing or incomplete")),
    ("succeeded", [CHECK], [{"status": "WARN"}], [], (PENDING, "post-check 1 reported a warning")),
    ("succeeded", [CHECK], [OK], [{"status": "succeeded"}, {"status": "skipped"}],
     (PENDING, "step 2 did not report success")),
    ("succeeded", [CHECK], [OK], [{"output": "no status"}], (PENDING, "step 1 did not report success")),
    ("succeeded", [CHECK, CHECK, CHECK], ["ok", {"passed": True}, {"result": "PASS"}], [{"status": "success"}],
     (PASSED, "all post-checks passed")),
])
def test_the_verdict_truth_table(status, checks, results, steps, expected):
    assert evaluate(status, checks, results, steps, "boom" if status == "failed" else "") == expected


# ── a fix: the verdict moves the issue ──────────────────────────────────────

def test_a_passing_run_resolves_the_issue(db, quiet):
    issue_id, plan_id, _ = _fix(db)
    out = _save(plan_id, post=[OK])
    ex = _only_execution(plan_id)
    assert (ex.verification_status, ex.verification_reason) == (PASSED, "all post-checks passed")
    assert _fresh(HealthIssue, issue_id).status == "resolved"
    assert "Verification: passed" in out and "auto-resolved" in out
    quiet["post"].assert_called_once_with(issue_id)
    quiet["pending"].assert_not_called()


def test_a_passing_run_waits_at_fix_executed_without_auto_resolve(db, quiet, monkeypatch):
    monkeypatch.setattr(settings, "executor_auto_resolve", False)
    issue_id, plan_id, _ = _fix(db)
    _save(plan_id, post=[OK])
    assert _fresh(HealthIssue, issue_id).status == "fix_executed"
    quiet["post"].assert_not_called()
    quiet["pending"].assert_not_called()  # nothing to accept: it passed


@pytest.mark.parametrize("checks,post,reason", [
    ((), [], "the plan has no post-checks"),
    ((CHECK,), [], "post-check results missing or incomplete"),
    ((CHECK,), [{"status": "warning"}], "post-check 1 reported a warning"),
])
def test_an_unverified_run_waits_for_acceptance(db, quiet, checks, post, reason):
    """A succeeded run no post-check passed is never closed: the issue waits at fix_executed (not resolved)."""
    issue_id, plan_id, _ = _fix(db, post_checks=checks)
    out = _save(plan_id, post=post)
    ex = _only_execution(plan_id)
    assert (ex.status, ex.verification_status, ex.verification_reason) == ("succeeded", PENDING, reason)
    assert _fresh(HealthIssue, issue_id).status == "fix_executed"
    assert "awaiting human acceptance" in out
    quiet["post"].assert_not_called()
    quiet["pending"].assert_called_once_with(ex.id, reason, issue_id=issue_id)


@pytest.mark.parametrize("status,post,error,reason", [
    ("succeeded", [{"status": "failed"}], "", "post-check 1 failed"),
    ("failed", [], "step 1 failed", "step 1 failed"),
    ("rolled_back", [], "", "execution rolled back"),
])
def test_a_failed_run_sends_the_issue_back_and_disputes_its_rca(db, quiet, status, post, error, reason):
    issue_id, plan_id, rca_id = _fix(db)
    out = _save(plan_id, status=status, post=post, error=error)
    ex = _only_execution(plan_id)
    assert (ex.verification_status, ex.verification_reason) == (FAILED, reason)
    assert _fresh(HealthIssue, issue_id).status == "root_cause_identified"
    assert "back at root_cause_identified" in out
    rca = _fresh(RCAResult, rca_id)
    assert rca.critic_verdict == "disputed_by_execution" and f"Fix execution #{ex.id} failed" in rca.critic_notes
    events = [e.event_type for e in db.query(PipelineEvent).filter_by(health_issue_id=issue_id)]
    assert "rca_disputed" in events
    quiet["post"].assert_not_called()
    quiet["pending"].assert_not_called()


def test_the_executors_mark_fix_failed_after_it_is_a_no_op(db):
    from agenticops.tools.metadata_tools import mark_fix_failed
    issue_id, plan_id, rca_id = _fix(db)
    _save(plan_id, post=[{"status": "failed"}])
    ex = _only_execution(plan_id)
    notes = _fresh(RCAResult, rca_id).critic_notes
    assert "back at 'root_cause_identified'" in mark_fix_failed(issue_id, ex.id, reason="post-check 1 failed")
    assert _fresh(RCAResult, rca_id).critic_notes == notes  # disputed once per execution
    # a run pending acceptance is the human's to reject, not the executor's
    pending_issue, pending_plan, _ = _fix(db, post_checks=())
    _save(pending_plan)
    out = mark_fix_failed(pending_issue, _only_execution(pending_plan).id, reason="looks off")
    assert f"stays 'fix_executed' (FixPlan #{pending_plan} is 'executed')" in out and "retry" not in out
    assert _fresh(HealthIssue, pending_issue).status == "fix_executed"


def test_mark_fix_executed_respects_the_verdict(db):
    from agenticops.tools.metadata_tools import mark_fix_executed
    issue_id, plan_id, _ = _fix(db)
    _save(plan_id, post=[{"status": "failed"}])
    out = mark_fix_executed(issue_id, _only_execution(plan_id).id)
    assert out.startswith(f"HealthIssue #{issue_id} stays 'root_cause_identified'") and "failed verification" in out
    assert _fresh(HealthIssue, issue_id).status == "root_cause_identified"
    other_id, other_plan, _ = _fix(db, post_checks=())
    _save(other_plan)
    out = mark_fix_executed(other_id, _only_execution(other_plan).id)
    assert "Awaiting human acceptance: the plan has no post-checks." in out
    assert _fresh(HealthIssue, other_id).status == "fix_executed"


def test_a_run_aborted_before_it_started_moves_nothing(db):
    from agenticops.tools.metadata_tools import mark_fix_failed
    issue_id, plan_id, _ = _fix(db)
    _save(plan_id, status="aborted", steps=(), error="pre-check failed")
    assert _fresh(FixPlan, plan_id).status == "approved"  # retry allowed
    assert _fresh(HealthIssue, issue_id).status == "fix_approved"
    # nor does the executor's mark_fix_failed after it: the approved plan can still be retried
    out = mark_fix_failed(issue_id, _only_execution(plan_id).id, reason="pre-check failed")
    assert "retry allowed" in out and _fresh(HealthIssue, issue_id).status == "fix_approved"


# ── a fix: the human acceptance ─────────────────────────────────────────────

def _pending_fix(db, **kw):
    issue_id, plan_id, rca_id = _fix(db, post_checks=(), **kw)
    _save(plan_id)
    return issue_id, plan_id, rca_id, _only_execution(plan_id).id


def test_accepting_resolves_the_issue_and_records_who_and_why(db, quiet):
    issue_id, plan_id, _, ex_id = _pending_fix(db)
    out = vf.accept_execution(ex_id, actor=BOB, decision="accepted", reason="checked the console")
    assert out == {"execution_id": ex_id, "decision": "accepted", "kind": "fix", "status": "resolved"}
    ex = _fresh(FixExecution, ex_id)
    assert (ex.verification_status, ex.accepted_by, ex.acceptance_note) == (PASSED, "user:bob", "checked the console")
    assert ex.accepted_at is not None
    assert _fresh(HealthIssue, issue_id).status == "resolved"
    moves = [json.loads(e.detail) for e in db.query(PipelineEvent).filter_by(
        health_issue_id=issue_id, event_type="status_changed")]
    assert (moves[-1]["from"], moves[-1]["to"]) == ("fix_executed", "resolved")
    assert db.query(PipelineEvent).filter_by(health_issue_id=issue_id,
                                             event_type="status_changed").all()[-1].actor == "user:bob"
    assert _audit_actions(db)[-1] == "execution.accepted"
    quiet["post"].assert_called_once_with(issue_id)


def test_rejecting_sends_the_issue_back_and_disputes_its_rca(db, quiet):
    issue_id, plan_id, rca_id, ex_id = _pending_fix(db)
    out = vf.accept_execution(ex_id, actor=BOB, decision="rejected", reason="latency still high")
    assert out["status"] == "root_cause_identified"
    assert _fresh(FixExecution, ex_id).verification_status == FAILED
    assert _fresh(HealthIssue, issue_id).status == "root_cause_identified"
    rca = _fresh(RCAResult, rca_id)
    assert rca.critic_verdict == "disputed_by_execution" and "latency still high" in rca.critic_notes
    assert _audit_actions(db)[-1] == "execution.rejected"
    quiet["post"].assert_not_called()


@pytest.mark.parametrize("decision,reason,code", [
    ("maybe", "r", 422), ("accepted", "   ", 422),
])
def test_a_bad_decision_or_no_reason_is_422(db, decision, reason, code):
    *_, ex_id = _pending_fix(db)
    with pytest.raises(vf.AcceptanceError) as e:
        vf.accept_execution(ex_id, actor=BOB, decision=decision, reason=reason)
    assert e.value.status_code == code
    assert _fresh(FixExecution, ex_id).verification_status == PENDING


def test_an_unknown_or_already_decided_execution_is_refused(db):
    *_, ex_id = _pending_fix(db)
    with pytest.raises(vf.AcceptanceNotFound):
        vf.accept_execution(999, actor=BOB, decision="accepted", reason="r")
    vf.accept_execution(ex_id, actor=BOB, decision="accepted", reason="r")
    with pytest.raises(vf.AcceptanceError, match="not pending acceptance") as e:
        vf.accept_execution(ex_id, actor=BOB, decision="rejected", reason="r")
    assert e.value.status_code == 409


def test_a_webhook_can_never_accept_even_in_shadow(db):
    issue_id, _, _, ex_id = _pending_fix(db)
    with patch("agenticops.audit.service.AuditService.log"), pytest.raises(vf.AcceptanceForbidden) as e:
        vf.accept_execution(ex_id, actor=webhook_actor("jira"), decision="accepted", reason="r")
    assert e.value.status_code == 403
    assert (_fresh(FixExecution, ex_id).verification_status, _fresh(HealthIssue, issue_id).status) == (
        PENDING, "fix_executed")


def test_an_issue_that_moved_on_is_a_conflict_and_nothing_is_stamped(db):
    from agenticops.services.issue_state import transition_issue
    issue_id, _, _, ex_id = _pending_fix(db)
    transition_issue(db, issue_id, "resolved", actor="user:carol", reason="closed by hand")
    db.commit()
    with pytest.raises(vf.AcceptanceError, match="no longer fix_executed") as e:
        vf.accept_execution(ex_id, actor=BOB, decision="rejected", reason="r")
    assert e.value.status_code == 409
    ex = _fresh(FixExecution, ex_id)
    assert (ex.verification_status, ex.accepted_by) == (PENDING, None)


def test_a_reopened_issue_is_not_resolved_by_an_old_run(db):
    """open → resolved is a legal edge, so only the fix_executed expectation stops a stale acceptance."""
    from agenticops.services.issue_state import transition_issue
    issue_id, _, _, ex_id = _pending_fix(db)
    transition_issue(db, issue_id, "dismissed", actor="user:carol", reason="not ours")
    transition_issue(db, issue_id, "open", actor="user:carol", reason="it is back")
    db.commit()
    with pytest.raises(vf.AcceptanceError, match="no longer fix_executed"):
        vf.accept_execution(ex_id, actor=BOB, decision="accepted", reason="r")
    assert (_fresh(HealthIssue, issue_id).status, _fresh(FixExecution, ex_id).verification_status) == (
        "open", PENDING)


def test_a_concurrent_decision_wins_and_the_second_is_refused(db):
    """Both read pending; the one whose stamp lands second gets 409 and moves nothing."""
    issue_id, plan_id, _, ex_id = _pending_fix(db)
    s = get_session()
    try:
        execution, plan = s.get(FixExecution, ex_id), s.get(FixPlan, plan_id)  # read while still pending
        vf.accept_execution(ex_id, actor=BOB, decision="accepted", reason="first")
        with pytest.raises(vf.AcceptanceError, match="was accepted or rejected concurrently"):  # the run's own CAS
            vf._accept_fix(s, execution, plan, actor=BOB, decision="rejected", reason="second")
    finally:
        s.close()
    ex = _fresh(FixExecution, ex_id)
    assert (ex.verification_status, ex.acceptance_note, _fresh(HealthIssue, issue_id).status) == (
        PASSED, "first", "resolved")


# ── a change: the same verdict, the change's own terminal writers ───────────

def _change(db, post_checks=(CHECK,)):
    """An executing change and its queued run (the run context names the ticket)."""
    cr = ChangeRequest(title="tag web", description="d", requested_by="user:alice", status="executing",
                       risk_level="L1", source="web")
    db.add(cr); db.flush()
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s",
                   steps=[{"command": "aws ec2 create-tags"}], rollback_plan={"steps": ["aws ec2 delete-tags"]},
                   post_checks=list(post_checks), status="executing", approved_by="user:bob")
    db.add(plan); db.flush()
    pc.stamp_content(db, plan)
    pc.stamp_approval(db, plan)
    ex = FixExecution(fix_plan_id=plan.id, status="running", executed_by="user:bob")
    db.add(ex); db.commit()
    return cr.id, plan.id, ex.id


def _save_change(cr_id, plan_id, ex_id, **kw):
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    token = set_run_context(RunContext(actor="agent:executor", agent_name="executor", fix_plan_id=plan_id,
                                       change_request_id=cr_id, execution_id=ex_id))
    try:
        return _save(plan_id, **kw)
    finally:
        reset_run_context(token)


def test_a_passing_change_run_completes(db, quiet):
    cr_id, plan_id, ex_id = _change(db)
    _save_change(cr_id, plan_id, ex_id, post=[OK])
    assert _fresh(ChangeRequest, cr_id).status == "completed"
    assert _fresh(FixExecution, ex_id).verification_status == PASSED
    quiet["pending"].assert_not_called()


def test_an_unverified_change_run_needs_review_and_notifies_acceptance(db, quiet):
    cr_id, plan_id, ex_id = _change(db)
    _save_change(cr_id, plan_id, ex_id, post=[])
    cr = _fresh(ChangeRequest, cr_id)
    assert (cr.status, cr.needs_review_reason) == ("needs_review", "post-check results missing or incomplete")
    assert _fresh(FixExecution, ex_id).verification_status == PENDING
    assert quiet["pending"].call_args.args == (ex_id, "post-check results missing or incomplete")
    assert quiet["pending"].call_args.kwargs["cr"]["id"] == cr_id


def test_a_change_post_check_failure_needs_review_but_is_not_pending(db, quiet):
    """2.6.0 mapping kept: a failed post-check → needs_review (the human resolves it); the run's verdict is
    failed, so it is not an acceptance — accept_execution refuses it."""
    cr_id, plan_id, ex_id = _change(db)
    _save_change(cr_id, plan_id, ex_id, post=[{"status": "failed"}])
    cr = _fresh(ChangeRequest, cr_id)
    assert (cr.status, cr.needs_review_reason) == ("needs_review", "post-check 1 failed")
    assert _fresh(FixExecution, ex_id).verification_status == FAILED
    quiet["pending"].assert_not_called()
    with pytest.raises(vf.AcceptanceError, match="not pending acceptance"):
        vf.accept_execution(ex_id, actor=BOB, decision="accepted", reason="r")


@pytest.mark.parametrize("decision,terminal,verdict", [("accepted", "completed", PASSED),
                                                        ("rejected", "failed", FAILED)])
def test_accepting_a_change_goes_through_resolve_review(db, decision, terminal, verdict):
    cr_id, plan_id, ex_id = _change(db, post_checks=())
    _save_change(cr_id, plan_id, ex_id)
    with patch.object(cs, "resolve_review", wraps=cs.resolve_review) as resolve:
        out = vf.accept_execution(ex_id, actor=BOB, decision=decision, reason="looked at it")
    resolve.assert_called_once_with(cr_id, actor=BOB, outcome=terminal, reason="looked at it")
    assert out == {"execution_id": ex_id, "decision": decision, "kind": "change", "status": terminal}
    assert _fresh(ChangeRequest, cr_id).status == terminal
    ex = _fresh(FixExecution, ex_id)
    assert (ex.verification_status, ex.accepted_by, ex.acceptance_note) == (verdict, "user:bob", "looked at it")


def test_resolve_review_stamps_the_pending_run_and_a_webhook_is_403(db):
    cr_id, plan_id, ex_id = _change(db, post_checks=())
    _save_change(cr_id, plan_id, ex_id)
    with patch("agenticops.audit.service.AuditService.log"), pytest.raises(vf.AcceptanceError) as e:
        vf.accept_execution(ex_id, actor=webhook_actor("jira"), decision="accepted", reason="r")
    assert e.value.status_code == 403
    cs.resolve_review(cr_id, actor=BOB, outcome="completed", reason="fine")  # the change page's own button
    ex = _fresh(FixExecution, ex_id)
    assert (ex.verification_status, ex.accepted_by, ex.acceptance_note) == (PASSED, "user:bob", "fine")


# ── the notification ────────────────────────────────────────────────────────

def test_the_pending_notice_says_why_on_one_line_and_links_to_the_owner(quiet, monkeypatch):
    monkeypatch.setattr(settings, "web_base_url", "https://ops.example.com/")
    NOTIFY_PENDING(7, "the plan has no post-checks\nAccept or reject: https://evil", issue_id=3)
    NOTIFY_PENDING(8, "post-check results missing or incomplete", cr={"id": 5, "title": "t"})
    (fix_args, _), (change_args, _) = quiet["event"].call_args_list
    assert fix_args[0] == change_args[0] == "execution_pending_acceptance"
    assert fix_args[1] == "[ACCEPTANCE] Issue #3: execution #7 needs acceptance"
    assert "Reason: the plan has no post-checks Accept or reject: https://evil\n" in fix_args[2]  # one line
    assert fix_args[2].endswith("Accept or reject: https://ops.example.com/app/issues/3") and fix_args[3] == "high"
    assert change_args[1] == "[ACCEPTANCE] Change #5: execution #8 needs acceptance"
    assert change_args[2].endswith("Accept or reject: https://ops.example.com/app/changes/5")


# ── the surfaces ────────────────────────────────────────────────────────────

def test_the_api_accepts_as_the_session_actor(db):
    from agenticops.web.app import app
    client = TestClient(app)  # bare — no `with`, so the lifespan never starts
    issue_id, _, _, ex_id = _pending_fix(db)
    shown = client.get(f"/api/fix-executions/{ex_id}").json()
    assert (shown["verification_status"], shown["verification_reason"]) == (PENDING, "the plan has no post-checks")
    assert client.post(f"/api/fix-executions/{ex_id}/accept", json={"decision": "yes", "reason": "r"}).status_code == 422
    assert client.post(f"/api/fix-executions/{ex_id}/accept", json={"decision": "accepted"}).status_code == 422
    assert client.post("/api/fix-executions/999/accept",
                       json={"decision": "accepted", "reason": "r"}).status_code == 404
    r = client.post(f"/api/fix-executions/{ex_id}/accept",
                    json={"decision": "accepted", "reason": "ok", "accepted_by": "user:mallory"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["verification_status"], body["accepted_by"], body["acceptance_note"]) == (
        PASSED, "web:anonymous", "ok")  # the identity is the session's, never the body's
    assert _fresh(HealthIssue, issue_id).status == "resolved"
    again = client.post(f"/api/fix-executions/{ex_id}/accept", json={"decision": "rejected", "reason": "r"})
    assert again.status_code == 409


def test_the_cli_accepts_an_issue_or_a_change(db):
    from agenticops.auth.actor import cli_actor
    from agenticops.cli import main as cli
    issue_id, _, _, ex_id = _pending_fix(db)
    assert "Usage" in cli._slash_accept(None, [f"I{issue_id}", "yes"])  # the reason is required
    assert "Usage" in cli._slash_accept(None, [f"P{issue_id}", "yes", "r"])
    assert "Usage" in cli._slash_accept(None, [f"I{issue_id}", "maybe", "r"])
    out = cli._slash_accept(None, [f"I{issue_id}", "yes", "service", "is", "back"])
    assert f"Execution #{ex_id} accepted; issue I#{issue_id} is resolved" in out
    ex = _fresh(FixExecution, ex_id)
    assert (ex.accepted_by, ex.acceptance_note) == (cli_actor().key, "service is back")
    assert "has no execution pending acceptance" in cli._slash_accept(None, [f"I{issue_id}", "no", "r"])
    cr_id, plan_id, cr_ex = _change(db, post_checks=())
    _save_change(cr_id, plan_id, cr_ex)
    out = cli._slash_accept(None, [f"C#{cr_id}", "no", "tag", "missing"])
    assert f"Change C#{cr_id} rejected (failed)" in out
    assert _fresh(FixExecution, cr_ex).verification_status == FAILED
    assert cli.SLASH_COMMANDS["accept"] is cli._slash_accept


def test_the_executor_prompt_leaves_the_verdict_to_the_platform():
    from agenticops.agents.executor_agent import EXECUTOR_SYSTEM_PROMPT
    assert "with status passed / failed / warning" in EXECUTOR_SYSTEM_PROMPT
    assert "the platform verifies the post-check results" in EXECUTOR_SYSTEM_PROMPT
