# Token & Cost Observability — Design Spec

> Status: approved design (brainstorm complete) · Date: 2026-06-27 · Branch: `MVP-2.0.0.methos-release`

## 1. Context

AgenticOps spends real money on every turn — each agent invocation burns Bedrock tokens, and the multi-agent fan-out (main router → rca/sre/executor/…) plus autonomous background work (auto-RCA, auto-fix pipeline, scheduled patrol, webhook/IM intake) makes that spend opaque. Today the data is *captured* (`agent_logs` has per-call input/output/cache_read tokens + `model_id` + `trace_id`; `chat_messages.token_usage` stores `{input, output}` per turn; `config.token_cost_table` has per-model USD rates) but **cost is never computed or stored** (only an in-memory CLI estimate), there is **no time-dimension analysis** (only an `hours=N` window), there is **no per-user/tenant attribution**, and the per-message token figure is **stored but never rendered** in the chat UI.

This feature closes that gap: a per-message token+cost readout in the chat box, and a Token & Cost dashboard (Web + CLI) that analyzes consumption by **agent**, **actor** (logged-in user / system / schedule / webhook / im / cli), and **model**, across **day / month / year**. Goal: make "how much did this cost, and where did it go?" answerable at a glance and sliceable for investigation.

**Out of scope (v1):** budget limits / threshold alerting ("alert at $X/day"); pre-aggregated rollup tables; per-message **historical** cost recompute (cost is snapshotted at write time). These are noted as future work in §10.

## 2. Decisions locked during brainstorm

| # | Decision | Choice |
|---|----------|--------|
| D1 | "Account" dimension | **Actor = logged-in user / tenant** (not a managed CloudAccount, not the Bedrock account) |
| D2 | Cost source | **Derived from `token_cost_table`**, snapshotted at write time; add `cache_write` rate |
| D3 | Per-message display | **Token + cost, expandable** (inline footer that unfolds a per-sub-agent table in place) |
| D4 | Aggregation strategy | **Real-time query over `agent_logs`** + new cost/actor columns + indexes (no rollup tables) |
| D5 | Surfaces | **Web + CLI** (shared aggregation service) |
| D6 | Background attribution | Interactive → the user; background → a **synthetic actor bucket** (`system`/`schedule`/`webhook`/`im`); default `system` so nothing is unattributed |
| V1 | Dashboard layout | **Scorecard**: KPI cards → big trend chart → breakdown row |
| V2 | Trend chart | **Mix**: stacked cost bars (by dimension) + overlaid token line (2nd axis) + current-period share donut |
| V3 | Per-message footer | **Inline footer → expands in place** (`↑in ↓out Σtotal $cost` → per-sub-agent table) |

## 3. Architecture overview

```
                         ┌─ compute_cost() ──────────────┐  (single source of truth)
                         │  agenticops/cost.py            │
write paths ─────────────┤   model_id + token dict → USD  │
  track_agent (agents)   └────────────────────────────────┘
  chat-message persist                 │
        │ writes                        │ snapshots cost_usd + actor + cache_write
        ▼                               ▼
  agent_logs  (+ cache_write_tokens, cost_usd, actor_type, actor_id)
  chat_messages (+ trace_id; token_usage JSON extended)
        │
        ▼  real-time GROUP BY (func.date / strftime), no rollup
  services/cost_service.py  ── cost_summary(period, group_by, filters) ──┐
        │                                                                 │
        ├── GET /api/cost/summary  (web/routers/cost.py)                  │
        │        └─► AgentMetrics.tsx  (scorecard + recharts mix chart)   │
        ├── GET /api/agent-logs/timeline/{trace_id}  (EXISTING)           │
        │        └─► chat MessageItem inline-expand footer                │
        └── aiops cost  (cli)  ◄──────────────────────────────────────────┘
```

Every unit has one job and a clear interface: `cost.py` (tokens→USD, pure), `cost_service.py` (query→aggregates), the router (HTTP), the CLI command (terminal render), the React components (display). Each is testable in isolation.

