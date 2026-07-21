"""RCA quality quintet (MVP-2.2.0) — thinking, evidence gate, critic,
confidence gate, incident memory, watchdog, save purification.

Run:
    pytest tests/test_rca_quality.py -v
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from agenticops.models import (
    Base,
    FixExecution,
    FixPlan,
    HealthIssue,
    RCAResult,
    get_session,
)


@pytest.fixture
def db_session(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/test_rca_quality.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def rca_settings():
    from agenticops.config import settings

    saved = {k: getattr(settings, k) for k in (
        "rca_min_confidence_for_autofix", "rca_critic_enabled",
        "rca_incident_memory_enabled", "rca_incident_memory_max",
        "agent_rca_thinking_budget",
    )}
    settings.rca_min_confidence_for_autofix = 0.6
    settings.rca_critic_enabled = True
    settings.rca_incident_memory_enabled = True
    settings.rca_incident_memory_max = 3
    yield settings
    for k, v in saved.items():
        setattr(settings, k, v)


def _seed_issue(db_session, **kw):
    defaults = dict(
        resource_id="i-abc", severity="high", source="cloudwatch_alarm",
        title="High CPU on i-abc", description="CPU > 90%", status="open",
        issue_type="cpu_spike", fingerprint="fp-test-1",
    )
    defaults.update(kw)
    issue = HealthIssue(**defaults)
    db_session.add(issue)
    db_session.commit()
    return issue.id


def _save_rca(db_session, issue_id, *, confidence=0.9, evidence=None):
    rca = RCAResult(
        health_issue_id=issue_id, root_cause="Deploy at 14:02 saturated CPU",
        confidence=confidence,
        evidence=evidence if evidence is not None else [],
    )
    db_session.add(rca)
    db_session.commit()
    return rca.id


def _messages_with_tool_trace(text: str) -> list:
    """Fabricate a Strands message list containing one toolResult with text."""
    return [
        {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "t1", "name": "lookup_cloudtrail_events",
                         "input": {"resource_id": "i-abc"}}},
        ]},
        {"role": "user", "content": [
            {"toolResult": {"toolUseId": "t1", "content": [{"text": text}]}},
        ]},
    ]


def _run_pipeline(issue_id, messages, critic_json=None):
    """run_post_rca_pipeline with LLM + side-effects mocked."""
    from agenticops.services import rca_quality

    critic_text = json.dumps(critic_json or {"verdict": "supported", "notes": "solid"})
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    with patch("agenticops.services.signal_gate._call_bedrock",
               return_value=(critic_text, {"input": 5, "output": 5})), \
         patch("agenticops.services.pipeline_service.trigger_auto_sre") as sre, \
         patch("agenticops.services.notification_service.notify_rca_completed"), \
         patch("agenticops.services.notification_service.notify_im_origin"), \
         patch("agenticops.services.notification_service.notify_event"):
        rca_quality.run_post_rca_pipeline(issue_id, messages, started)
    return sre


class TestThinking:
    def test_fields_shape(self, rca_settings):
        from agenticops.agents.preamble import thinking_request_fields

        rca_settings.agent_rca_thinking_budget = 4096
        fields = thinking_request_fields("rca", 16384)
        assert fields == {"thinking": {"type": "enabled", "budget_tokens": 4096}}

    def test_zero_budget_off(self, rca_settings):
        from agenticops.agents.preamble import thinking_request_fields

        rca_settings.agent_rca_thinking_budget = 0
        assert thinking_request_fields("rca", 16384) is None

    def test_budget_exceeding_max_tokens_off(self, rca_settings):
        from agenticops.agents.preamble import thinking_request_fields

        rca_settings.agent_rca_thinking_budget = 20000
        assert thinking_request_fields("rca", 16384) is None


class TestSaveRcaPurity:
    def test_save_persists_evidence_and_does_not_trigger_sre(self, db_session, rca_settings):
        from agenticops.tools import metadata_tools

        issue_id = _seed_issue(db_session)
        with patch("agenticops.services.pipeline_service.trigger_auto_sre") as sre, \
             patch("agenticops.services.notification_service.notify_rca_completed") as note:
            msg = metadata_tools.save_rca_result(
                health_issue_id=issue_id, root_cause="rc", confidence=0.9,
                contributing_factors="[]", recommendations='["scale up"]',
                evidence='[{"type":"metric","ref":"CPUUtilization","summary":"92%"}]',
            )
        assert "saved" in msg
        sre.assert_not_called()
        note.assert_not_called()
        rca = db_session.query(RCAResult).one()
        assert rca.evidence[0]["ref"] == "CPUUtilization"
        issue = db_session.get(HealthIssue, issue_id)
        db_session.refresh(issue)
        assert issue.status == "root_cause_identified"

    def test_illegal_transition_keeps_status(self, db_session, rca_settings):
        from agenticops.tools import metadata_tools

        issue_id = _seed_issue(db_session, status="resolved")
        msg = metadata_tools.save_rca_result(
            health_issue_id=issue_id, root_cause="rc", confidence=0.9,
            contributing_factors="[]", recommendations="[]",
        )
        assert "status unchanged" in msg
        issue = db_session.get(HealthIssue, issue_id)
        db_session.refresh(issue)
        assert issue.status == "resolved"


class TestEvidenceGate:
    def test_grounded_evidence_verified_true(self, db_session, rca_settings):
        issue_id = _seed_issue(db_session)
        _save_rca(db_session, issue_id, confidence=0.9,
                  evidence=[{"type": "cloudtrail", "ref": "RunInstances event at 14:02",
                             "summary": "deploy"}])
        messages = _messages_with_tool_trace(
            "Events: RunInstances event at 14:02 by role deployer")
        sre = _run_pipeline(issue_id, messages)
        rca = db_session.query(RCAResult).one()
        db_session.refresh(rca)
        assert rca.evidence_verified is True
        assert rca.confidence == pytest.approx(0.9)
        sre.assert_called_once()

    def test_fabricated_evidence_penalized(self, db_session, rca_settings):
        """Acceptance #6: fake ref → verified=false + confidence x0.6."""
        issue_id = _seed_issue(db_session)
        _save_rca(db_session, issue_id, confidence=0.9,
                  evidence=[{"type": "cloudtrail", "ref": "DeleteBucket by admin-x",
                             "summary": "fabricated"}])
        messages = _messages_with_tool_trace("No events found in the window.")
        _run_pipeline(issue_id, messages)
        rca = db_session.query(RCAResult).one()
        db_session.refresh(rca)
        assert rca.evidence_verified is False
        assert rca.confidence == pytest.approx(0.54)  # 0.9 * 0.6


