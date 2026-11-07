"""Chat attachments: per-format extraction into model-independent artifacts (2026-11-07)."""
import json
from pathlib import Path

import pytest

from agenticops.chat.attachments.extract import ExtractError, ExtractLimits, process
from tests.fixtures.attachments import TOKENS, make

LIM = ExtractLimits(text_max_chars=100_000, image_max_edge_px=1568, pdf_render_pages_max=5)


def _run(src: Path, tmp_path: Path, lim: ExtractLimits = LIM, ext: str | None = None) -> tuple[dict, Path]:
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    meta = process(src, src.suffix.lower() if ext is None else ext, out, lim)
    return meta, out


def _text(out: Path) -> str:
    return (out / "text.txt").read_text(encoding="utf-8")


def test_from_config_takes_the_three_limits():
    from agenticops.config import ChatUploadSettings
    lim = ExtractLimits.from_config(ChatUploadSettings(text_max_chars=5000, image_max_edge_px=800,
                                                       pdf_render_pages_max=2))
    assert lim == ExtractLimits(text_max_chars=5000, image_max_edge_px=800, pdf_render_pages_max=2)


def test_text_pdf_has_text_layer(tmp_path):
    meta, out = _run(make("pdf", tmp_path / "in"), tmp_path)
    assert meta["pages"] == 3 and meta["has_text_layer"] is True and meta["rendered_pages"] == 0
    assert TOKENS["pdf"] in _text(out)
    assert (out / "thumb.jpg").is_file()
    assert len(meta["sha256"]) == 64


def test_scanned_pdf_renders_pages(tmp_path):
    from PIL import Image
    meta, out = _run(make("scan_pdf", tmp_path / "in"), tmp_path)
    assert meta["pages"] == 7 and meta["has_text_layer"] is False
    assert meta["rendered_pages"] == 5
    pages = sorted((out / "pages").glob("page-*.png"))
    assert [p.name for p in pages] == [f"page-{n}.png" for n in range(1, 6)]
    with Image.open(pages[0]) as im:
        assert max(im.size) <= 1568
    assert not (out / "text.txt").exists()


def test_scanned_pdf_render_count_follows_limit(tmp_path):
    lim = ExtractLimits(text_max_chars=100_000, image_max_edge_px=1000, pdf_render_pages_max=0)
    meta, out = _run(make("scan_pdf", tmp_path / "in"), tmp_path, lim)
    assert meta["rendered_pages"] == 0 and not (out / "pages").exists()


def test_encrypted_pdf_refused(tmp_path):
    with pytest.raises(ExtractError) as e:
        _run(make("encrypted_pdf", tmp_path / "in"), tmp_path)
    assert e.value.reason == "encrypted"


