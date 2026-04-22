"""Tests for tools/file_tools.py — security blocklists, read, write, search, list, stat."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Helpers ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_files(tmp_path):
    """Create sample files for testing."""
    # Normal text file
    sample = tmp_path / "sample.txt"
    sample.write_text("line1\nline2\nline3\nline4\nline5\n")

    # Nested directory
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.conf").write_text("key=value\n")
    (sub / "other.yaml").write_text("name: test\n")

    # Large-ish file
    big = tmp_path / "big.txt"
    big.write_text("\n".join(f"row {i}" for i in range(500)))

    return tmp_path


@pytest.fixture(autouse=True)
def _reset_admin_mode():
    """Ensure admin mode is off by default."""
    from agenticops.config import settings
    original = settings.file_tools_admin_mode
    settings.file_tools_admin_mode = False
    yield
    settings.file_tools_admin_mode = original


# ── _is_blocked tests ────────────────────────────────────────────────

class TestIsBlocked:
    """Security blocklist validation."""

    def test_system_paths_always_blocked(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/etc/shadow")
        assert result is not None
        assert "Blocked" in result

    def test_system_filenames_always_blocked(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/some/path/.env")
        assert result is not None
        assert "blocklist" in result

    def test_system_extensions_always_blocked(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/some/path/cert.p12")
        assert result is not None
        assert "blocklist" in result

    def test_admin_paths_blocked_without_admin_mode(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/home/user/.ssh/id_rsa")
        assert result is not None
        assert "ADMIN_MODE" in result or "admin" in result.lower()

    def test_admin_paths_allowed_with_admin_mode(self):
        from agenticops.config import settings
        from agenticops.tools.file_tools import _is_blocked
        settings.file_tools_admin_mode = True
        # .ssh dir is admin-only, not system-blocked
        # But id_rsa is an admin filename AND in an admin path
        # Test just the path portion with a non-admin filename
        result = _is_blocked("/home/user/.ssh/known_hosts")
        assert result is None

    def test_admin_extensions_blocked_without_admin_mode(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/some/path/key.pem")
        assert result is not None

    def test_admin_extensions_allowed_with_admin_mode(self):
        from agenticops.config import settings
        from agenticops.tools.file_tools import _is_blocked
        settings.file_tools_admin_mode = True
        result = _is_blocked("/some/path/key.pem")
        assert result is None

    def test_normal_file_not_blocked(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/tmp/test.txt")
        assert result is None

    def test_gnupg_always_blocked(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/home/user/.gnupg/secring.gpg")
        assert result is not None

    def test_docker_config_always_blocked(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/home/user/.docker/config.json")
        assert result is not None

    def test_secrets_yaml_blocked(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/app/secrets.yaml")
        assert result is not None

    def test_credentials_json_blocked(self):
        from agenticops.tools.file_tools import _is_blocked
        result = _is_blocked("/app/credentials.json")
        assert result is not None


# ── _truncate tests ──────────────────────────────────────────────────

class TestTruncate:
    def test_short_text_unchanged(self):
        from agenticops.tools.file_tools import _truncate
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        from agenticops.tools.file_tools import _truncate
        result = _truncate("a" * 5000, 100)
        assert len(result) < 5000
        assert "truncated" in result


# ── read_local_file tests ────────────────────────────────────────────

class TestReadLocalFile:
    def test_read_normal_file(self, tmp_files):
        from agenticops.tools.file_tools import read_local_file
        result = read_local_file(str(tmp_files / "sample.txt"))
        assert "line1" in result
        assert "line5" in result

    def test_read_with_offset_limit(self, tmp_files):
        from agenticops.tools.file_tools import read_local_file
        result = read_local_file(str(tmp_files / "sample.txt"), offset=2, limit=2)
        assert "line3" in result
        assert "line1" not in result

    def test_read_nonexistent(self, tmp_files):
        from agenticops.tools.file_tools import read_local_file
        result = read_local_file(str(tmp_files / "nope.txt"))
        assert "not found" in result.lower()

    def test_read_directory_fails(self, tmp_files):
        from agenticops.tools.file_tools import read_local_file
        result = read_local_file(str(tmp_files / "subdir"))
        assert "Not a file" in result

    def test_read_blocked_file(self):
        from agenticops.tools.file_tools import read_local_file
        result = read_local_file("/etc/shadow")
        assert "ACCESS DENIED" in result

    def test_read_permission_denied(self, tmp_files):
        from agenticops.tools.file_tools import read_local_file
        f = tmp_files / "noperm.txt"
        f.write_text("secret")
        f.chmod(0o000)
        result = read_local_file(str(f))
        assert "denied" in result.lower() or "error" in result.lower()
        f.chmod(0o644)  # cleanup


# ── tail_local_file tests ───────────────────────────────────────────

class TestTailLocalFile:
    def test_tail_file(self, tmp_files):
        from agenticops.tools.file_tools import tail_local_file
        result = tail_local_file(str(tmp_files / "big.txt"), lines=5)
        assert "row 499" in result
        assert "last 5" in result

    def test_tail_nonexistent(self, tmp_files):
        from agenticops.tools.file_tools import tail_local_file
        result = tail_local_file(str(tmp_files / "nope.txt"))
        assert "not found" in result.lower()

    def test_tail_blocked(self):
        from agenticops.tools.file_tools import tail_local_file
        result = tail_local_file("/etc/shadow")
        assert "ACCESS DENIED" in result


# ── search_local_file tests ─────────────────────────────────────────

class TestSearchLocalFile:
    def test_search_found(self, tmp_files):
        from agenticops.tools.file_tools import search_local_file
        result = search_local_file(str(tmp_files / "sample.txt"), "line3")
        assert "line3" in result
        assert "1 matches" in result

    def test_search_not_found(self, tmp_files):
        from agenticops.tools.file_tools import search_local_file
        result = search_local_file(str(tmp_files / "sample.txt"), "zzz_missing")
        assert "No matches" in result

    def test_search_case_insensitive(self, tmp_files):
        from agenticops.tools.file_tools import search_local_file
        f = tmp_files / "case.txt"
        f.write_text("Hello World\n")
        result = search_local_file(str(f), "hello")
        assert "Hello World" in result

    def test_search_blocked(self):
        from agenticops.tools.file_tools import search_local_file
        result = search_local_file("/etc/shadow", "root")
        assert "ACCESS DENIED" in result

    def test_search_nonexistent(self, tmp_files):
        from agenticops.tools.file_tools import search_local_file
        result = search_local_file(str(tmp_files / "nope.txt"), "x")
        assert "not found" in result.lower()


# ── list_local_directory tests ───────────────────────────────────────

class TestListLocalDirectory:
    def test_list_basic(self, tmp_files):
        from agenticops.tools.file_tools import list_local_directory
        result = list_local_directory(str(tmp_files))
        assert "sample.txt" in result
        assert "big.txt" in result

    def test_list_with_pattern(self, tmp_files):
        from agenticops.tools.file_tools import list_local_directory
        result = list_local_directory(str(tmp_files), pattern="*.txt")
        assert "sample.txt" in result
        # subdir conf/yaml should not appear without recursive
        assert ".conf" not in result

    def test_list_recursive(self, tmp_files):
        from agenticops.tools.file_tools import list_local_directory
        result = list_local_directory(str(tmp_files), pattern="*.conf", recursive=True)
        assert "nested.conf" in result

    def test_list_nonexistent(self, tmp_files):
        from agenticops.tools.file_tools import list_local_directory
        result = list_local_directory(str(tmp_files / "nope"))
        assert "not found" in result.lower()

    def test_list_file_not_dir(self, tmp_files):
        from agenticops.tools.file_tools import list_local_directory
        result = list_local_directory(str(tmp_files / "sample.txt"))
        assert "Not a directory" in result

    def test_list_no_matches(self, tmp_files):
        from agenticops.tools.file_tools import list_local_directory
        result = list_local_directory(str(tmp_files), pattern="*.zzz")
        assert "No files matching" in result


# ── file_stat tests ──────────────────────────────────────────────────

class TestFileStat:
    def test_stat_file(self, tmp_files):
        from agenticops.tools.file_tools import file_stat
        result = file_stat(str(tmp_files / "sample.txt"))
        assert "file" in result.lower()
        assert "bytes" in result.lower()
        assert "Modified" in result

    def test_stat_directory(self, tmp_files):
        from agenticops.tools.file_tools import file_stat
        result = file_stat(str(tmp_files / "subdir"))
        assert "directory" in result.lower()

    def test_stat_nonexistent(self, tmp_files):
        from agenticops.tools.file_tools import file_stat
        result = file_stat(str(tmp_files / "nope"))
        assert "Not found" in result


# ── write_local_file tests ───────────────────────────────────────────

class TestWriteLocalFile:
    def test_write_new_file(self, tmp_files):
        from agenticops.tools.file_tools import write_local_file
        target = str(tmp_files / "output.txt")
        result = write_local_file(target, "hello world")
        assert "Wrote" in result
        assert Path(target).read_text() == "hello world"

    def test_write_append(self, tmp_files):
        from agenticops.tools.file_tools import write_local_file
        target = str(tmp_files / "sample.txt")
        write_local_file(target, "extra\n", mode="append")
        content = Path(target).read_text()
        assert content.endswith("extra\n")

    def test_write_creates_parent_dirs(self, tmp_files):
        from agenticops.tools.file_tools import write_local_file
        target = str(tmp_files / "deep" / "nested" / "file.txt")
        result = write_local_file(target, "nested content")
        assert "Wrote" in result
        assert Path(target).exists()

    def test_write_blocked(self):
        from agenticops.tools.file_tools import write_local_file
        result = write_local_file("/etc/shadow", "bad")
        assert "ACCESS DENIED" in result

    def test_write_invalid_mode(self, tmp_files):
        from agenticops.tools.file_tools import write_local_file
        result = write_local_file(str(tmp_files / "x.txt"), "data", mode="bad")
        assert "Invalid mode" in result

    def test_write_too_large(self, tmp_files):
        from agenticops.tools.file_tools import write_local_file
        result = write_local_file(str(tmp_files / "x.txt"), "x" * (1_048_577))
        assert "too large" in result.lower()


# ── _register_local_doc tests ────────────────────────────────────────

# ── read_document tests ──────────────────────────────────────────────

class TestReadDocument:
    """Tests for the read_document tool — text-based docs, blocked paths, errors."""

    def test_read_markdown(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        md = tmp_files / "doc.md"
        md.write_text("# Hello\n\nWorld")
        result = read_document(str(md))
        assert "doc.md" in result
        assert "# Hello" in result
        assert "World" in result

    def test_read_csv(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        csv = tmp_files / "data.csv"
        csv.write_text("a,b,c\n1,2,3\n")
        result = read_document(str(csv))
        assert "data.csv" in result
        assert "a,b,c" in result

    def test_read_json(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        jf = tmp_files / "config.json"
        jf.write_text('{"key": "value"}')
        result = read_document(str(jf))
        assert '"key"' in result

    def test_read_html(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        hf = tmp_files / "page.html"
        hf.write_text("<html><body>Hello</body></html>")
        result = read_document(str(hf))
        assert "page.html" in result
        assert "Hello" in result

    def test_read_yaml(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        yf = tmp_files / "config.yaml"
        yf.write_text("key: value\n")
        result = read_document(str(yf))
        assert "key: value" in result

    def test_read_txt(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        tf = tmp_files / "readme.txt"
        tf.write_text("Some readme content")
        result = read_document(str(tf))
        assert "readme.txt" in result
        assert "Some readme content" in result

    def test_read_nonexistent(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        result = read_document(str(tmp_files / "no_such_file.md"))
        assert "not found" in result.lower()

    def test_read_directory(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        result = read_document(str(tmp_files / "subdir"))
        assert "not a file" in result.lower()

    def test_read_blocked_path(self):
        from agenticops.tools.file_tools import read_document
        result = read_document("/etc/shadow")
        assert "ACCESS DENIED" in result

    def test_read_unsupported_extension(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        bf = tmp_files / "data.bin"
        bf.write_bytes(b"\x00\x01\x02")
        result = read_document(str(bf))
        assert "unsupported" in result.lower()

    def test_read_large_text_file_rejected(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        lf = tmp_files / "huge.md"
        lf.write_text("x" * (11 * 1024 * 1024))  # >10 MB
        result = read_document(str(lf))
        assert "too large" in result.lower()

    def test_read_permission_denied(self, tmp_files):
        from agenticops.tools.file_tools import read_document
        pf = tmp_files / "secret.md"
        pf.write_text("secret")
        pf.chmod(0o000)
        try:
            result = read_document(str(pf))
            assert "error" in result.lower() or "permission" in result.lower()
        finally:
            pf.chmod(0o644)

    def test_read_pdf_no_library(self, tmp_files):
        """When pymupdf and pypdf are both unavailable, should report it."""
        from agenticops.tools.file_tools import read_document
        pf = tmp_files / "doc.pdf"
        pf.write_bytes(b"%PDF-1.4 fake")
        with patch.dict("sys.modules", {"pymupdf": None, "pypdf": None}):
            result = read_document(str(pf))
            # Either an error or a library-not-installed message
            assert "pdf" in result.lower() or "error" in result.lower()

    def test_read_docx_no_library(self, tmp_files):
        """When python-docx is unavailable, should report it."""
        from agenticops.tools.file_tools import read_document
        df = tmp_files / "doc.docx"
        df.write_bytes(b"PK\x03\x04 fake docx")
        with patch.dict("sys.modules", {"docx": None}):
            result = read_document(str(df))
            assert "docx" in result.lower() or "error" in result.lower()

    def test_read_xlsx_no_library(self, tmp_files):
        """When openpyxl is unavailable, should report it."""
        from agenticops.tools.file_tools import read_document
        xf = tmp_files / "data.xlsx"
        xf.write_bytes(b"PK\x03\x04 fake xlsx")
        with patch.dict("sys.modules", {"openpyxl": None}):
            result = read_document(str(xf))
            assert "xlsx" in result.lower() or "error" in result.lower()


class TestRegisterLocalDoc:
    def test_register_does_not_crash_on_import_error(self):
        """_register_local_doc is best-effort and should never raise."""
        from agenticops.tools.file_tools import _register_local_doc
        # This should not raise even if DB is not configured
        _register_local_doc("/tmp/test.txt", 100, "overwrite")
