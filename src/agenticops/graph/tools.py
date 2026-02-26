"""Graph-based Strands tools for Agent use.

Each tool builds an InfraGraph from existing network_tools output,
runs the appropriate algorithm, and returns JSON results.
"""

from __future__ import annotations

import json
import logging

from strands import tool

from agenticops.graph.algorithms import (
    can_reach_internet,
    detect_anomalies,
    find_traffic_path,
    impact_analysis,
    network_segments,
)
from agenticops.graph.engine import InfraGraph
from agenticops.graph.serializers import to_agent_summary

logger = logging.getLogger(__name__)


def _build_vpc_graph(region: str, vpc_id: str) -> InfraGraph:
    """Build graph from VPC topology (calls existing network tool)."""
    from agenticops.tools.network_tools import analyze_vpc_topology

    raw = analyze_vpc_topology(region=region, vpc_id=vpc_id)
    topo = json.loads(raw)
    return InfraGraph().build_from_vpc_topology(topo)


def _build_region_graph(region: str) -> InfraGraph:
    """Build graph from region topology (calls existing network tool)."""
    from agenticops.tools.network_tools import describe_region_topology

    raw = describe_region_topology(region=region)
    topo = json.loads(raw)
    return InfraGraph().build_from_region_topology(topo)


def _build_multi_region_graph(regions: str) -> InfraGraph:
    """Build graph from cross-region topology (calls existing network tool)."""
    from agenticops.tools.network_tools import describe_cross_region_topology

    raw = describe_cross_region_topology(regions=regions)
    topo = json.loads(raw)
    if "error" in topo:
        raise RuntimeError(topo["error"])
    return InfraGraph().build_from_multi_region_topology(topo)


@tool
def analyze_cross_region_topology(regions: str = "") -> str:
    """Analyze network topology across multiple AWS regions.

    Builds a merged multi-region graph and runs anomaly detection and
    segmentation analysis. Highlights cross-region connections, isolated
    regions, broken peerings, and TGW asymmetry.

    Args:
        regions: Comma-separated region codes (e.g. 'us-east-1,eu-west-1').
                 If empty, discovers all enabled regions.

    Returns:
        JSON with per-region summaries, cross-region connections,
        anomalies, and network segments.
    """
    try:
        graph = _build_multi_region_graph(regions)
        g = graph.graph

        # Per-region summaries
        region_summaries: dict[str, dict] = {}
        for node_id, data in g.nodes(data=True):
            raw = data.get("raw", {})
            node_region = raw.get("region", "unknown")
            if node_region not in region_summaries:
                region_summaries[node_region] = {
                    "region": node_region,
                    "vpc_count": 0,
                    "tgw_count": 0,
                    "node_count": 0,
                }
            region_summaries[node_region]["node_count"] += 1
            nt = data.get("node_type", "")
            if nt == "vpc":
                region_summaries[node_region]["vpc_count"] += 1
            elif nt == "tgw":
                region_summaries[node_region]["tgw_count"] += 1

        # Cross-region connections
        from agenticops.graph.types import EdgeType as ET
        cross_region_connections = []
        for u, v, edata in g.edges(data=True):
            u_region = g.nodes[u].get("raw", {}).get("region", "")
            v_region = g.nodes[v].get("raw", {}).get("region", "")
            if u_region and v_region and u_region != v_region:
                cross_region_connections.append({
                    "source": u,
                    "source_region": u_region,
                    "target": v,
                    "target_region": v_region,
                    "edge_type": edata.get("edge_type", ""),
                    "label": edata.get("label", ""),
                    "state": edata.get("state", ""),
                })

        # Anomalies
        anomaly_report = detect_anomalies(graph)

        # Segmentation
        segment_report = network_segments(graph)

        # Agent summary
        summary = to_agent_summary(graph)

        output = {
            "region_summaries": list(region_summaries.values()),
            "cross_region_connections": cross_region_connections,
            "anomalies": anomaly_report.model_dump(),
            "segments": segment_report.model_dump(),
            "graph_summary": summary,
        }
        return json.dumps(output, indent=2)
    except Exception as e:
        logger.exception("analyze_cross_region_topology failed")
        return json.dumps({"error": str(e)})


