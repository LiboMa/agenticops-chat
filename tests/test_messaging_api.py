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
