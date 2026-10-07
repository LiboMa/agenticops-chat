"""Galaxy build pipeline: diff -> L1 rules -> publish rule relations -> L2 index -> L3 LLM enrichment
-> fail-closed verification -> merge/stabilize -> persist.

Runs synchronously (call inside a background task / thread). Concurrency guard:
a single 'running' GalaxyBuild row acts as the lock — a second normal build is a no-op.
The rule layer is published to resource_relations before the LLM phase (MVP-2.6.1). A rule-only refresh
(llm=False) takes no running row; it shares _RULE_LOCK with the normal build's rule phase.
"""

import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Optional

from agenticops.config import settings, get_bedrock_boto_session
from agenticops.cost import compute_cost
from agenticops.models import get_db_session, CloudResource
from agenticops.galaxy.models import GalaxyBuild, GalaxyResourceState, GalaxyGroup, ResourceRelation
from agenticops.galaxy import hashing
from agenticops.galaxy import rules

logger = logging.getLogger(__name__)

PROMPT_VERSION = "galaxy-v1"
# Triggers that refresh the rule layer only (spec §3.A.3 ④): K8s discovery (Plan B), RCA re-collect (Plan C).
RULE_ONLY_TRIGGERS = frozenset({"k8s-discovery", "rca-recollect"})
# Serialises rule derivation + publication: the normal build's rule phase and every rule-only refresh.
# In-process only; across processes the running row still keeps normal builds apart.
_RULE_LOCK = threading.Lock()


def _model_id() -> str:
    return settings.galaxy_model_id or settings.bedrock_model_id_cheap


def _load_resources(session) -> list:
    """Load all cloud resources as plain dicts (detached from ORM)."""
    out = []
    for r in session.query(CloudResource).all():
        out.append({
            "id": r.id, "account_id": r.account_id, "provider": r.provider,
            "region": r.region, "resource_type": r.resource_type,
            "resource_id": r.resource_id, "name": r.name or r.resource_id,
            "tags": r.tags if isinstance(r.tags, dict) else {},
            "raw_data": r.raw_data if isinstance(r.raw_data, dict) else {},
            "scanned_at": r.scanned_at, "absent_since": r.absent_since,
        })
    return out


def _compact_index(resources: list) -> str:
    """L2 global index: one compact line per resource (~40 tok), given to every batch."""
    lines = []
    for r in resources:
        tags = r["tags"]
        tag_str = ",".join(f"{k}={v}" for k, v in list(tags.items())[:6]) if isinstance(tags, dict) else ""
        lines.append(f"{rules.resource_node_id(r['id'])} {r['resource_type']} name={r['name']} tags=[{tag_str}]")
    return "\n".join(lines)


def _batches(resources: list, size: int) -> list:
    """Locality batches: group by (account_id, region) then chunk to <= size."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in resources:
        buckets[(r["account_id"], r["region"])].append(r)
    out = []
    for items in buckets.values():
        for i in range(0, len(items), size):
            out.append(items[i:i + size])
    return out


def _build_prompt(focus: list, global_index: str) -> str:
    """Cloud-neutral extraction prompt. Relation types are a closed enum; free text
    is only allowed in `evidence`. AWS names appear as examples only."""
    focus_json = json.dumps([
        {"node_id": rules.resource_node_id(r["id"]), "type": r["resource_type"],
         "name": r["name"], "tags": r["tags"], "raw_data": r["raw_data"]}
        for r in focus
    ], ensure_ascii=False, default=str)
    allowed = ", ".join(sorted(rules.LLM_RELATION_TYPES))
    return f"""You are analyzing cloud infrastructure inventory to infer SEMANTIC relationships
that are not already expressed by explicit id references. Examples of semantic links:
resources that belong to the same logical system/project/stack even without a shared tag;
a workload node and the data store it clearly serves.

You are given a GLOBAL INDEX of every resource (read-only context), then a FOCUS BATCH to analyze.

