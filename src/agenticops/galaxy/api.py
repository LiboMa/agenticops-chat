"""Galaxy read/rebuild API. Reads the latest completed build's stored graph and
overlays live HealthIssue status. Mounted at /api/galaxy."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Query, Response

from agenticops.config import settings
from agenticops.models import get_db_session, CloudResource, HealthIssue
from agenticops.galaxy.models import GalaxyBuild
from agenticops.galaxy import builder

router = APIRouter(prefix="/api/galaxy", tags=["galaxy"])

_SEVERITY_HEALTH = {"critical": "critical", "high": "warning", "medium": "warning", "low": "healthy"}
_HEALTH_RANK = {"healthy": 0, "warning": 1, "critical": 2}


def _health_by_resource_id() -> dict:
    """resource_id (cloud string) -> worst health among open issues."""
    out: dict = {}
    with get_db_session() as s:
        rows = s.query(HealthIssue.resource_id, HealthIssue.severity).filter(
            HealthIssue.status != "resolved").all()
    for rid, sev in rows:
        h = _SEVERITY_HEALTH.get((sev or "").lower(), "healthy")
        if _HEALTH_RANK[h] > _HEALTH_RANK.get(out.get(rid, "healthy"), 0):
            out[rid] = h
    return out


def _latest_completed(s) -> Optional[GalaxyBuild]:
    return (s.query(GalaxyBuild).filter_by(status="completed")
            .order_by(GalaxyBuild.id.desc()).first())


def _build_dict(b: GalaxyBuild) -> dict:
    return {
        "id": b.id, "status": b.status, "trigger": b.trigger, "full": b.full,
        "started_at": b.started_at.isoformat() if b.started_at else None,
        "finished_at": b.finished_at.isoformat() if b.finished_at else None,
        "node_count": b.node_count, "edge_count": b.edge_count,
        "dropped_edge_count": b.dropped_edge_count, "cost_usd": b.cost_usd,
        "input_tokens": b.input_tokens, "output_tokens": b.output_tokens,
        "error": b.error,
    }


@router.post("/rebuild")
async def rebuild(response: Response, full: bool = Query(False)):
    with get_db_session() as s:
        running = s.query(GalaxyBuild).filter_by(status="running").first()
        if running:
            response.status_code = 409
            return {"detail": f"build {running.id} already running"}
    # build_graph is fully blocking (sqlite + blocking Bedrock converse). This is an
    # async endpoint, so run it in a worker thread to avoid freezing the event loop
    # (matches the codebase pattern, e.g. app.py `await asyncio.to_thread(...)`).
    # Awaiting the result keeps the returned id = the actual completed build, which the
    # tests rely on; the single 'running' row guards against overlap.
    build_id = await asyncio.to_thread(builder.build_graph, "manual", full)
    response.status_code = 202
    return {"build_id": build_id}


@router.get("/status")
async def status():
    with get_db_session() as s:
        latest = (s.query(GalaxyBuild).order_by(GalaxyBuild.id.desc()).first())
        build = _build_dict(latest) if latest else None
    return {"build": build, "next_check_minutes": settings.galaxy_build_interval_minutes}


def _resource_ids_by_node(s) -> dict:
    """node_id -> cloud resource_id string (for health join)."""
    return {f"res:{r.id}": r.resource_id for r in s.query(CloudResource.id, CloudResource.resource_id).all()}


@router.get("/overview")
async def overview():
    with get_db_session() as s:
        latest = _latest_completed(s)
        if latest is None:
            return {"nodes": [], "edges": [], "build_id": None}
        rule = latest.rule_graph or {}
        nodes = rule.get("nodes", [])
        edges = rule.get("edges", [])
        build_id = latest.id  # capture inside session (avoid DetachedInstanceError after close)
        node_res_id = _resource_ids_by_node(s)
    health = _health_by_resource_id()

    # Each resource counts toward its ACCOUNT (exactly one, from the node's own
    # account_id) AND every GROUP it is a member_of (zero or more). Do NOT use a
    # single containment parent — a resource nested under a VPC still belongs to
    # its account and tag-groups, so single-parent bucketing loses those counts.
    groups_of: dict = {}  # resource node id -> set of group node ids
    for e in edges:
        if e["relation_type"] == "member_of" and e["target"].startswith("grp:"):
            groups_of.setdefault(e["source"], set()).add(e["target"])

    top_nodes = [n for n in nodes if n["kind"] in ("account", "group")]
    counts: dict = {n["id"]: {"resource_count": 0, "open_issues": 0, "health": "healthy",
                              "types": {}} for n in top_nodes}

    def _bump(container_id: str, node: dict, h: str) -> None:
        c = counts.get(container_id)
        if c is None:
            return
        c["resource_count"] += 1
        c["types"][node["resource_type"]] = c["types"].get(node["resource_type"], 0) + 1
        if h != "healthy":
            c["open_issues"] += 1
        if _HEALTH_RANK[h] > _HEALTH_RANK[c["health"]]:
            c["health"] = h

    for n in nodes:
        if n["kind"] != "resource":
            continue
        h = health.get(node_res_id.get(n["id"]), "healthy")
        if n.get("account_id") is not None:
            _bump(f"acct:{n['account_id']}", n, h)
        for gnode in groups_of.get(n["id"], ()):
            _bump(gnode, n, h)

    out_nodes = []
    for n in top_nodes:
        c = counts[n["id"]]
        out_nodes.append({**n, "resource_count": c["resource_count"], "open_issues": c["open_issues"],
                          "health": c["health"], "types": c["types"]})
    # Group-level edges among top nodes only (account contains group is implicit; keep empty for PoC overview).
    return {"nodes": out_nodes, "edges": [], "build_id": build_id}


@router.get("/expand")
async def expand(group: str = Query(...), types: Optional[str] = None, health: str = "all"):
    type_filter = {t for t in (types or "").split(",") if t} or None
    with get_db_session() as s:
        latest = _latest_completed(s)
        if latest is None:
            return {"nodes": [], "edges": [], "truncated": False}
        rule = latest.rule_graph or {}
        llm_edges = (latest.llm_graph or {}).get("edges", [])
        nodes = rule.get("nodes", [])
        rule_edges = rule.get("edges", [])
        node_res_id = _resource_ids_by_node(s)
    health_map = _health_by_resource_id()

    # Members of the requested group/account.
    member_ids = set()
    for e in rule_edges:
        if e["source"] == group and e["relation_type"] == "contains" and e["target"].startswith("res:"):
            member_ids.add(e["target"])
        if e["target"] == group and e["relation_type"] == "member_of":
            member_ids.add(e["source"])

    node_by_id = {n["id"]: n for n in nodes}
    members = []
    for nid in member_ids:
        n = node_by_id.get(nid)
        if not n:
            continue
        if type_filter and n["resource_type"] not in type_filter:
            continue
        rid = node_res_id.get(nid)
        h = health_map.get(rid, "healthy")
        if health == "worst" and h == "healthy":
            continue
        members.append({**n, "health": h})

    # Truncate by open-issue priority (unhealthy first), then name.
    cap = settings.galaxy_expand_node_cap
    truncated = len(members) > cap
    members.sort(key=lambda m: (-_HEALTH_RANK[m["health"]], m["name"]))
    members = members[:cap]
    kept_ids = {m["id"] for m in members}

    out_edges = [e for e in (rule_edges + llm_edges)
                 if e["source"] in kept_ids and e["target"] in kept_ids]
    return {"nodes": members, "edges": out_edges, "truncated": truncated}


@router.get("/graph")
async def graph():
    """Full starfield payload: every node (slim, health-overlaid) + all rule+llm edges.

    Feeds the Canvas force-directed 'galaxy' view, which lays out and renders the
    entire inventory at once (client-side). Slimmed to keep the payload small.
    """
    with get_db_session() as s:
        latest = _latest_completed(s)
        if latest is None:
            return {"nodes": [], "edges": [], "build_id": None}
        rule = latest.rule_graph or {}
        llm = latest.llm_graph or {}
        raw_nodes = rule.get("nodes", [])
        rule_edges = rule.get("edges", [])
        llm_edges = llm.get("edges", [])
        build_id = latest.id
        node_res_id = _resource_ids_by_node(s)
    health = _health_by_resource_id()

    nodes = []
    for n in raw_nodes:
        slim = {"id": n["id"], "kind": n["kind"], "name": (n.get("name") or "")[:60],
                "type": n.get("resource_type") or n.get("group_kind") or "",
                "acct": n.get("account_id")}
        if n["kind"] == "resource":
            slim["health"] = health.get(node_res_id.get(n["id"], ""), "healthy")
        elif n["kind"] == "group":
            slim["members"] = n.get("member_count", 0)
        nodes.append(slim)

    edges = []
    for e in rule_edges:
        edges.append({"s": e["source"], "t": e["target"], "r": e["relation_type"], "p": "rule"})
    for e in llm_edges:
        edges.append({"s": e["source"], "t": e["target"], "r": e["relation_type"], "p": "llm",
                      "ev": (e.get("evidence") or "")[:120], "c": e.get("confidence")})
    return {"nodes": nodes, "edges": edges, "build_id": build_id}
