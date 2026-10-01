"""RCA topology evidence (MVP-2.6.1 Plan C, spec §3.C.1–3.C.2).

build_evidence(issue_id) assembles what the published relation layer says around an issue's anchor: the
edges (with direction labels), every neighbor's own open issues, signals and changes inside the RCA window,
and deterministic root-cause candidates with their reasons. Every edge and node carries an evidence ref
(`graph:edge:<src>><dst>:<relation_type>`, `graph:node:<ref>`); save_rca_result cites it with evidence type
`graph`, so the post-RCA evidence check grounds it in this tool's output.

A K8s-side anchor (a cluster row or a K8s entity) whose cluster was last collected more than
rca_k8s_recollect_min_age_seconds ago is recollected first: one bounded K8s connector run for that cluster
(trigger rca), then a rule-only graph refresh when the structure changed. The anchor is read, and the
evidence assembled, in two separate sessions around it — an open read transaction would hold SQLite's
shared lock against the recollect's writes. A failed recollect marks the evidence stale and goes on with
the data at hand. No LLM; nothing else is written.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from strands import tool

from agenticops.config import settings
from agenticops.galaxy.rules import short_id
from agenticops.graph import query_service as qs
from agenticops.graph.relations import default_relations
from agenticops.models import (ChangeRequest, CloudAccount, CloudResource, FixExecution, FixPlan, HealthIssue,
                               get_db_session)
from agenticops.services import identity_resolver as ir

logger = logging.getLogger(__name__)

EDGE_PREFIX = "graph:edge:"
NODE_PREFIX = "graph:node:"
# One hop around these reaches only child containers, not workloads: they default to two (spec §3.C.1).
CONTAINER_TYPES = frozenset({"EKS", "EKS_Cluster", "K8s_Namespace", "VPC"})
_CLUSTER_TYPES = frozenset({"EKS", "EKS_Cluster"})
K8S_CONNECTOR = "k8s"


def edge_ref(src: int, dst: int, relation_type: str) -> str:
    return f"{EDGE_PREFIX}{src}>{dst}:{relation_type}"


def node_ref(ref: int) -> str:
    return f"{NODE_PREFIX}{ref}"


def _iso(value) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


def _when(value) -> Optional[datetime]:
    """A stored timestamp (naive UTC datetime, or an ISO string such as K8s creationTimestamp) → naive UTC."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return qs._naive_utc(value) if isinstance(value, datetime) else None


# ── phase 1: the anchor ──────────────────────────────────────────────


def _subject(issue_id: int) -> dict:
    """Plain data about the issue and its anchor row; no ORM object leaves the session."""
    with get_db_session() as s:
        issue = s.get(HealthIssue, issue_id)
        if issue is None:
            return {"missing": True}
        audit = issue.anchor_candidates if isinstance(issue.anchor_candidates, dict) else {}
        subject = {"missing": False, "issue_type": issue.issue_type, "account_id": issue.account_id,
                   "center": issue.observed_at or issue.first_seen or issue.detected_at or datetime.now(timezone.utc),
                   "status": issue.anchor_status or (ir.ANCHORED if issue.resource_ref else ir.UNANCHORED),
                   "anchor_candidates": audit.get("candidates") or [], "row": None}
        row = s.get(CloudResource, issue.resource_ref) if issue.resource_ref else None
        if row is not None and (issue.account_id is None or row.account_id == issue.account_id):
            account = s.get(CloudAccount, row.account_id)
            subject["row"] = {"ref": row.id, "type": row.resource_type, "name": row.name or "",
                              "provider": row.provider, "resource_id": row.resource_id,
                              "account_id": row.account_id, "account_name": account.name if account else "",
                              "cluster": (row.raw_data or {}).get("cluster"), "scanned_at": row.scanned_at}
        return subject


def _k8s_scope(row: dict) -> Optional[str]:
    """The K8s connector scope (cluster name) an anchor belongs to, or None when it is not K8s-side."""
    if row["provider"] == "kubernetes":
        return row["cluster"] or None
    if row["type"] in _CLUSTER_TYPES:
        return short_id(row["resource_id"]) or None
    return None


