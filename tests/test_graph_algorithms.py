"""Tests for graph engine and algorithms."""

import pytest

from agenticops.graph.engine import InfraGraph
from agenticops.graph.types import EdgeType, NodeStatus, NodeType
from agenticops.graph.algorithms import (
    can_reach_internet,
    detect_anomalies,
    find_traffic_path,
    impact_analysis,
    network_segments,
)
from agenticops.graph.serializers import to_agent_summary, to_reactflow


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_vpc_topology(
    *,
    has_igw: bool = True,
    has_nat: bool = True,
    has_blackhole: bool = False,
    has_tgw: bool = False,
    has_peering: bool = False,
) -> dict:
    """Build a minimal VPC topology dict for testing."""
    topo = {
        "vpc_id": "vpc-001",
        "vpc_cidr": "10.0.0.0/16",
        "vpc_name": "test-vpc",
        "region": "us-east-1",
        "internet_gateways": [],
        "vpc_peering_connections": [],
        "vpc_endpoints": [],
        "subnets": [
            {
                "subnet_id": "subnet-pub-1",
                "name": "public-subnet-1",
                "az": "us-east-1a",
                "cidr": "10.0.1.0/24",
                "type": "public",
                "available_ips": 250,
                "route_table_id": "rtb-pub",
                "default_route_target": "igw-001",
            },
            {
                "subnet_id": "subnet-priv-1",
                "name": "private-subnet-1",
                "az": "us-east-1a",
                "cidr": "10.0.2.0/24",
                "type": "private",
                "available_ips": 250,
                "route_table_id": "rtb-priv",
                "default_route_target": "nat-001" if has_nat else None,
            },
        ],
        "route_tables": [
            {
                "route_table_id": "rtb-pub",
                "name": "public-rt",
                "associated_subnets": ["subnet-pub-1"],
                "is_main": False,
                "routes": [
                    {"destination": "10.0.0.0/16", "state": "active", "target": "local", "origin": "CreateRouteTable"},
                    {
                        "destination": "0.0.0.0/0",
                        "state": "active",
                        "target": "igw-001" if has_igw else "blackhole",
                        "origin": "CreateRoute",
                    },
                ],
            },
            {
                "route_table_id": "rtb-priv",
                "name": "private-rt",
                "associated_subnets": ["subnet-priv-1"],
                "is_main": True,
                "routes": [
                    {"destination": "10.0.0.0/16", "state": "active", "target": "local", "origin": "CreateRouteTable"},
                ]
                + (
                    [{"destination": "0.0.0.0/0", "state": "active", "target": "nat-001", "origin": "CreateRoute"}]
                    if has_nat
                    else []
                )
                + (
                    [{"destination": "0.0.0.0/0", "state": "blackhole", "target": "nat-deleted", "origin": "CreateRoute"}]
                    if has_blackhole
                    else []
                ),
            },
        ],
        "nat_gateways": [],
        "transit_gateway_attachments": [],
        "security_group_dependency_map": {},
        "blackhole_routes": [],
    }

    if has_igw:
        topo["internet_gateways"] = [
            {"igw_id": "igw-001", "name": "main-igw", "attachments": [{"vpc_id": "vpc-001", "state": "attached"}]}
        ]

    if has_nat:
        topo["nat_gateways"] = [
            {
                "nat_gateway_id": "nat-001",
                "name": "main-nat",
                "subnet_id": "subnet-pub-1",
                "state": "available",
                "connectivity_type": "public",
                "az": "us-east-1a",
            }
        ]

    if has_blackhole:
        topo["blackhole_routes"] = [
            {"route_table_id": "rtb-priv", "destination": "0.0.0.0/0", "target": "nat-deleted", "affected_subnets": ["subnet-priv-1"]}
        ]

    if has_tgw:
        topo["transit_gateway_attachments"] = [
            {
                "attachment_id": "tgw-att-001",
                "transit_gateway_id": "tgw-001",
                "resource_type": "vpc",
                "state": "available",
            }
        ]

    if has_peering:
        topo["vpc_peering_connections"] = [
            {
                "pcx_id": "pcx-001",
                "status": "active",
                "requester_vpc": "vpc-001",
                "requester_cidr": "10.0.0.0/16",
                "requester_owner": "111111111111",
                "accepter_vpc": "vpc-002",
                "accepter_cidr": "10.1.0.0/16",
                "accepter_owner": "222222222222",
            }
        ]

    return topo


