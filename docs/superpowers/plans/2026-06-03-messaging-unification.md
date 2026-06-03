# Unified "Messaging" Settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the redundant "Notifications" + "IM Bots" Settings tabs into one **Messaging** tab (Bot Apps / Channels / Delivery Logs), backed by a new `/api/messaging/*` facade with a schema-driven Configure modal, and delete the now-dead components.

**Architecture:** A new backend facade (`/api/messaging/*`) wraps the existing `notify/im_config.py` load/save functions + `NotificationLog` + the notifier test path — no storage/schema change. A `/api/messaging/schema` descriptor declares per-type fields so the frontend Configure modal is data-driven. The frontend gets one `MessagingTab` (card UX, stroke-SVG icons, blue/white) + a schema-driven `ConfigureModal`; the old `NotificationsTab`/`NotificationLogsTab`/inline `ImBotsTab` and dead hooks are removed.

**Tech Stack:** FastAPI + existing `im_config.py`/`notifier.py` (backend); React 18 + TanStack Query + Tailwind + Vitest (frontend); pytest + Starlette TestClient.

**Spec:** `docs/superpowers/specs/2026-06-03-messaging-unification-design.md`

---

## Conventions

- **Backend tests:** `.venv/bin/python -m pytest tests/<file> -v`. Seed temp YAML via `settings.channels_config` / im-apps path; clean up. Follow `tests/test_chat_api.py` TestClient pattern.
- **Backend compile:** `python3 -m py_compile src/agenticops/web/app.py src/agenticops/notify/im_config.py`.
- **Frontend tests:** from `src/agenticops/web/frontend/`, `npm run test` (vitest `--run`, node env, pure-logic only — no DOM rendering).
- **Type-check/build:** `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build`.
- **Commits:** one per task, `git commit --no-verify`. Do NOT push.
- **`lib/` gitignore caveat:** new files under `src/.../lib/` need `git add -f`. `hooks/`, `components/`, `pages/`, `__tests__/` add normally.
- **Branch:** continue on `MVP-1.1.1-RELEASE`.
- **CRITICAL — facade only:** the new `/api/messaging/*` endpoints must call the EXISTING `im_config.py` functions (`get_apps_detail`, `save_app`, `delete_app`, `load_channels`, `save_channel`, `delete_channel`, `get_channel`) and the EXISTING notifier test path. Do NOT modify `im_config.py` storage logic, `notifier.py`, `notification_service.py`, gateways, or any YAML/DB schema.

### Verified backend facts (use these exact names)

- `im_config.py`: `get_apps_detail() -> Dict[str,Dict[str,dict]]`, `save_app(platform, app_name, config: dict)`, `delete_app(platform, app_name) -> bool`, `list_apps()`, `load_channels() -> List[ChannelConfig]`, `get_channel(name) -> Optional[ChannelConfig]`, `save_channel(name, channel_type, config, is_enabled=True, severity_filter=None)`, `delete_channel(name) -> bool`. `ChannelConfig` fields: `name, channel_type, config, is_enabled, severity_filter, preferred_format, role, alert_senders`. `_CHANNEL_RESERVED_KEYS = frozenset(("type","enabled","severity_filter","preferred_format","role","alert_senders"))`.
- `app.py`: `_SENSITIVE_IM_KEYS = {"app_secret","secret","bot_token","app_token","password","access_key_secret"}`; `_mask_im_secrets(config)` helper exists. `NotificationSendRequest` schema (subject, body, severity) exists. `NotificationLog` model + `NotificationLogResponse` exist. `NotificationManager.NOTIFIER_CLASSES` keys = `slack, email, ses, sns, sns-report, feishu, dingtalk, wecom, webhook`.
- IM app platforms + required fields: `feishu` (app_id, app_secret*), `slack` (bot_token*, app_token*), `dingtalk` (app_key, app_secret*), `wecom` (corp_id, corp_secret*, agent_id). (* = secret.)
- **No IM-gateway restart endpoint exists** → restart note is informational text only.

---

## File Structure

**Backend (modify):**
- `src/agenticops/web/app.py` — add `/api/messaging/*` endpoints + `MESSAGING_SCHEMA` constant + mark old endpoints deprecated (docstring only).

**Backend (test, create):**
- `tests/test_messaging_api.py` — facade endpoints + schema.

**Frontend (create):**
- `src/agenticops/web/frontend/src/hooks/useMessaging.ts` — apps/channels/logs/schema queries + mutations.
- `src/agenticops/web/frontend/src/lib/messagingFields.ts` — pure helper: build field list from schema + secret-merge logic (the only unit-tested piece).
- `src/agenticops/web/frontend/src/components/settings/ConfigureModal.tsx` — schema-driven modal.
- `src/agenticops/web/frontend/src/components/settings/MessagingTab.tsx` — the 3-section page.
- `src/agenticops/web/frontend/src/__tests__/messagingFields.test.ts` — tests for the pure helper.

**Frontend (modify):**
- `src/agenticops/web/frontend/src/pages/Settings.tsx` — replace `notifications` + `im-bots` tabs with one `messaging` tab; remove inline `ImBotsTab` + its imports.
- `src/agenticops/web/frontend/src/locales/en.json` + `zh.json` — add `settings.messaging`.

**Frontend (delete):**
- `src/agenticops/web/frontend/src/components/settings/NotificationsTab.tsx`
- `src/agenticops/web/frontend/src/components/settings/NotificationLogsTab.tsx`
- `src/agenticops/web/frontend/src/hooks/useImApps.ts` (folded into useMessaging)
- `src/agenticops/web/frontend/src/hooks/useNotifications.ts` (if no other consumer — verify in Task 7)

---

## Task 1: Backend — `MESSAGING_SCHEMA` descriptor + `/api/messaging/schema` (TDD)

**Files:**
- Create: `tests/test_messaging_api.py`
- Modify: `src/agenticops/web/app.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_messaging_api.py`:

```python
"""Tests for the unified /api/messaging/* facade."""

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestMessagingSchema:
    def test_schema_lists_channel_types_and_app_platforms(self, client):
        resp = client.get("/api/messaging/schema")
        assert resp.status_code == 200
        body = resp.json()
        # channel types present
        ch = body["channel_types"]
        names = {c["type"] for c in ch}
        assert {"slack", "feishu", "dingtalk", "wecom", "email", "ses", "sns", "sns-report", "webhook"} <= names
        # app platforms present
        ap = body["app_platforms"]
        pnames = {p["platform"] for p in ap}
        assert {"feishu", "slack", "dingtalk", "wecom"} == pnames

    def test_feishu_app_has_secret_flagged_field(self, client):
        body = client.get("/api/messaging/schema").json()
        feishu = next(p for p in body["app_platforms"] if p["platform"] == "feishu")
        fields = {f["key"]: f for f in feishu["fields"]}
        assert fields["app_id"]["required"] is True
        assert fields["app_secret"]["secret"] is True

    def test_ses_channel_has_sender_recipients(self, client):
        body = client.get("/api/messaging/schema").json()
        ses = next(c for c in body["channel_types"] if c["type"] == "ses")
        keys = {f["key"] for f in ses["fields"]}
        assert "sender" in keys and "recipients" in keys
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_messaging_api.py -v`
Expected: FAIL (404 — `/api/messaging/schema` not defined).

