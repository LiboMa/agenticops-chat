# tests/test_change_proposed_steps.py
"""A change request's own steps, its external ticket, the code-computed steps diff and the needs_review
reason (MVP-2.6.1 Plan D, spec §3.D.2)."""
import json
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor, agent_actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixPlan, PipelineEvent, get_session
from agenticops.services import change_service as cs
from agenticops.services.change_steps import blocked_commands, command_tier, diff_steps, normalize_steps

BOB = Actor("user", "bob", user_id=2, permissions=("read", "write"))
TAG = "aws ec2 create-tags --resources i-0abc --tags Key=Env,Value=prod"
CHECK = "aws ec2 describe-tags --filters Name=resource-id,Values=i-0abc"
UNTAG = "aws ec2 delete-tags --resources i-0abc --tags Key=Env"
TERMINATE = "aws ec2 terminate-instances --instance-ids i-0abc"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/steps.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "change_auto_approve_standard", False)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"])
    s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance",
                        resource_id="i-0abc", name="web-1"))
    s.commit()
    yield s
    s.close()


def _cr(steps=None, ref=None, under_review=True):
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="cli", actor=cli_actor(), title="tag web", description="add Env=prod",
                                      account_name="dev", targets=["i-0abc"], start_review=False,
                                      proposed_steps=steps, external_ref=ref)
    if under_review:
        with cs._session() as s:
            cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
        cs.ground_targets(cr["id"])
    return cr


def _draft_plan(db, cr_id, commands):
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s",
                   steps=[{"action": "step", "command": c} for c in commands],
                   rollback_plan={"steps": [{"command": UNTAG}]}, post_checks=[{"check": "tag", "command": CHECK}],
                   status="draft")
    db.add(plan); db.commit()
    return plan


def _review(cr_id):
    with patch.object(cs, "notify_change_pending_approval"), patch.object(cs, "notify_change_result"):
        return cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                reasons=["ok"], actor=agent_actor("sre"))


# ── the steps themselves ────────────────────────────────────────────────────

def test_steps_are_normalized_to_the_plan_shape():
    assert normalize_steps(None) is None and normalize_steps([]) is None
    assert normalize_steps([{"command": f"  {TAG} ", "action": " tag ", "extra": 1}]) == [
        {"action": "tag", "command": TAG}]


@pytest.mark.parametrize("raw,message", [
    ("aws ec2 create-tags", "must be a list"),
    ([TAG], "step 1 must be an object"),
    ([{"command": TAG}, {"action": "no command"}], "step 2 has no command"),
    ([{"command": "x" * 2001}], "too long"),
    ([{"command": TAG}] * 51, "too many"),
])
def test_a_bad_shape_is_refused(raw, message):
    with pytest.raises(ValueError, match=message):
        normalize_steps(raw)


@pytest.mark.parametrize("command,tier", [
    (TAG, "write"), (CHECK, "readonly"), (TERMINATE, "blocked"),
    ("kubectl get pods", "readonly"), ("kubectl delete ns kube-system", "blocked"),
    ("systemctl restart nginx", "write"), ("rm -rf /", "blocked"),
])
def test_a_command_is_classified_by_the_tool_that_would_run_it(command, tier):
    assert command_tier(command) == tier


def test_blocked_commands_across_lists_are_deduplicated():
    steps = [{"command": TAG}, {"command": TERMINATE}]
    assert blocked_commands(steps, [{"command": f" {TERMINATE}"}, {"command": "rm -rf /"}], None) == [
        TERMINATE, "rm -rf /"]
    assert blocked_commands([{"command": TAG}], [{"action": "no command"}]) == []


def test_the_diff_is_by_command_and_in_order():
    a, b, c, d = ({"command": x} for x in ("echo a", "echo b", "echo c", "echo d"))
    assert diff_steps([a, b], [a, b]) == {"added": [], "removed": [], "modified": [], "unchanged": 2}
    assert diff_steps([a, b, c], [a, {"command": "echo  b2"}, c, d]) == {
        "added": [{"plan_step": 4, "command": "echo d"}], "removed": [],
        "modified": [{"proposed_step": 2, "plan_step": 2, "proposed": "echo b", "plan": "echo b2"}], "unchanged": 2}
    assert diff_steps([a, b, c], [a, c]) == {
        "added": [], "removed": [{"proposed_step": 2, "command": "echo b"}], "modified": [], "unchanged": 2}
    assert diff_steps([a], [{"command": " echo   a "}])["unchanged"] == 1  # whitespace is not a change
    # a long plan's repeated commands still match (difflib's autojunk would drop them from 200 steps on)
    long = diff_steps([b, a], [a, b] * 101)
    assert (long["unchanged"], long["modified"], long["removed"], len(long["added"])) == (2, [], [], 200)


