"""Graph serializers — convert InfraGraph to ReactFlow JSON and agent summaries."""

from __future__ import annotations

from typing import Any, Literal

from agenticops.graph.engine import InfraGraph
from agenticops.graph.types import (
    EdgeType,
    GraphEdge,
    GraphMetadata,
    GraphNode,
    NodeStatus,
    NodeType,
    SerializedGraph,
)

# ── ReactFlow type mapping ───────────────────────────────────────────

NODE_TYPE_TO_REACTFLOW: dict[str, str] = {
    NodeType.SUBNET: "subnetNode",
    NodeType.INTERNET_GATEWAY: "igwNode",
    NodeType.NAT_GATEWAY: "natNode",
    NodeType.TRANSIT_GATEWAY: "tgwNode",
    NodeType.TGW_ATTACHMENT: "tgwNode",
    NodeType.PEERING: "peeringNode",
    NodeType.VPC_ENDPOINT: "endpointNode",
    NodeType.ROUTE_TABLE: "routeTableNode",
    NodeType.SECURITY_GROUP: "sgNode",
    NodeType.LOAD_BALANCER: "lbNode",
    NodeType.VPC: "vpcGroupNode",
    NodeType.EC2_INSTANCE: "ec2Node",
    NodeType.RDS_INSTANCE: "rdsNode",
    NodeType.LAMBDA_FUNCTION: "lambdaNode",
    NodeType.EKS_CLUSTER: "eksClusterNode",
    NodeType.EKS_NODE: "eksNodeNode",
    NodeType.EKS_POD: "eksPodNode",
    NodeType.EKS_SERVICE: "eksServiceNode",
    NodeType.ECS_CLUSTER: "ecsClusterNode",
    NodeType.ECS_SERVICE: "ecsServiceNode",
    NodeType.ECS_TASK: "ecsTaskNode",
    NodeType.TARGET_GROUP: "targetGroupNode",
    NodeType.ELASTICACHE_CLUSTER: "cacheNode",
}

# Region-level types
REGION_NODE_TYPE_TO_REACTFLOW: dict[str, str] = {
    NodeType.VPC: "vpcGroupNode",
    NodeType.TRANSIT_GATEWAY: "tgwHubNode",
}

# ── Rank constants (dagre layer assignment) ──────────────────────────

RANK_EXTERNAL = 0   # IGW, TGW, Peering
RANK_PUBLIC = 1     # Public subnets
RANK_NAT = 2        # NAT Gateways
RANK_PRIVATE = 3    # Private subnets
RANK_ENDPOINT = 4   # VPC Endpoints
RANK_COMPUTE = 5    # EC2, Lambda, EKS, ECS, Target Groups
RANK_DATA = 6       # RDS, ElastiCache

RANK_BY_NODE_TYPE: dict[str, int] = {
    NodeType.INTERNET_GATEWAY: RANK_EXTERNAL,
    NodeType.TGW_ATTACHMENT: RANK_EXTERNAL,
    NodeType.TRANSIT_GATEWAY: RANK_EXTERNAL,
    NodeType.PEERING: RANK_EXTERNAL,
    NodeType.LOAD_BALANCER: RANK_EXTERNAL,
    NodeType.NAT_GATEWAY: RANK_NAT,
    NodeType.VPC_ENDPOINT: RANK_ENDPOINT,
    NodeType.EC2_INSTANCE: RANK_COMPUTE,
    NodeType.LAMBDA_FUNCTION: RANK_COMPUTE,
    NodeType.EKS_CLUSTER: RANK_COMPUTE,
    NodeType.EKS_NODE: RANK_COMPUTE,
    NodeType.EKS_POD: RANK_COMPUTE,
    NodeType.EKS_SERVICE: RANK_COMPUTE,
    NodeType.ECS_CLUSTER: RANK_COMPUTE,
    NodeType.ECS_SERVICE: RANK_COMPUTE,
    NodeType.ECS_TASK: RANK_COMPUTE,
    NodeType.TARGET_GROUP: RANK_COMPUTE,
    NodeType.RDS_INSTANCE: RANK_DATA,
    NodeType.ELASTICACHE_CLUSTER: RANK_DATA,
}

