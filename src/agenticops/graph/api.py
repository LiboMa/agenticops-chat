"""Graph API endpoints — FastAPI router for graph-based topology queries."""

from __future__ import annotations

import json
import logging
from typing import Optional

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
    """Pre-warm a registered-account session for the region (default account).

    Graph collectors resolve credentials through the same provider layer
    (account-addressed, fail-closed). This only pre-warms the cache for the
    single enabled AWS account; if more than one is enabled it logs and lets
    the per-call resolution surface the ambiguity. Multi-account graph sync is
    a follow-up.
    """
    from agenticops.credentials.resolver import (
        resolve_default_account,
        resolve_account_session,
        AccountResolutionError,
    )

    try:
        snap = resolve_default_account("aws")
        resolve_account_session(snap, region)
    except AccountResolutionError as e:
        logger.debug("graph API: %s", e)
    except Exception:
        logger.debug("Failed to resolve AWS session for graph API", exc_info=True)


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


@router.get("/node/{ref}/context")
def get_node_context(ref: int) -> dict:
    """One-hop neighborhood of a cloud_resources row over the published relation layer."""
    from agenticops.graph import query_service as qs
    from agenticops.models import CloudResource, get_db_session

    with get_db_session() as s:
        if s.get(CloudResource, ref) is None:
            return JSONResponse({"error": "Resource not found"}, status_code=404)
        return qs.neighborhood(ref, depth=1, session=s).to_dict()


@router.get("/node/{ref}/blast-radius")
def get_node_blast_radius(ref: int, depth: int = Query(3, ge=1, le=3)) -> dict:
    """Potential impact: everything downstream of the resource over rule relations."""
    from agenticops.graph import query_service as qs
    from agenticops.models import CloudResource, get_db_session

    with get_db_session() as s:
        if s.get(CloudResource, ref) is None:
            return JSONResponse({"error": "Resource not found"}, status_code=404)
        data = qs.potential_impact(ref, depth=depth, session=s).to_dict()
    data["count"] = max(len(data["nodes"]) - 1, 0)
    return data


def _union(subs: list):
    """Merge per-start subgraphs: a node keeps its smallest hop count, an edge its first occurrence."""
    from agenticops.graph.query_service import Subgraph

    nodes, edges, reasons = {}, {}, set()
    for sub in subs:
        for n in sub.nodes:
            if n["ref"] not in nodes or n["hops"] < nodes[n["ref"]]["hops"]:
                nodes[n["ref"]] = n
        for e in sub.edges:
            edges.setdefault((e["src"], e["dst"], e["relation_type"], e["provenance"]), e)
        reasons.update((sub.truncated_reason or "").split("+"))
    order = [r for r in ("expansion_cap", "node_cap", "edge_cap") if r in reasons]
    return Subgraph(build_id=None,
                    nodes=sorted(nodes.values(), key=lambda n: (n["hops"], n["ref"])),
                    edges=[edges[k] for k in sorted(edges)],
                    truncated=any(sub.truncated for sub in subs),
                    truncated_reason="+".join(order) or None)


def _blast_count(subs: list, starts: list) -> int:
    return len({n["ref"] for sub in subs for n in sub.nodes} - set(starts))


def _focus_subject(s, issue_id, resource_id, change_request_id):
    """(starts, anchor, window_center, issue_type, subject_account_id), or a 404 response."""
    from datetime import datetime, timezone

    from agenticops.models import ChangeRequest, CloudResource, HealthIssue
    from agenticops.services import identity_resolver as ir

    now = datetime.now(timezone.utc)
    if issue_id is not None:
        issue = s.get(HealthIssue, issue_id)
        if issue is None:
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        audit = issue.anchor_candidates if isinstance(issue.anchor_candidates, dict) else {}
        starts = [issue.resource_ref] if issue.resource_ref else []
        anchor = {"kind": "issue", "id": issue_id,
                  "status": issue.anchor_status or (ir.ANCHORED if starts else ir.UNANCHORED),
                  "rule": audit.get("rule"), "candidates": audit.get("candidates") or []}
        center = issue.observed_at or issue.first_seen or issue.detected_at or now
        return starts, anchor, center, issue.issue_type, issue.account_id
    if resource_id is not None:
        row = s.get(CloudResource, resource_id)
        if row is None:
            return JSONResponse({"error": "Resource not found"}, status_code=404)
        anchor = {"kind": "resource", "id": resource_id, "status": ir.ANCHORED, "rule": None, "candidates": []}
        return [resource_id], anchor, now, None, row.account_id
    cr = s.get(ChangeRequest, change_request_id)
    if cr is None:
        return JSONResponse({"error": "Change request not found"}, status_code=404)
    starts = sorted({t["db_id"] for t in (cr.target_resources or [])
                     if isinstance(t, dict) and isinstance(t.get("db_id"), int)})
    anchor = {"kind": "change_request", "id": change_request_id,
              "status": ir.ANCHORED if starts else ir.UNANCHORED, "rule": None, "candidates": []}
    return starts, anchor, now, None, cr.account_id


