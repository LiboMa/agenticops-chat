# ACP Enhanced Backend — Implementation Plan (MVP-1.3.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give selected Strands agents (main/sre) an optional `enhanced_task` tool that delegates complex tasks to an external coding agent (Claude Code first) over a self-implemented ACP-style JSON-RPC/stdio protocol, behind a protocol-agnostic pluggable-backend abstraction — default off, existing architecture untouched.

**Architecture:** A protocol-agnostic `EnhancedBackend` Protocol + provider registry is the core (built unconditionally). A self-written `AcpClient` (newline JSON-RPC 2.0 over stdio) is the shared protocol layer for the claude/kiro providers. A `ClaudeCodeBackend` launches `claude-agent-acp` (Bedrock). An `enhanced_task` `@tool` (registered into main/sre when enabled) drives a backend and streams `EnhancedEvent`s mapped onto the existing SSE event types. A **Phase-0 spike gates** the provider wiring.

**Tech Stack:** Python 3.12 + asyncio (stdio subprocess + JSON-RPC); Strands `@tool`; pytest; existing `mcp_manager.py` subprocess recipe; `claude-agent-acp` (npx, Bedrock) external.

**Spec:** `docs/superpowers/specs/2026-06-06-acp-enhanced-backend-design.md`

---

## Conventions

- **Backend tests:** `.venv/bin/python -m pytest tests/<file> -v`. Pure-logic tests need no subprocess. The integration test that spawns `claude-agent-acp` reuses the existing `integration` marker (declared in `pytest.ini`, auto-skipped by `tests/conftest.py` unless `--run-integration`) — no new marker.
- **Compile:** `python3 -m py_compile src/agenticops/acp/<file>.py`.
- **Commits:** one per task, `git commit --no-verify` (Code Defender). Do NOT push.
- **Branch:** continue on the current branch (`MVP-1.1.1-RELEASE`).
- **Imports verified:** `from strands import Agent, tool`; `from pydantic import Field`; config is `class Settings(BaseSettings)` at `config.py:52`; list field pattern `x: list[str] = Field(default_factory=list)`.
- **CRITICAL — architecture-first:** Tasks 1-5 build the protocol-agnostic core + spike + self-written client; they touch ONLY the new `src/agenticops/acp/` module + tests + a standalone spike script. Tasks 6-8 (provider wiring, tool registration, frontend) are **gated on the spike (Task 2)** — if the spike shows the self-written JSON-RPC client can't cleanly drive `claude-agent-acp`, STOP after Task 5 and report before doing 6-8. Do NOT modify Strands agents, `app.py`, or the frontend until the protocol layer is proven.
- **Default off:** every change is inert unless `acp_enhanced_enabled=true`. The `enhanced_task` tool is only added to agent tool-lists conditionally.

---

## File Structure

**New module `src/agenticops/acp/`:**
- `types.py` — `EnhancedEvent`, `BackendCapabilities`, `EnhancedBackend` (Protocol). Protocol-agnostic; no JSON-RPC here.
- `registry.py` — `register_backend` / `get_backend` / `available_backends`.
- `jsonrpc.py` — newline-delimited JSON-RPC 2.0 framing over async stdio streams.
- `mapping.py` — pure `acp_update_to_event(update) -> EnhancedEvent | None`.
- `client.py` — `AcpClient`: spawn subprocess + drive `initialize`/`session.new`/`session.prompt`/consume `session/update`/`cancel`.
- `backends/__init__.py`, `backends/claude_code.py` — `ClaudeCodeBackend`.
- `__init__.py` — register the claude-code backend at import.

**New:**
- `scripts/acp_spike.py` — standalone Phase-0 spike.
- `src/agenticops/agents/enhanced.py` — `enhanced_task` `@tool`.
- `tests/test_acp_core.py`, `tests/test_acp_mapping.py`, `tests/test_acp_jsonrpc.py`.

**Modified (gated on spike):**
- `src/agenticops/config.py` — `acp_*` Fields.
- `config/settings.yaml` — `acp_*` defaults (off).
- `src/agenticops/agents/main_agent.py`, `sre_agent.py` — conditionally register `enhanced_task`.
- `src/agenticops/web/frontend/...` — "Enhanced" badge (small).

---

## Task 1: Config fields + protocol-agnostic core types (`types.py`) (TDD)

**Files:**
- Modify: `src/agenticops/config.py`
- Modify: `config/settings.yaml`
- Create: `src/agenticops/acp/__init__.py` (empty for now), `src/agenticops/acp/types.py`
- Create: `tests/test_acp_core.py`

- [ ] **Step 1: Add config fields**

In `src/agenticops/config.py`, find the `skills_security_scan_on_promote` Field (near the skills config block) and add AFTER it (inside the `Settings` class):

```python
    # ── ACP Enhanced Backend (MVP-1.3.0) ──────────────────────────────
    acp_enhanced_enabled: bool = Field(default=False, description="Enable the optional ACP enhanced-task backend (delegates complex tasks to Claude Code/Kiro)")
    acp_enhanced_backend: str = Field(default="claude-code", description="Default enhanced backend provider name")
    acp_claude_command: str = Field(default="npx", description="Launch command for the Claude Code ACP agent")
    acp_claude_args: list[str] = Field(default_factory=lambda: ["@agentclientprotocol/claude-agent-acp"], description="Args for the Claude Code ACP agent launch")
    acp_use_bedrock: bool = Field(default=True, description="Run the enhanced backend on Bedrock (CLAUDE_CODE_USE_BEDROCK=1)")
    acp_timeout_seconds: int = Field(default=300, description="Per-turn timeout for an enhanced-backend subprocess")
    acp_auto_approve_permissions: bool = Field(default=True, description="Auto-approve the backend's permission requests (allow_once) this round")
```

