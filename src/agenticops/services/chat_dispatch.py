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
    return (db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_pk, ChatMessage.role == "assistant", ChatMessage.id > user_msg_id)
            .order_by(ChatMessage.id.asc()).first())


def claim(db, row, client_message_id: str, content: str, attachments, busy: bool) -> Claim:
    """Add the user message as `accepted` (flushed, in the caller's transaction) or say why not."""
    prior = db.query(ChatMessage).filter_by(session_id=row.id, client_message_id=client_message_id).first()
    if prior is not None:
        if (prior.dispatch_state or "completed") in FINISHED:
            return Claim("replay", prior.id, _reply_after(db, row.id, prior.id))
        return Claim("in_flight", prior.id)
    still_open = (db.query(ChatMessage.id)
                  .filter(ChatMessage.session_id == row.id, ChatMessage.role == "user",
                          ChatMessage.dispatch_state.in_(OPEN)).first())
    if busy or still_open is not None:
        return Claim("busy", None)
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


def interrupt_stale() -> int:
    """Startup: every dispatch an earlier process left open was cut off — say so."""
    with get_db_session() as db:
        return db.query(ChatMessage).filter(ChatMessage.dispatch_state.in_(OPEN)).update(
            {"dispatch_state": "interrupted"}, synchronize_session=False)
