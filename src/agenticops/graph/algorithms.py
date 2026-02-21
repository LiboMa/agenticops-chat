"""Graph algorithms for infrastructure topology analysis."""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx
from pydantic import BaseModel, Field

from agenticops.graph.engine import InfraGraph
from agenticops.graph.types import EdgeType, NodeStatus, NodeType

logger = logging.getLogger(__name__)


# ── Result models ────────────────────────────────────────────────────


class ReachabilityResult(BaseModel):
    """Result of internet reachability analysis for a subnet."""

    subnet_id: str
    can_reach_internet: bool
    path: list[str] = Field(default_factory=list)
    path_details: list[dict[str, str]] = Field(default_factory=list)
    blocking_reason: str | None = None


class ImpactResult(BaseModel):
    """Result of failure impact analysis."""

    failed_node_id: str
    failed_node_type: str = ""
    affected_nodes: list[dict[str, Any]] = Field(default_factory=list)
    lost_connections: list[dict[str, str]] = Field(default_factory=list)
    isolated_subnets: list[str] = Field(default_factory=list)
    severity: str = "low"


class PathResult(BaseModel):
    """Result of traffic path analysis."""

    source: str
    target: str
    paths_found: int = 0
    paths: list[list[str]] = Field(default_factory=list)
    path_details: list[list[dict[str, str]]] = Field(default_factory=list)


class AnomalyItem(BaseModel):
    """A single detected anomaly."""

    type: str
    severity: str
    node_id: str
    node_type: str = ""
    description: str
    details: dict[str, Any] = Field(default_factory=dict)


class AnomalyReport(BaseModel):
    """Result of structural anomaly detection."""

    total_anomalies: int = 0
    anomalies: list[AnomalyItem] = Field(default_factory=list)
    summary: str = ""


class SegmentInfo(BaseModel):
    """A single network segment."""

    segment_id: int
    node_count: int = 0
    node_ids: list[str] = Field(default_factory=list)
    vpc_ids: list[str] = Field(default_factory=list)
    has_internet: bool = False


class SegmentReport(BaseModel):
    """Result of network segmentation analysis."""

    total_segments: int = 0
    segments: list[SegmentInfo] = Field(default_factory=list)
    isolated_vpcs: list[str] = Field(default_factory=list)


# ── Algorithms ───────────────────────────────────────────────────────


def can_reach_internet(graph: InfraGraph, subnet_id: str) -> ReachabilityResult:
    """Check if a subnet can reach the Internet via IGW (directly or through NAT).

    Traces through: Subnet -> RouteTable -> IGW (public)
                    Subnet -> RouteTable -> NAT -> NAT's Subnet -> RouteTable -> IGW (private)
    """
    g = graph.graph

    if subnet_id not in g:
        return ReachabilityResult(
            subnet_id=subnet_id,
            can_reach_internet=False,
            blocking_reason=f"Subnet {subnet_id} not found in graph",
        )

    # Find all IGW nodes
    igw_nodes = [
        n for n, d in g.nodes(data=True)
        if d.get("node_type") == NodeType.INTERNET_GATEWAY
    ]

    if not igw_nodes:
        return ReachabilityResult(
            subnet_id=subnet_id,
            can_reach_internet=False,
            blocking_reason="No Internet Gateway found in the VPC",
        )

    # Build an undirected view for path finding
    undirected = g.to_undirected()

    for igw_id in igw_nodes:
        try:
            if nx.has_path(undirected, subnet_id, igw_id):
                path = nx.shortest_path(undirected, subnet_id, igw_id)
                path_details = _build_path_details(g, path)

                # Check for blackhole routes along the path
                has_blackhole = _path_has_blackhole(g, path)
                if has_blackhole:
                    return ReachabilityResult(
                        subnet_id=subnet_id,
                        can_reach_internet=False,
                        path=path,
                        path_details=path_details,
                        blocking_reason="Path contains blackhole route",
                    )

                return ReachabilityResult(
                    subnet_id=subnet_id,
                    can_reach_internet=True,
                    path=path,
                    path_details=path_details,
                )
        except nx.NetworkXError:
            continue

    return ReachabilityResult(
        subnet_id=subnet_id,
        can_reach_internet=False,
        blocking_reason="No path found from subnet to any Internet Gateway",
    )


