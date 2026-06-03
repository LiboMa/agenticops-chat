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
