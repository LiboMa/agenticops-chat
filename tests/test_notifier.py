"""Unit tests for agenticops.notify.notifier module.

Covers: SlackNotifier, EmailNotifier, WebhookNotifier, NotificationManager,
        FeishuNotifier, DingTalkNotifier, WeComNotifier, SlackIMNotifier,
        SNSNotifier, SESNotifier, SNSReportNotifier.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticops.notify.notifier import (
    DingTalkNotifier,
    EmailNotifier,
    FeishuNotifier,
    NotificationManager,
    SlackIMNotifier,
    SlackNotifier,
    SNSNotifier,
    SNSReportNotifier,
    SESNotifier,
    WeComNotifier,
    WebhookNotifier,
)


# ============================================================================
# SlackNotifier
# ============================================================================


class TestSlackNotifier:
    def setup_method(self):
        self.config = {
            "webhook_url": "https://hooks.slack.com/services/T/B/X",
            "channel": "#alerts",
            "username": "TestBot",
            "icon_emoji": ":robot:",
        }
        self.notifier = SlackNotifier(self.config)

    @pytest.mark.asyncio
    async def test_send_success(self):
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await self.notifier.send("Test Alert", "Something happened", "critical")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_failure_status(self):
        mock_resp = MagicMock(status_code=500)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await self.notifier.send("Test", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_no_webhook(self):
        notifier = SlackNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_exception(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=Exception("timeout")):
            result = await self.notifier.send("Test", "body", "high")
        assert result is False

    @pytest.mark.asyncio
    async def test_severity_colors(self):
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await self.notifier.send("Alert", "body", "medium")
            payload = mock_post.call_args.kwargs["json"]
            assert payload["attachments"][0]["color"] == "#FFCC00"


# ============================================================================
# EmailNotifier
# ============================================================================


class TestEmailNotifier:
    def setup_method(self):
        self.config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "username": "user@example.com",
            "password": "secret",
            "from_addr": "ops@example.com",
            "to_addrs": ["admin@example.com"],
            "use_tls": True,
        }
        self.notifier = EmailNotifier(self.config)

    @pytest.mark.asyncio
    async def test_send_success(self):
        with patch.object(self.notifier, "_send_email") as mock_send:
            result = await self.notifier.send("Alert", "body", "critical")
        assert result is True
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_no_recipients(self):
        notifier = EmailNotifier({"to_addrs": []})
        result = await notifier.send("Alert", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_exception(self):
        with patch.object(self.notifier, "_send_email", side_effect=Exception("SMTP fail")):
            result = await self.notifier.send("Alert", "body")
        assert result is False

    def test_legacy_config_keys(self):
        """Accepts legacy config keys (smtp_user, from_email, to_emails)."""
        config = {
            "smtp_user": "legacy@example.com",
            "smtp_password": "pw",
            "from_email": "legacy-from@example.com",
            "to_emails": ["dest@example.com"],
        }
        notifier = EmailNotifier(config)
        assert notifier.smtp_user == "legacy@example.com"
        assert notifier.from_email == "legacy-from@example.com"
        assert notifier.to_emails == ["dest@example.com"]


# ============================================================================
# WebhookNotifier
# ============================================================================


class TestWebhookNotifier:
    def setup_method(self):
        self.config = {
            "url": "https://example.com/webhook",
            "method": "POST",
            "headers": {"X-Token": "abc"},
        }
        self.notifier = WebhookNotifier(self.config)

    @pytest.mark.asyncio
    async def test_send_post_success(self):
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await self.notifier.send("Alert", "body", "low")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_no_url(self):
        notifier = WebhookNotifier({})
        result = await notifier.send("Alert", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_custom_template(self):
        config = {
            "url": "https://example.com/hook",
            "template": '{"title": "{{subject}}", "msg": "{{body}}", "level": "{{severity}}"}',
        }
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock(status_code=201)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            result = await notifier.send("Hi", "World", "medium")
        assert result is True
        payload = mock_post.call_args.kwargs["json"]
        assert payload["title"] == "Hi"
        assert payload["msg"] == "World"

    @pytest.mark.asyncio
    async def test_send_get_method(self):
        config = {"url": "https://example.com/hook", "method": "GET"}
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            result = await notifier.send("Alert", "body")
        assert result is True


# ============================================================================
# FeishuNotifier
# ============================================================================


class TestFeishuNotifier:
    def setup_method(self):
        self.config = {
            "app_id": "cli_xxx",
            "app_secret": "secret",
            "chat_id": "oc_xxx",
        }
        self.notifier = FeishuNotifier(self.config)

    @pytest.mark.asyncio
    async def test_send_success(self):
        token_resp = MagicMock()
        token_resp.json.return_value = {"code": 0, "tenant_access_token": "t-xxx", "expire": 7200}
        send_resp = MagicMock()
        send_resp.json.return_value = {"code": 0}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[token_resp, send_resp]):
            result = await self.notifier.send("Feishu Alert", "body", "critical")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_no_config(self):
        notifier = FeishuNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        token_resp = MagicMock()
        token_resp.json.return_value = {"code": 0, "tenant_access_token": "t-xxx", "expire": 7200}
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=token_resp):
            result = await self.notifier.test_connection()
        assert result is True


# ============================================================================
# DingTalkNotifier
# ============================================================================


class TestDingTalkNotifier:
    def setup_method(self):
        self.config = {
            "app_key": "dingxxx",
            "app_secret": "secret",
            "chat_id": "cidxxx",
        }
        self.notifier = DingTalkNotifier(self.config)

    @pytest.mark.asyncio
    async def test_send_success(self):
        token_resp = MagicMock()
        token_resp.json.return_value = {"accessToken": "at-xxx", "expireIn": 7200}
        send_resp = MagicMock()
        send_resp.json.return_value = {"processQueryKey": "pqk-123"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[token_resp, send_resp]):
            result = await self.notifier.send("DingTalk Alert", "body", "high")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_no_config(self):
        notifier = DingTalkNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False


# ============================================================================
# WeComNotifier
# ============================================================================


class TestWeComNotifier:
    def setup_method(self):
        self.config = {
            "corp_id": "ww_xxx",
            "corp_secret": "secret",
            "agent_id": 1000001,
            "touser": "@all",
        }
        self.notifier = WeComNotifier(self.config)

    @pytest.mark.asyncio
    async def test_send_success_user_mode(self):
        token_resp = MagicMock()
        token_resp.json.return_value = {"errcode": 0, "access_token": "ak-xxx", "expires_in": 7200}
        send_resp = MagicMock()
        send_resp.json.return_value = {"errcode": 0}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=token_resp):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=send_resp):
                result = await self.notifier.send("WeCom Alert", "body", "medium")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_no_config(self):
        notifier = WeComNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False


# ============================================================================
# SlackIMNotifier
# ============================================================================


class TestSlackIMNotifier:
    def setup_method(self):
        self.config = {
            "bot_token": "xoxb-xxx",
            "chat_id": "C12345",
        }
        self.notifier = SlackIMNotifier(self.config)

    @pytest.mark.asyncio
    async def test_send_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await self.notifier.send("Subject", "Body text", "low")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_failure(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_resp.text = "error"
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await self.notifier.send("Subject", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_no_config(self):
        notifier = SlackIMNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_test_connection(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await self.notifier.test_connection()
        assert result is True


# ============================================================================
# SNSNotifier
# ============================================================================


class TestSNSNotifier:
    def setup_method(self):
        self.config = {
            "topic_arn": "arn:aws:sns:us-east-1:123456789:alerts",
            "region": "us-east-1",
        }
        self.notifier = SNSNotifier(self.config)

    @pytest.mark.asyncio
    async def test_send_no_topic(self):
        notifier = SNSNotifier({})
        result = await notifier.send("Alert", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        with patch.object(self.notifier, "_publish_sns") as mock_pub:
            result = await self.notifier.send("Alert", "body", "critical")
        assert result is True
        mock_pub.assert_called_once()


# ============================================================================
# NotificationManager
# ============================================================================


class TestNotificationManager:
    def setup_method(self):
        self.manager = NotificationManager()

    def test_notifier_classes_registered(self):
        assert "slack" in NotificationManager.NOTIFIER_CLASSES
        assert "email" in NotificationManager.NOTIFIER_CLASSES
        assert "feishu" in NotificationManager.NOTIFIER_CLASSES
        assert "dingtalk" in NotificationManager.NOTIFIER_CLASSES
        assert "wecom" in NotificationManager.NOTIFIER_CLASSES
        assert "webhook" in NotificationManager.NOTIFIER_CLASSES
        assert "sns" in NotificationManager.NOTIFIER_CLASSES
        assert "ses" in NotificationManager.NOTIFIER_CLASSES
        assert "sns-report" in NotificationManager.NOTIFIER_CLASSES

    def test_get_notifier_unknown_type(self):
        result = self.manager._get_notifier("test", "unknown_type", {})
        assert result is None

    def test_get_notifier_caches(self):
        config = {"webhook_url": "https://hooks.slack.com/test"}
        n1 = self.manager._get_notifier("my-slack", "slack", config)
        n2 = self.manager._get_notifier("my-slack", "slack", config)
        assert n1 is n2

    def test_invalidate_cache_single(self):
        config = {"webhook_url": "https://hooks.slack.com/test"}
        self.manager._get_notifier("my-slack", "slack", config)
        self.manager.invalidate_cache("my-slack")
        assert "my-slack" not in self.manager._notifiers

    def test_invalidate_cache_all(self):
        self.manager._get_notifier("a", "webhook", {"url": "http://a"})
        self.manager._get_notifier("b", "webhook", {"url": "http://b"})
        self.manager.invalidate_cache()
        assert len(self.manager._notifiers) == 0

    def test_slack_im_auto_selection(self):
        """When config has chat_id but no webhook_url, auto-selects SlackIMNotifier."""
        config = {"chat_id": "C12345", "bot_token": "xoxb-xxx"}
        notifier = self.manager._get_notifier("slack-im", "slack", config)
        assert isinstance(notifier, SlackIMNotifier)

    def test_slack_webhook_selection(self):
        """When config has webhook_url, uses SlackNotifier."""
        config = {"webhook_url": "https://hooks.slack.com/services/T/B/X"}
        notifier = self.manager._get_notifier("slack-wh", "slack", config)
        assert isinstance(notifier, SlackNotifier)
