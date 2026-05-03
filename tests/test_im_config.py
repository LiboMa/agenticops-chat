"""Tests for agenticops.notify.im_config — IM app and channel configuration.

Targets coverage from 67% → 85%+.
Covers: _interpolate_env, _load_raw, get_feishu_app, get_dingtalk_app,
        get_wecom_app, get_slack_app, list_apps, _load_channels_raw,
        _parse_channel, load_channels, get_channel, save_channel,
        delete_channel, find_channel_by_chat, _invalidate_channels_cache.
"""

import os
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

from agenticops.notify.im_config import (
    _interpolate_env,
    _load_raw,
    get_feishu_app,
    get_dingtalk_app,
    get_wecom_app,
    get_slack_app,
    list_apps,
    FeishuAppConfig,
    DingTalkAppConfig,
    WeComAppConfig,
    SlackAppConfig,
    ChannelConfig,
    _parse_channel,
    load_channels,
    get_channel,
    save_channel,
    delete_channel,
    find_channel_by_chat,
    _load_channels_raw,
    _invalidate_channels_cache,
)

# ── Helpers ─────────────────────────────────────────────────────────


def _reset_app_cache():
    """Reset the module-level app config cache."""
    import agenticops.notify.im_config as mod
    mod._cached_data = None
    mod._cached_mtime = 0.0


def _reset_channels_cache():
    """Reset the module-level channels config cache."""
    _invalidate_channels_cache()


# ── _interpolate_env ────────────────────────────────────────────────


class TestInterpolateEnv:
    def test_string_substitution(self):
        with patch.dict(os.environ, {"MY_VAR": "hello"}):
            assert _interpolate_env("prefix-${MY_VAR}-suffix") == "prefix-hello-suffix"

    def test_missing_env_returns_empty(self):
        result = _interpolate_env("${DEFINITELY_NOT_SET_XYZ}")
        assert result == ""

    def test_dict_recursive(self):
        with patch.dict(os.environ, {"A": "1"}):
            result = _interpolate_env({"key": "${A}", "nested": {"inner": "${A}"}})
            assert result == {"key": "1", "nested": {"inner": "1"}}

    def test_list_recursive(self):
        with patch.dict(os.environ, {"B": "val"}):
            result = _interpolate_env(["${B}", "literal"])
            assert result == ["val", "literal"]

    def test_non_string_passthrough(self):
        assert _interpolate_env(42) == 42
        assert _interpolate_env(True) is True
        assert _interpolate_env(None) is None


# ── _load_raw ───────────────────────────────────────────────────────


