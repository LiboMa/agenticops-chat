"""Effort (thinking budget) policy — MVP-2.2.1.

Covers the pure resolver, the RCA escalation inputs, and the per-session
override plumbing. No Bedrock calls: budget resolution is a pure function.

Run:
    pytest tests/test_effort_policy.py -v
"""

import pytest

from agenticops.agents.preamble import (
    effort_to_budget,
    resolve_thinking_budget,
    thinking_fields_for_budget,
    thinking_request_fields,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def effort_settings():
    """Pin effort settings to plan defaults."""
    from agenticops.config import settings

    keys = (
        "agent_rca_thinking_budget", "agent_main_thinking_budget",
        "thinking_escalation_step", "thinking_budget_min",
        "thinking_effort_presets",
    )
    saved = {k: getattr(settings, k) for k in keys}
    settings.agent_rca_thinking_budget = 4096
    settings.agent_main_thinking_budget = 0
    settings.thinking_escalation_step = 4096
    settings.thinking_budget_min = 1024
    settings.thinking_effort_presets = {"off": 0, "standard": 4096, "deep": 12288}
    yield settings
    for k, v in saved.items():
        setattr(settings, k, v)


# ── Task 1: pure resolver ─────────────────────────────────────────────


class TestResolveThinkingBudget:
    def test_base_from_yaml(self, effort_settings):
        assert resolve_thinking_budget("rca", 16384) == 4096

    def test_escalation_tiers(self, effort_settings):
        assert resolve_thinking_budget("rca", 16384, escalate=1) == 8192
        assert resolve_thinking_budget("rca", 16384, escalate=2) == 12288

    def test_clamped_below_max_tokens(self, effort_settings):
        """Escalation must never reach max_tokens (Bedrock rejects budget >= max)."""
        got = resolve_thinking_budget("rca", 8192, escalate=5)
        assert got < 8192
        assert got <= 8192 - effort_settings.thinking_budget_min

    def test_off_stays_off_under_escalation(self, effort_settings):
        """base=0 means 'off'; escalation must not switch thinking on."""
        assert resolve_thinking_budget("main", 16384, escalate=3) == 0

    def test_illegal_low_base_disabled(self, effort_settings, caplog):
        effort_settings.agent_rca_thinking_budget = 512  # below Bedrock minimum
        assert resolve_thinking_budget("rca", 16384) == 0

    def test_max_tokens_too_small_disables(self, effort_settings):
        """No room for a legal budget at all → off, not an illegal request."""
        assert resolve_thinking_budget("rca", 1024) == 0

    def test_override_wins_over_base_and_escalation(self, effort_settings):
        assert resolve_thinking_budget("rca", 16384, escalate=2, override="off") == 0
        assert resolve_thinking_budget("main", 16384, override="deep") == 12288
        assert resolve_thinking_budget("main", 16384, override="standard") == 4096

    def test_unknown_override_falls_back_to_auto(self, effort_settings):
        assert resolve_thinking_budget("rca", 16384, override="turbo") == 4096
        assert resolve_thinking_budget("rca", 16384, override="") == 4096
        assert resolve_thinking_budget("rca", 16384, override=None) == 4096


class TestEffortToBudget:
    def test_presets(self, effort_settings):
        assert effort_to_budget("off", 16384) == 0
        assert effort_to_budget("standard", 16384) == 4096
        assert effort_to_budget("deep", 16384) == 12288

    def test_unknown_is_none(self, effort_settings):
        assert effort_to_budget("wat", 16384) is None
        assert effort_to_budget("", 16384) is None
        assert effort_to_budget(None, 16384) is None

    def test_deep_clamped_for_small_max_tokens(self, effort_settings):
        got = effort_to_budget("deep", 8192)
        assert got is not None and got < 8192


class TestThinkingFields:
    def test_fields_shape(self, effort_settings):
        assert thinking_fields_for_budget(4096, 16384) == {
            "thinking": {"type": "enabled", "budget_tokens": 4096}
        }

    def test_zero_and_illegal_give_none(self, effort_settings):
        assert thinking_fields_for_budget(0, 16384) is None
        assert thinking_fields_for_budget(512, 16384) is None
        assert thinking_fields_for_budget(16384, 16384) is None

    def test_legacy_wrapper_unchanged(self, effort_settings):
        """thinking_request_fields keeps its 2.2.0 contract (7 call sites)."""
        assert thinking_request_fields("rca", 16384) == {
            "thinking": {"type": "enabled", "budget_tokens": 4096}
        }
        assert thinking_request_fields("main", 16384) is None


# ── Task 2: RCA escalation inputs ─────────────────────────────────────


class TestRcaEscalation:
    def _issue(self, severity="high", metric_data=None):
        from agenticops.models import HealthIssue

        return HealthIssue(
            resource_id="i-1", severity=severity, source="test",
            title="t", description="d", metric_data=metric_data,
        )

    def _rca(self, verdict=None):
        from agenticops.models import RCAResult

        return RCAResult(health_issue_id=1, root_cause="rc", confidence=0.5,
                         critic_verdict=verdict)

    def test_normal_issue_no_escalation(self):
        from agenticops.agents.rca_agent import _rca_escalation

        level, reason = _rca_escalation(self._issue(), None)
        assert level == 0
        assert reason == ""

    def test_critical_escalates(self):
        from agenticops.agents.rca_agent import _rca_escalation

        level, reason = _rca_escalation(self._issue(severity="critical"), None)
        assert level == 1
        assert "critical" in reason

    def test_needs_review_rerun_escalates(self):
        from agenticops.agents.rca_agent import _rca_escalation

        issue = self._issue(metric_data={"needs_review": True})
        level, reason = _rca_escalation(issue, None)
        assert level == 1
        assert "rerun" in reason

    def test_disputed_by_execution_escalates(self):
        from agenticops.agents.rca_agent import _rca_escalation

        level, reason = _rca_escalation(
            self._issue(), self._rca(verdict="disputed_by_execution"))
        assert level == 1
        assert "rerun" in reason

    def test_critical_and_rerun_stack(self):
        from agenticops.agents.rca_agent import _rca_escalation

        issue = self._issue(severity="critical", metric_data={"needs_review": True})
        level, reason = _rca_escalation(issue, None)
        assert level == 2
        assert "critical" in reason and "rerun" in reason

    def test_supported_verdict_does_not_escalate(self):
        from agenticops.agents.rca_agent import _rca_escalation

        level, _ = _rca_escalation(self._issue(), self._rca(verdict="supported"))
        assert level == 0

    def test_none_issue_is_fail_safe(self):
        """Attribution failure must never raise the price."""
        from agenticops.agents.rca_agent import _rca_escalation

        assert _rca_escalation(None, None) == (0, "")


# ── Task 3/4: per-session effort override ─────────────────────────────


class TestSessionEffortColumn:
    def test_roundtrip_and_null(self, tmp_path):
        import agenticops.models as models_mod
        from agenticops.config import settings
        from agenticops.models import Base, ChatSession, get_session

        models_mod._engine = None
        saved_url = settings.database_url
        settings.database_url = f"sqlite:///{tmp_path}/effort.db"
        try:
            Base.metadata.create_all(models_mod.get_engine())
            db = get_session()
            db.add_all([
                ChatSession(session_id="s-auto", name="a"),
                ChatSession(session_id="s-deep", name="b", effort="deep"),
            ])
            db.commit()
            assert db.query(ChatSession).filter_by(session_id="s-auto").one().effort is None
            assert db.query(ChatSession).filter_by(session_id="s-deep").one().effort == "deep"
            db.close()
        finally:
            settings.database_url = saved_url
            models_mod._engine = None

    def test_ensure_column_is_idempotent(self, tmp_path):
        """init_db() twice on a legacy schema must not raise."""
        import agenticops.models as models_mod
        from agenticops.config import settings
        from sqlalchemy import text

        models_mod._engine = None
        saved_url = settings.database_url
        settings.database_url = f"sqlite:///{tmp_path}/legacy.db"
        try:
            engine = models_mod.get_engine()
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE chat_sessions ("
                    "id INTEGER PRIMARY KEY, session_id VARCHAR(36), name VARCHAR(200))"
                ))
            models_mod.init_db()
            models_mod.init_db()
            with engine.connect() as conn:
                cols = {r[1] for r in conn.execute(text("PRAGMA table_info(chat_sessions)"))}
            assert "effort" in cols
            assert "model_id" in cols
        finally:
            settings.database_url = saved_url
            models_mod._engine = None


