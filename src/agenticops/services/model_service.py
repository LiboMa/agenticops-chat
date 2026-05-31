"""Model discovery service — dynamic model listing from AWS Bedrock.

Fetches available Claude models from Bedrock API (us-east-1), generates
standard + 1M context variants, caches with TTL, falls back to config.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Cache: (timestamp, data)
_models_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])
_CACHE_TTL = 86400  # 24 hours


def _fetch_bedrock_models(region: str = "us-east-1") -> list[dict[str, Any]]:
    """Call Bedrock API to list available Anthropic models."""
    from agenticops.config import get_bedrock_boto_session

    client = get_bedrock_boto_session().client("bedrock")
    response = client.list_foundation_models(byProvider="Anthropic")

    models = []
    for m in response.get("modelSummaries", []):
        # Filter: TEXT output, ACTIVE status
        if "TEXT" not in m.get("outputModalities", []):
            continue
        if m.get("modelLifecycle", {}).get("status") != "ACTIVE":
            continue

        model_id = m.get("modelId", "")
        model_name = m.get("modelName", "")

        # Skip embedding or non-claude models
        if "claude" not in model_id.lower() and "claude" not in model_name.lower():
            continue

        # Extract context window from input token limit
        input_tokens = 0
        if "inferenceTypesSupported" in m:
            # Try to get from response metadata
            pass

        # Build label from model name
        label = model_name or model_id

        models.append({
            "model_id": model_id,
            "model_name": model_name,
            "context_window": input_tokens,
            "streaming": "STREAMING" in m.get("inferenceTypesSupported", []),
        })

    return models


def _build_presets_from_bedrock(raw_models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw Bedrock model list into preset entries.

    Note: Bedrock does NOT support [1m] suffix for model IDs.
    Context window is 200K by default for Claude 4.x models.
    Use window_size agent config to control actual context usage.
    """
    import re

    presets = []
    seen_ids = set()

    for m in raw_models:
        model_id = m["model_id"]
        if model_id in seen_ids:
            continue
        seen_ids.add(model_id)

        # Use global. prefix for cross-region inference compatibility
        global_id = f"global.{model_id}" if not model_id.startswith("global.") else model_id

        # Extract version label (e.g., "4.6", "4.5")
        version = ""
        match = re.search(r"claude-(\w+)-(\d+[\.\-]\d+)", model_id)
        if match:
            family = match.group(1).capitalize()  # opus, sonnet, haiku
            version = match.group(2).replace("-", ".")
        else:
            family = m.get("model_name", model_id).split(" ")[0]

        label = f"{family} {version}" if version else family
        presets.append({
            "label": label,
            "value": global_id,
            "context_window": 200000,
        })

    # Sort: Opus first, then Sonnet, then Haiku; latest version first
    family_order = {"Opus": 0, "Sonnet": 1, "Haiku": 2}

    def _sort_key(p):
        parts = p["label"].split(" ")
        fam = parts[0]
        ver = 0.0
        if len(parts) >= 2:
            try:
                ver = float(parts[1])
            except ValueError:
                pass
        return (family_order.get(fam, 99), -ver)

    presets.sort(key=_sort_key)

    return presets


def _get_fallback_presets() -> list[dict[str, Any]]:
    """Return hardcoded fallback presets when Bedrock API is unavailable."""
    from agenticops.config import settings

    # Use MODEL_ALIASES as base
    aliases = dict(settings.model_aliases)

    presets = []
    for alias, model_id in aliases.items():
        family = alias.capitalize()
        presets.append({
            "label": family,
            "value": model_id,
            "context_window": 200000,
        })

    return presets


def get_model_presets(region: str = "us-east-1") -> list[dict[str, Any]]:
    """Return model presets for UI/CLI — cached, with Bedrock API + fallback.

    Returns list of:
        {"label": "Opus 4.6 (1M)", "value": "global.anthropic.claude-opus-4-6-v1[1m]", "context_window": 1000000}
    """
    global _models_cache

    now = time.time()
    cached_at, cached_data = _models_cache
    if cached_data and (now - cached_at) < _CACHE_TTL:
        return cached_data

    # Try Bedrock API
    try:
        raw = _fetch_bedrock_models(region)
        if raw:
            presets = _build_presets_from_bedrock(raw)
            logger.info("Refreshed model list from Bedrock: %d presets", len(presets))
        else:
            presets = _get_fallback_presets()
            logger.warning("Bedrock returned no models, using fallback")
    except Exception as e:
        logger.warning("Bedrock list_foundation_models failed: %s — using fallback", e)
        presets = _get_fallback_presets()

    # Merge custom_models from settings.yaml
    from agenticops.config import settings
    for custom in getattr(settings, "custom_models", []):
        if isinstance(custom, dict) and "model_id" in custom:
            presets.append({
                "label": custom.get("label", custom["model_id"]),
                "value": custom["model_id"],
                "context_window": custom.get("context_window", 200000),
            })

    # Deduplicate by value
    seen = set()
    deduped = []
    for p in presets:
        if p["value"] not in seen:
            seen.add(p["value"])
            deduped.append(p)

    _models_cache = (now, deduped)
    return deduped


def invalidate_cache() -> None:
    """Force refresh on next call."""
    global _models_cache
    _models_cache = (0.0, [])
