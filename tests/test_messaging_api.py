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
