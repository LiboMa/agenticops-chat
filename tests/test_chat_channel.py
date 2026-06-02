"""Unit tests for agenticops.chat.channel module.

Covers: execute_channel, _channel_list, _channel_show, _channel_test, _channel_set.
"""

from unittest.mock import patch, MagicMock

import pytest

from agenticops.chat.channel import (
    execute_channel,
    ChannelResult,
    _channel_list,
    _channel_show,
    _channel_test,
    _channel_set,
    _help_text,
)


# ── execute_channel routing tests ────────────────────────────────────


class TestExecuteChannel:
    @patch("agenticops.chat.channel._channel_list")
    def test_no_args_defaults_to_list(self, mock_list):
        mock_list.return_value = ChannelResult(True, "channels")
        result = execute_channel("/channel")
        mock_list.assert_called_once()

    @patch("agenticops.chat.channel._channel_list")
    def test_list_subcommand(self, mock_list):
        mock_list.return_value = ChannelResult(True, "channels")
        result = execute_channel("/channel list")
        mock_list.assert_called_once()

    @patch("agenticops.chat.channel._channel_list")
    def test_ls_alias(self, mock_list):
        mock_list.return_value = ChannelResult(True, "channels")
        result = execute_channel("/channel ls")
        mock_list.assert_called_once()

    @patch("agenticops.chat.channel._channel_show")
    def test_show_subcommand(self, mock_show):
        mock_show.return_value = ChannelResult(True, "details")
        result = execute_channel("/channel show slack")
        mock_show.assert_called_once_with("slack")

    def test_show_no_name(self):
        result = execute_channel("/channel show")
        assert not result.success
        assert "Usage" in result.message

    @patch("agenticops.chat.channel._channel_test")
    def test_test_subcommand(self, mock_test):
        mock_test.return_value = ChannelResult(True, "sent")
        result = execute_channel("/channel test email")
        mock_test.assert_called_once_with("email")

    def test_test_no_name(self):
        result = execute_channel("/channel test")
        assert not result.success
        assert "Usage" in result.message

    @patch("agenticops.chat.channel._channel_set")
    def test_set_subcommand(self, mock_set):
        mock_set.return_value = ChannelResult(True, "updated")
        result = execute_channel("/channel set slack webhook_url https://hooks.slack.com/xxx")
        mock_set.assert_called_once_with("slack", "webhook_url", "https://hooks.slack.com/xxx")

    def test_set_too_few_args(self):
        result = execute_channel("/channel set slack")
        assert not result.success
        assert "Usage" in result.message

    def test_unknown_subcommand(self):
        result = execute_channel("/channel foobar")
        assert not result.success
        assert "Channel Commands" in result.message

    @patch("agenticops.chat.channel._channel_list")
    def test_channels_prefix(self, mock_list):
        mock_list.return_value = ChannelResult(True, "ok")
        result = execute_channel("/channels list")
        mock_list.assert_called_once()


# ── _channel_list tests ──────────────────────────────────────────────


class TestChannelList:
    @patch("agenticops.notify.im_config.load_channels")
    def test_no_channels(self, mock_load):
        mock_load.return_value = []
        result = _channel_list()
        assert result.success
        assert "No notification channels" in result.message

    @patch("agenticops.notify.im_config.load_channels")
    def test_with_channels(self, mock_load):
        ch1 = MagicMock()
        ch1.name = "slack-ops"
        ch1.channel_type = "slack"
        ch1.is_enabled = True
        ch1.config = {"chat_id": "C123456"}

        ch2 = MagicMock()
        ch2.name = "email-oncall"
        ch2.channel_type = "email"
        ch2.is_enabled = False
        ch2.config = {}

        mock_load.return_value = [ch1, ch2]
        result = _channel_list()
        assert result.success
        assert "slack-ops" in result.message
        assert "[ON]" in result.message
        assert "[OFF]" in result.message

    @patch("agenticops.notify.im_config.load_channels")
    def test_long_chat_id_truncated(self, mock_load):
        ch = MagicMock()
        ch.name = "test"
        ch.channel_type = "slack"
        ch.is_enabled = True
        ch.config = {"chat_id": "x" * 50}
        mock_load.return_value = [ch]

        result = _channel_list()
        assert "..." in result.message


# ── _channel_show tests ──────────────────────────────────────────────


