"""Tests for agenticops.mcp_manager — boosting from 41% coverage."""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from agenticops.mcp_manager import (
    _read_config,
    _write_config,
    _expand_env,
    list_mcp_servers,
    get_mcp_server,
    upsert_mcp_server,
    delete_mcp_server,
    _build_clients,
    get_mcp_clients,
    stop_mcp_clients,
    _mcp_clients,
)


# ---------------------------------------------------------------------------
# _expand_env
# ---------------------------------------------------------------------------

class TestExpandEnv:
    def test_string_expansion(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "secret123")
        assert _expand_env("Bearer ${MY_TOKEN}") == "Bearer secret123"

    def test_missing_var_kept(self):
        result = _expand_env("${NONEXISTENT_VAR_12345}")
        assert result == "${NONEXISTENT_VAR_12345}"

    def test_dict_expansion(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        result = _expand_env({"url": "http://${HOST}:8080", "key": "static"})
        assert result == {"url": "http://localhost:8080", "key": "static"}

    def test_list_expansion(self, monkeypatch):
        monkeypatch.setenv("ARG1", "hello")
        result = _expand_env(["${ARG1}", "world"])
        assert result == ["hello", "world"]

    def test_non_string_passthrough(self):
        assert _expand_env(42) == 42
        assert _expand_env(True) is True
        assert _expand_env(None) is None


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------

class TestConfigIO:
    def test_read_config_missing_file(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "nonexistent.json"
        mock_settings = MagicMock()
        mock_settings.mcp_servers_config = fake_path
        monkeypatch.setattr("agenticops.mcp_manager.settings", mock_settings)

        result = _read_config()
        assert result == {"mcpServers": {}}

    def test_read_config_valid(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(json.dumps({"mcpServers": {"test": {"command": "echo"}}}))

        mock_settings = MagicMock()
        mock_settings.mcp_servers_config = cfg_file
        monkeypatch.setattr("agenticops.mcp_manager.settings", mock_settings)

        result = _read_config()
        assert "test" in result["mcpServers"]

    def test_read_config_empty_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text("")

        mock_settings = MagicMock()
        mock_settings.mcp_servers_config = cfg_file
        monkeypatch.setattr("agenticops.mcp_manager.settings", mock_settings)

        result = _read_config()
        assert result == {"mcpServers": {}}

    def test_read_config_invalid_json(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text("not json {{{")

        mock_settings = MagicMock()
        mock_settings.mcp_servers_config = cfg_file
        monkeypatch.setattr("agenticops.mcp_manager.settings", mock_settings)

        result = _read_config()
        assert result == {"mcpServers": {}}

    def test_read_config_no_mcpservers_key(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(json.dumps({"other": "data"}))

        mock_settings = MagicMock()
        mock_settings.mcp_servers_config = cfg_file
        monkeypatch.setattr("agenticops.mcp_manager.settings", mock_settings)

        result = _read_config()
        assert "mcpServers" in result

    def test_write_config(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "subdir" / "mcp.json"

        mock_settings = MagicMock()
        mock_settings.mcp_servers_config = cfg_file
        monkeypatch.setattr("agenticops.mcp_manager.settings", mock_settings)

        _write_config({"mcpServers": {"s1": {"command": "test"}}})
        assert cfg_file.exists()
        data = json.loads(cfg_file.read_text())
        assert data["mcpServers"]["s1"]["command"] == "test"


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

class TestCRUD:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.cfg_file = tmp_path / "mcp.json"
        self.cfg_file.write_text(json.dumps({
            "mcpServers": {
                "existing": {"command": "echo", "args": ["hello"]}
            }
        }))
        mock_settings = MagicMock()
        mock_settings.mcp_servers_config = self.cfg_file
        monkeypatch.setattr("agenticops.mcp_manager.settings", mock_settings)

    def test_list_mcp_servers(self):
        servers = list_mcp_servers()
        assert "existing" in servers

    def test_get_mcp_server_found(self):
        cfg = get_mcp_server("existing")
        assert cfg is not None
        assert cfg["command"] == "echo"

    def test_get_mcp_server_not_found(self):
        assert get_mcp_server("nope") is None

    def test_upsert_new(self):
        upsert_mcp_server("new_server", {"command": "node", "args": ["server.js"]})
        assert get_mcp_server("new_server") is not None

    def test_upsert_existing(self):
        upsert_mcp_server("existing", {"command": "python", "args": ["-m", "server"]})
        cfg = get_mcp_server("existing")
        assert cfg["command"] == "python"

    def test_delete_existing(self):
        assert delete_mcp_server("existing") is True
        assert get_mcp_server("existing") is None

    def test_delete_nonexistent(self):
        assert delete_mcp_server("nope") is False


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------

class TestBuildClients:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.cfg_file = tmp_path / "mcp.json"
        mock_settings = MagicMock()
        mock_settings.mcp_servers_config = self.cfg_file
        monkeypatch.setattr("agenticops.mcp_manager.settings", mock_settings)

    def test_empty_config(self):
        self.cfg_file.write_text(json.dumps({"mcpServers": {}}))
        clients = _build_clients()
        assert clients == []

    def test_disabled_server_skipped(self):
        self.cfg_file.write_text(json.dumps({
            "mcpServers": {"disabled_one": {"command": "echo", "disabled": True}}
        }))
        clients = _build_clients()
        assert len(clients) == 0

    def test_non_dict_config_skipped(self):
        self.cfg_file.write_text(json.dumps({
            "mcpServers": {"bad": "not-a-dict"}
        }))
        clients = _build_clients()
        assert len(clients) == 0

    def test_stdio_server_created(self):
        self.cfg_file.write_text(json.dumps({
            "mcpServers": {"my_server": {"command": "echo", "args": ["hi"]}}
        }))
        with patch("agenticops.mcp_manager.MCPClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            clients = _build_clients()
            assert len(clients) == 1

    def test_sse_server_created(self):
        self.cfg_file.write_text(json.dumps({
            "mcpServers": {"sse_server": {"url": "http://localhost:8080/sse"}}
        }))
        with patch("agenticops.mcp_manager.MCPClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            clients = _build_clients()
            assert len(clients) == 1

    def test_server_with_env(self):
        self.cfg_file.write_text(json.dumps({
            "mcpServers": {"env_server": {"command": "node", "env": {"KEY": "val"}}}
        }))
        with patch("agenticops.mcp_manager.MCPClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            clients = _build_clients()
            assert len(clients) == 1

    def test_creation_error_handled(self):
        self.cfg_file.write_text(json.dumps({
            "mcpServers": {"bad_server": {"command": "echo"}}
        }))
        with patch("agenticops.mcp_manager.MCPClient", side_effect=Exception("fail")):
            clients = _build_clients()
            assert len(clients) == 0


class TestStopClients:
    def test_stop_clears_list(self):
        import agenticops.mcp_manager as mcp_mod
        mock_client = MagicMock()
        mcp_mod._mcp_clients.clear()
        mcp_mod._mcp_clients.append(mock_client)

        stop_mcp_clients()
        assert len(mcp_mod._mcp_clients) == 0
        mock_client.stop.assert_called_once()

    def test_stop_handles_exception(self):
        import agenticops.mcp_manager as mcp_mod
        mock_client = MagicMock()
        mock_client.stop.side_effect = RuntimeError("stop failed")
        mcp_mod._mcp_clients.clear()
        mcp_mod._mcp_clients.append(mock_client)

        stop_mcp_clients()  # should not raise
        assert len(mcp_mod._mcp_clients) == 0
