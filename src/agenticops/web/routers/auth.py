"""Auth / users / api-keys API endpoints — extracted from app.py (no logic change)."""

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, HTTPException, Request

from agenticops.models import get_db_session
from agenticops.web.schemas import (
    APIKeyCreate,
    APIKeyCreatedResponse,
    APIKeyResponse,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    RegisterRequest,
    UserResponse,
)

router = APIRouter()


@router.post("/api/auth/register", response_model=UserResponse, status_code=201)
async def api_register(request_data: RegisterRequest):
    """Register a new user."""
    from agenticops.auth import AuthService

    try:
        user = AuthService.create_user(
            email=request_data.email,
            password=request_data.password,
            name=request_data.name,
        )
        return UserResponse.model_validate(user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
async def api_change_password(request: Request, request_data: PasswordChangeRequest):
    """Change the current user's password."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not AuthService.update_password(user.id, request_data.old_password, request_data.new_password):
        raise HTTPException(status_code=400, detail="Invalid current password")

    return {"message": "Password changed successfully"}


@router.post("/api/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
async def api_create_api_key(request: Request, request_data: APIKeyCreate):
    """Create a new API key for the current user."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Create API key
    key = AuthService.create_api_key(
        user_id=user.id,
        name=request_data.name,
        permissions=request_data.permissions,
        expires_days=request_data.expires_days,
    )

    # Get the created key info
    with get_db_session() as session:
        from agenticops.auth.models import APIKey
        api_key = session.query(APIKey).filter_by(user_id=user.id).order_by(APIKey.created_at.desc()).first()

        return APIKeyCreatedResponse(
            id=api_key.id,
            name=api_key.name,
            key=key,  # Full key - only shown once!
            permissions=api_key.permissions,
            expires_at=api_key.expires_at,
        )


@router.get("/api/api-keys", response_model=List[APIKeyResponse])
async def api_list_api_keys(request: Request):
    """List API keys for the current user."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    keys = AuthService.list_api_keys(user.id)
    return [APIKeyResponse.model_validate(k) for k in keys]


@router.delete("/api/api-keys/{key_id}", status_code=204)
async def api_revoke_api_key(request: Request, key_id: int):
    """Revoke an API key."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not AuthService.revoke_api_key(key_id, user.id):
        raise HTTPException(status_code=404, detail="API key not found")
