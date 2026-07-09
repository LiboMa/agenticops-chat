"""Tests for agenticops.tools.mcp_tools — raising coverage from 17%."""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# list_mcp_servers tool
# ---------------------------------------------------------------------------

class TestListMcpServers:
    def test_no_servers(self):
        with patch("agenticops.mcp_manager.list_mcp_servers", return_value={}):
            from agenticops.tools.mcp_tools import list_mcp_servers
            result = list_mcp_servers._tool_func()
            assert "No MCP servers configured" in result

    def test_with_servers_ok(self):
        servers = {
            "my-server": {"command": "uvx", "args": ["pkg@latest"]},
        }
        validation = [{"name": "my-server", "status": "ok", "error": None}]
        with patch("agenticops.mcp_manager.list_mcp_servers", return_value=servers):
            with patch("agenticops.mcp_manager.validate_mcp_config", return_value=validation):
                from agenticops.tools.mcp_tools import list_mcp_servers
                result = list_mcp_servers._tool_func()
                assert "my-server" in result
                assert "✓" in result
                assert "ready" in result

    def test_with_servers_disabled(self):
        servers = {
            "disabled-srv": {"command": "node", "args": ["index.js"], "disabled": True},
        }
        validation = [{"name": "disabled-srv", "status": "disabled", "error": None}]
        with patch("agenticops.mcp_manager.list_mcp_servers", return_value=servers):
            with patch("agenticops.mcp_manager.validate_mcp_config", return_value=validation):
                from agenticops.tools.mcp_tools import list_mcp_servers
                result = list_mcp_servers._tool_func()
                assert "disabled" in result

    def test_with_servers_error(self):
        servers = {
            "bad-srv": {"command": "missing-bin", "args": []},
        }
        validation = [{"name": "bad-srv", "status": "error", "error": "command not found"}]
        with patch("agenticops.mcp_manager.list_mcp_servers", return_value=servers):
            with patch("agenticops.mcp_manager.validate_mcp_config", return_value=validation):
                from agenticops.tools.mcp_tools import list_mcp_servers
                result = list_mcp_servers._tool_func()
                assert "ERROR" in result
                assert "command not found" in result

    def test_with_url_server(self):
        servers = {
            "http-srv": {"url": "http://localhost:3000"},
        }
        validation = [{"name": "http-srv", "status": "ok", "error": None}]
        with patch("agenticops.mcp_manager.list_mcp_servers", return_value=servers):
            with patch("agenticops.mcp_manager.validate_mcp_config", return_value=validation):
                from agenticops.tools.mcp_tools import list_mcp_servers
                result = list_mcp_servers._tool_func()
                assert "http://localhost:3000" in result


# ---------------------------------------------------------------------------
# validate_mcp_servers tool
# ---------------------------------------------------------------------------

class TestValidateMcpServers:
    def test_no_servers(self):
        with patch("agenticops.mcp_manager.validate_mcp_config", return_value=[]):
            from agenticops.tools.mcp_tools import validate_mcp_servers
            result = validate_mcp_servers._tool_func()
            assert "No MCP servers configured" in result

    def test_mixed_results(self):
        results = [
            {"name": "ok-srv", "status": "ok", "error": None},
            {"name": "bad-srv", "status": "error", "error": "timeout"},
            {"name": "off-srv", "status": "disabled", "error": None},
        ]
        with patch("agenticops.mcp_manager.validate_mcp_config", return_value=results):
            from agenticops.tools.mcp_tools import validate_mcp_servers
            result = validate_mcp_servers._tool_func()
            assert "1/3 servers valid" in result
            assert "✓ ok-srv" in result
            assert "✗ bad-srv" in result
            assert "○ off-srv" in result


# ---------------------------------------------------------------------------
# add_mcp_server tool
# ---------------------------------------------------------------------------

