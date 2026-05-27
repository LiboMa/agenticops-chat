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
        # Bedrock requires tool names match [a-zA-Z0-9_-]+ — sanitize prefix
        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
        prefix = f"{safe_name}_"

        try:
            # Allow per-server startup_timeout override (default 30s)
            startup_timeout = int(expanded.get("startup_timeout", 30))

            if "url" in expanded:
                # SSE transport
                from mcp.client.sse import sse_client

                client = MCPClient(
                    transport_callable=lambda url=expanded["url"], headers=expanded.get("headers", {}): sse_client(
                        url=url,
                        headers=headers,
                    ),
                    prefix=prefix,
                    startup_timeout=startup_timeout,
                )
            else:
                # Stdio transport (default)
                import shutil
                from mcp.client.stdio import stdio_client, StdioServerParameters

                # Validate command exists before attempting to spawn subprocess
                cmd = expanded["command"]
                if not shutil.which(cmd):
                    logger.warning(
                        "MCP server '%s' skipped: command '%s' not found in PATH", name, cmd
                    )
                    continue

                # Build env: start from SAFE base (not full os.environ) to avoid
                # VIRTUAL_ENV / UV_* vars causing recursive subprocess spawning.
                # MCP SDK's get_default_environment() only inherits:
                #   HOME, LOGNAME, PATH, SHELL, TERM, USER (on Unix)
                from mcp.client.stdio import get_default_environment
                project_root = str(Path(__file__).parent.parent.parent)
                server_env = get_default_environment()

                # Add AWS credential vars (needed for AWS MCP servers)
                for key in (
                    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                    "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                    "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE",
                    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
                    "AWS_EC2_METADATA_SERVICE_ENDPOINT",
                ):
                    val = os.environ.get(key)
                    if val:
                        server_env[key] = val

                # Auto-inject clean AWS config to avoid ~/.aws/config plugin issues
                clean_aws_cfg = Path(project_root) / "config" / "aws-mcp.cfg"
                if clean_aws_cfg.is_file() and "AWS_CONFIG_FILE" not in (expanded.get("env") or {}):
                    server_env["AWS_CONFIG_FILE"] = str(clean_aws_cfg)

                if expanded.get("env"):
                    for k, v in expanded["env"].items():
                        if isinstance(v, str) and v.startswith("./"):
                            v = str(Path(project_root) / v[2:])
                        server_env[k] = v

                params = StdioServerParameters(
                    command=expanded["command"],
                    args=expanded.get("args", []),
                    env=server_env,
                )
                client = MCPClient(
                    transport_callable=lambda p=params: stdio_client(p),
                    prefix=prefix,
                    startup_timeout=startup_timeout,
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


def validate_mcp_config() -> List[dict]:
    """Validate MCP server configs without starting them.

    Returns list of {name, status, error} for each server.
    """
    import shutil

    results = []
    servers = list_mcp_servers()
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            results.append({"name": name, "status": "invalid", "error": "Not a dict"})
            continue
        if cfg.get("disabled", False):
            results.append({"name": name, "status": "disabled", "error": None})
            continue

        # Check command exists
        if "url" not in cfg:
            cmd = cfg.get("command", "")
            if not cmd:
                results.append({"name": name, "status": "error", "error": "No command or url"})
                continue
            if not shutil.which(cmd):
                results.append({"name": name, "status": "error", "error": f"Command '{cmd}' not found in PATH"})
                continue

        results.append({"name": name, "status": "ok", "error": None})

    return results


def stop_mcp_clients():
    """Stop all running MCP clients. Call on shutdown."""
    for client in _mcp_clients:
        try:
            client.stop()
        except Exception:
            pass
    _mcp_clients.clear()


def reload_mcp_clients() -> List[dict]:
    """Hot-reload: validate config, stop old clients, rebuild (lazy-start).

    Returns validation results. New clients will be started by Strands Agent
    on next chat session (lazy-start pattern).
    """
    # 1. Validate before tearing down
    validation = validate_mcp_config()
    errors = [r for r in validation if r["status"] == "error"]
    if errors:
        logger.warning("MCP reload: %d server(s) have config errors", len(errors))
        # Still proceed — skip broken ones

    # 2. Stop existing clients
    stop_mcp_clients()

    # 3. Rebuild from config (lazy — no start())
    _mcp_clients.extend(_build_clients())
    logger.info("MCP reload: %d client(s) rebuilt (lazy-start on next use)", len(_mcp_clients))

    return validation
