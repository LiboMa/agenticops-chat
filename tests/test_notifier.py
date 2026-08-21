"""Tests for agenticops.notify.notifier module.

Covers: NotificationManager, SlackNotifier, EmailNotifier, SNSNotifier,
WebhookNotifier, and IM notifiers init/send logic.
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
