"""Tests for agenticops.notify.notifier — boosting from 43% coverage.

Focus: SlackNotifier, EmailNotifier, SNSNotifier, WebhookNotifier construction,
send logic with mocked HTTP/SMTP, and NotificationLog model.
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from agenticops.notify.notifier import (
    NotificationLog,
    Notifier,
    SlackNotifier,
    EmailNotifier,
    SNSNotifier,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_async(coro):
    """Run an async coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# NotificationLog model
# ---------------------------------------------------------------------------

class TestNotificationLog:
    def test_table_name(self):
        assert NotificationLog.__tablename__ == "notification_logs"

    def test_has_expected_columns(self):
        cols = {c.name for c in NotificationLog.__table__.columns}
        assert "channel_name" in cols
        assert "subject" in cols
        assert "body" in cols
        assert "severity" in cols
        assert "status" in cols
        assert "error" in cols
        assert "sent_at" in cols


# ---------------------------------------------------------------------------
# SlackNotifier
# ---------------------------------------------------------------------------

class TestSlackNotifier:
    def _make(self, **overrides):
        cfg = {"webhook_url": "https://hooks.slack.com/test", "channel": "#alerts"}
        cfg.update(overrides)
        return SlackNotifier(cfg)

    def test_init_defaults(self):
        n = self._make()
        assert n.webhook_url == "https://hooks.slack.com/test"
        assert n.channel == "#alerts"
        assert n.username == "AgenticAIOps"
        assert n.icon_emoji == ":robot_face:"

    def test_send_no_webhook(self):
        n = self._make(webhook_url=None)
        result = run_async(n.send("subj", "body"))
        assert result is False

    def test_send_success(self):
        n = self._make()
        mock_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = run_async(n.send("Alert", "Something happened", severity="critical"))
            assert result is True
            instance.post.assert_called_once()
            call_kwargs = instance.post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert payload["attachments"][0]["color"] == "#FF0000"

    def test_send_severity_colors(self):
        n = self._make()
        for sev, expected_color in [("critical", "#FF0000"), ("high", "#FF6600"),
                                     ("medium", "#FFCC00"), ("low", "#0066FF")]:
            mock_resp = MagicMock(status_code=200)
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance

                run_async(n.send("Alert", "body", severity=sev))
                payload = instance.post.call_args.kwargs.get("json") or instance.post.call_args[1].get("json")
                assert payload["attachments"][0]["color"] == expected_color

    def test_send_no_severity(self):
        n = self._make()
        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = run_async(n.send("Alert", "body"))
            assert result is True
            payload = instance.post.call_args.kwargs.get("json") or instance.post.call_args[1].get("json")
            # No severity → gray color and no fields
            assert payload["attachments"][0]["color"] == "#808080"
            assert "fields" not in payload["attachments"][0]

    def test_send_http_error(self):
        n = self._make()
        mock_resp = MagicMock(status_code=500)
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = run_async(n.send("Alert", "body"))
            assert result is False

    def test_send_exception(self):
        n = self._make()
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=Exception("network error"))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = run_async(n.send("Alert", "body"))
            assert result is False

    def test_test_connection_delegates_to_send(self):
        n = self._make()
        with patch.object(n, "send", new_callable=AsyncMock, return_value=True) as mock_send:
            result = run_async(n.test_connection())
            assert result is True
            mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# EmailNotifier
# ---------------------------------------------------------------------------

class TestEmailNotifier:
    def _make(self, **overrides):
        cfg = {
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "smtp_password": "pass",
            "from_email": "test@test.com",
            "to_emails": ["dest@test.com"],
        }
        cfg.update(overrides)
        return EmailNotifier(cfg)

    def test_init(self):
        n = self._make()
        assert n.smtp_host == "smtp.test.com"
        assert n.smtp_port == 587
        assert n.use_tls is True
        assert len(n.to_emails) == 1

    def test_send_no_recipients(self):
        n = self._make(to_emails=[])
        result = run_async(n.send("subj", "body"))
        assert result is False

    def test_send_success(self):
        n = self._make()
        with patch.object(n, "_send_email") as mock_send:
            result = run_async(n.send("Alert", "Something happened", severity="high"))
            assert result is True
            mock_send.assert_called_once()

    def test_send_with_severity(self):
        n = self._make()
        with patch.object(n, "_send_email") as mock_send:
            result = run_async(n.send("Alert", "Body", severity="critical"))
            assert result is True

    def test_send_without_severity(self):
        n = self._make()
        with patch.object(n, "_send_email") as mock_send:
            result = run_async(n.send("Alert", "Body"))
            assert result is True

    def test_send_smtp_failure(self):
        n = self._make()
        with patch.object(n, "_send_email", side_effect=Exception("SMTP error")):
            result = run_async(n.send("Alert", "Body"))
            assert result is False

    def test_send_email_method(self):
        n = self._make()
        mock_msg = MagicMock()
        with patch("smtplib.SMTP") as MockSMTP:
            server_inst = MagicMock()
            MockSMTP.return_value.__enter__ = MagicMock(return_value=server_inst)
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            n._send_email(mock_msg)
            server_inst.starttls.assert_called_once()
            server_inst.login.assert_called_once_with("user", "pass")
            server_inst.send_message.assert_called_once_with(mock_msg)

    def test_send_email_no_tls(self):
        n = self._make(use_tls=False)
        mock_msg = MagicMock()
        with patch("smtplib.SMTP") as MockSMTP:
            server_inst = MagicMock()
            MockSMTP.return_value.__enter__ = MagicMock(return_value=server_inst)
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            n._send_email(mock_msg)
            server_inst.starttls.assert_not_called()

    def test_send_email_no_auth(self):
        n = self._make(smtp_user=None, smtp_password=None)
        mock_msg = MagicMock()
        with patch("smtplib.SMTP") as MockSMTP:
            server_inst = MagicMock()
            MockSMTP.return_value.__enter__ = MagicMock(return_value=server_inst)
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            n._send_email(mock_msg)
            server_inst.login.assert_not_called()

    def test_test_connection_success(self):
        n = self._make()
        with patch.object(n, "_test_smtp"):
            result = run_async(n.test_connection())
            assert result is True

    def test_test_connection_failure(self):
        n = self._make()
        with patch.object(n, "_test_smtp", side_effect=Exception("fail")):
            result = run_async(n.test_connection())
            assert result is False


