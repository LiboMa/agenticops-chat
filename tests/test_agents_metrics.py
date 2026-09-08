"""Unit tests for agenticops.agents.metrics — token usage extraction."""

from types import SimpleNamespace

from agenticops.agents.metrics import extract_token_usage


class TestExtractTokenUsage:
    """Tests for extract_token_usage helper."""

    def test_returns_zeros_when_result_is_none(self):
        assert extract_token_usage(None) == {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0
        }

    def test_returns_zeros_when_no_metrics_attr(self):
        result = SimpleNamespace()
        assert extract_token_usage(result) == {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0
        }

    def test_returns_zeros_when_accumulated_usage_is_none(self):
        result = SimpleNamespace(metrics=SimpleNamespace(accumulated_usage=None))
        assert extract_token_usage(result) == {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0
        }

    def test_returns_zeros_when_accumulated_usage_is_empty(self):
        result = SimpleNamespace(metrics=SimpleNamespace(accumulated_usage={}))
        assert extract_token_usage(result) == {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0
        }

    def test_extracts_all_fields(self):
        usage = {
            "inputTokens": 1500,
            "outputTokens": 300,
            "cacheReadInputTokens": 200,
            "cacheWriteInputTokens": 50,
        }
        result = SimpleNamespace(metrics=SimpleNamespace(accumulated_usage=usage))
        assert extract_token_usage(result) == {
            "input": 1500, "output": 300, "cache_read": 200, "cache_write": 50
        }

    def test_missing_cache_fields_default_to_zero(self):
        usage = {"inputTokens": 100, "outputTokens": 50}
        result = SimpleNamespace(metrics=SimpleNamespace(accumulated_usage=usage))
        out = extract_token_usage(result)
        assert out["input"] == 100
        assert out["output"] == 50
        assert out["cache_read"] == 0
        assert out["cache_write"] == 0

    def test_handles_exception_gracefully(self):
        # metrics.accumulated_usage raises
        class BadMetrics:
            @property
            def accumulated_usage(self):
                raise RuntimeError("boom")

        result = SimpleNamespace(metrics=BadMetrics())
        assert extract_token_usage(result) == {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0
        }

    def test_non_dict_accumulated_usage(self):
        # If accumulated_usage is a non-falsy non-dict, .get will throw
        result = SimpleNamespace(metrics=SimpleNamespace(accumulated_usage=42))
        assert extract_token_usage(result) == {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0
        }