## 4. Data model changes

Additive only — follow the existing startup-migration pattern in `models.py` (`ALTER TABLE … ADD COLUMN` guarded blocks, ~lines 880–1000). No Alembic needed; all new columns are nullable / defaulted so old rows and old code keep working.

### 4.1 `agent_logs` (models.py `AgentLog`, ~line 582)
Add four columns + one index:
| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `cache_write_tokens` | int | 0 | Already extracted by `metrics.py`, currently discarded — persist it |
| `cost_usd` | float | 0.0 | Snapshot total cost at write time (D2) |
| `actor_type` | str(20) | `"system"` | `user` / `system` / `schedule` / `webhook` / `im` / `cli` (D1/D6) |
| `actor_id` | str(100) | NULL | username (interactive) or trigger label (e.g. schedule name); NULL for anonymous system |

New index `idx_agent_log_actor_time` on `(actor_type, created_at)` for the dashboard's actor+time queries (mirrors the existing `idx_agent_log_agent_time`).

### 4.2 `chat_messages` (models.py `ChatMessage`, ~line 802)
- Add `trace_id` (str(36), nullable) — links a chat turn to its `agent_logs` rows so the inline-expand footer can call the existing `/api/agent-logs/timeline/{trace_id}`.
- Extend the `token_usage` JSON shape written on assistant persist (app.py ~4497) from `{input, output}` to `{input, output, cache_read, cache_write, cost_usd, model}`. (Column type unchanged — JSON.)

### 4.3 `config.token_cost_table` (config.py ~line 748)
Add a `cache_write` rate to each model entry (Anthropic cache-write ≈ 1.25× input):
```python
"claude-opus-4-6":   {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
"claude-sonnet-4-6": {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
"claude-haiku-4-5":  {"input": 0.80, "output": 4.0,  "cache_read": 0.08, "cache_write": 1.00},
```
Add an entry for **opus-4-8** (the actual default for main/sre/executor) — currently missing, so those agents would price at 0. Rates per the published Opus 4.8 pricing at build time.

## 5. Cost computation — `agenticops/cost.py` (new, pure)

```python
def normalize_model_key(model_id: str) -> str
def compute_cost(model_id: str, tokens: dict) -> float           # total USD
def compute_cost_breakdown(model_id: str, tokens: dict) -> dict  # {input,output,cache_read,cache_write,total} USD
```
- `normalize_model_key`: maps full Bedrock IDs → table keys, e.g. `global.anthropic.claude-opus-4-6-v1` → `claude-opus-4-6`, `…claude-opus-4-8` → `claude-opus-4-8`, strips `global.`/`us.` prefix, `anthropic.`, and `-v1`/version suffixes. Deterministic, table-driven.
- `compute_cost`: `(tokens[k]/1_000_000) * rate[k]` summed over input/output/cache_read/cache_write; missing token keys → 0.
- **Unknown model → returns 0.0 and logs one WARNING** (never raises; pricing gaps must not crash a turn).
- Reused by: `agent_log_service.log_agent_call` (write snapshot), chat-message persist, CLI `display.py` (replaces its current inline calc), and `cost_service` (for indicative live recompute where needed).

## 6. Attribution — actor_type / actor_id

`track_agent(...)` (services/agent_log_service.py) and `log_agent_call(...)` gain optional `actor_type` / `actor_id` (default `actor_type="system"`, `actor_id=None`). Wiring at each entry point:
- **Web chat SSE** (app.py stream handler): `actor_type="user"`, `actor_id = request.state.user.username` (auth context already populated at app.py:4670; falls back to `"system"` if auth disabled).
- **CLI chat** (cli/main.py): `actor_type="cli"`, `actor_id = getpass.getuser()`.
- **Background services** — `pipeline_service` / `rca_service` / `resolution_service` → `actor_type="system"`; `scheduler` → `"schedule"` + `actor_id=<schedule name>`; webhook intake → `"webhook"` + source; IM intake (`im/`) → `"im"` + platform.

