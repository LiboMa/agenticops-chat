"""Chat attachments: supported types, content checks, Bedrock document names (2026-11-07)."""
import re

import pytest

from agenticops.chat.attachments.limits import document_name
from agenticops.chat.attachments.types import check_content, classify

BEDROCK_NAME = re.compile(r"[A-Za-z0-9 ()\[\]-]+")
ATT_ID = "1a2b3c4d5e6f47089abcdef012345678"

# the 23 types of the spec's acceptance list, plus three of today's text types and a name without an extension
SPEC_TYPES = {
    "a.txt": "text", "a.md": "text", "a.html": "text", "a.htm": "text", "a.pdf": "pdf", "scan.pdf": "pdf",
    "a.docx": "office", "a.doc": "office", "a.xlsx": "office", "a.xlsm": "office", "a.xls": "office",
    "a.csv": "text", "a.tsv": "text", "a.pptx": "office", "a.jpg": "image", "a.png": "image", "a.gif": "image",
    "a.webp": "image", "a.bmp": "image", "a.tiff": "image", "a.heic": "image", "a.json": "text", "a.log": "text",
    "deploy.sh": "text", "main.py": "text", "main.tf": "text", "Makefile": "text",
}


def test_classify_every_spec_extension():
    for name, kind in SPEC_TYPES.items():
        ft = classify(name)
        assert ft is not None, name
        assert ft.kind == kind, name


def test_classify_is_case_insensitive_and_native_formats():
    assert classify("REPORT.PDF").native_format == "pdf"
    assert classify("x.JPG").native_format == "jpeg"
    assert classify("x.docx").native_format == "docx"
    assert classify("x.xls").native_format == "xls"
    assert classify("x.xlsm").native_format is None
    assert classify("x.pptx").native_format is None
    assert classify("x.heic").native_format is None   # only through the preview
    assert classify("x.bmp").native_format is None


@pytest.mark.parametrize("name", ["setup.exe", "logo.svg", "bundle.zip"])
def test_classify_unknown_returns_none(name):
    assert classify(name) is None


def test_magic_mismatch():
    assert check_content(classify("photo.png"), b"%PDF-1.7\n...") == "content_mismatch"
    assert check_content(classify("photo.png"), b"\x89PNG\r\n\x1a\n" + b"\0" * 20) is None


@pytest.mark.parametrize("name,head", [
    ("a.jpg", b"\xff\xd8\xff\xe0rest"), ("a.gif", b"GIF89a..."), ("a.webp", b"RIFF\x10\0\0\0WEBPVP8 "),
    ("a.bmp", b"BM\x36\0\0\0"), ("a.tiff", b"II*\0\x08\0"), ("a.tif", b"MM\0*\0\0"),
    ("a.heic", b"\0\0\0\x18ftypheic\0\0\0\0"), ("a.heif", b"\0\0\0\x18ftypmif1\0\0\0\0"),
    ("a.pdf", b"\n\n%PDF-1.4"), ("a.docx", b"PK\x03\x04\x14\0"), ("a.xlsx", b"PK\x03\x04"),
    ("a.pptx", b"PK\x03\x04"), ("a.xlsm", b"PK\x03\x04"),
    ("a.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\0"), ("a.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\0"),
])
def test_magic_matches(name, head):
    assert check_content(classify(name), head) is None


def test_office_with_other_magic_is_mismatch():
    assert check_content(classify("a.docx"), b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") == "content_mismatch"
    assert check_content(classify("a.doc"), b"PK\x03\x04") == "content_mismatch"
    assert check_content(classify("a.pdf"), b"x" * 2000 + b"%PDF-") == "content_mismatch"


def test_utf16_bom_tsv_passes():
    raw = "﻿name\tvalue\n名字\t1\n".encode("utf-16")
    assert b"\0" in raw[:8192]
    assert check_content(classify("data.tsv"), raw) is None


def test_utf32_and_utf8_bom_pass():
    assert check_content(classify("a.txt"), "﻿hi".encode("utf-32")) is None
    assert check_content(classify("a.txt"), b"\xef\xbb\xbfhi\0") is None


def test_nul_without_bom_is_binary_text():
    assert check_content(classify("notes.txt"), b"hello\0world") == "binary_text"
    assert check_content(classify("Makefile"), b"\x7fELF\x02\x01\x01\0") == "binary_text"
    assert check_content(classify("notes.txt"), "普通文本 plain".encode("gbk")) is None


def _name(filename, taken=None):
    out = document_name(ATT_ID, filename, set() if taken is None else taken)
    assert BEDROCK_NAME.fullmatch(out), out
    assert "  " not in out
    return out


def test_document_name_ascii():
    assert re.fullmatch(r"att-[0-9a-f]{12}-report-pdf", _name("report.pdf"))
    assert _name("report.pdf").startswith("att-1a2b3c4d5e6f-")   # 48 bits of the id: no two files share a key


def test_document_name_cjk_keeps_extension():
    assert re.fullmatch(r"att-[0-9a-f]{12}-docx", _name("报告.docx"))


def test_document_name_only_dots():
    assert re.fullmatch(r"att-[0-9a-f]{12}(-[A-Za-z0-9]+)?", _name("...."))


def test_document_name_no_double_space():
    out = _name("a  b.pdf")
    assert out.endswith("a-b-pdf") or out.endswith("a b-pdf")


def test_document_name_long_is_capped():
    assert len(_name("x" * 300 + ".pdf")) <= 200


def test_document_name_hostile_chars():
    _name('"; rm -rf / #.pdf')
    _name("emoji 😀 file.xlsx")


def test_document_name_same_name_twice_is_unique():
    taken: set[str] = set()
    first = _name("report.pdf", taken)
    second = _name("report.pdf", taken)
    third = _name("report.pdf", taken)
    assert len({first, second, third}) == 3
    assert {first, second, third} <= taken