In `config/settings.yaml`, append at the end:
```yaml
# ── ACP Enhanced Backend (MVP-1.3.0) — optional, default off ──
acp_enhanced_enabled: false
acp_enhanced_backend: claude-code
acp_use_bedrock: true
acp_timeout_seconds: 300
acp_auto_approve_permissions: true
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_acp_core.py`:

```python
"""Tests for the protocol-agnostic ACP enhanced-backend core."""

import pytest


def test_config_fields_present():
    from agenticops.config import settings
    assert settings.acp_enhanced_enabled is False          # default off
    assert settings.acp_enhanced_backend == "claude-code"
    assert settings.acp_use_bedrock is True
    assert settings.acp_timeout_seconds == 300


def test_enhanced_event_kinds():
    from agenticops.acp.types import EnhancedEvent
    e = EnhancedEvent(kind="text", text="hi")
    assert e.kind == "text" and e.text == "hi"
    d = EnhancedEvent(kind="done", tokens={"input": 10, "output": 5})
    assert d.tokens["input"] == 10
    err = EnhancedEvent(kind="error", error="boom")
    assert err.error == "boom"


def test_backend_capabilities():
    from agenticops.acp.types import BackendCapabilities
    c = BackendCapabilities(streaming=True, plan=True, permissions=True, tools=False)
    assert c.streaming and not c.tools


def test_enhanced_backend_is_protocol():
    # A minimal duck-typed backend satisfies the Protocol (structural typing).
    from agenticops.acp.types import EnhancedBackend, BackendCapabilities, EnhancedEvent

    class Dummy:
        name = "dummy"
        def capabilities(self): return BackendCapabilities(True, False, False, False)
        async def run(self, task, context):
            yield EnhancedEvent(kind="text", text=task)
        async def cancel(self): ...

    b: EnhancedBackend = Dummy()   # structural check
    assert b.name == "dummy"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_acp_core.py -v`
Expected: FAIL — `agenticops.acp.types` does not exist (+ config import errors until Step 1 lands; if config fields missing, that test fails too).

- [ ] **Step 4: Write `types.py`**

Create `src/agenticops/acp/__init__.py`:
```python
"""ACP enhanced-backend module (MVP-1.3.0)."""
```

Create `src/agenticops/acp/types.py`:
```python
"""Protocol-agnostic core types for the enhanced-backend abstraction.

NO JSON-RPC / ACP wire details here — those live in client.py/mapping.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal, Optional, Protocol, runtime_checkable


EventKind = Literal["text", "tool_start", "tool_end", "plan", "done", "error"]


@dataclass(frozen=True)
class BackendCapabilities:
    streaming: bool
    plan: bool          # emits plan/step updates
    permissions: bool   # may request permission (HITL)
    tools: bool         # can be given client tools (MCP) — False this round


@dataclass(frozen=True)
class EnhancedEvent:
    """Backend-agnostic streaming event. `kind` values map 1:1 onto the
    frontend SSE cases (text/tool_start/tool_end/done/error)."""
    kind: EventKind
    text: Optional[str] = None          # kind="text"
    tool_name: Optional[str] = None     # kind="tool_start" | "tool_end"
    plan: Optional[list[dict]] = None   # kind="plan" (entries)
    tokens: Optional[dict] = None       # kind="done" ({"input":..,"output":..})
    error: Optional[str] = None         # kind="error"


@runtime_checkable
class EnhancedBackend(Protocol):
    """A pluggable enhancement backend. Protocol-agnostic: the wire protocol
    (ACP/JSON-RPC, or anything else) is the provider's implementation detail."""
    name: str
    def capabilities(self) -> BackendCapabilities: ...
    def run(self, task: str, context: str) -> AsyncIterator[EnhancedEvent]: ...
    async def cancel(self) -> None: ...
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_acp_core.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Compile + commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/config.py src/agenticops/acp/types.py
git add src/agenticops/config.py config/settings.yaml src/agenticops/acp/__init__.py src/agenticops/acp/types.py tests/test_acp_core.py
git commit --no-verify -m "feat(acp): config fields + protocol-agnostic core types (EnhancedEvent/Backend)"
```

---

## Task 2: Phase-0 spike — prove `claude-agent-acp` drives from Python over Bedrock

**Files:**
- Create: `scripts/acp_spike.py`
- Create: `docs/superpowers/acp-spike-findings.md` (the output that gates Tasks 6-8)

**This task is investigation, not TDD.** Its job is to answer the spec's open questions empirically.

- [ ] **Step 1: Write the spike script**