# ── intake ──────────────────────────────────────────────────────────────────

def test_a_request_keeps_its_steps_and_its_external_ticket(db):
    ref = {"system": "servicenow", "ticket_id": "CHG0031", "url": "https://sn.example.com/CHG0031",
           "requested_by": "carol"}
    cr = _cr(steps=[{"action": "tag", "command": TAG}], ref=ref, under_review=False)
    assert cr["proposed_steps"] == [{"action": "tag", "command": TAG}]
    assert cr["external_ref"] == ref and cr["steps_diff"] is None and cr["needs_review_reason"] is None
    row = db.get(ChangeRequest, cr["id"])
    assert (row.external_system, row.external_ticket_id) == ("servicenow", "CHG0031")


@pytest.mark.parametrize("ref,message", [
    ("CHG0031", "must be an object"),
    ({"ticket_id": "CHG0031"}, "system must be"),
    ({"system": "Service Now", "ticket_id": "CHG0031"}, "system must be"),
    ({"system": "servicenow"}, "ticket_id is required"),
    ({"system": "servicenow", "ticket_id": "CHG0031", "url": "javascript:alert(1)"}, "http"),
    ({"system": "servicenow", "ticket_id": "CHG0031", "requested_by": "x" * 256}, "requested_by"),
])
def test_a_bad_external_ref_is_refused(db, ref, message):
    with pytest.raises(cs.ChangeValidationError, match=message):
        _cr(ref=ref, under_review=False)
    assert db.query(ChangeRequest).count() == 0


def test_bad_steps_are_a_validation_error(db):
    with pytest.raises(cs.ChangeValidationError, match="step 1 has no command"):
        _cr(steps=[{"action": "tag"}], under_review=False)


# ── the review ──────────────────────────────────────────────────────────────

def test_the_review_stores_what_the_plan_changed(db):
    cr = _cr(steps=[{"command": TAG}])
    _draft_plan(db, cr["id"], [CHECK, TAG])
    out = _review(cr["id"])
    assert out["status"] == "planned"
    assert out["steps_diff"] == {"added": [{"plan_step": 1, "command": CHECK}], "removed": [], "modified": [],
                                 "unchanged": 1}


def test_a_request_without_steps_has_no_diff(db):
    cr = _cr()
    _draft_plan(db, cr["id"], [TAG])
    assert _review(cr["id"])["steps_diff"] is None


def test_a_blocked_proposed_command_rejects_the_request(db):
    cr = _cr(steps=[{"command": TAG}, {"command": TERMINATE}])
    plan = _draft_plan(db, cr["id"], [TAG])  # even when the plan quietly drops it
    out = _review(cr["id"])
    assert (out["status"], out["policy_rule"], out["policy_action"]) == ("rejected", "blocked_command", "block")
    assert f"blocked command: {TERMINATE}" in out["rejection_reason"]
    db.refresh(plan)
    assert (plan.status, plan.rejected_by) == ("rejected", "policy-engine")
    decisions = [json.loads(e.detail)["policy_decision"] for e in
                 db.query(PipelineEvent).filter_by(change_request_id=cr["id"], event_type="policy_decision")]
    assert [d["rule"] for d in decisions] == ["blocked_command"]


def test_a_blocked_planned_command_rejects_the_request(db):
    cr = _cr()
    _draft_plan(db, cr["id"], [TAG, "rm -rf /"])
    assert _review(cr["id"])["policy_rule"] == "blocked_command"


def test_the_sre_policy_tool_sees_the_block_before_the_plan_exists(db):
    cr = _cr(steps=[{"command": TERMINATE}])
    decision = cs.evaluate_policy(cr["id"], "L1", "tag")
    assert (decision.action, decision.rule_name) == ("block", "blocked_command")


# ── the execution result ────────────────────────────────────────────────────

