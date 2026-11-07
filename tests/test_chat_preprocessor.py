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
        mock_resolve.assert_called_once_with(5, None)

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

CLAUDE = "global.anthropic.claude-opus-5-5"


class TestPreprocessMessage:
    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_plain_text(self, _mock):
        result, warnings = preprocess_message("hello")
        assert result == "hello"
        assert isinstance(result, str)
        assert warnings == []

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_file_contents_web_upload(self, _mock):
        result, warnings = preprocess_message(
            "summarize this",
            file_contents=[("report.txt", "revenue up 10%")],
        )
        assert isinstance(result, str)
        assert '<attached_file path="report.txt">' in result
        assert "revenue up 10%" in result
        assert "summarize this" in result

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_image_blocks_returns_list(self, _mock):
        result, warnings = preprocess_message(
            "what is this?",
            file_images=[("photo.png", b"\x89PNG", "png")],
        )
        assert isinstance(result, list)
        assert result[0]["text"] == "what is this?"
        assert result[1]["image"]["format"] == "png"

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_document_blocks_returns_list(self, _mock):
        result, warnings = preprocess_message(
            "review doc",
            file_documents=[("spec.pdf", b"%PDF", "pdf", "spec")],
        )
        assert isinstance(result, list)
        assert result[1]["document"]["format"] == "pdf"
        assert result[1]["document"]["name"] == "spec"

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_mixed_media(self, _mock):
        result, warnings = preprocess_message(
            "analyze",
            file_images=[("a.png", b"\x89PNG", "png")],
            file_documents=[("b.pdf", b"%PDF", "pdf", "b")],
        )
        assert isinstance(result, list)
        assert len(result) == 3  # text + image + doc

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_cli_file_ref_text(self, _resolve, tmp_path):
        log = tmp_path / "log.txt"
        log.write_text("file content LOG-77")
        result, warnings = preprocess_message(f"analyze @{log}", resolve_file_refs=True, model_id=CLAUDE)
        assert isinstance(result, str) and warnings == []
        assert '<attachment n="1" name="log.txt" type="txt">' in result and "file content LOG-77" in result
        assert result.rstrip().endswith("analyze")

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_cli_file_ref_image(self, _resolve, tmp_path):
        from tests.fixtures.attachments import make
        pic = make("png", tmp_path)
        result, warnings = preprocess_message(f"show @{pic}", resolve_file_refs=True, model_id=CLAUDE)
        assert isinstance(result, list) and warnings == []
        assert any("image" in block for block in result)

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_cli_file_ref_document(self, _resolve, tmp_path):
        from tests.fixtures.attachments import make
        pdf = make("pdf", tmp_path)
        result, warnings = preprocess_message(f"read @{pdf}", resolve_file_refs=True, model_id=CLAUDE)
        assert isinstance(result, list)
        doc = next(block["document"] for block in result if "document" in block)
        assert doc["name"].startswith("att-") and doc["format"] == "pdf"

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_cli_file_ref_error(self, _resolve, tmp_path):
        result, warnings = preprocess_message(f"check @{tmp_path}/nope.txt", resolve_file_refs=True, model_id=CLAUDE)
        assert any("file not found" in w for w in warnings)
        assert isinstance(result, str)

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_cli_image_read_error(self, _resolve, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage")
        result, warnings = preprocess_message(f"show @{bad}", resolve_file_refs=True, model_id=CLAUDE)
        assert any("damaged" in w for w in warnings)
        assert isinstance(result, str)

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_cli_document_read_error(self, _resolve, tmp_path):
        from tests.fixtures.attachments import make
        locked = make("encrypted_pdf", tmp_path)
        result, warnings = preprocess_message(f"read @{locked}", resolve_file_refs=True, model_id=CLAUDE)
        assert any("password-protected" in w for w in warnings)

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_cli_at_path_uses_model_capabilities(self, _resolve, tmp_path):
        from tests.fixtures.attachments import make
        pic = make("png", tmp_path)
        result, warnings = preprocess_message(f"show @{pic}", resolve_file_refs=True,
                                              model_id="openai.gpt-oss-120b-1:0")
        assert isinstance(result, str)   # a text-only model gets no image block
        assert any("cannot see images" in w for w in warnings)

    def test_refs_not_resolved_from_attachment_text(self):
        from agenticops.chat.attachments.delivery import Turn
        seen = []

        def fake_resolve(text, **kw):
            seen.append((text, kw.get("change_ref_text")))
            return text, []
        turn = Turn(text="<attachment n=\"1\">see I#5 and R#9</attachment>", blocks=[], deliveries=[])
        with patch("agenticops.chat.preprocessor.resolve_references", side_effect=fake_resolve):
            result, _ = preprocess_message("summarize", attachment_turn=turn)
        assert seen == [("summarize", "summarize")]
        assert result.startswith("<attachment") and result.endswith("summarize")

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_attachment_turn_blocks_follow_text(self, _resolve):
        from agenticops.chat.attachments.delivery import Turn
        img = {"image": {"format": "png", "source": {"bytes": b"x"}}}
        result, _ = preprocess_message("look", attachment_turn=Turn("manifest", [img], []))
        assert result == [{"text": "manifest\n\nlook"}, img]

    @patch("agenticops.chat.preprocessor.resolve_references")
    def test_ref_warnings_propagated(self, mock_resolve):
        mock_resolve.return_value = ("text", ["Issue I#99 not found"])
        result, warnings = preprocess_message("I#99")
        assert "I#99 not found" in warnings[0]

    @patch("agenticops.chat.preprocessor.resolve_references", side_effect=lambda t, **_: (t, []))
    def test_multiple_file_contents(self, _mock):
        result, warnings = preprocess_message(
            "compare",
            file_contents=[("a.txt", "AAA"), ("b.txt", "BBB")],
        )
        assert "AAA" in result
        assert "BBB" in result


# ── shared reference resolver ───────────────────────────────────

def test_reference_resolver_module_exists_and_resolves(monkeypatch):
    from agenticops.chat import reference_resolver as rr

    class _Issue:
        id = 7; title = "Disk full"; severity = "high"; status = "open"
        resource_id = "i-1"; source = "cw"; description = "boom"; detected_at = "2026-01-01"

    class _Q:
        def filter_by(self, **kw): return self
        def first(self): return _Issue()
    class _DB:
        def query(self, *a): return _Q()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(rr, "get_db_session", lambda: _DB())
    out = rr.fetch_issue(7)
    assert out is not None and out["id"] == 7 and out["title"] == "Disk full"


class TestBoundAccountRefs:
    """MVP-2.7.0 S5: in a chat bound to an account, an I#/R#/C# of another account is withheld, not loaded."""

    @staticmethod
    def _fake(monkeypatch, account_id):
        import agenticops.chat.reference_resolver as rr
        rec = {"id": 7, "title": "SECRET-TITLE", "severity": "high", "status": "open", "resource_id": "i-1",
               "source": "manual", "description": "d", "detected_at": "2026-10-07", "account_id": account_id}
        monkeypatch.setattr(rr, "fetch_issue", lambda _i: rec)

    def test_ref_outside_the_bound_account_is_withheld(self, monkeypatch):
        from agenticops.chat.preprocessor import resolve_references
        self._fake(monkeypatch, 2)
        text, _ = resolve_references("look at I#7", bound_account_id=1)
        assert "not in this chat's account" in text and "SECRET-TITLE" not in text

    def test_ref_inside_the_bound_account_resolves(self, monkeypatch):
        from agenticops.chat.preprocessor import resolve_references
        self._fake(monkeypatch, 1)
        assert "SECRET-TITLE" in resolve_references("look at I#7", bound_account_id=1)[0]

    def test_unbound_chat_resolves_any_ref(self, monkeypatch):
        from agenticops.chat.preprocessor import resolve_references
        self._fake(monkeypatch, 2)
        assert "SECRET-TITLE" in resolve_references("look at I#7")[0]

    def test_preprocess_message_passes_the_binding_through(self, monkeypatch):
        from agenticops.chat.preprocessor import preprocess_message
        self._fake(monkeypatch, 2)
        out, _ = preprocess_message("look at I#7", bound_account_id=1)
        assert "SECRET-TITLE" not in out


def test_cli_reads_the_agents_actual_model_id():
    from types import SimpleNamespace
    from agenticops.cli.main import _agent_model_id
    assert _agent_model_id(SimpleNamespace(model=SimpleNamespace(config={"model_id": CLAUDE}))) == CLAUDE
    assert _agent_model_id(SimpleNamespace(model=SimpleNamespace(config={}))) == ""
    assert _agent_model_id(object()) == ""
