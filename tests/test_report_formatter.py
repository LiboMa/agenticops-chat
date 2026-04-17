"""Tests for agenticops.notify.report_formatter — boosting from 34% coverage."""

import pytest
from unittest.mock import patch, MagicMock

from agenticops.notify.report_formatter import (
    FormattedReport,
    format_report,
    _to_markdown,
    _parse_newsletter_items,
    _inject_section_ids,
    _build_newsletter_toc,
    _format_contributors,
)


# ---------------------------------------------------------------------------
# FormattedReport dataclass
# ---------------------------------------------------------------------------

class TestFormattedReport:
    def test_creation(self):
        r = FormattedReport(format="markdown", content=b"hello", content_type="text/markdown", extension=".md")
        assert r.format == "markdown"
        assert r.content == b"hello"
        assert r.extension == ".md"


# ---------------------------------------------------------------------------
# _to_markdown
# ---------------------------------------------------------------------------

class TestToMarkdown:
    def test_basic(self):
        r = _to_markdown("# Hello\nWorld")
        assert r.format == "markdown"
        assert r.content == b"# Hello\nWorld"
        assert r.content_type == "text/markdown; charset=utf-8"
        assert r.extension == ".md"


# ---------------------------------------------------------------------------
# Newsletter helper functions
# ---------------------------------------------------------------------------

class TestParseNewsletterItems:
    def test_contact_badge_chinese(self):
        html = "<p>联系人：张三</p>"
        result = _parse_newsletter_items(html)
        assert "&#128100;" in result
        assert "张三" in result

    def test_contact_badge_english(self):
        html = "<p>Contact: John Doe</p>"
        result = _parse_newsletter_items(html)
        assert "&#128100;" in result
        assert "John Doe" in result

    def test_confidentiality_badge_chinese(self):
        html = "<p>公开范围：内部</p>"
        result = _parse_newsletter_items(html)
        assert "&#128274;" in result
        assert "内部" in result

    def test_confidentiality_badge_english(self):
        html = "<p>Confidentiality: Internal</p>"
        result = _parse_newsletter_items(html)
        assert "&#128274;" in result

    def test_no_match(self):
        html = "<p>Normal paragraph</p>"
        result = _parse_newsletter_items(html)
        assert result == html

    def test_br_terminated(self):
        html = "<p>联系人：张三<br />公开范围：公开</p>"
        result = _parse_newsletter_items(html)
        assert "&#128100;" in result
        assert "&#128274;" in result


class TestInjectSectionIds:
    def test_adds_ids(self):
        html = "<h2>First</h2><p>text</p><h2>Second</h2>"
        result = _inject_section_ids(html)
        assert 'id="section-1"' in result
        assert 'id="section-2"' in result

    def test_preserves_existing_attrs(self):
        html = '<h2 class="foo">Title</h2>'
        result = _inject_section_ids(html)
        assert 'id="section-1"' in result
        assert "foo" in result

    def test_no_headings(self):
        html = "<p>No headings</p>"
        result = _inject_section_ids(html)
        assert result == html


class TestBuildNewsletterToc:
    def test_two_sections(self):
        html = '<h2 id="section-1">Intro</h2><h2 id="section-2">Body</h2>'
        toc = _build_newsletter_toc(html)
        assert "Contents" in toc
        assert "Intro" in toc
        assert "Body" in toc
        assert "#section-1" in toc

    def test_one_section_returns_empty(self):
        html = '<h2 id="section-1">Only</h2>'
        assert _build_newsletter_toc(html) == ""

    def test_no_sections(self):
        assert _build_newsletter_toc("<p>text</p>") == ""

    def test_strips_inner_html(self):
        html = '<h2 id="section-1"><b>Bold</b> Title</h2><h2 id="section-2">Second</h2>'
        toc = _build_newsletter_toc(html)
        assert "Bold Title" in toc  # inner <b> stripped


class TestFormatContributors:
    def test_with_contributors(self):
        result = _format_contributors(["Alice", "Bob"])
        assert "Contributors" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_empty_list(self):
        assert _format_contributors([]) == ""

    def test_none_like(self):
        assert _format_contributors([]) == ""


# ---------------------------------------------------------------------------
# format_report — public API
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_markdown_only(self):
        results = format_report("Title", "# Content", ["markdown"])
        assert len(results) == 1
        assert results[0].format == "markdown"
        assert b"# Content" in results[0].content

    def test_html_basic(self):
        results = format_report("Title", "**bold**", ["html"])
        assert len(results) == 1
        assert results[0].format == "html"
        assert results[0].extension == ".html"
        assert b"bold" in results[0].content

    def test_html_newsletter(self):
        meta = {"report_type": "newsletter", "issue_number": 42, "subtitle": "Weekly"}
        results = format_report("News", "## Section 1\nHello\n## Section 2\nWorld", ["html"], report_metadata=meta)
        assert len(results) == 1
        content = results[0].content.decode("utf-8")
        assert "section" in content.lower()

    def test_newsletter_with_contributors(self):
        meta = {"report_type": "newsletter", "contributors": ["Alice", "Bob"]}
        results = format_report("News", "Content", ["html"], report_metadata=meta)
        assert len(results) == 1
        content = results[0].content.decode("utf-8")
        assert "Alice" in content

    def test_newsletter_with_classification(self):
        meta = {"report_type": "newsletter", "classification": "Confidential"}
        results = format_report("News", "Content", ["html"], report_metadata=meta)
        assert len(results) == 1

    def test_multiple_formats(self):
        results = format_report("T", "C", ["markdown", "html"])
        assert len(results) == 2
        formats = {r.format for r in results}
        assert formats == {"markdown", "html"}

    def test_unknown_format_skipped(self):
        results = format_report("T", "C", ["markdown", "xyzzy"])
        assert len(results) == 1
        assert results[0].format == "markdown"

    def test_pdf_skipped_without_weasyprint(self):
        # weasyprint is not installed in test env — should skip gracefully
        results = format_report("T", "C", ["pdf"])
        # Either empty (skipped) or has a result if weasyprint is installed
        for r in results:
            assert r.format == "pdf"

    def test_docx_skipped_without_docx(self):
        results = format_report("T", "C", ["docx"])
        for r in results:
            assert r.format == "docx"

    def test_empty_formats(self):
        results = format_report("T", "C", [])
        assert results == []

    def test_no_metadata(self):
        results = format_report("T", "C", ["html"])
        assert len(results) == 1

    def test_exception_in_format_graceful(self):
        """If a format converter raises, it should be caught and skipped."""
        with patch("agenticops.notify.report_formatter._to_html", side_effect=RuntimeError("boom")):
            results = format_report("T", "C", ["html", "markdown"])
            # markdown should still succeed
            assert any(r.format == "markdown" for r in results)
