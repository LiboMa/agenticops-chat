"""FastAPI dependencies shared by routers (MVP-2.6.0)."""

from __future__ import annotations

from fastapi import Request

from agenticops.auth.actor import Actor, actor_from_request
from agenticops.config import get_trace_id
from agenticops.run_context import update_run_context


async def current_actor(request: Request) -> Actor:
    """Resolve the acting identity for this request and stamp it on the Run Context.

    api_auth_enabled=true → APIAuthMiddleware put the User on request.state → user:<email>.
    Otherwise → web:anonymous (exactly today's trust level). Never reads identity from the body.

    Must stay `async def`: FastAPI runs a plain `def` dependency in a threadpool under a COPIED
    context, so its ContextVar write would never reach the handler. Nothing is reset at request
    end — each request runs in its own task, so the ContextVar is isolated naturally.
    """
    actor = actor_from_request(request)
    update_run_context(actor=actor.key, actor_user_id=actor.user_id, actor_permissions=actor.permissions,
                       trace_id=get_trace_id())
    return actor
