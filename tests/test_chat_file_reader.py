"""Tests for agenticops.chat.file_reader module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import os

from agenticops.chat.file_reader import (
    read_file_as_text,
    is_image_file,
    is_document_file,
    read_file_as_image_bytes,
    read_upload_image_bytes,
    read_file_as_document_bytes,
    read_upload_document_bytes,
    read_upload_bytes,
    TEXT_EXTENSIONS,
    IMAGE_FORMAT_MAP,
    DOCUMENT_FORMAT_MAP,
    MAX_FILE_SIZE,
    MAX_IMAGE_SIZE,
    MAX_DOCUMENT_SIZE,
)


# ─── read_file_as_text ───────────────────────────────────────────────────────


class TestReadFileAsText:
    def test_text_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        content, err = read_file_as_text(str(f))
        assert content == "hello world"
        assert err is None

    def test_file_not_found(self):
        content, err = read_file_as_text("/nonexistent/path/xyz.txt")
        assert content == ""
        assert "File not found" in err

    def test_not_a_file(self, tmp_path):
        content, err = read_file_as_text(str(tmp_path))
        assert content == ""
        assert "Not a file" in err

    def test_text_file_too_large(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_bytes(b"x" * (MAX_FILE_SIZE + 1))
        content, err = read_file_as_text(str(f))
        assert content == ""
        assert "too large" in err

    def test_no_extension_treated_as_text(self, tmp_path):
        f = tmp_path / "noext"
        f.write_text("some content")
        content, err = read_file_as_text(str(f))
        assert content == "some content"
        assert err is None

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.xyz"
        f.write_bytes(b"binary")
        content, err = read_file_as_text(str(f))
        assert content == ""
        assert "Unsupported file type" in err

    def test_image_file_returns_placeholder(self, tmp_path):
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG" + b"\x00" * 100)
        content, err = read_file_as_text(str(f))
        assert "Image file" in content
        assert err is None

    def test_image_too_large(self, tmp_path):
        f = tmp_path / "huge.jpg"
        f.write_bytes(b"\xff\xd8" * (MAX_IMAGE_SIZE + 1))
        content, err = read_file_as_text(str(f))
        assert content == ""
        assert "too large" in err

    def test_python_file(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("print('hi')")
        content, err = read_file_as_text(str(f))
        assert content == "print('hi')"
        assert err is None

    def test_json_file(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        content, err = read_file_as_text(str(f))
        assert content == '{"key": "value"}'
        assert err is None

    def test_pdf_no_library(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 dummy")
        import sys
        # Remove both pdf modules from sys.modules temporarily
        orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
        def mock_import(name, *args, **kwargs):
            if name in ("pymupdf", "pypdf"):
                raise ImportError(f"No module named '{name}'")
            return orig_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=mock_import):
            content, err = read_file_as_text(str(f))
            assert content == ""
            assert err is not None

    def test_docx_no_library(self, tmp_path):
        f = tmp_path / "doc.docx"
        f.write_bytes(b"PK\x03\x04dummy")
        orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
        def mock_import(name, *args, **kwargs):
            if name == "docx":
                raise ImportError("No module named 'docx'")
            return orig_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=mock_import):
            content, err = read_file_as_text(str(f))
            assert content == ""
            assert err is not None


# ─── is_image_file / is_document_file ────────────────────────────────────────


class TestFileTypeChecks:
    @pytest.mark.parametrize("name,expected", [
        ("photo.png", True),
        ("pic.jpg", True),
        ("pic.jpeg", True),
        ("anim.gif", True),
        ("modern.webp", True),
        ("doc.pdf", False),
        ("file.txt", False),
        ("noext", False),
    ])
    def test_is_image_file(self, name, expected):
        assert is_image_file(name) == expected

    @pytest.mark.parametrize("name,expected", [
        ("report.pdf", True),
        ("data.csv", True),
        ("file.docx", True),
        ("sheet.xlsx", True),
        ("page.html", True),
        ("readme.md", True),
        ("readme.txt", True),
        ("photo.png", False),
        ("binary.bin", False),
    ])
    def test_is_document_file(self, name, expected):
        assert is_document_file(name) == expected


# ─── read_file_as_image_bytes ────────────────────────────────────────────────


class TestReadFileAsImageBytes:
    def test_valid_png(self, tmp_path):
        f = tmp_path / "img.png"
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        f.write_bytes(data)
        raw, fmt, err = read_file_as_image_bytes(str(f))
        assert raw == data
        assert fmt == "png"
        assert err is None

    def test_valid_jpeg(self, tmp_path):
        f = tmp_path / "img.jpg"
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        f.write_bytes(data)
        raw, fmt, err = read_file_as_image_bytes(str(f))
        assert raw == data
        assert fmt == "jpeg"
        assert err is None

    def test_not_found(self):
        raw, fmt, err = read_file_as_image_bytes("/no/such/file.png")
        assert raw is None
        assert "File not found" in err

    def test_not_a_file(self, tmp_path):
        raw, fmt, err = read_file_as_image_bytes(str(tmp_path))
        assert raw is None
        assert "Not a file" in err

    def test_unsupported_format(self, tmp_path):
        f = tmp_path / "img.tiff"
        f.write_bytes(b"TIFF data")
        raw, fmt, err = read_file_as_image_bytes(str(f))
        assert raw is None
        assert "Unsupported" in err

    def test_too_large(self, tmp_path):
        f = tmp_path / "huge.png"
        f.write_bytes(b"\x00" * (MAX_IMAGE_SIZE + 1))
        raw, fmt, err = read_file_as_image_bytes(str(f))
        assert raw is None
        assert "too large" in err


# ─── read_upload_image_bytes ─────────────────────────────────────────────────


class TestReadUploadImageBytes:
    def test_valid(self):
        data = b"\x89PNG" + b"\x00" * 100
        raw, fmt, err = read_upload_image_bytes("photo.png", data)
        assert raw == data
        assert fmt == "png"
        assert err is None

    def test_unsupported_format(self):
        raw, fmt, err = read_upload_image_bytes("image.bmp", b"BM" + b"\x00" * 50)
        assert raw is None
        assert "Unsupported" in err

    def test_too_large(self):
        data = b"\x00" * (MAX_IMAGE_SIZE + 1)
        raw, fmt, err = read_upload_image_bytes("big.png", data)
        assert raw is None
        assert "too large" in err


# ─── read_file_as_document_bytes ─────────────────────────────────────────────


class TestReadFileAsDocumentBytes:
    def test_valid_pdf(self, tmp_path):
        f = tmp_path / "doc.pdf"
        data = b"%PDF-1.4 content"
        f.write_bytes(data)
        raw, fmt, name, err = read_file_as_document_bytes(str(f))
        assert raw == data
        assert fmt == "pdf"
        assert name == "doc.pdf"
        assert err is None

    def test_not_found(self):
        raw, fmt, name, err = read_file_as_document_bytes("/no/file.pdf")
        assert raw is None
        assert "File not found" in err

    def test_not_a_file(self, tmp_path):
        raw, fmt, name, err = read_file_as_document_bytes(str(tmp_path))
        assert raw is None
        assert "Not a file" in err

    def test_unsupported_format(self, tmp_path):
        f = tmp_path / "data.xyz"
        f.write_bytes(b"some data")
        raw, fmt, name, err = read_file_as_document_bytes(str(f))
        assert raw is None
        assert "Unsupported" in err

    def test_too_large(self, tmp_path):
        f = tmp_path / "big.pdf"
        f.write_bytes(b"\x00" * (MAX_DOCUMENT_SIZE + 1))
        raw, fmt, name, err = read_file_as_document_bytes(str(f))
        assert raw is None
        assert "too large" in err


# ─── read_upload_document_bytes ──────────────────────────────────────────────


class TestReadUploadDocumentBytes:
    def test_valid(self):
        data = b"%PDF-1.4 stuff"
        raw, fmt, name, err = read_upload_document_bytes("report.pdf", data)
        assert raw == data
        assert fmt == "pdf"
        assert name == "report.pdf"
        assert err is None

    def test_unsupported(self):
        raw, fmt, name, err = read_upload_document_bytes("file.bin", b"\x00" * 10)
        assert raw is None
        assert "Unsupported" in err

    def test_too_large(self):
        data = b"\x00" * (MAX_DOCUMENT_SIZE + 1)
        raw, fmt, name, err = read_upload_document_bytes("big.docx", data)
        assert raw is None
        assert "too large" in err


# ─── read_upload_bytes ───────────────────────────────────────────────────────


class TestReadUploadBytes:
    def test_text_file(self):
        content, err = read_upload_bytes("notes.txt", b"hello world")
        assert content == "hello world"
        assert err is None

    def test_text_too_large(self):
        data = b"x" * (MAX_FILE_SIZE + 1)
        content, err = read_upload_bytes("big.txt", data)
        assert content == ""
        assert "too large" in err

    def test_json_file(self):
        content, err = read_upload_bytes("data.json", b'{"k":1}')
        assert content == '{"k":1}'
        assert err is None

    def test_image_upload(self):
        content, err = read_upload_bytes("photo.png", b"\x89PNG" + b"\x00" * 50)
        assert "Uploaded image" in content
        assert err is None

    def test_unsupported(self):
        content, err = read_upload_bytes("data.xyz", b"binary")
        assert content == ""
        assert "Unsupported" in err

    def test_no_extension(self):
        content, err = read_upload_bytes("Makefile", b"all:\n\techo hi")
        assert content == "all:\n\techo hi"
        assert err is None
