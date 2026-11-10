"""/api/users — admins manage web accounts (MVP-2.8.0 S2 rework; rules in services/user_admin).

Who may: a user whose own row is an admin (an API key must carry `admin` too), in BOTH sign-in modes — RBAC shadow
mode never widens it. With sign-in off the rest of the API treats everyone as an admin, but these writes persist
into the DB: a viewer that could reset the admin's password or promote itself would still be the admin once sign-in
is turned on (S2 rework review). The web always signs in, so the caller's row is always known
(web/deps.require_authenticated_user resolves the Bearer token in both modes). Plain `def` handlers.
"""
import hashlib
from typing import List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agenticops.services import user_admin
from agenticops.web.deps import require_session_user
from agenticops.web.schemas import (APIKeyCreate, APIKeyCreatedResponse, APIKeyResponse, PasswordResetResponse,
                                    UserCreateBody, UserCreatedResponse, UserPatchBody, UserRow)

router = APIRouter(tags=["users"])


async def users_admin(request: Request):
    # a signed-in admin session — never an API key, even an admin-scoped one (MVP-2.8.0 API keys)
    return await require_session_user(request, admin=True)


def _refused(e) -> JSONResponse:
    """The UiError shape the web client reads ({"detail": {"detail", "code"}} — api/client.apiFetch keeps the code);
    a top-level code was dropped, so the page could not word the refusal (MVP-2.8.0 API keys round)."""
    extra = getattr(e, "extra", None) or {}       # e.g. has_open_requests names the requests ({"refs": [...]})
    return JSONResponse(status_code=e.status, content={"detail": {"detail": e.detail, "code": e.code, **extra}})


def _token_hash(request: Request) -> str | None:
    """The caller's own session (the same sha256 AuthService.validate_session looks up)."""
    header = request.headers.get("authorization") or ""
    return hashlib.sha256(header[7:].encode()).hexdigest() if header.startswith("Bearer ") else None


@router.get("/api/users", response_model=List[UserRow])
def api_list_users(caller=Depends(users_admin)):
    from agenticops.services import api_keys
    counts = api_keys.active_counts()
    return [{**u, "active_api_keys": counts.get(u["id"], 0)} for u in user_admin.list_users()]


@router.get("/api/users/{user_id}/api-keys", response_model=List[APIKeyResponse])
def api_list_user_api_keys(user_id: int, caller=Depends(users_admin)):
    """An admin sees a user's API keys — prefixes only, never a full key (MVP-2.8.0)."""
    from agenticops.services import api_keys
    if not api_keys.owner_exists(user_id):
        return _refused(user_admin.UserAdminError(404, "not_found", f"user {user_id} not found"))
    return api_keys.list_keys(user_id)


@router.post("/api/users/{user_id}/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
def api_create_user_api_key(user_id: int, body: APIKeyCreate, caller=Depends(users_admin)):
    """An admin issues a key for someone (MVP-2.8.0, owner 2026-11-10): never above that person's role; the full key
    is in this response only, for the admin to hand over — like a reset password."""
    from agenticops.services import api_keys
    try:
        owner = api_keys.issuable_owner(user_id)
        row, key = api_keys.create_key(owner, name=body.name, permissions=body.permissions,
                                       expires_days=body.expires_days, caller=caller, by_admin=True)
    except api_keys.ApiKeyError as e:
        return _refused(e)
    return {**row, "key": key}


@router.delete("/api/users/{user_id}/api-keys/{key_id}", status_code=204)
def api_revoke_user_api_key(user_id: int, key_id: int, caller=Depends(users_admin)):
    """An admin revokes a user's API key; the audit says it was an admin (MVP-2.8.0)."""
    from agenticops.services import api_keys
    try:
        api_keys.revoke_key(key_id, owner_id=user_id, caller=caller, by_admin=True)
    except api_keys.ApiKeyError as e:
        return _refused(e)


@router.post("/api/users", response_model=UserCreatedResponse, status_code=201)
def api_create_user(body: UserCreateBody, caller=Depends(users_admin)):
    try:
        user, password = user_admin.create_user(email=body.email, name=body.name, role=body.role,
                                                settings_view=body.settings_view, caller=caller)
    except user_admin.UserAdminError as e:
        return _refused(e)
    return {"user": user, "password": password}


@router.patch("/api/users/{user_id}", response_model=UserRow)
def api_update_user(user_id: int, body: UserPatchBody, caller=Depends(users_admin)):
    try:
        return user_admin.update_user(user_id, role=body.role, settings_view=body.settings_view,
                                      is_active=body.is_active, caller=caller)
    except user_admin.UserAdminError as e:
        return _refused(e)


@router.delete("/api/users/{user_id}", status_code=204)
def api_delete_user(user_id: int, caller=Depends(users_admin)):
    """Delete a user (MVP-2.8.0): soft — sessions, keys and unsent uploads go at once, records stay with their
    owner, the login name is never reused (services/user_admin.delete_user)."""
    try:
        user_admin.delete_user(user_id, caller=caller)
    except user_admin.UserAdminError as e:
        return _refused(e)


@router.post("/api/users/{user_id}/reset-password", response_model=PasswordResetResponse)
def api_reset_password(user_id: int, request: Request, caller=Depends(users_admin)):
    try:
        return {"password": user_admin.reset_password(user_id, caller=caller, keep_token_hash=_token_hash(request))}
    except user_admin.UserAdminError as e:
        return _refused(e)
