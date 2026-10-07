"""Report renderings (MVP-2.7.0 S6): a report in Chinese and in English.

The source language is the source itself (ready, no row, no model). The other language is translated by the cheap
model at temperature 0 in a background thread (AgenticOps runs as ONE process, S1) with every protected value
masked first and checked after (services/content_protect) — a result that lost, duplicated or invented a value is
`failed`, never shown in part. Reading a rendering never calls a model; a rendering made from an older source is
`stale`. One lock per (report, version, language) and the source hash deduplicate the work.
"""
import logging
import threading
from datetime import datetime, timezone

from agenticops.config import settings
from agenticops.models import ContentRendering, Report, get_db_session
from agenticops.services.content_protect import ProtectedValuesChanged, protect, protected_hash, restore

logger = logging.getLogger(__name__)

LANGUAGES = ("zh", "en")
_NAMES = {"zh": "Simplified Chinese", "en": "English"}
_locks: dict[tuple, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(key: tuple) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _row(db, report_id: int, version: int, language: str):
    return (db.query(ContentRendering)
            .filter_by(entity_type="report", entity_id=report_id, source_version=version, language=language).first())


def rendering_view(db, report: Report, version: int, language: str) -> dict:
    """The contract's ContentRendering for one language of this report version. Never calls a model."""
    base = {"entity": {"entity_type": "report", "entity_id": report.id}, "source_version": version,
            "source_hash": report.content_hash, "language": language, "fields": {}}
    if language == (report.source_language or "en"):
        return {**base, "status": "ready", "body_markdown": report.content_markdown,
                "protected_value_hash": protected_hash(report.content_markdown), "generated_at": report.created_at,
                "error_code": None}
    row = _row(db, report.id, version, language)
    if row is None:
        return {**base, "status": "missing", "body_markdown": None, "protected_value_hash": None,
                "generated_at": None, "error_code": None}
    status = "stale" if row.status == "ready" and row.source_hash != report.content_hash else row.status
    return {**base, "status": status, "body_markdown": row.body_markdown if status == "ready" else None,
            "protected_value_hash": row.protected_value_hash, "generated_at": row.generated_at,
            "error_code": row.error_code}


def _call_model(prompt: str, model_id: str, max_tokens: int) -> str:
    """One Bedrock converse call at temperature 0 (the Signal Gate / RCA critic pattern)."""
    from agenticops.config import get_bedrock_boto_session
    client = get_bedrock_boto_session().client("bedrock-runtime")
    resp = client.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}],
                           inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
    return resp["output"]["message"]["content"][0]["text"]


def _prompt(masked: str, language: str) -> str:
    return (f"Translate the following markdown report into {_NAMES[language]}. Keep every placeholder like ⟦P3⟧ "
            "exactly as written, once each, and keep the markdown structure. Translate only the natural language. "
            "Output only the translation.\n\n" + masked)


def _save(report_id: int, version: int, language: str, source_hash: str, **fields) -> None:
    with get_db_session() as db:
        row = _row(db, report_id, version, language)
        if row is None:
            row = ContentRendering(entity_type="report", entity_id=report_id, source_version=version,
                                   language=language, source_hash=source_hash, status="pending")
            db.add(row)
        row.source_hash = source_hash
        row.generated_at = datetime.now(timezone.utc)
        for k, v in fields.items():
            setattr(row, k, v)


def translate_now(report_id: int, version: int, language: str) -> None:
    """The worker: translate one language of one report version (skips a ready, current rendering)."""
    with _lock(("report", report_id, version, language)):
        with get_db_session() as db:
            report = db.get(Report, report_id)
            if report is None or version != (report.content_version or 1) or language == report.source_language:
                return
            source, source_hash = report.content_markdown, report.content_hash
            existing = _row(db, report_id, version, language)
            if existing is not None and existing.status == "ready" and existing.source_hash == source_hash:
                return
        _save(report_id, version, language, source_hash, status="pending", error_code=None, body_markdown=None)
        masked, values = protect(source)
        model_id = settings.report_translation_model_id or settings.bedrock_model_id_cheap
        try:
            translated = _call_model(_prompt(masked, language), model_id, min(16000, 2 * len(masked) // 3 + 1000))
            body = restore(translated.strip(), values)
            if protected_hash(body) != protected_hash(source):
                raise ProtectedValuesChanged("restored values differ from the source")
        except ProtectedValuesChanged as e:
            logger.warning("Report %s %s translation refused: %s", report_id, language, e)
            _save(report_id, version, language, source_hash, status="failed", error_code="protected_values_changed")
            return
        except Exception:
            logger.warning("Report %s %s translation failed", report_id, language, exc_info=True)
            _save(report_id, version, language, source_hash, status="failed", error_code="model_failed")
            return
        _save(report_id, version, language, source_hash, status="ready", error_code=None, body_markdown=body,
              protected_value_hash=protected_hash(source))


def _start(report_id: int, version: int, language: str) -> None:
    threading.Thread(target=translate_now, args=(report_id, version, language), daemon=True,
                     name=f"report-translate-{report_id}-{language}").start()


def request_translations(report_id: int, version: int, languages: list[str]) -> list[dict]:
    """Queue what is missing, failed or stale; return each language's view (a queued one reads as pending)."""
    for lang in dict.fromkeys(languages):
        with get_db_session() as db:
            report = db.get(Report, report_id)
            view = rendering_view(db, report, version, lang)
            source_hash = report.content_hash
        if view["status"] in ("missing", "failed", "stale"):
            _save(report_id, version, lang, source_hash, status="pending", error_code=None, body_markdown=None)
            _start(report_id, version, lang)
    with get_db_session() as db:
        report = db.get(Report, report_id)
        return [rendering_view(db, report, version, lang) for lang in dict.fromkeys(languages)]


def enqueue_other_language(report_id: int) -> None:
    """After a report is saved: queue the language it is not in. Never raises (a report is saved regardless)."""
    try:
        with get_db_session() as db:
            report = db.get(Report, report_id)
            if report is None:
                return
            version, other = report.content_version or 1, "zh" if report.source_language == "en" else "en"
        request_translations(report_id, version, [other])
    except Exception:
        logger.warning("Could not queue the translation of report %s", report_id, exc_info=True)


def interrupt_pending() -> int:
    """Startup: a translation an earlier process was running was cut off — failed, so it can be retried."""
    with get_db_session() as db:
        return db.query(ContentRendering).filter(ContentRendering.status == "pending").update(
            {"status": "failed", "error_code": "interrupted"}, synchronize_session=False)
