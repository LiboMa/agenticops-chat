"""ORM-level secret redaction — the database write boundary.

Companion to :mod:`agenticops.security.redaction` (the pure scrubber) and to
``agent_memory._atomic_write_text`` (the file boundary). A single SQLAlchemy
``before_flush`` listener scrubs every ``String`` / ``Text`` / ``JSON`` column
of every model right before it is written, so no persistence path — RCA
results, fix-execution step output, alert payloads, chat messages, reports,
even a table added in the future — can leak AWS keys / AK-SK / session tokens /
passwords / private keys.

Why scan-all-except-denylist rather than a per-model allowlist: the owner
mandate is "never again". An allowlist silently leaks the day someone adds a
new sink column and forgets to register it; scanning every text/JSON column
closes that gap by default. It is safe because the scrubber is precision-biased
(see redaction.py) — it masks only AWS key IDs, label-anchored secrets, and PEM
blocks, so scanning benign columns (title, status, resource_id, account ids,
ARNs) is a no-op.

The ONE column that must survive verbatim is the encrypted at-rest credential
store ``CloudAccount.credentials`` — the platform needs it to authenticate to
target accounts. It is explicitly excluded.
"""
from __future__ import annotations

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.types import JSON, String, Text

from agenticops.security.redaction import redact_obj

# (class name, attribute) pairs persisted verbatim — never scrubbed.
# CloudAccount.credentials is the encrypted credential store the platform
# authenticates with; redacting it would break every cross-account call.
_EXCLUDED_COLUMNS: set[tuple[str, str]] = {
    ("CloudAccount", "credentials"),
}

# Only these column types can carry a secret-bearing string. Integer / Float /
# DateTime / Boolean columns are skipped entirely. (Text and Enum subclass
# String, so both are covered by the String check.)
_SCANNED_TYPES = (String, Text, JSON)


def _scrub_instance(obj) -> None:
    """Redact secret-bearing columns on a single mapped instance in place."""
    try:
        mapper = inspect(obj).mapper
    except Exception:  # pragma: no cover - not a mapped instance
        return
    cls_name = type(obj).__name__
    for col in mapper.columns:
        attr = col.key
        if (cls_name, attr) in _EXCLUDED_COLUMNS:
            continue
        if not isinstance(col.type, _SCANNED_TYPES):
            continue
        try:
            value = getattr(obj, attr)
        except Exception:  # pragma: no cover - unloaded/expired attr
            continue
        if value is None:
            continue
        cleaned = redact_obj(value)
        # Only write back when something actually changed, so we don't
        # needlessly re-mark clean objects dirty during flush.
        if cleaned != value:
            setattr(obj, attr, cleaned)


def _before_flush(session, flush_context, instances) -> None:
    for obj in session.new:
        _scrub_instance(obj)
    for obj in session.dirty:
        _scrub_instance(obj)


_INSTALLED = False


def install_db_redaction() -> None:
    """Register the before_flush secret scrubber on all sessions (idempotent).

    Listening on the base ``Session`` class covers every sessionmaker in the
    process (app, CLI, tests, migrations) — defense in depth.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    event.listen(Session, "before_flush", _before_flush)
    _INSTALLED = True
