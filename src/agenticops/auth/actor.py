"""Actor — who is acting (MVP-2.6.0). One string form everywhere: "<kind>:<id>".

kinds: user (authenticated web user, id=email) | web (anonymous) | cli (os user) |
       agent (auto paths) | im (platform:sender) | webhook (source, P2).
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Actor:
    kind: str
    id: str
    user_id: Optional[int] = None
    permissions: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    def __str__(self) -> str:  # so f"{actor}" gives the key
        return self.key


def web_anonymous_actor() -> Actor:
    return Actor("web", "anonymous")


def actor_from_user(user: Any) -> Actor:
    perms = tuple(getattr(user, "permissions", None) or ())
    return Actor("user", str(getattr(user, "email", "") or getattr(user, "id", "")), getattr(user, "id", None), perms)


def actor_from_request(request: Any) -> Actor:
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        return web_anonymous_actor()
    return actor_from_user(user)


def cli_actor() -> Actor:
    try:
        return Actor("cli", getpass.getuser())
    except Exception:
        return Actor("cli", "unknown")


def agent_actor(name: str) -> Actor:
    return Actor("agent", name)


def im_actor(platform: str, sender_id: str) -> Actor:
    return Actor("im", f"{platform}:{sender_id}")


def webhook_actor(source: str) -> Actor:
    return Actor("webhook", source)


def parse_actor(text: str) -> Actor:
    """Reconstruct an Actor from its key. Legacy free-text names become web:<text> — that is any text
    without a colon, and also "cli:" / ":x" (an empty kind or an empty id is not a valid key)."""
    text = (text or "").strip()
    kind, sep, rest = text.partition(":")
    if not sep or not kind or not rest:
        return Actor("web", text or "anonymous")
    return Actor(kind, rest)


def actor_from_run_context(ctx: Any) -> Actor:
    """Rebuild the acting identity from a RunContext (agent tools, executor worker). The permission
    flags travel with it — without them a user: actor would fail the rbac matrix on every check."""
    base = parse_actor(ctx.actor)
    return Actor(base.kind, base.id, ctx.actor_user_id, tuple(ctx.actor_permissions or ()))
