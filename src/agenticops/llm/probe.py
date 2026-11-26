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

from agenticops.llm import catalog

TOOL_NAME = "report_ready"
_MAX_TOKENS = 512   # room for a model that thinks before it answers or calls the tool (64 cut qwen3-style models off)
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
    from agenticops.llm.direct import send      # the one place a chat request to a provider is built
    reply = send(cfg, model_id, f"Call the {TOOL_NAME} tool now." if with_tool else "Reply with the single word: ok",
                 max_tokens=_MAX_TOKENS, tool=(TOOL_NAME, _TOOL_DESCRIPTION) if with_tool else None,
                 timeout=timeout, max_retries=0)
    called, cut = reply.tool_called, reply.truncated
    if with_tool and not called and cut:
        raise catalog.OwnMessage(f"cut at the output limit ({_MAX_TOKENS} tokens) before it called the tool — a model "
                                 "that thinks first may need more: test again, or set «calls tools» by hand")
    if with_tool and not called:
        raise catalog.OwnMessage("no tool call — the model answered in text: agents cannot use this model")
    return {}


def run(cfg, model_id: str) -> dict:
    """The three steps on `cfg` — writes nothing."""
    from agenticops.config import settings
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
    return result


def test(provider: str, model_id: Optional[str]) -> dict:
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
    result = run(cfg, model_id)
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


def test_draft(data: dict) -> dict:
    """The test of a provider before it is saved (MVP-2.9.0 review): `data` is the form (+ `provider` = the stored
    one an edit starts from, `model_id`), checked as saving it would check it. Nothing is written. Without a model
    the first chat model of the provider's listing is tried; a listing with none (or that cannot be read) is 422
    `no_model` only when nothing was typed — a typed model is always tried, so a wrong address shows as steps."""
    from agenticops.config import settings
    from agenticops.llm import registry
    existing = data.get("provider") if isinstance(data.get("provider"), str) and data.get("provider") else None
    cfg = registry.draft_config(data, existing)
    model_id = data.get("model_id") if isinstance(data.get("model_id"), str) and data["model_id"].strip() else None
    if model_id is None:
        timeout = int(min(settings.model_providers.test_timeout_seconds, cfg.timeout_seconds))
        try:
            items = catalog.fetch_listing(cfg, timeout=timeout)
        except Exception as e:  # noqa: BLE001 — said as the list step, the key never in it
            return {"model_id": None, "at": datetime.now(timezone.utc).isoformat(),
                    "list": {"ok": False, "ms": 0, "error": catalog.describe_error(e, cfg), "count": None},
                    "chat": {"ok": False, "ms": 0, "error": "not tried — the model list could not be read"},
                    "tools": {"ok": False, "ms": 0, "error": "not tried — the chat step failed"}}
        chats = [str(i["id"]) for i in items if catalog.parse_listing(i)["purpose"] == "chat"]
        if not chats:
            raise registry.ProviderError(422, "no_model", "name a model to test — the provider lists no chat model")
        model_id = chats[0]
    return run(cfg, model_id.strip())
