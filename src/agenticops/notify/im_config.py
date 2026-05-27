"""IM App and notification channel configuration loader.

Loads Feishu/DingTalk/WeCom app credentials from im-apps.yaml and
notification channel definitions from channels.yaml. Both support
${VAR_NAME} env var substitution and mtime-based cache invalidation.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from agenticops.config import settings

logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# ── Mtime-based cache ──────────────────────────────────────────────

_cached_data: Optional[Dict[str, Any]] = None
_cached_mtime: float = 0.0


def _interpolate_env(value: Any) -> Any:
    """Recursively replace ${VAR} with os.environ.get(VAR, '')."""
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            var = m.group(1)
            env_val = os.environ.get(var, "")
            if not env_val:
                logger.warning("IM config: env var %s is not set", var)
            return env_val
        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


def _load_raw() -> Dict[str, Any]:
    """Load and cache the YAML config, reloading on file change."""
    global _cached_data, _cached_mtime

    config_path: Path = settings.im_apps_config
    if not config_path.exists():
        logger.debug("IM apps config not found at %s", config_path)
        return {}

    mtime = config_path.stat().st_mtime
    if _cached_data is not None and mtime == _cached_mtime:
        return _cached_data

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    _cached_data = _interpolate_env(raw)
    _cached_mtime = mtime
    logger.info("Loaded IM apps config from %s", config_path)
    return _cached_data


# ── Dataclasses ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class FeishuAppConfig:
    app_id: str
    app_secret: str
    encrypt_key: str = ""
    verification_token: str = ""


@dataclass(frozen=True)
class DingTalkAppConfig:
    app_key: str
    app_secret: str


@dataclass(frozen=True)
class WeComAppConfig:
    corp_id: str
    corp_secret: str
    agent_id: int = 0
    callback_token: str = ""
    encoding_aes_key: str = ""


@dataclass(frozen=True)
class SlackAppConfig:
    bot_token: str            # xoxb-... Bot User OAuth Token
    app_token: str            # xapp-... App-Level Token (Socket Mode)
    signing_secret: str = ""  # For HTTP Events API verification
    respond_to: str = "mentions_only"  # "mentions_only" | "all"


# ── Getters ─────────────────────────────────────────────────────────


def get_feishu_app(name: str = "default") -> Optional[FeishuAppConfig]:
    """Get a Feishu app config by name, or None if not found."""
    data = _load_raw()
    app = data.get("feishu", {}).get(name)
    if not app or not app.get("app_id"):
        return None
    return FeishuAppConfig(
        app_id=app["app_id"],
        app_secret=app.get("app_secret", ""),
        encrypt_key=app.get("encrypt_key", ""),
        verification_token=app.get("verification_token", ""),
    )


def get_dingtalk_app(name: str = "default") -> Optional[DingTalkAppConfig]:
    """Get a DingTalk app config by name, or None if not found."""
    data = _load_raw()
    app = data.get("dingtalk", {}).get(name)
    if not app or not app.get("app_key"):
        return None
    return DingTalkAppConfig(
        app_key=app["app_key"],
        app_secret=app.get("app_secret", ""),
    )


def get_wecom_app(name: str = "default") -> Optional[WeComAppConfig]:
    """Get a WeCom app config by name, or None if not found."""
    data = _load_raw()
    app = data.get("wecom", {}).get(name)
    if not app or not app.get("corp_id"):
        return None
    return WeComAppConfig(
        corp_id=app["corp_id"],
        corp_secret=app.get("corp_secret", ""),
        agent_id=int(app.get("agent_id", 0)),
        callback_token=app.get("callback_token", ""),
        encoding_aes_key=app.get("encoding_aes_key", ""),
    )


def get_slack_app(name: str = "default") -> Optional[SlackAppConfig]:
    """Get a Slack app config by name, or None if not found."""
    data = _load_raw()
    app = data.get("slack", {}).get(name)
    if not app or not app.get("bot_token"):
        return None
    return SlackAppConfig(
        bot_token=app["bot_token"],
        app_token=app.get("app_token", ""),
        signing_secret=app.get("signing_secret", ""),
        respond_to=app.get("respond_to", "mentions_only"),
    )


def list_apps() -> Dict[str, list]:
    """List all configured IM app names grouped by platform."""
    data = _load_raw()
    result: Dict[str, list] = {}
    for platform in ("feishu", "dingtalk", "wecom", "slack"):
        names = list(data.get(platform, {}).keys())
        if names:
            result[platform] = names
    return result


def get_apps_detail() -> Dict[str, Dict[str, dict]]:
    """Return all IM apps with their full config (for API masking layer)."""
    data = _load_raw()
    result: Dict[str, Dict[str, dict]] = {}
    for platform in ("feishu", "dingtalk", "wecom", "slack"):
        apps = data.get(platform, {})
        if apps:
            result[platform] = dict(apps)
    return result


def save_app(platform: str, app_name: str, config: dict) -> None:
    """Add or update an IM app in im-apps.yaml."""
    global _cached_data, _cached_mtime

    config_path: Path = settings.im_apps_config
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    if platform not in raw:
        raw[platform] = {}
    raw[platform][app_name] = config

    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Invalidate cache
    _cached_data = None
    _cached_mtime = 0.0


def delete_app(platform: str, app_name: str) -> bool:
    """Remove an IM app from im-apps.yaml. Returns True if found and removed."""
    global _cached_data, _cached_mtime

    config_path: Path = settings.im_apps_config
    if not config_path.exists():
        return False

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    if platform not in raw or app_name not in raw[platform]:
        return False

    del raw[platform][app_name]
    if not raw[platform]:
        del raw[platform]

    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    _cached_data = None
    _cached_mtime = 0.0
    return True


# ── Notification Channels (channels.yaml) ─────────────────────────

_CHANNEL_RESERVED_KEYS = frozenset(("type", "enabled", "severity_filter", "preferred_format", "role", "alert_senders"))

_DEFAULT_PREFERRED_FORMAT: Dict[str, str] = {
    "feishu": "markdown",
    "dingtalk": "markdown",
    "wecom": "markdown",
    "slack": "markdown",
    "email": "html",
    "ses": "html",
    "sns": "text",
    "sns-report": "html",
    "webhook": "markdown",
}

_channels_cache: Optional[Dict[str, Any]] = None
_channels_mtime: float = 0.0


@dataclass
class ChannelConfig:
    """A notification channel loaded from YAML."""
    name: str
    channel_type: str
    config: dict
    is_enabled: bool = True
    severity_filter: list = field(default_factory=list)
    preferred_format: str = ""
    role: str = "chat"                     # "alert" | "chat"
    alert_senders: list = field(default_factory=list)  # sender IDs that always send alerts


def _load_channels_raw() -> Dict[str, Any]:
    """Load and cache channels.yaml, reloading on file change."""
    global _channels_cache, _channels_mtime

    config_path: Path = settings.channels_config
    if not config_path.exists():
        logger.debug("Channels config not found at %s", config_path)
        return {}

    mtime = config_path.stat().st_mtime
    if _channels_cache is not None and mtime == _channels_mtime:
        return _channels_cache

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    _channels_cache = _interpolate_env(raw)
    _channels_mtime = mtime
    logger.info("Loaded channels config from %s", config_path)
    return _channels_cache


def _parse_channel(name: str, data: dict) -> ChannelConfig:
    """Parse a single channel entry from YAML into ChannelConfig."""
    channel_type = data.get("type", "")
    is_enabled = data.get("enabled", True)
    severity_filter = data.get("severity_filter", [])
    preferred_format = data.get(
        "preferred_format",
        _DEFAULT_PREFERRED_FORMAT.get(channel_type, "markdown"),
    )
    role = data.get("role", "chat")
    alert_senders = data.get("alert_senders", [])
    # Everything not in reserved keys goes into the config dict
    config = {k: v for k, v in data.items() if k not in _CHANNEL_RESERVED_KEYS}
    return ChannelConfig(
        name=name,
        channel_type=channel_type,
        config=config,
        is_enabled=bool(is_enabled),
        severity_filter=severity_filter or [],
        preferred_format=preferred_format,
        role=role,
        alert_senders=alert_senders or [],
    )


def load_channels() -> List[ChannelConfig]:
    """Load all notification channels from channels.yaml."""
    raw = _load_channels_raw()
    channels_dict = raw.get("channels", {})
    return [_parse_channel(name, data) for name, data in channels_dict.items()
            if isinstance(data, dict)]


def get_channel(name: str) -> Optional[ChannelConfig]:
    """Get a specific channel by name from channels.yaml."""
    raw = _load_channels_raw()
    data = raw.get("channels", {}).get(name)
    if not isinstance(data, dict):
        return None
    return _parse_channel(name, data)


def save_channel(name: str, channel_type: str, config: dict,
                 is_enabled: bool = True,
                 severity_filter: Optional[list] = None) -> None:
    """Add or update a channel in channels.yaml."""
    config_path: Path = settings.channels_config
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    if "channels" not in raw:
        raw["channels"] = {}

    entry: dict = {"type": channel_type, "enabled": is_enabled}
    if severity_filter:
        entry["severity_filter"] = severity_filter
    entry.update(config)

    raw["channels"][name] = entry

    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Invalidate cache
    _invalidate_channels_cache()


def delete_channel(name: str) -> bool:
    """Remove a channel from channels.yaml. Returns True if found and removed."""
    config_path: Path = settings.channels_config
    if not config_path.exists():
        return False

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    channels = raw.get("channels", {})
    if name not in channels:
        return False

    del channels[name]

    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    _invalidate_channels_cache()
    return True


def find_channel_by_chat(platform: str, chat_id: str) -> Optional[ChannelConfig]:
    """Find channel config matching a platform type and chat_id.

    Used by IM alert detection to determine if a chat is a dedicated alert channel.
    """
    for ch in load_channels():
        if ch.channel_type == platform and ch.config.get("chat_id") == chat_id:
            return ch
    return None


def _invalidate_channels_cache() -> None:
    global _channels_cache, _channels_mtime
    _channels_cache = None
    _channels_mtime = 0.0