@tool
def query_reachability(region: str, vpc_id: str, subnet_id: str) -> str:
    """Check if a subnet can reach the Internet, returning the exact path or blocking reason.

    Builds a topology graph for the VPC and traces the path from the subnet
    through route tables and gateways to the Internet Gateway. Reports
    blackhole routes that block connectivity.

    Args:
        region: AWS region (e.g., 'us-east-1')
        vpc_id: VPC ID to analyze
        subnet_id: Subnet ID to check reachability for

    Returns:
        JSON with can_reach_internet (bool), path (list of node IDs),
        path_details (per-hop type and label), and blocking_reason if unreachable.
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        result = can_reach_internet(graph, subnet_id)
        return result.model_dump_json(indent=2)
    except Exception as e:
        logger.exception("query_reachability failed")
        return json.dumps({"error": str(e)})


@tool
def query_impact_radius(region: str, vpc_id: str, resource_id: str) -> str:
    """Simulate a resource failure and return the blast radius.

    Removes the specified node from the topology graph and computes
    which subnets lose Internet connectivity and which connections are broken.

    Args:
        region: AWS region (e.g., 'us-east-1')
        vpc_id: VPC ID to analyze
        resource_id: Resource ID to simulate failure for (e.g., nat-xxx, igw-xxx, tgw-att-xxx)

    Returns:
        JSON with affected_nodes, lost_connections, isolated_subnets, and severity.
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        result = impact_analysis(graph, resource_id)
        return result.model_dump_json(indent=2)
    except Exception as e:
        logger.exception("query_impact_radius failed")
        return json.dumps({"error": str(e)})


@tool
def find_network_path(region: str, vpc_id: str, source: str, target: str) -> str:
    """Find the network path between two resources in a VPC.

    Traces traffic flow through route tables, gateways, and subnets.
    Returns up to 5 shortest paths with per-hop details.

    Args:
        region: AWS region (e.g., 'us-east-1')
        vpc_id: VPC ID to analyze
        source: Source resource ID (e.g., subnet-xxx)
        target: Target resource ID (e.g., igw-xxx, nat-xxx, subnet-yyy)

    Returns:
        JSON with paths (list of node ID lists) and path_details (per-hop info).
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        result = find_traffic_path(graph, source, target)
        return result.model_dump_json(indent=2)
    except Exception as e:
        logger.exception("find_network_path failed")
        return json.dumps({"error": str(e)})


@tool
def detect_network_anomalies(region: str, vpc_id: str) -> str:
    """Detect structural anomalies in a VPC's network topology.

    Checks for orphan nodes (no connections), blackhole routes,
    routing cycles, unreachable public subnets, and nodes in error state.

    Args:
        region: AWS region (e.g., 'us-east-1')
        vpc_id: VPC ID to analyze

    Returns:
        JSON with total_anomalies count, anomaly list (each with type, severity,
        node_id, description), and summary string.
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        result = detect_anomalies(graph)
        return result.model_dump_json(indent=2)
    except Exception as e:
        logger.exception("detect_network_anomalies failed")
        return json.dumps({"error": str(e)})


@tool
def analyze_network_segments(region: str) -> str:
    """Analyze network segmentation across all VPCs in a region.

    Builds a region-level topology graph and identifies connected components
    (network segments), isolated VPCs, and cross-VPC connectivity via
    Transit Gateways and peering connections.

    Args:
        region: AWS region (e.g., 'us-east-1')

    Returns:
        JSON with total_segments, segment details (node counts, VPC IDs,
        internet access), and isolated_vpcs list.
    """
    try:
        graph = _build_region_graph(region)
        result = network_segments(graph)

        # Also include a text summary for the agent
        summary = to_agent_summary(graph)
        output = result.model_dump()
        output["graph_summary"] = summary
        return json.dumps(output, indent=2)
    except Exception as e:
        logger.exception("analyze_network_segments failed")
        return json.dumps({"error": str(e)})
