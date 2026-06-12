"""Tests for AnalyzeGraphRisksStep (P1) — SPOF/capacity findings become
HealthIssues with auto_rca=False, and the step degrades gracefully."""

import asyncio
from unittest.mock import MagicMock, patch

from agenticops.pipeline.health_patrol import AnalyzeGraphRisksStep


def _run(step, context):
    return asyncio.run(step.execute(context))


def _graph_with_nodes(n: int):
    inner = MagicMock()
    inner.number_of_nodes.return_value = n
    graph = MagicMock()
    graph.graph = inner
    return graph


class TestAnalyzeGraphRisksStep:
    def test_disabled_by_config(self):
        result = _run(AnalyzeGraphRisksStep(), {"config": {"graph_checks": False}})
        assert result["skipped"] is True

    def test_empty_graph_skips(self):
        store = MagicMock()
        store.load_graph.return_value = _graph_with_nodes(0)
        with patch("agenticops.graph.store.GraphStore", return_value=store):
            result = _run(AnalyzeGraphRisksStep(), {"config": {"graph_checks": True}})
        assert result["skipped"] is True
        assert "empty" in result["note"]

    def test_graph_load_failure_skips(self):
        with patch("agenticops.graph.store.GraphStore", side_effect=RuntimeError("no db")):
            result = _run(AnalyzeGraphRisksStep(), {"config": {"graph_checks": True}})
        assert result["skipped"] is True

    def test_findings_create_issues_without_rca(self):
        spof_item = MagicMock()
        spof_item.node_id = "nat-123"
        spof_item.label = "NAT Gateway"
        spof_item.impact_description = "Removal disconnects 2 components"
        spof_item.affected_components = 2

        spof_report = MagicMock()
        spof_report.total_spofs = 1
        spof_report.articulation_points = [spof_item]

        cap_item = MagicMock()
        cap_item.node_id = "subnet-9"
        cap_item.label = "private-a"
        cap_item.metric = "available_ips"
        cap_item.current = 240.0
        cap_item.maximum = 251.0
        cap_item.utilization_pct = 95.6
        cap_item.risk_level = "critical"

        cap_report = MagicMock()
        cap_report.total_risks = 1
        cap_report.items = [cap_item]

        store = MagicMock()
        store.load_graph.return_value = _graph_with_nodes(10)

        created = []

        def fake_create(**kwargs):
            created.append(kwargs)
            return f"Created HealthIssue #1: {kwargs['title']}"

        with patch("agenticops.graph.store.GraphStore", return_value=store), \
             patch("agenticops.graph.algorithms.detect_spof", return_value=spof_report), \
             patch("agenticops.graph.algorithms.capacity_risk_analysis", return_value=cap_report), \
             patch("agenticops.tools.metadata_tools._create_health_issue_impl", side_effect=fake_create):
            result = _run(AnalyzeGraphRisksStep(), {"config": {"graph_checks": True}})

        assert result["spofs"] == 1
        assert result["capacity_risks"] == 1
        assert len(created) == 2

        # Structural risks must NOT trigger forensic auto-RCA
        assert all(c["auto_rca"] is False for c in created)
        assert all(c["source"] == "graph_patrol" for c in created)

        spof_issue = created[0]
        assert spof_issue["resource_id"] == "nat-123"
        assert spof_issue["severity"] == "medium"
        assert "SPOF" in spof_issue["title"]

        cap_issue = created[1]
        assert cap_issue["resource_id"] == "subnet-9"
        assert cap_issue["severity"] == "high"  # critical risk_level → high
        assert "Capacity risk" in cap_issue["title"]

    def test_step_registered_in_patrol(self):
        from agenticops.pipeline.health_patrol import HealthPatrolPipeline

        pipeline = HealthPatrolPipeline()
        step_names = [s.name for s in pipeline.steps]
        assert "analyze_graph_risks" in step_names
        # Must run after detect (depends_on)
        graph_step = next(s for s in pipeline.steps if s.name == "analyze_graph_risks")
        assert "run_detect" in graph_step.depends_on


class TestCreateHealthIssueImplWrapper:
    def test_tool_wrapper_delegates_with_auto_rca_true(self):
        # The @tool create_health_issue must keep today's behavior (auto_rca=True)
        with patch("agenticops.tools.metadata_tools._create_health_issue_impl",
                   return_value="ok") as impl:
            from agenticops.tools.metadata_tools import create_health_issue
            fn = getattr(create_health_issue, "original_function", create_health_issue)
            fn(
                resource_id="i-1", severity="low", source="manual",
                title="t", description="d",
            )
        assert impl.call_args.kwargs["auto_rca"] is True
