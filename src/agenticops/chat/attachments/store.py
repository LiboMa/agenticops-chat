"""Where chat attachment files live (2026-11-07).

    <root>/_staging/<attachment id>/      an upload not sent yet
    <root>/<chat session uuid>/<attachment id>/   after the send that bound it

Each attachment directory holds `original` (the uploaded bytes, never under the user's file name) and the
extraction artifacts. A session's directory is named by its UUID, never by its integer key, which SQLite may reuse.
"""
import os
import shutil
from pathlib import Path

from agenticops.chat.attachments.limits import MIN_FREE_DISK_BYTES
from agenticops.config import settings

STAGING = "_staging"


def _base() -> Path:
    return Path(settings.chat_attachments_dir) if settings.chat_attachments_dir else settings.data_dir / "chat_attachments"


def root() -> Path:
    """The store's root, created on first use by a write (staging an upload, moving one into its session)."""
    base = _base()
    (base / STAGING).mkdir(parents=True, exist_ok=True)
    return base


def staging_dir(att_id: str) -> Path:
    return _base() / STAGING / att_id


def session_root(session_uuid: str) -> Path:
    return _base() / session_uuid


def attachment_dir(att, session_uuid: str | None) -> Path:
    """The directory holding this attachment's files: the session's when it is there, else staging (a send whose
    move has not happened yet, or failed)."""
    if session_uuid and att.session_id is not None:
        bound = session_root(session_uuid) / att.id
        if bound.is_dir():
            return bound
    return staging_dir(att.id)


def disk_free_ok() -> bool:
    return shutil.disk_usage(root()).free >= MIN_FREE_DISK_BYTES   # the upload that asks is about to write here


def move_into_session(att_ids: list[str], session_uuid: str) -> None:
    """Move staged directories under the session's (created without parents: a root that vanished is not rebuilt)."""
    root()
    target = session_root(session_uuid)
    target.mkdir(parents=False, exist_ok=True)
    for att_id in att_ids:
        src = staging_dir(att_id)
        if src.is_dir():
            try:
                os.replace(src, target / att_id)
            except FileNotFoundError:   # the sweep's re-home (or another mover) got there first
                pass


def remove_session(session_uuid: str) -> None:
    if session_uuid and session_uuid != STAGING:
        shutil.rmtree(session_root(session_uuid), ignore_errors=True)


def remove_staged(att_id: str) -> None:
    if att_id:
        shutil.rmtree(staging_dir(att_id), ignore_errors=True)


def staged_ids() -> set[str]:
    staging = _base() / STAGING
    return {p.name for p in staging.iterdir() if p.is_dir()} if staging.is_dir() else set()


def session_dirs() -> set[str]:
    base = _base()
    return {p.name for p in base.iterdir() if p.is_dir() and p.name != STAGING} if base.is_dir() else set()