def _recollect(row: dict, scope: str) -> tuple[Optional[datetime], str, bool]:
    """(last successful collection of the cluster, note, ok). Runs the connector only when that collection is
    older than rca_k8s_recollect_min_age_seconds — which also rate-limits RCAs on the same cluster. ok = the
    data is current: that collection was recent enough, or the recollect was complete or partial and any graph
    refresh after it succeeded. Otherwise the evidence is stale, however recent the last success was."""
    from agenticops.connectors import ingest, runner

    with get_db_session() as s:
        last = ingest.last_success_at(s, K8S_CONNECTOR, row["account_id"], scope)
    if last is not None and (datetime.now(timezone.utc) - last).total_seconds() < \
            settings.rca_k8s_recollect_min_age_seconds:
        return last, "", True
    if not row["account_name"]:  # run_connector reads account="" as every account
        return last, f"recollect of cluster {scope} skipped — the anchor row has no account", False
    try:
        res = runner.run_connector(K8S_CONNECTOR, account=row["account_name"], scope=scope, trigger="rca",
                                   timeout_seconds=settings.rca_k8s_recollect_timeout_seconds)
    except Exception as exc:  # the RCA goes on with the data at hand
        logger.warning("rca recollect of cluster %s failed: %s", scope, exc)
        note, ok = f"recollect of cluster {scope} failed — {type(exc).__name__}: {exc}", False
    else:
        errors = "; ".join(t.error for t in res.targets if t.error)
        note = "" if res.status == "complete" else \
            f"recollect of cluster {scope} was {res.status}" + (f" — {errors}" if errors else "")
        ok = res.status in ("complete", "partial")
        if res.changed and settings.galaxy_enabled:
            try:
                from agenticops.galaxy.builder import build_graph

                build_graph(trigger="rca-recollect", full=False, llm=False)
            except Exception as exc:
                logger.warning("rca recollect graph refresh failed: %s", exc)
                note = "; ".join(filter(None, [note, f"graph refresh after the recollect failed — {exc}"]))
                ok = False
    with get_db_session() as s:
        return ingest.last_success_at(s, K8S_CONNECTOR, row["account_id"], scope), note, ok


def _freshness(collected_at, window_start: datetime, note: str, what: str) -> dict:
    """fresh = the data was collected no earlier than the window start."""
    at = _when(collected_at)
    if at is None:
        return {"status": "stale", "reason": "; ".join(filter(None, [note, f"{what} never collected"])),
                "collected_at": None}
    if at >= window_start:
        return {"status": "fresh", "reason": note, "collected_at": at.isoformat()}
    return {"status": "stale", "collected_at": at.isoformat(), "reason": "; ".join(filter(None, [
        note, f"{what} last collected at {at.isoformat()}, before the window start {window_start.isoformat()}"]))}


# ── phase 2: the evidence ────────────────────────────────────────────


def _facts(s, refs: list) -> dict[int, dict]:
    q = select(CloudResource.id, CloudResource.raw_data["created_at"], CloudResource.raw_data["pod_summary"],
               CloudResource.content_changed_at, CloudResource.absent_since).where(CloudResource.id.in_(refs))
    return {rid: {"created_at": created, "pod_summary": pods, "content_changed_at": changed, "absent_since": absent}
            for rid, created, pods, changed, absent in s.execute(q)}


def _executions(s, refs: list, account_id: int, start: datetime, end: datetime) -> dict[int, list]:
    """Our own executions that started in the window, per targeted ref: a fix plan targets its issue's
    anchor, a change plan its request's resolved targets."""
    q = (select(FixExecution.id, FixExecution.started_at, FixExecution.status, FixPlan.id, FixPlan.plan_kind,
                HealthIssue.resource_ref, HealthIssue.account_id, ChangeRequest.target_resources,
                ChangeRequest.account_id)
         .join(FixPlan, FixPlan.id == FixExecution.fix_plan_id)
         .outerjoin(HealthIssue, HealthIssue.id == FixPlan.health_issue_id)
         .outerjoin(ChangeRequest, ChangeRequest.id == FixPlan.change_request_id)
         .where(FixExecution.started_at >= start, FixExecution.started_at <= end)
         .order_by(FixExecution.id))
    wanted, out = set(refs), {}
    for eid, at, status, pid, kind, issue_ref, issue_acct, targets, cr_acct in s.execute(q):
        if kind == "change":
            hit = {t.get("db_id") for t in targets or [] if isinstance(t, dict)} if cr_acct == account_id else set()
        else:
            hit = {issue_ref} if issue_acct == account_id else set()
        for ref in hit & wanted:
            out.setdefault(ref, []).append({"kind": "execution", "at": _iso(at),
                                            "detail": f"{kind} plan #{pid}, execution #{eid} ({status})"})
    return out


