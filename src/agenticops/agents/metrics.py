"""Unified token-usage extraction from Strands agent results.

Single source of truth so CLI (REPL + headless) and Web all report the same
numbers. Uses accumulated_usage (covers the main agent + every sub-agent call
in the turn), not latest_agent_invocation (which only sees the last call).
"""

from __future__ import annotations

from typing import Any


def extract_token_usage(result: Any) -> dict[str, int]:
    """Return {input, output, cache_read, cache_write} from an agent result.

    Never raises — returns zeros when metrics are absent.
    """
    zero = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    try:
        acc = result.metrics.accumulated_usage  # type: ignore[union-attr]
        if not acc:
            return zero
        return {
            "input": acc.get("inputTokens", 0),
            "output": acc.get("outputTokens", 0),
            "cache_read": acc.get("cacheReadInputTokens", 0),
            "cache_write": acc.get("cacheWriteInputTokens", 0),
        }
    except Exception:
        return zero
