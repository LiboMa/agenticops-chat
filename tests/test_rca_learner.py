"""Tests for RCA Learner — post-RCA learning pipeline."""

import asyncio
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agenticops.analyze.deep_rca import DeepRCAResult
from agenticops.analyze.evidence import EvidenceItem
from agenticops.analyze.rca import RCAAnalysis
from agenticops.analyze.rca_learner import RCALearner
from agenticops.memory import AgentMemory, MemoryType
from agenticops.memory.agent_memory import _NullEmbeddingClient


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_learner.db")


@pytest.fixture
def memory(tmp_db, tmp_path):
    mem = AgentMemory("rca_agent", db_path=tmp_db)
    mem._memory_md_path = tmp_path / "rca_MEMORY.md"
    mem._embedding_client = _NullEmbeddingClient()
    return mem


@pytest.fixture
def learner(memory):
    l = RCALearner()
    l.memory = memory
    return l


@pytest.fixture
def good_result():
    """A high-confidence RCA result."""
    return DeepRCAResult(
        analysis=RCAAnalysis(
            root_cause="Memory leak in checkout-service caused OOM kills",
            confidence_score=0.85,
            contributing_factors=["No memory limits set", "Memory leak in v2.3"],
            recommendations=["Set memory limits to 512Mi", "Fix leak in v2.4"],
            related_resources=["pod/checkout", "node/worker-1"],
        ),
        evidence_chain=[
            EvidenceItem(
                source="cloudwatch",
                content="Memory usage 95% before OOM",
                confidence_delta=0.2,
            ),
            EvidenceItem(
                source="cloudtrail",
                content="Deployment v2.3 at 14:00",
                confidence_delta=0.15,
            ),
        ],
        iterations=2,
        is_known_pattern=False,
    )


@pytest.fixture
def low_result():
    """A low-confidence RCA result."""
    return DeepRCAResult(
        analysis=RCAAnalysis(
            root_cause="Unclear cause",
            confidence_score=0.3,
            contributing_factors=[],
            recommendations=[],
        ),
        iterations=1,
        is_known_pattern=False,
    )


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRCALearner:
    """Test post-RCA learning pipeline."""

    def test_learn_stores_patterns(self, learner, good_result):
        """learn() extracts and stores patterns as PROCEDURAL memory."""
        summary = run(learner.learn(good_result))
        assert summary["patterns_stored"] >= 2  # factor pattern + fix pattern

        memories = run(learner.memory.recall(
            "memory limit OOM",
            memory_type=MemoryType.PROCEDURAL,
        ))
        assert len(memories) >= 1

    def test_learn_low_confidence_no_skill(self, learner, low_result):
        """Low confidence results don't trigger skill updates."""
        summary = run(learner.learn(low_result))
        assert summary["skill_action"] == "none"
        assert summary["patterns_stored"] == 0  # No factors/recommendations

    def test_extract_patterns_from_factors(self, learner, good_result):
        """Contributing factors → PATTERN extraction."""
        patterns = learner._extract_patterns(good_result)
        pattern_text = " ".join(patterns)
        assert "PATTERN" in pattern_text
        assert "memory limits" in pattern_text.lower() or "memory leak" in pattern_text.lower()

    def test_extract_patterns_from_recommendations(self, learner, good_result):
        """Recommendations → FIX pattern extraction."""
        patterns = learner._extract_patterns(good_result)
        fix_patterns = [p for p in patterns if p.startswith("FIX:")]
        assert len(fix_patterns) >= 1

    def test_extract_patterns_from_evidence(self, learner, good_result):
        """High-value evidence → EVIDENCE pattern extraction."""
        patterns = learner._extract_patterns(good_result)
        evidence_patterns = [p for p in patterns if p.startswith("EVIDENCE:")]
        assert len(evidence_patterns) >= 1
        assert "cloudwatch" in evidence_patterns[0].lower() or "cloudtrail" in evidence_patterns[0].lower()

    def test_categorize_root_cause(self, learner):
        """Root cause categorization works."""
        assert learner._categorize_root_cause("Out of memory OOM kill") == "oom"
        assert learner._categorize_root_cause("High CPU throttling") == "cpu"
        assert learner._categorize_root_cause("Connection timeout to DB") == "network"
        assert learner._categorize_root_cause("EBS volume full") == "storage"
        assert learner._categorize_root_cause("IAM permission denied") == "permission"
        assert learner._categorize_root_cause("Something weird") == "general"

    def test_should_create_skill(self, learner, good_result):
        """Skill creation requires high confidence + not known + multiple iterations."""
        assert learner._should_create_skill(good_result) is True

        # Known pattern → no new skill
        good_result.is_known_pattern = True
        assert learner._should_create_skill(good_result) is False

        # Low confidence → no new skill
        good_result.is_known_pattern = False
        good_result.analysis.confidence_score = 0.5
        assert learner._should_create_skill(good_result) is False

    def test_reflection_triggered(self, learner, good_result, memory):
        """Reflection triggers after REFLECT_THRESHOLD incidents."""
        # Seed multiple incidents
        for i in range(6):
            run(memory.remember(
                f"RCA incident {i}",
                source=f"deep_rca:resource-{i}",
            ))

        learner.REFLECT_THRESHOLD = 3
        summary = run(learner.learn(good_result))
        assert summary["reflected"] is True

    def test_reflection_not_triggered_few_incidents(self, learner, good_result):
        """Reflection not triggered with few incidents."""
        learner.REFLECT_THRESHOLD = 100
        summary = run(learner.learn(good_result))
        assert summary["reflected"] is False

    def test_skill_revision_path(self, learner, good_result):
        """When existing skill found, revision path taken."""
        mock_detector = MagicMock()
        mock_detector.find_skill_for_category.return_value = "memory_diagnosis"
        mock_module = MagicMock()
        mock_module.SkillGapDetector.return_value = mock_detector

        import sys
        original = sys.modules.get("agenticops.skills.evolution")
        sys.modules["agenticops.skills.evolution"] = mock_module
        try:
            summary = run(learner.learn(good_result))
        finally:
            if original:
                sys.modules["agenticops.skills.evolution"] = original
            else:
                sys.modules.pop("agenticops.skills.evolution", None)

        assert summary["skill_action"] == "revised"

        memories = run(learner.memory.recall(
            "SKILL_REVISION",
            memory_type=MemoryType.SEMANTIC,
        ))
        assert len(memories) >= 1

    def test_skill_gap_detection(self, learner, good_result):
        """When no existing skill, gap detection triggers."""
        mock_detector = MagicMock()
        mock_detector.find_skill_for_category.return_value = None
        mock_module = MagicMock()
        mock_module.SkillGapDetector.return_value = mock_detector

        import sys
        original = sys.modules.get("agenticops.skills.evolution")
        sys.modules["agenticops.skills.evolution"] = mock_module
        try:
            summary = run(learner.learn(good_result))
        finally:
            if original:
                sys.modules["agenticops.skills.evolution"] = original
            else:
                sys.modules.pop("agenticops.skills.evolution", None)

        assert summary["skill_action"] == "created"

        memories = run(learner.memory.recall(
            "SKILL_GAP",
            memory_type=MemoryType.SEMANTIC,
        ))
        assert len(memories) >= 1

    def test_incident_count_today(self, learner, memory):
        """_incident_count_today counts only today's deep_rca memories."""
        run(memory.remember("old incident", source="deep_rca:old"))
        run(memory.remember("today incident", source="deep_rca:new"))
        run(memory.remember("not rca", source="other:thing"))

        count = run(learner._incident_count_today())
        assert count >= 2  # Both deep_rca entries