def _changes(fact: dict, executions: list, start: datetime, end: datetime) -> list:
    out = [{"kind": kind, "at": at.isoformat()}
           for kind, at in (("created", _when(fact.get("created_at"))),
                            ("content_changed", _when(fact.get("content_changed_at"))),
                            ("absent", _when(fact.get("absent_since"))))
           if at is not None and start <= at <= end]
    return sorted(out + executions, key=lambda c: (c["at"], c["kind"]))


def _reasons(node: dict, fact: dict, changes: list, observed: bool) -> list[str]:
    out = []
    if node["issue_ids"]:
        out.append(f"open issue {', '.join(f'#{i}' for i in node['issue_ids'])} ({node['health']})")
    pods = fact.get("pod_summary")
    if isinstance(pods, dict):
        if pods.get("waiting_reasons"):
            out.append("pods waiting: " + ", ".join(str(r) for r in pods["waiting_reasons"]))
        if pods.get("last_termination_reason"):
            out.append(f"last pod termination: {pods['last_termination_reason']}")
        ready, desired = pods.get("ready"), pods.get("desired")
        if isinstance(ready, int) and isinstance(desired, int) and ready < desired:
            out.append(f"{ready}/{desired} pods ready")
    out += [f"{c['kind']} at {c['at']}" + (f": {c['detail']}" if c.get("detail") else "") for c in changes]
    if observed and not node["issue_ids"]:
        out.append("own signal in the window")
    if node["signal_at"] is not None:
        out.append(f"first signal at {_iso(node['signal_at'])}")
    out.append("the anchor itself" if node["hops"] == 0 else f"{node['hops']} hop(s) from the anchor")
    return out


def _unavailable(reason: str, detail: str, **extra) -> dict:
    return {"available": False, "reason": reason, "detail": detail, **extra}


