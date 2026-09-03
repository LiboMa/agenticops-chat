"""Model discovery service — dynamic model listing from AWS Bedrock.

Fetches available Anthropic (Claude) and OpenAI (gpt-oss / gpt-5.x) models
from the Bedrock API, resolves inference-profile ids where required, caches
with TTL, falls back to config.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Cache: (timestamp, data)
_models_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])
_CACHE_TTL = 86400  # 24 hours

# Providers surfaced in the model picker. Anthropic is the platform default;
# OpenAI covers the ChatGPT-family models Bedrock offers (gpt-oss-*, gpt-5.x).
_PROVIDERS = ("Anthropic", "OpenAI")


def _fetch_inference_profile_ids(client) -> set[str]:
    """All SYSTEM_DEFINED inference-profile ids (e.g. 'global.openai.gpt-5.6-sol').

    Needed to resolve an invokable id for models that only support
    INFERENCE_PROFILE inference (no ON_DEMAND). Fail-soft: caller handles
    exceptions and falls back to a 'global.' prefix guess.
    """
    ids: set[str] = set()
    token = None
    while True:
        kwargs: dict[str, Any] = {"typeEquals": "SYSTEM_DEFINED", "maxResults": 250}
        if token:
            kwargs["nextToken"] = token
        resp = client.list_inference_profiles(**kwargs)
        for p in resp.get("inferenceProfileSummaries", []):
            pid = p.get("inferenceProfileId", "")
            if pid:
                ids.add(pid)
        token = resp.get("nextToken")
        if not token:
            return ids


def _resolve_invoke_id(model_id: str, inference_types: list[str],
                       profile_ids: set[str] | None) -> str:
    """Map a foundation-model id to the id actually used for invocation.

    ON_DEMAND models invoke by raw id. INFERENCE_PROFILE-only models need a
    system profile — prefer 'global.' (cross-region), then 'us.'.
    """
    if "ON_DEMAND" in inference_types:
        return model_id
    for prefix in ("global.", "us."):
        candidate = f"{prefix}{model_id}"
        if profile_ids is None or candidate in profile_ids:
            return candidate
    return f"global.{model_id}"  # best guess when no profile is listed


def _fetch_bedrock_models(region: str = "us-east-1") -> list[dict[str, Any]]:
    """Call Bedrock API to list available Anthropic + OpenAI models."""
    from agenticops.config import get_bedrock_boto_session

    client = get_bedrock_boto_session().client("bedrock")

    models: list[dict[str, Any]] = []
    errors: list[Exception] = []
    profile_ids: set[str] | None = None

    for provider in _PROVIDERS:
        try:
            response = client.list_foundation_models(byProvider=provider)
        except Exception as e:  # one provider failing must not hide the others
            logger.warning("list_foundation_models(%s) failed: %s", provider, e)
            errors.append(e)
            continue

        for m in response.get("modelSummaries", []):
            # Filter: TEXT output, ACTIVE status
            if "TEXT" not in m.get("outputModalities", []):
                continue
            if m.get("modelLifecycle", {}).get("status") != "ACTIVE":
                continue

            model_id = m.get("modelId", "")
            model_name = m.get("modelName", "")

            # Anthropic list includes embeddings etc. — keep claude only
            if provider == "Anthropic" and "claude" not in model_id.lower() \
                    and "claude" not in model_name.lower():
                continue

            inference_types = list(m.get("inferenceTypesSupported", []))
            invoke_id = model_id
            if provider == "OpenAI" and "ON_DEMAND" not in inference_types:
                if profile_ids is None:
                    try:
                        profile_ids = _fetch_inference_profile_ids(client)
                    except Exception as e:
                        logger.warning("list_inference_profiles failed: %s — "
                                       "guessing 'global.' profile ids", e)
                        profile_ids = set()  # _resolve_invoke_id falls through to guess
                invoke_id = _resolve_invoke_id(model_id, inference_types,
                                               profile_ids or None)

            models.append({
                "model_id": model_id,
                "model_name": model_name,
                "provider": provider.lower(),
                "invoke_id": invoke_id,
                "context_window": 0,
                "streaming": "STREAMING" in inference_types,
            })

    if not models and errors:
        raise errors[0]
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

        if m.get("provider") == "openai":
            # invoke_id already resolved (raw for ON_DEMAND, profile otherwise)
            value = m.get("invoke_id") or model_id
            label = m.get("model_name") or model_id
            # gpt-oss = 128K context; gpt-5.x larger (display metadata only)
            window = 128000 if "gpt-oss" in model_id else 400000
            presets.append({
                "label": label,
                "value": value,
                "context_window": window,
            })
            continue

        # Anthropic: use global. prefix for cross-region inference compatibility
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

    # Sort: Claude families first (Opus, Sonnet, Haiku — latest version first),
    # then OpenAI gpt-5.x, then gpt-oss.
    family_order = {"Opus": 0, "Sonnet": 1, "Haiku": 2}

    def _sort_key(p):
        value = p["value"]
        if "openai." in value:
            return (11, 0.0) if "gpt-oss" in value else (10, 0.0)
        parts = p["label"].split(" ")
        fam = parts[0]
        ver = 0.0
        if len(parts) >= 2:
            try:
                ver = float(parts[1])
            except ValueError:
                pass
        return (family_order.get(fam, 9), -ver)

    presets.sort(key=_sort_key)

    return presets


def _get_fallback_presets() -> list[dict[str, Any]]:
    """Return hardcoded fallback presets when Bedrock API is unavailable."""
    from agenticops.config import settings

    # Use MODEL_ALIASES as base
    aliases = dict(settings.model_aliases)

    presets = []
    for alias, model_id in aliases.items():
        # keep gpt-* aliases verbatim ('gpt-oss-120b'.capitalize() mangles them)
        family = alias if alias.lower().startswith("gpt") else alias.capitalize()
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
