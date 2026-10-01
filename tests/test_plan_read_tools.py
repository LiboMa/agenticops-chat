# tests/test_plan_read_tools.py
"""Main's read tools for a plan and a run (MVP-2.6.1 Plan D, spec §3.D.7): get_plan (either origin, any
status), get_execution_result (by run or by plan) and the full get_change_request (the whole plan, the
steps diff, the needs_review reason and the latest run's verdict — no truncation)."""
import json

import pytest

from agenticops.config import settings
from agenticops.models import Base, ChangeRequest, FixExecution, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services import plan_content as pc
from agenticops.tools.change_tools import get_change_request
from agenticops.tools.metadata_tools import get_execution_result, get_plan
from tests.test_main_change_routing import _build_main

READ_TOOLS = {"get_plan", "get_execution_result"}
TAG = "aws ec2 create-tags --resources i-0abc --tags Key=Env,Value=prod"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/read.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()


def _fix_plan(db, status="rejected"):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="root_cause_identified",
                        resource_id="i-0abc")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="reboot", summary="s",
                   steps=[{"command": "aws ec2 reboot-instances --instance-ids i-0abc"}],
                   post_checks=[{"check": "healthy"}], status=status, approved_by="user:alice",
                   rejected_by="user:carol", rejection_reason="wrong window")
    db.add(plan); db.flush()
    pc.stamp_content(db, plan)
    pc.stamp_approval(db, plan)
    db.commit()
    return plan


def _change(db, steps=(TAG,), status="needs_review"):
    cr = ChangeRequest(title="tag web", description="d", requested_by="user:alice", status=status, risk_level="L1",
                       source="web", proposed_steps=[{"action": "tag", "command": TAG}],
                       steps_diff={"added": [], "removed": [], "modified": [], "unchanged": 1},
                       needs_review_reason="post-check results missing or incomplete")
    db.add(cr); db.flush()
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s",
                   steps=[{"action": "step", "command": c} for c in steps],
                   rollback_plan={"steps": ["aws ec2 delete-tags"]}, post_checks=[{"check": "tag"}],
                   status="executed", approved_by="user:bob")
    db.add(plan); db.flush()
    pc.stamp_content(db, plan)
    db.commit()
    return cr, plan


def _run(db, plan, status="succeeded", **kw):
    ex = FixExecution(fix_plan_id=plan.id, health_issue_id=plan.health_issue_id, status=status,
                      executed_by="agent:executor", **kw)
    db.add(ex); db.commit()
    return ex


# ── get_plan ────────────────────────────────────────────────────────────────

def test_get_plan_returns_either_origin_in_any_status(db):
    fix = _fix_plan(db)
    data = json.loads(get_plan(fix.id))
    assert (data["label"], data["plan_kind"], data["status"]) == (
        f"I#{fix.health_issue_id} fix plan v1", "fix", "rejected")
    assert data["steps"] == [{"command": "aws ec2 reboot-instances --instance-ids i-0abc"}]
    assert (data["content_hash"], data["approved_hash"], data["approved_version"]) == (
        fix.content_hash, fix.content_hash, 1)
    assert (data["rejected_by"], data["rejection_reason"]) == ("user:carol", "wrong window")
    cr, plan = _change(db)
    data = json.loads(get_plan(plan.id))
    assert (data["label"], data["change_request_id"], data["health_issue_id"]) == (
        f"C#{cr.id} implementation plan v1", cr.id, None)
    assert get_plan(999) == "Plan #999 not found."


# ── get_execution_result ────────────────────────────────────────────────────

def test_get_execution_result_by_run_or_by_plan(db):
    fix = _fix_plan(db, status="executed")
    first = _run(db, fix, status="failed", error_message="step 1 timed out", verification_status="failed",
                 verification_reason="step 1 timed out")
    latest = _run(db, fix, step_results=[{"status": "succeeded"}], post_check_results=[{"status": "passed"}],
                  verification_status="pending_acceptance", verification_reason="post-check 1 reported a warning",
                  accepted_by="user:bob", acceptance_note="checked by hand")
    by_plan = json.loads(get_execution_result(plan_id=fix.id))
    assert by_plan["id"] == latest.id  # the latest run of the plan
    assert (by_plan["verification_status"], by_plan["verification_reason"]) == (
        "pending_acceptance", "post-check 1 reported a warning")
    assert (by_plan["accepted_by"], by_plan["acceptance_note"]) == ("user:bob", "checked by hand")
    assert by_plan["post_check_results"] == [{"status": "passed"}]
    assert (by_plan["plan_label"], by_plan["change_request_id"]) == (f"I#{fix.health_issue_id} fix plan v1", None)
    by_id = json.loads(get_execution_result(execution_id=first.id, plan_id=fix.id))  # the run id wins
    assert (by_id["id"], by_id["status"], by_id["error_message"]) == (first.id, "failed", "step 1 timed out")


def test_get_execution_result_says_what_is_missing(db):
    fix = _fix_plan(db)
    assert get_execution_result() == "Give an execution_id or a plan_id."
    assert get_execution_result(execution_id=999) == "Execution #999 not found."
    assert get_execution_result(plan_id=fix.id) == f"Plan #{fix.id} has no execution."


# ── get_change_request ──────────────────────────────────────────────────────

def test_get_change_request_has_the_whole_plan_and_the_latest_verdict(db):
    long_steps = [f"{TAG}-{i:03d} " + "x" * 200 for i in range(40)]  # > 6000 chars: the old cut broke the JSON
    cr, plan = _change(db, steps=long_steps)
    _run(db, plan, status="failed", verification_status="failed", verification_reason="execution failed")
    last = _run(db, plan, verification_status="pending_acceptance",
                verification_reason="post-check results missing or incomplete")
    out = get_change_request(cr.id)
    assert len(out) > 6000
    data = json.loads(out)
    assert [s["command"] for s in data["plan"]["steps"]] == long_steps
    assert (data["plan"]["label"], data["plan"]["content_hash"]) == (
        f"C#{cr.id} implementation plan v1", plan.content_hash)
    assert data["proposed_steps"] == [{"action": "tag", "command": TAG}]
    assert data["steps_diff"]["unchanged"] == 1
    assert data["needs_review_reason"] == "post-check results missing or incomplete"
    latest = data["latest_execution"]
    assert (latest["execution_id"], latest["fix_plan_id"], latest["verification_status"]) == (
        last.id, plan.id, "pending_acceptance")


def test_a_change_without_a_plan_or_a_run(db):
    cr = ChangeRequest(title="t", description="d", requested_by="user:alice", status="draft", source="web")
    db.add(cr); db.commit()
    _run(db, _fix_plan(db, status="executed"))  # someone else's run is not this request's
    data = json.loads(get_change_request(cr.id))
    assert (data["plan"], data["latest_execution"]) == (None, None)
    assert "not found" in get_change_request(999)


# ── Main sees them, in lockstep with its prompt ─────────────────────────────

@pytest.mark.parametrize("flag", [True, False])
def test_main_has_the_read_tools_with_or_without_change_management(flag):
    """They read fix plans and runs too (acceptance is not a Change Management feature), so they are not gated."""
    prompt, names = _build_main(flag)
    assert READ_TOOLS <= names
    for name in READ_TOOLS:
        assert f"- {name}:" in prompt, name
    assert "/accept I<N>" in prompt and "HUMAN action" in prompt
