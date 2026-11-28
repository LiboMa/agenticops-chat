"""The model settings an administrator changes beside the agents' own (MVP-2.9.0 N35).

`SETTINGS` names the nine — the three tiers, the executor's smart model, and the five direct callers that fall back
to the cheap tier — by the key `/api/settings` uses (`model_settings`). `view()` gives each one's own value, the
model it resolves to, and what an empty value means (None where it cannot be empty: a tier). `problem(value)` says
why a value cannot be used, the one rule every write of a model setting checks: a Bedrock id while Bedrock is on, or
an enabled chat model of an enabled provider. `issues()` lists the settings in force whose model cannot be used.
"""
from __future__ import annotations

from typing import Optional

from agenticops.llm import registry
from agenticops.llm.refs import parse_ref

SETTINGS = registry.MODEL_SETTINGS                     # the one list (registry, review of 2.9.0)
NEVER_EMPTY = set(registry.TIER_FIELDS)


def effective(field: str) -> str:
    return registry.raw_value(field) or (registry.fallback(field) or "")


def view() -> dict:
    return {name: {"value": registry.raw_value(field), "effective": effective(field),
                   "default": registry.fallback(field)} for name, field in SETTINGS.items()}


def problem(value: str, *, purpose: str = "chat") -> Optional[tuple[str, str]]:
    """(reason, sentence) when `value` cannot be used as a `purpose` model, else None. Reasons: bedrock_off and the
    factory's (unknown_provider, provider_disabled, unknown_model, model_disabled), invalid_ref, wrong_purpose."""
    from agenticops.llm.factory import ModelProviderUnavailable, resolve
    try:
        ref = parse_ref(value)
    except ValueError as e:
        return "invalid_ref", str(e)
    if ref.is_bedrock:
        if not registry.bedrock_enabled():
            return "bedrock_off", "Amazon Bedrock is turned off (Settings → Model providers)"
        return None
    try:
        _cfg, row = resolve(value)
    except ModelProviderUnavailable as e:
        return e.reason, e.detail
    if row.purpose != purpose:
        return "wrong_purpose", f"«{ref.model_id}» of «{ref.provider}» is an {row.purpose} model, not a {purpose} model"
    return None


def issues() -> list[dict]:
    """The model settings in force whose model cannot be used — an agent's, a tier, a direct caller's. `inherited`:
    the setting is empty and its fallback is the one that cannot be used."""
    out = []
    for field in registry.MODEL_SETTING_FIELDS:
        raw = registry.raw_value(field)
        value = registry.effective_value(field)         # an empty smart model is no model of its own: skipped
        if not value:
            continue
        found = problem(value)
        if found:
            out.append({"setting": field, "value": value, "reason": found[0], "inherited": not raw})
    return out