def impact_analysis(graph: InfraGraph, failed_node_id: str) -> ImpactResult:
    """Simulate node failure and assess impact.

    Removes the node and compares connectivity before/after.
    """
    g = graph.graph

    if failed_node_id not in g:
        return ImpactResult(
            failed_node_id=failed_node_id,
            severity="unknown",
        )

    node_data = dict(g.nodes[failed_node_id])
    node_type = node_data.get("node_type", "")

    # Get components before removal
    undirected_before = g.to_undirected()
    components_before = list(nx.connected_components(undirected_before))

    # Create a copy and remove the node
    g_copy = g.copy()
    g_copy.remove_node(failed_node_id)

    undirected_after = g_copy.to_undirected()
    components_after = list(nx.connected_components(undirected_after))

    # Find affected nodes (nodes that lose connectivity)
    affected: list[dict[str, Any]] = []
    lost_connections: list[dict[str, str]] = []
    isolated_subnets: list[str] = []

    # Nodes that were connected to the failed node
    predecessors = list(g.predecessors(failed_node_id))
    successors = list(g.successors(failed_node_id))
    connected_nodes = set(predecessors + successors)

    for node_id in connected_nodes:
        if node_id == failed_node_id:
            continue
        nd = g.nodes.get(node_id, {})
        affected.append({
            "node_id": node_id,
            "node_type": nd.get("node_type", ""),
            "label": nd.get("label", ""),
        })

    # Check which subnets lost internet connectivity
    subnet_nodes = [
        n for n, d in g.nodes(data=True)
        if d.get("node_type") == NodeType.SUBNET and n != failed_node_id
    ]

    igw_nodes = [
        n for n, d in g.nodes(data=True)
        if d.get("node_type") == NodeType.INTERNET_GATEWAY and n != failed_node_id
    ]

    for subnet_id in subnet_nodes:
        had_path = False
        has_path_now = False
        for igw_id in igw_nodes:
            try:
                if nx.has_path(undirected_before, subnet_id, igw_id):
                    had_path = True
            except nx.NetworkXError:
                pass
            try:
                if subnet_id in g_copy and igw_id in g_copy:
                    if nx.has_path(undirected_after, subnet_id, igw_id):
                        has_path_now = True
            except nx.NetworkXError:
                pass

        if had_path and not has_path_now:
            isolated_subnets.append(subnet_id)
            lost_connections.append({
                "from": subnet_id,
                "to": "internet",
                "via": failed_node_id,
            })

    # Determine severity
    if len(isolated_subnets) > 3:
        severity = "critical"
    elif len(isolated_subnets) > 0:
        severity = "high"
    elif len(affected) > 2:
        severity = "medium"
    else:
        severity = "low"

    return ImpactResult(
        failed_node_id=failed_node_id,
        failed_node_type=node_type,
        affected_nodes=affected,
        lost_connections=lost_connections,
        isolated_subnets=isolated_subnets,
        severity=severity,
    )


def find_traffic_path(graph: InfraGraph, source: str, target: str) -> PathResult:
    """Find network paths between two points in the topology."""
    g = graph.graph

    if source not in g:
        return PathResult(source=source, target=target)
    if target not in g:
        return PathResult(source=source, target=target)

    undirected = g.to_undirected()

    try:
        if not nx.has_path(undirected, source, target):
            return PathResult(source=source, target=target)
    except nx.NetworkXError:
        return PathResult(source=source, target=target)

    paths: list[list[str]] = []
    path_details: list[list[dict[str, str]]] = []

    try:
        for path in nx.all_shortest_paths(undirected, source, target):
            paths.append(path)
            path_details.append(_build_path_details(g, path))
            if len(paths) >= 5:  # Limit to 5 paths
                break
    except nx.NetworkXError:
        pass

    return PathResult(
        source=source,
        target=target,
        paths_found=len(paths),
        paths=paths,
        path_details=path_details,
    )


