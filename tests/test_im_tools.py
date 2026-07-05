"""Tests for agenticops.tools.im_tools — IM channel management tools.

Covers: list_im_channels, add_im_channel, remove_im_channel,
toggle_im_channel, list_im_apps, set_im_app, import_im_config.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agenticops.tools.im_tools import (
    _mask_secret,
    list_im_channels,
    add_im_channel,
    remove_im_channel,
    toggle_im_channel,
    list_im_apps,
    set_im_app,
    import_im_config,
)


# ── Helper fixtures ──────────────────────────────────────────────────


class FakeChannelConfig:
    """Minimal stand-in for ChannelConfig dataclass."""

    def __init__(self, name, channel_type="feishu", config=None,
                 is_enabled=True, role="chat"):
        self.name = name
        self.channel_type = channel_type
        self.config = config or {}
        self.is_enabled = is_enabled
        self.role = role


# ── _mask_secret ─────────────────────────────────────────────────────


class TestMaskSecret:
    def test_short_value(self):
        assert _mask_secret("abc") == "****"

    def test_empty(self):
        assert _mask_secret("") == "****"

    def test_none(self):
        assert _mask_secret(None) == "****"

    def test_normal_value(self):
        result = _mask_secret("super-secret-token-12345678")
        assert result.startswith("****")
        assert result.endswith("5678")
        assert "super" not in result

    def test_exactly_8_chars(self):
        result = _mask_secret("12345678")
        assert result == "****5678"


# ── list_im_channels ─────────────────────────────────────────────────


class TestListImChannels:
    def test_empty_channels(self):
        with patch("agenticops.notify.im_config.load_channels", return_value=[]):
            result = list_im_channels._tool_func()
            assert "No channels configured" in result

    def test_with_channels(self):
        channels = [
            FakeChannelConfig("ops-alerts", "slack", {"webhook_url": "https://hooks.slack.com/xxx"}, True, "alert"),
            FakeChannelConfig("feishu-chat", "feishu", {"chat_id": "oc_123"}, False, "chat"),
        ]
        with patch("agenticops.notify.im_config.load_channels", return_value=channels):
            result = list_im_channels._tool_func()
            assert "ops-alerts" in result
            assert "slack" in result
            assert "✓" in result  # enabled marker
            assert "○" in result  # disabled marker
            assert "feishu-chat" in result
            # webhook_url is safe (no token/secret/key in key name) so it shows
            assert "webhook_url" in result

    def test_masks_sensitive_keys(self):
        """Config keys with 'token', 'secret', 'key' should be filtered."""
        channels = [
            FakeChannelConfig("test-ch", "webhook", {
                "url": "https://example.com",
                "auth_token": "secret-value-1234",
                "api_key": "key-value-5678",
            }),
        ]
        with patch("agenticops.notify.im_config.load_channels", return_value=channels):
            result = list_im_channels._tool_func()
            assert "url=https://example.com" in result
            # token/key fields should be filtered from safe display
            assert "secret-value" not in result
            assert "key-value" not in result


# ── add_im_channel ───────────────────────────────────────────────────


class TestAddImChannel:
    def test_valid_add(self):
        with patch("agenticops.notify.im_config.save_channel") as mock_save:
            result = add_im_channel._tool_func(
                name="my-slack",
                channel_type="slack",
                config_json='{"webhook_url": "https://hooks.slack.com/xxx"}',
                enabled=True,
                role="alert",
            )
            assert "my-slack" in result
            assert "slack" in result
            mock_save.assert_called_once()
            args = mock_save.call_args
            assert args[0][0] == "my-slack"
            assert args[0][1] == "slack"

    def test_invalid_channel_type(self):
        result = add_im_channel._tool_func(
            name="bad", channel_type="telegram", config_json="{}", enabled=True, role="chat"
        )
        assert "Invalid channel_type" in result
        assert "telegram" in result

    def test_invalid_json(self):
        result = add_im_channel._tool_func(
            name="test", channel_type="feishu", config_json="not-json{", enabled=True, role="chat"
        )
        assert "Invalid config_json" in result

    def test_disabled_channel(self):
        with patch("agenticops.notify.im_config.save_channel"):
            result = add_im_channel._tool_func(
                name="ch", channel_type="webhook", config_json="{}", enabled=False, role="chat"
            )
            assert "disabled" in result


# ── remove_im_channel ────────────────────────────────────────────────


class TestRemoveImChannel:
    def test_remove_existing(self):
        with patch("agenticops.notify.im_config.delete_channel", return_value=True):
            result = remove_im_channel._tool_func(name="old-ch")
            assert "removed" in result

    def test_remove_nonexistent(self):
        with patch("agenticops.notify.im_config.delete_channel", return_value=False):
            result = remove_im_channel._tool_func(name="ghost")
            assert "not found" in result


# ── toggle_im_channel ────────────────────────────────────────────────


class TestToggleImChannel:
    def test_enable(self):
        channels = [FakeChannelConfig("ch1", "slack", {"url": "x"}, False)]
        with patch("agenticops.notify.im_config.load_channels", return_value=channels):
            with patch("agenticops.notify.im_config.save_channel") as mock_save:
                result = toggle_im_channel._tool_func(name="ch1", enabled=True)
                assert "enabled" in result
                mock_save.assert_called_once()

    def test_disable(self):
        channels = [FakeChannelConfig("ch1", "feishu", {}, True)]
        with patch("agenticops.notify.im_config.load_channels", return_value=channels):
            with patch("agenticops.notify.im_config.save_channel"):
                result = toggle_im_channel._tool_func(name="ch1", enabled=False)
                assert "disabled" in result

    def test_not_found(self):
        with patch("agenticops.notify.im_config.load_channels", return_value=[]):
            result = toggle_im_channel._tool_func(name="nope", enabled=True)
            assert "not found" in result


# ── list_im_apps ─────────────────────────────────────────────────────


class TestListImApps:
    def test_empty(self):
        with patch("agenticops.notify.im_config.list_apps", return_value={}):
            result = list_im_apps._tool_func()
            assert "No IM apps configured" in result

    def test_with_apps(self):
        apps = {"feishu": ["default"], "slack": ["prod-bot"]}
        raw = {
            "feishu": {"default": {"app_id": "cli_xxx", "app_secret": "abcdefgh12345678"}},
            "slack": {"prod-bot": {"bot_token": "xoxb-supersecret99"}},
        }
        with patch("agenticops.notify.im_config.list_apps", return_value=apps):
            with patch("agenticops.notify.im_config._load_raw", return_value=raw):
                result = list_im_apps._tool_func()
                assert "feishu/default" in result
                assert "slack/prod-bot" in result
                # Secrets should be masked
                assert "abcdefgh" not in result
                assert "supersecret" not in result
                # Last 4 should appear
                assert "5678" in result


# ── set_im_app ───────────────────────────────────────────────────────


class TestSetImApp:
    def test_invalid_platform(self):
        result = set_im_app._tool_func(
            platform="telegram", app_name="bot", config_json='{"token": "x"}'
        )
        assert "Invalid platform" in result

    def test_invalid_json(self):
        result = set_im_app._tool_func(
            platform="feishu", app_name="default", config_json="broken{"
        )
        assert "Invalid config_json" in result

    def test_valid_save(self, tmp_path):
        config_file = tmp_path / "im-apps.yaml"
        mock_settings = MagicMock()
        mock_settings.im_apps_config = config_file

        with patch("agenticops.config.settings", mock_settings):
            result = set_im_app._tool_func(
                platform="feishu",
                app_name="default",
                config_json='{"app_id": "cli_abc", "app_secret": "secret12345678"}',
            )
            assert "saved" in result
            assert "feishu/default" in result
            # Secret should be masked in response
            assert "secret1234" not in result
            assert "5678" in result
            # File should be written
            assert config_file.exists()


# ── import_im_config ─────────────────────────────────────────────────


class TestImportImConfig:
    def test_invalid_json(self):
        result = import_im_config._tool_func(config_json="not json")
        assert "Invalid JSON" in result

    def test_import_channels(self):
        data = {
            "channels": {
                "ch1": {"type": "slack", "webhook_url": "https://x"},
                "ch2": {"type": "feishu", "chat_id": "oc_123"},
            }
        }
        with patch("agenticops.notify.im_config.save_channel") as mock_save:
            result = import_im_config._tool_func(config_json=json.dumps(data))
            assert "2 channels" in result
            assert mock_save.call_count == 2

    def test_import_apps(self, tmp_path):
        config_file = tmp_path / "im-apps.yaml"
        mock_settings = MagicMock()
        mock_settings.im_apps_config = config_file

        data = {
            "apps": {
                "feishu": {"default": {"app_id": "id1", "app_secret": "sec1"}},
                "slack": {"bot": {"bot_token": "xoxb-123"}},
            }
        }
        with patch("agenticops.config.settings", mock_settings):
            result = import_im_config._tool_func(config_json=json.dumps(data))
            assert "2 apps" in result
            assert config_file.exists()

    def test_import_both(self, tmp_path):
        config_file = tmp_path / "im-apps.yaml"
        mock_settings = MagicMock()
        mock_settings.im_apps_config = config_file

        data = {
            "channels": {"c1": {"type": "webhook", "url": "https://x"}},
            "apps": {"dingtalk": {"bot1": {"token": "t1"}}},
        }
        with patch("agenticops.notify.im_config.save_channel"):
            with patch("agenticops.config.settings", mock_settings):
                result = import_im_config._tool_func(config_json=json.dumps(data))
                assert "1 channels" in result
                assert "1 apps" in result