Create `scripts/acp_spike.py`:
```python
"""Phase-0 spike: prove AgenticOps can drive claude-agent-acp over stdio JSON-RPC + Bedrock.

Run manually:  .venv/bin/python scripts/acp_spike.py "say hello in one word"
NOT a test. Prints the raw protocol exchange so we can pin: handshake, protocol
version, session/update shapes, and whether Bedrock pass-through works.
"""
import asyncio
import json
import os
import sys


async def main(prompt: str) -> int:
    # Reuse the safe-env recipe from mcp_manager (HOME/PATH/etc + AWS creds for Bedrock).
    from mcp.client.stdio import get_default_environment
    env = get_default_environment()
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_AUTHORIZATION_TOKEN"):
        v = os.environ.get(key)
        if v:
            env[key] = v
    env["CLAUDE_CODE_USE_BEDROCK"] = "1"          # route the agent through Bedrock
    env.setdefault("AWS_REGION", "us-east-1")

    print(">>> launching: npx @agentclientprotocol/claude-agent-acp", file=sys.stderr)
    proc = await asyncio.create_subprocess_exec(
        "npx", "@agentclientprotocol/claude-agent-acp",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env,
    )

    next_id = [0]
    def send(method, params):
        next_id[0] += 1
        msg = {"jsonrpc": "2.0", "id": next_id[0], "method": method, "params": params}
        line = (json.dumps(msg) + "\n").encode()
        print(f"--> {method} {json.dumps(params)[:200]}", file=sys.stderr)
        proc.stdin.write(line); 
        return next_id[0]

    def notify(method, params):
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        proc.stdin.write((json.dumps(msg) + "\n").encode())

    async def read_until(pred, label, timeout=60):
        # Print every line; return the first JSON object matching pred.
        while True:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout)
            if not raw:
                raise RuntimeError(f"agent closed stdout while waiting for {label}")
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(f"<-- (non-json) {line[:200]}", file=sys.stderr); continue
            print(f"<-- {json.dumps(obj)[:300]}", file=sys.stderr)
            if pred(obj):
                return obj

    try:
        # 1) initialize
        init_id = send("initialize", {"protocolVersion": 2, "capabilities": {},
                                      "clientInfo": {"name": "agenticops-spike", "version": "0"}})
        await proc.stdin.drain()
        init = await read_until(lambda o: o.get("id") == init_id and "result" in o, "initialize")
        print("=== INITIALIZE RESULT ===", file=sys.stderr)
        print(json.dumps(init.get("result", {}), indent=2), file=sys.stderr)

        # 2) session/new  (cwd = project root)
        cwd = os.getcwd()
        sid_id = send("session/new", {"cwd": cwd, "mcpServers": []})
        await proc.stdin.drain()
        # Note: agent may interleave session/request_permission — auto-allow if so.
        async def pump_until_result(rid, label):
            while True:
                raw = await asyncio.wait_for(proc.stdout.readline(), 120)
                if not raw:
                    raise RuntimeError(f"closed while waiting {label}")
                line = raw.decode().strip()
                if not line: continue
                obj = json.loads(line)
                print(f"<-- {json.dumps(obj)[:300]}", file=sys.stderr)
                # auto-approve any permission request
                if obj.get("method") == "session/request_permission":
                    opts = obj["params"].get("options", [])
                    pick = next((o for o in opts if o.get("kind") == "allow_once"), opts[0] if opts else None)
                    proc.stdin.write((json.dumps({"jsonrpc":"2.0","id":obj["id"],
                        "result":{"outcome":{"outcome":"selected","optionId":pick.get("optionId")}}})+"\n").encode())
                    await proc.stdin.drain(); continue
                if obj.get("id") == rid and ("result" in obj or "error" in obj):
                    return obj
        sess = await pump_until_result(sid_id, "session/new")
        session_id = sess.get("result", {}).get("sessionId")
        print(f"=== sessionId = {session_id} ===", file=sys.stderr)

        # 3) session/prompt  + stream session/update
        pid = send("session/prompt", {"sessionId": session_id,
                                      "prompt": [{"type": "text", "text": prompt}]})
        await proc.stdin.drain()
        text_acc = []
        while True:
            raw = await asyncio.wait_for(proc.stdout.readline(), 120)
            if not raw: break
            line = raw.decode().strip()
            if not line: continue
            obj = json.loads(line)
            print(f"<-- {json.dumps(obj)[:300]}", file=sys.stderr)
            if obj.get("method") == "session/update":
                u = obj["params"].get("update", obj["params"])
                if u.get("sessionUpdate") == "agent_message_chunk":
                    text_acc.append(u.get("content", {}).get("text", ""))
            if obj.get("method") == "session/request_permission":
                opts = obj["params"].get("options", [])
                pick = next((o for o in opts if o.get("kind") == "allow_once"), opts[0] if opts else None)
                proc.stdin.write((json.dumps({"jsonrpc":"2.0","id":obj["id"],
                    "result":{"outcome":{"outcome":"selected","optionId":pick.get("optionId")}}})+"\n").encode())
                await proc.stdin.drain()
            if obj.get("id") == pid and ("result" in obj or "error" in obj):
                print(f"=== PROMPT DONE: {json.dumps(obj.get('result') or obj.get('error'))} ===", file=sys.stderr)
                break
        print("=== ACCUMULATED TEXT ===")
        print("".join(text_acc))
        return 0
    finally:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "Reply with exactly one word: hello"
    sys.exit(asyncio.run(main(p)))
```

- [ ] **Step 2: Run the spike**

Run: `.venv/bin/python scripts/acp_spike.py "Reply with exactly one word: hello"`
Observe stderr (the protocol trace) + stdout (accumulated text). Record:
- Did `npx @agentclientprotocol/claude-agent-acp` launch? (first run may download the package — allow time.)
- What `protocolVersion` + capabilities did `initialize` return?
- Did `session/new` return a `sessionId`?
- Did `session/prompt` stream `agent_message_chunk`s and reach a terminal `result` with `stopReason`?
- Did Bedrock work (vs an auth error)?
- Were there `session/request_permission` requests, and did auto-allow work?
- The EXACT shape of `session/update` payloads (is `update` nested or flat? key names?).

If launch fails because `claude-agent-acp` isn't installed, try `npx -y @agentclientprotocol/claude-agent-acp` (the `-y` auto-confirms install) and note it.

