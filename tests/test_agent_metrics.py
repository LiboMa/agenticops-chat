"""Tests for unified token-usage extraction (agents/metrics.py)."""
from types import SimpleNamespace

from agenticops.agents.metrics import extract_token_usage


def _result_with_accumulated(inp, out, cr=0, cw=0):
    acc = {"inputTokens": inp, "outputTokens": out,
           "cacheReadInputTokens": cr, "cacheWriteInputTokens": cw}
    return SimpleNamespace(metrics=SimpleNamespace(accumulated_usage=acc))


def test_extracts_accumulated_usage():
    usage = extract_token_usage(_result_with_accumulated(100, 50, 10, 5))
    assert usage == {"input": 100, "output": 50, "cache_read": 10, "cache_write": 5}


def test_missing_metrics_returns_zeros():
    usage = extract_token_usage(SimpleNamespace())
    assert usage == {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


def test_none_result_returns_zeros():
    usage = extract_token_usage(None)
    assert usage == {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
