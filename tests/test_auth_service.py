"""Tests for the authentication service (agenticops.auth.service)."""

import sys
sys.path.insert(0, "src")

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops.models import Base
from agenticops.auth.models import User, APIKey, Session
from agenticops.auth.service import (
    AuthService,
    generate_api_key,
    generate_session_token,
    hash_api_key,
    hash_password,
    verify_password,
    get_current_user,
    require_auth,
    require_admin,
)


# ---------------------------------------------------------------------------
# Fixtures – in-memory SQLite for isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_db(tmp_path):
    """Redirect all DB access to an in-memory SQLite DB."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    _Session = sessionmaker(bind=engine, expire_on_commit=False)

    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        sess = _Session()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    with patch("agenticops.auth.service.get_db_session", _fake_session), \
         patch("agenticops.auth.service.init_db"):
        yield engine


# ===========================================================================
# Password hashing
# ===========================================================================


class TestPasswordHashing:
    def test_hash_password_returns_salted_hash(self):
        h = hash_password("secret")
        assert "$" in h
        salt, hashed = h.split("$")
        assert len(salt) == 32  # 16 bytes hex
        assert len(hashed) == 64  # sha256 hex

    def test_hash_password_different_salts(self):
        h1 = hash_password("secret")
        h2 = hash_password("secret")
        assert h1 != h2  # different salts

    def test_verify_password_correct(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h) is True

    def test_verify_password_wrong(self):
        h = hash_password("mypassword")
        assert verify_password("wrong", h) is False

    def test_verify_password_invalid_hash(self):
        assert verify_password("any", "nodotsign") is False

    def test_verify_password_empty(self):
        h = hash_password("")
        assert verify_password("", h) is True
        assert verify_password("x", h) is False


# ===========================================================================
# Key / Token generation
# ===========================================================================


class TestKeyGeneration:
    def test_generate_api_key_format(self):
        key, key_hash = generate_api_key()
        assert key.startswith("aiops_")
        assert key_hash == hashlib.sha256(key.encode()).hexdigest()

    def test_generate_api_key_unique(self):
        k1, _ = generate_api_key()
        k2, _ = generate_api_key()
        assert k1 != k2

    def test_hash_api_key(self):
        key = "aiops_testkey123"
        assert hash_api_key(key) == hashlib.sha256(key.encode()).hexdigest()

    def test_generate_session_token(self):
        token, token_hash = generate_session_token()
        assert len(token) > 20
        assert token_hash == hashlib.sha256(token.encode()).hexdigest()

    def test_generate_session_token_unique(self):
        t1, _ = generate_session_token()
        t2, _ = generate_session_token()
        assert t1 != t2


# ===========================================================================
# AuthService – user management
# ===========================================================================


class TestCreateUser:
    def test_create_user_basic(self):
        user = AuthService.create_user("alice@example.com", "pass123", name="Alice")
        assert user.email == "alice@example.com"
        assert user.name == "Alice"
        assert user.is_admin is False
        assert "read" in user.permissions
        assert "write" in user.permissions
        assert "admin" not in user.permissions

    def test_create_admin_user(self):
        user = AuthService.create_user("admin@example.com", "pass", is_admin=True)
        assert user.is_admin is True
        assert "admin" in user.permissions

    def test_create_user_duplicate_email(self):
        AuthService.create_user("dup@example.com", "p1")
        with pytest.raises(ValueError, match="already exists"):
            AuthService.create_user("dup@example.com", "p2")


class TestAuthenticate:
    def test_authenticate_success(self):
        AuthService.create_user("login@test.com", "correct")
        user = AuthService.authenticate("login@test.com", "correct")
        assert user is not None
        assert user.email == "login@test.com"

    def test_authenticate_wrong_password(self):
        AuthService.create_user("login2@test.com", "right")
        assert AuthService.authenticate("login2@test.com", "wrong") is None

    def test_authenticate_nonexistent_email(self):
        assert AuthService.authenticate("ghost@test.com", "any") is None


class TestGetUserById:
    def test_get_existing_user(self):
        created = AuthService.create_user("byid@test.com", "p")
        found = AuthService.get_user_by_id(created.id)
        assert found is not None
        assert found.email == "byid@test.com"

    def test_get_nonexistent_user(self):
        assert AuthService.get_user_by_id(99999) is None


class TestUpdatePassword:
    def test_update_password_success(self):
        user = AuthService.create_user("pwd@test.com", "old")
        assert AuthService.update_password(user.id, "old", "new") is True
        # can now authenticate with new password
        assert AuthService.authenticate("pwd@test.com", "new") is not None
        assert AuthService.authenticate("pwd@test.com", "old") is None

    def test_update_password_wrong_old(self):
        user = AuthService.create_user("pwd2@test.com", "real")
        assert AuthService.update_password(user.id, "fake", "new") is False

    def test_update_password_nonexistent_user(self):
        assert AuthService.update_password(99999, "a", "b") is False


# ===========================================================================
# AuthService – sessions
# ===========================================================================


class TestSessions:
    def test_create_and_validate_session(self):
        user = AuthService.create_user("sess@test.com", "p")
        token = AuthService.create_session(user.id, ip_address="127.0.0.1", user_agent="pytest")
        assert isinstance(token, str)
        assert len(token) > 20

        found = AuthService.validate_session(token)
        assert found is not None
        assert found.email == "sess@test.com"

    def test_validate_invalid_session(self):
        assert AuthService.validate_session("bogus_token") is None

    def test_invalidate_session(self):
        user = AuthService.create_user("inv@test.com", "p")
        token = AuthService.create_session(user.id)
        assert AuthService.invalidate_session(token) is True
        assert AuthService.validate_session(token) is None

    def test_invalidate_nonexistent_session(self):
        assert AuthService.invalidate_session("nonexistent") is False


# ===========================================================================
# AuthService – API keys
# ===========================================================================


class TestAPIKeys:
    def test_create_and_validate_api_key(self):
        user = AuthService.create_user("apikey@test.com", "p")
        key = AuthService.create_api_key(user.id, "test-key", permissions=["read", "write"])
        assert key.startswith("aiops_")

        result = AuthService.validate_api_key(key)
        assert result is not None
        found_user, found_key = result
        assert found_user.email == "apikey@test.com"
        assert found_key.name == "test-key"

    def test_validate_invalid_api_key(self):
        assert AuthService.validate_api_key("aiops_nonexistent") is None

    def test_create_api_key_with_expiry(self):
        user = AuthService.create_user("expkey@test.com", "p")
        key = AuthService.create_api_key(user.id, "expiring", expires_days=30)
        assert AuthService.validate_api_key(key) is not None

    def test_revoke_api_key(self):
        user = AuthService.create_user("revoke@test.com", "p")
        key = AuthService.create_api_key(user.id, "to-revoke")
        # Get key id
        keys = AuthService.list_api_keys(user.id)
        assert len(keys) == 1
        assert AuthService.revoke_api_key(keys[0].id, user.id) is True
        assert AuthService.validate_api_key(key) is None

    def test_revoke_nonexistent_key(self):
        user = AuthService.create_user("norev@test.com", "p")
        assert AuthService.revoke_api_key(99999, user.id) is False

    def test_list_api_keys(self):
        user = AuthService.create_user("list@test.com", "p")
        AuthService.create_api_key(user.id, "key-1")
        AuthService.create_api_key(user.id, "key-2")
        keys = AuthService.list_api_keys(user.id)
        assert len(keys) == 2
        names = {k.name for k in keys}
        assert names == {"key-1", "key-2"}

    def test_list_api_keys_empty(self):
        user = AuthService.create_user("nokeys@test.com", "p")
        assert AuthService.list_api_keys(user.id) == []

    def test_create_api_key_default_permissions(self):
        user = AuthService.create_user("defperm@test.com", "p")
        key = AuthService.create_api_key(user.id, "default")
        result = AuthService.validate_api_key(key)
        assert result is not None
        _, api_key = result
        assert api_key.permissions == ["read"]


# ===========================================================================
# FastAPI dependencies
# ===========================================================================


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_no_credentials(self):
        request = MagicMock()
        result = await get_current_user(request, credentials=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_api_key_auth(self):
        user = AuthService.create_user("fastapi@test.com", "p")
        key = AuthService.create_api_key(user.id, "api", permissions=["read"])

        request = MagicMock()
        request.state = MagicMock()
        creds = MagicMock()
        creds.credentials = key

        result = await get_current_user(request, credentials=creds)
        assert result is not None
        assert result.email == "fastapi@test.com"

    @pytest.mark.asyncio
    async def test_session_token_auth(self):
        user = AuthService.create_user("session@test.com", "p")
        token = AuthService.create_session(user.id)

        request = MagicMock()
        creds = MagicMock()
        creds.credentials = token

        result = await get_current_user(request, credentials=creds)
        assert result is not None
        assert result.email == "session@test.com"

    @pytest.mark.asyncio
    async def test_invalid_token(self):
        request = MagicMock()
        creds = MagicMock()
        creds.credentials = "invalid_token"

        result = await get_current_user(request, credentials=creds)
        assert result is None


class TestRequireAuth:
    @pytest.mark.asyncio
    async def test_require_auth_no_user(self):
        from fastapi import HTTPException
        dep = require_auth()
        request = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await dep(request, user=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_auth_with_user(self):
        dep = require_auth()
        request = MagicMock()
        user = MagicMock()
        result = await dep(request, user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_require_auth_insufficient_permissions(self):
        from fastapi import HTTPException
        dep = require_auth(permissions=["admin"])
        request = MagicMock()
        request.state = MagicMock(spec=[])  # no api_key attr
        user = MagicMock()
        user.permissions = ["read"]
        with pytest.raises(HTTPException) as exc_info:
            await dep(request, user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_auth_api_key_narrows_permissions(self):
        from fastapi import HTTPException
        dep = require_auth(permissions=["write"])
        request = MagicMock()
        api_key = MagicMock()
        api_key.permissions = ["read"]  # api key only has read
        request.state.api_key = api_key
        user = MagicMock()
        user.permissions = ["read", "write"]  # user has write but key doesn't
        with pytest.raises(HTTPException) as exc_info:
            await dep(request, user=user)
        assert exc_info.value.status_code == 403


class TestRequireAdmin:
    @pytest.mark.asyncio
    async def test_require_admin_non_admin(self):
        from fastapi import HTTPException
        dep = require_admin()
        user = MagicMock()
        user.is_admin = False
        with pytest.raises(HTTPException) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_admin_success(self):
        dep = require_admin()
        user = MagicMock()
        user.is_admin = True
        result = await dep(user=user)
        assert result is user