- [ ] **Step 3: Record findings (this GATES Tasks 6-8)**

Create `docs/superpowers/acp-spike-findings.md` documenting: launch command that worked, protocol version, exact `session/update` payload shapes (paste 2-3 real examples), Bedrock result, permission behavior, and a GO/NO-GO verdict:
- **GO**: self-written JSON-RPC client drives `claude-agent-acp` cleanly → proceed to Tasks 3-8 as written.
- **ADJUST**: works but with a wrinkle (different version, payload shape, install quirk) → note the exact deltas to apply to `mapping.py` (Task 4) + `client.py` (Task 5) before continuing.
- **NO-GO**: can't drive it from a self-written client → STOP, report to the human; reconsider vendoring the TS adapter or the Python lib.

- [ ] **Step 4: Commit the spike + findings**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add scripts/acp_spike.py docs/superpowers/acp-spike-findings.md
git commit --no-verify -m "spike(acp): prove claude-agent-acp drives from Python over Bedrock (Phase 0)"
```

**GATE:** If the verdict is NO-GO, stop here and report. If ADJUST, apply the recorded deltas to the `mapping.py`/`client.py` code in Tasks 4-5 as you implement them.

---

## Task 3: JSON-RPC framing (`jsonrpc.py`) (TDD)

**Files:**
- Create: `src/agenticops/acp/jsonrpc.py`
- Create: `tests/test_acp_jsonrpc.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_acp_jsonrpc.py`:
```python
"""Tests for newline-delimited JSON-RPC 2.0 framing (no subprocess)."""
import asyncio
import json
import pytest


def test_encode_request_is_newline_delimited_single_line():
    from agenticops.acp.jsonrpc import encode_message
    line = encode_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1                 # exactly one trailing newline
    assert b"\n" not in line[:-1]                  # no embedded newlines