class TestConfidenceGateAndCritic:
    def test_low_confidence_no_autofix(self, db_session, rca_settings):
        """Acceptance #5: confidence < threshold → no auto-SRE + needs_review."""
        issue_id = _seed_issue(db_session)
        _save_rca(db_session, issue_id, confidence=0.3)
        sre = _run_pipeline(issue_id, _messages_with_tool_trace("trace"))
        sre.assert_not_called()
        issue = db_session.get(HealthIssue, issue_id)
        db_session.refresh(issue)
        assert issue.metric_data.get("needs_review") is True

    def test_critic_refuted_blocks_autofix_and_penalizes(self, db_session, rca_settings):
        issue_id = _seed_issue(db_session)
        _save_rca(db_session, issue_id, confidence=0.9)
        sre = _run_pipeline(issue_id, _messages_with_tool_trace("trace"),
                            critic_json={"verdict": "refuted", "notes": "alternative cause"})
        sre.assert_not_called()
        rca = db_session.query(RCAResult).one()
        db_session.refresh(rca)
        assert rca.critic_verdict == "refuted"
        assert rca.confidence == pytest.approx(0.45)  # 0.9 * 0.5

    def test_high_confidence_supported_triggers_sre_once(self, db_session, rca_settings):
        issue_id = _seed_issue(db_session)
        _save_rca(db_session, issue_id, confidence=0.85)
        sre = _run_pipeline(issue_id, _messages_with_tool_trace("trace"))
        sre.assert_called_once()

    def test_no_result_logs_failed(self, db_session, rca_settings):
        from agenticops.services import rca_quality

        issue_id = _seed_issue(db_session)
        started = datetime.now(timezone.utc)
        with patch("agenticops.services.pipeline_events.log_event") as log_event, \
             patch("agenticops.services.pipeline_service.trigger_auto_sre") as sre:
            rca_quality.run_post_rca_pipeline(issue_id, [], started)
        sre.assert_not_called()
        calls = [c for c in log_event.call_args_list if c.args[1] == "rca_completed"]
        assert calls and calls[0].args[3] == "failed"


