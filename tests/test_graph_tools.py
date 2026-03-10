"""Tests for agenticops.graph.tools — Strands @tool wrappers for graph algorithms.

All 9 tools follow the same pattern:
  build graph → call algorithm → return JSON (or {"error": ...})

Strategy: mock the graph builders and algorithm functions, verify:
1. Happy path returns valid JSON
2. Error path returns {"error": "..."} format
3. Correct builder/algorithm is called
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agenticops.graph.engine import InfraGraph


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_model(data: dict):
    """Build a mock Pydantic model with model_dump() and model_dump_json()."""
    m = MagicMock()
    m.model_dump.return_value = data
    m.model_dump_json.return_value = json.dumps(data, indent=2)
    return m


def _dummy_graph():
    return InfraGraph()


# ── VPC-scoped tools ────────────────────────────────────────────────


class TestQueryReachability:

    @patch("agenticops.graph.tools._build_vpc_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.can_reach_internet")
    def test_happy_path(self, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"can_reach": True, "path": ["sub-1", "igw-1"]})
        from agenticops.graph.tools import query_reachability
        result = json.loads(query_reachability(region="r", vpc_id="v", subnet_id="s"))
        assert result["can_reach"] is True
        mock_build.assert_called_once_with("r", "v")

    @patch("agenticops.graph.tools._build_vpc_graph", side_effect=Exception("VPC not found"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import query_reachability
        result = json.loads(query_reachability(region="r", vpc_id="v", subnet_id="s"))
        assert "error" in result
        assert "VPC not found" in result["error"]


class TestQueryImpactRadius:

    @patch("agenticops.graph.tools._build_vpc_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.impact_analysis")
    def test_happy_path(self, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"affected": 3, "severity": "high"})
        from agenticops.graph.tools import query_impact_radius
        result = json.loads(query_impact_radius(region="r", vpc_id="v", resource_id="nat-1"))
        assert result["severity"] == "high"

    @patch("agenticops.graph.tools._build_vpc_graph", side_effect=Exception("err"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import query_impact_radius
        result = json.loads(query_impact_radius(region="r", vpc_id="v", resource_id="x"))
        assert "error" in result


class TestFindNetworkPath:

    @patch("agenticops.graph.tools._build_vpc_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.find_traffic_path")
    def test_happy_path(self, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"paths": [["s", "t"]]})
        from agenticops.graph.tools import find_network_path
        result = json.loads(find_network_path(region="r", vpc_id="v", source="s", target="t"))
        assert len(result["paths"]) == 1

    @patch("agenticops.graph.tools._build_vpc_graph", side_effect=Exception("err"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import find_network_path
        result = json.loads(find_network_path(region="r", vpc_id="v", source="s", target="t"))
        assert "error" in result


class TestDetectNetworkAnomalies:

    @patch("agenticops.graph.tools._build_vpc_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.detect_anomalies")
    def test_happy_path(self, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"total_anomalies": 0, "anomalies": []})
        from agenticops.graph.tools import detect_network_anomalies
        result = json.loads(detect_network_anomalies(region="r", vpc_id="v"))
        assert result["total_anomalies"] == 0

    @patch("agenticops.graph.tools._build_vpc_graph", side_effect=Exception("err"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import detect_network_anomalies
        result = json.loads(detect_network_anomalies(region="r", vpc_id="v"))
        assert "error" in result


# ── Region-scoped tools ─────────────────────────────────────────────


class TestAnalyzeNetworkSegments:

    @patch("agenticops.graph.tools._build_region_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.network_segments")
    @patch("agenticops.graph.tools.to_agent_summary", return_value="3 VPCs")
    def test_happy_path(self, mock_summary, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"total_segments": 2, "segments": []})
        from agenticops.graph.tools import analyze_network_segments
        result = json.loads(analyze_network_segments(region="us-east-1"))
        assert result["total_segments"] == 2
        assert result["graph_summary"] == "3 VPCs"

    @patch("agenticops.graph.tools._build_region_graph", side_effect=Exception("err"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import analyze_network_segments
        result = json.loads(analyze_network_segments(region="r"))
        assert "error" in result


# ── Multi-region tool ───────────────────────────────────────────────


class TestAnalyzeCrossRegionTopology:

    @patch("agenticops.graph.tools._build_multi_region_graph")
    @patch("agenticops.graph.tools.detect_anomalies")
    @patch("agenticops.graph.tools.network_segments")
    @patch("agenticops.graph.tools.to_agent_summary", return_value="summary")
    def test_with_nodes_and_cross_region_edges(self, mock_summary, mock_segments, mock_anomalies, mock_build):
        """Test the per-node region summary and cross-region edge detection."""
        from agenticops.graph.types import NodeAttrs, NodeType, NodeStatus, EdgeAttrs, EdgeType
        g = InfraGraph()
        g._add_node("vpc-us", NodeAttrs(
            node_type=NodeType.VPC, label="us-vpc", status=NodeStatus.HEALTHY,
            resource_type="vpc", raw={"region": "us-east-1"},
        ))
        g._add_node("vpc-eu", NodeAttrs(
            node_type=NodeType.VPC, label="eu-vpc", status=NodeStatus.HEALTHY,
            resource_type="vpc", raw={"region": "eu-west-1"},
        ))
        g._add_node("tgw-1", NodeAttrs(
            node_type=NodeType.TRANSIT_GATEWAY, label="tgw", status=NodeStatus.HEALTHY,
            resource_type="tgw", raw={"region": "us-east-1"},
        ))
        g._add_edge("vpc-us", "tgw-1", EdgeAttrs(edge_type=EdgeType.ATTACHED_TO, label="", state=""))
        g._add_edge("tgw-1", "vpc-eu", EdgeAttrs(edge_type=EdgeType.ATTACHED_TO, label="", state=""))
        mock_build.return_value = g
        mock_anomalies.return_value = _mock_model({"total": 0})
        mock_segments.return_value = _mock_model({"segments": []})
        from agenticops.graph.tools import analyze_cross_region_topology
        result = json.loads(analyze_cross_region_topology(regions="us-east-1,eu-west-1"))
        # Should have 2 region summaries
        summaries = result["region_summaries"]
        regions_found = {s["region"] for s in summaries}
        assert "us-east-1" in regions_found
        assert "eu-west-1" in regions_found
        # Should detect cross-region connection tgw-1 → vpc-eu
        assert len(result["cross_region_connections"]) >= 1
        cross = result["cross_region_connections"][0]
        assert cross["source_region"] != cross["target_region"]

    @patch("agenticops.graph.tools._build_multi_region_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.detect_anomalies")
    @patch("agenticops.graph.tools.network_segments")
    @patch("agenticops.graph.tools.to_agent_summary", return_value="summary")
    def test_happy_path(self, mock_summary, mock_segments, mock_anomalies, mock_build):
        mock_anomalies.return_value = _mock_model({"total": 0})
        mock_segments.return_value = _mock_model({"segments": []})
        from agenticops.graph.tools import analyze_cross_region_topology
        result = json.loads(analyze_cross_region_topology(regions="us-east-1,eu-west-1"))
        assert "region_summaries" in result
        assert "graph_summary" in result

    @patch("agenticops.graph.tools._build_multi_region_graph", side_effect=RuntimeError("bad"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import analyze_cross_region_topology
        result = json.loads(analyze_cross_region_topology(regions=""))
        assert "error" in result


# ── Enriched VPC tools ──────────────────────────────────────────────


class TestAnalyzeDependencyChain:

    @patch("agenticops.graph.tools._build_enriched_vpc_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.dependency_chain_analysis")
    def test_happy_path(self, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"total_affected": 3})
        from agenticops.graph.tools import analyze_dependency_chain
        result = json.loads(analyze_dependency_chain(region="r", vpc_id="v", fault_node_id="rds-1"))
        assert result["total_affected"] == 3

    @patch("agenticops.graph.tools._build_enriched_vpc_graph", side_effect=Exception("err"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import analyze_dependency_chain
        result = json.loads(analyze_dependency_chain(region="r", vpc_id="v", fault_node_id="x"))
        assert "error" in result


class TestDetectSpof:

    @patch("agenticops.graph.tools._build_enriched_vpc_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.detect_spof")
    def test_happy_path(self, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"total_spofs": 1})
        from agenticops.graph.tools import detect_single_points_of_failure
        result = json.loads(detect_single_points_of_failure(region="r", vpc_id="v"))
        assert result["total_spofs"] == 1

    @patch("agenticops.graph.tools._build_enriched_vpc_graph", side_effect=Exception("err"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import detect_single_points_of_failure
        result = json.loads(detect_single_points_of_failure(region="r", vpc_id="v"))
        assert "error" in result


class TestCapacityRisk:

    @patch("agenticops.graph.tools._build_enriched_vpc_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.capacity_risk_analysis")
    def test_happy_path(self, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"total_risks": 0})
        from agenticops.graph.tools import analyze_capacity_risk
        result = json.loads(analyze_capacity_risk(region="r", vpc_id="v"))
        assert result["total_risks"] == 0

    @patch("agenticops.graph.tools._build_enriched_vpc_graph", side_effect=Exception("err"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import analyze_capacity_risk
        result = json.loads(analyze_capacity_risk(region="r", vpc_id="v"))
        assert "error" in result


class TestSimulateEdgeRemoval:

    @patch("agenticops.graph.tools._build_enriched_vpc_graph", return_value=_dummy_graph())
    @patch("agenticops.graph.tools.simulate_change")
    def test_happy_path(self, mock_algo, mock_build):
        mock_algo.return_value = _mock_model({"edge_existed": True, "total_connections_lost": 2})
        from agenticops.graph.tools import simulate_edge_removal
        result = json.loads(simulate_edge_removal(region="r", vpc_id="v", edge_source="a", edge_target="b"))
        assert result["edge_existed"] is True

    @patch("agenticops.graph.tools._build_enriched_vpc_graph", side_effect=Exception("err"))
    def test_error_format(self, mock_build):
        from agenticops.graph.tools import simulate_edge_removal
        result = json.loads(simulate_edge_removal(region="r", vpc_id="v", edge_source="a", edge_target="b"))
        assert "error" in result
