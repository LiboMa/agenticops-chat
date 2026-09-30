"""Measure the MVP-2.6.1 graph facts layer on a read-only copy of a SQLite database (spec §7, §8.1, §8.2).

    PYTHONPATH=src python scripts/measure_graph_facts.py --db PATH [--runs N] [--doc PATH]

The source is opened with mode=ro and copied through the SQLite backup API. The 2.6.1 migration and anchor
backfill, one rule build (LLM phase stubbed to return no edges: no Bedrock call, $0) and every query run on
the copy; the source file is never written. Prints the report as JSON; --doc also renders it as markdown.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import event, func

import agenticops.models as models
from agenticops.config import settings
from agenticops.galaxy import builder
from agenticops.galaxy.models import GalaxyBuild, ResourceRelation
from agenticops.graph import query_service
from agenticops.models import CloudAccount, CloudResource, HealthIssue, get_db_session, init_db
from agenticops.services import identity_resolver as ir
from agenticops.services.signal_gate import OPEN_ISSUE_STATUSES

ANCHOR_TARGET = 0.95   # spec §8.1
SQL_TARGET = 5         # spec §8.2
P95_TARGET_MS = 200.0  # spec §8.2


def copy_readonly(src: Path, dst: Path) -> None:
    """Consistent snapshot through a mode=ro connection: the source is never opened for writing, and a
    missing source raises instead of being created empty."""
    source = sqlite3.connect(f"{Path(src).resolve().as_uri()}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _claimed_accounts(db: Path) -> dict:
    """health_issues.account_id as it was before the backfill fills some of them in from the anchor."""
    conn = sqlite3.connect(db)
    try:
        return dict(conn.execute("SELECT id, account_id FROM health_issues"))
    finally:
        conn.close()


def _shape(resource_id: str) -> str:
    """Coarse id family for the unmatched breakdown: arn:<service>, <prefix>-*, or other."""
    rid = resource_id.strip()
    if rid.startswith("arn:"):
        parts = rid.split(":")
        return f"arn:{parts[2]}" if len(parts) > 2 and parts[2] else "arn"
    m = re.match(r"([a-z]+)-[0-9a-f]{6,}$", rid)
    return f"{m.group(1)}-*" if m else "other"


def measure_anchoring(session) -> dict:
    """Spec §8.1: open issues with a resource_id, (anchored + account_level) / total, and why the rest missed."""
    rows = (session.query(HealthIssue.resource_id, HealthIssue.anchor_status, HealthIssue.anchor_candidates)
            .filter(HealthIssue.status.in_(OPEN_ISSUE_STATUSES), func.trim(HealthIssue.resource_id) != "")
            .all())
    status = Counter(r.anchor_status for r in rows)
    missed = [r for r in rows if r.anchor_status not in (ir.ANCHORED, ir.ACCOUNT_LEVEL)]
    reasons = Counter((r.anchor_status, (r.anchor_candidates or {}).get("rule")) for r in missed)
    shapes = Counter(_shape(r.resource_id) for r in missed
                     if r.anchor_status == ir.UNANCHORED and (r.anchor_candidates or {}).get("rule") == "none")
    total = len(rows)
    rate = (status[ir.ANCHORED] + status[ir.ACCOUNT_LEVEL]) / total if total else 0.0
    return {
        "total": total,
        **{s: status[s] for s in (ir.ANCHORED, ir.ACCOUNT_LEVEL, ir.AMBIGUOUS, ir.UNANCHORED)},
        "not_backfilled": status[None],
        "rate": round(rate, 4), "target": ANCHOR_TARGET, "met": total > 0 and rate >= ANCHOR_TARGET,
        "reasons": [{"status": s, "rule": rule, "count": n} for (s, rule), n in reasons.most_common()],
        "unmatched_shapes": [{"shape": k, "count": n} for k, n in shapes.most_common(10)],
    }


def measure_duplicates(session, claimed: dict) -> dict:
    """Spec §8.1: an id that several accounts hold is never anchored to the wrong one. Checked on the open issues
    that name such an id, and by probing resolve() with every such id — without an account (anchoring would be
    a guess) and under each account that holds it (the anchor must stay inside that account)."""
    groups = [rid for (rid,) in session.query(CloudResource.resource_id).group_by(CloudResource.resource_id)
              .having(func.count(func.distinct(CloudResource.account_id)) > 1)]
    owner = dict(session.query(CloudResource.id, CloudResource.account_id))
    holders: dict = {}
    for rid, acct in (session.query(CloudResource.resource_id, CloudResource.account_id)
                      .filter(CloudResource.resource_id.in_(groups))):
        holders.setdefault(rid, set()).add(acct)

    issues = (session.query(HealthIssue.id, HealthIssue.resource_ref)
              .filter(HealthIssue.status.in_(OPEN_ISSUE_STATUSES), HealthIssue.resource_id.in_(groups),
                      HealthIssue.anchor_status == ir.ANCHORED).all())
    guessed = sum(1 for i in issues if claimed.get(i.id) is None)
    crossed = sum(1 for i in issues if claimed.get(i.id) is not None and owner.get(i.resource_ref) != claimed[i.id])

    probe_guessed = sum(1 for rid in groups if ir.resolve(session, resource_id=rid).status == ir.ANCHORED)
    in_account = [(acct, ir.resolve(session, account_id=acct, resource_id=rid))
                  for rid in groups for acct in sorted(holders[rid])]
    anchored = [(acct, a) for acct, a in in_account if a.status == ir.ANCHORED]
    probe_crossed = sum(1 for acct, a in anchored if owner.get(a.resource_ref) != acct)
    return {
        "groups": len(groups),
        "open_issues": (session.query(HealthIssue.id)
                        .filter(HealthIssue.status.in_(OPEN_ISSUE_STATUSES), HealthIssue.resource_id.in_(groups))
                        .count()),
        "crossed": crossed, "guessed": guessed,
        "probe_guessed": probe_guessed, "in_account_probes": len(in_account),
        "in_account_anchored": len(anchored), "probe_crossed": probe_crossed,
        "met": crossed == guessed == probe_guessed == probe_crossed == 0,
    }


def publish_rules() -> dict:
    """One full normal build with the LLM phase stubbed out. The query layer reads rule edges by default
    (include_llm=False), so this is the graph being measured."""
    real = builder._call_bedrock
    builder._call_bedrock = lambda prompt, model_id, max_tokens: (json.dumps({"edges": []}),
                                                                  {"input": 0, "output": 0})
    started = time.perf_counter()
    try:
        build_id = builder.build_graph("manual", full=True)
    finally:
        builder._call_bedrock = real
    seconds = time.perf_counter() - started
    with get_db_session() as s:
        b = s.get(GalaxyBuild, build_id)
        if b.status != "completed" or b.rules_published_at is None:
            raise RuntimeError(f"galaxy build {build_id} ended {b.status}: {b.error or 'no error recorded'}")
        relations = dict(s.query(ResourceRelation.provenance, func.count())
                         .filter(ResourceRelation.build_id == build_id).group_by(ResourceRelation.provenance))
    return {"build_id": build_id, "build_seconds": round(seconds, 1), "relations": relations}


def _pct(values: list, q: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def measure_queries(runs: int) -> dict:
    """Spec §8.2: a 2-hop neighborhood around every anchored open issue's resource. The cache is cleared
    before each call, so this is the uncached (slower) path."""
    with get_db_session() as s:
        refs = sorted({ref for (ref,) in s.query(HealthIssue.resource_ref).filter(
            HealthIssue.status.in_(OPEN_ISSUE_STATUSES), HealthIssue.anchor_status == ir.ANCHORED,
            HealthIssue.resource_ref.isnot(None))})
    if not refs:
        return {"refs": 0, "runs": runs, "calls": 0, "met": False}
    query_service.neighborhood(refs[0], depth=2)  # warm-up: first connect, imports
    counter = {"n": 0}

    def _count(*_args, **_kwargs):
        counter["n"] += 1

    engine = models.get_engine()
    event.listen(engine, "before_cursor_execute", _count)
    ms, sql, nodes, truncated = [], [], [], 0
    try:
        for _ in range(runs):
            for ref in refs:
                query_service.clear_cache()
                counter["n"] = 0
                started = time.perf_counter()
                sub = query_service.neighborhood(ref, depth=2)
                ms.append((time.perf_counter() - started) * 1000)
                sql.append(counter["n"])
                nodes.append(len(sub.nodes))
                truncated += bool(sub.truncated)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    if not ms:
        return {"refs": len(refs), "runs": runs, "calls": 0, "met": False}
    p95 = _pct(ms, 0.95)
    return {
        "refs": len(refs), "runs": runs, "calls": len(ms),
        "max_sql": max(sql), "sql_target": SQL_TARGET,
        "p50_ms": round(_pct(ms, 0.5), 1), "p95_ms": round(p95, 1), "max_ms": round(max(ms), 1),
        "p95_target_ms": P95_TARGET_MS, "max_nodes": max(nodes), "truncated": truncated,
        "met": max(sql) <= SQL_TARGET and p95 < P95_TARGET_MS,
    }


def measure(src: Path, runs: int = 3) -> dict:
    src = Path(src)
    saved_url, saved_engine = settings.database_url, models._engine
    with tempfile.TemporaryDirectory(prefix="graph-facts-") as tmp:
        copy = Path(tmp) / "copy.db"
        copy_readonly(src, copy)
        claimed = _claimed_accounts(copy)
        settings.database_url = f"sqlite:///{copy}"
        models._engine = None
        query_service.clear_cache()
        try:
            init_db()
            with get_db_session() as s:
                inventory = {"accounts": s.query(CloudAccount).count(), "resources": s.query(CloudResource).count()}
                anchoring = measure_anchoring(s)
                duplicates = measure_duplicates(s, claimed)
            graph = publish_rules()
            queries = measure_queries(runs)
        finally:
            if models._engine is not None and models._engine is not saved_engine:
                models._engine.dispose()
            settings.database_url, models._engine = saved_url, saved_engine
            query_service.clear_cache()
    return {"source": str(src), "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "inventory": inventory, "anchoring": anchoring, "duplicates": duplicates, "graph": graph,
            "queries": queries}


def _verdict(ok: bool) -> str:
    return "达标" if ok else "未达标"


def render_markdown(r: dict) -> str:
    a, d, g, q = r["anchoring"], r["duplicates"], r["graph"], r["queries"]
    lines = [
        "# MVP-2.6.1 图事实层实测",
        "",
        f"由 `scripts/measure_graph_facts.py` 生成（{r['measured_at']}）。数据源 `{r['source']}` 以只读方式打开，"
        "经 SQLite backup API 复制。迁移、锚定回填、规则构建和查询都在副本上跑，原库不写。规则构建时 LLM 阶段"
        "换成了返回空边的桩：不调 Bedrock，零成本；查询层默认只读规则边（`include_llm=False`），所以测的就是它。",
        "",
        f"库存：{r['inventory']['accounts']} 个账户，{r['inventory']['resources']} 个资源。",
        "",
        "## 锚定率（spec §8.1）",
        "",
        f"有 `resource_id` 的未关闭 Issue 共 {a['total']} 条。"
        f"(anchored + account_level) / 总数 = ({a['anchored']} + {a['account_level']}) / {a['total']}"
        f" = **{a['rate']:.1%}**，目标 ≥ {a['target']:.0%}：**{_verdict(a['met'])}**。",
        "",
        "| anchor_status | 条数 |",
        "|---|---|",
        *(f"| {s} | {a[s]} |" for s in (ir.ANCHORED, ir.ACCOUNT_LEVEL, ir.AMBIGUOUS, ir.UNANCHORED)),
    ]
    if a["not_backfilled"]:
        lines.append(f"| （回填失败，仍为空） | {a['not_backfilled']} |")
    lines += ["", "未锚定的原因分布（`anchor_candidates.rule`）：", "", "| anchor_status | rule | 条数 |", "|---|---|---|"]
    lines += [f"| {x['status']} | {x['rule']} | {x['count']} |" for x in a["reasons"]]
    if a["unmatched_shapes"]:
        lines += ["", "`rule = none`（库存里找不到这个资源）按 id 形态的前 10 类：", "", "| id 形态 | 条数 |", "|---|---|"]
        lines += [f"| `{x['shape']}` | {x['count']} |" for x in a["unmatched_shapes"]]
    if not a["met"]:
        lines += ["", "按 spec §8.1，未达标时如实报告原因分布，**不放宽规则去凑数**。`none`：库存里没有这个资源，"
                  "多为未扫描的资源类型；`unknown_account`：信号指向本平台未管理的账户；`ambiguous`：同一条规则"
                  "命中了多个物理资源，候选都记在 `anchor_candidates` 里。"]
    lines += [
        "",
        "## 跨账户重复 id（spec §8.1）",
        "",
        f"库存里有 {d['groups']} 组跨账户重复的 `resource_id`，指向它们的未关闭 Issue 有 {d['open_issues']} 条。"
        f"其中锚到错误账户 {d['crossed']} 条，没有账户却被锚定 {d['guessed']} 条。",
        "",
        f"`resolve()` 探测：不给账户时锚定 {d['probe_guessed']} 次（应为 0）；给出持有账户时 "
        f"{d['in_account_anchored']}/{d['in_account_probes']} 次锚定，其中锚到别的账户 {d['probe_crossed']} 次（应为 0）。"
        f"结论：**{_verdict(d['met'])}**。",
        "",
        "## 查询性能（spec §7、§8.2）",
        "",
        f"规则构建 build #{g['build_id']} 耗时 {g['build_seconds']} 秒，发布关系 rule {g['relations'].get('rule', 0)} 条、"
        f"llm {g['relations'].get('llm', 0)} 条（LLM 阶段是桩，应为 0）。",
        "",
    ]
    if q["calls"]:
        lines.append(
            f"对 {q['refs']} 个锚定资源各做 {q['runs']} 轮 2 跳 `neighborhood`，每次调用前清缓存（测未命中路径），"
            f"共 {q['calls']} 次。SQL 条数最多 {q['max_sql']}（目标 ≤ {q['sql_target']}）；耗时 p50 {q['p50_ms']} ms、"
            f"p95 {q['p95_ms']} ms、最大 {q['max_ms']} ms（目标 p95 < {q['p95_target_ms']:.0f} ms）；"
            f"最大邻域 {q['max_nodes']} 个节点，截断 {q['truncated']} 次。结论：**{_verdict(q['met'])}**。")
    else:
        lines.append("没有锚定的 Issue，未测查询性能。")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Measure the MVP-2.6.1 graph facts layer on a read-only DB copy.")
    p.add_argument("--db", required=True, type=Path, help="SQLite database to measure (opened read-only)")
    p.add_argument("--runs", type=int, default=3, help="passes over the anchored resources (default 3)")
    p.add_argument("--doc", type=Path, help="also write the markdown report to this path")
    args = p.parse_args(argv)
    report = measure(args.db, runs=args.runs)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.doc:
        args.doc.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
