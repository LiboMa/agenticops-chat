"""Unit tests for agenticops.tools.file_tools module.

Covers: read_local_file, tail_local_file, search_local_file,
list_local_directory, file_stat, write_local_file, _is_blocked, _truncate.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agenticops.tools.file_tools import (
    _is_blocked,
    _truncate,
    MAX_RESULT_CHARS,
    MAX_LIST_RESULT_CHARS,
    MAX_WRITE_BYTES,
)


# ── _truncate tests ──────────────────────────────────────────────────


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_exact_limit_unchanged(self):
        text = "a" * 100
        assert _truncate(text, 100) == text

    def test_over_limit_truncated(self):
        text = "a" * 200
        result = _truncate(text, 100)
        assert len(result) > 100  # includes suffix
        assert "truncated" in result

    def test_default_limit(self):
        text = "x" * (MAX_RESULT_CHARS + 100)
        result = _truncate(text)
        assert result.startswith("x" * MAX_RESULT_CHARS)
        assert "truncated" in result


# ── _is_blocked tests ────────────────────────────────────────────────


class TestIsBlocked:
    """Test security blocklist logic."""

    def test_normal_path_allowed(self, tmp_path):
        f = tmp_path / "readme.txt"
        f.touch()
        assert _is_blocked(str(f)) is None

    def test_system_shadow_always_blocked(self):
        assert _is_blocked("/etc/shadow") is not None

    def test_system_gshadow_always_blocked(self):
        assert _is_blocked("/etc/gshadow") is not None

    def test_system_sudoers_blocked(self):
        assert _is_blocked("/etc/sudoers") is not None

    def test_gnupg_blocked(self):
        assert _is_blocked("/home/user/.gnupg/secring.gpg") is not None

    def test_docker_config_blocked(self):
        assert _is_blocked("/home/user/.docker/config.json") is not None

    def test_env_file_blocked(self):
        assert _is_blocked("/app/.env") is not None

    def test_env_production_blocked(self):
        assert _is_blocked("/app/.env.production") is not None

    def test_credentials_json_blocked(self):
        assert _is_blocked("/app/credentials.json") is not None

    def test_secrets_yaml_blocked(self):
        assert _is_blocked("/app/secrets.yaml") is not None

    def test_p12_extension_blocked(self):
        assert _is_blocked("/certs/server.p12") is not None

    def test_pfx_extension_blocked(self):
        assert _is_blocked("/certs/server.pfx") is not None

    def test_jks_extension_blocked(self):
        assert _is_blocked("/certs/keystore.jks") is not None

    @patch("agenticops.tools.file_tools.settings")
    def test_ssh_key_blocked_no_admin(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        result = _is_blocked("/home/user/.ssh/id_rsa")
        assert result is not None
        assert "AIOPS_FILE_TOOLS_ADMIN_MODE" in result

    @patch("agenticops.tools.file_tools.settings")
    def test_ssh_key_allowed_admin_mode(self, mock_settings):
        mock_settings.file_tools_admin_mode = True
        # .ssh path is admin-gated but id_rsa filename is also admin-gated
        result = _is_blocked("/home/user/.ssh/config_backup")
        assert result is None

    @patch("agenticops.tools.file_tools.settings")
    def test_aws_credentials_blocked_no_admin(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        result = _is_blocked("/home/user/.aws/credentials")
        assert result is not None

    @patch("agenticops.tools.file_tools.settings")
    def test_aws_credentials_allowed_admin(self, mock_settings):
        mock_settings.file_tools_admin_mode = True
        # The filename "credentials" is in _SYSTEM_FILENAMES → always blocked
        result = _is_blocked("/home/user/.aws/credentials")
        assert result is not None  # system filename block overrides admin

    @patch("agenticops.tools.file_tools.settings")
    def test_pem_blocked_no_admin(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        result = _is_blocked("/certs/server.pem")
        assert result is not None

    @patch("agenticops.tools.file_tools.settings")
    def test_pem_allowed_admin(self, mock_settings):
        mock_settings.file_tools_admin_mode = True
        result = _is_blocked("/certs/server.pem")
        assert result is None

    @patch("agenticops.tools.file_tools.settings")
    def test_kube_config_blocked_no_admin(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        result = _is_blocked("/home/user/.kube/config")
        assert result is not None


# ── read_local_file tests ────────────────────────────────────────────


class TestReadLocalFile:
    """Test read_local_file tool function."""

    def _call(self, **kwargs):
        from agenticops.tools.file_tools import read_local_file
        return read_local_file._tool_func(**kwargs)

    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = self._call(path=str(f))
        assert "line1" in result
        assert "line2" in result
        assert "3 lines total" in result

    def test_read_with_offset(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd\ne\n")
        result = self._call(path=str(f), offset=2, limit=2)
        assert "showing 3-4" in result

    def test_read_nonexistent(self, tmp_path):
        result = self._call(path=str(tmp_path / "nope.txt"))
        assert "not found" in result.lower()

    def test_read_directory_error(self, tmp_path):
        result = self._call(path=str(tmp_path))
        assert "Not a file" in result

    @patch("agenticops.tools.file_tools.settings")
    def test_read_blocked_file(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        result = self._call(path="/etc/shadow")
        assert "ACCESS DENIED" in result

    def test_read_large_file_rejected(self, tmp_path):
        """Files > 10MB should be rejected."""
        f = tmp_path / "big.txt"
        f.write_text("x")
        mock_path = patch("agenticops.tools.file_tools.Path.resolve")
        with mock_path as mr:
            from unittest.mock import MagicMock as MM
            resolved = MM()
            resolved.exists.return_value = True
            resolved.is_file.return_value = True
            resolved.stat.return_value.st_size = 11 * 1024 * 1024
            mr.return_value = resolved
            result = self._call(path=str(f))
        assert "too large" in result.lower()

    def test_read_binary_file(self, tmp_path):
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02" * 100)
        # This will be read with errors="replace", so no UnicodeDecodeError
        result = self._call(path=str(f))
        assert "line" in result.lower() or "1 lines" in result


# ── tail_local_file tests ────────────────────────────────────────────


class TestTailLocalFile:
    def _call(self, **kwargs):
        from agenticops.tools.file_tools import tail_local_file
        return tail_local_file._tool_func(**kwargs)

    def test_tail_last_lines(self, tmp_path):
        f = tmp_path / "log.txt"
        lines = [f"line{i}\n" for i in range(100)]
        f.write_text("".join(lines))
        result = self._call(path=str(f), lines=5)
        assert "last 5 of 100" in result
        assert "line99" in result
        assert "line95" in result

    def test_tail_more_than_file(self, tmp_path):
        f = tmp_path / "short.txt"
        f.write_text("a\nb\n")
        result = self._call(path=str(f), lines=100)
        assert "last 2 of 2" in result

    def test_tail_nonexistent(self, tmp_path):
        result = self._call(path=str(tmp_path / "nope.log"))
        assert "not found" in result.lower()

    def test_tail_directory(self, tmp_path):
        result = self._call(path=str(tmp_path))
        assert "Not a file" in result

    @patch("agenticops.tools.file_tools.settings")
    def test_tail_blocked(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        result = self._call(path="/etc/shadow")
        assert "ACCESS DENIED" in result


# ── search_local_file tests ──────────────────────────────────────────


class TestSearchLocalFile:
    def _call(self, **kwargs):
        from agenticops.tools.file_tools import search_local_file
        return search_local_file._tool_func(**kwargs)

    def test_search_finds_matches(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("host: localhost\nport: 8080\nhost: remote\n")
        result = self._call(path=str(f), pattern="host")
        assert "2 matches" in result
        assert "localhost" in result
        assert "remote" in result

    def test_search_case_insensitive(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("ERROR: something\nerror: other\nInfo: ok\n")
        result = self._call(path=str(f), pattern="error")
        assert "2 matches" in result

    def test_search_no_matches(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\n")
        result = self._call(path=str(f), pattern="xyz")
        assert "No matches" in result

    def test_search_max_matches(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("".join(f"match line {i}\n" for i in range(100)))
        result = self._call(path=str(f), pattern="match", max_matches=5)
        # Should have at most 5 matches
        match_lines = [l for l in result.split("\n") if "match line" in l]
        assert len(match_lines) == 5

    def test_search_nonexistent(self, tmp_path):
        result = self._call(path=str(tmp_path / "nope.txt"), pattern="x")
        assert "not found" in result.lower()

    @patch("agenticops.tools.file_tools.settings")
    def test_search_blocked(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        result = self._call(path="/etc/shadow", pattern="root")
        assert "ACCESS DENIED" in result


# ── list_local_directory tests ───────────────────────────────────────


class TestListLocalDirectory:
    def _call(self, **kwargs):
        from agenticops.tools.file_tools import list_local_directory
        return list_local_directory._tool_func(**kwargs)

    def test_list_directory(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.yaml").write_text("key: val")
        result = self._call(path=str(tmp_path))
        assert "a.txt" in result
        assert "b.yaml" in result
        assert "2 entries" in result

    def test_list_with_pattern(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "b.yaml").write_text("y")
        result = self._call(path=str(tmp_path), pattern="*.yaml")
        assert "b.yaml" in result
        assert "a.txt" not in result

    def test_list_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.conf").write_text("z")
        (tmp_path / "top.conf").write_text("w")
        result = self._call(path=str(tmp_path), pattern="*.conf", recursive=True)
        assert "deep.conf" in result
        assert "top.conf" in result

    def test_list_nonexistent(self, tmp_path):
        result = self._call(path=str(tmp_path / "nope"))
        assert "not found" in result.lower()

    def test_list_not_a_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = self._call(path=str(f))
        assert "Not a directory" in result

    def test_list_empty_directory(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = self._call(path=str(empty))
        assert "No files" in result

    def test_list_shows_sizes(self, tmp_path):
        (tmp_path / "small.txt").write_text("x" * 500)
        result = self._call(path=str(tmp_path))
        assert "500B" in result

    @patch("agenticops.tools.file_tools.settings")
    def test_list_blocked_path(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        # Use a system-level blocked path substring
        result = self._call(path="/some/.gnupg/subdir")
        assert "ACCESS DENIED" in result


# ── file_stat tests ──────────────────────────────────────────────────


class TestFileStat:
    def _call(self, **kwargs):
        from agenticops.tools.file_tools import file_stat
        return file_stat._tool_func(**kwargs)

    def test_stat_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = self._call(path=str(f))
        assert "file" in result.lower()
        assert "11" in result  # 11 bytes
        assert "Path:" in result

    def test_stat_directory(self, tmp_path):
        result = self._call(path=str(tmp_path))
        assert "directory" in result.lower()

    def test_stat_nonexistent(self, tmp_path):
        result = self._call(path=str(tmp_path / "nope"))
        assert "Not found" in result


# ── write_local_file tests ───────────────────────────────────────────


class TestWriteLocalFile:
    def _call(self, **kwargs):
        from agenticops.tools.file_tools import write_local_file
        return write_local_file._tool_func(**kwargs)

    @patch("agenticops.tools.file_tools._register_local_doc")
    def test_write_new_file(self, mock_reg, tmp_path):
        f = tmp_path / "output.txt"
        result = self._call(path=str(f), content="hello world")
        assert "Wrote" in result
        assert "11" in result
        assert f.read_text() == "hello world"

    @patch("agenticops.tools.file_tools._register_local_doc")
    def test_write_overwrite(self, mock_reg, tmp_path):
        f = tmp_path / "output.txt"
        f.write_text("old")
        result = self._call(path=str(f), content="new content")
        assert "Wrote" in result
        assert f.read_text() == "new content"

    @patch("agenticops.tools.file_tools._register_local_doc")
    def test_write_append(self, mock_reg, tmp_path):
        f = tmp_path / "output.txt"
        f.write_text("line1\n")
        result = self._call(path=str(f), content="line2\n", mode="append")
        assert "Appended" in result
        assert f.read_text() == "line1\nline2\n"

    @patch("agenticops.tools.file_tools._register_local_doc")
    def test_write_creates_parent_dirs(self, mock_reg, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        result = self._call(path=str(f), content="deep")
        assert "Wrote" in result
        assert f.read_text() == "deep"

    def test_write_invalid_mode(self, tmp_path):
        f = tmp_path / "out.txt"
        result = self._call(path=str(f), content="x", mode="invalid")
        assert "Invalid mode" in result

    def test_write_too_large(self, tmp_path):
        f = tmp_path / "big.txt"
        content = "x" * (MAX_WRITE_BYTES + 1)
        result = self._call(path=str(f), content=content)
        assert "too large" in result.lower()

    @patch("agenticops.tools.file_tools.settings")
    def test_write_blocked(self, mock_settings):
        mock_settings.file_tools_admin_mode = False
        result = self._call(path="/etc/shadow", content="bad")
        assert "ACCESS DENIED" in result


# ── _register_local_doc tests ────────────────────────────────────────


class TestRegisterLocalDoc:
    @patch("agenticops.tools.file_tools.logger")
    def test_register_handles_import_error(self, mock_logger):
        """_register_local_doc is best-effort — should not raise."""
        from agenticops.tools.file_tools import _register_local_doc
        with patch("builtins.__import__", side_effect=ImportError("no models")):
            # Should not raise
            _register_local_doc("/tmp/test.txt", 100, "overwrite")