def test_corrupt_pdf_refused(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\nnot really a pdf")
    with pytest.raises(ExtractError) as e:
        _run(bad, tmp_path)
    assert e.value.reason == "corrupt"


def test_docx_paragraphs_and_tables(tmp_path):
    _, out = _run(make("docx", tmp_path / "in"), tmp_path)
    text = _text(out)
    assert TOKENS["docx"] in text
    assert "host\tstatus" in text and "web-01\tdegraded" in text


def test_xlsx_row_cap_reports_total_rows(tmp_path):
    meta, out = _run(make("xlsx", tmp_path / "in"), tmp_path)
    text = _text(out)
    sheet = meta["sheets"][0]
    assert sheet["name"] == "metrics" and sheet["rows"] == 3000 and sheet["rows_included"] == 2000
    assert "## Sheet: metrics (3000 rows × 4 cols; first 2000 rows included, 1000 more rows not included)" in text
    assert TOKENS["xlsx"] in text
    assert "web-0001\t1\t" + TOKENS["xlsx"] + "\n" in text   # the formula cell has no cached value → nothing


def test_xlsm_is_read_like_xlsx(tmp_path):
    _, out = _run(make("xlsm", tmp_path / "in"), tmp_path)
    assert TOKENS["xlsm"] in _text(out)


def test_pptx_slides_and_notes(tmp_path):
    meta, out = _run(make("pptx", tmp_path / "in"), tmp_path)
    text = _text(out)
    assert meta["slides"] == 1
    assert "## Slide 1" in text and TOKENS["pptx"] in text and "mention the rollback" in text


def test_gbk_tsv_decoded(tmp_path):
    meta, out = _run(make("gbk_tsv", tmp_path / "in"), tmp_path)
    assert "主机\t状态" in _text(out) and TOKENS["tsv"] in _text(out)
    assert meta["encoding"]


def test_longer_gbk_text_decoded(tmp_path):
    src = tmp_path / "notes.csv"
    src.write_bytes("服务器名称,状态,备注\nweb-01,正常,内存不足导致重启，已处理。\n".encode("gbk"))
    _, out = _run(src, tmp_path)
    assert "内存不足导致重启，已处理。" in _text(out)


def test_shift_jis_not_taken_for_gbk(tmp_path):
    src = tmp_path / "jp.csv"
    src.write_bytes("ホスト,状態\nweb-01,正常\n".encode("shift_jis"))
    _, out = _run(src, tmp_path)
    assert "ホスト,状態" in _text(out)


def test_utf16_bom_tsv_decoded(tmp_path):
    _, out = _run(make("utf16_tsv", tmp_path / "in"), tmp_path)
    text = _text(out)
    assert text.startswith("主机\t状态") and TOKENS["tsv"] in text


def test_html_visible_text_only(tmp_path):
    _, out = _run(make("html", tmp_path / "in"), tmp_path)
    text = _text(out)
    assert "Visible code " + TOKENS["html"] in text and "Status" in text
    assert "SCRIPT-ONLY" not in text and "color:red" not in text


@pytest.mark.parametrize("kind", ["txt", "md", "csv", "json", "log"])
def test_plain_text_types(tmp_path, kind):
    _, out = _run(make(kind, tmp_path / "in"), tmp_path)
    assert TOKENS[kind] in _text(out)


def test_python_shell_and_extensionless_files_are_text(tmp_path):
    for name, body in (("main.py", "print('hi')\n"), ("deploy.sh", "#!/bin/sh\necho ok\n"), ("Makefile", "all:\n")):
        src = tmp_path / "in" / name
        src.parent.mkdir(exist_ok=True)
        src.write_text(body)
        _, out = _run(src, tmp_path / name.replace(".", "_"))
        assert _text(out) == body


def test_empty_text_file(tmp_path):
    src = tmp_path / "empty.txt"
    src.write_bytes(b"")
    meta, out = _run(src, tmp_path)
    assert meta["chars"] == 0 and _text(out) == ""


@pytest.mark.parametrize("kind,fmt", [("heic", "jpeg"), ("bmp", "jpeg"), ("tiff", "jpeg"), ("jpg", "jpeg"),
                                      ("png", "jpeg"), ("gif", "jpeg"), ("webp", "jpeg")])
def test_heic_bmp_tiff_get_jpeg_or_png_preview(tmp_path, kind, fmt):
    from PIL import Image
    meta, out = _run(make(kind, tmp_path / "in"), tmp_path)
    assert meta["preview_format"] == fmt
    assert meta["width"] == 900 and meta["height"] == 300
    with Image.open(out / f"preview.{fmt}") as im:
        assert im.format == fmt.upper()
    with Image.open(out / "thumb.jpg") as im:
        assert max(im.size) <= 320


def test_png_with_alpha_keeps_png(tmp_path):
    meta, out = _run(make("png_alpha", tmp_path / "in"), tmp_path)
    assert meta["preview_format"] == "png" and (out / "preview.png").is_file()


def test_preview_long_edge_capped(tmp_path):
    from PIL import Image
    src = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), "white").save(src)
    meta, out = _run(src, tmp_path, ExtractLimits(100_000, 1000, 5))
    with Image.open(out / "preview.jpeg") as im:
        assert im.size == (1000, 250)
    assert meta["width"] == 4000


def test_noisy_image_preview_fits_bedrock_size(tmp_path):
    import os
    from PIL import Image
    from agenticops.chat.attachments.limits import BEDROCK_MAX_IMAGE_BYTES
    src = tmp_path / "noise.png"
    Image.frombytes("RGB", (3000, 3000), os.urandom(3000 * 3000 * 3)).save(src)
    _, out = _run(src, tmp_path, ExtractLimits(100_000, 8000, 5))
    assert (out / "preview.jpeg").stat().st_size <= BEDROCK_MAX_IMAGE_BYTES


