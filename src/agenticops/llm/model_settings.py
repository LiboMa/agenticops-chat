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

SETTINGS = {
    "tier_default": "bedrock_model_id",
    "tier_cheap": "bedrock_model_id_cheap",
    "tier_strong": "bedrock_model_id_strong",
    "executor_simple": "executor_simple_model_id",
    "security": "security_model_id",
    "report_translation": "report_translation_model_id",
    "signal_gate": "signal_gate_llm_model",
    "rca_critic": "rca_critic_model_id",
    "galaxy": "galaxy_model_id",
}
NEVER_EMPTY = set(registry.TIER_FIELDS)


def fallback(field: str) -> Optional[str]:
    """What an empty value of this setting means; None for a setting that cannot be empty."""
    from agenticops.config import get_agent_model_config, settings
    if field in NEVER_EMPTY:
        return None
    if field == "executor_simple_model_id":            # no smart model: the executor runs on its own
        return get_agent_model_config("executor")[0]
    return str(settings.bedrock_model_id_cheap or "")


def effective(field: str) -> str:
    raw = registry._raw(field)
    return raw or (fallback(field) or "")


def view() -> dict:
    return {name: {"value": registry._raw(field), "effective": effective(field), "default": fallback(field)}
            for name, field in SETTINGS.items()}


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
        raw = registry._raw(field)
        value = registry.effective_value(field)         # an empty smart model is no model of its own: skipped
        if not value:
            continue
        found = problem(value)
        if found:
            out.append({"setting": field, "value": value, "reason": found[0], "inherited": not raw})
    return out
