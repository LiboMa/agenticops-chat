"""Tests for agenticops.auth.service — authentication & authorization.

Three layers:
1. Utility functions (pure, no DB)
2. AuthService class (SQLite in-memory)
3. FastAPI dependencies (security tests — token/key/permissions)

Security focus per Architect: token expiry, invalid tokens, permission intersection.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops.models import Base
from agenticops.auth.models import User, APIKey, Session as SessionModel


# ── DB Fixture ───────────────────────────────────────────────────────


@pytest.fixture
def db_engine(tmp_path):
    """Create a temporary SQLite database with auth tables."""
    url = f"sqlite:///{tmp_path}/test_auth.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def patch_db(db_engine, db_session_factory):
    """Patch get_db_session and init_db to use test database."""
    from contextlib import contextmanager

    @contextmanager
    def _get_db_session():
        session = db_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    with patch("agenticops.auth.service.get_db_session", _get_db_session), \
         patch("agenticops.auth.service.init_db"):
        yield _get_db_session


# ── Layer 1: Utility Functions ───────────────────────────────────────


class TestHashPassword:

    def test_returns_salt_hash_format(self):
        from agenticops.auth.service import hash_password
        result = hash_password("test123")
        assert "$" in result
        parts = result.split("$")
        assert len(parts) == 2
        assert len(parts[0]) == 32  # hex salt
        assert len(parts[1]) == 64  # sha256 hex

    def test_different_calls_produce_different_hashes(self):
        from agenticops.auth.service import hash_password
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Different salts


class TestVerifyPassword:

    def test_correct_password(self):
        from agenticops.auth.service import hash_password, verify_password
        hashed = hash_password("mypass")
        assert verify_password("mypass", hashed) is True

    def test_wrong_password(self):
        from agenticops.auth.service import hash_password, verify_password
        hashed = hash_password("mypass")
        assert verify_password("wrongpass", hashed) is False

    def test_malformed_hash_no_dollar(self):
        from agenticops.auth.service import verify_password
        assert verify_password("anything", "nodoallarsign") is False

    def test_empty_password(self):
        from agenticops.auth.service import hash_password, verify_password
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False


class TestGenerateApiKey:

    def test_prefix(self):
        from agenticops.auth.service import generate_api_key
        key, key_hash = generate_api_key()
        assert key.startswith("aiops_")

    def test_hash_matches(self):
        from agenticops.auth.service import generate_api_key
        key, key_hash = generate_api_key()
        assert hashlib.sha256(key.encode()).hexdigest() == key_hash

    def test_uniqueness(self):
        from agenticops.auth.service import generate_api_key
        keys = {generate_api_key()[0] for _ in range(10)}
        assert len(keys) == 10


class TestGenerateSessionToken:

    def test_hash_matches(self):
        from agenticops.auth.service import generate_session_token
        token, token_hash = generate_session_token()
        assert hashlib.sha256(token.encode()).hexdigest() == token_hash

    def test_uniqueness(self):
        from agenticops.auth.service import generate_session_token
        tokens = {generate_session_token()[0] for _ in range(10)}
        assert len(tokens) == 10


# ── Layer 2: AuthService ─────────────────────────────────────────────


class TestCreateUser:

    def test_create_user(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("test@example.com", "pass123", name="Test")
        assert user.email == "test@example.com"
        assert user.name == "Test"
        assert user.is_admin is False
        assert "read" in user.permissions
        assert "write" in user.permissions

    def test_admin_permissions(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("admin@example.com", "pass", is_admin=True)
        assert user.is_admin is True
        assert "admin" in user.permissions

    def test_duplicate_email_raises(self, patch_db):
        from agenticops.auth.service import AuthService
        AuthService.create_user("dup@example.com", "pass")
        with pytest.raises(ValueError, match="already exists"):
            AuthService.create_user("dup@example.com", "pass2")


class TestAuthenticate:

    def test_correct_credentials(self, patch_db):
        from agenticops.auth.service import AuthService
        AuthService.create_user("auth@example.com", "secret")
        user = AuthService.authenticate("auth@example.com", "secret")
        assert user is not None
        assert user.email == "auth@example.com"

    def test_wrong_password(self, patch_db):
        from agenticops.auth.service import AuthService
        AuthService.create_user("auth2@example.com", "secret")
        user = AuthService.authenticate("auth2@example.com", "wrong")
        assert user is None

    def test_nonexistent_user(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.authenticate("noone@example.com", "pass")
        assert user is None

    def test_inactive_user(self, patch_db, db_session_factory):
        from agenticops.auth.service import AuthService
        AuthService.create_user("inactive@example.com", "pass")
        # Deactivate the user
        with db_session_factory() as s:
            u = s.query(User).filter_by(email="inactive@example.com").first()
            u.is_active = False
            s.commit()
        user = AuthService.authenticate("inactive@example.com", "pass")
        assert user is None


class TestSessionCRUD:

    def test_create_and_validate_session(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("sess@example.com", "pass")
        token = AuthService.create_session(user.id, ip_address="127.0.0.1")
        assert isinstance(token, str)
        validated_user = AuthService.validate_session(token)
        assert validated_user is not None
        assert validated_user.email == "sess@example.com"

    def test_expired_session(self, patch_db, db_session_factory):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("exp@example.com", "pass")
        token = AuthService.create_session(user.id)
        # Expire the session
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with db_session_factory() as s:
            sess = s.query(SessionModel).filter_by(token_hash=token_hash).first()
            sess.expires_at = datetime.utcnow() - timedelta(hours=1)
            s.commit()
        assert AuthService.validate_session(token) is None

    def test_invalidate_session(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("logout@example.com", "pass")
        token = AuthService.create_session(user.id)
        assert AuthService.invalidate_session(token) is True
        assert AuthService.validate_session(token) is None

    def test_invalidate_nonexistent_token(self, patch_db):
        from agenticops.auth.service import AuthService
        assert AuthService.invalidate_session("nonexistent-token") is False

    def test_session_for_inactive_user(self, patch_db, db_session_factory):
        """Session valid but user deactivated → should return None."""
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("deact@example.com", "pass")
        token = AuthService.create_session(user.id)
        with db_session_factory() as s:
            u = s.query(User).filter_by(email="deact@example.com").first()
            u.is_active = False
            s.commit()
        assert AuthService.validate_session(token) is None


class TestApiKeyCRUD:

    def test_create_and_validate(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("key@example.com", "pass")
        key = AuthService.create_api_key(user.id, "test-key", permissions=["read"])
        assert key.startswith("aiops_")
        result = AuthService.validate_api_key(key)
        assert result is not None
        validated_user, api_key = result
        assert validated_user.email == "key@example.com"
        assert api_key.name == "test-key"

    def test_expired_key(self, patch_db, db_session_factory):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("expkey@example.com", "pass")
        key = AuthService.create_api_key(user.id, "expiring", expires_days=1)
        # Expire it
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        with db_session_factory() as s:
            ak = s.query(APIKey).filter_by(key_hash=key_hash).first()
            ak.expires_at = datetime.utcnow() - timedelta(hours=1)
            s.commit()
        assert AuthService.validate_api_key(key) is None

    def test_revoked_key(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("revoke@example.com", "pass")
        key = AuthService.create_api_key(user.id, "to-revoke")
        # Get key ID
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        keys = AuthService.list_api_keys(user.id)
        assert len(keys) >= 1
        key_id = keys[0].id
        assert AuthService.revoke_api_key(key_id, user.id) is True
        assert AuthService.validate_api_key(key) is None

    def test_revoke_wrong_user(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("owner@example.com", "pass")
        AuthService.create_api_key(user.id, "owned")
        keys = AuthService.list_api_keys(user.id)
        # Try revoking with wrong user_id
        assert AuthService.revoke_api_key(keys[0].id, user_id=9999) is False

    def test_invalid_key(self, patch_db):
        from agenticops.auth.service import AuthService
        assert AuthService.validate_api_key("aiops_bogus_key_123") is None

    def test_key_for_inactive_user(self, patch_db, db_session_factory):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("inactkey@example.com", "pass")
        key = AuthService.create_api_key(user.id, "key")
        with db_session_factory() as s:
            u = s.query(User).filter_by(email="inactkey@example.com").first()
            u.is_active = False
            s.commit()
        assert AuthService.validate_api_key(key) is None

    def test_key_no_expiry(self, patch_db):
        """Key created without expires_days should not expire."""
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("noexp@example.com", "pass")
        key = AuthService.create_api_key(user.id, "forever")
        result = AuthService.validate_api_key(key)
        assert result is not None


class TestUpdatePassword:

    def test_update_success(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("pwup@example.com", "old_pass")
        assert AuthService.update_password(user.id, "old_pass", "new_pass") is True
        # Old password should fail, new should work
        assert AuthService.authenticate("pwup@example.com", "old_pass") is None
        assert AuthService.authenticate("pwup@example.com", "new_pass") is not None

    def test_wrong_old_password(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("pwfail@example.com", "correct")
        assert AuthService.update_password(user.id, "wrong", "new") is False


# ── Layer 3: FastAPI Dependencies (Security) ─────────────────────────


class TestGetCurrentUser:

    @pytest.mark.asyncio
    async def test_no_credentials(self):
        from agenticops.auth.service import get_current_user
        request = MagicMock()
        result = await get_current_user(request, credentials=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_api_key_path(self, patch_db):
        from agenticops.auth.service import get_current_user, AuthService
        user = AuthService.create_user("apipath@example.com", "pass")
        key = AuthService.create_api_key(user.id, "test")

        request = MagicMock()
        request.state = MagicMock(spec=[])  # No api_key attr initially
        creds = MagicMock()
        creds.credentials = key
        result = await get_current_user(request, credentials=creds)
        assert result is not None
        assert result.email == "apipath@example.com"
        assert hasattr(request.state, "api_key")

    @pytest.mark.asyncio
    async def test_session_token_path(self, patch_db):
        from agenticops.auth.service import get_current_user, AuthService
        user = AuthService.create_user("sesspath@example.com", "pass")
        token = AuthService.create_session(user.id)

        request = MagicMock()
        creds = MagicMock()
        creds.credentials = token  # No aiops_ prefix
        result = await get_current_user(request, credentials=creds)
        assert result is not None
        assert result.email == "sesspath@example.com"

    @pytest.mark.asyncio
    async def test_invalid_token(self, patch_db):
        from agenticops.auth.service import get_current_user
        request = MagicMock()
        creds = MagicMock()
        creds.credentials = "totally_invalid_token"
        result = await get_current_user(request, credentials=creds)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_api_key(self, patch_db):
        from agenticops.auth.service import get_current_user
        request = MagicMock()
        creds = MagicMock()
        creds.credentials = "aiops_invalid_key_xxx"
        result = await get_current_user(request, credentials=creds)
        assert result is None


class TestRequireAuth:

    @pytest.mark.asyncio
    async def test_unauthenticated_401(self):
        from agenticops.auth.service import require_auth
        from fastapi import HTTPException
        dep = require_auth()
        request = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await dep(request, user=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_passes(self):
        from agenticops.auth.service import require_auth
        dep = require_auth()
        request = MagicMock()
        user = MagicMock()
        user.permissions = ["read", "write"]
        result = await dep(request, user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_insufficient_permissions_403(self):
        from agenticops.auth.service import require_auth
        from fastapi import HTTPException
        dep = require_auth(permissions=["admin"])
        request = MagicMock()
        request.state = MagicMock(spec=[])  # No api_key
        user = MagicMock()
        user.permissions = ["read", "write"]  # No admin
        with pytest.raises(HTTPException) as exc_info:
            await dep(request, user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_api_key_permission_intersection(self):
        """User has [read, write] but API key only has [read] → write should be denied."""
        from agenticops.auth.service import require_auth
        from fastapi import HTTPException

        dep = require_auth(permissions=["write"])
        request = MagicMock()
        api_key = MagicMock()
        api_key.permissions = ["read"]  # Key only has read
        request.state.api_key = api_key

        user = MagicMock()
        user.permissions = ["read", "write"]  # User has both

        with pytest.raises(HTTPException) as exc_info:
            await dep(request, user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_api_key_permission_intersection_allows(self):
        """User has [read, write] and API key has [read, write] → read should pass."""
        from agenticops.auth.service import require_auth

        dep = require_auth(permissions=["read"])
        request = MagicMock()
        api_key = MagicMock()
        api_key.permissions = ["read", "write"]
        request.state.api_key = api_key

        user = MagicMock()
        user.permissions = ["read", "write"]

        result = await dep(request, user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_api_key_empty_intersection(self):
        """User perms and key perms have zero overlap → should 403."""
        from agenticops.auth.service import require_auth
        from fastapi import HTTPException

        dep = require_auth(permissions=["write"])
        request = MagicMock()
        api_key = MagicMock()
        api_key.permissions = ["read"]  # Only read
        request.state.api_key = api_key

        user = MagicMock()
        user.permissions = ["write"]  # Only write — intersect with key's [read] = empty

        with pytest.raises(HTTPException) as exc_info:
            await dep(request, user=user)
        assert exc_info.value.status_code == 403


class TestRequireAdmin:

    @pytest.mark.asyncio
    async def test_non_admin_403(self):
        from agenticops.auth.service import require_admin
        from fastapi import HTTPException
        dep = require_admin()
        user = MagicMock()
        user.is_admin = False
        user.permissions = ["read", "write"]
        with pytest.raises(HTTPException) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_passes(self):
        from agenticops.auth.service import require_admin
        dep = require_admin()
        user = MagicMock()
        user.is_admin = True
        user.permissions = ["read", "write", "admin"]
        result = await dep(user=user)
        assert result == user


class TestGetUserById:

    def test_found(self, patch_db):
        from agenticops.auth.service import AuthService
        user = AuthService.create_user("byid@example.com", "pass")
        found = AuthService.get_user_by_id(user.id)
        assert found is not None
        assert found.email == "byid@example.com"

    def test_not_found(self, patch_db):
        from agenticops.auth.service import AuthService
        assert AuthService.get_user_by_id(9999) is None
