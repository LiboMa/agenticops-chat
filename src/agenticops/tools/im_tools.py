"""IM and Notification Channel management tools — Chat/CLI interface.

Allows users to manage IM bot apps, notification channels, and WebSocket
connections through natural language. Supports JSON import for bulk config.
"""

from __future__ import annotations

import json
import logging
from strands import tool

logger = logging.getLogger(__name__)


def _mask_secret(value: str) -> str:
    """Mask sensitive values: show last 4 chars only."""
    if not value or len(value) < 8:
        return "****"
    return f"****{value[-4:]}"


@tool
def list_im_channels() -> str:
    """List all notification channels with their type, status, and role.

    Returns:
        Formatted list of channels from channels.yaml.
    """
    from agenticops.notify.im_config import load_channels

    channels = load_channels()
    if not channels:
        return "No channels configured. Use add_im_channel() to add one."

    lines = [f"Notification Channels ({len(channels)}):"]
    for c in channels:
        status = "enabled" if c.is_enabled else "disabled"
        icon = "✓" if c.is_enabled else "○"
        lines.append(f"\n  {icon} {c.name}")
        lines.append(f"    Type: {c.channel_type} | Status: {status} | Role: {c.role}")
        # Show non-sensitive config
        safe_keys = {k: v for k, v in c.config.items()
                     if "token" not in k.lower() and "secret" not in k.lower() and "key" not in k.lower()}
        if safe_keys:
            details = ", ".join(f"{k}={v}" for k, v in list(safe_keys.items())[:4])
            lines.append(f"    Config: {details}")

    return "\n".join(lines)


@tool
def add_im_channel(
    name: str,
    channel_type: str,
    config_json: str = "{}",
    enabled: bool = True,
    role: str = "chat",
) -> str:
    """Add or update a notification channel.

    Args:
        name: Channel name (e.g., 'feishu-ops', 'slack-alerts', 'email-team').
        channel_type: Type — feishu, slack, dingtalk, wecom, email, ses, sns, sns-report, webhook.
        config_json: JSON object with channel-specific config (chat_id, topic_arn, webhook_url, etc.).
        enabled: Whether the channel is active.
        role: Channel role — 'chat' (default) or 'alert'.

    Returns:
        Confirmation of channel creation/update.
    """
    from agenticops.notify.im_config import save_channel

    valid_types = {"feishu", "slack", "dingtalk", "wecom", "email", "ses", "sns", "sns-report", "webhook"}
    if channel_type not in valid_types:
        return f"Invalid channel_type '{channel_type}'. Valid: {', '.join(sorted(valid_types))}"

    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except json.JSONDecodeError as e:
        return f"Invalid config_json: {e}"

    save_channel(name, channel_type, config, is_enabled=enabled)
    return f"Channel '{name}' ({channel_type}) {'created' if enabled else 'created (disabled)'}. Role: {role}."


@tool
def remove_im_channel(name: str) -> str:
    """Remove a notification channel.

    Args:
        name: Channel name to remove.

    Returns:
        Confirmation.
    """
    from agenticops.notify.im_config import delete_channel

    if delete_channel(name):
        return f"Channel '{name}' removed."
    return f"Channel '{name}' not found."


@tool
def toggle_im_channel(name: str, enabled: bool) -> str:
    """Enable or disable a notification channel.

    Args:
        name: Channel name.
        enabled: True to enable, False to disable.

    Returns:
        Confirmation.
    """
    from agenticops.notify.im_config import load_channels, save_channel

    channels = load_channels()
    ch = next((c for c in channels if c.name == name), None)
    if not ch:
        return f"Channel '{name}' not found."

    save_channel(name, ch.channel_type, ch.config, is_enabled=enabled)
    action = "enabled" if enabled else "disabled"
    return f"Channel '{name}' {action}."


@tool
def list_im_apps() -> str:
    """List configured IM bot apps (Feishu/Slack/DingTalk/WeCom) with masked credentials.

    Returns:
        List of apps by platform with masked secrets.
    """
    from agenticops.notify.im_config import list_apps, _load_raw

    apps = list_apps()
    if not apps:
        return "No IM apps configured. Use set_im_app() to add one."

    raw = _load_raw()
    lines = ["IM Bot Apps:"]
    for platform, names in apps.items():
        for app_name in names:
            app_cfg = raw.get(platform, {}).get(app_name, {})
            masked = {}
            for k, v in app_cfg.items():
                if any(s in k.lower() for s in ("token", "secret", "key", "password")):
                    masked[k] = _mask_secret(str(v))
                else:
                    masked[k] = v
            details = ", ".join(f"{k}={v}" for k, v in masked.items())
            lines.append(f"\n  {platform}/{app_name}")
            lines.append(f"    {details}")

    return "\n".join(lines)


@tool
def set_im_app(
    platform: str,
    app_name: str,
    config_json: str,
) -> str:
    """Add or update an IM bot app credential.

    Sensitive values (tokens, secrets) are stored but never shown back in full.

    Args:
        platform: One of feishu, slack, dingtalk, wecom.
        app_name: App identifier (e.g., 'default', 'prod-bot').
        config_json: JSON object with app credentials (app_id, app_secret, bot_token, etc.).

    Returns:
        Confirmation (credentials masked).
    """
    import yaml
    from agenticops.config import settings
    from agenticops.notify.im_config import _cached_data

    valid_platforms = {"feishu", "slack", "dingtalk", "wecom"}
    if platform not in valid_platforms:
        return f"Invalid platform '{platform}'. Valid: {', '.join(sorted(valid_platforms))}"

    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except json.JSONDecodeError as e:
        return f"Invalid config_json: {e}"

    config_path = settings.im_apps_config
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
    import agenticops.notify.im_config as _imc
    _imc._cached_data = None
    _imc._cached_mtime = 0.0

    # Show masked confirmation
    masked = {k: _mask_secret(str(v)) if any(s in k.lower() for s in ("token", "secret", "key")) else v
              for k, v in config.items()}
    return f"IM app '{platform}/{app_name}' saved. Config: {masked}"


@tool
def import_im_config(config_json: str) -> str:
    """Bulk import IM channels and/or apps from a JSON blob.

    Accepts format:
    {
      "channels": {"name": {"type": "feishu", "chat_id": "...", ...}},
      "apps": {"feishu": {"default": {"app_id": "...", "app_secret": "..."}}}
    }

    Args:
        config_json: JSON string with channels and/or apps to import.

    Returns:
        Import summary.
    """
    try:
        data = json.loads(config_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    imported_channels = 0
    imported_apps = 0

    # Import channels
    if "channels" in data:
        from agenticops.notify.im_config import save_channel
        for name, cfg in data["channels"].items():
            ch_type = cfg.pop("type", "")
            enabled = cfg.pop("enabled", True)
            if ch_type:
                save_channel(name, ch_type, cfg, is_enabled=enabled)
                imported_channels += 1

    # Import apps
    if "apps" in data:
        import yaml
        from agenticops.config import settings
        config_path = settings.im_apps_config
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        for platform, apps in data["apps"].items():
            if platform not in raw:
                raw[platform] = {}
            for app_name, app_cfg in apps.items():
                raw[platform][app_name] = app_cfg
                imported_apps += 1

        with open(config_path, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return f"Imported {imported_channels} channels, {imported_apps} apps."
