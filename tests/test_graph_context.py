"""Tests for agenticops.graph.context — alert context dossier builder.

Covers:
- get_alert_context() happy path with full topology
- Exact ID match vs fuzzy match node selection
- Resource not found → None
- Empty search results → None
- Blast radius BFS traversal (in_edges + out_edges, bidirectional)
- Upstream/downstream dependency extraction
- Topology summary string construction
- Edge cases: isolated node, deep chain, diamond topology
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from agenticops.graph.engine import InfraGraph
from agenticops.graph.types import EdgeAttrs, EdgeType, NodeAttrs, NodeStatus, NodeType


# ── Helpers ──────────────────────────────────────────────────────────


def _make_graph(*nodes_and_edges) -> InfraGraph:
    """Build a small InfraGraph from tuples.

    Args:
        nodes_and_edges: mix of node tuples (id, node_type, label, status, extras)
                         and edge tuples (src, tgt, edge_type).
    """
    g = InfraGraph()
    for item in nodes_and_edges:
        if len(item) >= 4 and isinstance(item[1], NodeType):
            nid, ntype, label, status = item[0], item[1], item[2], item[3]
            extras = item[4] if len(item) > 4 else {}
            g._add_node(
                nid,
                NodeAttrs(
                    node_type=ntype,
                    label=label,
                    status=status,
                    resource_type=extras.get("resource_type", ntype.value),
                    raw=extras.get("raw", {}),
                ),
            )
        elif len(item) == 3:
            src, tgt, etype = item
            g._add_edge(src, tgt, EdgeAttrs(edge_type=etype, label="", state=""))
    return g


def _search_result(node_id, node_type="ec2", label="", status="healthy",
                    resource_type="", vpc_id="", region="us-east-1"):
    """Build a search_nodes()-style dict."""
    return {
        "id": node_id,
        "node_type": node_type,
        "label": label or node_id,
        "status": status,
        "resource_type": resource_type or node_type,
        "vpc_id": vpc_id,
        "region": region,
        "account_id": "123456789012",
        "updated_at": "2026-03-10 06:00:00",
    }


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_store():
    """Patch GraphStore used in context.py."""
    with patch("agenticops.graph.context.GraphStore") as cls:
        store = MagicMock()
        cls.return_value = store
        yield store


# ── Tests: resource not found ────────────────────────────────────────


class TestResourceNotFound:
    """get_alert_context returns None when resource cannot be located."""

    def test_no_search_results(self, mock_store):
        mock_store.search_nodes.return_value = []

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("i-nonexistent")

        assert result is None
        mock_store.search_nodes.assert_called_once_with(query="i-nonexistent", limit=5)


# ── Tests: node selection (exact vs fuzzy) ───────────────────────────


class TestNodeSelection:
    """Prefer exact ID match over fuzzy first-result."""

    def test_exact_id_match_preferred(self, mock_store):
        mock_store.search_nodes.return_value = [
            _search_result("i-fuzzy", label="i-abc123-backup"),
            _search_result("i-abc123", label="prod-web-1"),
        ]
        # Neighborhood returns a graph with just the target node
        g = _make_graph(
            ("i-abc123", NodeType.EC2_INSTANCE, "prod-web-1", NodeStatus.HEALTHY),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("i-abc123")

        assert result is not None
        assert result["resource"]["id"] == "i-abc123"
        mock_store.get_node_neighborhood.assert_called_once_with("i-abc123", depth=2)

    def test_falls_back_to_first_result(self, mock_store):
        mock_store.search_nodes.return_value = [
            _search_result("i-partial", label="web-server"),
        ]
        g = _make_graph(
            ("i-partial", NodeType.EC2_INSTANCE, "web-server", NodeStatus.HEALTHY),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("web-server")

        assert result is not None
        assert result["resource"]["id"] == "i-partial"


# ── Tests: neighbors ────────────────────────────────────────────────


class TestNeighbors:
    """Verify direct neighbor extraction from the neighborhood graph."""

    def test_neighbors_with_edges(self, mock_store):
        mock_store.search_nodes.return_value = [
            _search_result("i-main", node_type="ec2", label="main"),
        ]
        g = _make_graph(
            ("i-main", NodeType.EC2_INSTANCE, "main", NodeStatus.HEALTHY),
            ("subnet-1", NodeType.SUBNET, "subnet-a", NodeStatus.HEALTHY),
            ("sg-1", NodeType.SECURITY_GROUP, "web-sg", NodeStatus.HEALTHY),
            ("i-main", "subnet-1", EdgeType.HOSTED_IN),
            ("sg-1", "i-main", EdgeType.REFERENCES),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("i-main")

        neighbors = result["neighbors"]
        neighbor_ids = {n["id"] for n in neighbors}
        assert "subnet-1" in neighbor_ids
        assert "sg-1" in neighbor_ids
        assert len(neighbors) == 2

    def test_isolated_node_has_no_neighbors(self, mock_store):
        mock_store.search_nodes.return_value = [
            _search_result("i-alone"),
        ]
        g = _make_graph(
            ("i-alone", NodeType.EC2_INSTANCE, "alone", NodeStatus.HEALTHY),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("i-alone")

        assert result["neighbors"] == []
        assert result["blast_radius"]["total_affected"] == 0


# ── Tests: blast radius ─────────────────────────────────────────────


class TestBlastRadius:
    """Blast radius BFS traverses both in_edges and out_edges."""

    def test_linear_chain(self, mock_store):
        """A → B → C: from B, blast radius = {A, C}."""
        mock_store.search_nodes.return_value = [
            _search_result("B", node_type="ec2"),
        ]
        g = _make_graph(
            ("A", NodeType.VPC, "vpc-a", NodeStatus.HEALTHY),
            ("B", NodeType.EC2_INSTANCE, "ec2-b", NodeStatus.HEALTHY),
            ("C", NodeType.RDS_INSTANCE, "rds-c", NodeStatus.HEALTHY),
            ("A", "B", EdgeType.CONTAINS),
            ("B", "C", EdgeType.CONNECTS_TO),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("B")

        br = result["blast_radius"]
        assert br["total_affected"] == 2
        assert br["by_type"].get(NodeType.VPC.value, 0) == 1 or br["by_type"].get("vpc", 0) == 1

    def test_diamond_topology(self, mock_store):
        """Diamond: A → B, A → C, B → D, C → D. From A, all 3 reachable."""
        mock_store.search_nodes.return_value = [
            _search_result("A"),
        ]
        g = _make_graph(
            ("A", NodeType.VPC, "vpc-a", NodeStatus.HEALTHY),
            ("B", NodeType.SUBNET, "subnet-b", NodeStatus.HEALTHY),
            ("C", NodeType.SUBNET, "subnet-c", NodeStatus.HEALTHY),
            ("D", NodeType.EC2_INSTANCE, "ec2-d", NodeStatus.HEALTHY),
            ("A", "B", EdgeType.CONTAINS),
            ("A", "C", EdgeType.CONTAINS),
            ("B", "D", EdgeType.CONTAINS),
            ("C", "D", EdgeType.CONTAINS),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("A")

        assert result["blast_radius"]["total_affected"] == 3

    def test_bidirectional_reachability(self, mock_store):
        """BFS walks both directions: upstream via in_edges too."""
        mock_store.search_nodes.return_value = [
            _search_result("mid"),
        ]
        g = _make_graph(
            ("upstream", NodeType.VPC, "vpc-up", NodeStatus.HEALTHY),
            ("mid", NodeType.EC2_INSTANCE, "ec2-mid", NodeStatus.HEALTHY),
            ("downstream", NodeType.RDS_INSTANCE, "rds-down", NodeStatus.HEALTHY),
            ("upstream", "mid", EdgeType.CONTAINS),
            ("mid", "downstream", EdgeType.CONNECTS_TO),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("mid")

        # Both upstream and downstream should be in blast radius
        assert result["blast_radius"]["total_affected"] == 2

    def test_cycle_does_not_infinite_loop(self, mock_store):
        """Graph with cycle: A → B → C → A. BFS should terminate."""
        mock_store.search_nodes.return_value = [
            _search_result("A"),
        ]
        g = _make_graph(
            ("A", NodeType.VPC, "vpc-a", NodeStatus.HEALTHY),
            ("B", NodeType.SUBNET, "subnet-b", NodeStatus.HEALTHY),
            ("C", NodeType.EC2_INSTANCE, "ec2-c", NodeStatus.HEALTHY),
            ("A", "B", EdgeType.CONTAINS),
            ("B", "C", EdgeType.CONTAINS),
            ("C", "A", EdgeType.CONNECTS_TO),  # back edge creates cycle
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("A")

        assert result["blast_radius"]["total_affected"] == 2  # B + C

    def test_blast_radius_by_type_counts(self, mock_store):
        """Verify by_type breakdown is correct."""
        mock_store.search_nodes.return_value = [
            _search_result("vpc-1", node_type="vpc"),
        ]
        g = _make_graph(
            ("vpc-1", NodeType.VPC, "main-vpc", NodeStatus.HEALTHY),
            ("sub-1", NodeType.SUBNET, "subnet-1", NodeStatus.HEALTHY),
            ("sub-2", NodeType.SUBNET, "subnet-2", NodeStatus.HEALTHY),
            ("ec2-1", NodeType.EC2_INSTANCE, "web-1", NodeStatus.HEALTHY),
            ("vpc-1", "sub-1", EdgeType.CONTAINS),
            ("vpc-1", "sub-2", EdgeType.CONTAINS),
            ("sub-1", "ec2-1", EdgeType.CONTAINS),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("vpc-1")

        by_type = result["blast_radius"]["by_type"]
        assert by_type.get(NodeType.SUBNET.value, 0) == 2 or by_type.get("subnet", 0) == 2
        assert by_type.get(NodeType.EC2_INSTANCE.value, 0) == 1 or by_type.get("ec2", 0) == 1


# ── Tests: dependencies ─────────────────────────────────────────────


class TestDependencies:
    """Upstream (in_edges) and downstream (out_edges) extraction."""

    def test_upstream_downstream_split(self, mock_store):
        mock_store.search_nodes.return_value = [
            _search_result("ec2-1"),
        ]
        g = _make_graph(
            ("vpc-1", NodeType.VPC, "main-vpc", NodeStatus.HEALTHY),
            ("ec2-1", NodeType.EC2_INSTANCE, "web-1", NodeStatus.HEALTHY),
            ("rds-1", NodeType.RDS_INSTANCE, "db-1", NodeStatus.HEALTHY),
            ("vpc-1", "ec2-1", EdgeType.CONTAINS),       # vpc → ec2: ec2's upstream
            ("ec2-1", "rds-1", EdgeType.CONNECTS_TO),    # ec2 → rds: ec2's downstream
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("ec2-1")

        upstream = result["dependencies"]["upstream"]
        downstream = result["dependencies"]["downstream"]

        assert len(upstream) == 1
        assert upstream[0]["id"] == "vpc-1"
        assert len(downstream) == 1
        assert downstream[0]["id"] == "rds-1"

    def test_no_dependencies(self, mock_store):
        mock_store.search_nodes.return_value = [
            _search_result("standalone"),
        ]
        g = _make_graph(
            ("standalone", NodeType.EC2_INSTANCE, "standalone", NodeStatus.HEALTHY),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("standalone")

        assert result["dependencies"]["upstream"] == []
        assert result["dependencies"]["downstream"] == []


# ── Tests: topology summary ─────────────────────────────────────────


class TestTopologySummary:
    """Human-readable topology summary string."""

    def test_summary_includes_key_fields(self, mock_store):
        mock_store.search_nodes.return_value = [
            _search_result("i-abc", node_type="ec2", label="prod-web",
                          resource_type="ec2", vpc_id="vpc-123", region="us-east-1",
                          status="healthy"),
        ]
        g = _make_graph(
            ("i-abc", NodeType.EC2_INSTANCE, "prod-web", NodeStatus.HEALTHY),
            ("subnet-1", NodeType.SUBNET, "sub-a", NodeStatus.HEALTHY),
            ("i-abc", "subnet-1", EdgeType.HOSTED_IN),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("i-abc")

        summary = result["topology_summary"]
        assert "prod-web" in summary
        assert "i-abc" in summary
        assert "vpc-123" in summary
        assert "us-east-1" in summary
        assert "1 direct neighbors" in summary
        assert "1 nodes in blast radius" in summary

    def test_summary_without_vpc(self, mock_store):
        """If no vpc_id, that part is omitted."""
        mock_store.search_nodes.return_value = [
            _search_result("igw-1", node_type="igw", label="main-igw",
                          resource_type="igw", vpc_id="", region="eu-west-1"),
        ]
        g = _make_graph(
            ("igw-1", NodeType.INTERNET_GATEWAY, "main-igw", NodeStatus.HEALTHY),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("igw-1")

        summary = result["topology_summary"]
        assert "VPC" not in summary
        assert "eu-west-1" in summary


# ── Tests: full dossier structure ────────────────────────────────────


class TestDossierStructure:
    """Verify the returned dict has all expected keys."""

    def test_all_keys_present(self, mock_store):
        mock_store.search_nodes.return_value = [
            _search_result("i-test", vpc_id="vpc-1"),
        ]
        g = _make_graph(
            ("i-test", NodeType.EC2_INSTANCE, "test", NodeStatus.HEALTHY),
        )
        mock_store.get_node_neighborhood.return_value = g

        from agenticops.graph.context import get_alert_context
        result = get_alert_context("i-test")

        assert set(result.keys()) == {
            "resource", "neighbors", "blast_radius",
            "dependencies", "topology_summary",
        }
        assert isinstance(result["resource"], dict)
        assert isinstance(result["neighbors"], list)
        assert isinstance(result["blast_radius"], dict)
        assert "total_affected" in result["blast_radius"]
        assert "by_type" in result["blast_radius"]
        assert isinstance(result["dependencies"], dict)
        assert "upstream" in result["dependencies"]
        assert "downstream" in result["dependencies"]
        assert isinstance(result["topology_summary"], str)
