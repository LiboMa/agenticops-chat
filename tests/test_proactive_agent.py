"""Tests for Proactive Agent — Phase 3 P2."""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from agenticops.proactive.pattern_watch import PatternWatch, PatternAlert
from agenticops.proactive.risk_scorer import RiskScorer, RiskLevel, HealthIssue
from agenticops.proactive.predictive_alert import ProactiveAlert
from agenticops.agents.proactive_agent import ProactiveAgent
from agenticops.memory.agent_memory import AgentMemory
from agenticops.memory.types import MemoryEntry, MemoryType
from agenticops.utils.timeutils import utc_now

run = asyncio.get_event_loop().run_until_complete


def _make_entry(content: str, confidence: float = 0.7, days_ago: int = 0) -> MagicMock:
    entry = MagicMock(spec=MemoryEntry)
    entry.content = content
    entry.confidence = confidence
    entry.created_at = (utc_now() - timedelta(days=days_ago)).isoformat()
    return entry


# ── PatternWatch ──────────────────────────────────────────────

class TestPatternWatch:
    @pytest.fixture
    def watch(self):
        return PatternWatch()

    def test_no_memories(self, watch):
        memory = AsyncMock()
        memory.recall = AsyncMock(return_value=[])
        result = run(watch.scan(memory))
        assert result == []

    def test_below_threshold(self, watch):
        entries = [_make_entry("oom kill pod-1"), _make_entry("oom kill pod-2")]
        memory = AsyncMock()
        memory.recall = AsyncMock(return_value=entries)
        result = run(watch.scan(memory))
        assert result == []  # Only 2, threshold is 3

    def test_recurring_pattern_detected(self, watch):
        entries = [
            _make_entry("oom kill on pod-1"),
            _make_entry("oom killed pod-2"),
            _make_entry("out of memory on pod-3"),
        ]
        memory = AsyncMock()
        memory.recall = AsyncMock(return_value=entries)
        result = run(watch.scan(memory))
        assert len(result) == 1
        assert result[0].category == "oom"
        assert result[0].occurrences == 3

    def test_multiple_categories(self, watch):
        entries = [
            _make_entry("oom kill 1"), _make_entry("oom kill 2"), _make_entry("oom kill 3"),
            _make_entry("cpu spike 1"), _make_entry("cpu throttle 2"), _make_entry("high utilization 3"),
        ]
        memory = AsyncMock()
        memory.recall = AsyncMock(return_value=entries)
        result = run(watch.scan(memory))
        assert len(result) == 2
        cats = {r.category for r in result}
        assert "oom" in cats
        assert "cpu" in cats

    def test_score_higher_for_recent(self, watch):
        recent = [_make_entry("oom kill", confidence=0.8, days_ago=0) for _ in range(3)]
        old = [_make_entry("oom kill", confidence=0.8, days_ago=6) for _ in range(3)]

        mem_r = AsyncMock()
        mem_r.recall = AsyncMock(return_value=recent)
        mem_o = AsyncMock()
        mem_o.recall = AsyncMock(return_value=old)

        recent_alerts = run(watch.scan(mem_r))
        old_alerts = run(watch.scan(mem_o))

        assert recent_alerts[0].score > old_alerts[0].score

    def test_memory_error_handled(self, watch):
        memory = AsyncMock()
        memory.recall = AsyncMock(side_effect=RuntimeError("DB error"))
        result = run(watch.scan(memory))
        assert result == []

    def test_extract_category_unknown(self, watch):
        cat = watch._extract_category(_make_entry("everything is fine"))
        assert cat == ""

    def test_sorted_by_score(self, watch):
        entries = [
            _make_entry("oom 1", 0.9), _make_entry("oom 2", 0.9), _make_entry("oom 3", 0.9),
            _make_entry("disk full 1", 0.3), _make_entry("disk full 2", 0.3), _make_entry("disk full 3", 0.3),
        ]
        memory = AsyncMock()
        memory.recall = AsyncMock(return_value=entries)
        result = run(watch.scan(memory))
        assert result[0].score >= result[-1].score


# ── RiskScorer ────────────────────────────────────────────────

class TestRiskScorer:
    @pytest.fixture
    def scorer(self):
        return RiskScorer()

    def test_low_score_ignore(self, scorer):
        p = PatternAlert(category="oom", occurrences=3, score=0.1)
        assert scorer.score(p) == RiskLevel.IGNORE

    def test_notify_threshold(self, scorer):
        p = PatternAlert(category="oom", occurrences=3, score=0.35)
        assert scorer.score(p) == RiskLevel.NOTIFY

    def test_warn_threshold(self, scorer):
        p = PatternAlert(category="oom", occurrences=5, score=0.7)
        assert scorer.score(p) == RiskLevel.WARN

    def test_escalate_threshold(self, scorer):
        p = PatternAlert(category="oom", occurrences=10, score=0.9)
        assert scorer.score(p) == RiskLevel.ESCALATE

    def test_health_boost(self, scorer):
        p = PatternAlert(category="oom", occurrences=3, score=0.55)
        health = [HealthIssue(area="oom", description="Memory high")]
        # Without health: 0.55 → NOTIFY
        assert scorer.score(p) == RiskLevel.NOTIFY
        # With health boost: 0.55 + 0.2 = 0.75 → WARN
        assert scorer.score(p, health) == RiskLevel.WARN

    def test_health_no_match_no_boost(self, scorer):
        p = PatternAlert(category="oom", occurrences=3, score=0.55)
        health = [HealthIssue(area="cpu", description="CPU high")]
        assert scorer.score(p, health) == RiskLevel.NOTIFY

    def test_risk_level_to_severity(self):
        assert RiskLevel.WARN.to_severity() == "medium"
        assert RiskLevel.ESCALATE.to_severity() == "high"
        assert RiskLevel.NOTIFY.to_severity() == "low"


