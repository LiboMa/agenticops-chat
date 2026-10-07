"""A report's content identity (MVP-2.7.0 S6): its sha256 and source language, stamped on every insert / update of a
Report row — so a rendering always knows which exact text it was made from, and a changed source makes it stale."""
import hashlib
import re

_FENCE = re.compile(r"```.*?```", re.S)
_CJK = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-z]")


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def detect_language(text: str) -> str:
    """zh when CJK characters are at least 15% of the letters (code blocks ignored), else en."""
    prose = _FENCE.sub(" ", text or "")
    cjk, latin = len(_CJK.findall(prose)), len(_LATIN.findall(prose))
    return "zh" if cjk and cjk / (cjk + latin) >= 0.15 else "en"


def stamp(report) -> None:
    report.content_hash = content_hash(report.content_markdown)
    report.source_language = detect_language(report.content_markdown)
    report.visibility = report.visibility or "workspace"
    report.content_version = report.content_version or 1


def register() -> None:
    from sqlalchemy import event
    from agenticops.models import Report
    if not event.contains(Report, "before_insert", _on_write):
        event.listen(Report, "before_insert", _on_write)
        event.listen(Report, "before_update", _on_write)


def _on_write(_mapper, _connection, target) -> None:
    stamp(target)
