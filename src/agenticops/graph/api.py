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