# ── PredictiveAlert ───────────────────────────────────────────

class TestPredictiveAlert:
    def test_from_pattern(self):
        p = PatternAlert(category="oom", occurrences=5, score=0.8)
        alert = ProactiveAlert.from_pattern(p, RiskLevel.WARN)
        assert alert.source == "proactive_agent"
        assert alert.alert_type == "predictive:oom"
        assert alert.severity == "medium"
        assert "5" in alert.title
        assert alert.metadata["occurrences"] == 5

    def test_to_dict(self):
        alert = ProactiveAlert(title="test", severity="high")
        d = alert.to_dict()
        assert d["title"] == "test"
        assert "timestamp" in d


# ── ProactiveAgent ────────────────────────────────────────────

class TestProactiveAgent:
    @pytest.fixture
    def memory(self, tmp_path):
        db = str(tmp_path / "test.db")
        mem = AgentMemory("proactive_agent", db_path=db)

        class NullEmbed:
            pass
        mem._embedding_client = NullEmbed()
        return mem

    @pytest.fixture
    def agent(self, memory):
        return ProactiveAgent(memory=memory)

    def test_initial_state(self, agent):
        assert not agent.is_running
        stats = agent.get_stats()
        assert stats["alerts_last_hour"] == 0

    def test_cycle_no_patterns(self, agent):
        with patch.object(agent.pattern_watch, "scan", new_callable=AsyncMock, return_value=[]):
            alerts = run(agent._cycle())
        assert alerts == []

    def test_cycle_with_pattern_below_warn(self, agent):
        low_pattern = PatternAlert(category="oom", occurrences=3, score=0.3)
        with patch.object(agent.pattern_watch, "scan", new_callable=AsyncMock, return_value=[low_pattern]):
            alerts = run(agent._cycle())
        assert alerts == []  # NOTIFY only, not WARN

    def test_cycle_generates_alert(self, agent):
        pattern = PatternAlert(category="oom", occurrences=5, score=0.8)
        callback = AsyncMock()
        agent.alert_callback = callback

        with patch.object(agent.pattern_watch, "scan", new_callable=AsyncMock, return_value=[pattern]):
            alerts = run(agent._cycle())

        assert len(alerts) == 1
        assert alerts[0].alert_type == "predictive:oom"
        callback.assert_called_once()

    def test_rate_limiting(self, agent):
        pattern = PatternAlert(category="oom", occurrences=5, score=0.8)
        agent.alert_callback = AsyncMock()

        # Fill rate limit
        now = utc_now()
        for _ in range(5):
            agent._alert_history.append(now)

        with patch.object(agent.pattern_watch, "scan", new_callable=AsyncMock, return_value=[pattern]):
            alerts = run(agent._cycle())
        assert alerts == []  # Rate limited

    def test_cycle_remembers_alert(self, agent):
        pattern = PatternAlert(category="cpu", occurrences=4, score=0.75)
        with patch.object(agent.pattern_watch, "scan", new_callable=AsyncMock, return_value=[pattern]):
            run(agent._cycle())

        # Check memory was written
        recent = run(agent.memory.recall_recent(limit=5))
        proactive = [m for m in recent if "PROACTIVE_ALERT" in m.content]
        assert len(proactive) >= 1

    def test_callback_failure_doesnt_block(self, agent):
        pattern = PatternAlert(category="oom", occurrences=5, score=0.8)
        agent.alert_callback = AsyncMock(side_effect=RuntimeError("callback error"))

        with patch.object(agent.pattern_watch, "scan", new_callable=AsyncMock, return_value=[pattern]):
            alerts = run(agent._cycle())
        assert len(alerts) == 1  # Alert still generated

    def test_t0_security_binding(self, agent):
        """ProactiveAgent binds to T0 on start."""
        from agenticops.skills._security import _agent_tier, _agent_id
        from agenticops.skills._models import SecurityTier
        from agenticops.skills.agent_binding import bind_agent

        # Directly call bind_agent (same as start() does)
        bind_agent("proactive_agent")

        assert _agent_tier.get() == SecurityTier.T0_READONLY
        assert _agent_id.get() == "proactive_agent"
