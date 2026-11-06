"""Viewer accounts — a signed-in user without the write flag.

A viewer may sign in, browse, chat and look after its own sign-in and preferences; every other state change is
refused. The flag is the user's own row (`users.permissions`), never intersected with an API key, so API-key scope
semantics stay as they were. Three places act on it:
  * APIAuthMiddleware refuses every other POST/PUT/PATCH/DELETE (it runs before routing, so `viewer_may` matches the
    concrete request path, not a route template);
  * a viewer's chat turn runs a read-only agent (agents/main_agent.create_main_agent(read_only=True));
  * every CLI tool refuses a non-readonly command under RunContext.read_only (services/command_audit).
"""
from __future__ import annotations

import re
from typing import Any

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
READ_ONLY_CODE = "read_only"
READ_ONLY_MESSAGE = "This account is read-only. / 此账户为只读账户。"

_SEG = r"[^/]+"  # one path segment (a chat session id, a vpc id)
_ALLOWED: tuple[tuple[str, re.Pattern], ...] = tuple(
    (method, re.compile(pattern)) for method, pattern in (
        ("POST", r"/api/auth/logout"),
        ("PUT", r"/api/users/me/password"),
        ("PATCH", r"/api/users/me/preferences"),
        ("POST", r"/api/chat/sessions"),
        ("PATCH", rf"/api/chat/sessions/{_SEG}"),
        ("DELETE", rf"/api/chat/sessions/{_SEG}"),
        ("POST", rf"/api/chat/sessions/{_SEG}/messages"),
        # in-memory analysis over read-only describes — nothing is written or changed
        ("POST", rf"/api/graph/vpc/{_SEG}/dependency-chain"),
        ("POST", rf"/api/graph/vpc/{_SEG}/change-simulation"),
    )
)


def is_viewer(user: Any) -> bool:
    """A signed-in user whose own permissions lack "write"."""
    return user is not None and "write" not in (getattr(user, "permissions", None) or ())


def viewer_may(method: str, path: str) -> bool:
    """Whether a viewer may send this request. Reads always pass; a write only on the allowlist (whole-path match)."""
    m = (method or "").upper()
    if m not in MUTATING_METHODS:
        return True
    return any(m == allowed and rx.fullmatch(path or "") for allowed, rx in _ALLOWED)


def read_only_detail() -> dict:
    """The UiError body ({detail, code}) every viewer refusal carries; the web client keeps the code."""
    return {"detail": READ_ONLY_MESSAGE, "code": READ_ONLY_CODE}
