"""Galaxy build pipeline: diff -> L1 rules -> L2 index -> L3 LLM enrichment
-> fail-closed verification -> merge/stabilize -> persist.

Runs synchronously (call inside a background task / thread). Concurrency guard:
a single 'running' GalaxyBuild row acts as the lock — a second call is a no-op.
"""

import json
import logging
import re
from datetime import datetime, timezone

from agenticops.config import settings, get_bedrock_boto_session
from agenticops.cost import compute_cost
from agenticops.models import get_db_session, CloudResource
from agenticops.galaxy.models import GalaxyBuild, GalaxyResourceState, GalaxyGroup
from agenticops.galaxy import hashing
from agenticops.galaxy import rules

logger = logging.getLogger(__name__)

PROMPT_VERSION = "galaxy-v1"


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
    allowed = ", ".join(sorted(rules.RELATION_TYPES))
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
    in some real resource's data; the LLM cannot invent it."""
    if not isinstance(evidence, str) or not evidence.strip():
        return False
    # Extract the value after '=' if present, else use the whole string token.
    value = evidence.split("=", 1)[1] if "=" in evidence else evidence
    value = value.strip().strip('"').strip("'").lower()
    if not value:
        return False
    for res in endpoints:
        if not res:
            continue
        haystack = hashing.canonical_json({"raw_data": res.get("raw_data", {}),
                                           "tags": res.get("tags", {})}).lower()
        if value in haystack:
            return True
    return False


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
        if rtype not in rules.RELATION_TYPES:
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


def _latest_completed(session) -> GalaxyBuild:
    return (session.query(GalaxyBuild).filter_by(status="completed")
            .order_by(GalaxyBuild.id.desc()).first())


def build_graph(trigger: str = "manual", full: bool = False) -> int:
    """Run one build. Returns build id (or an existing running/latest id on no-op)."""
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
        latest = _latest_completed(s)
        if not full and latest is not None and not diff.dirty and not diff.removed:
            logger.info("galaxy: no resource changes; skipping build")
            return latest.id
        prev_llm_edges = list(latest.llm_graph.get("edges", [])) if latest else []
        # Open the build row (acts as the lock).
        build = GalaxyBuild(status="running", trigger=trigger, full=full,
                            model_id=_model_id(), prompt_version=PROMPT_VERSION,
                            started_at=datetime.now(timezone.utc))
        s.add(build)
        s.flush()
        build_id = build.id

    # --- Heavy work outside the lock transaction ---
    try:
        rule_graph = rules.derive_rule_graph(resources)
        valid_ids = {n["id"] for n in rule_graph["nodes"]}
        node_by_id = {n["id"]: n for n in rule_graph["nodes"]}
        resources_by_node = {rules.resource_node_id(r["id"]): r for r in resources}

        # Which resources need LLM analysis this run?
        exclude = set(settings.galaxy_llm_exclude_types)
        candidates = [r for r in resources if r["resource_type"] not in exclude]
        dirty_pks = current_hashes.keys() if full else diff.dirty
        focus_pool = [r for r in candidates if (full or r["id"] in dirty_pks)]

        global_index = _compact_index(resources)
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
            kept, dropped = _verify_edges(proposed, valid_ids, node_by_id, resources_by_node)
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
            _persist_groups(s, rule_graph["groups"], build_id)
            _persist_state(s, current_hashes, diff.removed, build_id)
            b = s.query(GalaxyBuild).filter_by(id=build_id).one()
            b.status = "completed"
            b.finished_at = datetime.now(timezone.utc)
            b.rule_graph = {"nodes": rule_graph["nodes"], "edges": rule_graph["edges"]}
            b.llm_graph = {"edges": merged}
            b.node_count = len(rule_graph["nodes"])
            b.edge_count = len(rule_graph["edges"]) + len(merged)
            b.dropped_edge_count = total_dropped
            b.input_tokens = in_tok
            b.output_tokens = out_tok
            b.cost_usd = cost
            _prune_old_builds(s, keep=settings.galaxy_builds_keep)
        logger.info("galaxy: build %s completed — %d nodes, %d edges, %d dropped, $%.4f",
                    build_id, len(rule_graph["nodes"]), len(rule_graph["edges"]) + len(merged),
                    total_dropped, cost)
        return build_id
    except Exception as e:
        logger.exception("galaxy: build %s failed", build_id)
        with get_db_session() as s:
            b = s.query(GalaxyBuild).filter_by(id=build_id).first()
            if b:
                b.status = "failed"
                b.finished_at = datetime.now(timezone.utc)
                b.error = str(e)[:2000]
        return build_id


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


def _prune_old_builds(session, keep: int) -> None:
    """Retain only the `keep` most-recent build rows to bound DB growth.

    Each GalaxyBuild row stores the full rule+llm graph JSON blobs (hundreds of KB
    to several MB at scale), and only the latest completed build is ever read, so
    unbounded retention would grow the DB by GBs/month. keep<=0 disables pruning.
    """
    if keep is None or keep <= 0:
        return
    keep_ids = [row.id for row in (session.query(GalaxyBuild.id)
                                   .order_by(GalaxyBuild.id.desc())
                                   .limit(keep).all())]
    if not keep_ids:
        return
    (session.query(GalaxyBuild)
     .filter(GalaxyBuild.id.notin_(keep_ids))
     .delete(synchronize_session=False))
