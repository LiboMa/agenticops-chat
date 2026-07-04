# MVP-2.0.1 Release Notes

> Version: 2.0.1 · Branch: `MVP-2.0.1` · Started: 2026-07-03
> Frontend overhaul in 4 sub-projects: **A composer 2.0(本篇)** → C nav bar → B rich chat → D stats redesign. This file grows as each sub-project lands.

## Sub-project A — Chat Composer 2.0 (2026-07-04)

### Per-session model switch

- New composer bottom-left **model pill** (replaces the detail-level select): shows `Auto · <global model>` or the session's chosen model; click opens a Radix Popover listing **Auto (follow global)** + all model presets with the full model id as a mono sub-line.
- **Per-session persistence**: `chat_sessions.model_id` nullable column (NULL = Auto). Set via existing `PATCH /api/chat/sessions/{id}` with a `""`-sentinel for Auto; omitted field = don't change.
- **Validation**: PATCH accepts only ids from the cached model presets ∪ `MODEL_ALIASES` values (400 otherwise). While the session is streaming, model PATCH returns **409** (new `_streaming_sessions` in-flight registry); the pill is also disabled client-side during streaming.
- On change, **only this session's** cached agent is evicted (`session_manager.remove`) — context/history preserved, agent rebuilds with the new model on the next message. Sub-agents are unaffected (Settings per-agent config remains their mechanism).
- **Cost attribution** now uses the session's effective model (override or global) in both the assistant-persist block and `log_agent_call` — per-token pricing stays correct for switched sessions.

### Detail-level removal (full chain)

- The concise/medium/detailed knob is **gone end-to-end**: composer select, `ChatMessageCreate.detail_level`, `set_detail_level`/`get_detail_level`/`VALID_DETAIL_LEVELS` ContextVar machinery in config.py, `agent_output_detail` setting, CLI `/detail` command + `--detail/-d` flag, session save/restore field.
- Output rules are fixed to the former **medium** template (`preamble.OUTPUT_RULES` single constant + RCA/SRE addenda); `get_output_rules(agent_type)` keeps its signature so all 7 agents' call sites are untouched.

### Docs / specs

- Design spec: `docs/superpowers/specs/2026-07-03-chat-composer-model-switch-design.md`
- Visual mockup: `docs/superpowers/specs/2026-07-04-chat-composer-model-selector-mockup.md`
- Plan: `docs/superpowers/plans/2026-07-04-chat-composer-model-switch.md`
