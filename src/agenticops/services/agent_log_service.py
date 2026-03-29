"""Agent log service — fire-and-forget token tracking for agent calls.

Records agent invocation metrics (tokens, duration, tool calls) into the
agent_logs table. Best-effort: errors are logged, never raised.
"""

import logging
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class _AgentTracker:
    """Accumulates metrics from a Strands agent result."""

    __slots__ = ("input_tokens", "output_tokens", "cache_read_tokens",
                 "tool_call_count", "output_summary", "status", "error")

    def __init__(self):
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_read_tokens: int = 0
        self.tool_call_count: int = 0
        self.output_summary: str = ""
        self.status: str = "success"
        self.error: Optional[str] = None

    def set_result(self, result) -> None:
        """Extract metrics from a Strands agent result object."""
        try:
            usage = result.metrics.accumulated_usage
            if usage:
                self.input_tokens = usage.get("inputTokens", 0)
                self.output_tokens = usage.get("outputTokens", 0)
                self.cache_read_tokens = usage.get("cacheReadInputTokens", 0)
        except Exception:
            pass

        try:
            tool_metrics = result.metrics.tool_metrics
            if tool_metrics:
                self.tool_call_count = sum(
                    m.get("call_count", 1) if isinstance(m, dict) else 1
                    for m in (tool_metrics.values() if isinstance(tool_metrics, dict) else tool_metrics)
                )
        except Exception:
            pass

        try:
            text = str(result)
            self.output_summary = text[:500] if text else ""
        except Exception:
            pass


def log_agent_call(
    agent_name: str,
    action: str,
    input_summary: str,
    output_summary: str = "",
    tool_calls: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    duration_ms: int = 0,
    status: str = "success",
    error: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_agent: Optional[str] = None,
    model_id: Optional[str] = None,
) -> None:
    """Fire-and-forget DB write for an agent call. Errors logged, never raised."""
    try:
        from agenticops.models import AgentLog, get_db_session

        with get_db_session() as db:
            db.add(AgentLog(
                agent_name=agent_name,
                action=action,
                input_summary=input_summary[:1000],
                output_summary=output_summary[:1000],
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                duration_ms=duration_ms,
                status=status,
                error=error[:1000] if error else None,
                trace_id=trace_id,
                parent_agent=parent_agent,
                model_id=model_id,
            ))
    except Exception:
        logger.debug("Failed to log agent call for %s", agent_name, exc_info=True)


@contextmanager
def track_agent(
    agent_name: str,
    action: str,
    input_summary: str,
    parent_agent: Optional[str] = None,
):
    """Context manager that records agent invocation metrics.

    Usage::

        with track_agent("scan", "scan_resources", "services=all", parent_agent="main") as tracker:
            result = invoke_with_retry(agent, prompt)
            tracker.set_result(result)
    """
    from agenticops.config import get_trace_id, get_agent_model_config

    tracker = _AgentTracker()
    start = time.monotonic()

    try:
        yield tracker
    except Exception as exc:
        tracker.status = "error"
        tracker.error = str(exc)[:500]
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        try:
            model_id, _ = get_agent_model_config(agent_name)
        except Exception:
            model_id = None

        log_agent_call(
            agent_name=agent_name,
            action=action,
            input_summary=input_summary,
            output_summary=tracker.output_summary,
            tool_calls=tracker.tool_call_count,
            input_tokens=tracker.input_tokens,
            output_tokens=tracker.output_tokens,
            cache_read_tokens=tracker.cache_read_tokens,
            duration_ms=duration_ms,
            status=tracker.status,
            error=tracker.error,
            trace_id=get_trace_id(),
            parent_agent=parent_agent,
            model_id=model_id,
        )
