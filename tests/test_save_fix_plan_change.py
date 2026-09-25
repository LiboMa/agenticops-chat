import json
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, CloudAccount, FixExecution, FixPlan, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/sfp.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[])); s.commit()
    yield s
    s.close()
    models_mod._engine = None


def _cr_under_review(db):
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=Actor("user", "a", 1, ("read", "write")), title="t",
                                      description="d", account_name="dev", start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    return cr["id"]


GOOD = dict(risk_level="L1", title="tag", summary="s", steps=json.dumps([{"action": "tag", "command": "aws ec2 create-tags"}]),
            rollback_plan=json.dumps({"steps": ["aws ec2 delete-tags"]}), post_checks=json.dumps([{"check": "present", "command": "aws ec2 describe-tags"}]))


def test_change_plan_created_and_dedup_updates_draft(db):
    from agenticops.tools.metadata_tools import save_fix_plan
    cr_id = _cr_under_review(db)
    out = save_fix_plan(plan_kind="change", change_request_id=cr_id, **GOOD)
    assert "saved" in out and "ChangeRequest" in out
    plan = db.query(FixPlan).one()
    assert plan.plan_kind == "change" and plan.change_request_id == cr_id and plan.health_issue_id is None and plan.status == "draft"
    out2 = save_fix_plan(plan_kind="change", change_request_id=cr_id, **{**GOOD, "title": "tag v2"})
    assert "UPDATED" in out2 and db.query(FixPlan).count() == 1
    ev = [e.event_type for e in db.query(PipelineEvent).filter_by(change_request_id=cr_id)]
    assert "fix_plan_created" in ev and "fix_plan_updated" in ev


def test_change_plan_requires_rollback_and_post_checks(db):
    from agenticops.tools.metadata_tools import save_fix_plan
    cr_id = _cr_under_review(db)
    out = save_fix_plan(plan_kind="change", change_request_id=cr_id, **{**GOOD, "rollback_plan": "{}"})
    assert "rollback_plan" in out and db.query(FixPlan).count() == 0
    out = save_fix_plan(plan_kind="change", change_request_id=cr_id, **{**GOOD, "post_checks": "[]"})
    assert "post_checks" in out and db.query(FixPlan).count() == 0


def test_change_plan_requires_under_review(db):
    from agenticops.tools.metadata_tools import save_fix_plan
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=Actor("user", "a", 1, ("read", "write")), title="t", description="d", start_review=False)
    out = save_fix_plan(plan_kind="change", change_request_id=cr["id"], **GOOD)
    assert "under_review" in out and db.query(FixPlan).count() == 0


def test_change_plan_is_keyed_to_the_review_attempt(db):
    """A stale SRE run (its attempt was rolled back and restarted) must neither create nor rewrite the newer
    attempt's plan; the live attempt saves and updates as before."""
    from agenticops.services import change_service as cs
    from agenticops.tools.metadata_tools import save_fix_plan
    cr_id = _cr_under_review(db)
    with cs._session() as s:  # a timeout + restart happened: the row is now attempt 2, still under_review
        s.get(ChangeRequest, cr_id).review_attempt = 2
    refusal = f"ChangeRequest #{cr_id} is no longer at review attempt 1 (the review was rolled back and restarted)"

    def save(attempt, **overrides):
        token = cs._review_attempt_var.set(attempt)
        try:
            return save_fix_plan(plan_kind="change", change_request_id=cr_id, **{**GOOD, **overrides})
        finally:
            cs._review_attempt_var.reset(token)

    assert save(1) == refusal and db.query(FixPlan).count() == 0  # a returned string, and none created
    assert "saved" in save(2)  # the live attempt saves as today
    db.expire_all()
    plan = db.query(FixPlan).one()
    before = (plan.id, plan.title, plan.steps, plan.updated_at)
    events = db.query(PipelineEvent).filter_by(change_request_id=cr_id).count()
    assert save(1, title="stale rewrite") == refusal
    db.expire_all()
    plan = db.query(FixPlan).one()  # still exactly one plan, unchanged
    assert (plan.id, plan.title, plan.steps, plan.updated_at) == before
    assert db.query(PipelineEvent).filter_by(change_request_id=cr_id).count() == events
    assert "UPDATED" in save(2, title="tag v2")  # ... and updates as today
    db.expire_all()
    assert db.query(FixPlan).one().title == "tag v2"


