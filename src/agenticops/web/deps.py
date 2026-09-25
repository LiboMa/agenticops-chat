"""FastAPI dependencies shared by routers (MVP-2.6.0)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

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


async def require_authenticated_user(request: Request, *, admin: bool) -> Any:
    """HARD identity check for security-sensitive web operations (use only when api_auth_enabled=true).

    Independent of rbac_enforce: shadow mode must never widen who can read the audit trail or flip a
    security toggle. The user comes from APIAuthMiddleware (request.state.user) or, when that is absent,
    from validating the Bearer header. `admin=True` also requires an admin user whose API key (if any)
    carries `admin` — a key's scopes cap the owner's. 401 without a valid token, 403 for a non-admin.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        header = request.headers.get("authorization") or ""
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        from fastapi.security import HTTPAuthorizationCredentials
        from agenticops.auth import get_current_user
        user = await get_current_user(request, HTTPAuthorizationCredentials(scheme="Bearer", credentials=header[7:]))
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    if admin:
        api_key = getattr(request.state, "api_key", None)
        if not getattr(user, "is_admin", False) or (
                api_key is not None and "admin" not in (getattr(api_key, "permissions", None) or ())):
            raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
