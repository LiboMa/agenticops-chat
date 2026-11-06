"""Report export (MVP-2.7.0 S6): one report version in zh, en or both, as a standalone file.

HTML is always available (a page with print rules: A4, one paper per language, a page break between them); pdf and
docx only when the server has weasyprint / python-docx. Raw HTML in a report body is escaped (python-markdown would
pass it through), so an exported file can never run a script. Export never publishes.
"""
import html as _html
import re

from agenticops.notify import report_formatter as rf

_CODE = re.compile(r"(`{3}.*?`{3}|`[^`\n]+`)", re.S)

CSS = """
body{margin:0;background:#f4f6fa;font:15px/1.6 -apple-system,"Segoe UI",Roboto,"Noto Sans SC","PingFang SC",sans-serif;color:#1f2937}
.paper{max-width:860px;margin:24px auto;background:#fff;border:1px solid #dbe3ef;border-radius:8px;padding:32px 40px}
.brand{font-size:12px;color:#64748b;margin-bottom:8px}
h1,h2,h3{color:#0f2a5c;line-height:1.3}h2{break-after:avoid}
pre{background:#f1f5f9;padding:12px;border-radius:6px;overflow:auto;white-space:pre-wrap}code{font-family:ui-monospace,Menlo,monospace}
table{border-collapse:collapse}td,th{border:1px solid #dbe3ef;padding:4px 8px}tr{break-inside:avoid}
.note{font-size:12px;color:#64748b;margin-top:24px;border-top:1px solid #e2e8f0;padding-top:8px}
@page{size:A4;margin:16mm}
@media print{body{background:#fff}.paper{border:0;margin:0;max-width:none;padding:0}}
.paper + .paper{break-before: page}
"""


def available_formats() -> list[str]:
    return ["html"] + (["pdf"] if rf._HAS_WEASYPRINT else []) + (["docx"] if rf._HAS_DOCX else [])


def _escape_raw_html(markdown: str) -> str:
    """Escape < and > outside code (markdown escapes inside code itself), keeping entities as they are."""
    parts = _CODE.split(markdown or "")
    return "".join(p if i % 2 else p.replace("<", "&lt;").replace(">", "&gt;") for i, p in enumerate(parts))


def markdown_to_html(markdown: str) -> str:
    safe = _escape_raw_html(markdown)
    if not rf._HAS_MARKDOWN:
        return f"<pre>{_html.escape(markdown or '')}</pre>"
    return rf._md.markdown(safe, extensions=["tables", "fenced_code", "nl2br"])


NOTES = {"zh": "报告绑定它的版本和证据；切换语言不改变任何事实或状态。",
         "en": "The report stays bound to its version and evidence; switching language does not change facts."}


def build_html(report, papers: list[tuple[str, str]]) -> str:
    """papers: [(language, markdown)] in the order shown."""
    title = _html.escape(report.title or "")
    articles = "".join(
        f'<article class="paper" lang="{lang}"><div class="brand">AgenticOps · R{report.id} · '
        f'v{report.content_version or 1} · {lang}</div>{markdown_to_html(body)}'
        f'<div class="note">{_html.escape(NOTES[lang])}</div></article>'
        for lang, body in papers)
    page_lang = papers[0][0] if len(papers) == 1 else "zh"
    return (f'<!DOCTYPE html>\n<html lang="{page_lang}"><head><meta charset="utf-8"><title>{title}</title>'
            f"<style>{CSS}</style></head><body>{articles}</body></html>")


def build_export(report, papers: list[tuple[str, str]], fmt: str) -> tuple[bytes, str, str]:
    """→ (body, content_type, extension)."""
    if fmt == "html":
        return build_html(report, papers).encode("utf-8"), "text/html; charset=utf-8", "html"
    joined = "\n\n---\n\n".join(body for _, body in papers)
    out = rf.format_report(report.title or "", _escape_raw_html(joined), [fmt], {"report_type": report.report_type})
    if not out:
        raise RuntimeError(f"{fmt} could not be generated")
    return out[0].content, out[0].content_type, out[0].extension.lstrip(".")


def filename(report, language: str, ext: str) -> str:
    return f"AgenticOps_R{report.id}_v{report.content_version or 1}_{language}.{ext}"
