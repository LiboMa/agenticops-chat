from agenticops.cost import normalize_model_key, compute_cost, compute_cost_breakdown


def test_normalize_strips_prefixes_and_version():
    assert normalize_model_key("global.anthropic.claude-opus-4-6-v1") == "claude-opus-4-6"
    assert normalize_model_key("us.anthropic.claude-opus-4-8") == "claude-opus-4-8"
    assert normalize_model_key("global.anthropic.claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert normalize_model_key("global.anthropic.claude-haiku-4-5-20251001-v1:0") == "claude-haiku-4-5"


def test_compute_cost_opus48():
    # 1M input @15 + 1M output @75 + 1M cache_read @1.50 + 1M cache_write @18.75
    tokens = {"input": 1_000_000, "output": 1_000_000, "cache_read": 1_000_000, "cache_write": 1_000_000}
    assert compute_cost("global.anthropic.claude-opus-4-8", tokens) == 15.0 + 75.0 + 1.50 + 18.75


def test_compute_cost_missing_keys_default_zero():
    assert compute_cost("global.anthropic.claude-sonnet-4-6", {"input": 1_000_000}) == 3.0


def test_unknown_model_returns_zero(caplog):
    assert compute_cost("some.unknown.model", {"input": 1_000_000}) == 0.0


def test_breakdown_sums_to_total():
    tokens = {"input": 500_000, "output": 200_000, "cache_read": 100_000, "cache_write": 0}
    b = compute_cost_breakdown("global.anthropic.claude-sonnet-4-6", tokens)
    assert round(b["total"], 6) == round(b["input"] + b["output"] + b["cache_read"] + b["cache_write"], 6)
    assert b["input"] == 0.5 * 3.0
