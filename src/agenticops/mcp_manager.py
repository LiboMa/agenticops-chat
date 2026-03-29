"""MCP (Model Context Protocol) client management.

Supports the standard mcpServers JSON format (same as Claude Desktop / Cursor):

    {
      "mcpServers": {
        "server-name": {
          "command": "uvx",
          "args": ["package@latest"],
          "env": { "KEY": "val" },
          "disabled": false,
          "autoApprove": []
        }
      }
    }

Config is stored at config/mcp-servers.json (configurable via AIOPS_MCP_SERVERS_CONFIG).
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from strands.tools.mcp import MCPClient

from agenticops.config import settings

logger = logging.getLogger(__name__)

_mcp_clients: List[MCPClient] = []


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    return settings.mcp_servers_config


def _read_config() -> Dict[str, Any]:
    """Read mcpServers config, return the full dict."""
    path = _config_path()
    if not path.exists():
        return {"mcpServers": {}}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        logger.error("Failed to load MCP config from %s: %s", path, e)
        return {"mcpServers": {}}
    if "mcpServers" not in data:
        data["mcpServers"] = {}
    return data


def _write_config(data: Dict[str, Any]) -> None:
    """Persist mcpServers config to disk."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _expand_env(value: Any) -> Any:
    """Recursively expand ${VAR} references in strings."""
    if isinstance(value, str):
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            value,
        )
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# CRUD helpers (used by web API)
# ---------------------------------------------------------------------------

def list_mcp_servers() -> Dict[str, Any]:
    """Return all configured MCP servers as {name: config} dict."""
    return _read_config().get("mcpServers", {})


def get_mcp_server(name: str) -> Optional[Dict[str, Any]]:
    """Return config for a single MCP server, or None."""
    return list_mcp_servers().get(name)


def upsert_mcp_server(name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update an MCP server config. Returns the saved config."""
    data = _read_config()
    data["mcpServers"][name] = cfg
    _write_config(data)
    return cfg


def delete_mcp_server(name: str) -> bool:
    """Delete an MCP server config. Returns True if it existed."""
    data = _read_config()
    if name not in data.get("mcpServers", {}):
        return False
    del data["mcpServers"][name]
    _write_config(data)
    return True


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------

def _build_clients() -> List[MCPClient]:
    """Build MCPClient instances from current config (does not start them)."""
    clients: List[MCPClient] = []
    servers = list_mcp_servers()

    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("disabled", False):
            logger.info("MCP server '%s' disabled, skipping", name)
            continue

        expanded = _expand_env(cfg)
        prefix = f"{name}_"

        try:
            if "url" in expanded:
                # SSE transport
                from mcp.client.sse import sse_client

                client = MCPClient(
                    transport_callable=lambda url=expanded["url"], headers=expanded.get("headers", {}): sse_client(
                        url=url,
                        headers=headers,
                    ),
                    prefix=prefix,
                )
            else:
                # Stdio transport (default)
                from mcp.client.stdio import stdio_client, StdioServerParameters

                params = StdioServerParameters(
                    command=expanded["command"],
                    args=expanded.get("args", []),
                    env={**os.environ, **expanded["env"]} if expanded.get("env") else None,
                )
                client = MCPClient(
                    transport_callable=lambda p=params: stdio_client(p),
                    prefix=prefix,
                )

            clients.append(client)
            logger.info("MCP server '%s' configured (prefix=%s)", name, prefix)
        except Exception as e:
            logger.error("Failed to create MCP client '%s': %s", name, e)

    return clients


def get_mcp_clients() -> List[MCPClient]:
    """Return cached MCP clients, building from config on first call."""
    if not _mcp_clients:
        _mcp_clients.extend(_build_clients())
    return _mcp_clients


def start_mcp_clients() -> List[MCPClient]:
    """Start all configured MCP clients. Call before creating agents."""
    clients = get_mcp_clients()
    started = 0
    for client in clients:
        try:
            client.start()
            started += 1
        except Exception as e:
            logger.error("Failed to start MCP client: %s", e)
    if started:
        logger.info("Started %d/%d MCP clients", started, len(clients))
    return clients


def stop_mcp_clients():
    """Stop all running MCP clients. Call on shutdown."""
    for client in _mcp_clients:
        try:
            client.stop()
        except Exception:
            pass
    _mcp_clients.clear()


def reload_mcp_clients() -> List[MCPClient]:
    """Stop existing clients, rebuild from config, and start."""
    stop_mcp_clients()
    return start_mcp_clients()