class TestAddMcpServer:
    def test_basic_add(self):
        with patch("agenticops.mcp_manager.upsert_mcp_server") as mock_upsert:
            from agenticops.tools.mcp_tools import add_mcp_server
            result = add_mcp_server._tool_func(
                name="test-srv", command="uvx", args="pkg@latest", env=""
            )
            assert "test-srv" in result
            assert "configured" in result
            mock_upsert.assert_called_once_with(
                "test-srv", {"command": "uvx", "args": ["pkg@latest"]}
            )

    def test_add_with_env(self):
        with patch("agenticops.mcp_manager.upsert_mcp_server") as mock_upsert:
            from agenticops.tools.mcp_tools import add_mcp_server
            result = add_mcp_server._tool_func(
                name="env-srv", command="node", args="server.js",
                env="AWS_REGION=us-east-1,DEBUG=true"
            )
            assert "env-srv" in result
            call_cfg = mock_upsert.call_args[0][1]
            assert call_cfg["env"] == {"AWS_REGION": "us-east-1", "DEBUG": "true"}

    def test_add_no_args(self):
        with patch("agenticops.mcp_manager.upsert_mcp_server") as mock_upsert:
            from agenticops.tools.mcp_tools import add_mcp_server
            result = add_mcp_server._tool_func(
                name="minimal", command="my-bin", args="", env=""
            )
            call_cfg = mock_upsert.call_args[0][1]
            assert "args" not in call_cfg
            assert "env" not in call_cfg


# ---------------------------------------------------------------------------
# remove_mcp_server tool
# ---------------------------------------------------------------------------

class TestRemoveMcpServer:
    def test_remove_found(self):
        with patch("agenticops.mcp_manager.delete_mcp_server", return_value=True):
            from agenticops.tools.mcp_tools import remove_mcp_server
            result = remove_mcp_server._tool_func(name="old-srv")
            assert "removed" in result

    def test_remove_not_found(self):
        with patch("agenticops.mcp_manager.delete_mcp_server", return_value=False):
            from agenticops.tools.mcp_tools import remove_mcp_server
            result = remove_mcp_server._tool_func(name="ghost")
            assert "not found" in result


# ---------------------------------------------------------------------------
# toggle_mcp_server tool
# ---------------------------------------------------------------------------

class TestToggleMcpServer:
    def test_disable(self):
        servers = {"my-srv": {"command": "uvx", "args": ["pkg"]}}
        with patch("agenticops.mcp_manager.list_mcp_servers", return_value=servers):
            with patch("agenticops.mcp_manager.upsert_mcp_server") as mock_upsert:
                from agenticops.tools.mcp_tools import toggle_mcp_server
                result = toggle_mcp_server._tool_func(name="my-srv", enabled=False)
                assert "disabled" in result
                call_cfg = mock_upsert.call_args[0][1]
                assert call_cfg["disabled"] is True

    def test_enable(self):
        servers = {"my-srv": {"command": "uvx", "args": ["pkg"], "disabled": True}}
        with patch("agenticops.mcp_manager.list_mcp_servers", return_value=servers):
            with patch("agenticops.mcp_manager.upsert_mcp_server") as mock_upsert:
                from agenticops.tools.mcp_tools import toggle_mcp_server
                result = toggle_mcp_server._tool_func(name="my-srv", enabled=True)
                assert "enabled" in result
                call_cfg = mock_upsert.call_args[0][1]
                assert call_cfg["disabled"] is False

    def test_toggle_not_found(self):
        with patch("agenticops.mcp_manager.list_mcp_servers", return_value={}):
            from agenticops.tools.mcp_tools import toggle_mcp_server
            result = toggle_mcp_server._tool_func(name="nope", enabled=True)
            assert "not found" in result


# ---------------------------------------------------------------------------
# reload_mcp_servers tool
# ---------------------------------------------------------------------------

class TestReloadMcpServers:
    def test_reload_all_ok(self):
        validation = [
            {"name": "srv1", "status": "ok", "error": None},
            {"name": "srv2", "status": "ok", "error": None},
        ]
        with patch("agenticops.mcp_manager.reload_mcp_clients", return_value=validation):
            from agenticops.tools.mcp_tools import reload_mcp_servers
            result = reload_mcp_servers._tool_func()
            assert "2 ready" in result
            assert "0 errors" in result
            assert "will be available" in result

    def test_reload_with_errors(self):
        validation = [
            {"name": "good", "status": "ok", "error": None},
            {"name": "bad", "status": "error", "error": "binary missing"},
        ]
        with patch("agenticops.mcp_manager.reload_mcp_clients", return_value=validation):
            from agenticops.tools.mcp_tools import reload_mcp_servers
            result = reload_mcp_servers._tool_func()
            assert "1 ready" in result
            assert "1 errors" in result
            assert "binary missing" in result

    def test_reload_empty(self):
        with patch("agenticops.mcp_manager.reload_mcp_clients", return_value=[]):
            from agenticops.tools.mcp_tools import reload_mcp_servers
            result = reload_mcp_servers._tool_func()
            assert "0 ready" in result