- [ ] **Step 3: Add the schema constant + endpoint**

In `src/agenticops/web/app.py`, immediately BEFORE the existing `@app.get("/api/settings/im-apps")` block (around line 788), insert:

```python
# ============================================================================
# Messaging — unified facade over channels.yaml + im-apps.yaml + NotificationLog
# (replaces the separate Notifications + IM Bots settings tabs)
# ============================================================================

# Schema descriptor: drives the frontend's dynamic Configure form.
# field: {key, label, type: text|password|number|list|select, required, secret}
MESSAGING_SCHEMA: dict = {
    "app_platforms": [
        {"platform": "feishu", "label": "Feishu (飞书)", "fields": [
            {"key": "app_id", "label": "App ID", "type": "text", "required": True, "secret": False},
            {"key": "app_secret", "label": "App Secret", "type": "password", "required": True, "secret": True},
        ]},
        {"platform": "slack", "label": "Slack", "fields": [
            {"key": "bot_token", "label": "Bot Token (xoxb-)", "type": "password", "required": True, "secret": True},
            {"key": "app_token", "label": "App Token (xapp-)", "type": "password", "required": True, "secret": True},
        ]},
        {"platform": "dingtalk", "label": "DingTalk (钉钉)", "fields": [
            {"key": "app_key", "label": "App Key", "type": "text", "required": True, "secret": False},
            {"key": "app_secret", "label": "App Secret", "type": "password", "required": True, "secret": True},
        ]},
        {"platform": "wecom", "label": "WeCom (企业微信)", "fields": [
            {"key": "corp_id", "label": "Corp ID", "type": "text", "required": True, "secret": False},
            {"key": "corp_secret", "label": "Corp Secret", "type": "password", "required": True, "secret": True},
            {"key": "agent_id", "label": "Agent ID", "type": "number", "required": False, "secret": False},
        ]},
    ],
    "channel_types": [
        {"type": "slack", "label": "Slack", "fields": [
            {"key": "webhook_url", "label": "Webhook URL", "type": "text", "required": False, "secret": False},
            {"key": "app_name", "label": "Bot App name (for bot mode)", "type": "text", "required": False, "secret": False},
            {"key": "chat_id", "label": "Channel ID (bot mode)", "type": "text", "required": False, "secret": False},
        ]},
        {"type": "feishu", "label": "Feishu (飞书)", "fields": [
            {"key": "app_name", "label": "Bot App name", "type": "text", "required": True, "secret": False},
            {"key": "chat_id", "label": "Chat ID (oc_...)", "type": "text", "required": True, "secret": False},
        ]},
        {"type": "dingtalk", "label": "DingTalk (钉钉)", "fields": [
            {"key": "app_name", "label": "Bot App name", "type": "text", "required": True, "secret": False},
            {"key": "chat_id", "label": "Conversation ID (cid...)", "type": "text", "required": True, "secret": False},
        ]},
        {"type": "wecom", "label": "WeCom (企业微信)", "fields": [
            {"key": "app_name", "label": "Bot App name", "type": "text", "required": True, "secret": False},
            {"key": "touser", "label": "To user(s)", "type": "text", "required": False, "secret": False},
        ]},
        {"type": "email", "label": "Email (SMTP)", "fields": [
            {"key": "smtp_host", "label": "SMTP Host", "type": "text", "required": True, "secret": False},
            {"key": "smtp_port", "label": "SMTP Port", "type": "number", "required": True, "secret": False},
            {"key": "username", "label": "Username", "type": "text", "required": False, "secret": False},
            {"key": "password", "label": "Password", "type": "password", "required": False, "secret": True},
            {"key": "from_addr", "label": "From", "type": "text", "required": True, "secret": False},
            {"key": "to_addrs", "label": "To (comma-separated)", "type": "list", "required": True, "secret": False},
        ]},
        {"type": "ses", "label": "Email (AWS SES)", "fields": [
            {"key": "sender", "label": "Sender", "type": "text", "required": True, "secret": False},
            {"key": "recipients", "label": "Recipients (comma-separated)", "type": "list", "required": True, "secret": False},
            {"key": "region", "label": "AWS Region", "type": "text", "required": True, "secret": False},
        ]},
        {"type": "sns", "label": "AWS SNS", "fields": [
            {"key": "topic_arn", "label": "Topic ARN", "type": "text", "required": True, "secret": False},
            {"key": "region", "label": "AWS Region", "type": "text", "required": True, "secret": False},
        ]},
        {"type": "sns-report", "label": "SNS Report (SNS + S3)", "fields": [
            {"key": "topic_arn", "label": "Topic ARN", "type": "text", "required": True, "secret": False},
            {"key": "region", "label": "AWS Region", "type": "text", "required": True, "secret": False},
            {"key": "s3_bucket", "label": "S3 Bucket", "type": "text", "required": False, "secret": False},
            {"key": "s3_prefix", "label": "S3 Prefix", "type": "text", "required": False, "secret": False},
        ]},
        {"type": "webhook", "label": "Webhook", "fields": [
            {"key": "url", "label": "URL", "type": "text", "required": True, "secret": False},
        ]},
    ],
}


@app.get("/api/messaging/schema")
async def api_messaging_schema():
    """Field descriptor for the dynamic Configure form (channel types + app platforms)."""
    return MESSAGING_SCHEMA
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_messaging_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Compile + commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/web/app.py
git add src/agenticops/web/app.py tests/test_messaging_api.py
git commit --no-verify -m "feat(api): /api/messaging/schema descriptor for dynamic Configure form"
```

---

## Task 2: Backend — `/api/messaging/apps` (list/upsert/delete) (TDD)

**Files:**
- Modify: `src/agenticops/web/app.py`
- Modify: `tests/test_messaging_api.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_messaging_api.py`:

```python
class TestMessagingApps:
    def test_list_apps_masks_secrets(self, client, monkeypatch):
        import agenticops.web.app as webapp
        fake = {"feishu": {"default": {"app_id": "cli_123456", "app_secret": "supersecretvalue"}}}
        monkeypatch.setattr(webapp, "_messaging_get_apps_detail", lambda: fake, raising=False)
        # Patch the underlying im_config function the endpoint calls:
        import agenticops.notify.im_config as imc
        monkeypatch.setattr(imc, "get_apps_detail", lambda: fake)
        resp = client.get("/api/messaging/apps")
        assert resp.status_code == 200
        body = resp.json()
        secret = body["feishu"]["default"]["app_secret"]
        assert secret.startswith("****") and "supersecret" not in secret
        assert body["feishu"]["default"]["app_id"] == "cli_123456"  # non-secret unmasked

    def test_upsert_app_invalid_platform_400(self, client):
        resp = client.put("/api/messaging/apps/badplatform/default", json={"app_id": "x"})
        assert resp.status_code == 400

    def test_upsert_and_delete_app(self, client, monkeypatch):
        import agenticops.notify.im_config as imc
        saved = {}
        monkeypatch.setattr(imc, "save_app", lambda p, n, c: saved.update({(p, n): c}))
        monkeypatch.setattr(imc, "delete_app", lambda p, n: saved.pop((p, n), None) is not None)
        r1 = client.put("/api/messaging/apps/feishu/default", json={"app_id": "cli_x", "app_secret": "s"})
        assert r1.status_code == 200 and ("feishu", "default") in saved
        r2 = client.delete("/api/messaging/apps/feishu/default")
        assert r2.status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_messaging_api.py::TestMessagingApps -v`
