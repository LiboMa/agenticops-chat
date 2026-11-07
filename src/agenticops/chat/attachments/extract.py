"""Turn one uploaded file into model-independent artifacts. Runs only inside the worker subprocess
(chat/attachments/worker.py): the native parsers (PyMuPDF, libheif, lxml) never run in the service process.

Artifacts written into `out_dir` (each optional): `text.txt` (UTF-8), `preview.png|preview.jpeg` (the image a model
and a browser get), `thumb.jpg` (long edge ≤ 320), `pages/page-<n>.png` (a scanned PDF's first pages). `process`
returns the metadata; an expected refusal is an ExtractError with a reason code.
"""
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from agenticops.chat.attachments.limits import BEDROCK_MAX_IMAGE_BYTES
from agenticops.chat.attachments.types import SUPPORTED

PDF_MAX_PAGES = 200
SHEET_MAX_ROWS = 2000
SHEET_MAX_COLS = 50
THUMB_EDGE = 320
MAX_IMAGE_PIXELS = 100_000_000
ZIP_MAX_TOTAL_BYTES = 200 * 1024 * 1024
ZIP_MAX_ENTRY_BYTES = 50 * 1024 * 1024
ZIP_MAX_ENTRIES = 10_000
_TEXT_LAYER_MIN_CHARS = 50
_BOM_CODECS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
               (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))


class ExtractError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class ExtractLimits:
    text_max_chars: int
    image_max_edge_px: int
    pdf_render_pages_max: int

    @classmethod
    def from_config(cls, cfg) -> "ExtractLimits":
        return cls(cfg.text_max_chars, cfg.image_max_edge_px, cfg.pdf_render_pages_max)


# ── helpers ──────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_text(out_dir: Path, text: str, lim: ExtractLimits, meta: dict) -> None:
    meta["chars"] = len(text)
    meta["truncated"] = len(text) > lim.text_max_chars
    (out_dir / "text.txt").write_text(text[:lim.text_max_chars], encoding="utf-8")


def _decode(raw: bytes) -> tuple[str, str]:
    for bom, codec in _BOM_CODECS:
        if raw.startswith(bom):
            return raw.decode(codec), codec
    if not raw:
        return "", "utf-8"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    from charset_normalizer import from_bytes
    matches = list(from_bytes(raw))
    if not matches:
        raise ExtractError("undecodable")
    best = matches[0]
    # A short text is often a tie (cp949 and gb18030 both score 0 chaos on a few GBK words): prefer gb18030 when the
    # bytes read as GBK land almost only in GB2312's symbol and common-hanzi rows (Shift-JIS / Big5 bytes do not).
    if best.encoding != "gb18030" and _gb_common_ratio(raw) >= 0.8:
        best = next((m for m in matches if m.encoding == "gb18030" and m.chaos <= best.chaos), best)
    return str(best), best.encoding


def _gb_common_ratio(raw: bytes) -> float:
    """Share of the double-byte characters whose GBK lead byte is in GB2312's rows of symbols (0xA1–0xA9) or
    level-1 hanzi (0xB0–0xD7), with a GB2312 trail byte."""
    i = total = common = 0
    n = len(raw)
    while i < n:
        b = raw[i]
        if b < 0x80:
            i += 1
            continue
        if i + 1 >= n:
            break
        total += 1
        if (0xA1 <= b <= 0xA9 or 0xB0 <= b <= 0xD7) and 0xA1 <= raw[i + 1] <= 0xFE:
            common += 1
        i += 2
    return common / total if total else 0.0


class _VisibleText(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _html_text(html: str) -> str:
    p = _VisibleText()
    p.feed(html)
    p.close()
    return "\n".join(p.parts)


def _check_zip(src: Path) -> None:
    try:
        with zipfile.ZipFile(src) as z:
            infos = z.infolist()
    except zipfile.BadZipFile as e:
        raise ExtractError("corrupt", str(e)) from None
    if len(infos) > ZIP_MAX_ENTRIES or sum(i.file_size for i in infos) > ZIP_MAX_TOTAL_BYTES \
            or any(i.file_size > ZIP_MAX_ENTRY_BYTES for i in infos):
        raise ExtractError("archive_too_large")


def _cell(value) -> str:
    return "" if value is None else re.sub(r"[\t\r\n]+", " ", str(value))


# ── images ───────────────────────────────────────────────────────────────────


def _pil():
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:  # pragma: no cover — the `files` extra installs it
        pass
    return Image


def _has_alpha(im) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)


