"""Graph API endpoints — FastAPI router for graph-based topology queries."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agenticops.graph.algorithms import (
    AnomalyReport,
    ImpactResult,
    PathResult,
    ReachabilityResult,
    can_reach_internet,
    detect_anomalies,
    find_traffic_path,
    impact_analysis,
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


def _build_region_graph(region: str) -> InfraGraph:
    """Build an InfraGraph from a region topology."""
    _ensure_aws_session(region)
    from agenticops.tools.network_tools import describe_region_topology

    raw = describe_region_topology(region=region)
    topo = json.loads(raw)
    return InfraGraph().build_from_region_topology(topo)


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
