"""The one place a Strands model is built (MVP-2.9.0 N35).

- A Bedrock model id builds exactly what the agent build sites built before: `BedrockModel` with
  `preamble.bedrock_model_kwargs` (client config, prompt cache, thinking / reasoning fields per family).
- `<provider>::<model>` builds `OpenAIModel` (OpenAI-compatible: LiteLLM proxy, OpenRouter, vLLM, Ollama, LM Studio …)
  or `AnthropicModel` (Anthropic-compatible: Anthropic, Sub2API …) from the stored provider. No Bedrock-only request
  field is ever sent there: the request carries what the model's own attributes (`provider_models`) allow.
- What cannot be built is an explicit `ModelProviderUnavailable` naming the reference and why — Bedrock turned off,
  no such provider, a provider or model turned off, a model not on the provider's list. Nothing falls back to Bedrock
  or to another provider.

Every model built here carries `aiops_ref` = the reference it was built from (`ref_of` reads it): the attachment
delivery and the budget hook judge a model's media by it, since `config["model_id"]` holds only the provider's own id.
"""
from __future__ import annotations

from typing import Any

from agenticops.llm.refs import parse_ref

REASONS = ("bedrock_off", "unknown_provider", "provider_disabled", "model_disabled", "unknown_model")
_OPENAI_EFFORT_TOP = "high"
_AGENT_RETRIES = 1   # an agent's model: one retry — a provider that does not answer fails after two tries, not three     # Chat Completions' reasoning_effort: low | medium | high


class ModelProviderUnavailable(RuntimeError):
    def __init__(self, ref: str, reason: str, detail: str):
        super().__init__(f"model «{ref}» is not available: {detail}")
        self.ref, self.reason, self.detail = ref, reason, detail


def resolve(ref: str):
    """(ProviderConfig, ProviderModelView) for a provider reference, or ModelProviderUnavailable."""
    from agenticops.llm import catalog, registry
    r = parse_ref(ref)
    cfg = registry.get(r.provider)
    if cfg is None:
        raise ModelProviderUnavailable(ref, "unknown_provider", f"there is no provider «{r.provider}»")
    if not cfg.enabled:
        raise ModelProviderUnavailable(ref, "provider_disabled", f"the provider «{r.provider}» is turned off")
    row = catalog.model_row(r.provider, r.model_id)
    if row is None:
        raise ModelProviderUnavailable(ref, "unknown_model",
                                       f"«{r.model_id}» is not on the model list of «{r.provider}» — refresh the list or add it")
    if not row.enabled:
        raise ModelProviderUnavailable(ref, "model_disabled", f"«{r.model_id}» of «{r.provider}» is turned off")
    return cfg, row


def require_bedrock(ref: str) -> None:
    from agenticops.llm import registry
    if not registry.bedrock_enabled():
        raise ModelProviderUnavailable(ref, "bedrock_off", "Amazon Bedrock is turned off (Settings → Model providers)")


def openai_effort(budget: int) -> str:
    """The thinking budget as Chat Completions' `reasoning_effort` (the internal budget → tier rule, capped at high)."""
    from agenticops.agents.preamble import _EFFORT_TIERS, _effort_tier
    tier = _effort_tier(budget)
    return tier if _EFFORT_TIERS.index(tier) <= _EFFORT_TIERS.index(_OPENAI_EFFORT_TOP) else _OPENAI_EFFORT_TOP


def client_args(cfg, *, timeout=None, max_retries: int = 2) -> dict:
    args: dict[str, Any] = {"base_url": cfg.base_url, "api_key": cfg.api_key or "not-needed",
                            "timeout": timeout or cfg.timeout_seconds, "max_retries": max_retries}
    if cfg.extra_headers:
        args["default_headers"] = dict(cfg.extra_headers)
    return args


def build_model(ref: str, *, max_tokens: int, thinking_budget: int = 0, bedrock_cls=None):
    """`bedrock_cls` is the BedrockModel class the caller's module imported (the agent modules pass theirs, so a
    test that patches `<agent module>.BedrockModel` still stands in for the Bedrock build); default Strands' own."""
    r = parse_ref(ref)
    if r.is_bedrock:
        require_bedrock(ref)
        if bedrock_cls is None:
            from strands.models.bedrock import BedrockModel as bedrock_cls
        from agenticops.agents.preamble import bedrock_model_kwargs, thinking_fields_for_budget
        from agenticops.config import get_bedrock_boto_session
        thinking = thinking_fields_for_budget(thinking_budget, max_tokens, ref) if thinking_budget > 0 else None
        model = bedrock_cls(model_id=ref, boto_session=get_bedrock_boto_session(), max_tokens=max_tokens,
                            **bedrock_model_kwargs(ref, thinking))
    else:
        cfg, row = resolve(ref)
        extra: dict[str, Any] = {"context_window_limit": row.context_window} if row.context_window else {}
        if cfg.kind == "anthropic_compatible":
            from strands.models.anthropic import AnthropicModel
            params: dict[str, Any] = {}
            if row.reasoning == "anthropic_thinking" and thinking_budget > 0:
                from agenticops.agents.preamble import thinking_fields_for_budget
                params = thinking_fields_for_budget(thinking_budget, max_tokens, r.model_id) or {}
            from agenticops.config import settings
            if settings.bedrock_cache_enabled and prompt_cache_on(cfg, row):
                from strands.models.model import CacheConfig
                extra["cache_config"] = CacheConfig(strategy="auto", tools_ttl=True, system_prompt_ttl=False)
            model = AnthropicModel(client_args=client_args(cfg, max_retries=_AGENT_RETRIES), model_id=r.model_id, max_tokens=max_tokens,
                                   **({"params": params} if params else {}), **extra)
        else:
            from strands.models.openai import OpenAIModel
            params = {"max_tokens": max_tokens}
            if row.reasoning == "openai_effort" and thinking_budget > 0:
                params["reasoning_effort"] = openai_effort(thinking_budget)
            model = OpenAIModel(client_args=client_args(cfg, max_retries=_AGENT_RETRIES), model_id=r.model_id, params=params, **extra)
    model.aiops_ref = ref
    return model


def prompt_cache_on(cfg, row) -> bool:
    """Whether an Anthropic-compatible model gets prompt-cache points: its row's word, else its platform's
    (`presets.PROMPT_CACHE_PRESETS`) — never its name."""
    from agenticops.llm.presets import PROMPT_CACHE_PRESETS
    if row.prompt_cache is not None:
        return bool(row.prompt_cache)
    return cfg.preset in PROMPT_CACHE_PRESETS


def ref_of(model) -> str | None:
    """The reference a model was built from; for a model not built here, its configured model id."""
    ref = getattr(model, "aiops_ref", None)
    if ref:
        return ref
    config = getattr(model, "config", None) or {}
    return config.get("model_id") if isinstance(config, dict) else None