Rules you MUST follow:
- Only emit edges whose `source` and `target` are node_ids that appear in the GLOBAL INDEX. Never invent node ids.
- `relation_type` MUST be one of: {allowed}. Prefer `inferred_group` for logical grouping.
- Every edge MUST include an `evidence` string quoting the concrete field/value you relied on
  (e.g. "Purpose=web-frontend" or "name shares prefix payments-"). If you cannot ground it, do not emit it.
- `confidence` is a float 0..1.
- Do NOT re-derive containment or explicit id references (the system already has those).
- Respond with ONLY a JSON object: {{"edges": [{{"source","target","relation_type","evidence","confidence"}}]}}. No prose, no fences.

GLOBAL INDEX:
{global_index}

FOCUS BATCH:
{focus_json}
"""


def _call_bedrock(prompt: str, model_id: str, max_tokens: int) -> tuple:
    """One Bedrock converse call. Returns (text, {"input","output"}). temperature=0."""
    client = get_bedrock_boto_session().client("bedrock-runtime")
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    usage = resp.get("usage", {})
    return text, {"input": int(usage.get("inputTokens", 0)), "output": int(usage.get("outputTokens", 0))}


def _parse_llm_edges(text: str) -> list:
    """Tolerant JSON extraction: strip fences, grab the first {...} object."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("galaxy: could not parse LLM output as JSON")
        return []
    edges = data.get("edges", [])
    return edges if isinstance(edges, list) else []


def _evidence_grounded(evidence: str, endpoints: list) -> bool:
    """The claimed evidence value must actually appear in at least one endpoint's
    raw_data/tags. Evidence for a relationship commonly lives on the SOURCE end
    (e.g. an EC2 whose raw_data cites a VpcId), not the target, and edges pointing
    at group/account nodes have no target raw_data at all — so we ground against
    whichever endpoints are real resources. Still fail-closed: the value must exist
    in some real resource's data; the LLM cannot invent it.

    Grounding strategy (fail-closed but prose-tolerant):
      - If evidence is `key=value`, the value must appear verbatim in an endpoint.
      - Otherwise (natural-language evidence like "name shares prefix payments"),
        at least one significant token (len >= 4, not a stopword) must appear in an
        endpoint's data. A cited term the LLM invented (present in no real resource)
        still fails — so hallucinated relationships are rejected."""
    if not isinstance(evidence, str) or not evidence.strip():
        return False

    haystacks = []
    for res in endpoints:
        if not res:
            continue
        haystacks.append(hashing.canonical_json(
            {"raw_data": res.get("raw_data", {}), "tags": res.get("tags", {})}).lower())
    if not haystacks:
        return False

    if "=" in evidence:
        value = evidence.split("=", 1)[1].strip().strip('"').strip("'").lower()
        return bool(value) and any(value in h for h in haystacks)

    # Natural-language evidence: require a significant cited token to be grounded.
    _STOP = {"name", "shares", "prefix", "same", "both", "with", "that", "this",
             "have", "share", "belong", "belongs", "part", "from", "into", "they"}
    import re as _re
    tokens = [t for t in _re.split(r"[^a-z0-9_-]+", evidence.lower())
              if len(t) >= 4 and t not in _STOP]
    if not tokens:
        return False
    return any(t in h for t in tokens for h in haystacks)


def _verify_edges(edges: list, valid_ids: set, node_by_id: dict, resources_by_node: dict) -> tuple:
    """Fail-closed: endpoints must exist; evidence must be grounded in the target; confidence gate.
    Returns (kept_edges, dropped_count). Kept edges are tagged provenance=llm."""
    kept, dropped = [], 0
    seen = set()
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        rtype = e.get("relation_type")
        conf = float(e.get("confidence", 0) or 0)
        if src not in valid_ids or tgt not in valid_ids or src == tgt:
            dropped += 1
            continue
        if rtype not in rules.LLM_RELATION_TYPES:
            dropped += 1
            continue
        if conf < settings.galaxy_confidence_min:
            dropped += 1
            continue
        # Ground evidence against either endpoint (source and/or target resource).
        # Group/account endpoints have no entry in resources_by_node -> skipped.
        endpoints = [resources_by_node.get(src), resources_by_node.get(tgt)]
        if any(r is not None for r in endpoints) and not _evidence_grounded(e.get("evidence", ""), endpoints):
            dropped += 1
            continue
        key = (src, tgt, rtype)
        if key in seen:
            continue
        seen.add(key)
        kept.append({
            "source": src, "target": tgt, "relation_type": rtype,
            "provenance": "llm", "evidence": str(e.get("evidence", ""))[:500],
            "confidence": conf, "model_id": _model_id(), "prompt_version": PROMPT_VERSION,
        })
    return kept, dropped