def _encode(im, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if fmt == "png":
        im.save(buf, format="PNG", optimize=True)
    else:
        im.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _fit_bedrock(im, fmt: str) -> tuple[bytes, str]:
    """The encoded preview within Bedrock's image byte limit: as is, then JPEG q70 at 0.75× per round (≤ 4)."""
    data = _encode(im, fmt, 85)
    rounds = 0
    while len(data) > BEDROCK_MAX_IMAGE_BYTES:
        if rounds == 4:
            raise ExtractError("image_too_large")
        im = im.resize((max(1, int(im.width * 0.75)), max(1, int(im.height * 0.75))))
        fmt = "jpeg"
        data = _encode(im, fmt, 70)
        rounds += 1
    return data, fmt


def _thumb(im, out_dir: Path) -> None:
    Image = _pil()
    t = im.copy()
    t.thumbnail((THUMB_EDGE, THUMB_EDGE))
    if _has_alpha(t):
        bg = Image.new("RGB", t.size, "white")
        bg.paste(t.convert("RGBA"), mask=t.convert("RGBA").split()[-1])
        t = bg
    t.convert("RGB").save(out_dir / "thumb.jpg", format="JPEG", quality=80)


def _image(src: Path, out_dir: Path, lim: ExtractLimits, meta: dict) -> None:
    Image = _pil()
    from PIL import ImageOps, UnidentifiedImageError
    try:
        with Image.open(src) as opened:
            opened.seek(0)
            im = ImageOps.exif_transpose(opened)
            im.load()
    except Image.DecompressionBombError:
        raise ExtractError("image_too_large") from None
    except (UnidentifiedImageError, OSError, ValueError, EOFError) as e:
        raise ExtractError("corrupt", str(e)) from None
    meta["width"], meta["height"] = im.size
    alpha = _has_alpha(im)
    im = im.convert("RGBA" if alpha else "RGB")
    im.thumbnail((lim.image_max_edge_px, lim.image_max_edge_px))
    data, fmt = _fit_bedrock(im, "png" if alpha else "jpeg")
    (out_dir / f"preview.{fmt}").write_bytes(data)
    meta["preview_format"] = fmt
    _thumb(im, out_dir)


# ── documents ────────────────────────────────────────────────────────────────


def _pixmap_png(page, edge: int) -> bytes:
    import fitz
    w, h = page.rect.width, page.rect.height
    scale = min(edge / max(w, h, 1), 4.0)
    for _ in range(5):
        data = page.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")
        if len(data) <= BEDROCK_MAX_IMAGE_BYTES:
            return data
        scale *= 0.75
    raise ExtractError("image_too_large")


def _pdf(src: Path, out_dir: Path, lim: ExtractLimits, meta: dict) -> None:
    import fitz
    try:
        doc = fitz.open(src)
    except Exception as e:  # PyMuPDF raises its own FileDataError / RuntimeError
        raise ExtractError("corrupt", str(e)) from None
    with doc:
        if doc.needs_pass:
            raise ExtractError("encrypted")
        meta["pages"] = doc.page_count
        if doc.page_count == 0:
            raise ExtractError("corrupt", "no pages")
        parts, size = [], 0
        for i in range(min(doc.page_count, PDF_MAX_PAGES)):
            body = doc[i].get_text().strip()
            parts.append(f"--- Page {i + 1} ---\n{body}")
            size += len(body)
            if size > lim.text_max_chars:
                break
        has_text = len(re.sub(r"\s+", "", "".join(p.split("\n", 1)[1] for p in parts))) >= _TEXT_LAYER_MIN_CHARS
        meta["has_text_layer"] = has_text
        meta["rendered_pages"] = 0
        if has_text:
            _write_text(out_dir, "\n\n".join(parts), lim, meta)
            if doc.page_count > PDF_MAX_PAGES:
                meta["truncated"] = True
        elif lim.pdf_render_pages_max:
            pages_dir = out_dir / "pages"
            pages_dir.mkdir()
            for i in range(min(doc.page_count, lim.pdf_render_pages_max)):
                (pages_dir / f"page-{i + 1}.png").write_bytes(_pixmap_png(doc[i], lim.image_max_edge_px))
                meta["rendered_pages"] = i + 1
        Image = _pil()
        with Image.open(io.BytesIO(_pixmap_png(doc[0], THUMB_EDGE * 2))) as first:
            first.load()
            _thumb(first, out_dir)


def _docx(src: Path, out_dir: Path, lim: ExtractLimits, meta: dict) -> None:
    import docx
    d = docx.Document(str(src))
    lines = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        lines.append("")
        for row in table.rows:
            lines.append("\t".join(_cell(c.text) for c in row.cells))
    _write_text(out_dir, "\n".join(lines), lim, meta)


def _xlsx(src: Path, out_dir: Path, lim: ExtractLimits, meta: dict) -> None:
    import openpyxl
    wb = openpyxl.load_workbook(str(src), read_only=True, data_only=True)
    try:
        blocks, sheets, size = [], [], 0
        for ws in wb.worksheets:
            rows_total = ws.max_row or 0
            cols_total = ws.max_column or 0
            lines, included = [], 0
            for values in ws.iter_rows(max_col=min(cols_total or SHEET_MAX_COLS, SHEET_MAX_COLS), values_only=True):
                if included == SHEET_MAX_ROWS or size > lim.text_max_chars:
                    break
                line = "\t".join(_cell(v) for v in values)
                lines.append(line)
                size += len(line) + 1
                included += 1
            rows_total = max(rows_total, included)
            head = f"## Sheet: {ws.title} ({rows_total} rows × {cols_total} cols)"
            if cols_total > SHEET_MAX_COLS:
                head += f" — first {SHEET_MAX_COLS} columns"
            body = "\n".join(lines)
            if rows_total > included:
                body += f"\n[… {rows_total - included} more rows not included]"
            blocks.append(f"{head}\n{body}")
            sheets.append({"name": ws.title, "rows": rows_total, "cols": cols_total, "rows_included": included})
        meta["sheets"] = sheets
        _write_text(out_dir, "\n\n".join(blocks), lim, meta)
    finally:
        wb.close()


def _pptx(src: Path, out_dir: Path, lim: ExtractLimits, meta: dict) -> None:
    from pptx import Presentation
    prs = Presentation(str(src))
    blocks = []
    for n, slide in enumerate(prs.slides, 1):
        lines = [f"## Slide {n}"]
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                lines.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    lines.append("\t".join(_cell(c.text) for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            lines.append("Notes: " + slide.notes_slide.notes_text_frame.text.strip())
        blocks.append("\n".join(lines))
    meta["slides"] = len(prs.slides)
    _write_text(out_dir, "\n\n".join(blocks), lim, meta)


def _text(src: Path, ext: str, out_dir: Path, lim: ExtractLimits, meta: dict) -> None:
    text, encoding = _decode(src.read_bytes())
    meta["encoding"] = encoding
    if ext in (".html", ".htm"):
        text = _html_text(text)
    _write_text(out_dir, text, lim, meta)


# ── entry ────────────────────────────────────────────────────────────────────


def process(src: Path, ext: str, out_dir: Path, lim: ExtractLimits) -> dict:
    """Write the artifacts for `src` (a file of supported extension `ext`) into `out_dir`; return the metadata.

    Raises ExtractError(reason) for a file that cannot or must not be read: encrypted, archive_too_large,
    image_too_large, undecodable, corrupt (any parser failure)."""
    ft = SUPPORTED.get(ext)
    if ft is None:
        raise ExtractError("unsupported_type", ext)
    meta: dict = {"sha256": _sha256(src), "chars": 0, "truncated": False}
    try:
        if ft.kind == "image":
            _image(src, out_dir, lim, meta)
        elif ft.kind == "pdf":
            _pdf(src, out_dir, lim, meta)
        elif ft.kind == "office":
            if ext in (".doc", ".xls"):
                return meta          # Claude reads the original; nothing to extract
            _check_zip(src)
            {".docx": _docx, ".xlsx": _xlsx, ".xlsm": _xlsx, ".pptx": _pptx}[ext](src, out_dir, lim, meta)
        else:
            _text(src, ext, out_dir, lim, meta)
    except ExtractError:
        raise
    except Exception as e:  # any parser's own failure on a malformed file
        raise ExtractError("corrupt", f"{type(e).__name__}: {e}") from None
    return meta
