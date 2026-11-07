"""Tests for multimodal file processing in the chat pipeline.

Covers:
- preprocessor.py: text-only backward compat, image/document content blocks, mixed mode, CLI @file refs
- Edge cases: oversized files, unsupported formats, missing files
"""

import os
import struct
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal valid file bytes
# ---------------------------------------------------------------------------

def _minimal_png() -> bytes:
    """1x1 red pixel PNG (valid header + IHDR + IDAT + IEND)."""
    import zlib

    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        raw = chunk_type + data
        return struct.pack(">I", len(data)) + raw + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8-bit RGB
    raw_row = b"\x00\xff\x00\x00"  # filter=none, R=255 G=0 B=0
    idat_data = zlib.compress(raw_row)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat_data) + _chunk(b"IEND", b"")


def _minimal_pdf() -> bytes:
    """Minimal valid PDF 1.4 with one blank page."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n183\n%%EOF\n"
    )



# ===========================================================================
# preprocessor.py — assembling the turn: text-only stays a str, media follow the text
# ===========================================================================

def _turn(blocks=(), text="Attachments (1): …"):
    from agenticops.chat.attachments.delivery import Turn
    return Turn(text=text, blocks=list(blocks), deliveries=[])


class TestPreprocessorTurnAssembly:
    def test_text_only_returns_str(self):
        from agenticops.chat.preprocessor import preprocess_message
        result, warnings = preprocess_message("hello world")
        assert result == "hello world" and warnings == []

    def test_text_attachments_stay_str(self):
        from agenticops.chat.preprocessor import preprocess_message
        result, _ = preprocess_message("summarize", attachment_turn=_turn(text='<attachment n="1">x</attachment>'))
        assert isinstance(result, str) and result.endswith("summarize")

    def test_empty_turn_is_ignored(self):
        from agenticops.chat.preprocessor import preprocess_message
        result, _ = preprocess_message("hi", attachment_turn=_turn(text=""))
        assert result == "hi"

    def test_media_follow_one_text_block(self):
        from agenticops.chat.preprocessor import preprocess_message
        img = {"image": {"format": "png", "source": {"bytes": _minimal_png()}}}
        doc = {"document": {"format": "pdf", "name": "att-1a2b3c4d-spec-pdf", "source": {"bytes": _minimal_pdf()}}}
        result, _ = preprocess_message("review", attachment_turn=_turn([img, doc]))
        assert result[0] == {"text": "Attachments (1): …\n\nreview"}
        assert result[1:] == [img, doc]


# ===========================================================================
# preprocessor.py — CLI @file refs with multimodal
# ===========================================================================

class TestPreprocessorCLIFileRefs:
    def test_at_image_ref_produces_content_blocks(self, tmp_path):
        from agenticops.chat.preprocessor import preprocess_message

        img = tmp_path / "test.png"
        img.write_bytes(_minimal_png())

        result, warnings = preprocess_message(
            f"analyze @{img}",
            resolve_file_refs=True,
        )
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert any("image" in b for b in result)
        assert warnings == []

    def test_at_document_ref_produces_content_blocks(self, tmp_path):
        from agenticops.chat.preprocessor import preprocess_message

        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(_minimal_pdf())

        result, warnings = preprocess_message(
            f"review @{pdf}",
            resolve_file_refs=True,
        )
        assert isinstance(result, list)
        assert any("document" in b for b in result)

    def test_at_txt_ref_is_text_not_a_document(self, tmp_path):
        """Plain-text formats are given as text even to Claude (2026-11-07): the same content, and no use of the
        five-documents-per-request quota."""
        from agenticops.chat.preprocessor import preprocess_message

        txt = tmp_path / "log.txt"
        txt.write_text("some error log content")

        result, warnings = preprocess_message(
            f"check @{txt}",
            resolve_file_refs=True,
        )
        assert isinstance(result, str)
        assert "some error log content" in result

    def test_at_json_ref_stays_string(self, tmp_path):
        """`.json` is NOT in DOCUMENT_FORMAT_MAP, so it stays as text extraction."""
        from agenticops.chat.preprocessor import preprocess_message

        jf = tmp_path / "config.json"
        jf.write_text('{"key": "value"}')

        result, warnings = preprocess_message(
            f"check @{jf}",
            resolve_file_refs=True,
        )
        assert isinstance(result, str)
        assert '{"key": "value"}' in result

    def test_at_mixed_text_and_image(self, tmp_path):
        from agenticops.chat.preprocessor import preprocess_message

        txt = tmp_path / "error.log"
        txt.write_text("NullPointerException")

        img = tmp_path / "screen.png"
        img.write_bytes(_minimal_png())

        result, warnings = preprocess_message(
            f"compare @{txt} with @{img}",
            resolve_file_refs=True,
        )
        # Has image → must be content blocks
        assert isinstance(result, list)
        text_block = next(b for b in result if "text" in b)
        assert "NullPointerException" in text_block["text"]
        assert any("image" in b for b in result)

    def test_at_missing_image_warns(self, tmp_path):
        from agenticops.chat.preprocessor import preprocess_message

        result, warnings = preprocess_message(
            f"analyze @{tmp_path}/nonexistent.png",
            resolve_file_refs=True,
        )
        assert len(warnings) == 1
        assert "not found" in warnings[0].lower()
        # No media blocks → stays str
        assert isinstance(result, str)