def _running_build_id(session) -> int:
    row = session.query(GalaxyBuild).filter_by(status="running").order_by(GalaxyBuild.id.desc()).first()
    return row.id if row else 0


def _latest_llm_build(session) -> Optional[GalaxyBuild]:
    """Newest completed normal build: the LLM carry source and the incremental-skip reference. A rule-only
    refresh never qualifies — it carries LLM edges but produced none."""
    return (session.query(GalaxyBuild)
            .filter(GalaxyBuild.status == "completed", GalaxyBuild.trigger.notin_(sorted(RULE_ONLY_TRIGGERS)))
            .order_by(GalaxyBuild.finished_at.desc().nulls_last(), GalaxyBuild.id.desc()).first())


def latest_published_id(session) -> Optional[int]:
    """The build GraphQueryService reads: newest rules_published_at, whatever its final status — a build
    whose LLM phase failed keeps its rule rows readable (spec §3.A.3 ④)."""
    row = (session.query(GalaxyBuild.id).filter(GalaxyBuild.rules_published_at.isnot(None))
           .order_by(GalaxyBuild.rules_published_at.desc(), GalaxyBuild.id.desc()).first())
    return row.id if row else None


def build_graph(trigger: str = "manual", full: bool = False, llm: bool = True) -> int:
    """Run one build. Returns the build id (or an existing running / latest id on no-op).

    llm=True is a normal build: the rule layer is published first, then the LLM phase runs outside
    _RULE_LOCK; it never raises (a failure returns the failed row's id). llm=False is a rule-only refresh
    (_rule_only_refresh). trigger and llm must agree, so the latest LLM build is known by its trigger."""
    if (not llm) != (trigger in RULE_ONLY_TRIGGERS):
        raise ValueError(f"galaxy: trigger {trigger!r} cannot run with llm={llm}; "
                         f"rule-only triggers are {sorted(RULE_ONLY_TRIGGERS)}")
    if not llm:
        return _rule_only_refresh(trigger)

    with _RULE_LOCK:
        # --- Concurrency guard + diff decision (short transaction) ---
        with get_db_session() as s:
            running = _running_build_id(s)
            if running:
                logger.info("galaxy: build already running (%s); skipping", running)
                return running
            resources = _load_resources(s)
            current_hashes = {r["id"]: hashing.content_hash(r) for r in resources}
            prev_rows = {row.resource_pk: row.content_hash for row in s.query(GalaxyResourceState).all()}
            diff = hashing.compute_diff(prev_rows, current_hashes)
            latest = _latest_llm_build(s)
            # A build from before 2.6.1 never published resource_relations. Skipping it would leave the query
            # layer empty for as long as the inventory stays unchanged (Review Focus 1).
            if (not full and latest is not None and latest.rules_published_at is not None
                    and not diff.dirty and not diff.removed):
                logger.info("galaxy: no resource changes; skipping build")
                return latest.id
            prev_llm_edges = list((latest.llm_graph or {}).get("edges", [])) if latest else []
            # Open the build row (the cross-process lock for normal builds).
            build = GalaxyBuild(status="running", trigger=trigger, full=full,
                                model_id=_model_id(), prompt_version=PROMPT_VERSION,
                                started_at=datetime.now(timezone.utc))
            s.add(build)
            s.flush()
            build_id = build.id

        # --- Rule layer: derive + publish before any LLM call ---
        try:
            rule_graph = rules.derive_rule_graph(resources, families=settings.identity_type_families)
            resources_by_node = {rules.resource_node_id(r["id"]): r for r in resources}
            with get_db_session() as s:
                _publish_rules(s, s.get(GalaxyBuild, build_id), resources, rule_graph, resources_by_node)
        except Exception as e:
            return _fail_build(build_id, e)

    # --- LLM phase, outside the rule lock: a rule-only refresh may publish meanwhile ---
    try:
        valid_ids = {n["id"] for n in rule_graph["nodes"]}
        node_by_id = {n["id"]: n for n in rule_graph["nodes"]}
        # K8s relations are fully rule-derived: K8s rows are neither shown to the LLM nor accepted from it.
        non_k8s = [r for r in resources if r["resource_type"] not in rules.K8S_TYPES]
        llm_ids = valid_ids - {rules.resource_node_id(r["id"]) for r in resources
                               if r["resource_type"] in rules.K8S_TYPES}

        # Which resources need LLM analysis this run?
        exclude = set(settings.galaxy_llm_exclude_types)
        candidates = [r for r in non_k8s if r["resource_type"] not in exclude]
        dirty_pks = current_hashes.keys() if full else diff.dirty
        focus_pool = [r for r in candidates if (full or r["id"] in dirty_pks)]

        global_index = _compact_index(non_k8s)
        max_tokens = settings.bedrock_max_tokens
        in_tok = out_tok = 0
        fresh_llm_edges: list = []
        total_dropped = 0

        for batch in _batches(focus_pool, settings.galaxy_batch_size):
            prompt = _build_prompt(batch, global_index)
            text, usage = _call_bedrock(prompt, _model_id(), max_tokens)
            in_tok += usage["input"]
            out_tok += usage["output"]
            proposed = _parse_llm_edges(text)
            kept, dropped = _verify_edges(proposed, llm_ids, node_by_id, resources_by_node)
            fresh_llm_edges.extend(kept)
            total_dropped += dropped

        # Carry forward prior LLM edges for resources NOT re-analyzed this run.
        if not full:
            dirty_nodes = {rules.resource_node_id(pk) for pk in dirty_pks}
            removed_nodes = {rules.resource_node_id(pk) for pk in diff.removed}
            for e in prev_llm_edges:
                if e["source"] in dirty_nodes or e["target"] in dirty_nodes:
                    continue  # will be re-proposed by fresh pass
                if e["source"] in removed_nodes or e["target"] in removed_nodes:
                    continue  # endpoint gone
                if e["source"] in valid_ids and e["target"] in valid_ids:
                    fresh_llm_edges.append(e)

        # Dedup carried + fresh by identity key.
        merged, seen = [], set()
        for e in fresh_llm_edges:
            k = (e["source"], e["target"], e["relation_type"])
            if k not in seen:
                seen.add(k)
                merged.append(e)

        drop_rate = total_dropped / max(1, total_dropped + len(merged))
        if drop_rate > settings.galaxy_drop_rate_alert:
            logger.warning("galaxy: LLM edge drop rate %.1f%% exceeds alert threshold", drop_rate * 100)

        cost = compute_cost(_model_id(), {"input": in_tok, "output": out_tok})

        with get_db_session() as s:
            _publish_relations(s, build_id, merged, resources_by_node)
            _persist_groups(s, rule_graph["groups"], build_id)
            _persist_state(s, current_hashes, diff.removed, build_id)
            b = s.query(GalaxyBuild).filter_by(id=build_id).one()
            b.status = "completed"
            b.finished_at = datetime.now(timezone.utc)
            b.llm_graph = {"edges": merged}
            b.edge_count = len(rule_graph["edges"]) + len(merged)
            b.dropped_edge_count = total_dropped
            b.input_tokens = in_tok
            b.output_tokens = out_tok
            b.cost_usd = cost
            _prune_old_builds(s, keep=settings.galaxy_builds_keep)
        logger.info("galaxy: build %s completed — %d nodes, %d edges, %d dropped, $%.4f",
                    build_id, len(rule_graph["nodes"]), len(rule_graph["edges"]) + len(merged),
                    total_dropped, cost)
    except Exception as e:
        return _fail_build(build_id, e)
    _reanchor()
    return build_id