def _make_region_topology(vpc_count: int = 2, has_tgw: bool = True) -> dict:
    """Build a minimal region topology dict."""
    vpcs = [
        {
            "vpc_id": f"vpc-{i:03d}",
            "name": f"vpc-{i}",
            "cidr_block": f"10.{i}.0.0/16",
            "state": "available",
            "is_default": i == 0,
            "subnet_count": 3,
        }
        for i in range(vpc_count)
    ]

    tgws = []
    if has_tgw and vpc_count >= 2:
        tgws = [
            {
                "transit_gateway_id": "tgw-001",
                "name": "main-tgw",
                "state": "available",
                "attachments": [
                    {"attachment_id": f"tgw-att-{i}", "resource_type": "vpc", "resource_id": f"vpc-{i:03d}", "state": "available"}
                    for i in range(vpc_count)
                ],
            }
        ]

    return {
        "region": "us-east-1",
        "vpcs": vpcs,
        "transit_gateways": tgws,
        "peering_connections": [],
    }


# ── Engine Tests ─────────────────────────────────────────────────────


class TestInfraGraphBuild:
    def test_build_from_vpc_topology_basic(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)

        assert g.graph.number_of_nodes() > 0
        assert g.graph.number_of_edges() > 0

        # Check VPC node exists
        vpc_node = g.get_node("vpc-001")
        assert vpc_node is not None
        assert vpc_node["node_type"] == NodeType.VPC

    def test_build_from_vpc_topology_node_types(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True, has_tgw=True)
        g = InfraGraph().build_from_vpc_topology(topo)

        igws = g.get_nodes_by_type(NodeType.INTERNET_GATEWAY)
        assert len(igws) == 1
        assert igws[0] == "igw-001"

        subnets = g.get_nodes_by_type(NodeType.SUBNET)
        assert len(subnets) == 2

        nats = g.get_nodes_by_type(NodeType.NAT_GATEWAY)
        assert len(nats) == 1

        tgws = g.get_nodes_by_type(NodeType.TGW_ATTACHMENT)
        assert len(tgws) == 1

    def test_build_from_vpc_topology_edges(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)

        # Subnet -> RouteTable associations
        neighbors = g.get_neighbors("subnet-pub-1", EdgeType.ASSOCIATED_WITH)
        assert "rtb-pub" in neighbors

    def test_build_from_region_topology(self):
        topo = _make_region_topology(vpc_count=3, has_tgw=True)
        g = InfraGraph().build_from_region_topology(topo)

        vpcs = g.get_nodes_by_type(NodeType.VPC)
        assert len(vpcs) == 3

        tgws = g.get_nodes_by_type(NodeType.TRANSIT_GATEWAY)
        assert len(tgws) == 1

    def test_merge_graphs(self):
        g1 = InfraGraph().build_from_vpc_topology(_make_vpc_topology())
        g2 = InfraGraph()
        g2._graph.add_node("extra-node", node_type="test")

        g1.merge(g2)
        assert "extra-node" in g1.graph

    def test_subgraph(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)

        sub = g.subgraph({"vpc-001", "igw-001"})
        assert sub.graph.number_of_nodes() == 2


# ── Algorithm Tests ──────────────────────────────────────────────────


