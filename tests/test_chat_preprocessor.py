"""Tests for chat.preprocessor — reference resolution, file refs, and full pipeline."""

import re
from unittest.mock import patch, MagicMock

import pytest

from agenticops.chat.preprocessor import (
    ISSUE_REF_PATTERN,
    RESOURCE_REF_PATTERN,
    FILE_REF_PATTERN,
    _extract_file_refs,
    resolve_references,
    preprocess_message,
)


# ── regex patterns ──────────────────────────────────────────────

class TestPatterns:
    def test_issue_ref_basic(self):
        assert ISSUE_REF_PATTERN.findall("check I#42 please") == ["42"]

    def test_issue_ref_multiple(self):
        assert ISSUE_REF_PATTERN.findall("I#1 and I#99") == ["1", "99"]

    def test_issue_ref_no_match(self):
        assert ISSUE_REF_PATTERN.findall("no refs here") == []

    def test_issue_ref_not_partial(self):
        # Must have word boundary
        assert ISSUE_REF_PATTERN.findall("XI#5") == []

    def test_resource_ref_basic(self):
        assert RESOURCE_REF_PATTERN.findall("look at R#7") == ["7"]

    def test_resource_ref_multiple(self):
        assert RESOURCE_REF_PATTERN.findall("R#10 R#20 R#30") == ["10", "20", "30"]

    def test_file_ref_absolute(self):
        assert FILE_REF_PATTERN.findall("read @/tmp/foo.txt now") == ["/tmp/foo.txt"]

    def test_file_ref_relative(self):
        assert FILE_REF_PATTERN.findall("@./data/x.csv done") == ["./data/x.csv"]

    def test_file_ref_parent(self):
        assert FILE_REF_PATTERN.findall("@../notes.md") == ["../notes.md"]

    def test_file_ref_no_match(self):
        assert FILE_REF_PATTERN.findall("email@example.com") == []


# ── _extract_file_refs ──────────────────────────────────────────

class TestExtractFileRefs:
    def test_single_ref(self):
        cleaned, paths = _extract_file_refs("analyze @/var/log/app.log")
        assert paths == ["/var/log/app.log"]
        assert "@" not in cleaned

    def test_multiple_refs(self):
        cleaned, paths = _extract_file_refs("@/a.txt @./b.txt summarize")
        assert paths == ["/a.txt", "./b.txt"]
        assert "summarize" in cleaned

    def test_no_refs(self):
        cleaned, paths = _extract_file_refs("just a message")
        assert paths == []
        assert cleaned == "just a message"

    def test_empty_string(self):
        cleaned, paths = _extract_file_refs("")
        assert paths == []


# ── resolve_references ──────────────────────────────────────────

class TestResolveReferences:
    @patch("agenticops.chat.preprocessor._resolve_issue_ref")
    def test_issue_found(self, mock_resolve):
        mock_resolve.return_value = '<referenced_issue id="5">\nTitle: OOM\n</referenced_issue>'
        enriched, warnings = resolve_references("fix I#5")
        assert '<referenced_issue id="5">' in enriched
        assert warnings == []
        mock_resolve.assert_called_once_with(5)

    @patch("agenticops.chat.preprocessor._resolve_issue_ref")
    def test_issue_not_found(self, mock_resolve):
        mock_resolve.return_value = None
        enriched, warnings = resolve_references("check I#999")
        assert "I#999 not found" in warnings[0]
        assert enriched == "check I#999"

    @patch("agenticops.chat.preprocessor._resolve_resource_ref")
    def test_resource_found(self, mock_resolve):
        mock_resolve.return_value = '<referenced_resource id="3">\nName: web-01\n</referenced_resource>'
        enriched, warnings = resolve_references("show R#3")
        assert '<referenced_resource id="3">' in enriched
        assert warnings == []

    @patch("agenticops.chat.preprocessor._resolve_resource_ref")
    def test_resource_not_found(self, mock_resolve):
        mock_resolve.return_value = None
        enriched, warnings = resolve_references("R#404")
        assert len(warnings) == 1
        assert "R#404 not found" in warnings[0]

    def test_no_references(self):
        enriched, warnings = resolve_references("hello world")
        assert enriched == "hello world"
        assert warnings == []

    @patch("agenticops.chat.preprocessor._resolve_resource_ref")
    @patch("agenticops.chat.preprocessor._resolve_issue_ref")
    def test_mixed_refs(self, mock_issue, mock_resource):
        mock_issue.return_value = "<referenced_issue>ok</referenced_issue>"
        mock_resource.return_value = "<referenced_resource>ok</referenced_resource>"
        enriched, warnings = resolve_references("I#1 and R#2")
        assert "<referenced_issue>" in enriched
        assert "<referenced_resource>" in enriched
        assert warnings == []


# ── preprocess_message ──────────────────────────────────────────

