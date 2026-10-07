"""GraphQueryService — bounded reads over the published relation layer (MVP-2.6.1, spec §3.A.4).

Topology comes from resource_relations of the latest published build: one batched query per hop, cached
in-process per (build_id, parameters). Node rows and the health overlay are read live on every call, so a
cache hit never shows stale issue state. Only nodes in the start resource's account are returned.

SQL per neighborhood(): depth + 2 on a cache miss (published build, one per hop, nodes + health in one),
2 on a hit.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import and_, func, or_, select

from agenticops.config import settings
from agenticops.galaxy.builder import latest_published_id
from agenticops.galaxy.models import ResourceRelation as RR
from agenticops.graph.relations import step
from agenticops.models import AlertEvent, CloudResource, HealthIssue, get_db_session
from agenticops.services.identity_resolver import account_pk
from agenticops.services.signal_gate import OPEN_ISSUE_STATUSES

HEALTH_RANK: dict[str, int] = {"unknown": 0, "notice": 1, "warning": 2, "critical": 3}
_SEVERITY_HEALTH = {"critical": "critical", "high": "warning", "medium": "notice", "low": "notice"}
DIRECTIONS = ("up", "down", "both")
NODE_CAP_MAX = 10000
EDGE_CAP_MAX = 50000
# Refs one expansion may discover. A safety bound, not a display cap; it also keeps the per-hop IN lists
# under SQLite's 32766 bound parameters. Hitting it marks the result truncated ("expansion_cap").
_EXPANSION_CAP = NODE_CAP_MAX
_CACHE_MAX = 256


@dataclass
class Subgraph:
    build_id: Optional[int]
    # {ref, type, name, account_id, region, absent, hops, health, issue_ids, anomalous, signal_at}
    nodes: list = field(default_factory=list)
    # {src, dst, relation_type, provenance, evidence, direction_label, observed_at}
    edges: list = field(default_factory=list)
    truncated: bool = False
    truncated_reason: Optional[str] = None  # "+"-joined: expansion_cap, node_cap, edge_cap

    def to_dict(self) -> dict:
        return {
            "build_id": self.build_id,
            "nodes": [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in n.items()}
                      for n in self.nodes],
            "edges": [dict(e) for e in self.edges],
            "truncated": self.truncated,
            "truncated_reason": self.truncated_reason,
        }


@dataclass
class _Topology:
    hops: dict    # ref -> hops from the start (start = 0)
    via: dict     # ref -> frozenset of refs one hop closer that reached it
    edges: tuple  # (id, src, dst, relation_type, provenance, evidence_text, observed_at), ascending id
    capped: bool


_cache: "OrderedDict[tuple, _Topology]" = OrderedDict()
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


@contextmanager
def _scope(session):
    if session is not None:
        yield session
    else:
        with get_db_session() as s:
            yield s


def published_build_id(session) -> Optional[int]:
    return latest_published_id(session)


def _ts(value) -> float:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # the database stores naive UTC
    return value.timestamp()


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _evidence_text(evidence) -> str:
    return str(evidence.get("text") or "") if isinstance(evidence, dict) else str(evidence or "")


def rank_key(node: dict, changed_refs=frozenset()) -> tuple:
    """Candidate order of spec §3.C.1: anomalous → changed in the window → earlier own signal → fewer hops
    → ref. neighborhood() truncates with no changed refs; Plan C re-ranks with its window's changes."""
    at = node.get("signal_at")
    return (0 if node.get("anomalous") else 1,
            0 if node["ref"] in changed_refs else 1,
            (0, _ts(at)) if at is not None else (1, 0.0),
            node.get("hops", 0),
            node["ref"])


def _fold_health(issues: Iterable[tuple]) -> dict:
    """(issue_id, severity, seen_at) rows of one resource → worst health, issue ids, earliest signal."""
    health, ids, signal_at = "unknown", [], None
    for iid, severity, seen_at in issues:
        h = _SEVERITY_HEALTH.get((severity or "").lower(), "notice")
        if HEALTH_RANK[h] > HEALTH_RANK[health]:
            health = h
        ids.append(iid)
        if seen_at is not None and (signal_at is None or _ts(seen_at) < _ts(signal_at)):
            signal_at = seen_at
    return {"health": health, "issue_ids": sorted(ids), "signal_at": signal_at}


