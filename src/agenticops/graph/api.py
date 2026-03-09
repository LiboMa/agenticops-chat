"""Graph API endpoints — FastAPI router for graph-based topology queries."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agenticops.graph.algorithms import (
    AnomalyReport,
    CapacityRiskReport,
    ChangeSimulationResult,
    DependencyChainResult,
    ImpactResult,
    PathResult,
    ReachabilityResult,
    SPOFReport,
    can_reach_internet,
    capacity_risk_analysis,
    dependency_chain_analysis,
    detect_anomalies,
    detect_spof,
    find_traffic_path,
    impact_analysis,
    simulate_change,
)
from agenticops.graph.engine import InfraGraph
from agenticops.graph.serializers import to_reactflow
from agenticops.graph.types import SerializedGraph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _ensure_aws_session(region: str) -> None:
    """Ensure AWS session exists for the given region."""
    import boto3
    import agenticops.tools.aws_tools as aws_tools_module

    for key in aws_tools_module._session_cache:
        if key.endswith(f":{region}"):
            return
    session = boto3.Session(region_name=region)
    aws_tools_module._session_cache[f"web:{region}"] = session


def _build_vpc_graph(region: str, vpc_id: str) -> InfraGraph:
    """Build an InfraGraph from a VPC topology."""
    _ensure_aws_session(region)
    from agenticops.tools.network_tools import analyze_vpc_topology

    raw = analyze_vpc_topology(region=region, vpc_id=vpc_id)
    topo = json.loads(raw)
    return InfraGraph().build_from_vpc_topology(topo)


def _build_enriched_vpc_graph(region: str, vpc_id: str) -> InfraGraph:
    """Build VPC graph enriched with compute resources."""
    graph = _build_vpc_graph(region, vpc_id)
    from agenticops.graph.collectors import collect_vpc_compute

    compute_data = collect_vpc_compute(region, vpc_id)
    graph.enrich_with_compute(compute_data)
    return graph


def _build_region_graph(region: str) -> InfraGraph:
    """Build an InfraGraph from a region topology."""
    _ensure_aws_session(region)
    from agenticops.tools.network_tools import describe_region_topology

    raw = describe_region_topology(region=region)
    topo = json.loads(raw)
    return InfraGraph().build_from_region_topology(topo)


def _build_multi_region_graph(regions: list[str]) -> InfraGraph:
    """Build an InfraGraph from multi-region topology."""
    regions_str = ",".join(regions)
    # Ensure sessions for all requested regions
    for reg in regions:
        _ensure_aws_session(reg)

    from agenticops.tools.network_tools import describe_cross_region_topology

    raw = describe_cross_region_topology(regions=regions_str)
    topo = json.loads(raw)
    if "error" in topo:
        raise RuntimeError(topo["error"])
    return InfraGraph().build_from_multi_region_topology(topo)


@router.get("/multi-region")
async def get_multi_region_graph(
    regions: str = Query("", description="Comma-separated region codes, e.g. 'us-east-1,eu-west-1'. Empty = all regions."),
) -> SerializedGraph:
    """Get ReactFlow-ready graph for multi-region network topology.

    Aggregates per-region graphs, adds cross-region VPC peering and TGW
    peering edges, and returns a single graph with region grouping.
    """
    try:
        region_list = [r.strip() for r in regions.split(",") if r.strip()] if regions else []
        graph = _build_multi_region_graph(region_list)
        return to_reactflow(graph, view="multi_region")
    except Exception as e:
        logger.exception("Failed to build multi-region graph")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}")
async def get_vpc_graph(
    vpc_id: str,
    region: str = Query("us-east-1"),
) -> SerializedGraph:
    """Get ReactFlow-ready graph for a single VPC.

    Replaces /api/network/vpc-topology + frontend mapTopologyToGraph.ts.
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return to_reactflow(graph, view="vpc")
    except Exception as e:
        logger.exception("Failed to build VPC graph")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/region")
async def get_region_graph(
    region: str = Query("us-east-1"),
) -> SerializedGraph:
    """Get ReactFlow-ready graph for a region (multi-VPC view).

    Replaces /api/network/region-topology + frontend mapRegionTopologyToGraph.ts.
    """
    try:
        graph = _build_region_graph(region)
        return to_reactflow(graph, view="region")
    except Exception as e:
        logger.exception("Failed to build region graph")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/reachability/{subnet_id}")