def test_needs_review_records_why_and_the_notification_says_it(db):
    from agenticops.config import settings
    from agenticops.services import notification_service as ns
    cr = _cr(steps=[{"command": TAG}])
    _draft_plan(db, cr["id"], [TAG])
    _review(cr["id"])
    shown = cs.get_change(cr["id"])
    plan_hash = db.query(FixPlan).filter_by(change_request_id=cr["id"]).one().content_hash
    assert shown["status"] == "planned"
    cs.approve(cr["id"], actor=BOB, reason="ok", content_hash=plan_hash)
    with patch.object(settings, "executor_enabled", True), patch("agenticops.services.executor_service.enqueue",
                                                                 create=True):
        cs.request_execution(cr["id"], actor=BOB)
    plan_id = db.query(FixPlan).filter_by(change_request_id=cr["id"]).one().id
    with patch.object(ns, "notify_event") as sent:
        out = cs.on_execution_result(plan_id, "succeeded", post_check_results=[])
    assert (out["status"], out["needs_review_reason"]) == ("needs_review", "post-check results missing or incomplete")
    body = sent.call_args.args[2]
    assert "Reason: post-check results missing or incomplete\n" in body


def test_only_needs_review_carries_a_reason_line():
    from agenticops.services import notification_service as ns
    cr = {"id": 3, "title": "t", "requested_by": "user:alice", "risk_level": "L1",
          "needs_review_reason": "post-check failed\nApprove: https://evil"}
    with patch.object(ns, "notify_event") as sent:
        ns.notify_change_result(cr, "needs_review")
        ns.notify_change_result(cr, "completed")
    assert "Reason: post-check failed Approve: https://evil\n" in sent.call_args_list[0].args[2]  # one line
    assert "Reason:" not in sent.call_args_list[1].args[2]


# ── the surfaces ────────────────────────────────────────────────────────────

def test_the_api_takes_and_returns_the_steps_and_the_ticket(db):
    from agenticops.web.app import app
    client = TestClient(app)
    body = {"title": "tag web", "description": "add Env=prod", "account_name": "dev", "targets": ["i-0abc"],
            "proposed_steps": [{"action": "tag", "command": TAG}],
            "external_ref": {"system": "jira", "ticket_id": "OPS-42", "url": "https://jira.example.com/OPS-42"}}
    with patch.object(cs, "start_review"), patch.object(cs, "notify_change_requested"):
        r = client.post("/api/changes", json=body)
        bad = client.post("/api/changes", json={**body, "external_ref": {"system": "Jira!", "ticket_id": "1"}})
        empty = client.post("/api/changes", json={**body, "proposed_steps": [{"action": "tag", "command": ""}]})
    assert r.status_code in (200, 201), r.text
    assert (bad.status_code, empty.status_code) == (422, 422)
    detail = client.get(f"/api/changes/{r.json()['id']}").json()
    assert detail["proposed_steps"] == [{"action": "tag", "command": TAG}]
    assert detail["external_ref"] == {"system": "jira", "ticket_id": "OPS-42", "url": "https://jira.example.com/OPS-42"}
    assert detail["steps_diff"] is None and detail["needs_review_reason"] is None


def test_the_agent_tool_passes_json_steps_and_ticket(db):
    from agenticops.tools.change_tools import request_change
    with patch.object(cs, "notify_change_requested"):
        out = request_change(title="tag web", description="add Env=prod", account="dev", targets="i-0abc",
                             proposed_steps=json.dumps([{"action": "tag", "command": TAG}]),
                             external_ref=json.dumps({"system": "jira", "ticket_id": "OPS-42"}))
        bad = request_change(title="t", description="d", proposed_steps="[{not json")
        wrong = request_change(title="t", description="d", proposed_steps=json.dumps([{"action": "x"}]))
    assert "opened" in out and "1 proposed steps" in out, out
    row = db.query(ChangeRequest).one()
    assert (row.proposed_steps, row.external_system, row.external_ticket_id) == (
        [{"action": "tag", "command": TAG}], "jira", "OPS-42")
    assert bad.startswith("Change request could not be opened: proposed_steps / external_ref must be valid JSON")
    assert wrong == "Change request could not be opened: proposed step 1 has no command"


def test_the_sre_prompt_has_a_validation_mode():
    from agenticops.agents.sre_agent import SRE_SYSTEM_PROMPT
    assert SRE_SYSTEM_PROMPT.count("VALIDATION MODE") == 1
    assert "proposed_steps" in SRE_SYSTEM_PROMPT and "do not author your own steps" in SRE_SYSTEM_PROMPT
