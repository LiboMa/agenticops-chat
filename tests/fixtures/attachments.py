"""Attachment test files, generated at run time (no binaries in git). Each planted token is unique per file type,
so a live model test can ask for it and know the model read that file.

    from tests.fixtures.attachments import make, TOKENS
    path = make("pdf", tmp_path)
"""
import io
import zipfile
from pathlib import Path

TOKENS = {
    "txt": "AMBER-TXT-4417", "md": "BIRCH-MD-5521", "html": "CEDAR-HTML-6630", "htm": "DAHLIA-HTM-7742",
    "pdf": "EMBER-PDF-8853", "scan_pdf": "FROST-SCAN-9964", "docx": "GARNET-DOCX-1075", "doc": None,
    "xlsx": "HAZEL-XLSX-2186", "xlsm": "IVORY-XLSM-3297", "xls": None, "csv": "JASPER-CSV-4308",
    "tsv": "KELP-TSV-5419", "pptx": "LUPIN-PPTX-6520", "jpg": "MAPLE-JPG", "png": "NUTMEG-PNG", "gif": "OPAL-GIF",
    "webp": "PEARL-WEBP", "bmp": "QUARTZ-BMP", "tiff": "RAVEN-TIFF", "heic": "SAGE-HEIC",
    "json": "TOPAZ-JSON-7631", "log": "UMBER-LOG-8742",
}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def text_image(text: str, size=(900, 300), mode="RGB", bg="white") -> "Image.Image":
    """A picture with `text` drawn large enough for a vision model to read."""
    from PIL import Image, ImageDraw
    im = Image.new(mode, size, bg)
    ImageDraw.Draw(im).text((30, size[1] // 3), text, fill="black", font=_font(64))
    return im


def _pdf_text(path: Path, token: str, pages=3) -> Path:
    import fitz
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"Quarterly report page {i + 1}. The audit code is {token}.", fontsize=12)
    doc.save(path)
    return path


def _pdf_scanned(path: Path, token: str, pages=7) -> Path:
    import fitz
    doc = fitz.open()
    buf = io.BytesIO()
    text_image(f"SCANNED {token}", size=(1200, 400)).save(buf, format="PNG")
    for _ in range(pages):
        page = doc.new_page()
        page.insert_image(fitz.Rect(36, 36, 576, 216), stream=buf.getvalue())
    doc.save(path)
    return path


def _pdf_encrypted(path: Path) -> Path:
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "secret", fontsize=12)
    doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    return path


def _docx(path: Path, token: str) -> Path:
    import docx
    d = docx.Document()
    d.add_paragraph(f"Incident summary. Reference {token}.")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "host", "status"
    table.cell(1, 0).text, table.cell(1, 1).text = "web-01", "degraded"
    d.save(path)
    return path


def _xlsx(path: Path, token: str, rows=3000) -> Path:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "metrics"
    ws.append(["host", "cpu", "note"])
    for i in range(1, rows):
        ws.append([f"web-{i:04d}", i % 100, token if i == 1 else ""])
    ws["D2"] = "=B2*2"   # a formula: openpyxl writes no cached value
    wb.save(path)
    return path


def _pptx(path: Path, token: str) -> Path:
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Postmortem"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    box.text_frame.text = f"Root cause code {token}"
    slide.notes_slide.notes_text_frame.text = "Speaker note: mention the rollback."
    prs.save(path)
    return path


def _image(path: Path, fmt: str, token: str, alpha=False) -> Path:
    if fmt == "HEIF":
        import pillow_heif
        pillow_heif.register_heif_opener()
    im = text_image(token, mode="RGBA" if alpha else "RGB", bg=(255, 255, 255, 0) if alpha else "white")
    if fmt == "GIF":
        im = im.convert("P")
    im.save(path, format=fmt)
    return path


def _ole(path: Path) -> Path:
    path.write_bytes(OLE_MAGIC + b"\0" * 4088)
    return path


def zip_bomb_docx(path: Path, entry_mb=60) -> Path:
    """A .docx whose single entry inflates to `entry_mb` MiB (compresses to a few hundred KiB)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        with z.open("word/document.xml", "w", force_zip64=True) as f:
            chunk = b"\0" * (1024 * 1024)
            for _ in range(entry_mb):
                f.write(chunk)
    return path


def make(kind: str, d: Path, name: str | None = None) -> Path:
    """Write one fixture into directory `d` and return its path. `kind` is a TOKENS key or a special name."""
    d.mkdir(parents=True, exist_ok=True)
    tok = TOKENS.get(kind)
    ext = {"scan_pdf": "pdf", "png_alpha": "png", "encrypted_pdf": "pdf", "gbk_tsv": "tsv", "utf16_tsv": "tsv",
           "zip_bomb": "docx"}.get(kind, kind)
    path = d / (name or f"sample-{kind}.{ext}")
    if kind == "pdf":
        return _pdf_text(path, tok)
    if kind == "scan_pdf":
        return _pdf_scanned(path, tok)
    if kind == "encrypted_pdf":
        return _pdf_encrypted(path)
    if kind == "docx":
        return _docx(path, tok)
    if kind in ("xlsx", "xlsm"):
        return _xlsx(path, tok)
    if kind == "pptx":
        return _pptx(path, tok)
    if kind in ("doc", "xls"):
        return _ole(path)
    if kind == "zip_bomb":
        return zip_bomb_docx(path)
    images = {"jpg": "JPEG", "png": "PNG", "gif": "GIF", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF", "heic": "HEIF"}
    if kind in images:
        return _image(path, images[kind], tok)
    if kind == "png_alpha":
        return _image(path, "PNG", TOKENS["png"], alpha=True)
    if kind == "txt":
        path.write_text(f"Plain notes. Ticket {tok}.\n", encoding="utf-8")
    elif kind == "md":
        path.write_text(f"# Runbook\n\n- step one\n- marker `{tok}`\n", encoding="utf-8")
    elif kind in ("html", "htm"):
        path.write_text(f"<html><head><style>p{{color:red}}</style><script>var hidden='SCRIPT-ONLY';</script></head>"
                        f"<body><h1>Status</h1><p>Visible code {tok}</p></body></html>", encoding="utf-8")
    elif kind == "csv":
        path.write_text(f"host,status,code\nweb-01,ok,{tok}\n", encoding="utf-8")
    elif kind in ("tsv", "gbk_tsv"):
        path.write_bytes(f"主机\t状态\t编号\nweb-01\t正常\t{TOKENS['tsv']}\n".encode("gbk"))
    elif kind == "utf16_tsv":
        path.write_bytes(f"主机\t状态\nweb-01\t{TOKENS['tsv']}\n".encode("utf-16"))
    elif kind == "json":
        path.write_text(f'{{"service": "orders", "marker": "{tok}"}}\n', encoding="utf-8")
    elif kind == "log":
        path.write_text(f"2026-11-07T10:00:00Z ERROR pool exhausted id={tok}\n", encoding="utf-8")
    else:
        raise ValueError(kind)
    return path