async def get_reachability(
    vpc_id: str,
    subnet_id: str,
    region: str = Query("us-east-1"),
) -> ReachabilityResult:
    """Check if a subnet can reach the Internet."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return can_reach_internet(graph, subnet_id)
    except Exception as e:
        logger.exception("Reachability check failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/impact/{resource_id}")
async def get_impact(
    vpc_id: str,
    resource_id: str,
    region: str = Query("us-east-1"),
) -> ImpactResult:
    """Simulate resource failure and return impact analysis."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return impact_analysis(graph, resource_id)
    except Exception as e:
        logger.exception("Impact analysis failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/path")
async def get_path(
    vpc_id: str,
    source: str = Query(...),
    target: str = Query(...),
    region: str = Query("us-east-1"),
) -> PathResult:
    """Find traffic path between two resources."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return find_traffic_path(graph, source, target)
    except Exception as e:
        logger.exception("Path finding failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/anomalies")
async def get_anomalies(
    vpc_id: str,
    region: str = Query("us-east-1"),
) -> AnomalyReport:
    """Detect structural anomalies in VPC topology."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return detect_anomalies(graph)
    except Exception as e:
        logger.exception("Anomaly detection failed")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── SRE Analysis Endpoints ───────────────────────────────────────────


@router.get("/vpc/{vpc_id}/enriched")
async def get_enriched_vpc_graph(
    vpc_id: str,
    region: str = Query("us-east-1"),
) -> SerializedGraph:
    """Get ReactFlow-ready graph for a VPC enriched with compute resources."""
    try:
        graph = _build_enriched_vpc_graph(region, vpc_id)
        return to_reactflow(graph, view="vpc")
    except Exception as e:
        logger.exception("Failed to build enriched VPC graph")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/vpc/{vpc_id}/dependency-chain")
async def post_dependency_chain(
    vpc_id: str,
    fault_node_id: str = Query(..., description="Node ID to simulate failure for"),
    region: str = Query("us-east-1"),
) -> DependencyChainResult:
    """Analyze dependency chain from a fault node (reverse BFS)."""
    try:
        graph = _build_enriched_vpc_graph(region, vpc_id)
        return dependency_chain_analysis(graph, fault_node_id)
    except Exception as e:
        logger.exception("Dependency chain analysis failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/spof")
async def get_spof(
    vpc_id: str,
    region: str = Query("us-east-1"),
) -> SPOFReport:
    """Detect single points of failure in VPC topology."""
    try:
        graph = _build_enriched_vpc_graph(region, vpc_id)
        return detect_spof(graph)
    except Exception as e:
        logger.exception("SPOF detection failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/capacity-risk")
async def get_capacity_risk(
    vpc_id: str,
    region: str = Query("us-east-1"),
    threshold: float = Query(0.8, ge=0.0, le=1.0),
) -> CapacityRiskReport:
    """Analyze capacity risks (IP exhaustion, pod limits)."""
    try:
        graph = _build_enriched_vpc_graph(region, vpc_id)
        return capacity_risk_analysis(graph, threshold)
    except Exception as e:
        logger.exception("Capacity risk analysis failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/vpc/{vpc_id}/change-simulation")
async def post_change_simulation(
    vpc_id: str,
    edge_source: str = Query(..., description="Source node of the edge to remove"),
    edge_target: str = Query(..., description="Target node of the edge to remove"),
    region: str = Query("us-east-1"),
) -> ChangeSimulationResult:
    """Simulate removing an edge and report reachability changes."""
    try:
        graph = _build_enriched_vpc_graph(region, vpc_id)
        return simulate_change(graph, edge_source, edge_target)
    except Exception as e:
        logger.exception("Change simulation failed")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── World Graph (persisted) Endpoints ─────────────────────────────


