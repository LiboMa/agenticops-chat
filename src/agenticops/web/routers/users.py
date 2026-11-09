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
from agenticops.web.deps import require_authenticated_user
from agenticops.web.schemas import (PasswordResetResponse, UserCreateBody, UserCreatedResponse, UserPatchBody,
                                    UserRow)

router = APIRouter(tags=["users"])


async def users_admin(request: Request):
    return await require_authenticated_user(request, admin=True)


def _refused(e: user_admin.UserAdminError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"detail": e.detail, "code": e.code})


def _token_hash(request: Request) -> str | None:
    """The caller's own session (the same sha256 AuthService.validate_session looks up)."""
    header = request.headers.get("authorization") or ""
    return hashlib.sha256(header[7:].encode()).hexdigest() if header.startswith("Bearer ") else None


@router.get("/api/users", response_model=List[UserRow])
def api_list_users(caller=Depends(users_admin)):
    return user_admin.list_users()


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


@router.post("/api/users/{user_id}/reset-password", response_model=PasswordResetResponse)
def api_reset_password(user_id: int, request: Request, caller=Depends(users_admin)):
    try:
        return {"password": user_admin.reset_password(user_id, caller=caller, keep_token_hash=_token_hash(request))}
    except user_admin.UserAdminError as e:
        return _refused(e)
