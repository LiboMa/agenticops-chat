# Chat Composer 2.0 — Per-Session Model Switch + Detail-Level Removal — Design Spec

> Status: approved design (brainstorm complete) · Date: 2026-07-03 · Branch: `MVP-2.0.1` (from `MVP-2.0.0-release`)
> Sub-project A of the MVP-2.0.1 frontend overhaul (A: composer → C: nav → B: rich chat → D: stats — each gets its own spec/plan cycle).

## 1. Context

Today model selection is **global per-agent** (Settings → AgentModelsCard → `PATCH /api/settings` → YAML persist + `_chat_sessions.clear()`), with no chat-surface control. Output verbosity is a **per-message** `detail_level` param (concise/medium/detailed) flowing from a composer `<select>` through `ChatMessageCreate` into a request-scoped ContextVar consumed by `preamble.get_output_rules()` at prompt build.

MVP-2.0.1 decisions (user-confirmed):

| Decision | Choice |
|---|---|
| Model switch scope | **Per-session** — saved on the ChatSession; "Auto" (NULL) follows global config; sub-agents unaffected |
| Detail levels | **Full-chain removal** — UI + API + CLI + ContextVar all deleted; prompts fixed to the current *medium* template |
| Selector placement | Composer bottom-left toolbar (the slot freed by the detail `<select>`), Radix Popover |
| Model list source | Existing `model_presets` from `GET /api/settings` (Bedrock dynamic discovery + alias fallback) — no new endpoint |

## 2. Feature A1 — per-session model switch

### Data model (additive, nullable — same migration pattern as the cost columns)

- `ChatSession` += `model_id: Optional[str]` (NULL = Auto → resolve via `get_agent_model_config("main")`)
- `ChatSessionResponse` += `model_id`
- `ChatSessionUpdate` (the existing PATCH schema used by pin/star/rename) += `model_id`

### API

