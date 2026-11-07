"""Which files a chat message may carry, and whether a file's first bytes match its extension."""
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal, Optional

Kind = Literal["image", "pdf", "office", "text"]


@dataclass(frozen=True)
class FileType:
    ext: str                      # lowercase with the dot; "" = no extension
    kind: Kind
    native_format: Optional[str]  # the Converse image/document format when Bedrock takes the original
    mime: str


def _t(ext: str, kind: Kind, native: Optional[str], mime: str) -> tuple[str, FileType]:
    return ext, FileType(ext, kind, native, mime)


# The text types the chat accepted before 2026-11-07 stay accepted (no regression), plus .htm, .tsv and no extension.
_TEXT = {
    ".txt": "text/plain", ".log": "text/plain", ".md": "text/markdown", ".json": "application/json",
    ".yaml": "application/yaml", ".yml": "application/yaml", ".toml": "text/plain", ".ini": "text/plain",
    ".cfg": "text/plain", ".conf": "text/plain", ".sh": "text/x-shellscript", ".py": "text/x-python",
    ".js": "text/javascript", ".ts": "text/plain", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".xml": "application/xml", ".html": "text/html", ".htm": "text/html", ".tf": "text/plain", ".hcl": "text/plain",
    "": "text/plain",
}

SUPPORTED: dict[str, FileType] = dict([
    _t(".png", "image", "png", "image/png"),
    _t(".jpg", "image", "jpeg", "image/jpeg"),
    _t(".jpeg", "image", "jpeg", "image/jpeg"),
    _t(".gif", "image", "gif", "image/gif"),
    _t(".webp", "image", "webp", "image/webp"),
    _t(".bmp", "image", None, "image/bmp"),
    _t(".tif", "image", None, "image/tiff"),
    _t(".tiff", "image", None, "image/tiff"),
    _t(".heic", "image", None, "image/heic"),
    _t(".heif", "image", None, "image/heif"),
    _t(".pdf", "pdf", "pdf", "application/pdf"),
    _t(".docx", "office", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    _t(".xlsx", "office", "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    _t(".xlsm", "office", None, "application/vnd.ms-excel.sheet.macroEnabled.12"),
    _t(".pptx", "office", None, "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    _t(".doc", "office", "doc", "application/msword"),
    _t(".xls", "office", "xls", "application/vnd.ms-excel"),
    *(_t(ext, "text", None, mime) for ext, mime in _TEXT.items()),
])

_ZIP = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_HEIF_BRANDS = (b"heic", b"heix", b"mif1", b"msf1", b"heif")
_BOMS = (b"\xef\xbb\xbf", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff", b"\xff\xfe", b"\xfe\xff")


def classify(filename: str) -> Optional[FileType]:
    """The file's type by its extension (case-insensitive), or None when it is not supported."""
    return SUPPORTED.get(PurePath(filename or "").suffix.lower())


def _image_ok(ext: str, head: bytes) -> bool:
    if ext == ".png":
        return head.startswith(b"\x89PNG")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return head.startswith(b"GIF8")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == ".bmp":
        return head.startswith(b"BM")
    if ext in (".tif", ".tiff"):
        return head.startswith(b"II*\x00") or head.startswith(b"MM\x00*")
    return head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS   # .heic / .heif


def check_content(ft: FileType, head: bytes) -> Optional[str]:
    """None when the first bytes fit the type; else `content_mismatch` (wrong magic number) or `binary_text`
    (a "text" file with a NUL byte in its first 8 KiB and no UTF-8/16/32 byte-order mark)."""
    if ft.kind == "image":
        return None if _image_ok(ft.ext, head) else "content_mismatch"
    if ft.kind == "pdf":
        return None if b"%PDF-" in head[:1024] else "content_mismatch"
    if ft.kind == "office":
        magic = _OLE if ft.ext in (".doc", ".xls") else _ZIP
        return None if head.startswith(magic) else "content_mismatch"
    if head.startswith(_BOMS):
        return None
    return "binary_text" if b"\x00" in head[:8192] else None