class TestAgentEffortWiring:
    """create_main_agent must translate an effort override into request fields."""

    def _build(self, **kw):
        from unittest.mock import MagicMock, patch

        # get_bedrock_boto_session is imported inside create_main_agent → patch at source
        with patch("agenticops.agents.main_agent.Agent") as MockAgent, \
             patch("agenticops.agents.main_agent.BedrockModel") as MockModel, \
             patch("agenticops.config.get_bedrock_boto_session",
                   return_value=MagicMock()), \
             patch("agenticops.agents.main_agent._safe_mcp_clients", return_value=[]), \
             patch("agenticops.memory.curator.maybe_run_curator"), \
             patch("agenticops.skills.curator.maybe_run_skills_curator"):
            MockAgent.return_value = MagicMock()
            from agenticops.agents.main_agent import create_main_agent

            create_main_agent(**kw)
            return MockModel.call_args.kwargs

    def test_deep_override_enables_thinking(self, effort_settings):
        kwargs = self._build(effort_override="deep")
        fields = kwargs.get("additional_request_fields")
        assert fields and fields["thinking"]["budget_tokens"] == 12288

    def test_no_override_matches_2_2_0_behaviour(self, effort_settings):
        """agent_main_thinking_budget=0 → byte-identical to 2.2.0 (no fields)."""
        assert self._build().get("additional_request_fields") is None
        assert self._build(effort_override="").get("additional_request_fields") is None

    def test_off_override_disables_even_when_base_set(self, effort_settings):
        effort_settings.agent_main_thinking_budget = 4096
        assert self._build(effort_override="off").get("additional_request_fields") is None
        assert self._build().get("additional_request_fields") is not None
