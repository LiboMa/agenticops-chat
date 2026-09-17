"""Schema tests for the generalized plan table, command_audits and audit_logs.actor (MVP-2.6.0)."""
import pytest
from sqlalchemy.exc import IntegrityError

from agenticops.models import (
    Base, ChangeRequest, CommandAudit, FixExecution, FixPlan, HealthIssue,
    PipelineEvent, RCAResult, get_engine, get_session, transition_plan,
)


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401 — register audit_logs
    from agenticops.config import settings

    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/schema.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


def _cr(session) -> ChangeRequest:
    cr = ChangeRequest(title="tag ec2", description="add Env=prod", requested_by="user:admin", source="web")
    session.add(cr)
    session.flush()
    return cr


def _issue_and_rca(session):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="open", resource_id="r")
    session.add(issue)
    session.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    session.add(rca)
    session.flush()
    return issue, rca


def test_change_plan_has_no_issue(db):
    cr = _cr(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    db.commit()
    assert plan.health_issue_id is None and plan.rca_result_id is None
    assert plan.change_request.id == cr.id
    assert cr.plans[0].id == plan.id


def test_default_plan_kind_is_fix(db):
    issue, rca = _issue_and_rca(db)
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    db.commit()
    assert plan.plan_kind == "fix"


def test_fix_plan_without_issue_violates_check(db):
    plan = FixPlan(plan_kind="fix", risk_level="L1", title="t", summary="s")
    db.add(plan)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_change_plan_with_issue_violates_check(db):
    cr = _cr(db)
    issue, rca = _issue_and_rca(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, health_issue_id=issue.id,
                   rca_result_id=rca.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_execution_and_event_can_belong_to_a_change(db):
    cr = _cr(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    db.flush()
    db.add(FixExecution(fix_plan_id=plan.id, status="pending", executed_by="user:admin"))
    db.add(PipelineEvent(change_request_id=cr.id, event_type="change_requested", stage="intake", status="completed"))
    db.commit()
    ev = db.query(PipelineEvent).filter_by(change_request_id=cr.id).one()
    assert ev.health_issue_id is None


def test_command_audit_row(db):
    row = CommandAudit(actor="cli:malibo", tool="run_aws_cli", tier="write", command="aws ec2 create-tags ...",
                       outcome="executed", exit_code=0, trace_id="TRC-abcd1234")
    db.add(row)
    db.commit()
    assert db.query(CommandAudit).count() == 1


def test_audit_log_has_actor_column(db):
    from agenticops.audit.models import AuditLog
    db.add(AuditLog(action="plan.approved", entity_type="fix_plan", entity_id="1", actor="user:admin"))
    db.commit()
    assert db.query(AuditLog).one().actor == "user:admin"


def test_transition_plan_updated_at_round_trips_through_db(db):
    issue, rca = _issue_and_rca(db)
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    db.commit()
    transition_plan(plan, "approved")
    db.commit()
    db.expire_all()
    db.refresh(plan)
    assert plan.status == "approved"
    assert plan.updated_at is not None