class TestIncidentMemory:
    def test_block_contains_prior_conclusion_and_dispute_flag(self, db_session, rca_settings):
        """Acceptance #7b: repeat RCA sees INCIDENT MEMORY with prior verdicts."""
        from agenticops.agents.rca_agent import _build_incident_memory

        prior_id = _seed_issue(db_session, status="resolved",
                               resolved_at=datetime.now(timezone.utc))
        rca = RCAResult(health_issue_id=prior_id, root_cause="Old kernel bug caused spike",
                        confidence=0.8, critic_verdict="disputed_by_execution")
        db_session.add(rca)
        db_session.flush()
        plan = FixPlan(health_issue_id=prior_id, rca_result_id=rca.id, risk_level="L1",
                       title="Patch kernel", summary="s", status="executed")
        db_session.add(plan)
        db_session.flush()
        db_session.add(FixExecution(fix_plan_id=plan.id, health_issue_id=prior_id,
                                    status="failed"))
        db_session.commit()

        new_id = _seed_issue(db_session)  # same fingerprint fp-test-1
        issue = db_session.get(HealthIssue, new_id)
        block = _build_incident_memory(issue)
        assert "INCIDENT MEMORY" in block
        assert "Old kernel bug" in block
        assert "refuted by a failed fix" in block

    def test_disabled_returns_empty(self, db_session, rca_settings):
        from agenticops.agents.rca_agent import _build_incident_memory

        rca_settings.rca_incident_memory_enabled = False
        issue = db_session.get(HealthIssue, _seed_issue(db_session))
        assert _build_incident_memory(issue) == ""


class TestFeedback:
    def test_rca_feedback_endpoint_records_verdict_and_memory(self, db_session, rca_settings, tmp_path):
        from fastapi.testclient import TestClient
        from agenticops.web.app import app

        issue_id = _seed_issue(db_session)
        _save_rca(db_session, issue_id, confidence=0.8)

        client = TestClient(app)
        with patch("agenticops.memory.agent_memory.AGENT_MEMORY_DIR", tmp_path):
            resp = client.post(f"/api/health-issues/{issue_id}/rca-feedback",
                               json={"verdict": "incorrect", "note": "actual cause was DB lock"})
        assert resp.status_code == 201
        rca = db_session.query(RCAResult).one()
        db_session.refresh(rca)
        assert rca.human_verdict == "incorrect"
        assert rca.verified_at is not None
        memory_files = list((tmp_path / "rca").glob("rca_feedback_issue_*.md"))
        assert len(memory_files) == 1
        assert "INCORRECT" in memory_files[0].read_text()

    def test_mark_fix_failed_disputes_rca(self, db_session, rca_settings):
        """Acceptance #7: failed fix → RCAResult disputed_by_execution."""
        from agenticops.tools import metadata_tools

        issue_id = _seed_issue(db_session, status="fix_executing")
        rca_id = _save_rca(db_session, issue_id, confidence=0.9)
        rca = db_session.get(RCAResult, rca_id)
        plan = FixPlan(health_issue_id=issue_id, rca_result_id=rca_id, risk_level="L1",
                       title="restart", summary="s", status="executing")
        db_session.add(plan)
        db_session.flush()
        execution = FixExecution(fix_plan_id=plan.id, health_issue_id=issue_id, status="failed")
        db_session.add(execution)
        db_session.commit()

        msg = metadata_tools.mark_fix_failed(issue_id, execution.id, reason="command exited 1")
        assert "failed" in msg
        db_session.refresh(rca)
        assert rca.critic_verdict == "disputed_by_execution"
        assert "command exited 1" in (rca.critic_notes or "")


class TestWatchdog:
    def test_timeout_logs_failed_and_flags(self, db_session, rca_settings):
        from agenticops.config import settings
        from agenticops.services import rca_service

        issue_id = _seed_issue(db_session)
        saved = settings.rca_timeout_seconds
        settings.rca_timeout_seconds = 1
        try:
            def _hang(issue_id):
                import time
                time.sleep(5)

            with patch("agenticops.agents.rca_agent.rca_agent", side_effect=_hang), \
                 patch("agenticops.services.pipeline_events.log_event") as log_event:
                rca_service._run_auto_rca(issue_id)
            failed = [c for c in log_event.call_args_list
                      if c.args[1:4] == ("rca_completed", "rca", "failed")]
            assert failed and failed[0].kwargs.get("detail", {}).get("reason") == "timeout"
            issue = db_session.get(HealthIssue, issue_id)
            db_session.refresh(issue)
            assert issue.metric_data.get("needs_review") is True
        finally:
            settings.rca_timeout_seconds = saved
