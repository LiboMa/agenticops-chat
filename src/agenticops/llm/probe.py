"""The connection test of a provider (MVP-2.9.0 N35): three steps, each with its own time limit
(`model_providers.test_timeout_seconds`) and no retry —

1. **list**: read the model list (the same request `catalog.refresh` makes; nothing is written);
2. **chat**: one short message to the model;
3. **tools**: one message with one tool the model is asked to call — an agent cannot work without tool calls, and a
   local model does not always make them.

The outcome is kept on the provider (`last_test`) and, for the tool step, on the model (`tools_probe`) — never over
what an admin set (`supports_tools`). Errors are said without the key. The model may be one not on the list yet (a
provider just added); `model_id` defaults to the provider's first enabled chat model.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

TOOL_NAME = "report_ready"
_TOOL_DESCRIPTION = "Call this to report that you are ready."


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _step(fn, cfg):
    from agenticops.llm.catalog import describe_error
    start = time.monotonic()
    try:
        extra = fn() or {}
        return {"ok": True, "ms": _ms(start), "error": None, **extra}
    except Exception as e:  # noqa: BLE001 — the test reports, it never raises
        return {"ok": False, "ms": _ms(start), "error": describe_error(e, cfg)}


def _chat(cfg, model_id: str, timeout: int, *, with_tool: bool) -> dict:
    from agenticops.llm.factory import client_args
    args = client_args(cfg, timeout=timeout, max_retries=0)
    if cfg.kind == "anthropic_compatible":
        import anthropic
        kwargs: dict = {"model": model_id, "max_tokens": 64,
                        "messages": [{"role": "user", "content": f"Call the {TOOL_NAME} tool now." if with_tool
                                      else "Reply with the single word: ok"}]}
        if with_tool:
            kwargs["tools"] = [{"name": TOOL_NAME, "description": _TOOL_DESCRIPTION,
                                "input_schema": {"type": "object", "properties": {}}}]
        resp = anthropic.Anthropic(**args).messages.create(**kwargs)
        called = any(getattr(b, "type", "") == "tool_use" for b in resp.content)
    else:
        import openai
        kwargs = {"model": model_id, "max_tokens": 64,
                  "messages": [{"role": "user", "content": f"Call the {TOOL_NAME} tool now." if with_tool
                                else "Reply with the single word: ok"}]}
        if with_tool:
            kwargs["tools"] = [{"type": "function", "function": {
                "name": TOOL_NAME, "description": _TOOL_DESCRIPTION, "parameters": {"type": "object", "properties": {}}}}]
            kwargs["tool_choice"] = "auto"
        resp = openai.OpenAI(**args).chat.completions.create(**kwargs)
        called = bool(resp.choices and resp.choices[0].message.tool_calls)
    if with_tool and not called:
        raise RuntimeError("no tool call — the model answered in text: agents cannot use this model")
    return {}


def test(provider: str, model_id: Optional[str]) -> dict:
    from agenticops.config import settings
    from agenticops.llm import catalog, registry
    from agenticops.llm.models import ModelProvider, ProviderModel
    from agenticops.models import get_db_session
    cfg = registry.get(provider)
    if cfg is None:
        raise registry.ProviderError(404, "not_found", f"no provider «{provider}»")
    if not model_id:
        chats = catalog.list_models(provider, purpose="chat", enabled_only=True)
        if not chats:
            raise registry.ProviderError(422, "no_model", "name a model to test — the provider has no model on its list yet")
        model_id = chats[0].model_id
    timeout = int(min(settings.model_providers.test_timeout_seconds, cfg.timeout_seconds))
    listed: dict = {}

    def _list():
        items = catalog.fetch_listing(cfg, timeout=timeout)
        listed["count"] = len(items)
        return {"count": len(items)}

    result = {"model_id": model_id, "at": datetime.now(timezone.utc).isoformat(),
              "list": _step(_list, cfg)}
    result["list"].setdefault("count", listed.get("count"))
    result["chat"] = _step(lambda: _chat(cfg, model_id, timeout, with_tool=False), cfg)
    result["tools"] = (_step(lambda: _chat(cfg, model_id, timeout, with_tool=True), cfg) if result["chat"]["ok"]
                       else {"ok": False, "ms": 0, "error": "not tried — the chat step failed"})
    with get_db_session() as s:
        row = s.query(ModelProvider).filter_by(name=provider).first()
        if row is not None:
            row.last_test = result
        if result["chat"]["ok"]:
            model = s.query(ProviderModel).filter_by(provider=provider, model_id=model_id).first()
            if model is not None:
                model.tools_probe = "passed" if result["tools"]["ok"] else "failed"
                model.tools_probe_at = datetime.now(timezone.utc)
    registry.reset_cache()
    return result
