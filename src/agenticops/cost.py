"""Pure token→USD cost computation, table-driven from config.token_cost_table.

Never raises: an unknown model yields 0.0 + one WARNING. Snapshot semantics —
callers store the returned value; historical cost is not recomputed.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_TOKEN_KEYS = ("input", "output", "cache_read", "cache_write")


def normalize_model_key(model_id: str) -> str:
    """Map a full Bedrock model id to a token_cost_table key.

    e.g. 'global.anthropic.claude-opus-4-6-v1' -> 'claude-opus-4-6'
         'global.anthropic.claude-haiku-4-5-20251001-v1:0' -> 'claude-haiku-4-5'
         'openai.gpt-oss-120b-1:0' -> 'gpt-oss-120b'
         'global.openai.gpt-5.6-terra' -> 'gpt-5.6-terra'
    """
    if not model_id:
        return ""
    key = model_id.strip()
    # drop region/provider prefixes
    key = re.sub(r"^(global|us|eu|apac)\.", "", key)
    key = re.sub(r"^(anthropic|openai)\.", "", key)
    # claude-<family>-<major>-<minor> ... keep through the minor version
    m = re.match(r"(claude-[a-z]+-\d+-\d+)", key)
    if m:
        return m.group(1)
    # other providers: strip a trailing Bedrock version suffix ('-1:0')
    return re.sub(r"-\d+:\d+$", "", key)


def _rates(model_id: str) -> dict | None:
    from agenticops.config import settings
    table = settings.token_cost_table or {}
    key = normalize_model_key(model_id)
    rates = table.get(key)
    if rates is None:
        logger.warning("No cost rates for model '%s' (key '%s'); cost=0", model_id, key)
    return rates


def compute_cost_breakdown(model_id: str, tokens: dict) -> dict:
    """Per-category USD cost. Missing token keys / unknown model → 0."""
    rates = _rates(model_id)
    out = {k: 0.0 for k in _TOKEN_KEYS}
    if rates:
        for k in _TOKEN_KEYS:
            out[k] = (int(tokens.get(k, 0) or 0) / 1_000_000.0) * float(rates.get(k, 0.0))
    out["total"] = sum(out[k] for k in _TOKEN_KEYS)
    return out


def compute_cost(model_id: str, tokens: dict) -> float:
    """Total USD cost for a token dict. Never raises."""
    return compute_cost_breakdown(model_id, tokens)["total"]