This yields both "user X spent $Y" and "human vs autonomous spend" from one column pair. No `user_id` FK is introduced (usernames are stable enough for v1 and avoid an auth-schema migration); revisit if multi-tenant hard isolation is needed.

## 7. Aggregation service — `services/cost_service.py` (new)

```python
def cost_summary(
    start: datetime, end: datetime,
    bucket: Literal["hour","day","month","year"] = "day",
    group_by: Literal["agent","actor","model","none"] = "agent",
    filters: dict | None = None,          # {actor_type, actor_id, agent_name, model_id}
) -> CostSummary
```
Returns (plain dict / pydantic):
- `totals`: `{input, output, cache_read, cache_write, total_tokens, cost_usd, cache_hit_pct, call_count}` — drives KPI cards.
- `series`: `[{bucket: "2026-06-21", cost_usd, total_tokens, by: {<group_key>: {cost_usd, tokens}}}, …]` — drives stacked bars + token line.
- `breakdown`: `[{key, calls, input, output, cache_read, cache_write, tokens, cache_hit_pct, cost_usd}, …]` sorted desc by cost — drives donut + breakdown rows.

Implementation: one SQLAlchemy query over `agent_logs` with a DB-portable bucket expression (`func.strftime('%Y-%m-%d', created_at)` on SQLite, `func.to_char` on Postgres — switch on dialect, following the existing `dashboard_trends` precedent) + `GROUP BY bucket, <group col>`. Time-zone: all timestamps are UTC (existing convention); bucketing is UTC. Cost is summed from the stored `cost_usd` column (snapshot), so the dashboard is consistent with what was charged.

## 8. API — `web/routers/cost.py` (new router, registered in app.py)

- `GET /api/cost/summary?bucket=day&group_by=agent&start=…&end=…&actor_type=&actor_id=&agent_name=&model_id=` → `CostSummary` (§7). `start`/`end` optional (default last 30 days); also accept `period=day|month|year|7d|30d` shorthand that sets a sensible default range + bucket.
- Existing `GET /api/agent-logs/summary` gains a non-breaking `cost_usd` field per agent/model and a top-level `total_cost_usd`.
- Per-message expand reuses **existing** `GET /api/agent-logs/timeline/{trace_id}` (add `cost_usd` per node — non-breaking).
- Auth: same dependency as other `/api/*` routes (`get_current_user` when `api_auth_enabled`).

## 9. Frontend & CLI

### 9.1 Web dashboard — extend `pages/AgentMetrics.tsx` (not a new page)
Add `recharts` (no charting lib today). Scorecard layout (V1):
1. **KPI cards row**: Total Cost (with ▲/▼ vs previous period), Total Tokens, Cache-Hit %, Call Count.
2. **Trend chart (the mix, V2)**: `recharts` `ComposedChart` — stacked `Bar`s (cost, segmented by the selected dimension) + a `Line` (total tokens) on a right `YAxis`. Controls: **Day / Month / Year** toggle + **stack-by** dropdown (agent / actor / model).
3. **Share donut**: `recharts` `PieChart` (current-period cost share by the selected dimension).
4. **Breakdown rows**: three horizontal bar-lists — By Agent / By Actor / By Model — each row `name · tokens · cache% · $cost`, click to set the page filter.
New hook `useCostSummary` in `hooks/` (TanStack Query) calling `/api/cost/summary`. Existing agent-log tables/timeline stay.

