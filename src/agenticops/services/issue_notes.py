"""Append-only notes on an issue (MVP-2.7.0 S4): one `note_added` PipelineEvent per note, written in the caller's
transaction — never through pipeline_events.log_event, which swallows errors (a note is acknowledged only once stored).
A note is never edited or deleted; agents do not read notes (S5 brings them into the Chat context)."""
import json
import re
from datetime import datetime, timezone

from agenticops.models import PipelineEvent

MAX_NOTE_CHARS = 8000
# Control characters other than tab and newline (\r is allowed too: a pasted CRLF block is ordinary text), the C1
# controls, and the bidi overrides / isolates — an append-only trail must read as written, never reordered on screen
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


class NoteRejected(ValueError):
    pass


def clean_note(content: str) -> str:
    text = (content or "").strip()
    if not text:
        raise NoteRejected("a note needs some text")
    if len(text) > MAX_NOTE_CHARS:
        raise NoteRejected(f"a note is at most {MAX_NOTE_CHARS} characters")
    if _CONTROL.search(text):
        raise NoteRejected("a note may not contain control characters")
    return text


def add_note(session, issue, content: str, actor) -> tuple[PipelineEvent, str]:
    """Add the note to the session (flushed, not committed) → (the event, the stored text)."""
    text = clean_note(content)
    ev = PipelineEvent(health_issue_id=issue.id, event_type="note_added", stage="note", status="recorded",
                       detail=json.dumps({"content": text}, ensure_ascii=False), actor=actor.key[:100],
                       trace_id=issue.trace_id, created_at=datetime.now(timezone.utc))
    session.add(ev)
    session.flush()
    return ev, text
