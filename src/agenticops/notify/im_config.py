"""IM App configuration loader — YAML with environment variable interpolation.

Loads Feishu/DingTalk/WeCom app credentials from a YAML file, with automatic
${VAR_NAME} env var substitution and mtime-based cache invalidation.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

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


def get_channel_chat_id(platform: str, app_name: str, channel_name: str) -> Optional[str]:
    """Resolve a channel's chat_id from YAML config. Returns None if not found."""
    data = _load_raw()
    app = data.get(platform, {}).get(app_name, {})
    return app.get("channels", {}).get(channel_name)


def list_apps() -> Dict[str, list]:
    """List all configured IM app names grouped by platform."""
    data = _load_raw()
    result: Dict[str, list] = {}
    for platform in ("feishu", "dingtalk", "wecom"):
        names = list(data.get(platform, {}).keys())
        if names:
            result[platform] = names
    return result
