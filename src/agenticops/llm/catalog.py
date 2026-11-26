"""The models each provider offers (MVP-2.9.0 N35): what the code knows about one model — `model_row` — and, from
task 3 on, reading a provider's list, adding by hand and editing a model's attributes."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from agenticops.llm.presets import ANTHROPIC

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderModelView:
    provider: str
    model_id: str
    label: str = ""
    purpose: str = "chat"                      # chat | embedding
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    supports_tools: Optional[bool] = None      # None = not known
    tools_probe: Optional[str] = None          # passed | failed
    tools_probe_at: Optional[datetime] = None
    supports_images: bool = False
    supports_documents: bool = False
    reasoning: str = "none"                    # one of REASONING
    accepts_temperature: Optional[bool] = None # None = not said: not sent
    prompt_cache: Optional[bool] = None        # None = the platform's default (Anthropic-compatible only)
    price_input: Optional[float] = None        # USD per 1M tokens
    price_output: Optional[float] = None
    price_cache_read: Optional[float] = None
    price_cache_write: Optional[float] = None
    source: str = "discovered"
    enabled: bool = True
    manual_fields: list = field(default_factory=list)


def view_of(row) -> ProviderModelView:
    return ProviderModelView(
        provider=row.provider, model_id=row.model_id, label=row.label or row.model_id, purpose=row.purpose or "chat",
        context_window=row.context_window, max_output_tokens=row.max_output_tokens, supports_tools=row.supports_tools,
        tools_probe=row.tools_probe, tools_probe_at=row.tools_probe_at, supports_images=bool(row.supports_images),
        supports_documents=bool(row.supports_documents), reasoning=row.reasoning or "none",
        accepts_temperature=row.accepts_temperature, prompt_cache=row.prompt_cache, price_input=row.price_input, price_output=row.price_output, price_cache_read=row.price_cache_read,
        price_cache_write=row.price_cache_write, source=row.source or "discovered", enabled=bool(row.enabled),
        manual_fields=list(row.manual_fields or []))


def model_row(provider: str, model_id: str) -> Optional[ProviderModelView]:
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    with get_db_session() as s:
        row = s.query(ProviderModel).filter_by(provider=provider, model_id=model_id).first()
        return view_of(row) if row is not None else None


# ── reading a provider's list (task 3) ───────────────────────────────────────

EDITABLE = ("label", "purpose", "context_window", "max_output_tokens", "supports_tools", "supports_images",
            "supports_documents", "reasoning", "accepts_temperature", "prompt_cache", "price_input", "price_output",
            "price_cache_read", "price_cache_write")
PURPOSES = ("chat", "embedding")
# A thinking model's request shape — the row says it, nothing reads the model's name: the OpenAI field, or one of
# the three Anthropic shapes (adaptive + a summary while it thinks: Claude 4.7+; adaptive: 4.6; a token budget: older)
ANTHROPIC_REASONING = ("anthropic_adaptive_summarized", "anthropic_adaptive", "anthropic_budget")
REASONING = ("none", "openai_effort") + ANTHROPIC_REASONING
ANTHROPIC_VERSION = "2023-06-01"


def effective_tools(view: ProviderModelView) -> Optional[bool]:
    """Whether the model calls tools: what the list or an admin said, else what the last connection test found."""
    if view.supports_tools is not None:
        return view.supports_tools
    return {"passed": True, "failed": False}.get(view.tools_probe or "")


def list_request(cfg) -> tuple[str, dict]:
    """The URL and headers of a provider's model list — the key in a header, never in the URL."""
    headers = dict(cfg.extra_headers or {})
    if cfg.kind == ANTHROPIC:
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if cfg.api_key:
            headers["x-api-key"] = cfg.api_key
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        return f"{cfg.base_url}/v1/models", headers
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    return f"{cfg.base_url}/models", headers


def fetch_listing(cfg, *, timeout: float) -> list[dict]:
    """The provider's model list as raw dicts. Raises on HTTP / network errors (the caller words them)."""
    import httpx
    url, headers = list_request(cfg)
    resp = httpx.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else body
    return [d for d in (data or []) if isinstance(d, dict) and d.get("id")]


def _per_million(value) -> Optional[float]:
    try:
        return round(float(value) * 1_000_000, 6)
    except (TypeError, ValueError):
        return None


