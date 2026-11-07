"""Chat attachments in the DB (2026-11-07): staging, processing, who may see one, binding it to a message, cleanup.

A staged attachment (session_id NULL) belongs to the actor who uploaded it (its actor key; `web:anonymous` with auth
off). Once a send binds it, it follows its session: whoever may see the session (services/chat_access) may fetch
it, and it is deleted with the session. Errors are AttachmentError(status, code, detail); the routers map them.
"""
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from agenticops.chat.attachments import store
from agenticops.chat.attachments.delivery import Prepared
from agenticops.chat.attachments.types import FileType
from agenticops.models import ChatAttachment, ChatSession, get_db_session

logger = logging.getLogger(__name__)
_MIB = 1024 * 1024
_FILENAME_MAX = 255
_SWEEP_EVERY_SECONDS = 3600
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-attachment")
_last_sweep = 0.0
_sweep_lock = threading.Lock()


class AttachmentError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _not_found() -> AttachmentError:
    return AttachmentError(404, "not_found", "Attachment not found")


def _cut_name(filename: str) -> str:
    name = (filename or "file").replace("/", "_").replace("\\", "_")
    if len(name) <= _FILENAME_MAX:
        return name
    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) <= 16:
        return stem[:_FILENAME_MAX - len(ext) - 1] + "." + ext
    return name[:_FILENAME_MAX]


def create_staged(db, *, owner_key: str, filename: str, ft: FileType, size: int) -> ChatAttachment:
    att = ChatAttachment(id=uuid.uuid4().hex, owner_key=owner_key, filename=_cut_name(filename), ext=ft.ext,
                         kind=ft.kind, size=size, status="processing")
    db.add(att)
    db.flush()
    return att


def process_now(att_id: str) -> None:
    """Run the worker on a staged attachment and record ready / failed. A row deleted meanwhile takes its files."""
    from agenticops.chat import upload_config
    from agenticops.chat.attachments import worker
    from agenticops.chat.attachments.extract import ExtractLimits
    with get_db_session() as db:
        att = db.get(ChatAttachment, att_id)
        if att is None:
            store.remove_staged(att_id)
            return
        ext = att.ext
    d = store.staging_dir(att_id)
    result = worker.run(d / "original", ext, d, ExtractLimits.from_config(upload_config.effective()))
    if not result.ok:
        logger.warning("chat attachment %s failed (%s): %s", att_id, result.reason, worker.stderr_tail(d)[-500:])
    with get_db_session() as db:
        updated = db.query(ChatAttachment).filter(ChatAttachment.id == att_id).update(
            {"status": "ready" if result.ok else "failed", "reason": None if result.ok else result.reason,
             "meta": result.meta}, synchronize_session=False)
    if not updated:
        store.remove_staged(att_id)


def submit_processing(att_id: str) -> Future:
    """Process in the background (two at a time): the upload request returns at once with status `processing`."""
    def _run():
        try:
            process_now(att_id)
        except Exception:
            logger.exception("chat attachment %s: processing crashed", att_id)
            with get_db_session() as db:
                db.query(ChatAttachment).filter(ChatAttachment.id == att_id).update(
                    {"status": "failed", "reason": "processing_failed"}, synchronize_session=False)
    return _pool.submit(_run)


def visible(db, att_id: str, actor) -> ChatAttachment:
    """The attachment, or AttachmentError 404 (missing and not-yours read the same)."""
    from agenticops.services import chat_access
    att = db.get(ChatAttachment, att_id) if att_id else None
    if att is None:
        raise _not_found()
    if att.session_id is None:
        if att.owner_key != actor.key:
            raise _not_found()
        return att
    row = db.get(ChatSession, att.session_id)
    if row is None or not chat_access.can_see(row, actor):
        raise _not_found()
    return att


def session_uuid_of(db, att: ChatAttachment) -> Optional[str]:
    if att.session_id is None:
        return None
    row = db.get(ChatSession, att.session_id)
    return row.session_id if row else None


def check_for_send(db, ids: list[str], actor, cfg) -> list[ChatAttachment]:
    """The caller's staged attachments `ids`, in order, if they may be sent together under `cfg`."""
    if len(ids) != len(set(ids)) or len(ids) > cfg.max_files:
        raise AttachmentError(422, "too_many_attachments",
                              f"At most {cfg.max_files} different attachments per message")
    rows = {a.id: a for a in db.query(ChatAttachment).filter(ChatAttachment.id.in_(ids)).all()} if ids else {}
    atts = []
    for att_id in ids:
        att = rows.get(att_id)
        if att is None or att.owner_key != actor.key or att.session_id is not None:
            raise AttachmentError(422, "attachment_unavailable",
                                  "An attachment is missing, already sent, or not yours — attach it again")
        atts.append(att)
    if any(a.status == "processing" for a in atts):
        raise AttachmentError(409, "attachments_processing", "Attachments are still being processed")
    if sum(a.size for a in atts) > cfg.max_total_mb * _MIB:
        raise AttachmentError(422, "attachments_too_large",
                              f"The attachments of one message may total at most {cfg.max_total_mb} MB")
    return atts


