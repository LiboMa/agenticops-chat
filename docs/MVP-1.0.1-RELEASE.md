# AgenticOps v1.0.1 — Release Notes

> **Version**: 1.0.1 | **Date**: 2026-05-27 | **Branch**: main

---

## Highlights

This release focuses on **MCP Server integration reliability**, **dynamic model selection**, **schedule/task UX improvements**, and **security hardening** (no local path exposure in reports).

---

## New Features

### 1. Dynamic Model Selection (Bedrock API)

- `/api/models` endpoint — dynamically fetches available Claude models from Bedrock (us-east-1)
- 24h TTL cache with automatic refresh; falls back to `settings.yaml` when API unavailable
- `custom_models` field in settings.yaml for user-added models
- CLI `/model` displays full dynamic model list with version info
- Web Settings Agent Models dropdown uses dynamic presets

**Models discovered:** Opus 4.7/4.6/4.5/4.1, Sonnet 4.6/4.5, Haiku 4.5

### 2. MCP Server Integration (Fully Working)

| Capability | Details |
|------------|---------|
| **Chat tools** | `list_mcp_servers`, `validate_mcp_servers`, `add_mcp_server`, `remove_mcp_server`, `toggle_mcp_server`, `reload_mcp_servers` |
| **Hot-reload** | Validate → Stop → Rebuild (lazy-start on next chat) |
| **Tool name sanitize** | `.` → `_` in prefix (Bedrock requires `[a-zA-Z0-9_-]+`) |
| **AWS config isolation** | Auto-inject `config/aws-mcp.cfg` to avoid `~/.aws/config` plugin conflicts |
| **Clean subprocess env** | `get_default_environment()` + AWS creds only (no VIRTUAL_ENV leak) |
| **Graceful degradation** | MCP failure → agent works without MCP tools (no crash) |
| **Lazy-start** | Strands Agent manages MCP lifecycle; no pre-start at app startup |

### 3. Schedule & Task Management

| Feature | Details |
|---------|---------|
| **Type toggle** | `[Recurring | One-time]` in creation dialog |
| **schedule_type field** | DB column distinguishing `recurring` vs `one_time` |
| **Unlimited timeout** | Default `timeout_seconds=0` (run until complete) |
| **Retry mechanism** | `max_retries` (0-5), auto-retry on failure, notify on final attempt |
| **Search + Pagination** | Task list: search by name/pipeline, 10 per page, row numbers |
| **Draggable dialog** | Creation modal supports drag-to-move + resize |
| **Auto-disable** | One-time tasks auto-disable after execution |

### 4. Report Security & Dual-Write

- **Never expose local paths** — only filename + presigned URL shown to users
- **Dual-write**: local filesystem + S3 mirror upload (when `report_s3_bucket` configured)
- **Unified S3 config**: `settings.yaml` is single source of truth; channels.yaml can override per-channel
- **Presigned URLs** in all notification channels (Email, Slack, Feishu)

### 5. Notification Consolidation

- `notifications_consolidated: true` (new default) — suppresses per-issue notifications during Scan/Detect/RCA
- Only final report is sent to channels
- Set `false` for dev/debug to see every notification
- `_batch_mode` + `_schedule_running` runtime guards for dynamic control

### 6. IM WebSocket Auto-Detect

- Feishu/Slack WS auto-start from `channels.yaml` enabled channels
- No need for `AIOPS_FEISHU_WS_ENABLED=true` — presence of enabled channel is the signal
- CLI `service start` status display synced with auto-detect

---

## Bug Fixes

| Fix | Root Cause |
|-----|-----------|
| MCP "session is currently running" | `start_mcp_clients()` at app startup conflicted with Strands Agent lifecycle |
| MCP "Connection closed" | `uvx` install time + Strands eager init race condition |
| MCP "No module named '~/'" | `~/.aws/config` plugin path not expanded in uvx venv |
| MCP tool name ValidationException | Dots in server name violated Bedrock `[a-zA-Z0-9_-]+` constraint |
| MCP subprocess infinite spawn | `os.environ` leaked `VIRTUAL_ENV`/`UV_*` to child process |
| test_mcp import error | Module renamed `mcp.py` → `mcp_manager.py` but tests had stale import |
| Bedrock `[1m]` model ID error | `[1m]` suffix is Claude Code convention, not valid Bedrock model ID |

---

## Configuration Changes

| Setting | Old Default | New Default | Notes |
|---------|-------------|-------------|-------|
| `notifications_consolidated` | `false` | `true` | Suppress per-issue notifications |
| `feishu_ws_enabled` | `true` | `false` | Auto-detected from channels.yaml |
| `report_s3_bucket` | (not set) | `agenticops-reports-*` | Unified S3 config for all notifiers |

**New settings.yaml fields:**
- `custom_models: []` — additional model presets
- `report_s3_bucket` / `report_s3_prefix` / `report_s3_region` — unified S3 storage
- `report_presigned_url_expiry: 604800` — presigned URL TTL (7 days)

---

## Files Changed (Key)

| File | Change |
|------|--------|
| `services/model_service.py` | **NEW** — Bedrock API model discovery |
| `tools/mcp_tools.py` | **NEW** — Chat/CLI MCP management tools |
| `mcp_manager.py` | Sanitize, lazy-start, validate, hot-reload |
| `agents/main_agent.py` | MCP graceful degradation, MCP tools registered |
| `web/app.py` | `/api/models`, dynamic presets, no MCP pre-start |
| `tools/report_tools.py` | Dual-write local+S3, no path exposure |
| `tools/notification_tools.py` | S3 mirror upload, presigned URLs |
| `notify/notifier.py` | S3 config fallback to settings.yaml |
| `scheduler/scheduler.py` | schedule_type, max_retries, unlimited timeout |
| `config.py` | custom_models, notifications_consolidated default |
| `frontend/Schedules.tsx` | Type toggle, search, pagination, draggable |
| `frontend/Settings.tsx` | IM status card, Report Storage card, dynamic models |

---

## Upgrade Notes

1. Run `aiops service restart` to apply all changes
2. DB migration auto-runs: adds `schedule_type`, `max_retries`, `retry_count` columns
3. If using MCP servers: no action needed (lazy-start replaces pre-start)
4. `notifications_consolidated` now defaults to `true` — set `false` in settings.yaml if you want per-issue notifications during dev