def build_evidence(issue_id: int, *, depth: Optional[int] = None, window_minutes: Optional[int] = None) -> dict:
    """The evidence package of spec §3.C.1 for one issue (see the module docstring)."""
    subject = _subject(issue_id)
    if subject["missing"]:
        return _unavailable("issue_not_found", f"issue #{issue_id} does not exist")
    status, row = subject["status"], subject["row"]
    if status == ir.AMBIGUOUS:
        return _unavailable(status, "the signal matched several resources, so the graph cannot pick one; this is "
                            "not 'no problem found' — investigate the listed candidates",
                            anchor_status=status, anchor_candidates=subject["anchor_candidates"])
    if status != ir.ANCHORED:
        return _unavailable(status, "the issue is not anchored to one resource, so the graph cannot speak for it; "
                            "this is not 'no problem found'", anchor_status=status)
    if row is None:
        return _unavailable("stale_ref", "the anchored resource row is gone or belongs to another account",
                            anchor_status=status)

    center = qs._naive_utc(subject["center"])
    before = window_minutes if window_minutes is not None and window_minutes >= 1 else \
        settings.rca_topology_window_before_minutes
    start = center - timedelta(minutes=before)
    end = center + timedelta(minutes=settings.rca_topology_window_after_minutes)
    scope = _k8s_scope(row)
    if scope is not None:
        collected_at, note, ok = _recollect(row, scope)
        freshness = _freshness(collected_at, start, note, f"cluster {scope}")
        if not ok:
            freshness["status"] = "stale"
    else:
        freshness = _freshness(row["scanned_at"], start, "", "the anchored resource")
    if depth is None:
        depth = 2 if row["type"] in CONTAINER_TYPES else 1
    depth = max(1, min(depth, settings.graph_query_max_depth))
    window = {"start": start.isoformat(), "end": end.isoformat()}
    anchor = {"ref": row["ref"], "type": row["type"], "name": row["name"], "anchor_status": status,
              "evidence_ref": node_ref(row["ref"])}

    with get_db_session() as s:
        if qs.published_build_id(s) is None:
            return _unavailable("no_published_build", "no graph build has been published yet", anchor=anchor,
                                freshness=freshness, window=window)
        sub = qs.neighborhood(row["ref"], depth=depth, relation_types=default_relations(
            subject["issue_type"], row["type"]), session=s)
        refs = [n["ref"] for n in sub.nodes]
        facts = _facts(s, refs) if refs else {}
        executions = _executions(s, refs, row["account_id"], start, end) if refs else {}
        observed = qs._observed_refs(s, refs, row["account_id"], start, end) if refs else set()

    names = {n["ref"]: n["name"] for n in sub.nodes}
    views, changed = {}, set()
    for n in sub.nodes:
        changes = _changes(facts.get(n["ref"], {}), executions.get(n["ref"], []), start, end)
        if changes:
            changed.add(n["ref"])
        views[n["ref"]] = {"ref": n["ref"], "type": n["type"], "name": n["name"], "hops": n["hops"],
                           "health": n["health"], "issue_ids": n["issue_ids"], "signal_at": _iso(n["signal_at"]),
                           "anomalous": n["anomalous"], "absent": n["absent"],
                           "observed_in_window": n["ref"] in observed, "changes": changes,
                           "evidence_ref": node_ref(n["ref"])}
    ranked = sorted((n for n in sub.nodes if n["anomalous"] or n["ref"] in changed or n["ref"] in observed),
                    key=lambda n: qs.rank_key(n, frozenset(changed)))
    if row["ref"] in views:
        anchor.update({k: views[row["ref"]][k] for k in ("health", "issue_ids", "changes", "absent")})
    return {
        "available": True,
        "anchor": anchor,
        "build_id": sub.build_id,
        "depth": depth,
        "window": window,
        "edges": [{"src": e["src"], "src_name": names.get(e["src"], ""), "dst": e["dst"],
                   "dst_name": names.get(e["dst"], ""), "relation_type": e["relation_type"],
                   "direction_label": e["direction_label"], "provenance": e["provenance"],
                   "evidence": e["evidence"], "evidence_ref": edge_ref(e["src"], e["dst"], e["relation_type"])}
                  for e in sub.edges],
        "neighbors": [v for r, v in views.items() if r != row["ref"]],
        "candidates": [{"rank": i, "ref": n["ref"], "type": n["type"], "name": n["name"], "absent": n["absent"],
                        "reasons": _reasons(n, facts.get(n["ref"], {}), views[n["ref"]]["changes"],
                                            n["ref"] in observed),
                        "evidence_ref": node_ref(n["ref"])} for i, n in enumerate(ranked, 1)],
        "truncated": sub.truncated,
        "truncated_reason": sub.truncated_reason,
        "freshness": freshness,
    }


@tool
def get_topology_evidence(issue_id: int, depth: Optional[int] = None, window_minutes: Optional[int] = None) -> str:
    """Topology evidence around an issue's anchored resource, read from the published relation graph.

    Returns JSON: the anchor; edges with direction_label (upstream = the far end is something the near end
    depends on, i.e. the root-cause side; downstream = the blast side); neighbors with their own open issues,
    signals and changes (created / content_changed / absent / our executions) inside the time window; ranked
    root-cause candidates with reasons; build_id, truncated and freshness. Cite an edge or a candidate in
    save_rca_result as evidence type "graph" with its evidence_ref as the ref, and pass
    location.build_id = build_id. available=false says why the graph cannot speak for this issue — it never
    means "no problem found".

    Args:
        issue_id: The HealthIssue id.
        depth: Hops around the anchor. Default 1, or 2 when the anchor is a container (a cluster, a
            namespace, a network); capped at the configured maximum.
        window_minutes: Minutes before the issue's observed time to search for changes and signals
            (default from config); the window always runs the configured minutes past it.
    """
    try:
        return json.dumps(build_evidence(issue_id, depth=depth, window_minutes=window_minutes), default=str)
    except Exception as exc:  # a broken evidence read must not end the RCA
        logger.exception("get_topology_evidence(%s) failed", issue_id)
        return json.dumps(_unavailable("error", f"{type(exc).__name__}: {exc}"))
