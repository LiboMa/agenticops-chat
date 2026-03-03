"""/channel command processor — shared by CLI, Web chat, and IM chat.

All channel configuration is read from and written to channels.yaml.

Syntax:
  /channel                        List all channels
  /channel list                   List all channels
  /channel show <name>            Show channel config details
  /channel test <name>            Send test notification to a channel
  /channel set <name> <key> <val> Update a channel config field
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ChannelResult:
    success: bool
    message: str


def execute_channel(command: str) -> ChannelResult:
    """Parse and execute a /channel command.

    Args:
        command: Full command string, e.g. "/channel list" or "/channel show foo"

    Returns:
        ChannelResult with success flag and display message.
    """
    parts = command.strip().split()
    # Strip the command prefix ("/channel")
    if parts and parts[0].lower() in ("/channel", "/channels"):
        parts = parts[1:]

    sub = parts[0].lower() if parts else "list"
    args = parts[1:]

    if sub in ("list", "ls"):
        return _channel_list()
    elif sub in ("show", "get", "info"):
        if not args:
            return ChannelResult(False, "Usage: /channel show <name>")
        return _channel_show(args[0])
    elif sub == "test":
        if not args:
            return ChannelResult(False, "Usage: /channel test <name>")
        return _channel_test(args[0])
    elif sub == "set":
        if len(args) < 3:
            return ChannelResult(False, "Usage: /channel set <name> <key> <value>")
        return _channel_set(args[0], args[1], " ".join(args[2:]))
    else:
        return ChannelResult(False, _help_text())


def _help_text() -> str:
    return (
        "Channel Commands:\n"
        "  /channel list              List all channels\n"
        "  /channel show <name>       Show channel details\n"
        "  /channel test <name>       Test a channel\n"
        "  /channel set <name> <key> <value>  Update config field"
    )


def _channel_list() -> ChannelResult:
    """List all notification channels from YAML."""
    from agenticops.notify.im_config import load_channels

    channels = load_channels()

    if not channels:
        return ChannelResult(True, "No notification channels configured in channels.yaml.")

    lines = ["Notification Channels (channels.yaml):"]
    for c in channels:
        status = "ON" if c.is_enabled else "OFF"
        chat_id = c.config.get("chat_id", "")
        chat_id_display = (
            f" chat_id={chat_id[:20]}..."
            if chat_id and len(chat_id) > 20
            else f" chat_id={chat_id}" if chat_id else ""
        )
        lines.append(f"  {c.name} ({c.channel_type}) [{status}]{chat_id_display}")

    return ChannelResult(True, "\n".join(lines))


def _channel_show(name: str) -> ChannelResult:
    """Show detailed config for a channel from YAML."""
    from agenticops.notify.im_config import get_channel

    channel = get_channel(name)
    if not channel:
        return ChannelResult(False, f"Channel '{name}' not found in channels.yaml.")

    lines = [
        f"Channel: {channel.name}",
        f"  Type:     {channel.channel_type}",
        f"  Enabled:  {channel.is_enabled}",
        f"  Severity: {', '.join(channel.severity_filter) if channel.severity_filter else 'all'}",
        f"  Config:",
    ]
    for k, v in channel.config.items():
        # Mask secrets
        if any(s in k.lower() for s in ("secret", "password", "token", "key")):
            display_v = f"{str(v)[:4]}****" if v else ""
        else:
            display_v = str(v)
        lines.append(f"    {k}: {display_v}")

    return ChannelResult(True, "\n".join(lines))


def _channel_test(name: str) -> ChannelResult:
    """Send a test notification to a specific channel."""
    from agenticops.notify.notifier import NotificationManager

    try:
        manager = NotificationManager()
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(manager.send_notification(
                subject="Channel Test",
                body="Test notification from /channel test command.",
                severity="info",
                channel_names=[name],
            ))
        finally:
            loop.close()

        if not results:
            return ChannelResult(False, f"Channel '{name}' not found or disabled.")

        for ch_name, success in results.items():
            if success:
                return ChannelResult(True, f"Test notification sent to '{ch_name}' successfully.")
            else:
                return ChannelResult(False, f"Test notification to '{ch_name}' failed.")

    except Exception as e:
        return ChannelResult(False, f"Test failed: {e}")

    return ChannelResult(False, f"Channel '{name}' not found.")


def _channel_set(name: str, key: str, value: str) -> ChannelResult:
    """Update a config field on a channel in channels.yaml."""
    from agenticops.notify.im_config import get_channel, save_channel

    channel = get_channel(name)
    if not channel:
        return ChannelResult(False, f"Channel '{name}' not found in channels.yaml.")

    # Handle top-level fields
    if key == "enabled":
        is_enabled = value.lower() in ("true", "1", "on", "yes")
        save_channel(
            name=name,
            channel_type=channel.channel_type,
            config=channel.config,
            is_enabled=is_enabled,
            severity_filter=channel.severity_filter,
        )
        return ChannelResult(True, f"Channel '{name}' enabled set to {is_enabled}.")

    if key == "severity":
        severity_filter = [s.strip() for s in value.split(",") if s.strip()]
        save_channel(
            name=name,
            channel_type=channel.channel_type,
            config=channel.config,
            is_enabled=channel.is_enabled,
            severity_filter=severity_filter,
        )
        return ChannelResult(True, f"Channel '{name}' severity_filter set to {severity_filter}.")

    # Otherwise update config dict
    config = dict(channel.config)
    config[key] = value
    save_channel(
        name=name,
        channel_type=channel.channel_type,
        config=config,
        is_enabled=channel.is_enabled,
        severity_filter=channel.severity_filter,
    )

    return ChannelResult(True, f"Channel '{name}' config.{key} set to '{value}'.")
