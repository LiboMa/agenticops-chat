"""One user message = one dispatch (MVP-2.7.0 S5).

`client_message_id` is unique within a session (DB index uq_chat_message_client_id): a repeat of a finished message
is replayed from what was stored, a repeat of a running one — or any new message while the session is busy — is
refused, and no path starts a second agent run. AgenticOps runs as ONE process (S1), so the in-process busy set is
the authority while the process lives; an `accepted` / `running` row left by an earlier process is closed by
interrupt_stale() at startup, and until then it counts as busy (fail closed: a doubt never starts a run)."""
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from agenticops.models import ChatMessage, get_db_session

UUID_RE = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
FINISHED = ("completed", "failed", "interrupted")
OPEN = ("accepted", "running")


@dataclass
class Claim:
    kind: str                         # new | replay | in_flight | busy
    user_message_id: int | None
    reply: ChatMessage | None = None  # replay: the assistant row that answered it, if any


def _reply_after(db, session_pk: int, user_msg_id: int) -> ChatMessage | None:
    """The assistant row that answered this user message: after it and before the next user message (never a later
    message's reply)."""
    nxt = (db.query(ChatMessage.id)
           .filter(ChatMessage.session_id == session_pk, ChatMessage.role == "user", ChatMessage.id > user_msg_id)
           .order_by(ChatMessage.id.asc()).first())
    q = db.query(ChatMessage).filter(ChatMessage.session_id == session_pk, ChatMessage.role == "assistant",
                                     ChatMessage.id > user_msg_id)
    if nxt is not None:
        q = q.filter(ChatMessage.id < nxt[0])
    return q.order_by(ChatMessage.id.asc()).first()


def _close_dead(db, msg: ChatMessage) -> None:
    """An open dispatch with nothing running it any more: interrupted, with an interrupted reply the page can label."""
    msg.dispatch_state = "interrupted"
    if _reply_after(db, msg.session_id, msg.id) is None:
        db.add(ChatMessage(session_id=msg.session_id, role="assistant", content="", dispatch_state="interrupted"))


def claim(db, row, client_message_id: str, content: str, attachments, busy: bool) -> Claim:
    """Add the user message as `accepted` (flushed, in the caller's transaction) or say why not.

    `busy` = a dispatch of this session is live in this process (the caller's registry — the one authority, since
    AgenticOps runs as one process). With none live, an open row is dead (its stream never started, or failed
    before it could close it): it is closed as interrupted, never counted as busy."""
    prior = db.query(ChatMessage).filter_by(session_id=row.id, client_message_id=client_message_id).first()
    if prior is not None:
        if (prior.dispatch_state or "completed") in OPEN:
            if busy:
                return Claim("in_flight", prior.id)
            _close_dead(db, prior)
            db.flush()
        return Claim("replay", prior.id, _reply_after(db, row.id, prior.id))
    if busy:
        return Claim("busy", None)
    for dead in (db.query(ChatMessage)
                 .filter(ChatMessage.session_id == row.id, ChatMessage.role == "user",
                         ChatMessage.dispatch_state.in_(OPEN)).all()):
        _close_dead(db, dead)
    msg = ChatMessage(session_id=row.id, role="user", content=content, attachments=attachments,
                      client_message_id=client_message_id, dispatch_state="accepted")
    try:
        with db.begin_nested():  # a savepoint: losing the race leaves the caller's transaction usable
            db.add(msg)
            db.flush()
    except IntegrityError:  # a concurrent request with the same id won the unique index
        return Claim("in_flight", None)
    return Claim("new", msg.id)


def set_state(message_id: int, state: str) -> None:
    with get_db_session() as db:
        db.query(ChatMessage).filter(ChatMessage.id == message_id).update(
            {"dispatch_state": state}, synchronize_session=False)


def close_interrupted(session_pk: int, user_message_id: int, partial: str, tool_calls, trace_id: str | None) -> None:
    """A stream that was cancelled (the client went away) keeps what it had written, labelled interrupted — never
    stored as a complete reply, never dropped (S5)."""
    from agenticops.models import ChatSession
    with get_db_session() as db:
        if db.get(ChatSession, session_pk) is not None:
            db.add(ChatMessage(session_id=session_pk, role="assistant", content=partial or "", tool_calls=tool_calls,
                               trace_id=trace_id, dispatch_state="interrupted"))
        db.query(ChatMessage).filter(ChatMessage.id == user_message_id).update(
            {"dispatch_state": "interrupted"}, synchronize_session=False)


def interrupt_stale() -> int:
    """Startup: every dispatch an earlier process left open was cut off — say so (with a labelled reply)."""
    with get_db_session() as db:
        open_rows = db.query(ChatMessage).filter(ChatMessage.dispatch_state.in_(OPEN)).all()
        for msg in open_rows:
            if msg.role == "user":
                _close_dead(db, msg)
            else:
                msg.dispatch_state = "interrupted"
        return len(open_rows)