Expected: FAIL (404).

- [ ] **Step 3: Add the apps endpoints**

In `src/agenticops/web/app.py`, immediately after the `api_messaging_schema` function, insert:

```python
@app.get("/api/messaging/apps")
async def api_messaging_list_apps():
    """List IM bot apps (credentials) with secrets masked."""
    from agenticops.notify.im_config import get_apps_detail
    apps = get_apps_detail()
    return {
        platform: {name: _mask_im_secrets(cfg) for name, cfg in platform_apps.items()}
        for platform, platform_apps in apps.items()
    }


@app.put("/api/messaging/apps/{platform}/{name}")
async def api_messaging_upsert_app(platform: str, name: str, body: dict = Body(...)):
    """Create/update a bot app credential. Empty secret fields keep the existing value."""
    from agenticops.notify.im_config import save_app, get_apps_detail
    valid = {"feishu", "dingtalk", "wecom", "slack"}
    if platform not in valid:
        raise HTTPException(400, f"Invalid platform. Valid: {', '.join(sorted(valid))}")
    # Merge: a blank secret field means "keep existing" (the GET masked it).
    existing = get_apps_detail().get(platform, {}).get(name, {})
    merged = dict(existing)
    for k, v in body.items():
        if k.lower() in _SENSITIVE_IM_KEYS and (v == "" or v is None):
            continue  # keep existing secret
        merged[k] = v
    save_app(platform, name, merged)
    return {"platform": platform, "name": name, "status": "saved", "restart_hint": True}


@app.delete("/api/messaging/apps/{platform}/{name}")
async def api_messaging_delete_app(platform: str, name: str):
    """Delete a bot app credential."""
    from agenticops.notify.im_config import delete_app
    if not delete_app(platform, name):
        raise HTTPException(404, f"App '{platform}/{name}' not found")
    return {"status": "deleted"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_messaging_api.py -v`
Expected: PASS (all, incl. Task 1's).

- [ ] **Step 5: Compile + commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/web/app.py
git add src/agenticops/web/app.py tests/test_messaging_api.py
git commit --no-verify -m "feat(api): /api/messaging/apps — bot credential CRUD (masked, secret-keep merge)"
```

---

## Task 3: Backend — `/api/messaging/channels` (list/upsert/delete/toggle/test) + `/logs` (TDD)

**Files:**
- Modify: `src/agenticops/web/app.py`
- Modify: `tests/test_messaging_api.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_messaging_api.py`:

```python
class TestMessagingChannels:
    def test_list_channels_masks_secret_config(self, client, monkeypatch):
        import agenticops.notify.im_config as imc
        from agenticops.notify.im_config import ChannelConfig
        chans = [
            ChannelConfig(name="feishu-alert", channel_type="feishu",
                          config={"chat_id": "oc_x", "app_secret": "topsecret"},
                          is_enabled=False, severity_filter=[], role="alert"),
        ]
        monkeypatch.setattr(imc, "load_channels", lambda: chans)
        resp = client.get("/api/messaging/channels")
        assert resp.status_code == 200
        body = resp.json()
        ch = body[0]
        assert ch["name"] == "feishu-alert"
        assert ch["type"] == "feishu"
        assert ch["enabled"] is False
        assert ch["role"] == "alert"
        assert ch["config"]["chat_id"] == "oc_x"
        assert "topsecret" not in str(ch["config"].get("app_secret", ""))  # masked/dropped

    def test_upsert_channel_requires_type(self, client):
        resp = client.put("/api/messaging/channels/x", json={"chat_id": "oc_y"})
        assert resp.status_code == 400

    def test_upsert_channel_roundtrips(self, client, monkeypatch):
        import agenticops.notify.im_config as imc
        saved = {}
        monkeypatch.setattr(imc, "save_channel",
                            lambda name, ct, cfg, is_enabled=True, severity_filter=None: saved.update(
                                {"name": name, "ct": ct, "cfg": cfg, "en": is_enabled}))
        resp = client.put("/api/messaging/channels/feishu-alert",
                          json={"type": "feishu", "enabled": True, "role": "alert",
                                "config": {"app_name": "default", "chat_id": "oc_x"}})
        assert resp.status_code == 200
        assert saved["name"] == "feishu-alert" and saved["ct"] == "feishu" and saved["en"] is True
        assert saved["cfg"]["chat_id"] == "oc_x" and saved["cfg"]["role"] == "alert"

    def test_delete_channel(self, client, monkeypatch):
        import agenticops.notify.im_config as imc
        monkeypatch.setattr(imc, "delete_channel", lambda name: True)
        assert client.delete("/api/messaging/channels/x").status_code == 200

    def test_logs_endpoint_ok(self, client):
        resp = client.get("/api/messaging/logs?limit=5")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_messaging_api.py::TestMessagingChannels -v`
Expected: FAIL (404).

- [ ] **Step 3: Add channel + logs endpoints**

In `src/agenticops/web/app.py`, after the `api_messaging_delete_app` function, insert:

```python
def _mask_channel_config(config: dict) -> dict:
    """Drop secret-ish keys from a channel config for safe display."""
    return {k: v for k, v in config.items()
            if "token" not in k.lower() and "secret" not in k.lower() and "password" not in k.lower()}


@app.get("/api/messaging/channels")
async def api_messaging_list_channels():
    """List all channels (routing) with full shape + secrets masked."""
    from agenticops.notify.im_config import load_channels
    return [
        {
            "name": c.name,
            "type": c.channel_type,
            "enabled": c.is_enabled,
            "role": c.role,
            "severity_filter": c.severity_filter,
            "preferred_format": c.preferred_format,
            "config": _mask_channel_config(c.config),
        }
        for c in load_channels()
    ]


@app.put("/api/messaging/channels/{name}")
async def api_messaging_upsert_channel(name: str, body: dict = Body(...)):
    """Create/update a channel. Body: {type, enabled, role, severity_filter, config}.
    Blank secret config values keep the existing stored value."""
    from agenticops.notify.im_config import save_channel, get_channel
    channel_type = body.get("type", "")
    if not channel_type:
        raise HTTPException(400, "Field 'type' is required")
    enabled = body.get("enabled", True)
    role = body.get("role", "chat")
    severity_filter = body.get("severity_filter") or None
    config = dict(body.get("config", {}))
    config["role"] = role  # role is stored inside the channel entry (reserved key handled by save_channel)
    # secret-keep merge: blank secret value → keep existing
    existing = get_channel(name)
    if existing:
        for k, v in list(config.items()):
            if ("token" in k.lower() or "secret" in k.lower() or "password" in k.lower()) and (v == "" or v is None):
                if k in existing.config:
                    config[k] = existing.config[k]
                else:
                    config.pop(k, None)
    save_channel(name, channel_type, config, is_enabled=enabled, severity_filter=severity_filter)
    return {"name": name, "type": channel_type, "status": "saved"}


@app.delete("/api/messaging/channels/{name}")
async def api_messaging_delete_channel(name: str):
    """Delete a channel."""
    from agenticops.notify.im_config import delete_channel
    if not delete_channel(name):
        raise HTTPException(404, f"Channel '{name}' not found")
    return {"status": "deleted"}


@app.patch("/api/messaging/channels/{name}/toggle")
async def api_messaging_toggle_channel(name: str, body: dict = Body(...)):
    """Enable/disable a channel."""
    from agenticops.notify.im_config import load_channels, save_channel
    enabled = body.get("enabled", True)
    ch = next((c for c in load_channels() if c.name == name), None)
    if not ch:
        raise HTTPException(404, f"Channel '{name}' not found")
    save_channel(name, ch.channel_type, ch.config, is_enabled=enabled, severity_filter=ch.severity_filter or None)
    return {"name": name, "enabled": enabled}


@app.post("/api/messaging/channels/{name}/test")
async def api_messaging_test_channel(name: str, data: NotificationSendRequest):
    """Send a test message through a channel (reuses the notifier path; writes a NotificationLog)."""
    from agenticops.notify.im_config import get_channel
    from agenticops.notify.notifier import NotificationManager
    channel = get_channel(name)
    if not channel:
        raise HTTPException(404, "Channel not found")
    notifier_class = NotificationManager.NOTIFIER_CLASSES.get(channel.channel_type)
    if not notifier_class:
        raise HTTPException(400, f"Unknown channel type: {channel.channel_type}")
    try:
        notifier = notifier_class(channel.config)
        success = await notifier.send(subject=data.subject, body=data.body, severity=data.severity)
        return {"status": "sent" if success else "failed", "channel": channel.name}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "failed", "channel": channel.name, "error": str(e)})


