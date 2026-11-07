"""Settings changed at runtime and kept in the DB (`runtime_settings`, 2026-11-07).

A small key → JSON store with a per-process cache (AgenticOps runs as one process, so this cache is the only one).
It does not validate: the module that owns a key checks the value every time it reads it, so a stored value that a
later release no longer accepts is dropped there instead of breaking startup.
"""
import copy
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from agenticops.models import RuntimeSetting, get_db_session

_MISSING = object()
_cache: dict[str, Any] = {}
_lock = threading.Lock()


def get(key: str) -> Optional[Any]:
    """The stored value (a copy), or None."""
    with _lock:
        cached = _cache.get(key, _MISSING)
    if cached is _MISSING:
        with get_db_session() as db:
            row = db.get(RuntimeSetting, key)
            cached = copy.deepcopy(row.value) if row is not None else None
        with _lock:
            _cache[key] = cached
    return copy.deepcopy(cached)


def get_row(key: str) -> Optional[dict]:
    """`{value, updated_at, updated_by}` straight from the DB, or None."""
    with get_db_session() as db:
        row = db.get(RuntimeSetting, key)
        if row is None:
            return None
        return {"value": copy.deepcopy(row.value), "updated_at": row.updated_at, "updated_by": row.updated_by}


def _write(key: str, value: Any, actor_key: Optional[str], session) -> None:
    row = session.get(RuntimeSetting, key)
    if row is None:
        session.add(RuntimeSetting(key=key, value=value, updated_by=actor_key,
                                   updated_at=datetime.now(timezone.utc)))
    else:
        row.value = value
        row.updated_by = actor_key
        row.updated_at = datetime.now(timezone.utc)
    session.flush()


def _drop(key: str) -> None:
    with _lock:
        _cache.pop(key, None)


def _after_commit(session, key: str) -> None:
    """With a caller's session the write is not visible until that commit: drop the entry now and again then."""
    from sqlalchemy import event
    _drop(key)
    event.listen(session, "after_commit", lambda _s: _drop(key), once=True)


def put(key: str, value: Any, actor_key: str, session=None) -> None:
    """Store `value` under `key`. With `session`, the write joins that transaction (the caller commits)."""
    if session is not None:
        _write(key, value, actor_key, session)
        _after_commit(session, key)
        return
    with get_db_session() as db:
        _write(key, value, actor_key, db)
    _drop(key)


def delete(key: str, session=None) -> None:
    def _delete(db):
        db.query(RuntimeSetting).filter(RuntimeSetting.key == key).delete(synchronize_session=False)
    if session is not None:
        _delete(session)
        _after_commit(session, key)
        return
    with get_db_session() as db:
        _delete(db)
    _drop(key)


def reset_cache() -> None:
    with _lock:
        _cache.clear()
