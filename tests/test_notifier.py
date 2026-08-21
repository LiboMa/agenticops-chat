"""Tests for agenticops.notify.notifier module.

Covers: NotificationManager, SlackNotifier, EmailNotifier, SNSNotifier,
WebhookNotifier, and IM notifiers (Feishu, DingTalk, WeCom, SlackIM).
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
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
    WeComNotifier,
    WebhookNotifier,
)


# ============================================================================
# SlackNotifier
# ============================================================================


class TestSlackNotifier:
    def test_init_defaults(self):
        notifier = SlackNotifier({"webhook_url": "https://hooks.slack.com/test"})
        assert notifier.webhook_url == "https://hooks.slack.com/test"
        assert notifier.channel == "#alerts"
        assert notifier.username == "AgenticAIOps"
        assert notifier.icon_emoji == ":robot_face:"

    def test_init_custom(self):
        cfg = {
            "webhook_url": "https://hooks.slack.com/custom",
            "channel": "#ops",
            "username": "Bot",
            "icon_emoji": ":wave:",
        }
        notifier = SlackNotifier(cfg)
        assert notifier.channel == "#ops"
        assert notifier.username == "Bot"

    @pytest.mark.asyncio
    async def test_send_no_webhook_url(self):
        notifier = SlackNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        notifier = SlackNotifier({"webhook_url": "https://hooks.slack.com/x"})
        mock_resp = MagicMock(status_code=200)
        with patch("agenticops.notify.notifier.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await notifier.send("Alert", "Something happened", severity="critical")
        assert result is True
        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args[1]["json"]
        assert payload["attachments"][0]["color"] == "#FF0000"

    @pytest.mark.asyncio
    async def test_send_failure_status(self):
        notifier = SlackNotifier({"webhook_url": "https://hooks.slack.com/x"})
        mock_resp = MagicMock(status_code=500)
        with patch("agenticops.notify.notifier.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await notifier.send("Alert", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_exception(self):
        notifier = SlackNotifier({"webhook_url": "https://hooks.slack.com/x"})
        with patch("agenticops.notify.notifier.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await notifier.send("Alert", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_severity_colors(self):
        """Verify severity→color mapping in Slack payload."""
        notifier = SlackNotifier({"webhook_url": "https://hooks.slack.com/x"})
        mock_resp = MagicMock(status_code=200)
        with patch("agenticops.notify.notifier.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            await notifier.send("Alert", "body", severity="medium")
        payload = mock_client.post.call_args[1]["json"]
        assert payload["attachments"][0]["color"] == "#FFCC00"


# ============================================================================
# WebhookNotifier
# ============================================================================


class TestWebhookNotifier:
    def test_init(self):
        notifier = WebhookNotifier({"url": "https://example.com/hook"})
        assert notifier.config["url"] == "https://example.com/hook"

    @pytest.mark.asyncio
    async def test_send_no_url(self):
        notifier = WebhookNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_post_success(self):
        notifier = WebhookNotifier({
            "url": "https://example.com/webhook",
            "method": "POST",
            "headers": {"X-Token": "abc"},
        })
        mock_resp = MagicMock(status_code=200)
        with patch("agenticops.notify.notifier.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await notifier.send("Alert", "body", "low")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_custom_template(self):
        config = {
            "url": "https://example.com/hook",
            "template": '{"title": "{{subject}}", "msg": "{{body}}", "level": "{{severity}}"}',
        }
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock(status_code=201)
        with patch("agenticops.notify.notifier.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await notifier.send("Hi", "World", "medium")
        assert result is True
        payload = mock_client.post.call_args[1]["json"]
        assert payload["title"] == "Hi"
        assert payload["msg"] == "World"

    @pytest.mark.asyncio
    async def test_send_get_method(self):
        config = {"url": "https://example.com/hook", "method": "GET"}
        notifier = WebhookNotifier(config)
        mock_resp = MagicMock(status_code=200)
        with patch("agenticops.notify.notifier.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await notifier.send("Alert", "body")
        assert result is True


# ============================================================================
# EmailNotifier
# ============================================================================


class TestEmailNotifier:
    def test_init(self):
        cfg = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "from_email": "ops@example.com",
            "to_emails": ["team@example.com"],
        }
        notifier = EmailNotifier(cfg)
        assert notifier.config["smtp_host"] == "smtp.example.com"

    @pytest.mark.asyncio
    async def test_send_no_smtp_host(self):
        notifier = EmailNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        cfg = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "username": "user@example.com",
            "password": "secret",
            "from_addr": "ops@example.com",
            "to_addrs": ["admin@example.com"],
            "use_tls": True,
        }
        notifier = EmailNotifier(cfg)
        with patch.object(notifier, "_send_email") as mock_send:
            result = await notifier.send("Alert", "body", "critical")
        assert result is True
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_no_recipients(self):
        notifier = EmailNotifier({"smtp_host": "smtp.example.com", "to_addrs": []})
        result = await notifier.send("Alert", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_exception(self):
        cfg = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "from_addr": "ops@example.com",
            "to_addrs": ["admin@example.com"],
        }
        notifier = EmailNotifier(cfg)
        with patch.object(notifier, "_send_email", side_effect=Exception("SMTP fail")):
            result = await notifier.send("Alert", "body")
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
# SNSNotifier
# ============================================================================


class TestSNSNotifier:
    def test_init(self):
        cfg = {"topic_arn": "arn:aws:sns:us-east-1:123456:my-topic", "region": "us-east-1"}
        notifier = SNSNotifier(cfg)
        assert notifier.config["topic_arn"] == "arn:aws:sns:us-east-1:123456:my-topic"

    @pytest.mark.asyncio
    async def test_send_no_topic_arn(self):
        notifier = SNSNotifier({})
        result = await notifier.send("Test", "body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        cfg = {
            "topic_arn": "arn:aws:sns:us-east-1:123456789:alerts",
            "region": "us-east-1",
        }
        notifier = SNSNotifier(cfg)
        with patch.object(notifier, "_publish_sns") as mock_pub:
            result = await notifier.send("Alert", "body", "critical")
        assert result is True
        mock_pub.assert_called_once()


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
# NotificationManager
# ============================================================================


class TestNotificationManager:
    def test_init(self):
        mgr = NotificationManager()
        assert mgr._notifiers == {}

    def test_notifier_classes_map(self):
        mgr = NotificationManager()
        assert "slack" in mgr.NOTIFIER_CLASSES
        assert "email" in mgr.NOTIFIER_CLASSES
        assert "webhook" in mgr.NOTIFIER_CLASSES
        assert "feishu" in mgr.NOTIFIER_CLASSES
        assert "dingtalk" in mgr.NOTIFIER_CLASSES
        assert "wecom" in mgr.NOTIFIER_CLASSES
        assert "sns" in mgr.NOTIFIER_CLASSES
        assert "ses" in mgr.NOTIFIER_CLASSES

    def test_get_notifier_creates_and_caches(self):
        mgr = NotificationManager()
        cfg = {"webhook_url": "https://hooks.slack.com/x"}
        n1 = mgr._get_notifier("slack-main", "slack", cfg)
        n2 = mgr._get_notifier("slack-main", "slack", cfg)
        assert n1 is n2
        assert isinstance(n1, SlackNotifier)

    def test_get_notifier_unknown_type(self):
        mgr = NotificationManager()
        result = mgr._get_notifier("unknown-ch", "carrier_pigeon", {})
        assert result is None

    def test_get_notifier_slack_im_auto_select(self):
        mgr = NotificationManager()
        cfg = {"chat_id": "C12345", "bot_token": "xoxb-xxx"}
        n = mgr._get_notifier("slack-im", "slack", cfg)
        assert isinstance(n, SlackIMNotifier)

    def test_get_notifier_slack_webhook_selection(self):
        """When config has webhook_url, uses SlackNotifier."""
        mgr = NotificationManager()
        cfg = {"webhook_url": "https://hooks.slack.com/services/T/B/X"}
        n = mgr._get_notifier("slack-wh", "slack", cfg)
        assert isinstance(n, SlackNotifier)

    def test_invalidate_cache_specific(self):
        mgr = NotificationManager()
        cfg = {"webhook_url": "https://hooks.slack.com/x"}
        mgr._get_notifier("slack-main", "slack", cfg)
        assert "slack-main" in mgr._notifiers
        mgr.invalidate_cache("slack-main")
        assert "slack-main" not in mgr._notifiers

    def test_invalidate_cache_all(self):
        mgr = NotificationManager()
        mgr._get_notifier("ch1", "slack", {"webhook_url": "https://a"})
        mgr._get_notifier("ch2", "webhook", {"url": "https://b"})
        assert len(mgr._notifiers) == 2
        mgr.invalidate_cache()
        assert len(mgr._notifiers) == 0

    @pytest.mark.asyncio
    async def test_send_notification_filters_channels(self):
        """send_notification loads channels from YAML and filters by name."""
        mgr = NotificationManager()

        fake_channel = SimpleNamespace(
            name="test-slack",
            channel_type="slack",
            is_enabled=True,
            severity_filter=None,
            config={"webhook_url": "https://hooks.slack.com/test"},
        )

        with patch("agenticops.notify.im_config.load_channels", return_value=[fake_channel]):
            with patch.object(SlackNotifier, "send", new_callable=AsyncMock, return_value=True):
                with patch.object(mgr, "_log_notification"):
                    results = await mgr.send_notification(
                        subject="Test",
                        body="Hello",
                        channel_names=["test-slack"],
                    )
        assert results == {"test-slack": True}

    @pytest.mark.asyncio
    async def test_send_notification_severity_filter(self):
        """Channels with severity_filter skip non-matching severities."""
        mgr = NotificationManager()

        fake_channel = SimpleNamespace(
            name="critical-only",
            channel_type="slack",
            is_enabled=True,
            severity_filter=["critical"],
            config={"webhook_url": "https://hooks.slack.com/test"},
        )

        with patch("agenticops.notify.im_config.load_channels", return_value=[fake_channel]):
            with patch.object(mgr, "_log_notification"):
                results = await mgr.send_notification(
                    subject="Test",
                    body="Hello",
                    severity="low",
                    channel_names=["critical-only"],
                )
        # Channel should be skipped due to severity filter
        assert results == {}

    @pytest.mark.asyncio
    async def test_send_anomaly_notification(self):
        """send_anomaly_notification formats anomaly and delegates."""
        mgr = NotificationManager()

        anomaly = SimpleNamespace(
            severity="high",
            title="CPU Spike",
            description="CPU utilization exceeds 95%",
            resource_type="ec2",
            resource_id="i-abc123",
            region="us-east-1",
            detected_at=datetime(2026, 8, 21, 3, 30, tzinfo=timezone.utc),
            metric_name="CPUUtilization",
            expected_value="40%",
            actual_value="97%",
        )

        with patch.object(mgr, "send_notification", new_callable=AsyncMock, return_value={"slack": True}) as mock_send:
            result = await mgr.send_anomaly_notification(anomaly)

        assert result == {"slack": True}
        call_kwargs = mock_send.call_args[1]
        assert "[HIGH]" in call_kwargs["subject"]
        assert "CPU Spike" in call_kwargs["subject"]
        assert "97%" in call_kwargs["body"]

    @pytest.mark.asyncio
    async def test_test_channel_not_found(self):
        with patch("agenticops.notify.im_config.get_channel", return_value=None):
            with pytest.raises(ValueError, match="not found"):
                await NotificationManager.test_channel("nonexistent")


# ============================================================================
# IM Notifiers basic init
# ============================================================================


class TestIMNotifiers:
    def test_feishu_init(self):
        cfg = {"webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"}
        n = FeishuNotifier(cfg)
        assert n.config["webhook_url"].startswith("https://open.feishu.cn")

    def test_dingtalk_init(self):
        cfg = {"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=xxx"}
        n = DingTalkNotifier(cfg)
        assert "dingtalk" in n.config["webhook_url"]

    def test_wecom_init(self):
        cfg = {"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"}
        n = WeComNotifier(cfg)
        assert "weixin" in n.config["webhook_url"]
