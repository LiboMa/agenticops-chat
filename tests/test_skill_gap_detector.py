"""Tests for SkillGapDetector — Phase 2 P2 port from agentic-aiops-mvp."""

import pytest
from agenticops.skills.iteration.gap_detector import (
    SkillGap,
    SkillGapDetector,
    _infer_domain,
    _ALL_KNOWN_COMMANDS,
)


class TestSkillGap:
    def test_creation(self):
        gap = SkillGap(gap_type="novel_tool_usage", incident_id="INC-001")
        assert gap.gap_type == "novel_tool_usage"
        assert gap.incident_id == "INC-001"

    def test_commands_hash_deterministic(self):
        g1 = SkillGap(gap_type="novel_tool_usage", uncovered_commands=["foo", "bar"])
        g2 = SkillGap(gap_type="novel_tool_usage", uncovered_commands=["bar", "foo"])
        assert g1.commands_hash == g2.commands_hash  # sorted

    def test_to_dict(self):
        gap = SkillGap(
            gap_type="repeated_manual",
            incident_id="INC-002",
            repeat_count=5,
            suggested_action="create_runbook_skill",
        )
        d = gap.to_dict()
        assert d["gap_type"] == "repeated_manual"
        assert d["repeat_count"] == 5


class TestInferDomain:
    def test_kubernetes_commands(self):
        assert _infer_domain(["kubectl", "helm"]) == "kubernetes"

    def test_linux_commands(self):
        assert _infer_domain(["top", "ps", "df"]) == "linux_admin"

    def test_network_commands(self):
        assert _infer_domain(["ping", "traceroute"]) == "network_engineer"

    def test_unknown_commands(self):
        assert _infer_domain(["customtool123"]) == "general"

    def test_empty(self):
        assert _infer_domain([]) == "general"


class TestSkillGapDetector:
    @pytest.fixture
    def detector(self):
        return SkillGapDetector()

    def test_novel_tool_usage(self, detector):
        gap = detector.analyze_incident(
            incident="INC-001",
            rca_result={},
            resolution_log=["customscript --fix", "kubectl get pods"],
        )
        assert gap is not None
        assert gap.gap_type == "novel_tool_usage"
        assert "customscript" in gap.uncovered_commands

    def test_no_gap_when_all_known(self, detector):
        gap = detector.analyze_incident(
            incident="INC-002",
            rca_result={"detection_source": "cloudwatch", "confidence": 0.9},
            resolution_log=["kubectl get pods", "grep error"],
        )
        assert gap is None

    def test_repeated_manual(self, detector):
        gap = detector.analyze_incident(
            incident="INC-003",
            rca_result={
                "similar_incident_count": 5,
                "affected_service": "payment-service",
                "detection_source": "cloudwatch",
                "confidence": 0.9,
            },
            resolution_log=[],
        )
        assert gap is not None
        assert gap.gap_type == "repeated_manual"
        assert gap.repeat_count == 5

    def test_repeated_below_threshold(self, detector):
        gap = detector.analyze_incident(
            incident="INC-004",
            rca_result={
                "similar_incident_count": 2,
                "detection_source": "cloudwatch",
                "confidence": 0.9,
            },
            resolution_log=[],
        )
        assert gap is None

    def test_detection_miss(self, detector):
        gap = detector.analyze_incident(
            incident="INC-005",
            rca_result={
                "detection_source": "manual",
                "alert_type": "oom",
                "affected_service": "api-server",
                "confidence": 0.9,
            },
            resolution_log=[],
        )
        assert gap is not None
        assert gap.gap_type == "detection_miss"

    def test_detection_miss_empty_source(self, detector):
        gap = detector.analyze_incident(
            incident="INC-006",
            rca_result={"detection_source": "", "confidence": 0.9},
            resolution_log=[],
        )
        assert gap is not None
        assert gap.gap_type == "detection_miss"

    def test_low_confidence(self, detector):
        gap = detector.analyze_incident(
            incident="INC-007",
            rca_result={
                "detection_source": "cloudwatch",
                "confidence": 0.1,
            },
            resolution_log=[],
        )
        assert gap is not None
        assert gap.gap_type == "low_confidence"

    def test_priority_novel_over_repeated(self, detector):
        """Novel tool usage is checked before repeated manual."""
        gap = detector.analyze_incident(
            incident="INC-008",
            rca_result={"similar_incident_count": 10, "detection_source": "cloudwatch", "confidence": 0.9},
            resolution_log=["specialtool --run"],
        )
        assert gap.gap_type == "novel_tool_usage"  # Higher priority

    def test_known_commands_populated(self):
        assert "kubectl" in _ALL_KNOWN_COMMANDS
        assert "grep" in _ALL_KNOWN_COMMANDS
        assert "ping" in _ALL_KNOWN_COMMANDS