class TestLoadRaw:
    def test_file_not_found_returns_empty(self, tmp_path):
        _reset_app_cache()
        mock_settings = MagicMock()
        mock_settings.im_apps_config = tmp_path / "nonexistent.yaml"
        with patch("agenticops.notify.im_config.settings", mock_settings):
            assert _load_raw() == {}

    def test_loads_yaml(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im-apps.yaml"
        cfg.write_text(yaml.dump({"feishu": {"default": {"app_id": "id1"}}}))
        mock_settings = MagicMock()
        mock_settings.im_apps_config = cfg
        with patch("agenticops.notify.im_config.settings", mock_settings):
            data = _load_raw()
            assert data["feishu"]["default"]["app_id"] == "id1"

    def test_cache_hit(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im-apps.yaml"
        cfg.write_text(yaml.dump({"feishu": {"default": {"app_id": "x"}}}))
        mock_settings = MagicMock()
        mock_settings.im_apps_config = cfg
        with patch("agenticops.notify.im_config.settings", mock_settings):
            d1 = _load_raw()
            d2 = _load_raw()
            assert d1 is d2  # same object = cache hit

    def test_cache_invalidation_on_mtime_change(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im-apps.yaml"
        cfg.write_text(yaml.dump({"v": 1}))
        mock_settings = MagicMock()
        mock_settings.im_apps_config = cfg
        with patch("agenticops.notify.im_config.settings", mock_settings):
            d1 = _load_raw()
            # Simulate file change by modifying content and mtime
            cfg.write_text(yaml.dump({"v": 2}))
            os.utime(cfg, (cfg.stat().st_mtime + 10, cfg.stat().st_mtime + 10))
            d2 = _load_raw()
            assert d2["v"] == 2


# ── App getter functions ────────────────────────────────────────────


class TestGetFeishuApp:
    def test_returns_config(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({
            "feishu": {"default": {"app_id": "aid", "app_secret": "sec", "encrypt_key": "ek"}}
        }))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            app = get_feishu_app()
            assert isinstance(app, FeishuAppConfig)
            assert app.app_id == "aid"
            assert app.app_secret == "sec"

    def test_returns_none_missing(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({"feishu": {}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            assert get_feishu_app("nonexistent") is None

    def test_returns_none_no_app_id(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({"feishu": {"default": {"app_secret": "sec"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            assert get_feishu_app() is None


class TestGetDingtalkApp:
    def test_returns_config(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({
            "dingtalk": {"default": {"app_key": "dk", "app_secret": "ds"}}
        }))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            app = get_dingtalk_app()
            assert isinstance(app, DingTalkAppConfig)
            assert app.app_key == "dk"

    def test_returns_none_missing_key(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({"dingtalk": {"default": {"app_secret": "ds"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            assert get_dingtalk_app() is None


class TestGetWecomApp:
    def test_returns_config(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({
            "wecom": {"default": {"corp_id": "cid", "corp_secret": "cs", "agent_id": 100,
                                   "callback_token": "ct", "encoding_aes_key": "eak"}}
        }))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            app = get_wecom_app()
            assert isinstance(app, WeComAppConfig)
            assert app.corp_id == "cid"
            assert app.agent_id == 100
            assert app.callback_token == "ct"
            assert app.encoding_aes_key == "eak"

    def test_returns_none_no_corp_id(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({"wecom": {"default": {"corp_secret": "cs"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            assert get_wecom_app() is None


class TestGetSlackApp:
    def test_returns_config(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({
            "slack": {"default": {"bot_token": "xoxb-123", "app_token": "xapp-456",
                                   "signing_secret": "sig", "respond_to": "all"}}
        }))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            app = get_slack_app()
            assert isinstance(app, SlackAppConfig)
            assert app.bot_token == "xoxb-123"
            assert app.respond_to == "all"

    def test_returns_none_no_bot_token(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({"slack": {"default": {"signing_secret": "s"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            assert get_slack_app() is None


class TestListApps:
    def test_lists_all_platforms(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text(yaml.dump({
            "feishu": {"a1": {"app_id": "x"}},
            "dingtalk": {"d1": {"app_key": "x"}, "d2": {"app_key": "y"}},
            "slack": {"s1": {"bot_token": "x"}},
        }))
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            result = list_apps()
            assert "feishu" in result
            assert result["feishu"] == ["a1"]
            assert len(result["dingtalk"]) == 2
            assert "wecom" not in result  # not configured

    def test_empty_config(self, tmp_path):
        _reset_app_cache()
        cfg = tmp_path / "im.yaml"
        cfg.write_text("{}")
        with patch("agenticops.notify.im_config.settings", MagicMock(im_apps_config=cfg)):
            assert list_apps() == {}


# ── Channel config ──────────────────────────────────────────────────


class TestParseChannel:
    def test_basic(self):
        data = {"type": "feishu", "enabled": True, "chat_id": "c123"}
        ch = _parse_channel("test-ch", data)
        assert ch.name == "test-ch"
        assert ch.channel_type == "feishu"
        assert ch.is_enabled is True
        assert ch.config == {"chat_id": "c123"}
        assert ch.preferred_format == "markdown"

    def test_severity_filter(self):
        data = {"type": "slack", "severity_filter": ["critical", "high"]}
        ch = _parse_channel("ch", data)
        assert ch.severity_filter == ["critical", "high"]

    def test_custom_preferred_format(self):
        data = {"type": "email", "preferred_format": "text"}
        ch = _parse_channel("ch", data)
        assert ch.preferred_format == "text"

    def test_role_and_alert_senders(self):
        data = {"type": "feishu", "role": "alert", "alert_senders": ["u1", "u2"]}
        ch = _parse_channel("ch", data)
        assert ch.role == "alert"
        assert ch.alert_senders == ["u1", "u2"]

    def test_default_preferred_format_email(self):
        data = {"type": "email"}
        ch = _parse_channel("ch", data)
        assert ch.preferred_format == "html"


class TestLoadChannels:
    def test_loads_channels(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({
            "channels": {
                "ch1": {"type": "feishu", "chat_id": "c1"},
                "ch2": {"type": "slack", "chat_id": "c2"},
            }
        }))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            channels = load_channels()
            assert len(channels) == 2
            names = {c.name for c in channels}
            assert names == {"ch1", "ch2"}

    def test_skips_non_dict_entries(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"ch1": {"type": "feishu"}, "bad": "string"}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            channels = load_channels()
            assert len(channels) == 1

    def test_empty_channels(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text("{}")
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            assert load_channels() == []


class TestGetChannel:
    def test_found(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"ch1": {"type": "feishu", "chat_id": "c1"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            ch = get_channel("ch1")
            assert ch is not None
            assert ch.channel_type == "feishu"

    def test_not_found(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"ch1": {"type": "feishu"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            assert get_channel("missing") is None

    def test_non_dict_entry(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"bad": "string"}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            assert get_channel("bad") is None


class TestSaveChannel:
    def test_creates_new_file(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "sub" / "channels.yaml"
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            save_channel("ch1", "feishu", {"chat_id": "c1"})
            assert cfg.exists()
            data = yaml.safe_load(cfg.read_text())
            assert data["channels"]["ch1"]["type"] == "feishu"
            assert data["channels"]["ch1"]["chat_id"] == "c1"

    def test_updates_existing(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"ch1": {"type": "slack"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            save_channel("ch2", "feishu", {"chat_id": "c2"}, severity_filter=["critical"])
            data = yaml.safe_load(cfg.read_text())
            assert "ch1" in data["channels"]
            assert "ch2" in data["channels"]
            assert data["channels"]["ch2"]["severity_filter"] == ["critical"]

    def test_no_severity_filter(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            save_channel("ch1", "slack", {"webhook": "url"})
            data = yaml.safe_load(cfg.read_text())
            assert "severity_filter" not in data["channels"]["ch1"]


class TestDeleteChannel:
    def test_deletes_existing(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"ch1": {"type": "feishu"}, "ch2": {"type": "slack"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            result = delete_channel("ch1")
            assert result is True
            data = yaml.safe_load(cfg.read_text())
            assert "ch1" not in data["channels"]
            assert "ch2" in data["channels"]

    def test_not_found(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"ch1": {"type": "feishu"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            assert delete_channel("missing") is False

    def test_file_not_found(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "nonexistent.yaml"
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            assert delete_channel("ch1") is False


class TestFindChannelByChat:
    def test_found(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({
            "channels": {
                "ch1": {"type": "feishu", "chat_id": "c123"},
                "ch2": {"type": "slack", "chat_id": "s456"},
            }
        }))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            ch = find_channel_by_chat("feishu", "c123")
            assert ch is not None
            assert ch.name == "ch1"

    def test_not_found(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"ch1": {"type": "feishu", "chat_id": "c123"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            assert find_channel_by_chat("feishu", "wrong") is None
            assert find_channel_by_chat("slack", "c123") is None


class TestLoadChannelsRaw:
    def test_cache_hit(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "channels.yaml"
        cfg.write_text(yaml.dump({"channels": {"ch1": {"type": "feishu"}}}))
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            d1 = _load_channels_raw()
            d2 = _load_channels_raw()
            assert d1 is d2

    def test_file_not_found(self, tmp_path):
        _reset_channels_cache()
        cfg = tmp_path / "nonexistent.yaml"
        with patch("agenticops.notify.im_config.settings", MagicMock(channels_config=cfg)):
            assert _load_channels_raw() == {}
