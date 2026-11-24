"""The conversation list (MVP-2.9.0 N22, the 2.8.0 spec's S5): the view, the search and the order are the server's.

The old list took the newest 50 and sorted pinned ones first AFTERWARDS — an older pinned conversation was cut
before it could be put first — and «show archived» never asked the server for an archived row. Here the order
(pinned, last activity, id) is applied before the cut, the archive is a view of its own, and each row says what is
going on in it."""
from __future__ import annotations

from typing import Callable, Optional

from sqlalchemy import and_, case, func, or_, select

from agenticops.models import ChangeRequest, ChatMessage, ChatSession, CloudAccount, HealthIssue
from agenticops.services import chat_access
from agenticops.services.chat_dispatch import OPEN
from agenticops.services.listing import like_pattern, ref_number

VIEWS = ("all", "starred", "archived")      # all = not archived; starred = starred and not archived; archived = only those
ISSUE, CHANGE = "health_issue", "change_request"


def _matches(term: str):
    """`term` in the conversation's name, in the title of the issue / change it is about, in its account's name —
    or as a reference: «I#12» / «C#3», and a bare «12» for either kind."""
    pattern = like_pattern(term)
    about = lambda kind, model: and_(  # noqa: E731
        ChatSession.context_entity_type == kind,
        ChatSession.context_entity_id.in_(select(model.id).where(model.title.ilike(pattern, escape="\\"))))
    match = [ChatSession.name.ilike(pattern, escape="\\"), about(ISSUE, HealthIssue), about(CHANGE, ChangeRequest),
             ChatSession.context_account_id.in_(select(CloudAccount.id).where(CloudAccount.name.ilike(pattern, escape="\\")))]
    for kind, letters in ((ISSUE, "Ii"), (CHANGE, "Cc")):
        number = ref_number(term, letters)
        if number is not None:
            match.append(and_(ChatSession.context_entity_type == kind, ChatSession.context_entity_id == number))
    return or_(*match)


def page_sessions(db, actor, *, view: str = "all", q: Optional[str] = None, limit: int = 50, offset: int = 0,
                  live: Callable[[str], bool] = lambda session_id: False) -> dict:
    """One page of the conversations the actor may see: `{rows, total, all_total, next_offset, counts, activity,
    waiting}` — `total` = what matches the search, `all_total` = everything in the view.

    `live(session_id)` = a send of that conversation is running in this process (the web app's registry — AgenticOps
    is one process). `activity[pk]`: generating (a live send) | failed (the last send failed, was cut off, or was
    left open with nothing running it) | tool_failed (the last reply has a failed tool step) | None.
    `waiting[pk]`: the issue / change the conversation is about waits on this actor — the to-do list's own answer."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {list(VIEWS)}")
    query = chat_access.visible_filter(db.query(ChatSession), actor)
    query = query.filter(ChatSession.archived == True) if view == "archived" else query.filter(ChatSession.archived == False)  # noqa: E712
    if view == "starred":
        query = query.filter(ChatSession.starred == True)  # noqa: E712
    all_total = query.count()            # everything in this view, before the search
    term = (q or "").strip()
    if term:
        query = query.filter(_matches(term))

    total = query.count() if term else all_total
    rows = (query.order_by(case((ChatSession.pinned == True, 0), else_=1),  # noqa: E712 — pinned first, BEFORE the cut
                           ChatSession.last_activity_at.desc(), ChatSession.id.desc())
            .offset(max(0, offset)).limit(limit).all())
    end = max(0, offset) + len(rows)

    # one grouped statement: how many messages, the newest send and the newest reply of each conversation on the page
    stats = {pk: (n, send, reply) for pk, n, send, reply in db.query(
        ChatMessage.session_id, func.count(ChatMessage.id),
        func.max(case((ChatMessage.role == "user", ChatMessage.id))),
        func.max(case((ChatMessage.role == "assistant", ChatMessage.id))),
    ).filter(ChatMessage.session_id.in_([r.id for r in rows])).group_by(ChatMessage.session_id)} if rows else {}
    newest = [i for _n, send, reply in stats.values() for i in (send, reply) if i is not None]
    messages = {m.id: m for m in db.query(ChatMessage.id, ChatMessage.dispatch_state, ChatMessage.tool_calls)
                .filter(ChatMessage.id.in_(newest))} if newest else {}

    def activity(row) -> Optional[str]:
        if live(row.session_id):
            return "generating"
        _n, send, reply = stats.get(row.id, (0, None, None))
        state = messages[send].dispatch_state if send in messages else None
        if state in ("failed", "interrupted") or state in OPEN:     # open with nothing running it: it was cut off
            return "failed"
        steps = messages[reply].tool_calls if reply in messages else None
        if isinstance(steps, list) and any(isinstance(s, dict) and s.get("outcome") == "error" for s in steps):
            return "tool_failed"
        return None

    waiting_refs: set[str] = set()
    if any(r.context_entity_type in (ISSUE, CHANGE) and r.context_entity_id for r in rows):
        from agenticops.services import attention
        waiting_refs = {item["id"] for item in attention.attention_items(actor)}

    def waits(row) -> bool:
        letter = {ISSUE: "I", CHANGE: "C"}.get(row.context_entity_type)
        return bool(letter and row.context_entity_id and f"{letter}{row.context_entity_id}" in waiting_refs)

    return {"rows": rows, "total": total, "all_total": all_total, "next_offset": end if end < total else None,
            "counts": {pk: n for pk, (n, _s, _r) in stats.items()},
            "activity": {r.id: activity(r) for r in rows}, "waiting": {r.id: waits(r) for r in rows}}
