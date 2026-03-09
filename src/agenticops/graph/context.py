"""Graph Context Builder — builds structured dossiers from stored graph data.

Used by the alert pipeline and RCA agent to quickly understand the
topology around a resource without live AWS calls.
"""

from __future__ import annotations

import logging
from typing import Any

from agenticops.graph.store import GraphStore
from agenticops.graph.types import EdgeType, NodeType

logger = logging.getLogger(__name__)


def get_alert_context(resource_hint: str) -> dict[str, Any] | None:
    """Build a structured context dossier from the stored graph.

    Args:
        resource_hint: Resource ID (e.g., "i-abc123", "vpc-xyz", "my-rds-db").

    Returns:
        Dict with keys: resource, neighbors, blast_radius, dependencies,
        topology_summary. Returns None if resource not found.
    """
    store = GraphStore()

    # Find the resource node
    nodes = store.search_nodes(query=resource_hint, limit=5)
    if not nodes:
        logger.info("get_alert_context: no node found for %s", resource_hint)
        return None

    # Prefer exact ID match, fall back to first result
    target_node = nodes[0]
    for n in nodes:
        if n["id"] == resource_hint:
            target_node = n
            break

    node_id = target_node["id"]

    # Load neighborhood graph (depth=2 gives 2-hop context)
    neighborhood = store.get_node_neighborhood(node_id, depth=2)
    g = neighborhood.graph

    # Build neighbor list
    neighbors: list[dict[str, Any]] = []
    for nid in neighborhood.get_neighbors(node_id):
        ndata = g.nodes.get(nid, {})
        edge_data = g.edges.get((node_id, nid), {}) or g.edges.get((nid, node_id), {})
        neighbors.append({
            "id": nid,
            "node_type": ndata.get("node_type", ""),
            "label": ndata.get("label", ""),
            "status": ndata.get("status", ""),
            "relationship": edge_data.get("edge_type", ""),
        })

    # Blast radius: count of all nodes reachable from this node
    reachable: set[str] = set()
    frontier = {node_id}
    visited: set[str] = set()
    while frontier:
        current = frontier.pop()
        if current in visited:
            continue
        visited.add(current)
        if current != node_id:
            reachable.add(current)
        for _, successor in g.out_edges(current):
            if successor not in visited:
                frontier.add(successor)
        for predecessor, _ in g.in_edges(current):
            if predecessor not in visited:
                frontier.add(predecessor)

    blast_radius = {
        "total_affected": len(reachable),
        "by_type": {},
    }
    for rid in reachable:
        rdata = g.nodes.get(rid, {})
        ntype = rdata.get("node_type", "unknown")
        blast_radius["by_type"][ntype] = blast_radius["by_type"].get(ntype, 0) + 1

    # Dependencies: upstream (what this node depends on) and downstream (what depends on this)
    upstream: list[dict[str, str]] = []
    downstream: list[dict[str, str]] = []
    for pred, _, edata in g.in_edges(node_id, data=True):
        pdata = g.nodes.get(pred, {})
        upstream.append({
            "id": pred,
            "label": pdata.get("label", ""),
            "node_type": pdata.get("node_type", ""),
            "edge_type": edata.get("edge_type", ""),
        })
    for _, succ, edata in g.out_edges(node_id, data=True):
        sdata = g.nodes.get(succ, {})
        downstream.append({
            "id": succ,
            "label": sdata.get("label", ""),
            "node_type": sdata.get("node_type", ""),
            "edge_type": edata.get("edge_type", ""),
        })

    dependencies = {
        "upstream": upstream,
        "downstream": downstream,
    }

    # Topology summary: human-readable position description
    summary_parts = [
        f"{target_node['resource_type']} '{target_node['label']}' ({node_id})"
    ]
    if target_node.get("vpc_id"):
        summary_parts.append(f"in VPC {target_node['vpc_id']}")
    if target_node.get("region"):
        summary_parts.append(f"region {target_node['region']}")
    summary_parts.append(f"status={target_node.get('status', 'unknown')}")
    summary_parts.append(f"{len(neighbors)} direct neighbors")
    summary_parts.append(f"{len(reachable)} nodes in blast radius")

    topology_summary = ", ".join(summary_parts)

    return {
        "resource": target_node,
        "neighbors": neighbors,
        "blast_radius": blast_radius,
        "dependencies": dependencies,
        "topology_summary": topology_summary,
    }