def _pod_anomalous(pod_summary) -> bool:
    if not isinstance(pod_summary, dict):
        return False
    if pod_summary.get("waiting_reasons") or pod_summary.get("last_termination_reason"):
        return True
    ready, desired = pod_summary.get("ready"), pod_summary.get("desired")
    return isinstance(ready, int) and isinstance(desired, int) and ready < desired


def _issue_seen():
    return (HealthIssue.observed_at, HealthIssue.first_seen, HealthIssue.detected_at)


def health_overlay(session, refs: Optional[Iterable[int]] = None) -> dict[int, dict]:
    """{ref: {health, issue_ids, signal_at}} for refs with an open issue; a missing ref means `unknown`.

    An issue colours a node only when its account matches the resource row's: SQLite does not enforce
    ON DELETE SET NULL, so a stale resource_ref may point at an id another account's row now uses."""
    q = (select(HealthIssue.resource_ref, HealthIssue.id, HealthIssue.severity, *_issue_seen())
         .join(CloudResource, and_(CloudResource.id == HealthIssue.resource_ref,
                                   CloudResource.account_id == HealthIssue.account_id))
         .where(HealthIssue.status.in_(OPEN_ISSUE_STATUSES)))
    if refs is not None:
        q = q.where(HealthIssue.resource_ref.in_(list(refs)))
    grouped: dict[int, list] = {}
    for ref, iid, severity, observed, first, detected in session.execute(q):
        grouped.setdefault(ref, []).append((iid, severity, observed or first or detected))
    return {ref: _fold_health(rows) for ref, rows in grouped.items()}


def _live_nodes(session, refs: list) -> dict[int, dict]:
    """Resource rows plus their open issues, one statement — never cached."""
    q = (select(CloudResource.id, CloudResource.resource_type, CloudResource.name, CloudResource.account_id,
                CloudResource.region, CloudResource.absent_since, CloudResource.raw_data["pod_summary"],
                HealthIssue.id, HealthIssue.severity, *_issue_seen())
         .outerjoin(HealthIssue, and_(HealthIssue.resource_ref == CloudResource.id,
                                      HealthIssue.account_id == CloudResource.account_id,
                                      HealthIssue.status.in_(OPEN_ISSUE_STATUSES)))
         .where(CloudResource.id.in_(refs)))
    rows: dict[int, dict] = {}
    for (rid, rtype, name, acct, region, absent_since, pod_summary,
         iid, severity, observed, first, detected) in session.execute(q):
        row = rows.setdefault(rid, {"ref": rid, "type": rtype, "name": name or "", "account_id": acct,
                                    "region": region, "absent": absent_since is not None,
                                    "pod_summary": pod_summary, "issues": []})
        if iid is not None:
            row["issues"].append((iid, severity, observed or first or detected))
    return rows


def _expand(session, bid: int, ref: int, depth: int, direction: str,
            relation_types: Optional[tuple], include_llm: bool) -> _Topology:
    """BFS over one build's relations, one query per hop. The start's account is a scalar subquery inside
    each hop query, so the same-account rule costs no extra statement."""
    start_account = select(CloudResource.account_id).where(CloudResource.id == ref).scalar_subquery()
    hops, via, rows = {ref: 0}, {ref: frozenset()}, {}
    frontier, capped = {ref}, False
    for hop in range(1, depth + 1):
        q = select(RR.id, RR.src_ref, RR.dst_ref, RR.relation_type, RR.provenance, RR.evidence,
                   RR.observed_at).where(
            RR.build_id == bid, RR.account_id == start_account,
            or_(RR.src_ref.in_(frontier), RR.dst_ref.in_(frontier)))
        if not include_llm:
            q = q.where(RR.provenance == "rule")
        if relation_types is not None:
            q = q.where(RR.relation_type.in_(relation_types))
        found: dict[int, set] = {}
        for rid, src, dst, rtype, prov, evidence, observed in session.execute(q.order_by(RR.id)):
            for near, far, near_is_src in ((src, dst, True), (dst, src, False)):
                if near not in frontier:
                    continue
                down, up = step(rtype, frontier_is_src=near_is_src)
                if (direction == "up" and not up) or (direction == "down" and not down):
                    continue
                rows[rid] = (rid, src, dst, rtype, prov, _evidence_text(evidence), observed)
                if far not in hops:
                    found.setdefault(far, set()).add(near)
        new = sorted(found)
        room = _EXPANSION_CAP - len(hops)
        if len(new) > room:
            new, capped = new[:max(room, 0)], True
        for r in new:
            hops[r], via[r] = hop, frozenset(found[r])
        if capped or not new:
            break
        frontier = set(new)
    return _Topology(hops=hops, via=via, edges=tuple(rows[k] for k in sorted(rows)), capped=capped)


