# Design: ACP Enhanced Backend — Pluggable Multi-Backend Task Delegation (MVP-1.3.0)

**Date:** 2026-06-06
**Status:** Architecture design (architecture-first; implementation deferred to a spike + plan)
**Goal (user's):** Give selected Strands agents (initially **main** and **sre**) an *optional* ability to delegate hard tasks — create-skill, deep-research, brainstorming, complex operations — to an external coding agent (**Claude Code** first, **Kiro-cli** / **Codex** later) over a self-implemented ACP-style protocol, to get a better result. This is an **enhancement / escalation path**, NOT a replacement of the existing architecture.

## Framing & scope decisions (all locked)

| Decision | Choice |
|----------|--------|
| Positioning | **Optional enhancement backend.** Strands stays the default framework; the 7-agent orchestration, 35 tools, and per-agent model tiering are **untouched**. |
| Trigger | **Agent-decided**, exposed as a Strands `@tool` (`enhanced_task`) — the agent's LLM calls it when it judges a task warrants enhancement, exactly like today's sub-agents-as-tools. |
| Multi-backend | **Protocol-agnostic `EnhancedBackend` abstraction + a provider registry** from day one. Adding Codex/Kiro later = write one provider class + register it; the core never changes. |
| Abstraction boundary | The top-level interface (`run/cancel/capabilities`) is **protocol-agnostic**. ACP-JSON-RPC is an *implementation detail* shared by the claude/kiro providers (`AcpClient`). A future Codex backend on a different protocol is just another provider. |
| Protocol layer | **Self-implemented.** Newline-delimited JSON-RPC 2.0 over stdio, written in-house (`src/agenticops/acp/`). **No third-party ACP dependency** (the PyPI `agent-client-protocol` is young/v0.10 and would couple us to its API + schema-version drift). |
| First backend | **Claude Code** via `claude-agent-acp` (npx, stdio). Kiro/Codex interfaces reserved. |
| Credentials/model | **Bedrock** — `CLAUDE_CODE_USE_BEDROCK=1` + reuse existing AWS creds/region + `CLAUDE_MODEL_CONFIG`. No new billing. |
| Tools to the backend | **None this round.** Claude Code uses its own file/bash/web tools. Exposing our 35 ops tools via MCP (`session/new.mcpServers`) is a **reserved future enhancement**, not in scope. |
| Frontend | **Reuse existing SSE events** (`text`/`tool_start`/`tool_end`/`done`/`error`) + an "Enhanced" badge. `plan` updates optional. |
| Default state | `acp_enhanced_enabled = false` — the tool isn't registered unless enabled. Zero impact on existing deployments. |
| Delivery | **Architecture-first.** This spec defines structure + interfaces. A **spike** validates the load-bearing unknowns before the full implementation plan. Not rushing code. |

## Why architecture-first + a spike

Research (grounded against the canonical ACP repo + npm/PyPI) confirmed two **load-bearing unknowns** that must be de-risked before committing an implementation plan:

1. **The exact `claude-agent-acp` handshake + Bedrock credential pass-through** — we know the topology (we spawn it as a stdio subprocess speaking JSON-RPC 2.0; `CLAUDE_CODE_USE_BEDROCK=1`) and the message shapes (`initialize` → `session/new` → `session/prompt`, streaming `session/update` with `agent_message_chunk`/`tool_call`/`tool_call_update`/`plan`, terminal `stopReason`), but have not run it end-to-end from Python.
2. **ACP protocol version drift** — `fs/*` methods are v1; v2's client surface is `session/request_permission` + `session/update`. Our self-implemented client must target the version `claude-agent-acp` actually speaks. The spike pins this empirically.

So MVP-1.3.0 is **two phases**: **Phase 0 (spike)** proves a single `session/prompt` round-trip + streaming + Bedrock works from AgenticOps; **Phase 1** builds the full layered framework below, informed by what the spike learned.

**What this spec commits to now vs. later:** the implementation plan produced next (writing-plans) covers **Phase 0 (the spike) + the protocol-agnostic core skeleton** (`types.py`, `registry.py`, `jsonrpc.py`, `mapping.py` — all unit-testable without a live subprocess). The **full `ClaudeCodeBackend` wiring, the `enhanced_task` tool registration into main/sre, and the frontend badge** are written into the plan but **gated on the spike's findings** — if the spike reveals the self-written client needs rework, those tasks adjust before implementation. This keeps the architecture honest: we don't build the provider on an unproven protocol layer. The core abstraction (Layer ③) is built regardless, because it's protocol-agnostic and the whole point of the design.

## Architecture (5 layers; protocol-agnostic core)

```
① Strands Agents (UNCHANGED)        main / sre  ── LLM decides "this is complex"
        │ calls a @tool, like a sub-agent
        ▼
② Enhancement entry  (NEW)          @tool enhanced_task(task, context, backend?)
        │ protocol-agnostic call
        ▼
③ EnhancedBackend abstraction + registry  (NEW · CORE)
        │   Protocol  EnhancedBackend: name, capabilities(), run()->AsyncIterator[EnhancedEvent], cancel()
        │   register_backend(name, cls) / get_backend(settings.acp_enhanced_backend)
        │   unified EnhancedEvent stream (backend-agnostic)
        ▼ each provider translates its own protocol → EnhancedEvent
④ Providers (pluggable)             ClaudeCodeBackend (first) · KiroCliBackend / CodexBackend (reserved)
        │   claude + kiro share →   AcpClient  (self-implemented JSON-RPC/stdio, src/agenticops/acp/)
        ▼ stdio subprocess
⑤ External agent process            claude-agent-acp (Bedrock)  · kiro-cli acp / codex (later)

   ▲ events flow back: EnhancedEvent → map → existing SSE (text/tool_start/tool_end/done) → frontend + "Enhanced" badge
```

### The core contract (Layer ③) — what to get right

Two small, stable types are the heart of the design. Everything else is an implementation of these.

```python
# src/agenticops/acp/types.py  (protocol-agnostic — NO ACP/JSON-RPC here)

@dataclass(frozen=True)
class BackendCapabilities:
    streaming: bool
    plan: bool          # emits plan/step updates
    permissions: bool   # may request permission (HITL)
    tools: bool         # can be given client tools (MCP) — False this round

@dataclass(frozen=True)
class EnhancedEvent:
    kind: Literal["text", "tool_start", "tool_end", "plan", "done", "error"]
    text: str | None = None          # for text
    tool_name: str | None = None     # for tool_start/tool_end
    plan: list[dict] | None = None   # for plan (entries)
    tokens: dict | None = None       # for done (input/output)
    error: str | None = None         # for error

class EnhancedBackend(Protocol):
    name: str
    def capabilities(self) -> BackendCapabilities: ...
    async def run(self, task: str, context: str) -> AsyncIterator[EnhancedEvent]: ...
    async def cancel(self) -> None: ...
```

```python
# src/agenticops/acp/registry.py
_BACKENDS: dict[str, type[EnhancedBackend]] = {}
def register_backend(name: str, cls: type[EnhancedBackend]) -> None: ...
def get_backend(name: str) -> EnhancedBackend: ...   # raises if unknown/disabled
def available_backends() -> list[str]: ...
```

The `EnhancedEvent.kind` values are chosen to map 1:1 onto the **existing** frontend SSE cases (`chatStream.ts` handles `text`/`tool_start`/`tool_end`/`done`/`error`), so the web path needs no new event types — only an "Enhanced" badge.

### Layer ④ — providers + the shared `AcpClient`

```
src/agenticops/acp/
├── types.py          # EnhancedEvent, BackendCapabilities, EnhancedBackend (Protocol)
├── registry.py       # register_backend / get_backend
├── client.py         # AcpClient — self-implemented JSON-RPC 2.0 over stdio (the protocol layer)
├── jsonrpc.py        # tiny newline-delimited JSON-RPC framing (read/write/notify/request)
├── mapping.py        # ACP session/update  → EnhancedEvent   (pure, unit-testable)
└── backends/
    ├── claude_code.py   # ClaudeCodeBackend: launches `claude-agent-acp` via AcpClient, Bedrock env
    ├── kiro_cli.py       # (reserved) KiroCliBackend: same AcpClient, command = `kiro-cli acp`
    └── codex.py          # (reserved) CodexBackend: own protocol OR codex-acp via AcpClient
```

- **`AcpClient`** owns the subprocess + JSON-RPC: launch (reusing the **`mcp_manager.py` subprocess recipe** — `get_default_environment()` + AWS-cred passthrough, which is exactly how Bedrock creds reach the child), `initialize`, `session/new`, `session/prompt`, consume `session/update` notifications, `session/cancel`, timeout + kill. Protocol-version-aware (target whatever the spike pins).
- **`mapping.py`** is a **pure function** `acp_update_to_event(update: dict) -> EnhancedEvent | None` — the unit-testable seam (no subprocess needed to test the translation), mirroring how `messagingFields.ts`/`groupSessions.ts` isolated pure logic.
- **`ClaudeCodeBackend`** = thin: build the launch command (`npx @agentclientprotocol/claude-agent-acp` or configured path) + Bedrock env (`CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION`, optional `CLAUDE_MODEL_CONFIG`), drive `AcpClient`, yield mapped `EnhancedEvent`s.
- **Permissions this round:** `session/request_permission` → auto `allow_once` (enhancement runs in a controlled ops context; HITL approval is a reserved future enhancement, surfaced via the same SSE channel later).

### Layer ② — the `enhanced_task` tool

```python
# src/agenticops/agents/enhanced.py
@tool
def enhanced_task(task: str, context: str = "", backend: str = "") -> str:
    """Delegate a complex task (create-skill, deep research, brainstorming, complex ops)
    to an enhanced external coding agent (Claude Code) for a higher-quality result.
    Use when the standard tools cannot fully solve the user's request."""
    if not settings.acp_enhanced_enabled:
        return "Enhanced backend is disabled."
    be = get_backend(backend or settings.acp_enhanced_backend)
    # drive be.run(task, context); accumulate text; surface streaming via the SSE path;
    # on any backend/launch error, return a clear message so the agent can fall back.
```

Registered into `main_agent` and `sre_agent` `tools=[...]` (the existing import + list pattern). Because it's a normal `@tool`, the Strands router decides when to call it — no orchestration change.

### Streaming integration (Layer ② ↔ web)

The web SSE generator (`app.py api_send_chat_message._generate`) already consumes Strands `agent.stream_async` events. When the agent calls `enhanced_task`, that tool's streaming is surfaced through the **same** SSE event types. Concretely (to be finalized in Phase 1 from the spike): the tool emits `tool_start{name:"enhanced_task"}`, then the backend's `EnhancedEvent`s map to nested `text`/`tool_start`/`tool_end`, then `tool_end`. The frontend tags the turn with an **"Enhanced"** badge (a small UI marker keyed off the `enhanced_task` tool call — reuses `ToolCallChip`).

### Config (settings.yaml — schema only; defaults off)

```
acp_enhanced_enabled: false                       # master switch (tool not registered unless true)
acp_enhanced_backend: "claude-code"               # default provider
acp_claude_command: "npx"                         # launch command
acp_claude_args: ["@agentclientprotocol/claude-agent-acp"]
acp_use_bedrock: true                             # CLAUDE_CODE_USE_BEDROCK=1
acp_timeout_seconds: 300                           # subprocess turn timeout
acp_auto_approve_permissions: true                 # auto allow_once this round
```

(Per project rule: `config.py` defines the schema/Field, `settings.yaml` holds defaults — no hardcoded values.)

## Error handling

- **Backend unavailable** (node/npx missing, `claude-agent-acp` not installed, ACP lib N/A, launch fails) → `enhanced_task` returns a clear error string; the calling agent continues with normal handling. **Never crashes the turn.**
- **Disabled** (`acp_enhanced_enabled=false`) → tool not registered (or returns "disabled"); zero impact.
- **Subprocess hang / timeout** → `acp_timeout_seconds` → `session/cancel` → kill child; surface `error` event.
- **Permission request** → auto `allow_once` (this round).
- **Protocol mismatch** (wrong ACP version) → AcpClient detects on `initialize` and fails cleanly with a diagnostic.

## Testing

- **Phase 0 spike**: a standalone script that launches `claude-agent-acp`, runs one `session/prompt`, prints streamed `session/update`s, confirms Bedrock. Output: a short findings note (does the self-written JSON-RPC client work? which protocol version? does Bedrock pass-through work? does a Python ACP lib add value?). This **gates** Phase 1.
- **Phase 1 unit (pytest)**: `mapping.py` pure function — every `session/update` variant (`agent_message_chunk`/`tool_call`/`tool_call_update`/`plan`/stopReason) → correct `EnhancedEvent`; unknown update → `None`. `registry.py` — register/get/unknown/disabled. `jsonrpc.py` — framing round-trip. (All without a live subprocess.)
- **Phase 1 integration (gated/optional)**: a test behind a marker that actually spawns `claude-agent-acp` if present (skipped in CI without it), asserting a trivial prompt streams text + reaches `done`.
- **Manual smoke**: enable `acp_enhanced_enabled`, ask main to "use the enhanced backend to brainstorm/create a skill", confirm streamed output + "Enhanced" badge, both light/dark.

## Scope guardrails

- **New:** `src/agenticops/acp/` (types, registry, jsonrpc, client, mapping, backends/claude_code) + `agents/enhanced.py` (`enhanced_task` tool) + register into main/sre + config fields + a small frontend "Enhanced" badge.
- **Reserved (NOT built this round):** Kiro/Codex providers (interfaces only), MCP tool exposure to the backend, HITL permission UI, per-message model tiering through ACP, scan/detect/rca/reporter enhancement.
- **Untouched:** Strands 7-agent orchestration, 35 tools, BedrockModel direct path, model tiering, SSE protocol, session manager, Messaging, chat UI.
- **No third-party ACP dependency** (self-implemented protocol). No new runtime deps beyond what the spike may justify.

## Documentation (per CLAUDE.md rule 7)

After Phase 1: `docs/WORKFLOW.md` (enhancement-path section + diagram), `CLAUDE.md` (new `acp/` module row + config keys), and MVP-1.3.0 release notes. Note that adding a backend = one provider class + `register_backend`.

## Open questions deferred to the spike (Phase 0)

1. Does a self-written newline-JSON-RPC stdio client cleanly drive `claude-agent-acp`, or is there a framing/version subtlety that argues for vendoring a minimal piece of the TS adapter? (Spec assumes self-written works; spike confirms.)
2. Exact `claude-agent-acp` install/launch (`npx @agentclientprotocol/claude-agent-acp` vs a pinned local install) + the precise Bedrock env it honors.
3. The real `session/update` payload shapes from the current adapter version (to finalize `mapping.py`).
4. Whether per-session model selection via `_meta.claudeCode` is worth wiring now or deferring.