def _rule_only_refresh(trigger: str) -> int:
    """Re-derive and publish the rule layer without the LLM (spec §3.A.3 ④).

    Takes no running row, so a normal build in its LLM phase never blocks it; _RULE_LOCK keeps it from
    interleaving with that build's rule phase. Carries the latest LLM build's edges whose two ends still
    exist, and writes one completed row with zero tokens. It leaves galaxy_resource_state alone: that is the
    LLM diff baseline, so the next normal build still sees every change since the last LLM pass.
    Raises on failure, and then nothing is written (the transaction rolls back); callers log it."""
    with _RULE_LOCK:
        with get_db_session() as s:
            resources = _load_resources(s)
            latest = _latest_llm_build(s)
            prev_llm_edges = list((latest.llm_graph or {}).get("edges", [])) if latest else []
        rule_graph = rules.derive_rule_graph(resources, families=settings.identity_type_families)
        resources_by_node = {rules.resource_node_id(r["id"]): r for r in resources}
        valid_ids = {n["id"] for n in rule_graph["nodes"]}
        carried = [e for e in prev_llm_edges if e["source"] in valid_ids and e["target"] in valid_ids]
        now = datetime.now(timezone.utc)
        with get_db_session() as s:
            build = GalaxyBuild(status="completed", trigger=trigger, full=False, model_id="",
                                prompt_version=PROMPT_VERSION, started_at=now, finished_at=now,
                                llm_graph={"edges": carried}, dropped_edge_count=0,
                                input_tokens=0, output_tokens=0, cost_usd=0.0)
            s.add(build)
            s.flush()
            _publish_rules(s, build, resources, rule_graph, resources_by_node)
            _publish_relations(s, build.id, carried, resources_by_node)
            build.edge_count = len(rule_graph["edges"]) + len(carried)
            _persist_groups(s, rule_graph["groups"], build.id)
            _prune_old_builds(s, keep=settings.galaxy_builds_keep)
            build_id = build.id
    logger.info("galaxy: rule-only refresh %s (%s) — %d nodes, %d rule edges, %d llm edges carried",
                build_id, trigger, len(rule_graph["nodes"]), len(rule_graph["edges"]), len(carried))
    _reanchor()
    return build_id


