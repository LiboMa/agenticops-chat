"""2.7.0 E2E observations 4 and 5: facts the code knows are recorded by the code, not asked of the model.

4. RCAResult.model_id was empty — save_rca_result took it only as the agent's own argument, and the agent never
   knows its model. rca_agent now names the model it built the agent with in the Run Context.
5. A run's duration_ms was the executor's own report (45000 for both E2E runs). executor_agent now records when
   its run began in the Run Context, and save_execution_result measures from it (or from the queued ticket's
   claim); the agent's figure is kept only when the code knows no start.
"""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from agenticops.config import settings
from agenticops.models import Base, FixExecution, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.run_context import get_run_context, run_context
from agenticops.services import change_service as cs
from agenticops.services import notification_service as ns
from agenticops.services import plan_content as pc

OPUS = "global.anthropic.claude-opus-5"
CHECK = {"check": "healthy", "command": "aws ec2 describe-instance-status --instance-ids i-0abc"}
OK = [{"check_id": "pc-1", "check": "healthy", "status": "passed"}]


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/facts.db")
    monkeypatch.setattr(settings, "executor_auto_resolve", True)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def quiet():
    with patch.object(ns, "notify_event"), \
         patch("agenticops.services.resolution_service.trigger_post_resolution"), \
         patch.object(ns, "notify_execution_pending_acceptance"), \
         patch.object(cs, "notify_execution_pending_acceptance"):
        yield


def _issue(db, status="investigating"):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status=status, resource_id="i-0abc")
    db.add(issue); db.commit()
    return issue.id


def _approved_plan(db):
    issue_id = _issue(db, status="fix_approved")
    rca = RCAResult(health_issue_id=issue_id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue_id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   steps=[{"command": "aws ec2 reboot-instances --instance-ids i-0abc"}], post_checks=[CHECK],
                   status="approved", approved_by="user:alice")
    db.add(plan); db.flush()
    pc.stamp_content(db, plan)
    pc.stamp_approval(db, plan)
    db.commit()
    return plan.id


def _latest(model, **by):
    s = get_session()
    try:
        return s.query(model).filter_by(**by).order_by(model.id.desc()).first()
    finally:
        s.close()


# ── 4. the RCA's model ────────────────────────────────────────────────


def _save_rca(issue_id, model_id=""):
    from agenticops.tools.metadata_tools import save_rca_result
    return save_rca_result(health_issue_id=issue_id, root_cause="disk full", confidence=0.8,
                           contributing_factors="[]", recommendations="[]", model_id=model_id)


def test_an_rca_records_the_model_its_agent_was_built_with(db):
    issue_id = _issue(db)
    with run_context(model_id=OPUS):
        _save_rca(issue_id)
    assert _latest(RCAResult, health_issue_id=issue_id).model_id == OPUS


def test_the_codes_model_wins_over_the_agents_own_claim(db):
    issue_id = _issue(db)
    with run_context(model_id=OPUS):
        _save_rca(issue_id, model_id="claude-3-sonnet")
    assert _latest(RCAResult, health_issue_id=issue_id).model_id == OPUS


def test_without_a_context_the_argument_is_kept(db):
    issue_id = _issue(db)
    _save_rca(issue_id, model_id="claude-x")
    assert _latest(RCAResult, health_issue_id=issue_id).model_id == "claude-x"


def test_rca_agent_names_its_model_in_the_run_context():
    seen = {}

    def invoke(agent, prompt, **kw):
        seen["model_id"] = get_run_context().model_id
        return "done"

    ra = "agenticops.agents.rca_agent"
    with patch(f"{ra}.Agent") as agent_cls, patch(f"{ra}.BedrockModel"), \
         patch("agenticops.config.get_agent_model_config", return_value=(OPUS, 16384)), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch(f"{ra}.resolve_rca_effort", return_value=(0, None)), \
         patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke), \
         patch("agenticops.services.agent_log_service.track_agent"), \
         patch("agenticops.services.rca_quality.run_post_rca_pipeline"), \
         patch("agenticops.models.get_db_session", side_effect=RuntimeError("no db here")):
        agent_cls.return_value.messages = []
        from agenticops.agents.rca_agent import rca_agent
        out = rca_agent(issue_id=7)
    assert out == "done", out
    assert seen["model_id"] == OPUS
    assert get_run_context().model_id is None  # reset after the run


# ── 5. the run's duration ─────────────────────────────────────────────


def _save_run(plan_id, reported_ms=45000):
    from agenticops.tools.metadata_tools import save_execution_result
    return save_execution_result(fix_plan_id=plan_id, status="succeeded", post_check_results=json.dumps(OK),
                                 step_results=json.dumps([{"status": "succeeded"}]), duration_ms=reported_ms)


def test_a_run_is_timed_from_when_the_executor_began(db):
    plan_id = _approved_plan(db)
    began = datetime.now(timezone.utc) - timedelta(seconds=90)
    with run_context(run_started_at=began):
        _save_run(plan_id)
    run = _latest(FixExecution, fix_plan_id=plan_id)
    assert 89_000 <= run.duration_ms <= 120_000, run.duration_ms
    assert abs((run.started_at.replace(tzinfo=timezone.utc) - began).total_seconds()) < 1


def test_a_queued_run_is_timed_from_its_claim(db):
    plan_id = _approved_plan(db)
    claimed = datetime.now(timezone.utc) - timedelta(seconds=120)
    db.add(FixExecution(fix_plan_id=plan_id, health_issue_id=None, status="running", started_at=claimed,
                        executed_by="user:alice"))
    db.commit()
    ticket = _latest(FixExecution, fix_plan_id=plan_id)
    with run_context(execution_id=ticket.id, fix_plan_id=plan_id):
        _save_run(plan_id)  # reports 45000 — outside the measured range below
    run = _latest(FixExecution, fix_plan_id=plan_id)
    assert run.id == ticket.id
    assert 119_000 <= run.duration_ms <= 150_000, run.duration_ms


def test_without_a_known_start_the_reported_figure_is_kept(db):
    plan_id = _approved_plan(db)
    _save_run(plan_id, reported_ms=1234)
    assert _latest(FixExecution, fix_plan_id=plan_id).duration_ms == 1234


@contextmanager
def _executor_build():
    ea = "agenticops.agents.executor_agent"
    with patch(f"{ea}.Agent"), patch(f"{ea}.BedrockModel"), \
         patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch(f"{ea}.get_cli_tool_for_issue", return_value=None), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.services.agent_log_service.track_agent"):
        yield


def test_executor_agent_records_when_its_run_began(db, monkeypatch):
    monkeypatch.setattr(settings, "executor_enabled", True)
    plan_id = _approved_plan(db)
    seen = {}

    def invoke(agent, prompt, **kw):
        seen["started"] = get_run_context().run_started_at
        return "done"

    before = datetime.now(timezone.utc)
    with _executor_build(), patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke):
        from agenticops.agents.executor_agent import executor_agent
        out = executor_agent(fix_plan_id=plan_id)
    assert out == "done", out
    assert seen["started"] is not None and before <= seen["started"] <= datetime.now(timezone.utc)
    assert get_run_context().run_started_at is None  # reset after the run