def test_decompression_bomb_image_refused(tmp_path, monkeypatch):
    from PIL import Image
    from agenticops.chat.attachments import extract
    monkeypatch.setattr(extract, "MAX_IMAGE_PIXELS", 1000)   # 900×300 is > 2× this → Pillow's bomb error
    with pytest.raises(ExtractError) as e:
        _run(make("png", tmp_path / "in"), tmp_path)
    assert e.value.reason == "image_too_large"
    assert Image.MAX_IMAGE_PIXELS == 1000


def test_zip_bomb_refused(tmp_path):
    with pytest.raises(ExtractError) as e:
        _run(make("zip_bomb", tmp_path / "in"), tmp_path)
    assert e.value.reason == "archive_too_large"


def test_doc_and_xls_meta_only(tmp_path):
    for kind in ("doc", "xls"):
        meta, out = _run(make(kind, tmp_path / "in"), tmp_path / kind)
        assert set(meta) >= {"sha256", "chars", "truncated"} and not (out / "text.txt").exists()


def test_text_truncated_at_limit(tmp_path):
    src = tmp_path / "long.txt"
    src.write_text("x" * 5000)
    meta, out = _run(src, tmp_path, ExtractLimits(1000, 1568, 5))
    assert meta["truncated"] is True and meta["chars"] == 5000
    assert len(_text(out)) == 1000


def test_meta_is_json_serialisable(tmp_path):
    meta, _ = _run(make("xlsx", tmp_path / "in"), tmp_path)
    json.dumps(meta)


@pytest.mark.parametrize("kind", ["xlsx", "xlsm", "docx", "pptx", "pdf", "heic", "tsv"])
def test_stored_original_without_suffix_is_read(tmp_path, kind):
    """Uploads are stored as `<dir>/original` — no extension; every parser must take the type from `ext`."""
    import shutil
    src = make(kind, tmp_path / "in")
    stored = tmp_path / "stored" / "original"
    stored.parent.mkdir()
    shutil.copyfile(src, stored)
    meta, out = _run(stored, tmp_path, ext=src.suffix.lower())
    assert meta["sha256"]
    if kind not in ("heic",):
        assert TOKENS[kind] in _text(out)


# ── final review fixes ───────────────────────────────────────────────────────


def test_large_worksheet_entry_is_streamed_not_refused(tmp_path, monkeypatch):
    """A big sheet's XML is streamed by openpyxl read-only: the per-entry archive cap must not refuse it (a 1M-row
    xlsx unpacks one 197 MB sheet); other entries (docx, sharedStrings) keep the cap."""
    from agenticops.chat.attachments import extract
    monkeypatch.setattr(extract, "ZIP_MAX_ENTRY_BYTES", 50_000)   # the sheet is 410 KB
    meta, out = _run(make("xlsx", tmp_path / "in"), tmp_path)
    assert meta["sheets"][0]["rows"] == 3000 and TOKENS["xlsx"] in _text(out)
    with pytest.raises(ExtractError) as e:
        _run(make("zip_bomb", tmp_path / "in2"), tmp_path / "o2")
    assert e.value.reason == "archive_too_large"


def test_omitted_rows_are_said_in_the_sheet_header(tmp_path):
    lim = ExtractLimits(text_max_chars=5_000, image_max_edge_px=1568, pdf_render_pages_max=5)
    meta, out = _run(make("xlsx", tmp_path / "in"), tmp_path, lim)
    head = _text(out).split("\n", 1)[0]
    assert head.startswith("## Sheet: metrics (3000 rows × 4 cols") and "more rows not included" in head
    assert meta["sheets"][0]["rows_included"] < 3000


def test_sheet_without_dimension_is_not_padded_and_says_at_least(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook(write_only=True)   # write-only output carries no <dimension>
    ws = wb.create_sheet("stream")
    for i in range(2500):
        ws.append([f"h{i}", i])
    path = tmp_path / "stream.xlsx"
    wb.save(path)
    meta, out = _run(path, tmp_path)
    text = _text(out)
    assert "\nh1\t1\n" in text                          # two cells, not padded to 50 columns
    assert "at least 2000 rows" in text.split("\n", 1)[0]
    assert meta["sheets"][0]["cols"] == 2