def _publish_rules(session, build: GalaxyBuild, resources: list, rule_graph: dict,
                   resources_by_node: dict) -> None:
    """Publish one build's rule layer in the caller's transaction: unresolved_refs write-back, the rule rows
    of resource_relations, the rule_graph JSON and rules_published_at. Caller holds _RULE_LOCK."""
    _write_unresolved_refs(session, resources, rule_graph["unresolved_refs"])
    _publish_relations(session, build.id, rule_graph["edges"], resources_by_node)
    build.rule_graph = {"nodes": rule_graph["nodes"], "edges": rule_graph["edges"]}
    build.node_count = len(rule_graph["nodes"])
    build.edge_count = len(rule_graph["edges"])
    build.rules_published_at = datetime.now(timezone.utc)


def _publish_relations(session, build_id: int, edges: list, resources_by_node: dict) -> int:
    """Copy a build's resource→resource edges into resource_relations; returns the rows written.

    Account and group endpoints stay in the build JSON only (they narrow scope, they do not propagate
    faults), and so does an edge whose two ends sit in different accounts: rules never derive one, but the
    LLM sees every account in its global index."""
    rows = []
    for e in edges:
        src, dst = resources_by_node.get(e["source"]), resources_by_node.get(e["target"])
        if src is None or dst is None or src["account_id"] != dst["account_id"]:
            continue
        rows.append(ResourceRelation(
            build_id=build_id, account_id=src["account_id"], src_ref=src["id"], dst_ref=dst["id"],
            relation_type=e["relation_type"], provenance=e.get("provenance") or "rule",
            evidence={"text": str(e.get("evidence") or "")},
            confidence=float(e.get("confidence", 1.0) or 0.0)))
    session.add_all(rows)
    return len(rows)