@router.get("/search")
async def search_graph_nodes(
    q: str = Query("", description="Search query (matches label or ID)"),
    node_type: str = Query("", description="Filter by node type"),
    region: str = Query("", description="Filter by region"),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    """Search persisted graph nodes by label/type/region."""
    try:
        from agenticops.graph.store import GraphStore
        store = GraphStore()
        return store.search_nodes(query=q, node_type=node_type, region=region, limit=limit)
    except Exception as e:
        logger.exception("Graph search failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/node/{node_id}/context")
async def get_node_context(node_id: str) -> dict:
    """Get full neighborhood context for a node (for RCA enrichment)."""
    try:
        from agenticops.graph.context import get_alert_context
        ctx = get_alert_context(node_id)
        if ctx is None:
            return JSONResponse({"error": "Node not found"}, status_code=404)
        return ctx
    except Exception as e:
        logger.exception("Node context lookup failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/node/{node_id}/blast-radius")
async def get_node_blast_radius(
    node_id: str,
    depth: int = Query(2, ge=1, le=5, description="Neighborhood depth"),
) -> dict:
    """Get blast radius / impact analysis from the stored graph."""
    try:
        from agenticops.graph.store import GraphStore
        from agenticops.graph.algorithms import dependency_chain_analysis

        store = GraphStore()
        graph = store.get_node_neighborhood(node_id, depth=depth)
        if node_id not in graph.graph:
            return JSONResponse({"error": "Node not found"}, status_code=404)

        result = dependency_chain_analysis(graph, node_id)
        return result.model_dump()
    except Exception as e:
        logger.exception("Blast radius analysis failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/stats")
async def get_graph_stats() -> dict:
    """Get graph statistics: node/edge counts, last sync, staleness."""
    try:
        from sqlalchemy import text
        from agenticops.models import get_engine
        from agenticops.config import settings

        engine = get_engine()
        with engine.connect() as conn:
            node_count = conn.execute(text("SELECT COUNT(*) FROM graph_nodes")).scalar() or 0
            edge_count = conn.execute(text("SELECT COUNT(*) FROM graph_edges")).scalar() or 0

            # Counts by type
            type_rows = conn.execute(
                text("SELECT node_type, COUNT(*) as cnt FROM graph_nodes GROUP BY node_type ORDER BY cnt DESC")
            ).fetchall()
            type_counts = {r[0]: r[1] for r in type_rows}

            # Last sync
            last_snapshot = conn.execute(
                text("SELECT scope, snapshot_at, node_count, edge_count, nodes_added, nodes_updated, nodes_removed "
                     "FROM graph_snapshots ORDER BY id DESC LIMIT 1")
            ).fetchone()

            last_sync = None
            if last_snapshot:
                last_sync = {
                    "scope": last_snapshot[0],
                    "snapshot_at": last_snapshot[1],
                    "node_count": last_snapshot[2],
                    "edge_count": last_snapshot[3],
                    "nodes_added": last_snapshot[4],
                    "nodes_updated": last_snapshot[5],
                    "nodes_removed": last_snapshot[6],
                }

            # Stale nodes count
            from datetime import datetime, timedelta, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings.graph_node_ttl_hours)).strftime("%Y-%m-%d %H:%M:%S")
            stale_count = conn.execute(
                text("SELECT COUNT(*) FROM graph_nodes WHERE updated_at < :cutoff"),
                {"cutoff": cutoff},
            ).scalar() or 0

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "type_counts": type_counts,
            "last_sync": last_sync,
            "stale_node_count": stale_count,
            "graph_sync_enabled": settings.graph_sync_enabled,
            "graph_sync_interval_minutes": settings.graph_sync_interval_minutes,
            "graph_node_ttl_hours": settings.graph_node_ttl_hours,
        }
    except Exception as e:
        logger.exception("Graph stats failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/diff")
async def get_graph_diff(
    limit: int = Query(10, ge=1, le=50, description="Number of recent snapshots"),
) -> list[dict]:
    """Compare recent graph snapshots to show sync history."""
    try:
        from sqlalchemy import text
        from agenticops.models import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, scope, snapshot_at, node_count, edge_count, "
                    "nodes_added, nodes_updated, nodes_removed "
                    "FROM graph_snapshots ORDER BY id DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()

        return [
            {
                "id": r[0],
                "scope": r[1],
                "snapshot_at": r[2],
                "node_count": r[3],
                "edge_count": r[4],
                "nodes_added": r[5],
                "nodes_updated": r[6],
                "nodes_removed": r[7],
            }
            for r in rows
        ]
    except Exception as e:
        logger.exception("Graph diff failed")
        return JSONResponse({"error": str(e)}, status_code=500)