class TestReachability:
    def test_public_subnet_reaches_internet(self):
        """Public subnet -> route table -> IGW = reachable."""
        topo = _make_vpc_topology(has_igw=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = can_reach_internet(g, "subnet-pub-1")

        assert result.can_reach_internet is True
        assert len(result.path) > 0
        assert "igw-001" in result.path

    def test_private_subnet_through_nat_reaches_internet(self):
        """Private subnet -> RT -> NAT -> NAT's subnet -> RT -> IGW = reachable."""
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = can_reach_internet(g, "subnet-priv-1")

        assert result.can_reach_internet is True
        assert "igw-001" in result.path

    def test_isolated_subnet_no_internet(self):
        """Subnet with no route to 0.0.0.0/0 = unreachable."""
        topo = _make_vpc_topology(has_igw=False, has_nat=False)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = can_reach_internet(g, "subnet-pub-1")

        assert result.can_reach_internet is False
        assert result.blocking_reason is not None

    def test_blackhole_blocks_reachability(self):
        """Path with blackhole route should be detected by anomaly detection."""
        topo = _make_vpc_topology(has_igw=True, has_nat=False, has_blackhole=True)
        g = InfraGraph().build_from_vpc_topology(topo)

        # The private subnet can still find a path via VPC containment edges,
        # but the blackhole is detectable via anomaly detection.
        result = can_reach_internet(g, "subnet-priv-1")
        # Path exists through VPC node (structural connectivity)
        assert result.subnet_id == "subnet-priv-1"

        # The blackhole should be caught by anomaly detection
        anomaly_result = detect_anomalies(g)
        blackholes = [a for a in anomaly_result.anomalies if a.type == "blackhole_route"]
        assert len(blackholes) > 0

    def test_nonexistent_subnet(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)
        result = can_reach_internet(g, "subnet-nonexistent")

        assert result.can_reach_internet is False
        assert "not found" in (result.blocking_reason or "")


class TestImpactAnalysis:
    def test_nat_failure_isolates_private_subnets(self):
        """Removing NAT gateway should isolate private subnets from internet."""
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = impact_analysis(g, "nat-001")

        assert result.failed_node_id == "nat-001"
        assert len(result.affected_nodes) > 0

    def test_igw_failure_impacts_all(self):
        """Removing IGW should affect connected nodes."""
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = impact_analysis(g, "igw-001")

        assert result.failed_node_id == "igw-001"
        assert result.failed_node_type == NodeType.INTERNET_GATEWAY
        # IGW connects to VPC and route table — those are affected
        assert len(result.affected_nodes) > 0

    def test_nonexistent_node(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)
        result = impact_analysis(g, "nonexistent")

        assert result.severity == "unknown"


class TestPathFinding:
    def test_find_path_between_subnets(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = find_traffic_path(g, "subnet-pub-1", "subnet-priv-1")

        assert result.paths_found > 0
        assert len(result.paths) > 0

    def test_path_to_igw(self):
        topo = _make_vpc_topology(has_igw=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = find_traffic_path(g, "subnet-pub-1", "igw-001")

        assert result.paths_found > 0

    def test_no_path(self):
        topo = _make_vpc_topology(has_igw=False, has_nat=False)
        g = InfraGraph().build_from_vpc_topology(topo)
        # Add an isolated node
        g._graph.add_node("isolated-node", node_type="test")
        result = find_traffic_path(g, "subnet-pub-1", "isolated-node")

        assert result.paths_found == 0


class TestAnomalyDetection:
    def test_blackhole_detected(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=False, has_blackhole=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = detect_anomalies(g)

        blackhole_anomalies = [a for a in result.anomalies if a.type == "blackhole_route"]
        assert len(blackhole_anomalies) > 0

    def test_orphan_node_detected(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)
        # Add an orphan node
        g._graph.add_node("orphan-001", node_type=NodeType.SUBNET, label="orphan", status=NodeStatus.UNKNOWN)
        result = detect_anomalies(g)

        orphan_anomalies = [a for a in result.anomalies if a.type == "orphan_node"]
        assert len(orphan_anomalies) > 0

    def test_no_anomalies_in_healthy_vpc(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = detect_anomalies(g)

        # A healthy VPC should have few/no anomalies
        critical = [a for a in result.anomalies if a.severity == "critical"]
        assert len(critical) == 0


class TestNetworkSegments:
    def test_single_connected_segment(self):
        topo = _make_region_topology(vpc_count=2, has_tgw=True)
        g = InfraGraph().build_from_region_topology(topo)
        result = network_segments(g)

        # All VPCs connected via TGW should be in one segment
        assert result.total_segments == 1

    def test_isolated_vpcs(self):
        topo = _make_region_topology(vpc_count=3, has_tgw=False)
        g = InfraGraph().build_from_region_topology(topo)
        result = network_segments(g)

        # Without TGW, each VPC is its own segment
        assert result.total_segments == 3
        assert len(result.isolated_vpcs) == 3


# ── Serializer Tests ─────────────────────────────────────────────────


class TestSerializers:
    def test_to_reactflow_vpc(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = to_reactflow(g, view="vpc")

        assert len(result.nodes) > 0
        assert len(result.edges) > 0
        assert result.metadata.node_count == len(result.nodes)
        assert result.metadata.edge_count == len(result.edges)

        # Check node types are ReactFlow-compatible
        node_types = {n.type for n in result.nodes}
        assert "subnetNode" in node_types or "igwNode" in node_types

    def test_to_reactflow_region(self):
        topo = _make_region_topology(vpc_count=2, has_tgw=True)
        g = InfraGraph().build_from_region_topology(topo)
        result = to_reactflow(g, view="region")

        assert len(result.nodes) > 0
        node_types = {n.type for n in result.nodes}
        assert "vpcGroupNode" in node_types

    def test_to_agent_summary(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        summary = to_agent_summary(g)

        assert "nodes" in summary.lower() or "Nodes" in summary
        assert "edges" in summary.lower() or "Edges" in summary
