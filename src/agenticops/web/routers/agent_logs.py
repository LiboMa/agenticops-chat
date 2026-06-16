"""Agent log / token-tracking API endpoints — extracted from app.py (no logic change)."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func

from agenticops.models import get_db_session

router = APIRouter()


@router.get("/api/agent-logs")
async def api_list_agent_logs(
    agent_name: Optional[str] = None,
    trace_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
):
    """List agent log entries with optional filters."""
    from agenticops.models import AgentLog

    with get_db_session() as db:
        q = db.query(AgentLog)
        if agent_name:
            q = q.filter(AgentLog.agent_name == agent_name)
        if trace_id:
            q = q.filter(AgentLog.trace_id == trace_id)
        if status:
            q = q.filter(AgentLog.status == status)
        rows = q.order_by(AgentLog.created_at.desc()).offset(offset).limit(limit).all()
        return [
            {
                "id": r.id,
                "agent_name": r.agent_name,
                "action": r.action,
                "input_summary": r.input_summary,
                "output_summary": r.output_summary,
                "tool_calls": r.tool_calls,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read_tokens": r.cache_read_tokens,
                "duration_ms": r.duration_ms,
                "status": r.status,
                "error": r.error,
                "trace_id": r.trace_id,
                "parent_agent": r.parent_agent,
                "model_id": r.model_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


@router.get("/api/agent-logs/timeline/{trace_id}")
async def api_agent_log_timeline(trace_id: str):
    """Get agent call chain for a single trace with aggregated totals."""
    from agenticops.models import AgentLog

    with get_db_session() as db:
        rows = (
            db.query(AgentLog)
            .filter(AgentLog.trace_id == trace_id)
            .order_by(AgentLog.created_at.asc())
            .all()
        )
        if not rows:
            raise HTTPException(404, f"No logs found for trace {trace_id}")

        calls = []
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_duration = 0
        for r in rows:
            total_input += r.input_tokens
            total_output += r.output_tokens
            total_cache_read += r.cache_read_tokens
            total_duration += r.duration_ms
            calls.append({
                "id": r.id,
                "agent_name": r.agent_name,
                "action": r.action,
                "parent_agent": r.parent_agent,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read_tokens": r.cache_read_tokens,
                "tool_calls": r.tool_calls,
                "duration_ms": r.duration_ms,
                "status": r.status,
                "model_id": r.model_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

        return {
            "trace_id": trace_id,
            "calls": calls,
            "totals": {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cache_read_tokens": total_cache_read,
                "duration_ms": total_duration,
                "call_count": len(calls),
            },
        }


@router.get("/api/agent-logs/summary")
async def api_agent_log_summary(hours: int = Query(24, le=720)):
    """Per-agent token consumption aggregation over a time window."""
    from agenticops.models import AgentLog

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with get_db_session() as db:
        rows = (
            db.query(
                AgentLog.agent_name,
                func.count(AgentLog.id).label("call_count"),
                func.sum(AgentLog.input_tokens).label("total_input"),
                func.sum(AgentLog.output_tokens).label("total_output"),
                func.sum(AgentLog.cache_read_tokens).label("total_cache_read"),
                func.sum(AgentLog.duration_ms).label("total_duration_ms"),
                func.sum(AgentLog.tool_calls).label("total_tool_calls"),
                func.sum(
                    case((AgentLog.status != "success", 1), else_=0)
                ).label("error_count"),
            )
            .filter(AgentLog.created_at >= cutoff)
            .group_by(AgentLog.agent_name)
            .all()
        )
        per_agent = {}
        grand_input = 0
        grand_output = 0
        for r in rows:
            inp = r.total_input or 0
            out = r.total_output or 0
            grand_input += inp
            grand_output += out
            per_agent[r.agent_name] = {
                "calls": r.call_count,
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_tokens": r.total_cache_read or 0,
                "total_duration_ms": r.total_duration_ms or 0,
                "errors": r.error_count or 0,
                "tool_calls": r.total_tool_calls or 0,
            }

        # Per-model aggregation
        model_rows = (
            db.query(
                AgentLog.model_id,
                func.count(AgentLog.id).label("call_count"),
                func.sum(AgentLog.input_tokens).label("total_input"),
                func.sum(AgentLog.output_tokens).label("total_output"),
                func.sum(AgentLog.cache_read_tokens).label("total_cache_read"),
                func.sum(AgentLog.duration_ms).label("total_duration_ms"),
            )
            .filter(AgentLog.created_at >= cutoff, AgentLog.model_id.isnot(None))
            .group_by(AgentLog.model_id)
            .all()
        )
        per_model = {}
        for r in model_rows:
            model_name = r.model_id or "unknown"
            per_model[model_name] = {
                "calls": r.call_count,
                "input_tokens": r.total_input or 0,
                "output_tokens": r.total_output or 0,
                "cache_read_tokens": r.total_cache_read or 0,
                "total_duration_ms": r.total_duration_ms or 0,
            }

        return {
            "hours": hours,
            "per_agent": per_agent,
            "per_model": per_model,
            "total_input_tokens": grand_input,
            "total_output_tokens": grand_output,
        }