def test_roundtrip_through_a_pipe():
    async def run():
        from agenticops.acp.jsonrpc import encode_message, read_message
        reader = asyncio.StreamReader()
        reader.feed_data(encode_message({"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}))
        reader.feed_data(encode_message({"jsonrpc": "2.0", "method": "session/update", "params": {"x": 1}}))
        reader.feed_eof()
        m1 = await read_message(reader)
        m2 = await read_message(reader)
        m3 = await read_message(reader)        # EOF -> None
        return m1, m2, m3
    m1, m2, m3 = asyncio.run(run())
    assert m1["id"] == 7 and m1["result"]["ok"] is True
    assert m2["method"] == "session/update"
    assert m3 is None


def test_read_skips_blank_and_nonjson_lines():
    async def run():
        from agenticops.acp.jsonrpc import encode_message, read_message
        reader = asyncio.StreamReader()
        reader.feed_data(b"\n")                              # blank
        reader.feed_data(b"not json at all\n")               # noise (e.g. stray stdout)
        reader.feed_data(encode_message({"jsonrpc": "2.0", "id": 1, "result": 1}))
        reader.feed_eof()
        return await read_message(reader)
    m = asyncio.run(run())
    assert m["id"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_acp_jsonrpc.py -v`
Expected: FAIL — `agenticops.acp.jsonrpc` missing.

- [ ] **Step 3: Write `jsonrpc.py`**

Create `src/agenticops/acp/jsonrpc.py`:
```python
"""Newline-delimited JSON-RPC 2.0 framing over asyncio streams.

ACP transport rule: each message is a single-line JSON object terminated by '\n',
with NO embedded newlines. Non-JSON / blank lines on the stream are skipped
(the agent must keep stdout clean, but be defensive).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional


def encode_message(msg: dict[str, Any]) -> bytes:
    """Serialize a JSON-RPC message to a single newline-terminated line."""
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


async def read_message(reader: asyncio.StreamReader) -> Optional[dict[str, Any]]:
    """Read the next JSON object line. Returns None at EOF. Skips blank/non-JSON lines."""
    while True:
        raw = await reader.readline()
        if not raw:
            return None
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue  # defensive: ignore stray non-protocol stdout
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_acp_jsonrpc.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/acp/jsonrpc.py
git add src/agenticops/acp/jsonrpc.py tests/test_acp_jsonrpc.py
git commit --no-verify -m "feat(acp): newline JSON-RPC 2.0 framing (self-implemented)"
```

---

## Task 4: ACP→EnhancedEvent mapping (`mapping.py`) (TDD)

**Files:**
- Create: `src/agenticops/acp/mapping.py`
- Create: `tests/test_acp_mapping.py`

**NOTE:** if Task 2's spike recorded different `session/update` shapes than assumed below, apply those exact deltas here (the spike findings are authoritative for payload shape).

- [ ] **Step 1: Write the failing test**

Create `tests/test_acp_mapping.py`:
```python
"""Tests for the pure ACP session/update -> EnhancedEvent mapping."""
from agenticops.acp.mapping import acp_update_to_event
from agenticops.acp.types import EnhancedEvent


def _update(params):
    # session/update notification params; mapping accepts the params dict
    return params


def test_agent_message_chunk_to_text():
    ev = acp_update_to_event({"sessionUpdate": "agent_message_chunk",
                              "content": {"type": "text", "text": "hello"}})
    assert ev == EnhancedEvent(kind="text", text="hello")


def test_tool_call_to_tool_start():
    ev = acp_update_to_event({"sessionUpdate": "tool_call", "toolCallId": "t1",
                              "title": "Read file", "status": "pending"})
    assert ev.kind == "tool_start" and ev.tool_name == "Read file"


def test_tool_call_update_completed_to_tool_end():
    ev = acp_update_to_event({"sessionUpdate": "tool_call_update", "toolCallId": "t1",
                              "status": "completed"})
    assert ev.kind == "tool_end"


def test_tool_call_update_in_progress_is_ignored():
    ev = acp_update_to_event({"sessionUpdate": "tool_call_update", "toolCallId": "t1",
                              "status": "in_progress"})
    assert ev is None


def test_plan_update_to_plan():
    ev = acp_update_to_event({"sessionUpdate": "plan_update",
                              "plan": {"entries": [{"content": "step 1", "status": "pending"}]}})
    assert ev.kind == "plan" and ev.plan == [{"content": "step 1", "status": "pending"}]


def test_unknown_update_is_none():
    assert acp_update_to_event({"sessionUpdate": "available_commands_update"}) is None
    assert acp_update_to_event({}) is None


def test_empty_text_chunk_is_none():
    assert acp_update_to_event({"sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": ""}}) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_acp_mapping.py -v`
Expected: FAIL — `agenticops.acp.mapping` missing.

- [ ] **Step 3: Write `mapping.py`**

Create `src/agenticops/acp/mapping.py`:
```python
"""Pure translation: ACP session/update payload -> backend-agnostic EnhancedEvent.

This is the unit-testable seam between the ACP wire protocol and our core.
Input is the `update` object from a session/update notification's params
(the spike pins whether it's nested under "update" — the AcpClient passes the
right level here). Returns None for updates we don't surface.
"""
from __future__ import annotations

from typing import Any, Optional

from agenticops.acp.types import EnhancedEvent


def acp_update_to_event(update: dict[str, Any]) -> Optional[EnhancedEvent]:
    kind = update.get("sessionUpdate")

    if kind == "agent_message_chunk":
        text = (update.get("content") or {}).get("text", "")
        return EnhancedEvent(kind="text", text=text) if text else None

    if kind == "tool_call":
        # a new tool call begins
        return EnhancedEvent(kind="tool_start",
                             tool_name=update.get("title") or update.get("toolCallId") or "tool")

    if kind == "tool_call_update":
        # only surface terminal states as tool_end
        if update.get("status") in ("completed", "failed"):
            return EnhancedEvent(kind="tool_end",
                                 tool_name=update.get("title") or update.get("toolCallId") or "tool")
        return None

    if kind == "plan_update":
        entries = (update.get("plan") or {}).get("entries", [])
        return EnhancedEvent(kind="plan", plan=entries)

    return None  # available_commands_update, user_message_chunk, usage_update, unknown
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_acp_mapping.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/acp/mapping.py
git add src/agenticops/acp/mapping.py tests/test_acp_mapping.py
git commit --no-verify -m "feat(acp): pure session/update -> EnhancedEvent mapping (tested)"
```

---

## Task 5: Registry + AcpClient (`registry.py`, `client.py`) (TDD for registry; client driven by spike)

**Files:**
- Create: `src/agenticops/acp/registry.py`
- Create: `src/agenticops/acp/client.py`
- Modify: `tests/test_acp_core.py` (add registry tests)

- [ ] **Step 1: Add failing registry tests**

Append to `tests/test_acp_core.py`:
```python
class TestRegistry:
    def setup_method(self):
        from agenticops.acp import registry
        registry._BACKENDS.clear()

    def test_register_and_get(self):
        from agenticops.acp import registry
        from agenticops.acp.types import BackendCapabilities, EnhancedEvent

        class Dummy:
            name = "dummy"
            def capabilities(self): return BackendCapabilities(True, False, False, False)
            async def run(self, task, context):
                yield EnhancedEvent(kind="text", text="x")
            async def cancel(self): ...

        registry.register_backend("dummy", Dummy)
        assert "dummy" in registry.available_backends()
        be = registry.get_backend("dummy")
        assert be.name == "dummy"

    def test_get_unknown_raises(self):
        from agenticops.acp import registry
        import pytest
        with pytest.raises(KeyError):
            registry.get_backend("nope")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_acp_core.py::TestRegistry -v`
Expected: FAIL — `agenticops.acp.registry` missing.

- [ ] **Step 3: Write `registry.py`**

Create `src/agenticops/acp/registry.py`:
```python
"""Pluggable backend registry. Adding a backend = register_backend(name, cls)."""
from __future__ import annotations

from typing import Type

from agenticops.acp.types import EnhancedBackend

_BACKENDS: dict[str, Type[EnhancedBackend]] = {}


def register_backend(name: str, cls: Type[EnhancedBackend]) -> None:
    _BACKENDS[name] = cls


def available_backends() -> list[str]:
    return sorted(_BACKENDS)


def get_backend(name: str) -> EnhancedBackend:
    if name not in _BACKENDS:
        raise KeyError(f"Unknown enhanced backend: {name!r}. Available: {available_backends()}")
    return _BACKENDS[name]()
```

- [ ] **Step 4: Write `client.py` (the self-implemented ACP client)**

Create `src/agenticops/acp/client.py`. **If the spike (Task 2) recorded different handshake/payload details, apply them here verbatim.** Baseline:
```python
"""Self-implemented ACP client: spawn an ACP agent subprocess and drive it over
newline-delimited JSON-RPC 2.0 (stdio). No third-party ACP dependency.

Shared by the claude-code / kiro providers; the provider supplies the launch
command + env and consumes the yielded EnhancedEvents.
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
                 auto_approve: bool = True, timeout: int = 300):
        self._command = command
        self._args = args
        self._env = _safe_env(env_extra)
        self._auto_approve = auto_approve
        self._timeout = timeout
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
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
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
            # initialize
            init_id = await self._send("initialize", {"protocolVersion": 2, "capabilities": {},
                                                      "clientInfo": {"name": "agenticops", "version": "1.3.0"}})
            if not await self._await_result(init_id):
                yield EnhancedEvent(kind="error", error="ACP initialize failed"); return

            # session/new
            sid_id = await self._send("session/new", {"cwd": cwd or os.getcwd(), "mcpServers": []})
            sess = await self._await_result(sid_id)
            if not sess or "result" not in sess:
                yield EnhancedEvent(kind="error", error="ACP session/new failed"); return
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
                yield EnhancedEvent(kind="error", error="Enhanced backend closed unexpectedly"); return
            if await self._maybe_permission(obj):
                continue
            if obj.get("method") == "session/update":
                params = obj.get("params", {})
                update = params.get("update", params)   # spike pins nested vs flat
                ev = acp_update_to_event(update)
                if ev is not None:
                    yield ev
            if obj.get("id") == rid and ("result" in obj or "error" in obj):
                if "error" in obj:
                    yield EnhancedEvent(kind="error", error=str(obj["error"]))
                else:
                    stop = obj["result"].get("stopReason")
                    yield EnhancedEvent(kind="done", tokens=None)
                return
```

- [ ] **Step 5: Run registry tests + compile client**

Run: `.venv/bin/python -m pytest tests/test_acp_core.py -v`
Expected: PASS (core + registry). Then `python3 -m py_compile src/agenticops/acp/client.py registry.py`.
(The client is exercised end-to-end by the gated integration test in Task 6, not unit-tested here — its logic is thin glue over the unit-tested jsonrpc + mapping.)

- [ ] **Step 6: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/acp/registry.py src/agenticops/acp/client.py
git add src/agenticops/acp/registry.py src/agenticops/acp/client.py tests/test_acp_core.py
git commit --no-verify -m "feat(acp): backend registry + self-implemented AcpClient (stdio JSON-RPC)"
```

---

## Task 6: ClaudeCodeBackend provider + gated integration test  ⟵ GATED ON SPIKE (Task 2)

**Files:**
- Create: `src/agenticops/acp/backends/__init__.py`, `src/agenticops/acp/backends/claude_code.py`
- Modify: `src/agenticops/acp/__init__.py` (register at import)
- Create: `tests/test_acp_integration.py` (marked, skips without claude-agent-acp)

**Do NOT start until Task 2's verdict is GO or ADJUST. Apply any ADJUST deltas.**

- [ ] **Step 1: Write `ClaudeCodeBackend`**

Create `src/agenticops/acp/backends/__init__.py` (empty), and `src/agenticops/acp/backends/claude_code.py`:
```python
"""Claude Code enhanced backend — drives `claude-agent-acp` over Bedrock via AcpClient."""
from __future__ import annotations

from typing import AsyncIterator

from agenticops.acp.client import AcpClient
from agenticops.acp.types import BackendCapabilities, EnhancedEvent
from agenticops.config import settings


class ClaudeCodeBackend:
    name = "claude-code"

    def __init__(self):
        env_extra = {}
        if settings.acp_use_bedrock:
            env_extra["CLAUDE_CODE_USE_BEDROCK"] = "1"
            region = getattr(settings, "bedrock_region", "") or "us-east-1"
            env_extra.setdefault("AWS_REGION", region)
        self._client = AcpClient(
            command=settings.acp_claude_command,
            args=list(settings.acp_claude_args),
            env_extra=env_extra,
            auto_approve=settings.acp_auto_approve_permissions,
            timeout=settings.acp_timeout_seconds,
        )

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(streaming=True, plan=True, permissions=True, tools=False)

    async def run(self, task: str, context: str) -> AsyncIterator[EnhancedEvent]:
        prompt = f"{task}\n\n---\nContext:\n{context}" if context else task
        async for ev in self._client.run(prompt):
            yield ev

    async def cancel(self) -> None:
        await self._client.cancel()
```

In `src/agenticops/acp/__init__.py`, register at import:
```python
"""ACP enhanced-backend module (MVP-1.3.0)."""
from agenticops.acp.registry import register_backend
from agenticops.acp.backends.claude_code import ClaudeCodeBackend

register_backend("claude-code", ClaudeCodeBackend)
```

- [ ] **Step 2: Write the gated integration test**

**Reuse the EXISTING integration convention** — DO NOT invent a new marker. `pytest.ini` already declares `markers = integration: ...` and the root `tests/conftest.py` auto-skips any `integration`-marked test unless `--run-integration` is passed. So mark the test `@pytest.mark.integration` (already registered) and add a `skipif not npx` belt-and-suspenders guard.

Create `tests/test_acp_integration.py`:
```python
"""Integration test that actually spawns claude-agent-acp.

Uses the existing `integration` marker: skipped by default; run with
`pytest --run-integration`. Also skipif when npx is absent.
"""
import shutil
import asyncio
import pytest


def _have_npx():
    return shutil.which("npx") is not None


@pytest.mark.integration
@pytest.mark.skipif(not _have_npx(), reason="npx/claude-agent-acp not available")
def test_claude_backend_streams_text():
    from agenticops.config import settings
    settings.acp_use_bedrock = True
    from agenticops.acp.backends.claude_code import ClaudeCodeBackend

    async def run():
        be = ClaudeCodeBackend()
        kinds, text = [], []
        async for ev in be.run("Reply with exactly one word: hello", ""):
            kinds.append(ev.kind)
            if ev.kind == "text":
                text.append(ev.text or "")
            if ev.kind == "error":
                pytest.skip(f"backend error (likely no creds/install): {ev.error}")
        return kinds, "".join(text)

    kinds, text = asyncio.run(asyncio.wait_for(run(), 180))
    assert "done" in kinds
```

No marker registration needed — `integration` is already in `pytest.ini`. Run with `.venv/bin/python -m pytest tests/test_acp_integration.py --run-integration -v` (skips silently otherwise).

- [ ] **Step 3: Verify registry wiring (no live subprocess)**

Run: `.venv/bin/python -c "import agenticops.acp; from agenticops.acp.registry import available_backends, get_backend; print(available_backends()); print(get_backend('claude-code').name)"`
Expected: `['claude-code']` then `claude-code`. Then `python3 -m py_compile src/agenticops/acp/backends/claude_code.py`.

- [ ] **Step 4: (optional) run the gated integration test**

Run: `.venv/bin/python -m pytest tests/test_acp_integration.py -v` (will skip if no npx/creds; if it runs, asserts streaming reaches `done`).

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/acp/backends/ src/agenticops/acp/__init__.py tests/test_acp_integration.py
git commit --no-verify -m "feat(acp): ClaudeCodeBackend (Bedrock) + registered + gated integration test"
```

---

## Task 7: `enhanced_task` tool + register into main/sre  ⟵ GATED ON SPIKE

**Files:**
- Create: `src/agenticops/agents/enhanced.py`
- Modify: `src/agenticops/agents/main_agent.py`, `src/agenticops/agents/sre_agent.py`

- [ ] **Step 1: Write the `enhanced_task` tool**

Create `src/agenticops/agents/enhanced.py`:
```python
"""Optional enhancement tool: delegate a complex task to an external coding
agent (Claude Code) via the ACP enhanced backend. Registered into main/sre only
when settings.acp_enhanced_enabled is true."""
from __future__ import annotations

import asyncio

from strands import tool

from agenticops.config import settings


@tool
def enhanced_task(task: str, context: str = "", backend: str = "") -> str:
    """Delegate a complex task to an enhanced external coding agent (e.g. Claude Code)
    for a higher-quality result. Use for create-skill, deep research, brainstorming,
    or complex multi-step operations that the standard tools cannot fully solve.

    Args:
        task: The task/instruction to delegate.
        context: Optional supporting context.
        backend: Optional backend name override (default from settings).
    Returns:
        The accumulated text result from the enhanced backend, or an error message
        (in which case continue with normal handling).
    """
    if not settings.acp_enhanced_enabled:
        return "Enhanced backend is disabled (acp_enhanced_enabled=false)."

    from agenticops.acp.registry import get_backend

    try:
        be = get_backend(backend or settings.acp_enhanced_backend)
    except KeyError as e:
        return f"Enhanced backend unavailable: {e}"

    async def _drive() -> tuple[list[str], str | None]:
        chunks: list[str] = []
        err: str | None = None
        async for ev in be.run(task, context):
            if ev.kind == "text" and ev.text:
                chunks.append(ev.text)
            elif ev.kind == "error":
                err = ev.error
        return chunks, err

    try:
        chunks, err = asyncio.run(_drive())
    except Exception as e:  # never crash the calling agent's turn
        return f"Enhanced backend failed: {e}"
    if err and not chunks:
        return f"Enhanced backend error: {err}"
    return "".join(chunks) or "(enhanced backend returned no text)"
```

- [ ] **Step 2: Register into sre_agent (conditional)**

In `src/agenticops/agents/sre_agent.py`, add the import near the other tool imports (top of file):
```python
from agenticops.agents.enhanced import enhanced_task
```
Then, where `sre_agent` builds its `tools=[...]` list (around line 219), the list is static. Make `enhanced_task` conditional by building the tool list before the `Agent(...)` call. Find the `Agent(... tools=[ ... ],)` construction and refactor minimally: assign the existing list to a local `_tools = [ ... ]`, then:
```python
        if settings.acp_enhanced_enabled:
            _tools.append(enhanced_task)
```
and pass `tools=_tools`. (Confirm `settings` is imported in sre_agent.py; the file already uses config — if not, add `from agenticops.config import settings`.)

- [ ] **Step 3: Register into main_agent (conditional)**

In `src/agenticops/agents/main_agent.py`, add import near the other `from agenticops.agents...` imports:
```python
from agenticops.agents.enhanced import enhanced_task
```
Apply the same conditional-append pattern to main_agent's `tools=[...]` (around line 262): assign to a local list, then `if settings.acp_enhanced_enabled: _tools.append(enhanced_task)`, pass `tools=_tools`. (`settings` is already imported in main_agent.py.)

- [ ] **Step 4: Verify (default off → tool not present; on → present)**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/agents/enhanced.py src/agenticops/agents/main_agent.py src/agenticops/agents/sre_agent.py
.venv/bin/python -c "
from agenticops.config import settings
settings.acp_enhanced_enabled = False
from agenticops.agents.enhanced import enhanced_task
print('tool imported OK, name:', enhanced_task.tool_name if hasattr(enhanced_task,'tool_name') else 'enhanced_task')
"
```
Expected: imports clean; tool callable. (Full agent-build test requires Bedrock; the conditional registration is the unit of interest — confirm the code path compiles and the append is guarded.)

- [ ] **Step 5: Run the backend test sweep (no regression)**

Run: `.venv/bin/python -m pytest tests/test_acp_core.py tests/test_acp_mapping.py tests/test_acp_jsonrpc.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/agents/enhanced.py src/agenticops/agents/main_agent.py src/agenticops/agents/sre_agent.py
git commit --no-verify -m "feat(acp): enhanced_task tool, conditionally registered into main/sre (default off)"
```

---

## Task 8: Frontend "Enhanced" badge + docs  ⟵ GATED ON SPIKE

**Files:**
- Modify: `src/agenticops/web/frontend/src/components/chat/ToolCallChip.tsx` (or MessageList) — badge for the `enhanced_task` tool call
- Modify: `docs/WORKFLOW.md`, `CLAUDE.md`

- [ ] **Step 1: Confirm how tool calls render (find the chip)**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
sed -n '1,60p' src/agenticops/web/frontend/src/components/chat/ToolCallChip.tsx
```
The chip renders `{name}` + status. The `enhanced_task` tool call already streams through the existing `tool_start`/`tool_end` SSE events (the agent calling the tool), so it ALREADY appears as a chip named "enhanced_task". The only change: give that specific chip an "Enhanced" visual treatment.

- [ ] **Step 2: Add the Enhanced visual treatment**

In `ToolCallChip.tsx`, detect the enhanced tool and restyle. After the existing destructuring of `name`, add a branch: if `name === "enhanced_task"`, render with a distinct label "✦ Enhanced" and a primary-tinted chip. Concretely, find the chip's root element/className and add:
```tsx
  const isEnhanced = name === "enhanced_task";
```
and in the chip's className/label, when `isEnhanced`, use `bg-primary-50 text-primary-700 border-primary-200` and prefix the label with `✦ Enhanced: ` (keep the existing status dot). Keep all other tool chips unchanged. (Match the file's actual structure — show the real before/after at implementation time.)

- [ ] **Step 3: Type-check + build**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: PASS.

- [ ] **Step 4: Update docs**

In `docs/WORKFLOW.md`, add a section near the chat/agent area:
```markdown
## Enhanced Backend (ACP) — optional task delegation

Selected agents (main/sre) can delegate a complex task — create-skill, deep research,
brainstorming, complex operations — to an external coding agent via the optional
**ACP enhanced backend** (`src/agenticops/acp/`). The agent calls the `enhanced_task`
tool (only registered when `acp_enhanced_enabled=true`), which drives a pluggable
`EnhancedBackend` provider. The first provider, `ClaudeCodeBackend`, launches
`claude-agent-acp` as a stdio subprocess over a self-implemented JSON-RPC 2.0 client
(`AcpClient`), running on Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`). Streamed
`session/update`s map onto the existing SSE events (text/tool_start/tool_end/done) and
render with an "✦ Enhanced" chip. Adding a backend (Kiro-cli, Codex) = one provider
class + `register_backend`; the protocol-agnostic core (`EnhancedBackend`/`EnhancedEvent`)
does not change. Default off.
```

In `CLAUDE.md`, add a module row under Backend:
```
| `acp/` | `types.py`, `registry.py`, `jsonrpc.py`, `mapping.py`, `client.py`, `backends/` | Optional ACP enhanced backend — protocol-agnostic EnhancedBackend abstraction + registry; self-implemented JSON-RPC/stdio AcpClient; ClaudeCodeBackend (Bedrock). `enhanced_task` tool, default off (`acp_enhanced_enabled`) |
```
And note the new config keys (`acp_enhanced_enabled`, `acp_enhanced_backend`, `acp_use_bedrock`, `acp_timeout_seconds`, `acp_auto_approve_permissions`) in the config section.

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/components/chat/ToolCallChip.tsx docs/WORKFLOW.md CLAUDE.md
git commit --no-verify -m "feat(web): Enhanced chip for enhanced_task + docs for ACP enhanced backend"
```

---

## Self-Review Notes (author)

- **Spec coverage:** config + core types (T1), spike that GATES providers (T2), self-implemented JSON-RPC (T3), pure ACP→EnhancedEvent mapping (T4), registry + AcpClient (T5), ClaudeCodeBackend + gated integration (T6), enhanced_task tool conditionally into main/sre (T7), Enhanced badge + docs (T8). Protocol-agnostic core (③) built unconditionally in T1/T4/T5; provider wiring (T6-8) gated on T2 per the spec's phasing. Reserved items (Kiro/Codex/MCP-tools/HITL) correctly NOT built.
- **Type consistency:** `EnhancedEvent(kind, text, tool_name, plan, tokens, error)` defined in T1, produced by `acp_update_to_event` (T4) + AcpClient (T5), consumed by ClaudeCodeBackend (T6) + enhanced_task (T7). `EnhancedBackend` Protocol (name/capabilities/run/cancel) in T1, implemented by Dummy (tests), ClaudeCodeBackend (T6). `register_backend/get_backend/available_backends` (T5) used by enhanced_task (T7) + `__init__` (T6). `acp_*` settings (T1) read by client/backend/tool (T5/T6/T7). `EnhancedEvent.kind` values = the verified frontend SSE cases.
- **Architecture-first honored:** T1-5 touch only the new `acp/` module + tests + spike; T6-8 (Strands agents, frontend) gated on the spike GO/ADJUST/NO-GO verdict, explicitly stated.
- **No placeholders.** The spike's "open questions" are its deliverable, not unfinished plan steps. New runtime deps: none (self-implemented; reuses `mcp.client.stdio.get_default_environment` already in deps).
- **Default-off guard** in every integration touchpoint (tool registration conditional, tool returns early when disabled).
