# src/agenticops/services/cost_service.py
"""Real-time token/cost aggregation over agent_logs (no rollup tables)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, literal

_GROUP_COL = {"agent": "agent_name", "actor": "actor_type", "model": "model_id"}
_BUCKET_FMT = {"hour": "%Y-%m-%d %H:00", "day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}


def _bucket_expr(col, bucket: str):
    """DB-portable time-bucket string. SQLite: strftime; else fall back to date()."""
    fmt = _BUCKET_FMT.get(bucket, "%Y-%m-%d")
    try:
        return func.strftime(fmt, col)            # sqlite
    except Exception:
        return func.date(col)


def cost_summary(
    start: datetime,
    end: datetime,
    bucket: str = "day",
    group_by: str = "agent",
    filters: Optional[dict] = None,
) -> dict:
    from agenticops.models import AgentLog, get_db_session

    filters = filters or {}

    with get_db_session() as db:
        if group_by == "none":
            # No dimension split: a single aggregate bucket keyed "all".
            gcol = literal("all")
        else:
            gcol = getattr(AgentLog, _GROUP_COL.get(group_by, "agent_name"))
        bexpr = _bucket_expr(AgentLog.created_at, bucket)

        def base_query():
            q = db.query(AgentLog).filter(
                AgentLog.created_at >= start, AgentLog.created_at < end
            )
            if filters.get("actor_type"):
                q = q.filter(AgentLog.actor_type == filters["actor_type"])
            if filters.get("actor_id"):
                q = q.filter(AgentLog.actor_id == filters["actor_id"])
            if filters.get("agent_name"):
                q = q.filter(AgentLog.agent_name == filters["agent_name"])
            if filters.get("model_id"):
                q = q.filter(AgentLog.model_id == filters["model_id"])
            return q

        # totals
        t = base_query().with_entities(
            func.coalesce(func.sum(AgentLog.input_tokens), 0),
            func.coalesce(func.sum(AgentLog.output_tokens), 0),
            func.coalesce(func.sum(AgentLog.cache_read_tokens), 0),
            func.coalesce(func.sum(AgentLog.cache_write_tokens), 0),
            func.coalesce(func.sum(AgentLog.cost_usd), 0.0),
            func.count(AgentLog.id),
        ).one()
        ti, to, tcr, tcw, tcost, tcalls = t
        total_tokens = ti + to + tcr + tcw
        cache_hit_pct = round(100.0 * tcr / (ti + tcr), 1) if (ti + tcr) else 0.0
        totals = {
            "input": ti, "output": to, "cache_read": tcr, "cache_write": tcw,
            "total_tokens": total_tokens, "cost_usd": round(tcost, 6),
            "cache_hit_pct": cache_hit_pct, "call_count": tcalls,
        }

        # series: bucket × group
        srows = base_query().with_entities(
            bexpr.label("b"), gcol.label("g"),
            func.coalesce(func.sum(AgentLog.cost_usd), 0.0),
            func.coalesce(func.sum(AgentLog.input_tokens + AgentLog.output_tokens
                                   + AgentLog.cache_read_tokens + AgentLog.cache_write_tokens), 0),
        ).group_by("b", "g").all()
        series_map: dict[str, dict] = {}
        for b, g, cost, toks in srows:
            entry = series_map.setdefault(b, {"bucket": b, "cost_usd": 0.0, "total_tokens": 0, "by": {}})
            entry["cost_usd"] = round(entry["cost_usd"] + (cost or 0.0), 6)
            entry["total_tokens"] += int(toks or 0)
            entry["by"][g or "unknown"] = {"cost_usd": round(cost or 0.0, 6), "tokens": int(toks or 0)}
        series = sorted(series_map.values(), key=lambda r: r["bucket"])

        # breakdown by dimension
        brows = base_query().with_entities(
            gcol.label("g"),
            func.count(AgentLog.id),
            func.coalesce(func.sum(AgentLog.input_tokens), 0),
            func.coalesce(func.sum(AgentLog.output_tokens), 0),
            func.coalesce(func.sum(AgentLog.cache_read_tokens), 0),
            func.coalesce(func.sum(AgentLog.cache_write_tokens), 0),
            func.coalesce(func.sum(AgentLog.cost_usd), 0.0),
        ).group_by("g").all()
        breakdown = []
        for g, calls, bi, bo, bcr, bcw, bcost in brows:
            toks = bi + bo + bcr + bcw
            breakdown.append({
                "key": g or "unknown", "calls": calls,
                "input": bi, "output": bo, "cache_read": bcr, "cache_write": bcw,
                "tokens": toks,
                "cache_hit_pct": round(100.0 * bcr / (bi + bcr), 1) if (bi + bcr) else 0.0,
                "cost_usd": round(bcost or 0.0, 6),
            })
        breakdown.sort(key=lambda r: r["cost_usd"], reverse=True)

        return {"totals": totals, "series": series, "breakdown": breakdown}