# ── Edge style mapping ───────────────────────────────────────────────

def _edge_style(edge_type: str, state: str) -> str:
    """Map edge type + state to a visual style."""
    if state == "blackhole":
        return "blackhole"
    if edge_type == EdgeType.HOSTED_IN:
        return "dashed"
    if edge_type == EdgeType.REFERENCES:
        return "dotted"
    if edge_type == EdgeType.CONNECTS_TO:
        return "dashed"
    if edge_type in (EdgeType.RUNS_ON, EdgeType.MEMBER_OF):
        return "dotted"
    if edge_type == EdgeType.TARGETS:
        return "solid"
    return "solid"


# ── Serializers ──────────────────────────────────────────────────────


def to_reactflow(
    graph: InfraGraph,
    view: Literal["vpc", "region", "multi_region"] = "vpc",
) -> SerializedGraph:
    """Convert InfraGraph to ReactFlow-compatible JSON.

    Replaces frontend mapTopologyToGraph.ts / mapRegionTopologyToGraph.ts.
    """
    g = graph.graph
    type_map = (
        REGION_NODE_TYPE_TO_REACTFLOW if view in ("region", "multi_region")
        else NODE_TYPE_TO_REACTFLOW
    )

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    node_type_counts: dict[str, int] = {}
    anomaly_count = 0

    # Build subnet -> rank mapping for route tables
    subnet_rtb_rank: dict[str, int] = {}
    for node_id, data in g.nodes(data=True):
        if data.get("node_type") == NodeType.SUBNET:
            raw = data.get("raw", {})
            subnet_type = raw.get("type", "private")
            rank = RANK_PUBLIC if subnet_type == "public" else RANK_PRIVATE
            # Check associated route table via edges
            for _, target, edata in g.out_edges(node_id, data=True):
                if edata.get("edge_type") == EdgeType.ASSOCIATED_WITH:
                    current = subnet_rtb_rank.get(target)
                    if current is None or rank < current:
                        subnet_rtb_rank[target] = rank

    # Nodes
    for node_id, data in g.nodes(data=True):
        node_type = data.get("node_type", "")
        rf_type = type_map.get(node_type, "default")
        status = data.get("status", NodeStatus.UNKNOWN)
        raw = data.get("raw", {})

        # Determine rank
        if node_type == NodeType.SUBNET:
            subnet_type = raw.get("type", "private")
            rank = RANK_PUBLIC if subnet_type == "public" else RANK_PRIVATE
        elif node_type == NodeType.ROUTE_TABLE:
            rank = subnet_rtb_rank.get(node_id, RANK_PRIVATE)
        else:
            rank = RANK_BY_NODE_TYPE.get(node_type, RANK_PRIVATE)

        # Check for issues
        has_issue = status == NodeStatus.ERROR

        node_data: dict[str, Any] = {
            "label": data.get("label", node_id),
            "resourceType": data.get("resource_type", ""),
            "raw": raw,
            "status": status,
            "hasIssue": has_issue,
            "rank": rank,
        }

        # Add region-specific data
        if view in ("region", "multi_region") and node_type == NodeType.VPC:
            node_data.update({
                "vpcId": raw.get("vpc_id", node_id),
                "cidr": raw.get("cidr_block", raw.get("cidr", "")),
                "subnetCount": raw.get("subnet_count", 0),
                "isDefault": raw.get("is_default", False),
                "state": raw.get("state", "available"),
            })
        elif view in ("region", "multi_region") and node_type == NodeType.TRANSIT_GATEWAY:
            node_data.update({
                "tgwId": raw.get("transit_gateway_id", node_id),
                "state": raw.get("state", "unknown"),
                "attachmentCount": len(raw.get("attachments", [])),
            })

        nodes.append(GraphNode(
            id=node_id,
            type=rf_type,
            data=node_data,
        ))

        # Count by type
        nt_str = str(node_type)
        node_type_counts[nt_str] = node_type_counts.get(nt_str, 0) + 1

        if has_issue:
            anomaly_count += 1

    # Edges
    for u, v, data in g.edges(data=True):
        edge_type = data.get("edge_type", "")
        state = data.get("state", "")
        style = _edge_style(edge_type, state)
        label = data.get("label", "")

        # Skip containment and SG reference edges from VPC view (too noisy)
        if view == "vpc" and edge_type in (EdgeType.CONTAINS,):
            continue

        edges.append(GraphEdge(
            id=f"e-{u}-{v}-{label}".replace("/", "_"),
            source=u,
            target=v,
            data={
                "label": label,
                "style": style,
                "edgeType": edge_type,
            },
        ))

    # ── Multi-region layout: group by region with horizontal offsets ──
    if view == "multi_region":
        # Collect per-region node ids
        region_groups: dict[str, list[str]] = {}
        for node in nodes:
            node_region = node.data.get("raw", {}).get("region", "") if isinstance(node.data.get("raw"), dict) else ""
            if not node_region:
                node_region = "__unknown__"
            region_groups.setdefault(node_region, []).append(node.id)

        # Assign horizontal offset per region (800px apart)
        sorted_regions = sorted(r for r in region_groups if r != "__unknown__")
        region_x_offset: dict[str, float] = {}
        for idx, reg in enumerate(sorted_regions):
            region_x_offset[reg] = idx * 800.0
        if "__unknown__" in region_groups:
            region_x_offset["__unknown__"] = len(sorted_regions) * 800.0

        # Apply offsets to node positions and tag region in node data
        node_lookup = {n.id: n for n in nodes}
        for reg, nids in region_groups.items():
            x_off = region_x_offset.get(reg, 0.0)
            for i, nid in enumerate(nids):
                node = node_lookup[nid]
                node.position = {"x": x_off + (i % 4) * 180, "y": (i // 4) * 140}
                node.data["region"] = reg

        # Add region label annotation nodes
        for reg in sorted_regions:
            x_off = region_x_offset[reg]
            nodes.append(GraphNode(
                id=f"region-label-{reg}",
                type="regionLabelNode",
                position={"x": x_off, "y": -60},
                data={"label": reg, "isAnnotation": True, "region": reg},
            ))

        # Style cross-region edges distinctly
        node_region_map: dict[str, str] = {}
        for reg, nids in region_groups.items():
            for nid in nids:
                node_region_map[nid] = reg

        for edge in edges:
            src_region = node_region_map.get(edge.source, "")
            tgt_region = node_region_map.get(edge.target, "")
            if src_region and tgt_region and src_region != tgt_region:
                edge.data["crossRegion"] = True
                edge.data["style"] = "cross_region"

    metadata = GraphMetadata(
        node_count=len(nodes),
        edge_count=len(edges),
        node_type_counts=node_type_counts,
        has_anomalies=anomaly_count > 0,
        anomaly_count=anomaly_count,
    )

    return SerializedGraph(nodes=nodes, edges=edges, metadata=metadata)


def to_agent_summary(graph: InfraGraph) -> str:
    """Convert InfraGraph to an agent-friendly text summary.

    Outputs structured text with node counts, connections, and anomalies
    optimized for LLM consumption.
    """
    g = graph.graph
    lines: list[str] = []

    # Node statistics
    type_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        nt = data.get("node_type", "unknown")
        type_counts[nt] = type_counts.get(nt, 0) + 1

    lines.append(f"Graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
    lines.append("Node types:")
    for nt, count in sorted(type_counts.items()):
        lines.append(f"  {nt}: {count}")

    # Status summary
    status_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        s = data.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    lines.append("Status:")
    for s, count in sorted(status_counts.items()):
        lines.append(f"  {s}: {count}")

    # Blackhole routes
    blackholes = [
        (u, v, d) for u, v, d in g.edges(data=True)
        if d.get("state") == "blackhole"
    ]
    if blackholes:
        lines.append(f"Blackhole routes: {len(blackholes)}")
        for u, v, d in blackholes:
            lines.append(f"  {u} -> {v} ({d.get('label', '')})")

    # Error nodes
    error_nodes = [
        (n, d) for n, d in g.nodes(data=True)
        if d.get("status") == NodeStatus.ERROR
    ]
    if error_nodes:
        lines.append(f"Error nodes: {len(error_nodes)}")
        for n, d in error_nodes:
            lines.append(f"  {n} ({d.get('label', '')}) - {d.get('node_type', '')}")

    return "\n".join(lines)