def _topology(session, bid, ref, depth, direction, relation_types, include_llm) -> _Topology:
    key = (bid, ref, depth, direction, relation_types, include_llm)
    with _cache_lock:
        topo = _cache.get(key)
    if topo is None:
        topo = _expand(session, bid, ref, depth, direction, relation_types, include_llm)
        with _cache_lock:
            _cache[key] = topo
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    return topo


def _node(row: dict, hops: int) -> dict:
    h = _fold_health(row["issues"])
    return {"ref": row["ref"], "type": row["type"], "name": row["name"], "account_id": row["account_id"],
            "region": row["region"], "absent": row["absent"], "hops": hops, **h,
            "anomalous": h["health"] != "unknown" or _pod_anomalous(row["pod_summary"])}


def _edge(e: tuple, nodes: dict) -> dict:
    """direction_label: how the end farther from the start relates to the nearer one (dst on a tie)."""
    _, src, dst, rtype, prov, evidence, observed = e
    down, up = step(rtype, frontier_is_src=nodes[src]["hops"] <= nodes[dst]["hops"])
    label = "both" if down and up else "downstream" if down else "upstream" if up else "none"
    return {"src": src, "dst": dst, "relation_type": rtype, "provenance": prov, "evidence": evidence,
            "direction_label": label,
            "observed_at": observed.isoformat() if isinstance(observed, datetime) else observed}


def _assemble(bid: int, start: int, topo: _Topology, live: dict, node_cap: int, edge_cap: int) -> Subgraph:
    origin = live.get(start)
    if origin is None:
        return Subgraph(build_id=bid)
    nodes: dict[int, dict] = {}
    for r in sorted(topo.hops, key=lambda x: (topo.hops[x], x)):
        row = live.get(r)
        if row is None or row["account_id"] != origin["account_id"]:
            continue  # row gone, or the id now belongs to another account
        if r != start and not any(v in nodes for v in topo.via[r]):
            continue  # every path to it ran through a dropped node
        nodes[r] = _node(row, topo.hops[r])
    parent = {r: min(v for v in topo.via[r] if v in nodes) for r in nodes if r != start}

    reasons = ["expansion_cap"] if topo.capped else []
    if len(nodes) > node_cap:
        # Best-ranked first; a node comes with its not-yet-kept parent chain, so a kept abnormal node two
        # hops out is still connected to the start. A chain that no longer fits is skipped, not cut.
        keep = {start}
        for n in sorted((n for r, n in nodes.items() if r != start), key=rank_key):
            if len(keep) >= node_cap:
                break
            chain, r = [], n["ref"]
            while r not in keep:
                chain.append(r)
                r = parent[r]
            if len(keep) + len(chain) <= node_cap:
                keep.update(chain)
        nodes = {r: n for r, n in nodes.items() if r in keep}
        reasons.append("node_cap")

    edges = [e for e in topo.edges if e[1] in nodes and e[2] in nodes]
    if len(edges) > edge_cap:
        # Tree edges (first row between a node and its parent) first, then nearer edges, then row id.
        # A node whose edges are cut stays in the result.
        tree, has_tree = set(), set()
        for e in edges:
            for child, par in ((e[2], e[1]), (e[1], e[2])):
                if parent.get(child) == par and child not in has_tree:
                    has_tree.add(child)
                    tree.add(e[0])

        def importance(e):
            h = (nodes[e[1]]["hops"], nodes[e[2]]["hops"])
            return (0 if e[0] in tree else 1, max(h), min(h), e[0])

        edges = sorted(edges, key=importance)[:edge_cap]
        reasons.append("edge_cap")

    return Subgraph(
        build_id=bid,
        nodes=sorted(nodes.values(), key=lambda n: (n["hops"], n["ref"])),
        edges=sorted((_edge(e, nodes) for e in edges),
                     key=lambda d: (d["src"], d["dst"], d["relation_type"], d["provenance"])),
        truncated=bool(reasons),
        truncated_reason="+".join(reasons) or None,
    )