- Reuse `PATCH /api/chat/sessions/{id}` — new optional `model_id` field.
  - **Auto sentinel**: `model_id: ""` (empty string) means Auto (stored as NULL). Omitting the field means "don't change". Pydantic `None` is treated as omitted — the `""` sentinel avoids the null-vs-unset ambiguity in `ChatSessionUpdate` (whose existing fields use None=don't-change).
  - Validation: non-empty value must be a model id present in the **cached** presets list (`get_model_presets()` 24h cache — validation must NOT trigger a live Bedrock call) or `MODEL_ALIASES` values. Unknown id → 400 with the allowed-list hint.
  - While the session has an **active stream**, PATCH with `model_id` → **409** ("finish or stop the current response first"). Requires a small new in-flight registry (none exists today): a module-level `set[str]` of streaming session_ids, added at SSE generator start, removed in `finally` (~10 lines in app.py). Frontend additionally disables the selector during streaming.
- On successful model change: evict **only this session's** cached agent via the **existing** `session_manager.remove(session_id)` (session_manager.py:474 — already used on session delete), NOT the global `clear()`. Next message rebuilds the main agent with restored history + new model. Context is preserved; Bedrock prompt cache for that session resets (first message after switch is slower — acceptable, documented).

### session_manager resolution

`get_or_create(session_id)`: read `session.model_id`; if set, build `create_main_agent(model_id_override=...)`; else current behavior. `create_main_agent` gains an optional `model_id_override: str = ""` parameter that takes precedence over `get_agent_model_config("main")` for the main agent's model only (max_tokens/window still from global config).

### Cost attribution fix (required, not optional)

`app.py` assistant-persist block and `log_agent_call` currently hard-code `get_agent_model_config("main")[0]` as the model for `cost_usd`/`model_id`. Change both to read the **session's effective model** (override or global). Otherwise a switched session records wrong per-token pricing.

### UX

- Composer bottom-left: a model pill (short name: "Auto", "Opus 4.8", "Sonnet 4.6", …) → click opens Radix Popover listing: top item **Auto (follow global)** + presets (friendly label + model id in small muted text). Current selection checked.
- Pill shows resolved global model name in muted style when Auto (e.g. "Auto · Opus 4.8").
- Disabled (with tooltip) while `useSessionStream` reports streaming.
- Persisted per session server-side — survives reload, visible in any browser.
- i18n: ~4 new flat keys in both `en.json` and `zh.json` (`chat.model.auto`, `chat.model.switchTooltip`, `chat.model.streamingLocked`, `chat.model.followGlobal`).

### Short-name derivation

Reuse the presets' friendly names when available; fallback: strip provider prefix from the model id (same convention as `AgentMetrics.tsx` `shortName`).

## 3. Feature A2 — detail-level full-chain removal

Fixed behavior = today's **medium** template. Removal blast-radius (verified by recon, file:line current as of `MVP-2.0.0-release` HEAD):

| Layer | Removal |
|---|---|
| Frontend | `ChatInput.tsx` detail `<select>` (:14,32,176-189); `Chat.tsx` `usePersistedState("aiops-detail-level")` (:26,144,222,293,297); `chatStream.ts` param append (:92,127,133); `useSessionStream.ts` (:50,63); `useLazySessionCreate.ts` (:23,48). NOTE: `ContextPanel.tsx` "Detail chips" render pipeline-event metadata — unrelated to detail-level, do NOT touch |
| API | `ChatMessageCreate.detail_level` (schemas.py:578); app.py extract + `set_detail_level()` (:4291,4297,4350,4413-4416) |
| config.py | `agent_output_detail` field (:490-494); `VALID_DETAIL_LEVELS`, `_detail_level_var`, `get_detail_level`, `set_detail_level` (:951-977); `config/settings.yaml` `agent_output_detail` line |
| preamble.py | Collapse `OUTPUT_RULES` 3-template dict + `RCA_ADDENDA`/`SRE_ADDENDA` to single medium constants; **keep `get_output_rules(agent_type)` signature** so the 8 `build_system_prompt(agent_type=...)` call sites across the 7 agents (detect has two) stay unchanged — it just no longer reads a ContextVar |
| skills/loader.py | Update the back-compat re-exports (:434-458) to the new constants |
| CLI | `/detail` command (main.py:3507-3519), `-d/--detail` flag — **both** the `typer.Option` declaration (:4065) and the handling block (:4086-4104), autocomplete (:4172), per-turn contextvar set (:4268-4269), `ctx.detail_level` + `set_detail()` (context.py:19,40), session save/restore fields (:2562,2638,2656,2833,2851) |
| Tests | Delete `tests/test_detail_level.py` (231 LoC); update `test_preamble.py` (:58-78+), `test_cli_session_commands.py` (:290). Prompt-budget goldens should NOT need re-pinning (medium was already the build-time default → assembled prompts byte-identical; goldens have ±25% bands) — verify, re-pin only if a band actually trips |
| Docs | `docs/WORKFLOW.md` (:634,813-816,826,1016,1051,1054), `CLAUDE.md` config table (`agent_output_detail` row), MVP-2.0.1 release notes |

Sub-agent behavior note: sub-agents rebuild per invocation and previously read the per-message ContextVar; after removal they always get the medium rules — no behavior cliff (medium was already the default).

## 4. Explicitly out of scope (YAGNI)

- Per-message model override (session-level only)
- Sub-agent model switching from chat (Settings per-agent config remains the mechanism)
- CLI per-session model (CLI keeps its global `/model` command)
- IM (Feishu) chat model switching
- Any new "verbosity" replacement knob

## 5. Testing

Backend (pytest):
1. PATCH `model_id` valid → persisted, response echoes; invalid → 400; `""` → stored NULL (Auto); field omitted → unchanged; during active stream (in-flight registry) → 409, registry entry removed after stream `finally`
2. `get_or_create` honors session `model_id`; Auto (NULL) falls back to global; `remove(session_id)` rebuild keeps history
3. Cost/persist blocks use the effective (overridden) model id
4. `detail_level` in POST body → Pydantic ignores unknown field (verify no 500, no ContextVar path left); grep-level assertion that `set_detail_level` no longer exists
5. Prompt goldens re-pinned; `get_output_rules("rca"/"sre"/"generic")` returns medium+addenda

Frontend: `npx tsc --noEmit` + `npm run build`; manual E2E — switch model → send → per-message footer shows new model in trace; reload → pill persists; second browser sees same model.

Regression: full pytest suite; chat SSE flow (send/stream/done) unchanged for Auto sessions.
