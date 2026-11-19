"""The four high-impact switches in force (MVP-2.9.0 N25 — the 2.8.0 spec's S8, R18): whether the executor runs,
whether the post-RCA pipeline acts by itself, whether L0 / L1 fix plans are approved without a person, whether the
executor asks a person again before each write (HITL).

`settings.yaml` (or the environment) gives the DEFAULT. An administrator's change is one JSON object in the database
(`runtime_settings`, key `exec_switches`) — so switching the executor off survives a restart, which a value set on
the process's `settings` object never did. Every read re-validates what is stored (a value that is no switch is
dropped with a warning, never fatal).

This module is the ONE reader: nothing else in `src/` reads `settings.executor_enabled`, `settings.auto_fix_enabled`,
`settings.executor_auto_approve_l0_l1` or `settings.executor_hitl_enabled` (`tests/test_exec_switches.py` scans for
it). The stored object is remembered for `TTL_SECONDS`, so a change made by another process — the CLI is one — is seen
within that time; a change made in this process is seen at once.

When the store cannot be read, nobody can tell whether an administrator switched something off: the three switches
that let something happen without a person read OFF until it can be read again. A database that has no such table
holds no override (a fresh database before `init_db`).
"""
import logging
import threading
import time
from dataclasses import dataclass, fields
from typing import Optional

from agenticops.config import settings
from agenticops.services import runtime_settings

logger = logging.getLogger(__name__)

KEY = "exec_switches"
TTL_SECONDS = 1.0


@dataclass(frozen=True)
class ExecSwitches:
    executor_enabled: bool
    auto_fix_enabled: bool
    executor_auto_approve_l0_l1: bool
    executor_hitl_enabled: bool

    def as_dict(self) -> dict[str, bool]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


FIELDS: tuple[str, ...] = tuple(f.name for f in fields(ExecSwitches))
# What must not happen by itself while the store is unreadable. HITL is the other way round (on = stricter), so it
# keeps its default.
_ACTS_ALONE = ("executor_enabled", "auto_fix_enabled", "executor_auto_approve_l0_l1")

_clock = time.monotonic
_lock = threading.Lock()
_memo: Optional[tuple[str, float, dict]] = None      # (database url, read at, the stored object)


class ExecSwitchError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def defaults() -> ExecSwitches:
    """What settings.yaml / the environment say — the value in force while nothing is stored."""
    return ExecSwitches(**{name: bool(getattr(settings, name)) for name in FIELDS})


def invalidate() -> None:
    global _memo
    with _lock:
        _memo = None


def _table_exists() -> bool:
    from sqlalchemy import inspect

    from agenticops.models import get_engine
    try:
        return inspect(get_engine()).has_table("runtime_settings")
    except Exception:
        return True          # cannot tell: treat the failure as a failure


def _stored() -> dict:
    """The stored object as it is ({} when there is none). Raises when the store cannot be read."""
    global _memo
    url, now = settings.database_url, _clock()
    with _lock:
        if _memo is not None and _memo[0] == url and now - _memo[1] < TTL_SECONDS:
            return _memo[2]
    try:
        row = runtime_settings.get_row(KEY)
    except Exception:
        if _table_exists():
            raise
        row = None
    value = row["value"] if row and isinstance(row["value"], dict) else {}
    with _lock:
        _memo = (url, now, value)
    return value


def _valid(stored: dict) -> dict[str, bool]:
    out = {}
    for name, value in stored.items():
        if name in FIELDS and isinstance(value, bool):
            out[name] = value
        else:
            logger.warning("exec_switches: stored %s=%r is no switch — dropped", name, value)
    return out


def effective() -> ExecSwitches:
    base = defaults()
    try:
        stored = _stored()
    except Exception:
        logger.error("exec_switches: the stored switches cannot be read — the executor, auto-fix and auto-approval "
                     "are treated as OFF until they can", exc_info=True)
        return ExecSwitches(**{**base.as_dict(), **dict.fromkeys(_ACTS_ALONE, False)})
    return ExecSwitches(**{**base.as_dict(), **_valid(stored)})


def overridden() -> list[str]:
    """The switches whose value in force is a stored one (sorted)."""
    try:
        return sorted(_valid(_stored()))
    except Exception:
        return []


def validate_patch(patch: dict) -> dict[str, bool]:
    """The patch as it would be stored, or ExecSwitchError naming the first bad field."""
    for name in sorted(patch):
        if name not in FIELDS:
            raise ExecSwitchError(name, f"Unknown switch: {name}")
        if not isinstance(patch[name], bool):
            raise ExecSwitchError(name, f"{name} must be a boolean")
    return dict(patch)


def save(patch: dict, actor_key: str, session=None) -> ExecSwitches:
    """Store `patch` over what is stored. With `session` the write joins that transaction (the caller commits, and
    audits). Seen by this process at once; by another within TTL_SECONDS."""
    checked = validate_patch(patch)
    if session is not None:                       # inside the caller's transaction: read what IT sees
        from agenticops.models import RuntimeSetting
        row = session.get(RuntimeSetting, KEY)
        value = row.value if row is not None else None
    else:
        row = runtime_settings.get_row(KEY)
        value = row["value"] if row else None
    current = _valid(value) if isinstance(value, dict) else {}
    runtime_settings.put(KEY, {**current, **checked}, actor_key, session=session)
    invalidate()
    if session is not None:
        from sqlalchemy import event
        event.listen(session, "after_commit", lambda _s: invalidate(), once=True)
    return effective()


def stored_info() -> dict:
    """Who last changed the stored switches and when — for the settings page."""
    try:
        row = runtime_settings.get_row(KEY)
    except Exception:
        row = None
    return {"overridden": overridden(), "defaults": defaults().as_dict(),
            "updated_by": row["updated_by"] if row else None,
            "updated_at": row["updated_at"].isoformat() if row and row["updated_at"] else None}