@app.get("/api/messaging/logs", response_model=List[NotificationLogResponse])
async def api_messaging_logs(
    channel_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """Delivery logs (reuses NotificationLog)."""
    from agenticops.notify.notifier import NotificationLog
    with get_db_session() as session:
        q = session.query(NotificationLog).order_by(NotificationLog.sent_at.desc())
        if channel_name:
            q = q.filter_by(channel_name=channel_name)
        if status:
            q = q.filter_by(status=status)
        return [NotificationLogResponse.model_validate(log) for log in q.offset(offset).limit(limit).all()]
```

- [ ] **Step 4: Run + regression**

Run: `.venv/bin/python -m pytest tests/test_messaging_api.py -v`
Expected: PASS (all).
Run: `.venv/bin/python -m pytest tests/test_chat_api.py -q`
Expected: PASS (no regression).

- [ ] **Step 5: Mark old endpoints deprecated (docstring only) + compile + commit**

Add `" [DEPRECATED: use /api/messaging/*]"` to the docstrings of `api_list_im_apps` (line ~789), `api_upsert_im_app`, `api_delete_im_app`, `api_list_channels`, `api_upsert_channel`, `api_delete_channel`, `api_toggle_channel`, `api_list_notification_channels`, `api_test_notification_channel`, `api_list_notification_logs`. Do NOT change their behavior.

```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/web/app.py
git add src/agenticops/web/app.py tests/test_messaging_api.py
git commit --no-verify -m "feat(api): /api/messaging/channels + /logs (unified); deprecate old channel/im endpoints"
```

---

## Task 4: Frontend — `messagingFields.ts` pure helper + tests (TDD)

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/messagingFields.ts`
- Create: `src/agenticops/web/frontend/src/__tests__/messagingFields.test.ts`

- [ ] **Step 1: Write the helper**

Create `src/agenticops/web/frontend/src/lib/messagingFields.ts`:

```typescript
// Pure helpers for the schema-driven Configure form (no React).

export interface FieldDescriptor {
  key: string;
  label: string;
  type: "text" | "password" | "number" | "list" | "select";
  required: boolean;
  secret: boolean;
}
export interface TypeDescriptor { type?: string; platform?: string; label: string; fields: FieldDescriptor[]; }
export interface MessagingSchema { app_platforms: TypeDescriptor[]; channel_types: TypeDescriptor[]; }

/** Find the field list for a channel type. */
export function channelFields(schema: MessagingSchema | undefined, type: string): FieldDescriptor[] {
  return schema?.channel_types.find((c) => c.type === type)?.fields ?? [];
}

/** Find the field list for an app platform. */
export function appFields(schema: MessagingSchema | undefined, platform: string): FieldDescriptor[] {
  return schema?.app_platforms.find((p) => p.platform === platform)?.fields ?? [];
}

/** Validate required fields against current values; returns missing field keys. */
export function missingRequired(fields: FieldDescriptor[], values: Record<string, string>): string[] {
  return fields.filter((f) => f.required && !String(values[f.key] ?? "").trim()).map((f) => f.key);
}

/**
 * Build the payload to send. Secret fields left blank are OMITTED (backend keeps existing).
 * `list` type fields are split on commas into arrays.
 */
export function buildConfigPayload(fields: FieldDescriptor[], values: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = values[f.key];
    if (raw == null || raw === "") {
      if (f.secret) continue;        // blank secret → keep existing (omit)
      if (!f.required) continue;     // blank optional → omit
    }
    if (f.type === "list") {
      out[f.key] = String(raw ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    } else if (f.type === "number") {
      out[f.key] = raw === "" || raw == null ? undefined : Number(raw);
    } else {
      out[f.key] = raw;
    }
  }
  return out;
}
```

- [ ] **Step 2: Write the failing tests**

Create `src/agenticops/web/frontend/src/__tests__/messagingFields.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { channelFields, appFields, missingRequired, buildConfigPayload, type MessagingSchema } from "@/lib/messagingFields";

const SCHEMA: MessagingSchema = {
  app_platforms: [
    { platform: "feishu", label: "Feishu", fields: [
      { key: "app_id", label: "App ID", type: "text", required: true, secret: false },
      { key: "app_secret", label: "App Secret", type: "password", required: true, secret: true },
    ]},
  ],
  channel_types: [
    { type: "ses", label: "SES", fields: [
      { key: "sender", label: "Sender", type: "text", required: true, secret: false },
      { key: "recipients", label: "Recipients", type: "list", required: true, secret: false },
      { key: "region", label: "Region", type: "text", required: true, secret: false },
    ]},
  ],
};

describe("messagingFields", () => {
  it("channelFields / appFields look up by type/platform", () => {
    expect(channelFields(SCHEMA, "ses").map((f) => f.key)).toEqual(["sender", "recipients", "region"]);
    expect(appFields(SCHEMA, "feishu").map((f) => f.key)).toEqual(["app_id", "app_secret"]);
    expect(channelFields(SCHEMA, "nope")).toEqual([]);
    expect(channelFields(undefined, "ses")).toEqual([]);
  });

  it("missingRequired flags blank required fields", () => {
    const f = channelFields(SCHEMA, "ses");
    expect(missingRequired(f, { sender: "a@b.com" })).toEqual(["recipients", "region"]);
    expect(missingRequired(f, { sender: "a@b.com", recipients: "x", region: "us-east-1" })).toEqual([]);
  });

  it("buildConfigPayload splits list fields and casts numbers", () => {
    const f = channelFields(SCHEMA, "ses");
    const p = buildConfigPayload(f, { sender: "a@b.com", recipients: "x@y.com, z@w.com", region: "us-east-1" });
    expect(p.recipients).toEqual(["x@y.com", "z@w.com"]);
    expect(p.sender).toBe("a@b.com");
  });

  it("buildConfigPayload OMITS blank secret fields (keep-existing)", () => {
    const f = appFields(SCHEMA, "feishu");
    const p = buildConfigPayload(f, { app_id: "cli_x", app_secret: "" });
    expect(p.app_id).toBe("cli_x");
    expect("app_secret" in p).toBe(false); // omitted → backend keeps existing
  });
});
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx vitest --run src/__tests__/messagingFields.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 4: Type-check + commit (force-add lib)**

```bash
cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit
cd /Users/malibo/MyDev/AgenticOps
git add -f src/agenticops/web/frontend/src/lib/messagingFields.ts
git add src/agenticops/web/frontend/src/__tests__/messagingFields.test.ts
git commit --no-verify -m "feat(web): messagingFields — pure schema/field/payload helpers (tested)"
```

---

## Task 5: Frontend — `useMessaging.ts` hooks

**Files:**
- Create: `src/agenticops/web/frontend/src/hooks/useMessaging.ts`

- [ ] **Step 1: Write the hooks**

Create `src/agenticops/web/frontend/src/hooks/useMessaging.ts`:

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { MessagingSchema } from "@/lib/messagingFields";

export type AppsMap = Record<string, Record<string, Record<string, string>>>;

export interface ChannelInfo {
  name: string;
  type: string;
  enabled: boolean;
  role: string;
  severity_filter: string[];
  preferred_format: string;
  config: Record<string, unknown>;
}

export interface DeliveryLog {
  id: number;
  channel_name: string;
  subject: string;
  body: string;
  severity?: string | null;
  status: string;
  error?: string | null;
  sent_at: string;
}

export function useMessagingSchema() {
  return useQuery<MessagingSchema>({
    queryKey: ["messaging-schema"],
    queryFn: () => apiFetch("/messaging/schema"),
    staleTime: Infinity,
  });
}

export function useMessagingApps() {
  return useQuery<AppsMap>({ queryKey: ["messaging-apps"], queryFn: () => apiFetch("/messaging/apps") });
}

export function useUpsertApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ platform, name, config }: { platform: string; name: string; config: Record<string, unknown> }) =>
      apiFetch(`/messaging/apps/${platform}/${name}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-apps"] }),
  });
}

