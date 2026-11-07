"""Chat attachments API (2026-11-07): upload one file at a time, follow its processing, fetch it, remove it.

    POST   /api/chat/attachments                      multipart, one `file` → 201 {id, filename, size, kind, status}
    GET    /api/chat/attachments/{id}                 state + public metadata
    GET    /api/chat/attachments/{id}/content?variant=original|preview|thumb|page-N
    DELETE /api/chat/attachments/{id}                 an unsent upload only

A message takes them by id (POST /api/chat/sessions/{sid}/messages `attachment_ids`). Who may see one:
chat/attachments/service.visible. Downloads never render in the browser: only images are inline, every response
carries nosniff + `Content-Security-Policy: sandbox`.
"""
import asyncio
import logging
import re
import shutil
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import UploadFile

from agenticops.auth.actor import Actor
from agenticops.chat import upload_config
from agenticops.chat.attachments import service, store
from agenticops.chat.attachments.service import AttachmentError
from agenticops.chat.attachments.types import SUPPORTED, check_content, classify
from agenticops.config import get_trace_id
from agenticops.models import get_db_session
from agenticops.web.deps import current_actor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat-attachments"])

_MIB = 1024 * 1024
_FORM_OVERHEAD = 64 * 1024
_INLINE_ORIGINALS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_PUBLIC_META = ("pages", "has_text_layer", "rendered_pages", "sheets", "slides", "width", "height", "chars",
                "truncated")
_ASCII_UNSAFE = re.compile(r"[^A-Za-z0-9._ ()-]+")
_SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox",
                     "Cache-Control": "private, max-age=3600"}


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code, "trace_id": get_trace_id() or None})


def _from(e: AttachmentError) -> JSONResponse:
    return _error(e.status, e.code, e.detail)


def body_of(att, session_uuid) -> dict:
    meta = att.meta or {}
    return {"id": att.id, "filename": att.filename, "size": att.size, "kind": att.kind, "ext": att.ext,
            "status": att.status, "reason": att.reason, "meta": {k: meta[k] for k in _PUBLIC_META if k in meta},
            "created_at": att.created_at.isoformat() if att.created_at else None,
            "session_id": session_uuid, "message_id": att.message_id}


def stage_file(fileobj, filename: str, ft, size: int, owner_key: str) -> dict:
    """Create the staged row, copy the bytes to `<staging>/<id>/original`, start processing. Blocking: call it in a
    worker thread. A failed copy leaves nothing behind."""
    with get_db_session() as db:
        att = service.create_staged(db, owner_key=owner_key, filename=filename, ft=ft, size=size)
        att_id = att.id
        body = {"id": att.id, "filename": att.filename, "size": att.size, "kind": att.kind, "status": "processing"}
    d = store.staging_dir(att_id)
    try:
        d.mkdir(parents=True)
        with open(d / "original", "wb") as out:
            shutil.copyfileobj(fileobj, out, 1024 * 1024)
    except Exception:
        store.remove_staged(att_id)
        with get_db_session() as db:
            from agenticops.models import ChatAttachment
            db.query(ChatAttachment).filter(ChatAttachment.id == att_id).delete(synchronize_session=False)
        raise
    return body


def precheck(filename: str, head: bytes, size: int, cfg):
    """→ (FileType, None) or (None, JSONResponse) for a file the upload limits refuse."""
    ft = classify(filename)
    if ft is None or ft.ext not in upload_config.allowed_extensions(cfg):
        return None, _error(415, "unsupported_type", "This file type is not accepted")
    refusal = check_content(ft, head)
    if refusal:
        return None, _error(415, refusal, "The file content does not match its type")
    if size > cfg.max_file_mb * _MIB:
        return None, _error(413, "file_too_large", f"A file may be at most {cfg.max_file_mb} MB")
    return ft, None


def _upload_size(upload: UploadFile) -> int:
    if upload.size is not None:
        return upload.size
    pos = upload.file.tell()
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(pos)
    return size


@router.post("/api/chat/attachments", status_code=201)
async def upload_attachment(request: Request, actor: Actor = Depends(current_actor)):
    cfg = await asyncio.to_thread(upload_config.effective)
    length = request.headers.get("content-length")
    if length is None or not length.isdigit():
        return _error(411, "length_required", "Send the file with a Content-Length")
    if int(length) > cfg.max_file_mb * _MIB + _FORM_OVERHEAD:
        return _error(413, "file_too_large", f"A file may be at most {cfg.max_file_mb} MB")
    form = None
    try:
        form = await request.form(max_files=1, max_fields=4)
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            return _error(422, "file_required", "Send one file in the `file` field")
        filename = upload.filename or "file"
        head = await upload.read(8192)
        await upload.seek(0)
        ft, refused = precheck(filename, head, _upload_size(upload), cfg)
        if refused is not None:
            return refused
        if not await asyncio.to_thread(store.disk_free_ok):
            return _error(507, "insufficient_storage", "The server is low on disk space")
        body = await asyncio.to_thread(stage_file, upload.file, filename, ft, _upload_size(upload), actor.key)
        service.submit_processing(body["id"])
        await asyncio.to_thread(service.maybe_sweep)
        return JSONResponse(status_code=201, content=body)
    finally:
        if form is not None:
            await form.close()


@router.get("/api/chat/attachments/{att_id}")
def get_attachment(att_id: str, actor: Actor = Depends(current_actor)):
    with get_db_session() as db:
        try:
            att = service.visible(db, att_id, actor)
        except AttachmentError as e:
            return _from(e)
        return body_of(att, service.session_uuid_of(db, att))


def _disposition(kind: str, name: str) -> str:
    ascii_name = _ASCII_UNSAFE.sub("_", name).strip() or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name, safe='')}"


@router.get("/api/chat/attachments/{att_id}/content")
def get_attachment_content(att_id: str, actor: Actor = Depends(current_actor),
                           variant: str = Query("original", pattern=r"^(original|preview|thumb|page-\d{1,3})$")):
    with get_db_session() as db:
        try:
            att = service.visible(db, att_id, actor)
        except AttachmentError as e:
            return _from(e)
        d = store.attachment_dir(att, service.session_uuid_of(db, att))
        ext, filename, meta = att.ext, att.filename, dict(att.meta or {})
    stem = Path(filename).stem or "file"
    if variant == "original":
        path, mime, inline, name = d / "original", SUPPORTED[ext].mime, ext in _INLINE_ORIGINALS, filename
    elif variant == "preview":
        fmt = meta.get("preview_format")
        path = d / f"preview.{fmt}" if fmt else None
        mime, inline, name = f"image/{fmt}", True, f"{stem}-preview.{fmt}"
    elif variant == "thumb":
        path, mime, inline, name = d / "thumb.jpg", "image/jpeg", True, f"{stem}-thumb.jpg"
    else:
        n = int(variant.split("-", 1)[1])
        path, mime, inline, name = d / "pages" / f"page-{n}.png", "image/png", True, f"{stem}-page-{n}.png"
    if path is None or not path.is_file():
        return _error(404, "variant_unavailable", "This attachment has no such content")
    headers = {**_SECURITY_HEADERS, "Content-Disposition": _disposition("inline" if inline else "attachment", name)}
    return FileResponse(path, media_type=mime, headers=headers)


@router.delete("/api/chat/attachments/{att_id}", status_code=204)
def delete_attachment(att_id: str, actor: Actor = Depends(current_actor)):
    with get_db_session() as db:
        try:
            service.delete_staged(db, att_id, actor)
        except AttachmentError as e:
            return _from(e)
    return Response(status_code=204)
