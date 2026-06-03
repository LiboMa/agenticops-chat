# Design: Unified "Messaging" Settings (merge Notifications + IM Bots)

**Date:** 2026-06-03
**Status:** Approved design → ready for implementation plan
**Goal (user's):** Make it **direct and simple** for users to configure IM bots, email, and bidirectional channels — by merging the redundant "Notifications" and "IM Bots" Settings tabs into one **Messaging** tab, with a card-based UX (borrowed from the Hermes Agents dashboard) rendered in our blue/white style.

## Problem

Settings has two overlapping tabs that confuse and duplicate:

- **Notifications tab** (`NotificationsTab` + `NotificationLogsTab`): channel CRUD via `/api/notifications/channels` (full config + `severity_filter`, raw-JSON config editing) + a delivery log viewer.
- **IM Bots tab** (`ImBotsTab`, inline in `Settings.tsx`): bot-app credentials (`/api/settings/im-apps`) **plus a second channel list** via `/api/settings/channels` (masks secrets, has enable toggle). Its card is even already titled "IM & Notifications".

**Verified crux:** both `/api/notifications/channels` and `/api/settings/channels` read/write the **same `channels.yaml`** via `load_channels()`/`save_channel()` in `notify/im_config.py`. They differ only in response shape (one exposes `severity_filter`+config, the other masks secrets). So the two "channel" lists are the **same data shown twice** — genuine duplication, safe to unify.

The one concept that is **not** duplicate and must be preserved as distinct:
- **Bot App** (`im-apps.yaml`) = inbound **connection credentials** (Feishu `app_id`/`app_secret`, Slack `bot_token`/`app_token`, DingTalk `app_key`/`app_secret`, WeCom `corp_id`/`corp_secret`/`agent_id`) used by the IM gateway to open a WebSocket and **receive** messages (bidirectional chat).
- **Channel** (`channels.yaml`) = **routing rule** (where to send: name, type, chat_id/sender/recipients, `role` = alert|chat, `severity_filter`, `enabled`); references a bot app by `app_name`.

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Merge | One **Messaging** tab; **delete** the old Notifications + IM Bots tabs (and `NotificationsTab`/`ImBotsTab`/`NotificationLogsTab` components are folded in / removed). |
| Backend | **New unified `/api/messaging/*`** (`apps`, `channels`, `logs`). The old `/api/notifications/*` and `/api/settings/{channels,im-apps}` endpoints are **kept but marked deprecated** (CLI / external callers may still use them). |
| Storage | Unchanged: `channels.yaml` (channels) + `im-apps.yaml` (bot apps) + `NotificationLog` DB table (logs). New API is a clean facade over the existing `im_config.py` load/save functions. **No YAML schema change, no DB migration.** |
| Page layout | 3 sections: **Bot Apps** / **Channels** (email/SES are just channel types here) / **Delivery Logs**. |
| Card UX | stroke-SVG icons (project `Icon*` idiom, no emoji), `w-8 h-8 rounded-lg` icon chip, status badge + pulsing dot, enable Switch, **Test** (⚡), **Configure** (⚙). Top **informational restart note** when bot creds change (text only — no restart endpoint exists; see Error handling). |
| Configure modal | Per-row modal; **segmented type tiles** drive **dynamic fields** (only show fields the type needs); secrets are `password` + eye-reveal + "encrypted at rest"; footer **Test** + Cancel + **Save & enable**. |
| Email | `email` (SMTP) and `ses` (AWS SES) are **channel types** (tiles alongside Slack/Feishu/SNS/Webhook), not a separate section. |
| Theme | Borrow Hermes **structure** (connection cards, status badges, configure-modal, test, restart banner, masked-secret rows), render in **our blue/white** (`--primary-*` + semantic tokens). Light + dark both work. |

## Non-goals (YAGNI)

- No change to the notification **firing** pipeline (`notification_service.py` triggers, gating, consolidation) — only the config UI/API.
- No change to the IM **gateway** runtime (`im/feishu_ws.py` etc.) — it keeps reading `im-apps.yaml`/`channels.yaml`.
- No YAML restructure, no `NotificationChannel` DB resurrection (it's already YAML-only).
- No validation gate restricting which channel types may exist (keep current permissiveness).
- No new email provider; just surface existing `email`/`ses`.

## Architecture

### Backend — new facade `web/routers/messaging.py` (or a section in app.py) exposing `/api/messaging/*`

All endpoints are thin wrappers over existing `notify/im_config.py` functions — **no new storage logic**.

**Apps** (bot credentials, `im-apps.yaml`):
- `GET /api/messaging/apps` → `get_apps_detail()` (secrets masked, same as today's `/api/settings/im-apps`).
- `PUT /api/messaging/apps/{platform}/{name}` → `save_app(platform, name, config)`. After write, set a process flag so the UI can show the **restart banner** (creds need gateway restart).
- `DELETE /api/messaging/apps/{platform}/{name}` → `delete_app(...)`.
- `POST /api/messaging/apps/{platform}/{name}/test` → attempt a lightweight connectivity check (e.g. token/app_id present + a platform ping if cheap); return ok/error. (If a true ping is expensive/risky, validate presence + format only — decide at impl, log what it does.)

**Channels** (routing, `channels.yaml`) — unifies the two old channel APIs into one with the **fuller** shape:
- `GET /api/messaging/channels` → `load_channels()` → list of `{name, type, enabled, role, severity_filter, config}` with **secret keys masked** in `config` (best of both: full shape + masked secrets).
- `PUT /api/messaging/channels/{name}` → `save_channel(name, channel_type, config, is_enabled, severity_filter)`. `config` excludes reserved keys (`type/enabled/severity_filter/preferred_format/role/alert_senders` per `_CHANNEL_RESERVED_KEYS`); `role` passed through the config/entry.
- `DELETE /api/messaging/channels/{name}` → `delete_channel(name)`.
- `PATCH /api/messaging/channels/{name}/toggle` → flip `enabled` via `save_channel`.
- `POST /api/messaging/channels/{name}/test` → reuse the existing notifier test path (the same one `/api/notifications/channels/{name}/test` uses → writes a `NotificationLog`).

**Logs**:
- `GET /api/messaging/logs?channel_name=&status=&limit=` → `NotificationLog` query (same as today's `/api/notifications/logs`).

**Type schema for dynamic forms** — the key to "simple config". A static descriptor (backend constant or shared TS const) declares, per type, the fields the Configure modal renders:
- `channel` types: `slack` (webhook_url **or** bot_token+chat_id), `feishu` (app_name+chat_id), `dingtalk` (app_name+chat_id), `wecom` (app_name+touser), `email` (smtp host/port/user/pass/from/to), `ses` (sender/recipients/region/[s3 for reports]), `sns`/`sns-report` (topic_arn/region/[s3...]), `webhook` (url/headers). Each field: `{key, label, type: text|password|number|list|select, required, secret}`.
- `app` platforms: `feishu` (app_id, app_secret*), `slack` (bot_token*, app_token*), `dingtalk` (app_key, app_secret*), `wecom` (corp_id, corp_secret*, agent_id). (* = secret.)
- **Decision:** define this descriptor **once on the backend** (`GET /api/messaging/schema` or embed in the list responses) so the frontend form is data-driven and stays in sync with what the notifier classes actually accept. (Mirrors Hermes' `AutoField` schema-driven form.)

**Deprecation:** old endpoints stay functional; add a `Deprecated` note in their docstrings/OpenAPI. No removal this round (CLI `/channel`, IM gateway, external scripts may call them).

### Frontend — new `pages/` section + components

- **New** `components/settings/MessagingTab.tsx` — the 3-section page (Bot Apps / Channels / Delivery Logs) using the card pattern.
- **New** `components/settings/ConfigureModal.tsx` — schema-driven modal: segmented type tiles → dynamic fields (from `/api/messaging/schema`), secret mask + eye, Test, Save & enable.
- **New** `hooks/useMessaging.ts` — `useMessagingApps`, `useMessagingChannels`, `useMessagingLogs`, mutations (upsert/delete/toggle/test for both apps & channels), `useMessagingSchema`.
- **Modify** `pages/Settings.tsx` — replace the `notifications` + `im-bots` `Tabs.Trigger`/`Tabs.Content` with a single `messaging` tab rendering `<MessagingTab/>`. Remove the inline `ImBotsTab` function.
- **Delete** `components/settings/NotificationsTab.tsx`, `NotificationLogsTab.tsx` (their capability moves into MessagingTab; the raw-JSON channel form is replaced by the dynamic form). Old `hooks/useNotifications.ts` / `useImApps.ts` either removed or left unused (decide at impl — prefer removing the now-dead hooks to avoid confusion).
- **i18n**: add `settings.messaging` label; drop `settings.notifications` usage from the tab list (keep the key if referenced elsewhere).

### Data flow

```
MessagingTab
  ├─ Bot Apps   → useMessagingApps  → GET /api/messaging/apps      → get_apps_detail() (im-apps.yaml, masked)
  │   Configure → PUT /api/messaging/apps/{platform}/{name}        → save_app()  → restart-needed flag
  ├─ Channels   → useMessagingChannels → GET /api/messaging/channels → load_channels() (channels.yaml, masked)
  │   Configure → PUT /api/messaging/channels/{name}               → save_channel()
  │   Toggle    → PATCH .../toggle ; Test → POST .../test (→ NotificationLog)
  └─ Logs       → useMessagingLogs   → GET /api/messaging/logs       → NotificationLog query
  Dynamic form fields ← GET /api/messaging/schema (per type/platform descriptor)
```

## Error handling

- Configure modal: client validates required fields before save; backend returns 400 with the specific missing/invalid field; secrets never returned in full (masked on GET; write-only on PUT — empty secret field = "keep existing", non-empty = replace).
- Test: returns `{ok, error}`; modal shows inline success/failure; channel test writes a `NotificationLog` (visible in the Logs section).
- Restart banner: **verified there is NO IM-gateway restart endpoint today** (only MCP has `/api/settings/mcp-servers/reload`). So the banner is **informational only** — after an app-credential PUT in the current process, show a dismissible note: "Bot credentials saved — restart the service (`aiops service restart`) for the IM gateway to pick them up." **No fabricated "Restart now" button / endpoint.** (An `/api/messaging/apps/reload` mirroring the MCP reload pattern is a sensible future enhancement but is explicitly OUT OF SCOPE here.)

## Testing

**Backend (pytest):**
- `/api/messaging/channels` GET returns unified shape with secrets masked; PUT round-trips to `channels.yaml` (seed temp file via `settings.channels_config`); toggle flips enabled; DELETE removes.
- `/api/messaging/apps` GET masks secrets; PUT save_app round-trips to `im-apps.yaml`; DELETE removes.
- `/api/messaging/logs` filters by channel_name/status.
- `/api/messaging/schema` returns a descriptor containing all channel types + app platforms with required/secret flags.
- Old `/api/notifications/channels` + `/api/settings/channels` still work (no regression — they share the same store).

**Frontend (vitest, node — pure logic only):**
- A pure `messagingSchema` helper / field-builder: given a type, returns the right field list; secret fields flagged. (Mirrors the backend descriptor; unit-test the mapping + the "empty secret = keep" merge logic.)

**Manual (Playwright, light + dark):** Messaging tab shows 3 sections with SVG icons (no emoji); Configure modal: pick type tile → fields change; secret mask + eye; Save & enable; toggle; Test writes a log; old two tabs gone; both themes legible.

## Scope guardrails

- **Touched (frontend):** `pages/Settings.tsx` (tab swap), new `MessagingTab.tsx` + `ConfigureModal.tsx` + `hooks/useMessaging.ts`; delete `NotificationsTab.tsx`/`NotificationLogsTab.tsx` + dead hooks; i18n label.
- **Touched (backend):** new `/api/messaging/*` facade over existing `im_config.py` functions + a `schema` descriptor; deprecation notes on old endpoints. **No** change to `im_config.py` storage, `notifier.py`, `notification_service.py`, gateways, or YAML/DB schema.
- **No new deps. No new features** beyond the dynamic-form + Test + unified view; firing pipeline & gateway untouched.

## Documentation (per CLAUDE.md rule 7)

After implementation: update `docs/WORKFLOW.md` (notification/messaging section), `CLAUDE.md` (note Settings Messaging tab + `/api/messaging`), and the next release notes. Note in CLAUDE.md that `config/channels.yaml` + `config/im-apps.yaml` remain the source of truth.
