"""Tests for CredentialStore — Fernet-based credential encryption."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from agenticops.providers.credential_store import (
    CredentialStore,
    get_credential_store,
    reset_credential_store,
    _KEY_ENV_VAR,
    _KEY_FILE_PATH,
    _resolve_key,
)


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset singleton between tests."""
    reset_credential_store()
    yield
    reset_credential_store()


@pytest.fixture
def test_key():
    return Fernet.generate_key()


@pytest.fixture
def store(test_key):
    return CredentialStore(test_key)


class TestCredentialStore:
    """Core encrypt/decrypt functionality."""

    def test_encrypt_decrypt_roundtrip(self, store):
        """Encrypted credentials can be decrypted back to original."""
        creds = {
            "role_arn": "arn:aws:iam::123456789012:role/ops",
            "account_id": "123456789012",
            "external_id": "secret-ext-id",
        }
        token = store.encrypt(creds)
        assert isinstance(token, str)
        assert token != json.dumps(creds)  # Not plaintext
        result = store.decrypt(token)
        assert result == creds

    def test_encrypt_decrypt_empty_dict(self, store):
        """Empty credentials dict roundtrips correctly."""
        token = store.encrypt({})
        assert store.decrypt(token) == {}

    def test_encrypt_decrypt_complex_credentials(self, store):
        """Complex nested credentials roundtrip correctly."""
        creds = {
            "client_id": "app-xxx",
            "client_secret": "super-secret-value",
            "tenant_id": "t-xxx",
            "service_account_key": {
                "type": "service_account",
                "project_id": "my-project",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
            },
        }
        token = store.encrypt(creds)
        assert store.decrypt(token) == creds

    def test_decrypt_with_wrong_key_fails(self, store):
        """Decryption with a different key raises InvalidToken."""
        token = store.encrypt({"secret": "value"})
        wrong_store = CredentialStore(Fernet.generate_key())
        with pytest.raises(InvalidToken):
            wrong_store.decrypt(token)

    def test_encrypted_token_not_plaintext(self, store):
        """The encrypted token does not contain any plaintext credential values."""
        creds = {
            "access_key_secret": "MY_SUPER_SECRET_KEY_12345",
            "client_secret": "another-secret-value",
        }
        token = store.encrypt(creds)
        assert "MY_SUPER_SECRET_KEY_12345" not in token
        assert "another-secret-value" not in token
        assert "access_key_secret" not in token


class TestKeyResolution:
    """Key source priority: env → file → auto-generate."""

    def test_key_from_env_var(self, test_key):
        """Priority 1: Key from environment variable."""
        with patch.dict(os.environ, {_KEY_ENV_VAR: test_key.decode("ascii")}):
            key = _resolve_key()
            assert key == test_key

    def test_key_from_file(self, tmp_path, test_key):
        """Priority 2: Key from file."""
        key_file = tmp_path / "credential.key"
        key_file.write_bytes(test_key)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_KEY_ENV_VAR, None)
            with patch(
                "agenticops.providers.credential_store._KEY_FILE_PATH",
                key_file,
            ):
                key = _resolve_key()
                assert key == test_key

    def test_key_auto_generate(self, tmp_path):
        """Priority 3: Auto-generate key and write to file."""
        key_file = tmp_path / "auto" / "credential.key"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_KEY_ENV_VAR, None)
            with patch(
                "agenticops.providers.credential_store._KEY_FILE_PATH",
                key_file,
            ):
                key = _resolve_key()
                assert key_file.exists()
                assert key_file.read_bytes().strip() == key
                # Verify it's a valid Fernet key
                Fernet(key)

    def test_singleton_returns_same_instance(self, test_key):
        """get_credential_store() returns singleton."""
        with patch.dict(os.environ, {_KEY_ENV_VAR: test_key.decode("ascii")}):
            s1 = get_credential_store()
            s2 = get_credential_store()
            assert s1 is s2