def detect_anomalies(graph: InfraGraph) -> AnomalyReport:
    """Detect structural anomalies in the topology.

    Checks for:
    - Orphan nodes (degree == 0)
    - Blackhole routes (edge state == "blackhole")
    - Routing cycles
    - Unreachable subnets (no path to IGW)
    """
    g = graph.graph
    anomalies: list[AnomalyItem] = []

    # 1. Orphan nodes (no edges at all)
    for node_id, data in g.nodes(data=True):
        if g.degree(node_id) == 0:
            anomalies.append(AnomalyItem(
                type="orphan_node",
                severity="medium",
                node_id=node_id,
                node_type=data.get("node_type", ""),
                description=f"Orphan node {node_id} has no connections",
                details={"label": data.get("label", "")},
            ))

    # 2. Blackhole routes (from edge state AND from route table raw data)
    for u, v, data in g.edges(data=True):
        if data.get("state") == "blackhole":
            anomalies.append(AnomalyItem(
                type="blackhole_route",
                severity="high",
                node_id=u,
                node_type=g.nodes[u].get("node_type", ""),
                description=f"Blackhole route from {u} to {v} (destination: {data.get('label', '')})",
                details={"source": u, "target": v, "destination": data.get("label", "")},
            ))

    # Also check route table nodes' raw data for blackholes with non-existent targets
    for node_id, data in g.nodes(data=True):
        if data.get("node_type") == NodeType.ROUTE_TABLE:
            raw = data.get("raw", {})
            for route in raw.get("routes", []):
                if route.get("state") == "blackhole":
                    dest = route.get("destination", "")
                    target = route.get("target", "")
                    # Avoid duplicate: check if we already caught this via edge
                    already_reported = any(
                        a.type == "blackhole_route"
                        and a.details.get("source") == node_id
                        and a.details.get("destination") == dest
                        for a in anomalies
                    )
                    if not already_reported:
                        anomalies.append(AnomalyItem(
                            type="blackhole_route",
                            severity="high",
                            node_id=node_id,
                            node_type=NodeType.ROUTE_TABLE,
                            description=f"Blackhole route in {node_id}: {dest} -> {target}",
                            details={"source": node_id, "target": target, "destination": dest},
                        ))

    # 3. Routing cycles — only on ROUTES_TO edges (not structural containment edges)
    try:
        routing_edges = [
            (u, v) for u, v, d in g.edges(data=True)
            if d.get("edge_type") in (EdgeType.ROUTES_TO, EdgeType.ASSOCIATED_WITH)
        ]
        routing_subgraph = nx.DiGraph(routing_edges)
        cycles = list(nx.simple_cycles(routing_subgraph))
        for cycle in cycles[:10]:
            if len(cycle) < 2:
                continue
            anomalies.append(AnomalyItem(
                type="routing_cycle",
                severity="critical",
                node_id=cycle[0],
                node_type=g.nodes[cycle[0]].get("node_type", "") if cycle[0] in g else "",
                description=f"Routing cycle detected: {' -> '.join(cycle)} -> {cycle[0]}",
                details={"cycle": cycle},
            ))
    except nx.NetworkXError:
        pass

    # 4. Unreachable subnets
    subnet_nodes = [
        n for n, d in g.nodes(data=True)
        if d.get("node_type") == NodeType.SUBNET
    ]
    igw_nodes = [
        n for n, d in g.nodes(data=True)
        if d.get("node_type") == NodeType.INTERNET_GATEWAY
    ]

    if igw_nodes:
        undirected = g.to_undirected()
        for subnet_id in subnet_nodes:
            reachable = False
            for igw_id in igw_nodes:
                try:
                    if nx.has_path(undirected, subnet_id, igw_id):
                        reachable = True
                        break
                except nx.NetworkXError:
                    pass
            if not reachable:
                subnet_data = g.nodes[subnet_id]
                subnet_type = subnet_data.get("raw", {}).get("type", "unknown")
                # Private subnets without NAT path are expected; only flag if concerning
                if subnet_type == "public":
                    anomalies.append(AnomalyItem(
                        type="unreachable_subnet",
                        severity="high",
                        node_id=subnet_id,
                        node_type=NodeType.SUBNET,
                        description=f"Public subnet {subnet_id} has no path to Internet Gateway",
                        details={"subnet_type": subnet_type},
                    ))

    # 5. Nodes with error status
    for node_id, data in g.nodes(data=True):
        if data.get("status") == NodeStatus.ERROR:
            node_type = data.get("node_type", "")
            if node_type not in (NodeType.SECURITY_GROUP,):  # Skip SG status issues
                anomalies.append(AnomalyItem(
                    type="unhealthy_node",
                    severity="medium",
                    node_id=node_id,
                    node_type=node_type,
                    description=f"Node {node_id} ({data.get('label', '')}) has error status",
                    details={"label": data.get("label", ""), "resource_type": data.get("resource_type", "")},
                ))

    summary_parts = []
    if anomalies:
        by_type: dict[str, int] = {}
        for a in anomalies:
            by_type[a.type] = by_type.get(a.type, 0) + 1
        summary_parts = [f"{count} {atype}" for atype, count in by_type.items()]

    return AnomalyReport(
        total_anomalies=len(anomalies),
        anomalies=anomalies,
        summary=f"Found: {', '.join(summary_parts)}" if summary_parts else "No anomalies detected",
    )


