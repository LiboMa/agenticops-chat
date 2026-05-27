"""MCP Server management tools — Agent-facing tools for Chat/CLI.

Allows agents to list, validate, add, remove, and reload MCP servers
through natural language in Chat, similar to Skill management tools.
"""

from __future__ import annotations

import logging
from strands import tool

logger = logging.getLogger(__name__)


@tool
def list_mcp_servers() -> str:
    """List all configured MCP servers with their status.

    Returns:
        Formatted list of MCP servers with name, command, status (ok/disabled/error).
    """
    from agenticops.mcp_manager import list_mcp_servers as _list, validate_mcp_config

    servers = _list()
    if not servers:
        return "No MCP servers configured. Use add_mcp_server() to add one."

    validation = validate_mcp_config()
    status_map = {r["name"]: r for r in validation}

    lines = [f"MCP Servers ({len(servers)}):"]
    for name, cfg in servers.items():
        v = status_map.get(name, {"status": "unknown", "error": None})
        status = v["status"]
        disabled = cfg.get("disabled", False)
        cmd = cfg.get("command", cfg.get("url", "?"))
        args = " ".join(cfg.get("args", []))

        status_icon = {"ok": "✓", "disabled": "○", "error": "✗"}.get(status, "?")
        lines.append(f"\n  {status_icon} {name}")
        lines.append(f"    Command: {cmd} {args}")
        if disabled:
            lines.append("    Status: disabled")
        elif v.get("error"):
            lines.append(f"    Status: ERROR — {v['error']}")
        else:
            lines.append("    Status: ready")

    lines.append("\nUse validate_mcp_servers() to check connectivity.")
    return "\n".join(lines)


@tool
def validate_mcp_servers() -> str:
    """Validate all MCP server configurations (checks command exists, config format).

    Returns:
        Validation results for each server.
    """
    from agenticops.mcp_manager import validate_mcp_config

    results = validate_mcp_config()
    if not results:
        return "No MCP servers configured."

    lines = ["MCP Server Validation:"]
    ok_count = 0
    for r in results:
        if r["status"] == "ok":
            lines.append(f"  ✓ {r['name']} — OK")
            ok_count += 1
        elif r["status"] == "disabled":
            lines.append(f"  ○ {r['name']} — disabled (skipped)")
        else:
            lines.append(f"  ✗ {r['name']} — {r['error']}")

    lines.append(f"\nResult: {ok_count}/{len(results)} servers valid.")
    return "\n".join(lines)


@tool
def add_mcp_server(
    name: str,
    command: str,
    args: str = "",
    env: str = "",
) -> str:
    """Add or update an MCP server configuration.

    Args:
        name: Server name (e.g., 'awslabs.aws-documentation-mcp-server').
        command: Command to run (e.g., 'uvx', 'npx', 'node').
        args: Space-separated arguments (e.g., 'awslabs.aws-documentation-mcp-server@latest').
        env: Comma-separated KEY=VALUE pairs (e.g., 'AWS_REGION=us-east-1,FASTMCP_LOG_LEVEL=ERROR').

    Returns:
        Confirmation of server addition.
    """
    from agenticops.mcp_manager import upsert_mcp_server

    cfg: dict = {"command": command}
    if args:
        cfg["args"] = args.split()
    if env:
        env_dict = {}
        for pair in env.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                env_dict[k.strip()] = v.strip()
        if env_dict:
            cfg["env"] = env_dict

    upsert_mcp_server(name, cfg)
    return (
        f"MCP server '{name}' configured.\n"
        f"  Command: {command} {args}\n"
        f"Use reload_mcp_servers() to activate, or it will auto-start on next chat."
    )


@tool
def remove_mcp_server(name: str) -> str:
    """Remove an MCP server configuration.

    Args:
        name: Server name to remove.

    Returns:
        Confirmation of removal.
    """
    from agenticops.mcp_manager import delete_mcp_server

    if delete_mcp_server(name):
        return f"MCP server '{name}' removed. Use reload_mcp_servers() to apply."
    return f"MCP server '{name}' not found."


@tool
def toggle_mcp_server(name: str, enabled: bool) -> str:
    """Enable or disable an MCP server without removing it.

    Args:
        name: Server name.
        enabled: True to enable, False to disable.

    Returns:
        Confirmation of the change.
    """
    from agenticops.mcp_manager import list_mcp_servers as _list, upsert_mcp_server

    servers = _list()
    if name not in servers:
        return f"MCP server '{name}' not found."

    cfg = dict(servers[name])
    cfg["disabled"] = not enabled
    upsert_mcp_server(name, cfg)
    action = "enabled" if enabled else "disabled"
    return f"MCP server '{name}' {action}. Use reload_mcp_servers() to apply."


@tool
def reload_mcp_servers() -> str:
    """Hot-reload MCP servers: validate config, stop old clients, rebuild.

    New servers will auto-start on the next chat message.

    Returns:
        Reload results with validation status for each server.
    """
    from agenticops.mcp_manager import reload_mcp_clients

    validation = reload_mcp_clients()
    ok_count = sum(1 for r in validation if r["status"] == "ok")
    err_count = sum(1 for r in validation if r["status"] == "error")

    lines = [f"MCP reload complete: {ok_count} ready, {err_count} errors."]
    for r in validation:
        if r["status"] == "error":
            lines.append(f"  ✗ {r['name']}: {r['error']}")
        elif r["status"] == "ok":
            lines.append(f"  ✓ {r['name']}: ready (will start on next chat)")

    if ok_count:
        lines.append("\nMCP tools will be available on the next message.")
    return "\n".join(lines)
