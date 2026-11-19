"""What a reporter run read — recorded by the code while its tools run (MVP-2.9.0 N21, the 2.8.0 spec's S4).

A report's `coverage` says which accounts and regions the run's tools ranged over, whether every result reached the
model whole, and when the run began reading:

    {accounts: [name], regions: [region], completeness: "complete" | "partial",
     partial: {truncated, offloaded, failed}, read_at: ISO}

None of it comes from the model. `reporter_agent` begins a record and puts it on the run's RunContext (`coverage`);
the data tools (tools/metadata_tools), the credential resolver (credentials/resolver.resolve_account_session — the one
place every account-addressed cloud call passes) and the reporter's hook (results that failed or that the context
offloader moved out) write into it; `save_report` stores it on the report. Outside a reporter run there is no record
and every `note_*` is a no-op, so a report saved any other way has no coverage — it is never guessed from the text.
How many rows were read is not recorded: the code does not know that.

A tool runs in another thread under a COPY of the context (Strands: asyncio.to_thread + copy_context); the copy holds
the same record object, so a note made there reaches the run.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional


@dataclass
class Coverage:
    read_at: datetime
    accounts: set = field(default_factory=set)
    regions: set = field(default_factory=set)
    truncated: int = 0
    offloaded: int = 0
    failed: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def as_dict(self) -> dict:
        with self._lock:
            partial = {"truncated": self.truncated, "offloaded": self.offloaded, "failed": self.failed}
            at = self.read_at if self.read_at.tzinfo else self.read_at.replace(tzinfo=timezone.utc)
            return {"accounts": sorted(self.accounts), "regions": sorted(self.regions),
                    "completeness": "partial" if any(partial.values()) else "complete",
                    "partial": partial,
                    "read_at": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}


def begin(now: Optional[datetime] = None) -> Coverage:
    """A new record; `read_at` is when the run began."""
    return Coverage(read_at=now or datetime.now(timezone.utc))


def current() -> Optional[Coverage]:
    """The running reporter's record, or None — every writer below is a no-op then."""
    from agenticops.run_context import get_run_context
    record = getattr(get_run_context(), "coverage", None)
    return record if isinstance(record, Coverage) else None


def note_scope(accounts: Optional[Iterable] = (), regions: Optional[Iterable] = ()) -> None:
    """A tool ranged over these accounts (by name) and regions. Never raises: it sits on every tool's path."""
    try:
        record = current()
        if record is None:
            return
        names = {str(a) for a in (accounts or ()) if a}
        places = {str(r) for r in (regions or ()) if r}
        with record._lock:
            record.accounts |= names
            record.regions |= places
    except Exception:       # bookkeeping must never fail the read it describes
        pass


def _count(what: str) -> None:
    try:
        record = current()
        if record is not None:
            with record._lock:
                setattr(record, what, getattr(record, what) + 1)
    except Exception:
        pass


def note_truncated() -> None:
    """A result was cut before the model got it (a length limit, or a row cap with more rows behind it)."""
    _count("truncated")


def note_offloaded() -> None:
    """The context offloader moved a result out of the context, leaving a preview."""
    _count("offloaded")


def note_failed() -> None:
    """A tool answered with an error."""
    _count("failed")