export function useDeleteApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ platform, name }: { platform: string; name: string }) =>
      apiFetch(`/messaging/apps/${platform}/${name}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-apps"] }),
  });
}

export function useMessagingChannels() {
  return useQuery<ChannelInfo[]>({ queryKey: ["messaging-channels"], queryFn: () => apiFetch("/messaging/channels") });
}

export function useUpsertChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, data }: { name: string; data: Record<string, unknown> }) =>
      apiFetch(`/messaging/channels/${name}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-channels"] }),
  });
}

export function useDeleteChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiFetch(`/messaging/channels/${name}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-channels"] }),
  });
}

export function useToggleChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      apiFetch(`/messaging/channels/${name}/toggle`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["messaging-channels"] }),
  });
}

export function useTestChannel() {
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch(`/messaging/channels/${name}/test`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: "Test from AgenticOps", body: "This is a test message.", severity: "low" }),
      }),
  });
}

export function useMessagingLogs(channelName?: string) {
  const qs = channelName ? `?channel_name=${encodeURIComponent(channelName)}` : "";
  return useQuery<DeliveryLog[]>({
    queryKey: ["messaging-logs", channelName ?? null],
    queryFn: () => apiFetch(`/messaging/logs${qs}`),
  });
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/hooks/useMessaging.ts
git commit --no-verify -m "feat(web): useMessaging hooks (apps/channels/logs/schema + mutations)"
```

---

## Task 6: Frontend — `ConfigureModal.tsx` (schema-driven)

**Files:**
- Create: `src/agenticops/web/frontend/src/components/settings/ConfigureModal.tsx`

- [ ] **Step 1: Write the modal**

Create `src/agenticops/web/frontend/src/components/settings/ConfigureModal.tsx`:

```typescript
import { useMemo, useState } from "react";
import { channelFields, appFields, missingRequired, buildConfigPayload, type MessagingSchema, type FieldDescriptor } from "@/lib/messagingFields";

interface Props {
  mode: "app" | "channel";
  schema: MessagingSchema | undefined;
  initialName?: string;
  initialType?: string;            // channel type OR app platform
  initialValues?: Record<string, string>;
  initialEnabled?: boolean;
  initialRole?: string;
  onClose: () => void;
  onSave: (args: { name: string; type: string; enabled: boolean; role: string; values: Record<string, string> }) => void;
  saving?: boolean;
}

const inputCls = "w-full px-3 py-2 border border-border rounded-lg text-sm bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary-500";

export function ConfigureModal({ mode, schema, initialName, initialType, initialValues, initialEnabled, initialRole, onClose, onSave, saving }: Props) {
  const isApp = mode === "app";
  const types = (isApp ? schema?.app_platforms : schema?.channel_types) ?? [];
  const [type, setType] = useState(initialType ?? (isApp ? "feishu" : "slack"));
  const [name, setName] = useState(initialName ?? (isApp ? "default" : ""));
  const [enabled, setEnabled] = useState(initialEnabled ?? true);
  const [role, setRole] = useState(initialRole ?? "alert");
  const [values, setValues] = useState<Record<string, string>>(initialValues ?? {});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [err, setErr] = useState<string[]>([]);

  const fields: FieldDescriptor[] = useMemo(
    () => (isApp ? appFields(schema, type) : channelFields(schema, type)),
    [isApp, schema, type],
  );

  const handleSave = () => {
    const missing = missingRequired(fields, values);
    if (!name.trim()) missing.unshift("name");
    if (missing.length) { setErr(missing); return; }
    onSave({ name: name.trim(), type, enabled, role, values });
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-card border border-border rounded-xl shadow-xl w-[380px] max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <h3 className="font-semibold text-foreground text-sm">{isApp ? "Configure Bot App" : "Configure Channel"}</h3>
          <button onClick={onClose} className="ml-auto text-muted-foreground hover:text-foreground">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="px-4 py-3 space-y-3">
          {/* Type tiles */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground">Type</label>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {types.map((tp) => {
                const key = (isApp ? tp.platform : tp.type) as string;
                const active = key === type;
                return (
                  <button key={key} onClick={() => setType(key)}
                    className={`px-2.5 py-1.5 rounded-lg text-xs border transition-colors ${active ? "border-primary-500 bg-primary-50 text-primary-700 font-semibold" : "border-border text-muted-foreground hover:bg-secondary"}`}>
                    {tp.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Name */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground">{isApp ? "App name" : "Channel name"} <span className="text-red-500">*</span></label>
            <input className={inputCls} value={name} disabled={!!initialName} onChange={(e) => setName(e.target.value)} placeholder={isApp ? "default" : "e.g. feishu-alert"} />
          </div>

          {/* Channel-only: role */}
          {!isApp && (
            <div>
              <label className="text-xs font-semibold text-muted-foreground">Role</label>
              <select className={inputCls} value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="alert">alert — 告警/报告投递</option>
                <option value="chat">chat — 双向对话</option>
              </select>
            </div>
          )}

          {/* Dynamic fields */}
          {fields.map((f) => (
            <div key={f.key}>
              <label className="text-xs font-semibold text-muted-foreground">{f.label} {f.required && <span className="text-red-500">*</span>}</label>
              <div className="relative">
                <input
                  className={`${inputCls} ${f.secret ? "pr-9 font-mono" : ""}`}
                  type={f.secret && !revealed[f.key] ? "password" : f.type === "number" ? "number" : "text"}
                  value={values[f.key] ?? ""}
                  placeholder={f.secret && initialName ? "•••• (leave blank to keep)" : ""}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
                {f.secret && (
                  <button type="button" onClick={() => setRevealed((r) => ({ ...r, [f.key]: !r[f.key] }))}
                    className="absolute right-2 top-2.5 text-muted-foreground hover:text-foreground">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></svg>
                  </button>
                )}
              </div>
              {f.secret && <p className="text-[10px] text-muted-foreground mt-0.5">Encrypted at rest</p>}
            </div>
          ))}

          {err.length > 0 && <p className="text-xs text-red-500">Required: {err.join(", ")}</p>}
        </div>

        <div className="flex items-center gap-2 px-4 py-3 border-t border-border">
          <span className="text-[11px] text-muted-foreground mr-auto">{buildConfigPayload(fields, values) && ""}{isApp ? "Inbound bot credentials" : "Outbound routing"}</span>
          <button onClick={onClose} className="px-3 py-1.5 text-sm border border-border rounded-lg text-foreground hover:bg-secondary">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="px-3 py-1.5 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-700 disabled:opacity-50">
            {saving ? "Saving…" : "Save & enable"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

NOTE: `buildConfigPayload` is imported here only to keep the lib import live; the actual payload build happens in `MessagingTab.onSave` (Task 7). If tsc flags it unused, remove it from the import and the `{buildConfigPayload(...) && ""}` placeholder. Report which.

- [ ] **Step 2: Type-check + commit**

```bash
cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/components/settings/ConfigureModal.tsx
git commit --no-verify -m "feat(web): ConfigureModal — schema-driven dynamic form (type tiles, secret mask)"
```

---

## Task 7: Frontend — `MessagingTab.tsx` + wire into Settings + delete old files

**Files:**
- Create: `src/agenticops/web/frontend/src/components/settings/MessagingTab.tsx`
- Modify: `src/agenticops/web/frontend/src/pages/Settings.tsx`
- Modify: `src/agenticops/web/frontend/src/locales/en.json`, `zh.json`
- Delete: `NotificationsTab.tsx`, `NotificationLogsTab.tsx`, `hooks/useImApps.ts`, `hooks/useNotifications.ts` (if unused)

- [ ] **Step 1: Write MessagingTab**

Create `src/agenticops/web/frontend/src/components/settings/MessagingTab.tsx`:

```typescript
import { useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ConfigureModal } from "./ConfigureModal";
import { buildConfigPayload, channelFields, appFields } from "@/lib/messagingFields";
import {
  useMessagingSchema, useMessagingApps, useMessagingChannels, useMessagingLogs,
  useUpsertApp, useDeleteApp, useUpsertChannel, useDeleteChannel, useToggleChannel, useTestChannel,
  type ChannelInfo,
} from "@/hooks/useMessaging";

const APP_PLATFORMS = ["feishu", "slack", "dingtalk", "wecom"] as const;

function StatusBadge({ on, label }: { on: boolean; label: string }) {
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-md font-semibold inline-flex items-center gap-1 ${on ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" : "bg-secondary text-muted-foreground"}`}>
      {on && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}{label}
    </span>
  );
}

function Switch({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <div onClick={onClick} className={`relative w-9 h-5 rounded-full cursor-pointer transition-colors ${on ? "bg-primary-600" : "bg-muted-foreground/30"}`}>
      <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
    </div>
  );
}

function IconBtn({ title, onClick, children }: { title: string; onClick: () => void; children: React.ReactNode }) {
  return <button title={title} onClick={onClick} className="w-7 h-7 rounded-lg border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-secondary flex items-center justify-center">{children}</button>;
}

const GearIcon = () => <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><circle cx="12" cy="12" r="3" /><path strokeLinecap="round" strokeLinejoin="round" d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-2.82 1.17V21a2 2 0 11-4 0v-.09A1.65 1.65 0 007.18 19.4l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 004.6 13.82 1.65 1.65 0 003 12.09V12a2 2 0 110-4h.09A1.65 1.65 0 004.6 6.18l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 3.6V3a2 2 0 114 0v.09a1.65 1.65 0 002.82 1.17l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0021 9.18V9a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 2z" /></svg>;
const BoltIcon = () => <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" /></svg>;

interface ModalState {
  mode: "app" | "channel";
  name?: string; type?: string; values?: Record<string, string>; enabled?: boolean; role?: string;
}

export function MessagingTab() {
  const schemaQ = useMessagingSchema();
  const appsQ = useMessagingApps();
  const channelsQ = useMessagingChannels();
  const logsQ = useMessagingLogs();
  const upsertApp = useUpsertApp();
  const deleteApp = useDeleteApp();
  const upsertChannel = useUpsertChannel();
  const deleteChannel = useDeleteChannel();
  const toggleChannel = useToggleChannel();
  const testChannel = useTestChannel();

  const [modal, setModal] = useState<ModalState | null>(null);
  const [restartHint, setRestartHint] = useState(false);

  const handleSave = (a: { name: string; type: string; enabled: boolean; role: string; values: Record<string, string> }) => {
    if (!modal) return;
    if (modal.mode === "app") {
      const fields = appFields(schemaQ.data, a.type);
      const config = buildConfigPayload(fields, a.values);
      upsertApp.mutate({ platform: a.type, name: a.name, config }, {
        onSuccess: () => { setModal(null); setRestartHint(true); },
      });
    } else {
      const fields = channelFields(schemaQ.data, a.type);
      const config = buildConfigPayload(fields, a.values);
      upsertChannel.mutate({ name: a.name, data: { type: a.type, enabled: a.enabled, role: a.role, config } }, {
        onSuccess: () => setModal(null),
      });
    }
  };

  return (
    <div className="space-y-5">
      {restartHint && (
        <div className="flex items-center gap-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 text-amber-800 dark:text-amber-300 rounded-lg px-3 py-2 text-xs">
          <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h16.9a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /></svg>
          Bot credentials saved — restart the service (<code className="font-mono">aiops service restart</code>) for the IM gateway to pick them up.
          <button onClick={() => setRestartHint(false)} className="ml-auto text-amber-600">Dismiss</button>
        </div>
      )}

      {/* BOT APPS */}
      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-foreground">Bot Apps</h2>
          <button onClick={() => setModal({ mode: "app" })} className="px-2.5 py-1 text-xs font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700">+ Connect Bot</button>
        </CardHeader>
        <CardBody>
          {appsQ.isLoading ? <Spinner /> : appsQ.error ? <ErrorBanner message="Failed to load apps" /> : (
            <div className="space-y-2">
              {APP_PLATFORMS.flatMap((platform) =>
                Object.entries(appsQ.data?.[platform] ?? {}).map(([name, cfg]) => (
                  <div key={`${platform}/${name}`} className="flex items-center gap-3 p-2.5 border border-border rounded-lg">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-foreground flex items-center gap-2">{platform}/{name} <StatusBadge on label="Configured" /></div>
                      <div className="text-[11px] text-muted-foreground truncate">{Object.entries(cfg).map(([k, v]) => `${k}=${v}`).join("  ·  ")}</div>
                    </div>
                    <IconBtn title="Configure" onClick={() => setModal({ mode: "app", name, type: platform, values: cfg as Record<string, string> })}><GearIcon /></IconBtn>
                    <button onClick={() => deleteApp.mutate({ platform, name })} className="text-xs text-red-600 hover:underline">Delete</button>
                  </div>
                ))
              )}
              {APP_PLATFORMS.every((p) => !Object.keys(appsQ.data?.[p] ?? {}).length) && <p className="text-sm text-muted-foreground">No bot apps configured.</p>}
            </div>
          )}
        </CardBody>
      </Card>

      {/* CHANNELS */}
      <Card>
        <CardHeader>
          <h2 className="text-base font-semibold text-foreground">Channels</h2>
          <button onClick={() => setModal({ mode: "channel" })} className="px-2.5 py-1 text-xs font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700">+ Add Channel</button>
        </CardHeader>
        <CardBody>
          {channelsQ.isLoading ? <Spinner /> : channelsQ.error ? <ErrorBanner message="Failed to load channels" /> : (
            <div className="space-y-2">
              {(channelsQ.data ?? []).map((ch: ChannelInfo) => (
                <div key={ch.name} className="flex items-center gap-3 p-2.5 border border-border rounded-lg">
                  <Switch on={ch.enabled} onClick={() => toggleChannel.mutate({ name: ch.name, enabled: !ch.enabled })} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground flex items-center gap-2">{ch.name} <StatusBadge on={ch.enabled} label={ch.enabled ? "Enabled" : "Disabled"} /></div>
                    <div className="text-[11px] text-muted-foreground">{ch.type} · role: {ch.role}</div>
                  </div>
                  <IconBtn title="Test" onClick={() => testChannel.mutate(ch.name)}><BoltIcon /></IconBtn>
                  <IconBtn title="Configure" onClick={() => setModal({ mode: "channel", name: ch.name, type: ch.type, enabled: ch.enabled, role: ch.role, values: ch.config as Record<string, string> })}><GearIcon /></IconBtn>
                  <button onClick={() => deleteChannel.mutate(ch.name)} className="text-xs text-red-600 hover:underline">Delete</button>
                </div>
              ))}
              {!(channelsQ.data ?? []).length && <p className="text-sm text-muted-foreground">No channels configured.</p>}
            </div>
          )}
        </CardBody>
      </Card>

      {/* DELIVERY LOGS */}
      <Card>
        <CardHeader><h2 className="text-base font-semibold text-foreground">Delivery Logs</h2></CardHeader>
        <CardBody>
          {logsQ.isLoading ? <Spinner /> : (
            <div className="space-y-1.5">
              {(logsQ.data ?? []).slice(0, 20).map((log) => (
                <div key={log.id} className="flex items-center gap-2 text-xs p-2 border border-border rounded-lg">
                  <span className={`px-1.5 py-0.5 rounded font-semibold ${log.status === "sent" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>{log.status}</span>
                  <span className="font-medium text-foreground">{log.channel_name}</span>
                  <span className="text-muted-foreground truncate flex-1">{log.subject}</span>
                  <span className="text-muted-foreground/60">{new Date(log.sent_at).toLocaleString()}</span>
                </div>
              ))}
              {!(logsQ.data ?? []).length && <p className="text-sm text-muted-foreground">No delivery logs yet.</p>}
            </div>
          )}
        </CardBody>
      </Card>

      {modal && (
        <ConfigureModal
          mode={modal.mode}
          schema={schemaQ.data}
          initialName={modal.name}
          initialType={modal.type}
          initialValues={modal.values}
          initialEnabled={modal.enabled}
          initialRole={modal.role}
          saving={upsertApp.isPending || upsertChannel.isPending}
          onClose={() => setModal(null)}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
```

NOTE (verified): `Card`, `CardHeader`, `CardBody` ARE all exported from `@/components/ui/Card` — the imports above are correct as written.

- [ ] **Step 2: Wire into Settings.tsx — replace two tabs with one**

In `src/agenticops/web/frontend/src/pages/Settings.tsx`:

(a) Replace the import (lines 13-14):
```typescript
import { NotificationsTab } from "@/components/settings/NotificationsTab";
import { NotificationLogsTab } from "@/components/settings/NotificationLogsTab";
```
with:
```typescript
import { MessagingTab } from "@/components/settings/MessagingTab";
```

(b) Remove the `useImApps`-block import (lines 40-47, the `import { useImApps, useUpsertImApp, useDeleteImApp, useChannels, useUpsertChannel, useDeleteChannel, useToggleChannel } from "@/hooks/useImApps";`). Delete the whole inline `ImBotsTab` function (the `function ImBotsTab() {...}` block starting ~line 1079 and its `IM_PLATFORMS`/`IM_FIELDS` consts above it ~line 1069) — and any other helper used ONLY by ImBotsTab.

(c) Replace the two `Tabs.Trigger` lines:
```typescript
          <Tabs.Trigger value="notifications" className={tabTriggerClass}>{t("settings.notifications")}</Tabs.Trigger>
```
... and ...
```typescript
          <Tabs.Trigger value="im-bots" className={tabTriggerClass}>IM Bots</Tabs.Trigger>
```
with a single trigger (place where `notifications` was):
```typescript
          <Tabs.Trigger value="messaging" className={tabTriggerClass}>{t("settings.messaging")}</Tabs.Trigger>
```

(d) Replace the two `Tabs.Content` blocks:
```typescript
        <Tabs.Content value="notifications" className="space-y-6">
          <NotificationsTab />
          <NotificationLogsTab />
        </Tabs.Content>
```
... and ...
```typescript
        <Tabs.Content value="im-bots" className="space-y-6">
          <ImBotsTab />
        </Tabs.Content>
```
with a single block (where `notifications` was):
```typescript
        <Tabs.Content value="messaging" className="space-y-6">
          <MessagingTab />
        </Tabs.Content>
```

- [ ] **Step 3: Add i18n key**

In `src/agenticops/web/frontend/src/locales/en.json`, add after the `"settings.notifications"` line:
```json
  "settings.messaging": "Messaging",
```
In `zh.json`, add:
```json
  "settings.messaging": "消息",
```

- [ ] **Step 4: Delete dead files (after confirming no other importers)**

```bash
cd /Users/malibo/MyDev/AgenticOps
# Confirm nothing else imports them:
grep -rn "NotificationsTab\|NotificationLogsTab" src/agenticops/web/frontend/src --include=*.tsx | grep -v "MessagingTab\|Settings.tsx" || echo "no other importers"
grep -rn "useImApps\|from \"@/hooks/useNotifications\"" src/agenticops/web/frontend/src --include=*.tsx --include=*.ts | grep -v "MessagingTab\|useMessaging" || echo "no other importers"
# Delete:
git rm src/agenticops/web/frontend/src/components/settings/NotificationsTab.tsx
git rm src/agenticops/web/frontend/src/components/settings/NotificationLogsTab.tsx
git rm src/agenticops/web/frontend/src/hooks/useImApps.ts
# useNotifications.ts: VERIFIED no other importers (only NotificationsTab/LogsTab use it) → safe to delete:
git rm src/agenticops/web/frontend/src/hooks/useNotifications.ts
```
(Pre-verified: no standalone Notifications page, no other importer of `useNotifications`. Still re-run the grep to be safe; if a new importer appeared, leave it and report.)

- [ ] **Step 5: Type-check + build**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: PASS. Fix any dangling reference the deletions surfaced (e.g. a type imported from a deleted file). If `NotificationChannel*` types in `api/types.ts` are now unused, leave them (harmless) — don't chase unrelated cleanup.

- [ ] **Step 6: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/components/settings/MessagingTab.tsx \
        src/agenticops/web/frontend/src/pages/Settings.tsx \
        src/agenticops/web/frontend/src/locales/en.json src/agenticops/web/frontend/src/locales/zh.json
git commit --no-verify -m "feat(web): unified Messaging tab; remove Notifications + IM Bots tabs + dead hooks"
```

---

## Task 8: Full verification + Playwright smoke (light + dark) + docs

**Files:**
- Modify: `docs/WORKFLOW.md`, `CLAUDE.md`

- [ ] **Step 1: Full automated gate**

```bash
cd /Users/malibo/MyDev/AgenticOps
.venv/bin/python -m pytest tests/test_messaging_api.py tests/test_chat_api.py -q
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build && npm run test
```
Expected: backend green; tsc clean; build OK; vitest green (messagingFields + prior suites).

- [ ] **Step 2: Launch server + Playwright smoke (light + dark)**

```bash
cd /Users/malibo/MyDev/AgenticOps
lsof -ti:8013 2>/dev/null | xargs kill 2>/dev/null
.venv/bin/python -m uvicorn agenticops.web.app:app --host 127.0.0.1 --port 8013 > /tmp/aiops-msg-smoke.log 2>&1 &
sleep 6
```
Then drive `http://127.0.0.1:8013/app/settings` (set `localStorage.aiops_token="smoke"` via the login-page origin first, as in prior smokes). Verify + screenshot in BOTH themes:
- Settings has ONE **Messaging** tab (no "Notifications" / "IM Bots").
- 3 sections render (Bot Apps / Channels / Delivery Logs) with stroke-SVG icons (no emoji).
- Click "+ Add Channel" → modal: type tiles switch fields; pick "Email (AWS SES)" → sender/recipients/region appear; secret field shows mask + eye.
- Toggle a channel; click Test on a channel (may fail to send if creds absent — that's fine, just verify it calls the endpoint + a log row could appear).
- Dark mode legible.
- Console 0 errors (favicon 404 ok).
Then: `lsof -ti:8013 | xargs kill`. Record results.

- [ ] **Step 3: Update docs**

In `docs/WORKFLOW.md`, near the notification section, add a note:
```markdown
**Messaging settings (v1.1.x):** the Settings → Messaging tab unifies the former Notifications
+ IM Bots tabs into one page (Bot Apps / Channels / Delivery Logs), backed by `/api/messaging/*`
(a facade over `channels.yaml` + `im-apps.yaml` + NotificationLog). Configure uses a
schema-driven form (`/api/messaging/schema`) with masked secrets. Bot App = inbound bot
credentials; Channel = outbound routing (alert/chat). Old `/api/notifications/*` +
`/api/settings/{channels,im-apps}` endpoints remain but are deprecated.
```

In `CLAUDE.md`, update the `web/` row or notify note to mention the unified Messaging tab + `/api/messaging`. Confirm the note that `config/channels.yaml` + `config/im-apps.yaml` remain source of truth.

- [ ] **Step 4: Commit docs**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add docs/WORKFLOW.md CLAUDE.md
git commit --no-verify -m "docs: document unified Messaging settings + /api/messaging facade"
```

---

## Self-Review Notes (author)

- **Spec coverage:** schema descriptor (T1), apps facade w/ secret-keep merge (T2), channels facade + toggle + test + logs (T3), pure field/payload helper (T4), hooks (T5), schema-driven modal w/ type tiles + mask + Save&enable (T6), MessagingTab 3-section card UX + Settings tab swap + delete old tabs/hooks + i18n (T7), verification + light/dark smoke + docs (T8). Old endpoints deprecated not removed (T3). email/ses as channel types (T1 schema). Restart note informational only (T7). All spec sections map to a task.
- **Type consistency:** `MessagingSchema`/`FieldDescriptor`/`TypeDescriptor` defined in `messagingFields.ts` (T4), imported by hooks (T5) + modal (T6) + tab (T7). `ChannelInfo` shape (name/type/enabled/role/severity_filter/config) matches the T3 GET response. `buildConfigPayload`/`channelFields`/`appFields`/`missingRequired` names consistent T4↔T6↔T7. Endpoint paths `/messaging/{schema,apps,channels,logs}` consistent backend (T1-3) ↔ hooks (T5). Secret-keep contract: backend omit-blank-secret (T2/T3) ↔ frontend buildConfigPayload omits blank secrets (T4).
- **No placeholders.** New deps: none. The one risk flagged for impl: `CardBody` export name (T7 NOTE) + possibly-unused `buildConfigPayload` import in modal (T6 NOTE) — both have explicit fallback instructions.
- **Deletions gated** on a grep confirming no other importers (T7 Step 4) — won't blindly delete `useNotifications.ts` if something else uses it.