class TestPreprocessMessage:
    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    def test_plain_text(self, _mock):
        result, warnings = preprocess_message("hello")
        assert result == "hello"
        assert isinstance(result, str)
        assert warnings == []

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    def test_file_contents_web_upload(self, _mock):
        result, warnings = preprocess_message(
            "summarize this",
            file_contents=[("report.txt", "revenue up 10%")],
        )
        assert isinstance(result, str)
        assert '<attached_file path="report.txt">' in result
        assert "revenue up 10%" in result
        assert "summarize this" in result

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    def test_image_blocks_returns_list(self, _mock):
        result, warnings = preprocess_message(
            "what is this?",
            file_images=[("photo.png", b"\x89PNG", "png")],
        )
        assert isinstance(result, list)
        assert result[0]["text"] == "what is this?"
        assert result[1]["image"]["format"] == "png"

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    def test_document_blocks_returns_list(self, _mock):
        result, warnings = preprocess_message(
            "review doc",
            file_documents=[("spec.pdf", b"%PDF", "pdf", "spec")],
        )
        assert isinstance(result, list)
        assert result[1]["document"]["format"] == "pdf"
        assert result[1]["document"]["name"] == "spec"

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    def test_mixed_media(self, _mock):
        result, warnings = preprocess_message(
            "analyze",
            file_images=[("a.png", b"\x89PNG", "png")],
            file_documents=[("b.pdf", b"%PDF", "pdf", "b")],
        )
        assert isinstance(result, list)
        assert len(result) == 3  # text + image + doc

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    @patch("agenticops.chat.preprocessor.is_image_file", return_value=False)
    @patch("agenticops.chat.preprocessor.is_document_file", return_value=False)
    @patch("agenticops.chat.preprocessor.read_file_as_text", return_value=("file content", None))
    def test_cli_file_ref_text(self, mock_read, _doc, _img, _resolve):
        result, warnings = preprocess_message(
            "analyze @/tmp/log.txt",
            resolve_file_refs=True,
        )
        assert isinstance(result, str)
        assert "file content" in result
        mock_read.assert_called_once_with("/tmp/log.txt")

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    @patch("agenticops.chat.preprocessor.is_image_file", return_value=True)
    @patch("agenticops.chat.preprocessor.read_file_as_image_bytes", return_value=(b"\x89PNG", "png", None))
    def test_cli_file_ref_image(self, mock_read, _img, _resolve):
        result, warnings = preprocess_message(
            "show @/tmp/pic.png",
            resolve_file_refs=True,
        )
        assert isinstance(result, list)
        assert any("image" in block for block in result)

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    @patch("agenticops.chat.preprocessor.is_image_file", return_value=False)
    @patch("agenticops.chat.preprocessor.is_document_file", return_value=True)
    @patch("agenticops.chat.preprocessor.read_file_as_document_bytes", return_value=(b"%PDF", "pdf", "doc", None))
    def test_cli_file_ref_document(self, mock_read, _doc, _img, _resolve):
        result, warnings = preprocess_message(
            "read @/tmp/spec.pdf",
            resolve_file_refs=True,
        )
        assert isinstance(result, list)
        assert any("document" in block for block in result)

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    @patch("agenticops.chat.preprocessor.is_image_file", return_value=False)
    @patch("agenticops.chat.preprocessor.is_document_file", return_value=False)
    @patch("agenticops.chat.preprocessor.read_file_as_text", return_value=(None, "File not found: /tmp/nope.txt"))
    def test_cli_file_ref_error(self, _read, _doc, _img, _resolve):
        result, warnings = preprocess_message(
            "check @/tmp/nope.txt",
            resolve_file_refs=True,
        )
        assert any("File not found" in w for w in warnings)

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    @patch("agenticops.chat.preprocessor.is_image_file", return_value=True)
    @patch("agenticops.chat.preprocessor.read_file_as_image_bytes", return_value=(None, None, "Cannot read image"))
    def test_cli_image_read_error(self, _read, _img, _resolve):
        result, warnings = preprocess_message(
            "show @/tmp/bad.png",
            resolve_file_refs=True,
        )
        assert any("Cannot read" in w for w in warnings)

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    @patch("agenticops.chat.preprocessor.is_image_file", return_value=False)
    @patch("agenticops.chat.preprocessor.is_document_file", return_value=True)
    @patch("agenticops.chat.preprocessor.read_file_as_document_bytes", return_value=(None, None, None, "Bad doc"))
    def test_cli_document_read_error(self, _read, _doc, _img, _resolve):
        result, warnings = preprocess_message(
            "read @/tmp/bad.pdf",
            resolve_file_refs=True,
        )
        assert any("Bad doc" in w for w in warnings)

    @patch("agenticops.chat.preprocessor.resolve_references")
    def test_ref_warnings_propagated(self, mock_resolve):
        mock_resolve.return_value = ("text", ["Issue I#99 not found"])
        result, warnings = preprocess_message("I#99")
        assert "I#99 not found" in warnings[0]

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t: (t, []))
    def test_multiple_file_contents(self, _mock):
        result, warnings = preprocess_message(
            "compare",
            file_contents=[("a.txt", "AAA"), ("b.txt", "BBB")],
        )
        assert "AAA" in result
        assert "BBB" in result
