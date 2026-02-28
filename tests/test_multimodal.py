"""Tests for multimodal file processing in the chat pipeline.

Covers:
- file_reader.py: type helpers, image/document byte readers
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
# file_reader.py — type helpers
# ===========================================================================

class TestFileTypeHelpers:
    def test_is_image_file_supported(self):
        from agenticops.chat.file_reader import is_image_file

        assert is_image_file("photo.png") is True
        assert is_image_file("PHOTO.PNG") is True
        assert is_image_file("shot.jpg") is True
        assert is_image_file("shot.jpeg") is True
        assert is_image_file("anim.gif") is True
        assert is_image_file("pic.webp") is True

    def test_is_image_file_unsupported(self):
        from agenticops.chat.file_reader import is_image_file

        assert is_image_file("pic.bmp") is False  # not in Strands ImageFormat
        assert is_image_file("doc.pdf") is False
        assert is_image_file("script.py") is False
        assert is_image_file("noext") is False

    def test_is_document_file_supported(self):
        from agenticops.chat.file_reader import is_document_file

        assert is_document_file("report.pdf") is True
        assert is_document_file("data.csv") is True
        assert is_document_file("file.doc") is True
        assert is_document_file("file.docx") is True
        assert is_document_file("sheet.xls") is True
        assert is_document_file("sheet.xlsx") is True
        assert is_document_file("page.html") is True
        assert is_document_file("readme.txt") is True
        assert is_document_file("notes.md") is True

    def test_is_document_file_unsupported(self):
        from agenticops.chat.file_reader import is_document_file

        assert is_document_file("script.py") is False
        assert is_document_file("photo.png") is False
        assert is_document_file("data.json") is False
        assert is_document_file("config.yaml") is False


# ===========================================================================
# file_reader.py — image byte readers
# ===========================================================================

class TestImageByteReaders:
    def test_read_file_as_image_bytes_png(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_image_bytes

        img = tmp_path / "test.png"
        img.write_bytes(_minimal_png())

        raw, fmt, error = read_file_as_image_bytes(str(img))
        assert error is None
        assert fmt == "png"
        assert raw is not None
        assert raw[:4] == b"\x89PNG"

    def test_read_file_as_image_bytes_jpeg(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_image_bytes

        img = tmp_path / "test.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # JPEG header stub

        raw, fmt, error = read_file_as_image_bytes(str(img))
        assert error is None
        assert fmt == "jpeg"

    def test_read_file_as_image_bytes_not_found(self):
        from agenticops.chat.file_reader import read_file_as_image_bytes

        raw, fmt, error = read_file_as_image_bytes("/nonexistent/image.png")
        assert raw is None
        assert "not found" in error.lower()

    def test_read_file_as_image_bytes_too_large(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_image_bytes, MAX_IMAGE_SIZE

        img = tmp_path / "huge.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * (MAX_IMAGE_SIZE + 1))

        raw, fmt, error = read_file_as_image_bytes(str(img))
        assert raw is None
        assert "too large" in error.lower()

    def test_read_file_as_image_bytes_unsupported_ext(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_image_bytes

        img = tmp_path / "test.bmp"
        img.write_bytes(b"BM" + b"\x00" * 100)

        raw, fmt, error = read_file_as_image_bytes(str(img))
        assert raw is None
        assert "unsupported" in error.lower()

    def test_read_upload_image_bytes_ok(self):
        from agenticops.chat.file_reader import read_upload_image_bytes

        raw, fmt, error = read_upload_image_bytes("shot.png", _minimal_png())
        assert error is None
        assert fmt == "png"
        assert raw is not None

    def test_read_upload_image_bytes_too_large(self):
        from agenticops.chat.file_reader import read_upload_image_bytes, MAX_IMAGE_SIZE

        raw, fmt, error = read_upload_image_bytes("big.png", b"\x00" * (MAX_IMAGE_SIZE + 1))
        assert raw is None
        assert "too large" in error.lower()

    def test_read_upload_image_bytes_bad_ext(self):
        from agenticops.chat.file_reader import read_upload_image_bytes

        raw, fmt, error = read_upload_image_bytes("file.bmp", b"BM")
        assert raw is None
        assert "unsupported" in error.lower()


# ===========================================================================
# file_reader.py — document byte readers
# ===========================================================================

class TestDocumentByteReaders:
    def test_read_file_as_document_bytes_pdf(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_document_bytes

        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(_minimal_pdf())

        raw, fmt, name, error = read_file_as_document_bytes(str(pdf))
        assert error is None
        assert fmt == "pdf"
        assert name == "report.pdf"
        assert raw is not None
        assert raw[:5] == b"%PDF-"

    def test_read_file_as_document_bytes_txt(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_document_bytes

        txt = tmp_path / "notes.txt"
        txt.write_text("hello world")

        raw, fmt, name, error = read_file_as_document_bytes(str(txt))
        assert error is None
        assert fmt == "txt"
        assert name == "notes.txt"
        assert b"hello world" in raw

    def test_read_file_as_document_bytes_not_found(self):
        from agenticops.chat.file_reader import read_file_as_document_bytes

        raw, fmt, name, error = read_file_as_document_bytes("/nonexistent/doc.pdf")
        assert raw is None
        assert "not found" in error.lower()

    def test_read_file_as_document_bytes_too_large(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_document_bytes, MAX_DOCUMENT_SIZE

        pdf = tmp_path / "huge.pdf"
        pdf.write_bytes(b"%PDF-" + b"\x00" * (MAX_DOCUMENT_SIZE + 1))

        raw, fmt, name, error = read_file_as_document_bytes(str(pdf))
        assert raw is None
        assert "too large" in error.lower()

    def test_read_file_as_document_bytes_unsupported_ext(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_document_bytes

        py = tmp_path / "script.py"
        py.write_text("print('hi')")

        raw, fmt, name, error = read_file_as_document_bytes(str(py))
        assert raw is None
        assert "unsupported" in error.lower()

    def test_read_upload_document_bytes_ok(self):
        from agenticops.chat.file_reader import read_upload_document_bytes

        raw, fmt, name, error = read_upload_document_bytes("report.pdf", _minimal_pdf())
        assert error is None
        assert fmt == "pdf"
        assert name == "report.pdf"
        assert raw is not None

    def test_read_upload_document_bytes_too_large(self):
        from agenticops.chat.file_reader import read_upload_document_bytes, MAX_DOCUMENT_SIZE

        raw, fmt, name, error = read_upload_document_bytes("big.pdf", b"\x00" * (MAX_DOCUMENT_SIZE + 1))
        assert raw is None
        assert "too large" in error.lower()

    def test_read_upload_document_bytes_bad_ext(self):
        from agenticops.chat.file_reader import read_upload_document_bytes

        raw, fmt, name, error = read_upload_document_bytes("script.py", b"print('hi')")
        assert raw is None
        assert "unsupported" in error.lower()


# ===========================================================================
# preprocessor.py — backward compatibility
# ===========================================================================

class TestPreprocessorBackwardCompat:
    """Existing text-only messages must still return plain str."""

    def test_text_only_returns_str(self):
        from agenticops.chat.preprocessor import preprocess_message

        result, warnings = preprocess_message("hello world")
        assert isinstance(result, str)
        assert "hello world" in result
        assert warnings == []

    def test_text_with_file_contents_returns_str(self):
        from agenticops.chat.preprocessor import preprocess_message

        result, warnings = preprocess_message(
            "check this log",
            file_contents=[("error.log", "NullPointerException at line 42")],
        )
        assert isinstance(result, str)
        assert "NullPointerException" in result
        assert "check this log" in result

    def test_empty_media_lists_returns_str(self):
        from agenticops.chat.preprocessor import preprocess_message

        result, warnings = preprocess_message(
            "just text",
            file_images=[],
            file_documents=[],
        )
        assert isinstance(result, str)


# ===========================================================================
# preprocessor.py — multimodal content blocks
# ===========================================================================

class TestPreprocessorMultimodal:
    def test_image_returns_content_blocks(self):
        from agenticops.chat.preprocessor import preprocess_message

        png_bytes = _minimal_png()
        result, warnings = preprocess_message(
            "analyze this screenshot",
            file_images=[("screen.png", png_bytes, "png")],
        )
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert any("text" in b for b in result)
        assert any("image" in b for b in result)

        # Verify image block structure
        img_block = next(b for b in result if "image" in b)
        assert img_block["image"]["format"] == "png"
        assert img_block["image"]["source"]["bytes"] == png_bytes

        # Verify text block contains user message
        text_block = next(b for b in result if "text" in b)
        assert "analyze this screenshot" in text_block["text"]

    def test_document_returns_content_blocks(self):
        from agenticops.chat.preprocessor import preprocess_message

        pdf_bytes = _minimal_pdf()
        result, warnings = preprocess_message(
            "review this report",
            file_documents=[("report.pdf", pdf_bytes, "pdf", "report.pdf")],
        )
        assert isinstance(result, list)
        assert any("text" in b for b in result)
        assert any("document" in b for b in result)

        # Verify document block structure
        doc_block = next(b for b in result if "document" in b)
        assert doc_block["document"]["format"] == "pdf"
        assert doc_block["document"]["name"] == "report.pdf"
        assert doc_block["document"]["source"]["bytes"] == pdf_bytes

    def test_mixed_text_file_and_image(self):
        from agenticops.chat.preprocessor import preprocess_message

        result, warnings = preprocess_message(
            "compare log with screenshot",
            file_contents=[("error.log", "StackOverflowError")],
            file_images=[("screen.png", _minimal_png(), "png")],
        )
        assert isinstance(result, list)
        text_block = next(b for b in result if "text" in b)
        assert "StackOverflowError" in text_block["text"]
        assert "compare log with screenshot" in text_block["text"]
        assert any("image" in b for b in result)

    def test_multiple_images(self):
        from agenticops.chat.preprocessor import preprocess_message

        result, warnings = preprocess_message(
            "compare these",
            file_images=[
                ("before.png", _minimal_png(), "png"),
                ("after.jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 10, "jpeg"),
            ],
        )
        assert isinstance(result, list)
        image_blocks = [b for b in result if "image" in b]
        assert len(image_blocks) == 2
        assert image_blocks[0]["image"]["format"] == "png"
        assert image_blocks[1]["image"]["format"] == "jpeg"

    def test_image_and_document_together(self):
        from agenticops.chat.preprocessor import preprocess_message

        result, warnings = preprocess_message(
            "analyze both",
            file_images=[("arch.png", _minimal_png(), "png")],
            file_documents=[("spec.pdf", _minimal_pdf(), "pdf", "spec.pdf")],
        )
        assert isinstance(result, list)
        assert any("text" in b for b in result)
        assert any("image" in b for b in result)
        assert any("document" in b for b in result)
        assert len(result) == 3  # text + image + document

    def test_content_block_ordering(self):
        """Text block comes first, then images, then documents."""
        from agenticops.chat.preprocessor import preprocess_message

        result, _ = preprocess_message(
            "analyze",
            file_images=[("a.png", _minimal_png(), "png")],
            file_documents=[("b.pdf", _minimal_pdf(), "pdf", "b.pdf")],
        )
        assert "text" in result[0]
        assert "image" in result[1]
        assert "document" in result[2]


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

    def test_at_txt_ref_becomes_document_block(self, tmp_path):
        """`.txt` is in DOCUMENT_FORMAT_MAP, so it becomes a native document block."""
        from agenticops.chat.preprocessor import preprocess_message

        txt = tmp_path / "log.txt"
        txt.write_text("some error log content")

        result, warnings = preprocess_message(
            f"check @{txt}",
            resolve_file_refs=True,
        )
        assert isinstance(result, list)
        assert any("document" in b for b in result)
        doc_block = next(b for b in result if "document" in b)
        assert doc_block["document"]["format"] == "txt"
        assert doc_block["document"]["source"]["bytes"] == b"some error log content"

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


# ===========================================================================
# Integration: verify existing read_file_as_text still works for images
# ===========================================================================

class TestLegacyImageFallback:
    """Ensure read_file_as_text still returns placeholder for images (no regression)."""

    def test_read_file_as_text_image_placeholder(self, tmp_path):
        from agenticops.chat.file_reader import read_file_as_text

        img = tmp_path / "test.png"
        img.write_bytes(_minimal_png())

        content, error = read_file_as_text(str(img))
        assert error is None
        assert "Image file" in content
        assert "cannot be directly analyzed" in content

    def test_read_upload_bytes_image_placeholder(self):
        from agenticops.chat.file_reader import read_upload_bytes

        content, error = read_upload_bytes("test.png", _minimal_png())
        assert error is None
        assert "image" in content.lower()
