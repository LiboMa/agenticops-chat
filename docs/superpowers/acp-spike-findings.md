# ACP Phase-0 Spike — Findings (MVP-1.3.0)

**Date:** 2026-06-06
**Spike:** `scripts/acp_spike.py`
**Verdict:** ✅ **GO** — a self-written newline JSON-RPC/stdio client cleanly drives `claude-agent-acp` over Bedrock. Proceed to Tasks 3–8 with the small ADJUST deltas below.

## What was proven

Ran the spike end-to-end against `@agentclientprotocol/claude-agent-acp` **v0.42.0** (resolved live from npm). Full round-trip succeeded:

```
initialize → session/new → session/prompt → stream session/update → terminal result(stopReason)
```

- **Accumulated agent text** = `"hello"` / `"ping"` (two runs) — real LLM output.
- **Terminal**: `{"stopReason": "end_turn", "usage": {"inputTokens":…, "outputTokens":…, "cachedReadTokens":…, "cachedWriteTokens":…, "totalTokens":…}}`.
- **Bedrock pass-through WORKS**: message IDs are `msg_bdrk_*`; real token usage + a `cost` field appeared. Credentials reached the child via the env recipe (`get_default_environment()` passes `HOME`/`PATH`; the underlying SDK's default chain reads `~/.aws/credentials`). `CLAUDE_CODE_USE_BEDROCK=1` + `AWS_REGION` set in the child env. Account 533267047935 (`aws sts get-caller-identity` confirmed).

## Load-bearing findings (these change the implementation)

### 1. `npx` MUST be invoked with `-y`
Without `-y`, `npx` blocks on an interactive install-confirmation prompt; `initialize` then never receives a response (the spike's first run timed out at 60s on exactly this). With `-y` the handshake returns instantly.
- **ADJUST:** `acp_claude_args` default = `["-y", "@agentclientprotocol/claude-agent-acp"]`.

### 2. Protocol version is **v1**, not v2
Client sent `protocolVersion: 2`; the adapter negotiated **`protocolVersion: 1`** in its `initialize` result. This resolves the spec's "version drift" open question: **0.42.0 speaks ACP v1.** `authMethods: []` (no auth handshake needed). The client surface we use (`session/request_permission` + `session/update`) is present and is what matters; we do not use `fs/*`.
- **ADJUST:** `AcpClient` sends `protocolVersion: 1` on `initialize`.

### 3. `session/update` payload shape is **nested**
Every update arrives as: `params.update.sessionUpdate` + the update body under `params.update`. Example:
```json
{"jsonrpc":"2.0","method":"session/update","params":{
  "sessionId":"…",
  "update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"hello"},"messageId":"msg_bdrk_…"}}}
```
- **CONFIRMS:** `AcpClient`'s `update = params.get("update", params)` is correct; `mapping.acp_update_to_event()` receives the inner `update` object. No change to `mapping.py` beyond what the plan already specifies.

### 4. Terminal result carries `usage` → populate the `done` event
`session/prompt` result = `{"stopReason": "...", "usage": {"inputTokens","outputTokens","cachedReadTokens","cachedWriteTokens","totalTokens"}}`.
- **ADJUST:** `AcpClient` `done` event sets `tokens={"input": usage.inputTokens, "output": usage.outputTokens}` (map ACP's `inputTokens`/`outputTokens` to our existing `input`/`output` keys).

## Update kinds observed (simple text prompt)

| `sessionUpdate` | Maps to | Notes |
|-----------------|---------|-------|
| `available_commands_update` | (ignored → None) | lists slash-commands; not surfaced |
| `usage_update` | (ignored → None) | running token/cost meter; terminal `usage` is what we use |
| `agent_thought_chunk` | (ignored → None) | extended-thinking text; not surfaced this round |
| `agent_message_chunk` | `text` | the visible answer; empty-text chunks → None |
| `tool_call` / `tool_call_update` | `tool_start`/`tool_end` | NOT seen in this trivial prompt — mapping coded from the ACP spec; the gated integration test (Task 6) exercises a tool-using prompt |
| terminal `result.stopReason` | `done` | with `usage` tokens |

(`agent_thought_chunk` was not in the original plan's mapping list. It is correctly handled by the mapping's catch-all `return None`. No new branch needed unless we later choose to surface thinking.)

## Capabilities advertised by the agent (for future rounds)

`initialize` result `agentCapabilities`: `loadSession: true`, `promptCapabilities: {image, embeddedContext}`, `mcpCapabilities: {http, sse}`, `sessionCapabilities: {additionalDirectories, close, delete, fork, list, resume}`, `_meta.claudeCode.promptQueueing: true`. `session/new` returns `modes` (`default`/`acceptEdits`/`plan`). All reserved for later — out of scope this round.

## Net effect on the plan

- **GO.** No NO-GO, no rework of the architecture. The protocol-agnostic core (Tasks 1/3/4/5) is unaffected in shape.
- **3 small ADJUST deltas**, all localized to config defaults + `client.py`:
  1. `acp_claude_args` → prepend `-y`.
  2. `initialize` → `protocolVersion: 1`.
  3. `done` → fill `tokens` from terminal `result.usage`.
- These are applied as Tasks 3–6 are implemented. Tasks 6–8 (provider wiring, tool, frontend) are **un-gated → cleared to proceed**.
