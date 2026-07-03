# tests/test_message_token_usage.py
"""Verify per-message token_usage carries cost_usd + trace_id."""

from agenticops.cost import compute_cost


def test_message_token_usage_includes_cost():
    tu = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write": 0,
          "model": "global.anthropic.claude-sonnet-4-6"}
    tu["cost_usd"] = compute_cost(tu["model"], tu)
    assert tu["cost_usd"] == 3.0
    assert set(tu) >= {"input", "output", "cache_read", "cache_write", "cost_usd", "model"}


def test_schema_has_trace_and_cost_fields():
    from agenticops.web.schemas import ChatMessageResponse
    fields = ChatMessageResponse.model_fields
    assert "trace_id" in fields
    assert "cost_usd" in fields
