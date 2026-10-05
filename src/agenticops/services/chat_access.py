"""Who may see a chat session (MVP-2.7.0 S1b) — the one rule every chat route applies.

A session a logged-in user creates is theirs and `private`: only they and admins see it. Sessions with no
single owner — pre-2.7.0 rows, and those made with auth off, from IM or from the CLI — are `workspace`
sessions everyone sees. With api_auth_enabled=false every caller is web:anonymous, so every session is
visible (the 2.6.1 behaviour). A session the caller may not see is reported exactly like a missing one.
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.models import ChatSession

PRIVATE, WORKSPACE = "private", "workspace"
VISIBILITIES = (PRIVATE, WORKSPACE)
NOT_FOUND = "Session not found"


def is_admin(actor: Actor) -> bool:
    """The authz notion of admin (an API key's scopes already cap the owner's permissions)."""
    return "admin" in (actor.permissions or ())


def new_session_owner(actor: Actor) -> tuple[Optional[int], str]:
    """(owner_user_id, visibility) for a session this caller creates."""
    if settings.api_auth_enabled and actor.kind == "user" and actor.user_id is not None:
        return actor.user_id, PRIVATE
    return None, WORKSPACE


def can_see(row: ChatSession, actor: Actor) -> bool:
    if not settings.api_auth_enabled or (row.visibility or WORKSPACE) == WORKSPACE or is_admin(actor):
        return True
    return actor.user_id is not None and row.owner_user_id == actor.user_id


def owned_by(row: ChatSession, actor: Actor) -> bool:
    return actor.user_id is not None and row.owner_user_id == actor.user_id


def visible_filter(query, actor: Actor):
    """Narrow a ChatSession query to the sessions this caller may see."""
    if not settings.api_auth_enabled or is_admin(actor):
        return query
    conditions = [ChatSession.visibility == WORKSPACE]
    if actor.user_id is not None:
        conditions.append(ChatSession.owner_user_id == actor.user_id)
    return query.filter(or_(*conditions))


def get_visible_session(db, session_id: str, actor: Actor) -> ChatSession:
    """The session, or a 404 that reads the same whether it is missing or not the caller's to see."""
    row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if row is None or not can_see(row, actor):
        raise HTTPException(404, NOT_FOUND)
    return row


def check_visibility_change(row: ChatSession, actor: Actor, visibility: str) -> None:
    """Only the owner or an admin decides who sees a session; a session with no owner stays workspace."""
    if visibility == (row.visibility or WORKSPACE):
        return
    if row.owner_user_id is None:
        raise HTTPException(409, "This session has no owner, so it stays visible to the workspace")
    if not (owned_by(row, actor) or is_admin(actor)):
        raise HTTPException(403, "Only the session's owner or an admin can change who sees it")
