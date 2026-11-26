"""A local stand-in for an OpenAI-compatible and an Anthropic-compatible model server (MVP-2.9.0 N35 tests).

One threaded HTTP server on 127.0.0.1 answers both protocols — `/v1/chat/completions`, `/v1/embeddings` and
`/v1/models` (OpenAI shapes: plain, OpenRouter, vLLM) and `/v1/messages`, `/v1/models` (Anthropic shape when the
request carries `anthropic-version`). What it answers is set on the instance: a delay, whether it calls tools, the
reply text, how it stops, the key it requires. Every request is kept in `requests` for assertions.

Also the database helpers the provider tests share: `llm_db(tmp_path, monkeypatch)`, `add_provider`, `add_model`.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Optional

ADMIN = SimpleNamespace(key="user:root", user_id=1)


class FakeLLMServer:
    def __init__(self):
        self.delay = 0.0
        self.tools_supported = True
        self.reply: Optional[str] = None          # None = echo the last user text
        self.stop = "stop"                        # "stop" | "length"
        self.require_key: Optional[str] = None
        self.list_shape = "plain"                 # plain | openrouter | vllm
        self.models = ["fake-chat-1", "fake-embed-1"]
        self.embedding_dim = 8
        self.embed_fail_on: Optional[str] = None    # an embeddings input holding this text is answered 500
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _authorised(self) -> bool:
                if not outer.require_key:
                    return True
                got = self.headers.get("x-api-key") or (self.headers.get("authorization") or "").removeprefix("Bearer ")
                return got == outer.require_key

            def _record(self, body):
                outer.requests.append({"method": self.command, "path": self.path,
                                       "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})

            def do_GET(self):
                self._record(None)
                if not self._authorised():
                    return self._send(401, {"error": {"message": "invalid api key", "type": "authentication_error"}})
                if self.path.startswith("/v1/models"):
                    if self.headers.get("anthropic-version"):
                        return self._send(200, {"data": [{"id": m, "display_name": m.upper(), "type": "model"}
                                                         for m in outer.models], "has_more": False})
                    return self._send(200, {"object": "list", "data": [outer._listing(m) for m in outer.models]})
                self._send(404, {"error": {"message": "not found"}})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._record(body)
                if outer.delay:
                    time.sleep(outer.delay)
                if not self._authorised():
                    return self._send(401, {"error": {"message": "invalid api key", "type": "authentication_error"}})
                if self.path.startswith("/v1/chat/completions"):
                    return self._send(200, outer._chat(body))
                if self.path.startswith("/v1/messages"):
                    return self._send(200, outer._messages(body))
                if self.path.startswith("/v1/embeddings"):
                    items = body.get("input")
                    items = items if isinstance(items, list) else [items]
                    if outer.embed_fail_on and any(outer.embed_fail_on in str(i) for i in items):
                        return self._send(500, {"error": {"message": "embedding backend failed"}})
                    return self._send(200, {"object": "list", "data": [
                        {"object": "embedding", "index": i, "embedding": [0.1 * (i + 1)] * outer.embedding_dim}
                        for i, _ in enumerate(items)], "usage": {"prompt_tokens": 3, "total_tokens": 3}})
                self._send(404, {"error": {"message": "not found"}})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # ── answers ──────────────────────────────────────────────────────────────
    def _listing(self, model_id: str) -> dict:
        row = {"id": model_id, "object": "model", "owned_by": "fake"}
        if self.list_shape == "openrouter":
            row.update({"name": f"Fake {model_id}", "context_length": 131072,
                        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                        "supported_parameters": ["tools", "temperature", "max_tokens"] if "chat" in model_id else ["max_tokens"],
                        "architecture": {"input_modalities": ["text", "image"]}})
        elif self.list_shape == "vllm":
            row["max_model_len"] = 32768
        return row

    def _text_for(self, messages) -> str:
        if self.reply is not None:
            return self.reply
        last = messages[-1] if messages else {}
        content = last.get("content")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        return f"echo: {content}"

    def _chat(self, body) -> dict:
        model = body.get("model")
        if body.get("tools") and self.tools_supported:
            name = body["tools"][0]["function"]["name"]
            return {"id": "c1", "object": "chat.completion", "model": model, "choices": [{
                "index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function",
                                    "function": {"name": name, "arguments": "{}"}}]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}
        text = self._text_for(body.get("messages") or [])
        return {"id": "c1", "object": "chat.completion", "model": model, "choices": [{
            "index": 0, "finish_reason": self.stop, "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}

    def _messages(self, body) -> dict:
        model = body.get("model")
        if body.get("tools") and self.tools_supported:
            name = body["tools"][0]["name"]
            return {"id": "m1", "type": "message", "role": "assistant", "model": model,
                    "content": [{"type": "tool_use", "id": "tu_1", "name": name, "input": {}}],
                    "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 3}}
        text = self._text_for(body.get("messages") or [])
        return {"id": "m1", "type": "message", "role": "assistant", "model": model,
                "content": [{"type": "text", "text": text}] if text else [],
                "stop_reason": "max_tokens" if self.stop == "length" else "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5}}

    # ── lifecycle ────────────────────────────────────────────────────────────
    @property
    def base(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


# ── the database helpers the provider tests share ────────────────────────────

def llm_db(tmp_path, monkeypatch, name: str = "llm.db"):
    """A temp database with the provider tables, a master key for the credential store, fresh caches — swapped in
    through monkeypatch, so what a test caches (Bedrock turned off, a provider, the test's key) ends with it."""
    from agenticops.credentials import store
    from agenticops.llm import registry
    from agenticops.services import runtime_settings
    from tests.test_viewer_role import _temp_db
    settings = _temp_db(tmp_path, monkeypatch, name)
    monkeypatch.delenv("AIOPS_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("AIOPS_MASTER_KEY", "n35-test-master-key-0123456789abcdef")
    monkeypatch.setattr(store, "_store_instance", None)
    monkeypatch.setattr(runtime_settings, "_cache", {})
    monkeypatch.setattr(registry, "_cache", {})
    return settings


def add_provider(name: str, base_url: str, *, kind: str = "openai_compatible", api_key: str = "",
                 timeout_seconds: int = 30, **extra) -> dict:
    from agenticops.llm import registry
    preset = "custom_openai" if kind == "openai_compatible" else "custom_anthropic"
    return registry.create({"name": name, "preset": preset, "kind": kind, "base_url": base_url, "api_key": api_key,
                            "timeout_seconds": timeout_seconds, **extra}, ADMIN)


def add_model(provider: str, model_id: str, **fields) -> None:
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    with get_db_session() as s:
        s.add(ProviderModel(provider=provider, model_id=model_id, label=fields.pop("label", model_id), **fields))