def bind(db, atts: list[ChatAttachment], session_row: ChatSession, message_id: Optional[int]) -> None:
    """Bind the attachments to the session and message — all of them, only while still unsent (compare-and-set)."""
    ids = [a.id for a in atts]
    if not ids:
        return
    moved = db.query(ChatAttachment).filter(ChatAttachment.id.in_(ids), ChatAttachment.session_id.is_(None)).update(
        {"session_id": session_row.id, "message_id": message_id}, synchronize_session=False)
    if moved != len(ids):
        raise AttachmentError(409, "attachment_unavailable", "An attachment was just sent with another message")
    for att in atts:
        att.session_id, att.message_id = session_row.id, message_id


def move_bound(att_ids: list[str], session_uuid: str) -> None:
    """After the send commits: move the files under the session — unless the session was deleted meanwhile."""
    if not att_ids:
        return
    with get_db_session() as db:
        exists = db.query(ChatSession.id).filter(ChatSession.session_id == session_uuid).first() is not None
    if exists:
        store.move_into_session(att_ids, session_uuid)


def prepared(att: ChatAttachment, session_uuid: Optional[str]) -> Prepared:
    """What delivery needs. With `session_uuid`, a bound row's directory is the session's (where move_bound puts it)."""
    d: Path = (store.session_root(session_uuid) / att.id if (session_uuid and att.session_id is not None)
               else store.attachment_dir(att, session_uuid))
    return Prepared(id=att.id, filename=att.filename, ext=att.ext, kind=att.kind, size=att.size,
                    status=att.status, reason=att.reason, dir=d, meta=dict(att.meta or {}))


def delete_staged(db, att_id: str, actor) -> None:
    att = visible(db, att_id, actor)
    if att.session_id is not None:
        raise AttachmentError(409, "attachment_bound", "A sent attachment is deleted with its chat")
    db.delete(att)
    db.flush()
    store.remove_staged(att_id)


def delete_for_session(db, session_pk: int) -> None:
    db.query(ChatAttachment).filter(ChatAttachment.session_id == session_pk).delete(synchronize_session=False)


def sweep_staged(now: Optional[datetime] = None) -> int:
    """Remove unsent uploads older than staged_ttl_hours, staging dirs without a row and session dirs without a
    session; move a bound attachment still in staging to its session. → directories / rows removed."""
    from agenticops.chat import upload_config
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=upload_config.effective().staged_ttl_hours)).replace(tzinfo=None)
    removed = 0
    rehome: dict[str, list[str]] = {}
    with get_db_session() as db:
        expired = [a.id for a in db.query(ChatAttachment).filter(ChatAttachment.session_id.is_(None),
                                                                  ChatAttachment.created_at < cutoff).all()]
        if expired:
            db.query(ChatAttachment).filter(ChatAttachment.id.in_(expired)).delete(synchronize_session=False)
        staged_on_disk = store.staged_ids()
        rows = {a.id: a for a in db.query(ChatAttachment).filter(ChatAttachment.id.in_(staged_on_disk)).all()} \
            if staged_on_disk else {}
        sessions = {s.id: s.session_id for s in db.query(ChatSession.id, ChatSession.session_id).all()}
        for att_id in staged_on_disk:
            att = rows.get(att_id)
            if att is not None and att.session_id is not None and att.session_id in sessions:
                rehome.setdefault(sessions[att.session_id], []).append(att_id)
        live_session_uuids = set(sessions.values())
    for att_id in staged_on_disk:
        if att_id in expired or att_id not in rows:
            store.remove_staged(att_id)
            removed += 1
    removed += len([a for a in expired if a not in staged_on_disk])
    for session_uuid, ids in rehome.items():
        store.move_into_session(ids, session_uuid)
    for name in store.session_dirs() - live_session_uuids:
        store.remove_session(name)
        removed += 1
    return removed


def maybe_sweep() -> None:
    """At most once an hour per process (called on upload, so no schedule is needed)."""
    global _last_sweep
    with _sweep_lock:
        if time.monotonic() - _last_sweep < _SWEEP_EVERY_SECONDS and _last_sweep:
            return
        _last_sweep = time.monotonic()
    try:
        sweep_staged()
    except Exception:
        logger.exception("chat attachment sweep failed")


def discard_unbound(att_ids: list[str]) -> None:
    """Remove the given uploads that are still unsent (a multipart send that did not bind them)."""
    if not att_ids:
        return
    with get_db_session() as db:
        unbound = [a.id for a in db.query(ChatAttachment).filter(ChatAttachment.id.in_(att_ids),
                                                                 ChatAttachment.session_id.is_(None)).all()]
        if unbound:
            db.query(ChatAttachment).filter(ChatAttachment.id.in_(unbound)).delete(synchronize_session=False)
    for att_id in unbound:
        store.remove_staged(att_id)


def filenames(att_ids: list[str], actor) -> list[str]:
    """The names of the caller's uploads among `att_ids`, in order (for a message sent without text)."""
    with get_db_session() as db:
        rows = {a.id: a.filename for a in db.query(ChatAttachment).filter(
            ChatAttachment.id.in_(att_ids), ChatAttachment.owner_key == actor.key).all()}
    return [rows[i] for i in att_ids if i in rows]


def record_deliveries(message_id: int, deliveries: list[dict]) -> None:
    """Write how each attachment reached the model onto its message (`delivery`, `reason` per id)."""
    from agenticops.models import ChatMessage
    by_id = {d["id"]: d for d in deliveries}
    with get_db_session() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None or not isinstance(msg.attachments, list):
            return
        msg.attachments = [{**a, "delivery": by_id[a["id"]]["delivery"], "reason": by_id[a["id"]]["reason"]}
                           if isinstance(a, dict) and a.get("id") in by_id else a for a in msg.attachments]