def neighborhood(ref: int, *, depth: int = 1, direction: str = "both", relation_types=None,
                 node_cap: Optional[int] = None, edge_cap: Optional[int] = None, include_llm: bool = False,
                 session=None) -> Subgraph:
    """Resources within `depth` hops of `ref` in the latest published build, same account only.

    direction: "up" = what ref depends on (root-cause side), "down" = what depends on ref (blast side),
    "both" = every edge, including llm types that do not propagate. relation_types=None means no type
    filter; callers that know the issue pass relations.default_relations(issue_type, anchor_type).
    Callers clamp depth to graph_query_max_depth; caps default to graph_query_node_cap / _edge_cap."""
    if depth < 1:
        raise ValueError(f"depth must be >= 1, got {depth}")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    node_cap = settings.graph_query_node_cap if node_cap is None else node_cap
    edge_cap = settings.graph_query_edge_cap if edge_cap is None else edge_cap
    if node_cap < 1 or edge_cap < 1:
        raise ValueError(f"node_cap and edge_cap must be >= 1, got {node_cap} / {edge_cap}")
    rtypes = None if relation_types is None else tuple(sorted(set(relation_types)))
    with _scope(session) as s:
        bid = published_build_id(s)
        if bid is None:
            return Subgraph(build_id=None)
        topo = _topology(s, bid, ref, depth, direction, rtypes, bool(include_llm))
        live = _live_nodes(s, list(topo.hops))
    return _assemble(bid, ref, topo, live, node_cap, edge_cap)


def potential_impact(ref: int, *, depth: int = 3, session=None) -> Subgraph:
    """Everything downstream of ref over rule relations — the structural blast radius. Capped only by
    NODE_CAP_MAX / EDGE_CAP_MAX: the count must not depend on a display cap."""
    return neighborhood(ref, depth=depth, direction="down", include_llm=False,
                        node_cap=NODE_CAP_MAX, edge_cap=EDGE_CAP_MAX, session=session)


def _observed_refs(session, refs: list, account_id: int, start: datetime, end: datetime) -> set:
    in_window = and_(AlertEvent.received_at >= start, AlertEvent.received_at <= end)
    # (a) a signal in the window linked to an issue anchored on the node
    hit = set(session.scalars(
        select(HealthIssue.resource_ref).join(AlertEvent, AlertEvent.health_issue_id == HealthIssue.id)
        .where(HealthIssue.resource_ref.in_(refs), HealthIssue.account_id == account_id, in_window)))
    # (b) a signal in the window naming the node's resource id — merged and noise signals count too. The
    #     ledger stores the account as a name, a 12-digit number or a key, so it goes through account_pk.
    accounts: dict = {}
    for ref, signal_account in session.execute(
            select(CloudResource.id, AlertEvent.account_id)
            .join(AlertEvent, AlertEvent.resource_id == CloudResource.resource_id)
            .where(CloudResource.id.in_(refs), in_window).distinct()):
        if signal_account not in accounts:
            accounts[signal_account] = account_pk(session, signal_account)
        if accounts[signal_account] == account_id:
            hit.add(ref)
    # (c) an open issue on the node that already existed at the window end
    hit |= set(session.scalars(
        select(HealthIssue.resource_ref).where(
            HealthIssue.resource_ref.in_(refs), HealthIssue.account_id == account_id,
            HealthIssue.status.in_(OPEN_ISSUE_STATUSES), func.coalesce(*_issue_seen()) <= end)))
    return hit


def observed_impact(ref: int, *, window: tuple, session=None) -> Subgraph:
    """Potential-impact nodes that also have their own signal in the window, or an open issue that existed
    by its end (spec §3.A.4). A set, not a path: edges are only those between returned nodes."""
    start, end = (_naive_utc(t) for t in window)
    if start > end:
        raise ValueError("window start is after its end")
    with _scope(session) as s:
        pot = potential_impact(ref, session=s)
        if not pot.nodes:
            return pot
        candidates = [n["ref"] for n in pot.nodes if n["ref"] != ref]
        hit = _observed_refs(s, candidates, pot.nodes[0]["account_id"], start, end) if candidates else set()
    keep = {ref} | hit
    return Subgraph(build_id=pot.build_id,
                    nodes=[n for n in pot.nodes if n["ref"] in keep],
                    edges=[e for e in pot.edges if e["src"] in keep and e["dst"] in keep],
                    truncated=pot.truncated, truncated_reason=pot.truncated_reason)