# ---------------------------------------------------------------------------
# Config-key mapping regression: UI/YAML keys must populate recipients.
# Bug: SESNotifier read "to" but the UI/YAML key is "recipients" → recipients
# silently emptied → send() returned False without ever calling SES. Same shape
# in EmailNotifier (username/password/from_addr/to_addrs vs legacy keys).
# ---------------------------------------------------------------------------

class TestConfigKeyMapping:
    def test_ses_reads_recipients_key(self):
        from agenticops.notify.notifier import SESNotifier
        n = SESNotifier({"sender": "s@x.com", "recipients": ["r@x.com"], "region": "us-east-1"})
        assert n.recipients == ["r@x.com"]  # not dropped to []

    def test_ses_legacy_to_key_still_works(self):
        from agenticops.notify.notifier import SESNotifier
        n = SESNotifier({"sender": "s@x.com", "to": ["legacy@x.com"]})
        assert n.recipients == ["legacy@x.com"]

    def test_ses_send_false_without_recipients(self):
        from agenticops.notify.notifier import SESNotifier
        n = SESNotifier({"sender": "s@x.com", "region": "us-east-1"})
        assert n.recipients == []
        assert run_async(n.send("subj", "body")) is False

    def test_email_reads_ui_keys(self):
        n = EmailNotifier({
            "smtp_host": "h", "username": "u", "password": "p",
            "from_addr": "f@x.com", "to_addrs": ["r@x.com"],
        })
        assert n.smtp_user == "u"
        assert n.smtp_password == "p"
        assert n.from_email == "f@x.com"
        assert n.to_emails == ["r@x.com"]

    def test_email_legacy_keys_still_work(self):
        n = EmailNotifier({
            "smtp_user": "u2", "smtp_password": "p2",
            "from_email": "f2@x.com", "to_emails": ["r2@x.com"],
        })
        assert n.smtp_user == "u2"
        assert n.from_email == "f2@x.com"
        assert n.to_emails == ["r2@x.com"]


# ---------------------------------------------------------------------------
# SNSNotifier
# ---------------------------------------------------------------------------

class TestSNSNotifier:
    def _make(self, **overrides):
        cfg = {"topic_arn": "arn:aws:sns:us-east-1:123456:test", "region": "us-east-1"}
        cfg.update(overrides)
        return SNSNotifier(cfg)

    def test_init(self):
        n = self._make()
        assert n.topic_arn == "arn:aws:sns:us-east-1:123456:test"
        assert n.region == "us-east-1"

    def test_send_no_topic_arn(self):
        n = self._make(topic_arn=None)
        result = run_async(n.send("subj", "body"))
        assert result is False

    def test_send_success(self):
        n = self._make()
        with patch.object(n, "_publish_sns"):
            result = run_async(n.send("Alert", "Body", severity="high"))
            assert result is True

    def test_send_failure(self):
        n = self._make()
        with patch.object(n, "_publish_sns", side_effect=Exception("aws error")):
            result = run_async(n.send("Alert", "Body"))
            assert result is False

    def test_publish_sns(self):
        n = self._make()
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            n._publish_sns("Alert", "Body", "critical")
            mock_client.publish.assert_called_once()
            call_kwargs = mock_client.publish.call_args.kwargs
            assert call_kwargs["TopicArn"] == n.topic_arn
            assert "critical" in call_kwargs["MessageAttributes"]["severity"]["StringValue"]

    def test_publish_sns_no_severity(self):
        n = self._make()
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            n._publish_sns("Alert", "Body", None)
            call_kwargs = mock_client.publish.call_args.kwargs
            assert call_kwargs["MessageAttributes"]["severity"]["StringValue"] == "info"

    def test_test_connection_success(self):
        n = self._make()
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            result = run_async(n.test_connection())
            assert result is True
            mock_client.get_topic_attributes.assert_called_once()

    def test_test_connection_failure(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.get_topic_attributes.side_effect = Exception("not found")
        with patch("boto3.client", return_value=mock_client):
            result = run_async(n.test_connection())
            assert result is False