def parse_listing(item: dict) -> dict:
    """What a list entry says about a model (only the fields it really carries). Nothing is read off the model's
    name (review of MVP-2.9.0, the owner: no guessing) — no list field says what a model is for, so a new row is a
    chat model until an admin marks it an embedding one, and a refresh leaves the purpose alone."""
    model_id = str(item["id"])
    out: dict = {"label": str(item.get("name") or item.get("display_name") or model_id)[:300]}
    window = item.get("context_length") or item.get("max_model_len") or item.get("context_window")
    if isinstance(window, int) and window > 0:
        out["context_window"] = window
    pricing = item.get("pricing")
    if isinstance(pricing, dict):
        if _per_million(pricing.get("prompt")) is not None:
            out["price_input"] = _per_million(pricing.get("prompt"))
        if _per_million(pricing.get("completion")) is not None:
            out["price_output"] = _per_million(pricing.get("completion"))
    params = item.get("supported_parameters")
    if isinstance(params, list):
        out["supports_tools"] = "tools" in params
        out["accepts_temperature"] = "temperature" in params
    modalities = (item.get("architecture") or {}).get("input_modalities") if isinstance(item.get("architecture"), dict) else None
    if isinstance(modalities, list):
        out["supports_images"] = "image" in modalities
        out["supports_documents"] = "file" in modalities
    return out


class OwnMessage(RuntimeError):
    """An error whose text is ours, never a provider's or a library's — shown as it is (the connection test's
    «no tool call — …»)."""


def describe_error(exc: Exception, cfg=None) -> str:
    """A short, key-free sentence for an HTTP / SDK error."""
    import httpx
    if isinstance(exc, OwnMessage):
        return str(exc)
    status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)
    name = type(exc).__name__
    if status in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        text = f"authentication failed ({status or 401}) — check the API key"
    elif status == 404 or "NotFound" in name:
        text = "not found (404) — check the address and the model id"
    elif isinstance(exc, (httpx.TimeoutException,)) or "Timeout" in name:
        text = "timed out"
    elif isinstance(exc, httpx.ConnectError) or "Connection" in name:
        text = "could not connect — check the address and that the server is running"
    elif status:
        text = f"the server answered {status}"
    else:
        text = name   # never the error's own text: it can quote a key or header value (final review)
    key = getattr(cfg, "api_key", "") if cfg is not None else ""
    if key:
        text = text.replace(key, "****")
    from agenticops.security.redaction import redact_secrets
    return redact_secrets(text)


def refresh_enabled() -> dict:
    """Read every ENABLED provider's model list again — at startup, in a background thread (the spec: «启动时只刷新开着的
    提供方的模型列表»). A turned-off provider is not contacted; one that cannot be read keeps its models (refresh says
    why) and stops nothing. {name: refresh's answer}; never raises."""
    from types import SimpleNamespace
    from agenticops.llm import registry
    actor = SimpleNamespace(key="system:startup", user_id=None)
    out: dict = {}
    try:
        names = [p["name"] for p in registry.list_public() if p.get("enabled")]
    except Exception:
        logger.warning("model providers: could not list them for the startup refresh", exc_info=True)
        return out
    for name in names:
        try:
            out[name] = refresh(name, actor)
        except Exception as e:  # noqa: BLE001 — one provider never stops the others
            out[name] = {"error": type(e).__name__}
        if out[name].get("error"):
            logger.warning("model providers: «%s» model list not read at startup: %s", name, out[name]["error"])
    return out


def refresh(provider: str, actor) -> dict:
    from agenticops.config import settings
    from agenticops.llm import registry
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    cfg = registry.get(provider)
    if cfg is None:
        raise registry.ProviderError(404, "not_found", f"no provider «{provider}»")
    try:
        listing = fetch_listing(cfg, timeout=settings.model_providers.test_timeout_seconds)
    except Exception as e:  # noqa: BLE001 — every failure keeps the models and is said
        return {"added": 0, "updated": 0, "unchanged": 0, "error": describe_error(e, cfg)}
    added = updated = unchanged = 0
    now = datetime.now(timezone.utc)
    with get_db_session() as s:
        rows = {r.model_id: r for r in s.query(ProviderModel).filter_by(provider=provider)}
        seen: set[str] = set()
        for item in listing:
            if str(item["id"]) in seen:   # a list that names a model twice: the first one counts
                continue
            seen.add(str(item["id"]))
            facts = parse_listing(item)
            row = rows.get(str(item["id"]))
            if row is None:
                s.add(ProviderModel(provider=provider, model_id=str(item["id"]), source="discovered", enabled=True,
                                    manual_fields=[], updated_at=now, **facts))
                added += 1
                continue
            manual = set(row.manual_fields or [])
            changed = False
            for key, value in facts.items():
                if key not in manual and getattr(row, key) != value:
                    setattr(row, key, value)
                    changed = True
            if changed:
                row.updated_at = now
                updated += 1
            else:
                unchanged += 1
        registry._audit(s, "refresh_models", provider, actor,
                        details={"added": added, "updated": updated, "unchanged": unchanged})
    return {"added": added, "updated": updated, "unchanged": unchanged, "error": None}


def list_models(provider: str, *, purpose: Optional[str] = None, enabled_only: bool = False) -> list[ProviderModelView]:
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    with get_db_session() as s:
        q = s.query(ProviderModel).filter_by(provider=provider)
        if purpose:
            q = q.filter_by(purpose=purpose)
        if enabled_only:
            q = q.filter(ProviderModel.enabled.is_(True))
        return [view_of(r) for r in q.order_by(ProviderModel.model_id)]