class TestChannelShow:
    @patch("agenticops.notify.im_config.get_channel")
    def test_not_found(self, mock_get):
        mock_get.return_value = None
        result = _channel_show("missing")
        assert not result.success
        assert "not found" in result.message

    @patch("agenticops.notify.im_config.get_channel")
    def test_show_details(self, mock_get):
        ch = MagicMock()
        ch.name = "slack-ops"
        ch.channel_type = "slack"
        ch.is_enabled = True
        ch.severity_filter = ["critical", "high"]
        ch.config = {"token": "xoxb-secret-value-123", "channel": "#alerts"}
        mock_get.return_value = ch

        result = _channel_show("slack-ops")
        assert result.success
        assert "slack-ops" in result.message
        assert "critical" in result.message
        # Token should be masked (key contains "token")
        assert "secret-value-123" not in result.message
        assert "****" in result.message
        # Non-secret shown
        assert "#alerts" in result.message


# ── _channel_test tests ──────────────────────────────────────────────


class TestChannelTest:
    @patch("agenticops.notify.notifier.NotificationManager")
    def test_success(self, mock_nm_class):
        mock_nm = MagicMock()
        mock_nm_class.return_value = mock_nm

        import asyncio
        async def fake_send(**kwargs):
            return {"slack-ops": True}

        mock_nm.send_notification = fake_send

        result = _channel_test("slack-ops")
        assert result.success
        assert "successfully" in result.message

    @patch("agenticops.notify.notifier.NotificationManager")
    def test_failure(self, mock_nm_class):
        mock_nm = MagicMock()
        mock_nm_class.return_value = mock_nm

        async def fake_send(**kwargs):
            return {"slack-ops": False}

        mock_nm.send_notification = fake_send

        result = _channel_test("slack-ops")
        assert not result.success
        assert "failed" in result.message

    @patch("agenticops.notify.notifier.NotificationManager")
    def test_not_found(self, mock_nm_class):
        mock_nm = MagicMock()
        mock_nm_class.return_value = mock_nm

        async def fake_send(**kwargs):
            return {}

        mock_nm.send_notification = fake_send

        result = _channel_test("missing")
        assert not result.success

    @patch("agenticops.notify.notifier.NotificationManager")
    def test_exception(self, mock_nm_class):
        mock_nm_class.side_effect = Exception("import error")
        result = _channel_test("broken")
        assert not result.success
        assert "failed" in result.message.lower()


# ── _channel_set tests ───────────────────────────────────────────────


class TestChannelSet:
    @patch("agenticops.notify.im_config.save_channel")
    @patch("agenticops.notify.im_config.get_channel")
    def test_set_enabled(self, mock_get, mock_save):
        ch = MagicMock()
        ch.channel_type = "slack"
        ch.config = {"webhook_url": "https://x"}
        ch.is_enabled = True
        ch.severity_filter = ["critical"]
        mock_get.return_value = ch

        result = _channel_set("slack-ops", "enabled", "false")
        assert result.success
        assert "enabled" in result.message
        mock_save.assert_called_once()
        assert mock_save.call_args[1]["is_enabled"] is False

    @patch("agenticops.notify.im_config.save_channel")
    @patch("agenticops.notify.im_config.get_channel")
    def test_set_severity(self, mock_get, mock_save):
        ch = MagicMock()
        ch.channel_type = "slack"
        ch.config = {}
        ch.is_enabled = True
        ch.severity_filter = []
        mock_get.return_value = ch

        result = _channel_set("slack-ops", "severity", "critical, high")
        assert result.success
        assert mock_save.call_args[1]["severity_filter"] == ["critical", "high"]

    @patch("agenticops.notify.im_config.save_channel")
    @patch("agenticops.notify.im_config.get_channel")
    def test_set_config_field(self, mock_get, mock_save):
        ch = MagicMock()
        ch.channel_type = "slack"
        ch.config = {"channel": "#old"}
        ch.is_enabled = True
        ch.severity_filter = []
        mock_get.return_value = ch

        result = _channel_set("slack-ops", "channel", "#new-alerts")
        assert result.success
        assert "#new-alerts" in result.message

    @patch("agenticops.notify.im_config.get_channel")
    def test_not_found(self, mock_get):
        mock_get.return_value = None
        result = _channel_set("missing", "key", "val")
        assert not result.success
        assert "not found" in result.message


# ── _help_text test ──────────────────────────────────────────────────


class TestHelpText:
    def test_contains_commands(self):
        text = _help_text()
        assert "/channel list" in text
        assert "/channel show" in text
        assert "/channel test" in text
        assert "/channel set" in text
