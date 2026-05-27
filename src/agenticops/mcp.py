"""Backward-compat shim — re-exports from mcp_manager."""
from agenticops.mcp_manager import *  # noqa: F401,F403
from agenticops.mcp_manager import (  # noqa: F401
    _config_path,
    _read_config,
    _write_config,
    _expand_env,
    _build_clients,
    _mcp_clients,
)
