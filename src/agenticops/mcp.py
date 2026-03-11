"""MCP (Model Context Protocol) client management.

Loads MCP server configs from config/mcp-servers.yaml and creates MCPClient
instances that can be passed as ToolProviders to any Strands Agent.
"""

import logging
import os
import re
from typing import List

import yaml
from strands.tools.mcp import MCPClient

from agenticops.config import settings

logger = logging.getLogger(__name__)

_mcp_clients: List[MCPClient] = []


def _expand_env(value):
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


def get_mcp_clients() -> List[MCPClient]:
    """Return cached MCP clients, initializing from YAML on first call."""
    if _mcp_clients:
        return _mcp_clients

    config_path = settings.mcp_servers_config
    if not config_path.exists():
        return []

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
    except Exception as e:
        logger.error("Failed to load MCP config from %s: %s", config_path, e)
        return []

    servers = data.get("servers") or {}
    if not isinstance(servers, dict):
        logger.error("MCP config 'servers' must be a mapping, got %s", type(servers).__name__)
        return []

    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            logger.info("MCP server '%s' disabled, skipping", name)
            continue

        cfg = _expand_env(cfg)
        transport = cfg.get("transport", "stdio")
        use_prefix = cfg.get("prefix", True)
        prefix = f"{name}_" if use_prefix else None

        try:
            if transport == "sse":
                from mcp.client.sse import sse_client

                client = MCPClient(
                    transport_callable=lambda url=cfg["url"], headers=cfg.get("headers", {}): sse_client(
                        url=url,
                        headers=headers,
                    ),
                    prefix=prefix,
                )
            else:
                from mcp.client.stdio import stdio_client, StdioServerParameters

                params = StdioServerParameters(
                    command=cfg["command"],
                    args=cfg.get("args", []),
                    env={**os.environ, **cfg["env"]} if cfg.get("env") else None,
                )
                client = MCPClient(
                    transport_callable=lambda p=params: stdio_client(p),
                    prefix=prefix,
                )

            _mcp_clients.append(client)
            logger.info("MCP server '%s' configured (%s)", name, transport)
        except Exception as e:
            logger.error("Failed to create MCP client '%s': %s", name, e)

    return _mcp_clients


def start_mcp_clients() -> List[MCPClient]:
    """Start all configured MCP clients. Call before creating agents."""
    clients = get_mcp_clients()
    for client in clients:
        try:
            client.start()
        except Exception as e:
            logger.error("Failed to start MCP client: %s", e)
    return clients


def stop_mcp_clients():
    """Stop all running MCP clients. Call on shutdown."""
    for client in _mcp_clients:
        try:
            client.stop()
        except Exception:
            pass
    _mcp_clients.clear()
