"""Authentication service for AgenticOps."""

import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Tuple, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from agenticops.models import get_db_session, init_db
from agenticops.auth.models import User, APIKey, Session


# ============================================================================
# Password Hashing
# ============================================================================


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt.

    Note: In production, use bcrypt or argon2 instead.
    """
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}${hashed}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    try:
        salt, hashed = password_hash.split("$")
        check_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return secrets.compare_digest(hashed, check_hash)
    except ValueError:
        return False


# ============================================================================
# API Key Generation
# ============================================================================


def generate_api_key() -> Tuple[str, str]:
    """Generate a new API key.

    Returns:
        Tuple of (plain_key, key_hash)
    """
    key = f"aiops_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return key, key_hash


def hash_api_key(key: str) -> str:
    """Hash an API key."""
    return hashlib.sha256(key.encode()).hexdigest()


# ============================================================================
# Session Token Generation
# ============================================================================


def generate_session_token() -> Tuple[str, str]:
    """Generate a new session token.

    Returns:
        Tuple of (plain_token, token_hash)
    """
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


# ============================================================================
# Authentication Service
# ============================================================================


class AuthService:
    """Service for user authentication and authorization."""

    SESSION_DURATION_HOURS = 24
    API_KEY_DEFAULT_EXPIRY_DAYS = 365

    @staticmethod
    def create_user(
        email: str,
        password: str,
        name: Optional[str] = None,
        is_admin: bool = False,
    ) -> User:
        """Create a new user.

        Args:
            email: User email
            password: Plain text password
            name: Optional display name
            is_admin: Whether user has admin privileges

        Returns:
            Created User instance
        """
        init_db()

        with get_db_session() as session:
            # Check if email already exists
            existing = session.query(User).filter_by(email=email).first()
            if existing:
                raise ValueError(f"User with email '{email}' already exists")

            user = User(
                email=email,
                password_hash=hash_password(password),
                name=name,
                is_admin=is_admin,
                permissions=["read", "write"] if not is_admin else ["read", "write", "admin"],
            )
            session.add(user)
            session.flush()
            return user

    @staticmethod
    def authenticate(email: str, password: str) -> Optional[User]:
        """Authenticate a user by email and password.

        Args:
            email: User email
            password: Plain text password

        Returns:
            User if authentication successful, None otherwise
        """
        with get_db_session() as session:
            user = session.query(User).filter_by(email=email, is_active=True).first()
            if user and verify_password(password, user.password_hash):
                user.last_login_at = datetime.utcnow()
                return user
            return None

    @staticmethod
    def create_session(user_id: int, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> str:
        """Create a new session for a user.

        Args:
            user_id: User ID
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Session token (plain text)
        """
        token, token_hash = generate_session_token()

        with get_db_session() as session:
            db_session = Session(
                user_id=user_id,
                token_hash=token_hash,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=datetime.utcnow() + timedelta(hours=AuthService.SESSION_DURATION_HOURS),
            )
            session.add(db_session)

        return token

    @staticmethod
    def validate_session(token: str) -> Optional[User]:
        """Validate a session token.

        Args:
            token: Plain text session token

        Returns:
            User if session is valid, None otherwise
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        with get_db_session() as session:
            db_session = (
                session.query(Session)
                .filter_by(token_hash=token_hash)
                .filter(Session.expires_at > datetime.utcnow())
                .first()
            )

            if db_session:
                user = session.query(User).filter_by(
                    id=db_session.user_id,
                    is_active=True,
                ).first()
                return user

        return None

    @staticmethod
    def invalidate_session(token: str) -> bool:
        """Invalidate a session token (logout).

        Args:
            token: Plain text session token

        Returns:
            True if session was invalidated
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        with get_db_session() as session:
            db_session = session.query(Session).filter_by(token_hash=token_hash).first()
            if db_session:
                session.delete(db_session)
                return True
        return False

    @staticmethod
    def create_api_key(
        user_id: int,
        name: str,
        permissions: Optional[list] = None,
        expires_days: Optional[int] = None,
    ) -> str:
        """Create a new API key for a user.

        Args:
            user_id: User ID
            name: Key name/description
            permissions: Key permissions
            expires_days: Days until expiry

        Returns:
            API key (plain text) - only returned once!
        """
        key, key_hash = generate_api_key()

        expires_at = None
        if expires_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)

        with get_db_session() as session:
            api_key = APIKey(
                user_id=user_id,
                name=name,
                key_hash=key_hash,
                key_prefix=key[:12],
                permissions=permissions or ["read"],
                expires_at=expires_at,
            )
            session.add(api_key)

        return key

    @staticmethod
    def validate_api_key(key: str) -> Optional[Tuple[User, APIKey]]:
        """Validate an API key.

        Args:
            key: Plain text API key

        Returns:
            Tuple of (User, APIKey) if valid, None otherwise
        """
        key_hash = hash_api_key(key)

        with get_db_session() as session:
            api_key = (
                session.query(APIKey)
                .filter_by(key_hash=key_hash, is_active=True)
                .first()
            )

            if api_key:
                # Check expiry
                if api_key.expires_at and api_key.expires_at < datetime.utcnow():
                    return None

                # Update last used
                api_key.last_used_at = datetime.utcnow()

                # Get user
                user = session.query(User).filter_by(
                    id=api_key.user_id,
                    is_active=True,
                ).first()

                if user:
                    return user, api_key

        return None

    @staticmethod
    def revoke_api_key(key_id: int, user_id: int) -> bool:
        """Revoke an API key.

        Args:
            key_id: API key ID
            user_id: User ID (for authorization)

        Returns:
            True if key was revoked
        """
        with get_db_session() as session:
            api_key = session.query(APIKey).filter_by(id=key_id, user_id=user_id).first()
            if api_key:
                api_key.is_active = False
                return True
        return False

    @staticmethod
    def list_api_keys(user_id: int) -> list:
        """List API keys for a user.

        Args:
            user_id: User ID

        Returns:
            List of APIKey objects
        """
        with get_db_session() as session:
            return session.query(APIKey).filter_by(user_id=user_id).all()

    @staticmethod
    def get_user_by_id(user_id: int) -> Optional[User]:
        """Get a user by ID.

        Args:
            user_id: User ID

        Returns:
            User if found
        """
        with get_db_session() as session:
            return session.query(User).filter_by(id=user_id).first()

    @staticmethod
    def update_password(user_id: int, old_password: str, new_password: str) -> bool:
        """Update a user's password.

        Args:
            user_id: User ID
            old_password: Current password
            new_password: New password

        Returns:
            True if password was updated
        """
        with get_db_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if user and verify_password(old_password, user.password_hash):
                user.password_hash = hash_password(new_password)
                return True
        return False


# ============================================================================
# FastAPI Dependencies
# ============================================================================


security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    """Get the current authenticated user from the request.

    Supports both session tokens and API keys via Bearer authentication.
    """
    if not credentials:
        return None

    token = credentials.credentials

    # Try API key first (starts with aiops_)
    if token.startswith("aiops_"):
        result = AuthService.validate_api_key(token)
        if result:
            user, api_key = result
            request.state.api_key = api_key
            return user
    else:
        # Try session token
        user = AuthService.validate_session(token)
        if user:
            return user

    return None


def require_auth(permissions: Optional[list] = None) -> Callable:
    """Dependency that requires authentication.

    Args:
        permissions: Required permissions (e.g., ["read", "write"])
    """
    async def dependency(
        request: Request,
        user: Optional[User] = Depends(get_current_user),
    ) -> User:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if permissions:
            user_perms = set(user.permissions)
            required_perms = set(permissions)

            # Check API key permissions if applicable
            api_key = getattr(request.state, "api_key", None)
            if api_key:
                user_perms = user_perms.intersection(set(api_key.permissions))

            if not required_perms.issubset(user_perms):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions",
                )

        return user

    return dependency


def require_admin() -> Callable:
    """Dependency that requires admin privileges."""
    async def dependency(
        user: User = Depends(require_auth(["admin"])),
    ) -> User:
        if not user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges required",
            )
        return user

    return dependency