def network_segments(graph: InfraGraph) -> SegmentReport:
    """Analyze network segmentation — find connected components."""
    g = graph.graph
    undirected = g.to_undirected()

    components = list(nx.connected_components(undirected))
    segments: list[SegmentInfo] = []
    isolated_vpcs: list[str] = []

    for idx, component in enumerate(components):
        vpc_ids = [
            n for n in component
            if g.nodes[n].get("node_type") == NodeType.VPC
        ]
        has_igw = any(
            g.nodes[n].get("node_type") == NodeType.INTERNET_GATEWAY
            for n in component
        )
        segments.append(SegmentInfo(
            segment_id=idx,
            node_count=len(component),
            node_ids=sorted(component),
            vpc_ids=vpc_ids,
            has_internet=has_igw,
        ))

        # VPCs in segments with only the VPC node are isolated
        if len(component) == 1 and vpc_ids:
            isolated_vpcs.extend(vpc_ids)

    return SegmentReport(
        total_segments=len(segments),
        segments=segments,
        isolated_vpcs=isolated_vpcs,
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _build_path_details(
    g: nx.DiGraph, path: list[str]
) -> list[dict[str, str]]:
    """Build human-readable details for each hop in a path."""
    details = []
    for node_id in path:
        if node_id in g:
            data = g.nodes[node_id]
            details.append({
                "id": node_id,
                "type": data.get("node_type", ""),
                "label": data.get("label", ""),
            })
        else:
            details.append({"id": node_id, "type": "unknown", "label": node_id})
    return details


def _path_has_blackhole(g: nx.DiGraph, path: list[str]) -> bool:
    """Check if any edge along the path has blackhole state."""
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        # Check both directions since path is on undirected graph
        for src, dst in [(u, v), (v, u)]:
            if g.has_edge(src, dst):
                edge_data = g.edges[src, dst]
                if edge_data.get("state") == "blackhole":
                    return True
    return False