@router.get("/focus")
def get_focus(
    issue_id: Optional[int] = Query(None, ge=1),
    resource_id: Optional[int] = Query(None, ge=1, description="cloud_resources.id"),
    change_request_id: Optional[int] = Query(None, ge=1),
    depth: int = Query(1, ge=1),
    node_cap: Optional[int] = Query(None, ge=1, le=10000),
    edge_cap: Optional[int] = Query(None, ge=1, le=50000),
    include_llm: bool = Query(False),
) -> dict:
    """Local graph around an issue's anchor, a resource, or a change request's resolved targets (spec §3.A.4).

    Display layer: neighborhood() over the issue class's default relations, one call per start, unioned
    (node_cap applies per start); include_llm adds llm edges plus the display-only types (references,
    inferred_group). Blast radius, three layers (spec §3.E.3): structural = every rule
    relation within 2 hops both ways; potential = potential_impact; observed = observed_impact over the
    RCA topology window. Counts exclude the starts. A start whose row is gone or belongs to another
    account than the subject is dropped (SQLite does not enforce ON DELETE SET NULL)."""
    from datetime import timedelta

    from sqlalchemy import select

    from agenticops.config import settings
    from agenticops.graph import query_service as qs
    from agenticops.graph.relations import NONE, PROPAGATION, default_relations
    from agenticops.models import CloudResource, get_db_session
    from agenticops.services import identity_resolver as ir

    if sum(x is not None for x in (issue_id, resource_id, change_request_id)) != 1:
        return JSONResponse({"error": "pass exactly one of issue_id, resource_id, change_request_id"},
                            status_code=422)
    depth = min(depth, settings.graph_query_max_depth)
    display_only = tuple(sorted(t for t, p in PROPAGATION.items() if p == NONE))
    with get_db_session() as s:
        subject = _focus_subject(s, issue_id, resource_id, change_request_id)
        if isinstance(subject, JSONResponse):
            return subject
        starts, anchor, center, issue_type, account = subject
        rows = {rid: (rtype, acct) for rid, rtype, acct in s.execute(
            select(CloudResource.id, CloudResource.resource_type, CloudResource.account_id)
            .where(CloudResource.id.in_(starts)))} if starts else {}
        kept = [r for r in starts if r in rows and (account is None or rows[r][1] == account)]
        if starts and not kept:
            anchor.update(status=ir.UNANCHORED, rule="stale_ref")
        starts = anchor["refs"] = kept
        center = qs._naive_utc(center)
        window = (center - timedelta(minutes=settings.rca_topology_window_before_minutes),
                  center + timedelta(minutes=settings.rca_topology_window_after_minutes))
        display, structural, potential, observed = [], [], [], []
        for ref in starts:
            rels = default_relations(issue_type, rows[ref][0]) + (display_only if include_llm else ())
            display.append(qs.neighborhood(ref, depth=depth, relation_types=rels, node_cap=node_cap,
                                           edge_cap=edge_cap, include_llm=include_llm, session=s))
            structural.append(qs.neighborhood(ref, depth=2, node_cap=qs.NODE_CAP_MAX,
                                              edge_cap=qs.EDGE_CAP_MAX, session=s))
            potential.append(qs.potential_impact(ref, session=s))
            observed.append(qs.observed_impact(ref, window=window, session=s))
        build_id = qs.published_build_id(s)
    union = _union(display)
    union.build_id = build_id
    return {**union.to_dict(), "depth": depth, "anchor": anchor,
            "blast": {"structural": _blast_count(structural, starts),
                      "potential": _blast_count(potential, starts),
                      "observed": _blast_count(observed, starts),
                      "truncated": any(sub.truncated for sub in structural + potential + observed)},
            "window": {"start": window[0].isoformat(), "end": window[1].isoformat()}}


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
        from agenticops.graph.store import GraphStore

        return GraphStore().get_recent_snapshots(limit=limit)
    except Exception as e:
        logger.exception("Graph diff failed")
        return JSONResponse({"error": str(e)}, status_code=500)