### 9.2 Chat per-message footer (V3) — `components/chat/`
Wire the existing-but-unused `TokenMetrics.tsx` into `MessageItem`: a compact footer under each assistant message — `↑input ↓output Σtotal · $cost · details ▾`. Clicking `details` fetches `/api/agent-logs/timeline/{trace_id}` (via the message's new `trace_id`) and unfolds a per-sub-agent table (agent · model · in · out · cache · $) in place. Requires threading `trace_id` + the extended `token_usage`/`cost_usd` into the message API response (`web/schemas.py` `ChatMessageResponse`) and the `chatStream` store.

### 9.3 CLI — `aiops cost`
New command (cli): `aiops cost [--period day|month|year] [--by agent|actor|model] [--days N] [--actor X]`. Calls `cost_service.cost_summary` directly (same backend), renders a Rich table (buckets as rows or breakdown as rows) + a totals line with cost. The existing `/tokens` session command keeps working; its inline cost calc is refactored to call `cost.compute_cost`.

## 10. Testing & verification

- **Unit (`tests/`)**: `test_cost.py` — `normalize_model_key` across full Bedrock IDs + opus-4-8; `compute_cost` math per model incl. cache_write; unknown-model → 0 + warning. `test_cost_service.py` — seed in-memory `agent_logs` (sqlite), assert day/month/year bucketing, group_by agent/actor/model, filters, cache_hit_pct, totals. Attribution: `track_agent` writes correct `actor_type/actor_id`; default `system`.
- **API**: `/api/cost/summary` shape + filters; `/api/agent-logs/summary` gains `cost_usd` (non-breaking — existing tests still pass).
- **Migration**: fresh DB + pre-existing DB both gain the new columns; old rows read with defaults (`cost_usd=0`, `actor_type='system'`).
- **Frontend**: `npx tsc --noEmit` + build; manual: per-message footer renders + expands; dashboard chart toggles day/month/year and stack dimension.
- **E2E manual**: run a chat turn → footer shows tokens+cost, expand shows sub-agents; trigger an auto-RCA → appears under `actor_type=system`; `aiops cost --period month --by actor` matches the Web dashboard totals for the same range.

## 11. Files touched (map)

| Area | File | Change |
|------|------|--------|
| Cost fn | `src/agenticops/cost.py` | **new** — pure tokens→USD |
| Model | `src/agenticops/models.py` | +4 cols on `AgentLog`, +`trace_id` on `ChatMessage`, +index, +migration block |
| Config | `src/agenticops/config.py` | `token_cost_table` += cache_write + opus-4-8 |
| Write path | `src/agenticops/services/agent_log_service.py` | persist cache_write + cost_usd + actor; `track_agent` actor params |
| Extract | `src/agenticops/agents/metrics.py` | (already returns cache_write — confirm passthrough) |
| Attribution | `web/app.py` (SSE), `cli/main.py`, `services/{pipeline,rca,resolution}_service.py`, `scheduler/`, `integrations/`, `im/` | pass actor_type/actor_id |
| Aggregation | `src/agenticops/services/cost_service.py` | **new** |
| API | `src/agenticops/web/routers/cost.py` | **new**; register in `web/app.py`; `routers/agent_logs.py` +cost_usd |
| Schemas | `src/agenticops/web/schemas.py` | `ChatMessageResponse` += trace_id, cost_usd |
| CLI | `src/agenticops/cli/main.py`, `cli/display.py` | `aiops cost`; refactor `/tokens` to use `cost.py` |
| Web FE | `web/frontend/`: `AgentMetrics.tsx`, `hooks/useCostSummary.ts`, `components/chat/TokenMetrics.tsx`+`MessageItem`, `lib/chatStream.ts`, `api/types.ts`, `package.json` (+recharts) | dashboard mix chart + per-message footer |
| Tests | `tests/test_cost.py`, `tests/test_cost_service.py` (+ extend existing) | **new/extend** |

## 12. Future work (explicitly deferred)
- Budget limits + threshold alerting (notify at $X/day per actor).
- Pre-aggregated daily rollup table if `agent_logs` volume makes real-time bucketing slow (the API contract in §8 is designed so only `cost_service`'s internals change).
- Historical cost recompute on rate changes (today: snapshot only).
- `user_id` FK + true multi-tenant isolation if auth grows beyond single-admin.