def test_change_plan_does_not_trigger_fix_auto_approve(db):
    from agenticops.tools.metadata_tools import save_fix_plan
    cr_id = _cr_under_review(db)
    with patch("agenticops.services.pipeline_service.trigger_auto_approve") as auto, \
         patch("agenticops.services.notification_service.notify_fix_planned") as notify:
        save_fix_plan(plan_kind="change", change_request_id=cr_id, **GOOD)
    assert not auto.called and not notify.called


def test_fix_plan_path_unchanged(db):
    from agenticops.models import HealthIssue, RCAResult
    from agenticops.tools.metadata_tools import save_fix_plan
    issue = HealthIssue(title="t", description="d", severity="low", source="t", status="root_cause_identified", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9); db.add(rca); db.commit()
    with patch("agenticops.services.pipeline_service.trigger_auto_approve") as auto:
        out = save_fix_plan(health_issue_id=issue.id, rca_result_id=rca.id, **GOOD)
    assert "saved" in out and auto.called
    assert db.query(FixPlan).one().plan_kind == "fix"


def test_get_approved_fix_plan_reports_kind_and_accepts_executing(db):
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    cr_id = _cr_under_review(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s", status="approved",
                   rollback_plan={"x": 1}, post_checks=[{"check": "c"}])
    db.add(plan); db.commit()
    data = json.loads(get_approved_fix_plan(plan.id))
    assert data["plan_kind"] == "change" and data["change_request_id"] == cr_id and data["health_issue_id"] is None
    plan.status = "executing"; db.commit()
    assert json.loads(get_approved_fix_plan(plan.id))["status"] == "executing"  # queued route: already claimed
    plan.status = "draft"; db.commit()
    assert get_approved_fix_plan(plan.id).startswith("REJECTED")


def test_save_execution_result_for_change_calls_mapper(db):
    from agenticops.tools.metadata_tools import save_execution_result
    cr_id = _cr_under_review(db)
    with get_session() as s:
        pass
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s", status="executing",
                   rollback_plan={"x": 1}, post_checks=[{"check": "c"}])
    db.add(plan); db.commit()
    with patch("agenticops.services.change_service.on_execution_result", return_value={"status": "completed"}) as mapper, \
         patch("agenticops.services.notification_service.notify_execution_result") as fix_notify:
        out = save_execution_result(fix_plan_id=plan.id, health_issue_id=None, status="succeeded",
                                    post_check_results=json.dumps([{"check": "c", "status": "pass"}]))
    assert "FixExecution #" in out
    mapper.assert_called_once()
    assert mapper.call_args.args == (plan.id, "succeeded")
    assert mapper.call_args.kwargs["post_check_results"] == [{"check": "c", "status": "pass"}]
    assert not fix_notify.called
    db.expire_all()
    assert db.get(FixPlan, plan.id).status == "executed"
    ev = db.query(PipelineEvent).filter_by(change_request_id=cr_id, event_type="execution_completed").count()
    assert ev == 1


def test_executor_service_crash_calls_mapper(db):
    from agenticops.services.executor_service import ExecutorService
    cr_id = _cr_under_review(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s", status="executing",
                   rollback_plan={"x": 1}, post_checks=[{"check": "c"}])
    db.add(plan); db.flush()
    ex = FixExecution(fix_plan_id=plan.id, status="running", executed_by="u"); db.add(ex); db.commit()
    with patch("agenticops.services.change_service.on_execution_result") as mapper:
        ExecutorService()._mark_crashed(ex.id, plan.id, "boom")
    mapper.assert_called_once_with(plan.id, "failed", error="Agent crashed: boom")