def _fail_build(build_id: int, exc: Exception) -> int:
    """Mark a normal build failed; call from an except block. Rule rows it already published stay readable."""
    logger.exception("galaxy: build %s failed", build_id)
    with get_db_session() as s:
        b = s.query(GalaxyBuild).filter_by(id=build_id).first()
        if b:
            b.status = "failed"
            b.finished_at = datetime.now(timezone.utc)
            b.error = str(exc)[:2000]
    return build_id


def _reanchor() -> None:
    """Retry anchoring open issues after a completed build (spec §3.A.3 ⑤). Fail-soft: anchoring is an
    enrichment and must never turn a completed build into an error."""
    try:
        from agenticops.services.identity_resolver import reanchor_open_issues

        with get_db_session() as s:
            changed = reanchor_open_issues(s)
        if changed:
            logger.info("galaxy: re-anchored %d open issue(s)", changed)
    except Exception:
        logger.exception("galaxy: re-anchoring after the build failed")


def _persist_groups(session, groups: list, build_id: int) -> None:
    """Create-or-match group registry rows (stable slugs across builds)."""
    for g in groups:
        row = session.query(GalaxyGroup).filter_by(slug=g["slug"]).first()
        if row is None:
            session.add(GalaxyGroup(slug=g["slug"], display_name=g["display_name"],
                                    kind=g["kind"], created_by_build=build_id,
                                    member_count=g["member_count"]))
        else:
            row.member_count = g["member_count"]
            row.display_name = g["display_name"]


def _persist_state(session, current_hashes: dict, removed: set, build_id: int) -> None:
    existing = {row.resource_pk: row for row in session.query(GalaxyResourceState).all()}
    for pk, h in current_hashes.items():
        row = existing.get(pk)
        if row is None:
            session.add(GalaxyResourceState(resource_pk=pk, content_hash=h, last_analyzed_build_id=build_id))
        else:
            row.content_hash = h
            row.last_analyzed_build_id = build_id
    for pk in removed:
        if pk in existing:
            session.delete(existing[pk])


def _write_unresolved_refs(session, resources: list, unresolved: dict) -> int:
    """Write each K8s workload's unresolved references back into its raw_data, only where the value changed
    (spec §3.A.3 ③). The key is volatile (hashing.VOLATILE_KEYS), so this never dirties a content hash.
    The row is re-read here and only this key is replaced, so a concurrent ingest keeps its other fields."""
    current = {r["id"]: (r["raw_data"].get("unresolved_refs") or []) for r in resources}
    written = 0
    for pk, refs in unresolved.items():
        if current.get(pk) == refs:
            continue
        row = session.get(CloudResource, pk)
        if row is None:
            continue
        raw = dict(row.raw_data) if isinstance(row.raw_data, dict) else {}
        raw["unresolved_refs"] = refs
        row.raw_data = raw
        written += 1
    return written


def _prune_old_builds(session, keep: int) -> None:
    """Retain the `keep` most-recent build rows to bound DB growth, plus every build still in use: a running
    build (its rule rows may already be what GraphQueryService reads), the latest LLM build (carry source
    and incremental-skip reference) and the latest published build. A pruned build's resource_relations
    rows go with it. keep<=0 disables pruning.

    Each GalaxyBuild row stores the full rule+llm graph JSON blobs (hundreds of KB to several MB at scale),
    so unbounded retention would grow the DB by GBs/month.
    """
    if keep is None or keep <= 0:
        return
    keep_ids = {row.id for row in session.query(GalaxyBuild.id).order_by(GalaxyBuild.id.desc()).limit(keep)}
    if not keep_ids:
        return
    keep_ids |= {row.id for row in session.query(GalaxyBuild.id).filter_by(status="running")}
    llm = _latest_llm_build(session)
    keep_ids |= {i for i in (llm.id if llm else None, latest_published_id(session)) if i is not None}
    doomed = [row.id for row in session.query(GalaxyBuild.id).filter(GalaxyBuild.id.notin_(keep_ids))]
    if not doomed:
        return
    (session.query(ResourceRelation).filter(ResourceRelation.build_id.in_(doomed))
     .delete(synchronize_session=False))
    session.query(GalaxyBuild).filter(GalaxyBuild.id.in_(doomed)).delete(synchronize_session=False)