def _check_fields(data: dict) -> dict:
    from agenticops.llm import registry
    out: dict = {}
    for key, value in data.items():
        if key not in EDITABLE:
            continue
        bad = False
        if key == "purpose":
            bad = value not in PURPOSES
        elif key == "reasoning":
            bad = value not in REASONING
        elif key == "label":
            bad = not isinstance(value, str)
            value = (value or "")[:300] if not bad else value
        elif key in ("context_window", "max_output_tokens"):
            bad = value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0)
        elif key.startswith("price_"):
            bad = value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0)
        elif key in ("supports_tools", "accepts_temperature", "prompt_cache"):     # yes / no / not said
            bad = value is not None and not isinstance(value, bool)
        else:  # supports_images / supports_documents
            bad = not isinstance(value, bool)
        if bad:
            raise registry.ProviderError(422, "invalid_model_field", f"«{key}» has a value it cannot take",
                                         extra={"field": key})
        out[key] = value
    return out


def add_manual(provider: str, data: dict, actor) -> ProviderModelView:
    from agenticops.llm import registry
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    if registry.get(provider) is None:
        raise registry.ProviderError(404, "not_found", f"no provider «{provider}»")
    model_id = (data.get("model_id") or "").strip() if isinstance(data.get("model_id"), str) else ""
    if not model_id or len(model_id) > 300:
        raise registry.ProviderError(422, "invalid_model_field", "a model id is needed", extra={"field": "model_id"})
    fields = _check_fields(data)
    with get_db_session() as s:
        if s.query(ProviderModel).filter_by(provider=provider, model_id=model_id).first() is not None:
            raise registry.ProviderError(409, "model_exists", f"«{model_id}» is already on the list of «{provider}»")
        defaults = {"label": model_id, "purpose": "chat"}       # an embedding model is said so, never guessed
        row = ProviderModel(provider=provider, model_id=model_id, source="manual", enabled=True,
                            manual_fields=sorted(fields), updated_at=datetime.now(timezone.utc),
                            **{**defaults, **fields})
        s.add(row)
        s.flush()
        registry._audit(s, "add_model", provider, actor, after={"model_id": model_id, **fields})
        return view_of(row)


def patch_model(provider: str, model_id: str, data: dict, actor) -> ProviderModelView:
    from agenticops.llm import registry
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    fields = _check_fields(data)
    enabled = data.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise registry.ProviderError(422, "invalid_model_field", "«enabled» is true or false", extra={"field": "enabled"})
    with get_db_session() as s:
        row = s.query(ProviderModel).filter_by(provider=provider, model_id=model_id).first()
        if row is None:
            raise registry.ProviderError(404, "not_found", f"«{model_id}» is not on the list of «{provider}»")
        if enabled is False and row.enabled:
            registry._refuse_in_use(provider, model_id)
        before = {k: getattr(row, k) for k in fields}
        for key, value in fields.items():
            setattr(row, key, value)
        if fields:
            row.manual_fields = sorted(set(row.manual_fields or []) | set(fields))
        if enabled is not None:
            row.enabled = enabled
        row.updated_at = datetime.now(timezone.utc)
        s.flush()
        registry._audit(s, "update_model", provider, actor, before={"model_id": model_id, **before},
                        after={"model_id": model_id, **fields, **({"enabled": enabled} if enabled is not None else {})})
        return view_of(row)


def all_presets(*, purpose: str = "chat") -> list[dict]:
    """Every enabled model of every enabled provider, as the model pickers list them."""
    from agenticops.llm.models import ModelProvider, ProviderModel
    from agenticops.llm.refs import format_ref
    from agenticops.models import get_db_session
    out = []
    try:
        with get_db_session() as s:
            providers = {p.name: p for p in s.query(ModelProvider).filter(ModelProvider.enabled.is_(True))}
            rows = (s.query(ProviderModel).filter(ProviderModel.enabled.is_(True), ProviderModel.purpose == purpose)
                    .order_by(ProviderModel.provider, ProviderModel.model_id).all())
            views = [view_of(r) for r in rows if r.provider in providers]
            labels = {name: (p.display_name or name) for name, p in providers.items()}
    except Exception:   # a database without the tables: no provider models
        return []
    for v in views:
        out.append({"label": v.label or v.model_id, "value": format_ref(v.provider, v.model_id),
                    "context_window": v.context_window, "provider": v.provider,
                    "provider_label": labels.get(v.provider, v.provider), "purpose": v.purpose,
                    "capabilities": {"tools": effective_tools(v), "images": v.supports_images,
                                     "documents": v.supports_documents, "reasoning": v.reasoning},
                    "priced": v.price_input is not None or v.price_output is not None})
    return out
