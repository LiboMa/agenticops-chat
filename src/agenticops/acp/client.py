"""Self-implemented ACP client: spawn an ACP agent subprocess and drive it over
newline-delimited JSON-RPC 2.0 (stdio). No third-party ACP dependency.

Shared by the claude-code / kiro providers; the provider supplies the launch
command + env and consumes the yielded EnhancedEvents.

Spike findings baked in (claude-agent-acp 0.42.0):
  - initialize negotiates protocolVersion 1
  - session/update payloads are nested: params.update.sessionUpdate
  - terminal session/prompt result carries usage {inputTokens, outputTokens, ...}
"""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, Optional

from agenticops.acp.jsonrpc import encode_message, read_message
from agenticops.acp.mapping import acp_update_to_event
from agenticops.acp.types import EnhancedEvent


def _safe_env(extra: Optional[dict] = None) -> dict:
    """Subprocess env using the mcp_manager recipe: minimal base + AWS creds."""
    from mcp.client.stdio import get_default_environment
    env = get_default_environment()
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_AUTHORIZATION_TOKEN"):
        v = os.environ.get(key)
        if v:
            env[key] = v
    if extra:
        env.update(extra)
    return env


class AcpClient:
    def __init__(self, command: str, args: list[str], env_extra: Optional[dict] = None,
                 auto_approve: bool = True, timeout: int = 300, protocol_version: int = 1):
        self._command = command
        self._args = args
        self._env = _safe_env(env_extra)
        self._auto_approve = auto_approve
        self._timeout = timeout
        self._protocol_version = protocol_version
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._next_id = 0

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _send(self, method: str, params: dict) -> int:
        rid = self._new_id()
        self._proc.stdin.write(encode_message({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
        await self._proc.stdin.drain()
        return rid

    async def _respond(self, rid, result: dict) -> None:
        self._proc.stdin.write(encode_message({"jsonrpc": "2.0", "id": rid, "result": result}))
        await self._proc.stdin.drain()

    async def cancel(self) -> None:
        if not self._proc:
            return
        # Reap the child + close the stdin pipe within the loop's lifetime.
        # Otherwise the transport's delayed __del__ fires after the loop closes
        # (enhanced_task uses asyncio.run(), a short-lived loop) and raises
        # "RuntimeError: Event loop is closed". The leak is the STDIN pipe
        # transport, not just the process — so we must close stdin explicitly
        # and yield a tick for the transport to tear down.
        if self._proc.returncode is None:
            for sig in ("terminate", "kill"):
                try:
                    getattr(self._proc, sig)()
                except ProcessLookupError:
                    break
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                    break  # reaped cleanly
                except asyncio.TimeoutError:
                    continue  # escalate terminate -> kill
                except Exception:
                    break
        # Close ALL pipe transports (stdin writer + stdout/stderr reader
        # transports), not just stdin — each leaked transport raises on __del__.
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        for stream in (self._proc.stdout, self._proc.stderr):
            tr = getattr(stream, "_transport", None) if stream else None
            try:
                if tr:
                    tr.close()
            except Exception:
                pass
        try:
            await asyncio.sleep(0)  # let the pipe transports finish closing
        except Exception:
            pass

    async def run(self, prompt_text: str, cwd: Optional[str] = None) -> AsyncIterator[EnhancedEvent]:
        """Launch, handshake, prompt, and yield EnhancedEvents until done/error."""
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._command, *self._args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env=self._env,
            )
        except FileNotFoundError:
            yield EnhancedEvent(kind="error", error=f"Enhanced backend command not found: {self._command}")
            return

        try:
            # initialize  (spike: claude-agent-acp 0.42.0 negotiates protocolVersion 1;
            # per-provider override via protocol_version ctor arg)
            init_id = await self._send("initialize", {"protocolVersion": self._protocol_version, "capabilities": {},
                                                      "clientInfo": {"name": "agenticops", "version": "1.3.0"}})
            if not await self._await_result(init_id):
                yield EnhancedEvent(kind="error", error="ACP initialize failed")
                return

            # session/new
            sid_id = await self._send("session/new", {"cwd": cwd or os.getcwd(), "mcpServers": []})
            sess = await self._await_result(sid_id)
            if not sess or "result" not in sess:
                yield EnhancedEvent(kind="error", error="ACP session/new failed")
                return
            session_id = sess["result"].get("sessionId")

            # session/prompt + stream
            pid = await self._send("session/prompt", {"sessionId": session_id,
                                                      "prompt": [{"type": "text", "text": prompt_text}]})
            async for ev in self._stream_until_result(pid):
                yield ev
        except asyncio.TimeoutError:
            yield EnhancedEvent(kind="error", error="Enhanced backend timed out")
        finally:
            await self.cancel()

    async def _read(self):
        return await asyncio.wait_for(read_message(self._proc.stdout), self._timeout)

    async def _maybe_permission(self, obj) -> bool:
        if obj.get("method") == "session/request_permission" and self._auto_approve:
            opts = obj["params"].get("options", [])
            pick = next((o for o in opts if o.get("kind") == "allow_once"), opts[0] if opts else {})
            await self._respond(obj["id"], {"outcome": {"outcome": "selected", "optionId": pick.get("optionId")}})
            return True
        return False

    async def _await_result(self, rid):
        while True:
            obj = await self._read()
            if obj is None:
                return None
            if await self._maybe_permission(obj):
                continue
            if obj.get("id") == rid and ("result" in obj or "error" in obj):
                return obj

    async def _stream_until_result(self, rid) -> AsyncIterator[EnhancedEvent]:
        while True:
            obj = await self._read()
            if obj is None:
                yield EnhancedEvent(kind="error", error="Enhanced backend closed unexpectedly")
                return
            if await self._maybe_permission(obj):
                continue
            if obj.get("method") == "session/update":
                params = obj.get("params", {})
                update = params.get("update", params)   # spike: shape is nested
                ev = acp_update_to_event(update)
                if ev is not None:
                    yield ev
            if obj.get("id") == rid and ("result" in obj or "error" in obj):
                if "error" in obj:
                    yield EnhancedEvent(kind="error", error=str(obj["error"]))
                else:
                    # spike: terminal result carries usage {inputTokens, outputTokens, ...}
                    usage = (obj["result"] or {}).get("usage") or {}
                    tokens = {"input": usage.get("inputTokens", 0),
                              "output": usage.get("outputTokens", 0)} if usage else None
                    yield EnhancedEvent(kind="done", tokens=tokens)
                return
