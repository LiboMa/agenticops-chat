"""Auth / users / api-keys API endpoints — extracted from app.py (no logic change)."""

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from agenticops.models import get_db_session
from agenticops.web.schemas import (
    APIKeyCreate,
    APIKeyCreatedResponse,
    APIKeyResponse,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    UserResponse,
)

router = APIRouter()


async def _session_user(request: Request):
    """A signed-in session, never an API key (MVP-2.8.0: a key never manages keys or the password)."""
    from agenticops.web.deps import require_session_user
    return await require_session_user(request, admin=False)


@router.post("/api/auth/login", response_model=LoginResponse)
async def api_login(request: Request, request_data: LoginRequest):
    """Login and get a session token."""
    from agenticops.auth import AuthService

    user = AuthService.authenticate(request_data.email, request_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Get client info
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Create session
    token = AuthService.create_session(user.id, ip_address, user_agent)

    return LoginResponse(
        token=token,
        user_id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=AuthService.SESSION_DURATION_HOURS),
    )


@router.post("/api/auth/logout")
async def api_logout(request: Request):
    """Logout and invalidate the session."""
    from agenticops.auth import AuthService

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        AuthService.invalidate_session(token)

    return {"message": "Logged out successfully"}


@router.get("/api/users/me", response_model=UserResponse)
async def api_get_current_user(request: Request):
    """Get the currently authenticated user."""
    from agenticops.auth import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Extract credentials from header
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return UserResponse.model_validate(user)


@router.put("/api/users/me/password")
def api_change_password(request_data: PasswordChangeRequest, user=Depends(_session_user)):
    """Change the current user's password — from a signed-in session only (an API key never changes it)."""
    from agenticops.auth import AuthService
    if not AuthService.update_password(user.id, request_data.old_password, request_data.new_password):
        raise HTTPException(status_code=400, detail="Invalid current password")
    return {"message": "Password changed successfully"}


def _key_refused(e) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"detail": {"detail": e.detail, "code": e.code}})


@router.post("/api/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
def api_create_api_key(request_data: APIKeyCreate, user=Depends(_session_user)):
    """Create an API key for the signed-in user (MVP-2.8.0): ["read"] or ["read","write"], never above the owner's role
    (a viewer: read only); the full key is in this response only."""
    from agenticops.services import api_keys
    try:
        row, key = api_keys.create_key(user, name=request_data.name, permissions=request_data.permissions,
                                       expires_days=request_data.expires_days, caller=user)
    except api_keys.ApiKeyError as e:
        return _key_refused(e)
    return {**row, "key": key}


@router.get("/api/api-keys", response_model=List[APIKeyResponse])
def api_list_api_keys(user=Depends(_session_user)):
    """The signed-in user's API keys — prefixes only, never a full key."""
    from agenticops.services import api_keys
    return api_keys.list_keys(user.id)


@router.delete("/api/api-keys/{key_id}", status_code=204)
def api_revoke_api_key(key_id: int, user=Depends(_session_user)):
    """Revoke one of the signed-in user's API keys (another user's is a 404)."""
    from agenticops.services import api_keys
    try:
        api_keys.revoke_key(key_id, owner_id=user.id, caller=user, by_admin=False)
    except api_keys.ApiKeyError as e:
        return _key_refused(e)
