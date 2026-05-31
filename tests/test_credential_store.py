"""Tests for the Credential Store and SessionFactory.

Tests:
1. CredentialStore encrypt/decrypt with LocalKey backend
2. CredentialStore with Plaintext backend (dev mode)
3. SessionFactory environment detection
4. SessionFactory credential_source_type resolution
5. Integration: encrypt → store → decrypt → session creation
"""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestCredentialStoreLocalKey:
    """Test CredentialStore with LocalKeyBackend."""

    def setup_method(self):
        from agenticops.credentials.store import (
            CredentialStore,
            LocalKeyBackend,
            reset_credential_store,
        )
        reset_credential_store()
        self.backend = LocalKeyBackend("test-master-key-for-unit-tests")
        self.store = CredentialStore(self.backend)

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting then decrypting returns original credentials."""
        creds = {
            "access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "role_arn": "arn:aws:iam::123456789012:role/MyRole",
            "external_id": "aiops-test",
        }
        encrypted = self.store.encrypt_credentials(creds)

        # Encrypted dict should have _encrypted key
        assert "_encrypted" in encrypted
        # Non-sensitive fields preserved in plaintext
        assert encrypted.get("role_arn") == "arn:aws:iam::123456789012:role/MyRole"
        assert encrypted.get("external_id") == "aiops-test"
        # Sensitive fields should NOT be in plaintext
        assert "access_key_id" not in encrypted
        assert "secret_access_key" not in encrypted

        # Decrypt
        decrypted = self.store.decrypt_credentials(encrypted)
        assert decrypted["access_key_id"] == "AKIAIOSFODNN7EXAMPLE"
        assert decrypted["secret_access_key"] == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        assert decrypted["role_arn"] == "arn:aws:iam::123456789012:role/MyRole"
        assert decrypted["external_id"] == "aiops-test"

    def test_encrypt_empty_credentials(self):
        """Empty credentials dict returns as-is."""
        assert self.store.encrypt_credentials({}) == {}
        assert self.store.encrypt_credentials(None) is None

    def test_encrypt_no_sensitive_fields(self):
        """Credentials with no sensitive fields are not encrypted."""
        creds = {"role_arn": "arn:aws:iam::123:role/Test", "external_id": "test"}
        encrypted = self.store.encrypt_credentials(creds)
        # No _encrypted key since role_arn and external_id are not in sensitive list
        assert "_encrypted" not in encrypted
        assert encrypted == creds

    def test_decrypt_unencrypted_credentials(self):
        """Credentials without _encrypted key are returned as-is."""
        creds = {"role_arn": "arn:aws:iam::123:role/Test"}
        assert self.store.decrypt_credentials(creds) == creds

    def test_is_encrypted(self):
        """is_encrypted correctly identifies encrypted credentials."""
        assert not self.store.is_encrypted({})
        assert not self.store.is_encrypted({"role_arn": "test"})
        assert self.store.is_encrypted({"_encrypted": "abc123"})

    def test_different_keys_produce_different_ciphertext(self):
        """Different master keys produce different encrypted outputs."""
        from agenticops.credentials.store import CredentialStore, LocalKeyBackend

        store2 = CredentialStore(LocalKeyBackend("different-key"))
        creds = {"access_key_id": "AKIA123", "secret_access_key": "secret123"}

        enc1 = self.store.encrypt_credentials(creds)
        enc2 = store2.encrypt_credentials(creds)

        assert enc1["_encrypted"] != enc2["_encrypted"]

    def test_wrong_key_fails_decrypt(self):
        """Decrypting with wrong key raises an error."""
        from agenticops.credentials.store import CredentialStore, LocalKeyBackend

        creds = {"access_key_id": "AKIA123", "secret_access_key": "secret123"}
        encrypted = self.store.encrypt_credentials(creds)

        # Try decrypting with different key
        wrong_store = CredentialStore(LocalKeyBackend("wrong-key"))
        with pytest.raises(Exception):
            wrong_store.decrypt_credentials(encrypted)


class TestCredentialStorePlaintext:
    """Test CredentialStore with PlaintextBackend (dev mode)."""

    def setup_method(self):
        from agenticops.credentials.store import (
            CredentialStore,
            PlaintextBackend,
            reset_credential_store,
        )
        reset_credential_store()
        self.store = CredentialStore(PlaintextBackend())

    def test_plaintext_roundtrip(self):
        """Plaintext backend still wraps sensitive fields under _encrypted."""
        creds = {"access_key_id": "AKIA123", "secret_access_key": "secret"}
        encrypted = self.store.encrypt_credentials(creds)
        assert "_encrypted" in encrypted

        decrypted = self.store.decrypt_credentials(encrypted)
        assert decrypted["access_key_id"] == "AKIA123"
        assert decrypted["secret_access_key"] == "secret"


class TestCredentialStoreAutoDetect:
    """Test auto-detection of encryption backend."""

    def test_detects_kms_backend(self):
        from agenticops.credentials.store import reset_credential_store, _detect_backend

        reset_credential_store()
        with patch.dict(os.environ, {"AIOPS_KMS_KEY_ID": "arn:aws:kms:us-east-1:123:key/abc"}):
            backend = _detect_backend()
            assert backend.backend_name == "kms"

    def test_detects_local_key_backend(self):
        from agenticops.credentials.store import reset_credential_store, _detect_backend

        reset_credential_store()
        with patch.dict(os.environ, {"AIOPS_MASTER_KEY": "my-secret-master-key"}, clear=False):
            # Remove KMS key if present
            env = {k: v for k, v in os.environ.items() if k != "AIOPS_KMS_KEY_ID"}
            with patch.dict(os.environ, env, clear=True):
                backend = _detect_backend()
                assert backend.backend_name == "local_key"

    def test_detects_plaintext_backend_explicit(self):
        from agenticops.credentials.store import reset_credential_store, _detect_backend

        reset_credential_store()
        env = {"AIOPS_CREDENTIAL_BACKEND": "plaintext"}
        with patch.dict(os.environ, env, clear=True):
            backend = _detect_backend()
            assert backend.backend_name == "plaintext"

    def test_default_is_plaintext_with_warning(self):
        from agenticops.credentials.store import reset_credential_store, _detect_backend

        reset_credential_store()
        with patch.dict(os.environ, {}, clear=True):
            backend = _detect_backend()
            assert backend.backend_name == "plaintext"


class TestSessionFactory:
    """Test SessionFactory environment detection and session creation."""

    def setup_method(self):
        from agenticops.credentials.session_factory import SessionFactory
        SessionFactory.reset()

    def test_detect_eks_environment(self):
        from agenticops.credentials.session_factory import SessionFactory, EnvironmentType

        factory = SessionFactory()
        with patch.dict(os.environ, {"AWS_WEB_IDENTITY_TOKEN_FILE": "/var/run/secrets/token"}):
            env = factory.detect_environment()
            assert env == EnvironmentType.EKS

    def test_detect_ecs_environment(self):
        from agenticops.credentials.session_factory import SessionFactory, EnvironmentType

        factory = SessionFactory()
        with patch.dict(os.environ, {"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/xxx"}):
            env = factory.detect_environment()
            assert env == EnvironmentType.ECS

    def test_detect_local_environment(self):
        from agenticops.credentials.session_factory import SessionFactory, EnvironmentType

        factory = SessionFactory()
        # Clear cloud env vars
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(factory, "_check_imdsv2", return_value=False):
                factory._environment = None  # Reset cached detection
                env = factory.detect_environment()
                assert env == EnvironmentType.LOCAL

    def test_list_available_profiles_empty(self):
        """No profiles when ~/.aws doesn't exist."""
        from agenticops.credentials.session_factory import SessionFactory

        factory = SessionFactory()
        with patch("pathlib.Path.exists", return_value=False):
            profiles = factory.list_available_profiles()
            assert profiles == []

    def test_credential_source_type_inference(self):
        """Source type is correctly inferred from credentials content."""
        from agenticops.credentials.session_factory import SessionFactory, CredentialSourceType
        from types import SimpleNamespace

        factory = SessionFactory()

        # assume_role
        acct = SimpleNamespace(credentials={"role_arn": "arn:aws:iam::123:role/X"}, credential_source_type="assume_role")
        assert factory._get_source_type(acct) == CredentialSourceType.ASSUME_ROLE

        # profile
        acct = SimpleNamespace(credentials={"profile_name": "prod"}, credential_source_type="profile")
        assert factory._get_source_type(acct) == CredentialSourceType.PROFILE

        # static_keys
        acct = SimpleNamespace(credentials={"access_key_id": "AKIA..."}, credential_source_type="static_keys")
        assert factory._get_source_type(acct) == CredentialSourceType.STATIC_KEYS

        # environment (default)
        acct = SimpleNamespace(credentials={}, credential_source_type="environment")
        assert factory._get_source_type(acct) == CredentialSourceType.ENVIRONMENT

    def test_credential_source_type_inference_from_content(self):
        """Source type inferred from credentials content when type field is empty."""
        from agenticops.credentials.session_factory import SessionFactory, CredentialSourceType
        from types import SimpleNamespace

        factory = SessionFactory()

        # Infer assume_role from content
        acct = SimpleNamespace(credentials={"role_arn": "arn:aws:iam::123:role/X"}, credential_source_type="")
        assert factory._get_source_type(acct) == CredentialSourceType.ASSUME_ROLE

        # Infer profile from content
        acct = SimpleNamespace(credentials={"profile_name": "dev"}, credential_source_type="")
        assert factory._get_source_type(acct) == CredentialSourceType.PROFILE

    def test_session_cache_invalidation(self):
        """Invalidating a session removes it from cache."""
        from agenticops.credentials.session_factory import SessionFactory, CachedSession
        import time

        factory = SessionFactory()
        factory._cache["test-account:us-east-1"] = CachedSession(
            session=MagicMock(), created_at=time.time()
        )
        assert "test-account:us-east-1" in factory._cache

        factory.invalidate("test-account")
        assert "test-account:us-east-1" not in factory._cache

    def test_session_cache_expiry(self):
        """Expired sessions are not returned from cache."""
        from agenticops.credentials.session_factory import CachedSession
        import time

        cached = CachedSession(session=MagicMock(), created_at=time.time() - 7200, ttl=3600)
        assert cached.is_expired

        fresh = CachedSession(session=MagicMock(), created_at=time.time(), ttl=3600)
        assert not fresh.is_expired


class TestLocalKeyGeneration:
    """Test key generation utility."""

    def test_generate_key(self):
        from agenticops.credentials.store import LocalKeyBackend

        key = LocalKeyBackend.generate_key()
        assert len(key) == 44  # Fernet key is 44 chars base64
        # Verify it's a valid Fernet key
        backend = LocalKeyBackend(key)
        data = b"test data"
        assert backend.decrypt(backend.encrypt(data)) == data
