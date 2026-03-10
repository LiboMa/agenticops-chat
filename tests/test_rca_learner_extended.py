"""Tests for RCA Learner + Evidence module — filling coverage gaps.

Covers:
- rca_learner.py: 0% → target 90%+
- evidence.py: 27% → target 80%+
"""
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticops.analyze.deep_rca import DeepRCAResult
from agenticops.analyze.evidence import EvidenceItem, gather_evidence
from agenticops.analyze.rca import RCAAnalysis
from agenticops.analyze.rca_learner import RCALearner
from agenticops.memory import AgentMemory, MemoryType
from agenticops.memory.agent_memory import _NullEmbeddingClient


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def memory(tmp_path):
    db = str(tmp_path / "test_learner.db")
    mem = AgentMemory("rca_agent", db_path=db)
    mem._memory_md_path = tmp_path / "rca_agent_MEMORY.md"
    mem._embedding_client = _NullEmbeddingClient()
    return mem


@pytest.fixture
def learner(memory):
    l = RCALearner()
    l.memory = memory
    return l


def _make_result(
    root_cause="EKS pod OOMKilled due to memory limit too low",
    confidence=0.85,
    iterations=2,
    contributing_factors=None,
    recommendations=None,
    evidence_chain=None,
    is_known_pattern=False,
):
    return DeepRCAResult(
        analysis=RCAAnalysis(
            root_cause=root_cause,
            confidence_score=confidence,
            contributing_factors=contributing_factors or ["memory limit 256Mi", "traffic spike"],
            recommendations=recommendations or ["Increase memory limit to 512Mi"],
        ),
        evidence_chain=evidence_chain or [],
        iterations=iterations,
        is_known_pattern=is_known_pattern,
    )


# ═══════════════════════════════════════════════════════════════
# RCALearner Tests
# ═══════════════════════════════════════════════════════════════


class TestExtractPatterns:
    """Test pattern extraction from RCA results."""

    def test_pattern_from_contributing_factors(self, learner):
        result = _make_result()
        patterns = learner._extract_patterns(result)
        factor_patterns = [p for p in patterns if p.startswith("PATTERN:")]
        assert len(factor_patterns) >= 1
        assert "memory limit 256Mi" in factor_patterns[0]

    def test_pattern_from_recommendations(self, learner):
        result = _make_result()
        patterns = learner._extract_patterns(result)
        fix_patterns = [p for p in patterns if p.startswith("FIX:")]
        assert len(fix_patterns) >= 1
        assert "512Mi" in fix_patterns[0]

    def test_pattern_from_high_value_evidence(self, learner):
        evidence = [
            EvidenceItem(
                source="cloudtrail",
                content="StopInstances API call by user admin",
                confidence_delta=0.3,
            ),
        ]
        result = _make_result(evidence_chain=evidence)
        patterns = learner._extract_patterns(result)
        ev_patterns = [p for p in patterns if p.startswith("EVIDENCE:")]
        assert len(ev_patterns) >= 1
        assert "StopInstances" in ev_patterns[0]

    def test_no_patterns_from_empty_result(self, learner):
        result = DeepRCAResult(
            analysis=RCAAnalysis(
                root_cause="unknown",
                confidence_score=0.3,
                contributing_factors=[],
                recommendations=[],
            ),
            evidence_chain=[],
        )
        patterns = learner._extract_patterns(result)
        assert patterns == []

    def test_low_value_evidence_excluded(self, learner):
        evidence = [
            EvidenceItem(source="cloudwatch", content="CPU at 50%", confidence_delta=0.05),
        ]
        result = _make_result(evidence_chain=evidence)
        patterns = learner._extract_patterns(result)
        ev_patterns = [p for p in patterns if p.startswith("EVIDENCE:")]
        assert len(ev_patterns) == 0  # delta 0.05 < 0.1 threshold


class TestCategorizeRootCause:
    """Test root cause categorization."""

    def test_oom_category(self, learner):
        assert learner._categorize_root_cause("Pod OOM killed") == "oom"

    def test_cpu_category(self, learner):
        assert learner._categorize_root_cause("CPU throttle on i-123") == "cpu"

    def test_network_category(self, learner):
        assert learner._categorize_root_cause("Connection timeout to RDS") == "network"

    def test_storage_category(self, learner):
        assert learner._categorize_root_cause("EBS volume IOPS exhausted") == "storage"

    def test_permission_category(self, learner):
        assert learner._categorize_root_cause("IAM access denied for s3:PutObject") == "permission"

    def test_config_category(self, learner):
        assert learner._categorize_root_cause("Misconfigured security group") == "config"

    def test_scaling_category(self, learner):
        assert learner._categorize_root_cause("Autoscaling group at capacity limit") == "scaling"

    def test_dependency_category(self, learner):
        assert learner._categorize_root_cause("Downstream service cascade failure") == "dependency"

    def test_unknown_defaults_to_general(self, learner):
        assert learner._categorize_root_cause("Something weird happened") == "general"


class TestShouldCreateSkill:
    """Test skill creation threshold logic."""

    def test_high_confidence_novel_multi_iteration(self, learner):
        result = _make_result(confidence=0.9, iterations=2, is_known_pattern=False)
        assert learner._should_create_skill(result) is True

    def test_low_confidence_rejects(self, learner):
        result = _make_result(confidence=0.5, iterations=2)
        assert learner._should_create_skill(result) is False

    def test_known_pattern_rejects(self, learner):
        result = _make_result(confidence=0.9, iterations=2, is_known_pattern=True)
        assert learner._should_create_skill(result) is False

    def test_single_iteration_rejects(self, learner):
        result = _make_result(confidence=0.9, iterations=1)
        assert learner._should_create_skill(result) is False


