"""Tests for notify/notifier.py — SlackNotifier, EmailNotifier, SNSNotifier, NotificationOperator."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, ANY

import pytest

from agenticops.notify.notifier import (
    SlackNotifier,
    EmailNotifier,
    SNSNotifier,
    NotificationLog,
    Notifier,
)


# ============================================================================
# SlackNotifier Tests
# ============================================================================


class TestSlackNotifier:
    """Tests for SlackNotifier."""

    def _make(self, **overrides):
        config = {
            "webhook_url": "https://hooks.slack.com/services/T00/B00/XXX",
            "channel": "#alerts",
            "username": "TestBot",
            "icon_emoji": ":robot_face:",
        }
        config.update(overrides)
        return SlackNotifier(config)

    def test_init(self):
        n = self._make()
        assert n.webhook_url == "https://hooks.slack.com/services/T00/B00/XXX"
        assert n.channel == "#alerts"
        assert n.username == "TestBot"
        assert n.icon_emoji == ":robot_face:"

    def test_init_defaults(self):
        n = SlackNotifier({"webhook_url": "https://x"})
        assert n.channel == "#alerts"
        assert n.username == "AgenticAIOps"

    @pytest.mark.asyncio
    async def test_send_no_webhook(self):
        n = SlackNotifier({})
        result = await n.send("Test", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        n = self._make()
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await n.send("Alert", "Something happened", severity="critical")

        assert result is True
        instance.post.assert_called_once()
        call_kwargs = instance.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["attachments"][0]["color"] == "#FF0000"
        assert payload["attachments"][0]["title"] == "Alert"

    @pytest.mark.asyncio
    async def test_send_with_severity_field(self):
        n = self._make()
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            await n.send("Alert", "body", severity="high")

        payload = instance.post.call_args.kwargs.get("json") or instance.post.call_args[1].get("json")
        fields = payload["attachments"][0]["fields"]
        assert fields[0]["title"] == "Severity"
        assert fields[0]["value"] == "HIGH"

    @pytest.mark.asyncio
    async def test_send_no_severity(self):
        n = self._make()
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            await n.send("Alert", "body")

        payload = instance.post.call_args.kwargs.get("json") or instance.post.call_args[1].get("json")
        assert "fields" not in payload["attachments"][0]

    @pytest.mark.asyncio
    async def test_send_failure_status(self):
        n = self._make()
        mock_resp = MagicMock(status_code=500)
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await n.send("Alert", "body")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_exception(self):
        n = self._make()
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=Exception("network error"))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await n.send("Alert", "body")

        assert result is False

    @pytest.mark.asyncio
    async def test_test_connection_delegates_to_send(self):
        n = self._make()
        with patch.object(n, "send", new_callable=AsyncMock, return_value=True) as mock_send:
            result = await n.test_connection()
        assert result is True
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_severity_colors(self):
        n = self._make()
        mock_resp = MagicMock(status_code=200)

        for severity, expected_color in [
            ("critical", "#FF0000"),
            ("high", "#FF6600"),
            ("medium", "#FFCC00"),
            ("low", "#0066FF"),
            ("unknown", "#808080"),
        ]:
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance

                await n.send("Test", "body", severity=severity)

            payload = instance.post.call_args.kwargs.get("json") or instance.post.call_args[1].get("json")
            assert payload["attachments"][0]["color"] == expected_color, f"Failed for {severity}"


# ============================================================================
# EmailNotifier Tests
# ============================================================================


class TestEmailNotifier:
    """Tests for EmailNotifier."""

    def _make(self, **overrides):
        config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "username": "user@example.com",
            "password": "secret",
            "from_addr": "ops@example.com",
            "to_addrs": ["admin@example.com", "oncall@example.com"],
            "use_tls": True,
        }
        config.update(overrides)
        return EmailNotifier(config)

    def test_init(self):
        n = self._make()
        assert n.smtp_host == "smtp.example.com"
        assert n.smtp_port == 587
        assert n.smtp_user == "user@example.com"
        assert n.smtp_password == "secret"
        assert n.from_email == "ops@example.com"
        assert n.to_emails == ["admin@example.com", "oncall@example.com"]
        assert n.use_tls is True

    def test_init_legacy_keys(self):
        config = {
            "smtp_host": "smtp.test.com",
            "smtp_user": "legacy@test.com",
            "smtp_password": "pw",
            "from_email": "from@test.com",
            "to_emails": ["dest@test.com"],
        }
        n = EmailNotifier(config)
        assert n.smtp_user == "legacy@test.com"
        assert n.from_email == "from@test.com"
        assert n.to_emails == ["dest@test.com"]

    def test_init_to_addrs_string(self):
        """to_addrs as single string gets wrapped in list."""
        n = EmailNotifier({"to_addrs": "single@test.com"})
        assert n.to_emails == ["single@test.com"]

    def test_init_defaults(self):
        n = EmailNotifier({})
        assert n.smtp_host == "localhost"
        assert n.smtp_port == 587
        assert n.from_email == "aiops@localhost"
        assert n.to_emails == []

    @pytest.mark.asyncio
    async def test_send_no_recipients(self):
        n = EmailNotifier({})
        result = await n.send("Subject", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        n = self._make()
        with patch.object(n, "_send_email") as mock_send:
            result = await n.send("Alert", "Something happened", severity="high")
        assert result is True
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_exception(self):
        n = self._make()
        with patch.object(n, "_send_email", side_effect=Exception("SMTP error")):
            result = await n.send("Alert", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        n = self._make()
        with patch.object(n, "_test_smtp"):
            result = await n.test_connection()
        assert result is True

    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        n = self._make()
        with patch.object(n, "_test_smtp", side_effect=Exception("conn refused")):
            result = await n.test_connection()
        assert result is False


# ============================================================================
# SNSNotifier Tests
# ============================================================================


class TestSNSNotifier:
    """Tests for SNSNotifier."""

    def _make(self, **overrides):
        config = {
            "topic_arn": "arn:aws:sns:us-east-1:123456789:alerts",
            "region": "us-east-1",
        }
        config.update(overrides)
        return SNSNotifier(config)

    def test_init(self):
        n = self._make()
        assert n.topic_arn == "arn:aws:sns:us-east-1:123456789:alerts"
        assert n.region == "us-east-1"

    def test_init_defaults(self):
        n = SNSNotifier({})
        assert n.topic_arn is None
        assert n.region == "us-east-1"

    @pytest.mark.asyncio
    async def test_send_no_topic(self):
        n = SNSNotifier({})
        result = await n.send("Subject", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        n = self._make()
        with patch.object(n, "_publish_sns") as mock_pub:
            result = await n.send("Alert", "Body", severity="critical")
        assert result is True
        mock_pub.assert_called_once_with("Alert", "Body", "critical")

    @pytest.mark.asyncio
    async def test_send_exception(self):
        n = self._make()
        with patch.object(n, "_publish_sns", side_effect=Exception("AWS error")):
            result = await n.send("Alert", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.get_topic_attributes.return_value = {}
        with patch("boto3.client", return_value=mock_client):
            result = await n.test_connection()
        assert result is True

    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.get_topic_attributes.side_effect = Exception("not found")
        with patch("boto3.client", return_value=mock_client):
            result = await n.test_connection()
        assert result is False


# ============================================================================
# NotificationLog Model Tests
# ============================================================================


class TestNotificationLog:
    """Tests for NotificationLog model."""

    def test_model_tablename(self):
        assert NotificationLog.__tablename__ == "notification_logs"

    def test_model_columns(self):
        columns = {c.name for c in NotificationLog.__table__.columns}
        expected = {"id", "channel_name", "subject", "body", "severity", "status", "error", "sent_at"}
        assert expected.issubset(columns)