class TestRCALearnerLearn:
    """Test the full learn() pipeline."""

    def test_learn_stores_patterns(self, learner, memory):
        result = _make_result()
        summary = run(learner.learn(result))
        assert summary["patterns_stored"] >= 1

    def test_learn_high_confidence_triggers_skill_update(self, learner):
        result = _make_result(confidence=0.85)
        # SkillGapDetector won't be available, so skill_action = "none" (ImportError)
        summary = run(learner.learn(result))
        # Patterns still stored even if skill update fails
        assert summary["patterns_stored"] >= 1

    def test_learn_low_confidence_skips_skill_update(self, learner):
        result = _make_result(confidence=0.3)
        summary = run(learner.learn(result))
        assert summary["skill_action"] == "none"

    def test_learn_no_reflection_below_threshold(self, learner):
        result = _make_result()
        summary = run(learner.learn(result))
        assert summary["reflected"] is False

    @patch.object(RCALearner, "_incident_count_today", new_callable=AsyncMock)
    def test_learn_reflects_above_threshold(self, mock_count, learner):
        mock_count.return_value = 6  # Above REFLECT_THRESHOLD=5
        result = _make_result()
        summary = run(learner.learn(result))
        assert summary["reflected"] is True

    @patch.object(RCALearner, "_update_skills", new_callable=AsyncMock)
    def test_learn_skill_revised(self, mock_skills, learner):
        mock_skills.return_value = "revised"
        result = _make_result(confidence=0.85)
        summary = run(learner.learn(result))
        assert summary["skill_action"] == "revised"


# ═══════════════════════════════════════════════════════════════
# Evidence Module Tests
# ═══════════════════════════════════════════════════════════════


class TestEvidenceItem:
    """Test EvidenceItem data model."""

    def test_create_basic(self):
        ev = EvidenceItem(
            source="cloudtrail",
            content="StopInstances by admin",
            confidence_delta=0.3,
        )
        assert ev.source == "cloudtrail"
        assert ev.confidence_delta == 0.3

    def test_summary_format(self):
        ev = EvidenceItem(
            source="cloudwatch",
            content="CPU at 95% for 30 minutes",
            confidence_delta=0.2,
        )
        s = ev.summary()
        assert "[cloudwatch]" in s
        assert "+0.20" in s

    def test_summary_negative_delta(self):
        ev = EvidenceItem(
            source="network",
            content="No anomaly found",
            confidence_delta=-0.1,
        )
        s = ev.summary()
        assert "-0.10" in s

    def test_raw_data_defaults_empty(self):
        ev = EvidenceItem(source="trace", content="ok", confidence_delta=0.0)
        assert ev.raw_data == {}

    def test_summary_truncation(self):
        ev = EvidenceItem(
            source="logs",
            content="A" * 500,
            confidence_delta=0.1,
        )
        s = ev.summary(max_len=50)
        assert len(s) < 200  # Much shorter than full content


class TestGatherEvidence:
    """Test evidence dispatcher."""

    def test_unknown_type_returns_none(self):
        result = run(gather_evidence({"type": "unknown_source"}))
        assert result is None

    def test_missing_type_returns_none(self):
        result = run(gather_evidence({}))
        assert result is None

    @patch("agenticops.analyze.evidence._gather_cloudtrail", new_callable=AsyncMock)
    def test_cloudtrail_dispatch(self, mock_gather):
        mock_gather.return_value = EvidenceItem(
            source="cloudtrail", content="events found", confidence_delta=0.3
        )
        result = run(gather_evidence(
            {"type": "cloudtrail", "params": {"lookback_hours": 48}},
            resource_id="i-123",
        ))
        assert result is not None
        assert result.source == "cloudtrail"
        mock_gather.assert_called_once()

    @patch("agenticops.analyze.evidence._gather_cloudwatch", new_callable=AsyncMock)
    def test_cloudwatch_dispatch(self, mock_gather):
        mock_gather.return_value = EvidenceItem(
            source="cloudwatch", content="metrics", confidence_delta=0.2
        )
        result = run(gather_evidence({"type": "cloudwatch"}, resource_id="i-456"))
        assert result.source == "cloudwatch"

    @patch("agenticops.analyze.evidence._gather_network", new_callable=AsyncMock)
    def test_network_dispatch(self, mock_gather):
        mock_gather.return_value = EvidenceItem(
            source="network", content="sg rules", confidence_delta=0.15
        )
        result = run(gather_evidence({"type": "network"}))
        assert result.source == "network"

    @patch("agenticops.analyze.evidence._gather_trace", new_callable=AsyncMock)
    def test_trace_dispatch(self, mock_gather):
        mock_gather.return_value = EvidenceItem(
            source="trace", content="spans", confidence_delta=0.25
        )
        result = run(gather_evidence({"type": "trace"}))
        assert result.source == "trace"

    @patch("agenticops.analyze.evidence._gather_logs", new_callable=AsyncMock)
    def test_logs_dispatch(self, mock_gather):
        mock_gather.return_value = EvidenceItem(
            source="logs", content="error entries", confidence_delta=0.1
        )
        result = run(gather_evidence({"type": "logs"}))
        assert result.source == "logs"

    @patch("agenticops.analyze.evidence._gather_cloudtrail", new_callable=AsyncMock)
    def test_gatherer_exception_returns_fallback(self, mock_gather):
        mock_gather.side_effect = RuntimeError("AWS error")
        result = run(gather_evidence({"type": "cloudtrail"}, resource_id="i-err"))
        assert result is not None
        assert "Gathering failed" in result.content
        assert result.confidence_delta == 0.0
