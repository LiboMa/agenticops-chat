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


class TestIsSensitiveKey:
    """One rule decides which fields are secrets — the encryption and the edit merge both use it."""

    def test_secret_names(self):
        from agenticops.credentials.store import is_sensitive_key

        for name in ("access_key_id", "secret_access_key", "session_token", "client_secret",
                     "service_account_key", "access_key_secret", "password", "bot_token", "My_Api_Key"):
            assert is_sensitive_key(name), name

    def test_plain_names(self):
        from agenticops.credentials.store import is_sensitive_key

        for name in ("role_arn", "external_id", "account_id", "profile_name", "kubeconfigs",
                     "tenant_id", "client_id", "subscription_id", "project_id"):
            assert not is_sensitive_key(name), name


class TestMergeCredentials:
    """An edit merges into the stored credentials (2026-11-09: a region edit dropped a stored key pair)."""

    STORED = {"role_arn": "arn:aws:iam::111122223333:role/Ops", "external_id": "ext-1",
              "account_id": "111122223333", "kubeconfigs": {"eks-a": "/etc/kube/eks-a"},
              "access_key_id": "AKIAOLD", "secret_access_key": "old-secret", "session_token": "old-token"}

    def merge(self, incoming, **kw):
        from agenticops.credentials.store import merge_credentials
        return merge_credentials(dict(self.STORED), incoming, **kw)

    def test_a_secret_left_out_is_kept(self):
        # what the edit form sent on 2026-11-09: the role ARN only — it never sees the stored keys
        assert self.merge({"role_arn": "arn:aws:iam::111122223333:role/Ops"}) == self.STORED

    def test_a_new_secret_replaces_the_stored_one(self):
        merged = self.merge({"secret_access_key": "new-secret"})
        assert merged["secret_access_key"] == "new-secret"
        assert merged["access_key_id"] == "AKIAOLD"

    def test_an_empty_secret_keeps_the_stored_one(self):
        assert self.merge({"access_key_id": "", "secret_access_key": None}) == self.STORED

    def test_a_redacted_or_masked_echo_changes_nothing(self):
        # a GET response sent back, or an agent repeating list_cloud_accounts' masked value
        merged = self.merge({"_encrypted": "***REDACTED***", "access_key_id": "***REDACTED***",
                             "secret_access_key": "****cret", "role_arn": "****/Ops"})
        assert merged == self.STORED

    def test_clear_secrets_removes_every_stored_secret(self):
        merged = self.merge({}, clear_secrets=True)
        assert merged == {k: v for k, v in self.STORED.items()
                          if k not in ("access_key_id", "secret_access_key", "session_token")}

    def test_clear_secrets_with_new_keys_keeps_only_the_new_ones(self):
        merged = self.merge({"access_key_id": "AKIANEW", "secret_access_key": "new-secret"}, clear_secrets=True)
        assert (merged["access_key_id"], merged["secret_access_key"]) == ("AKIANEW", "new-secret")
        assert "session_token" not in merged

    def test_an_empty_plain_field_is_deleted(self):
        merged = self.merge({"external_id": "", "account_id": None})
        assert "external_id" not in merged and "account_id" not in merged

    def test_a_plain_field_is_set(self):
        assert self.merge({"external_id": "ext-2"})["external_id"] == "ext-2"

    def test_fields_left_out_are_kept(self):
        merged = self.merge({"role_arn": "arn:aws:iam::111122223333:role/Other"})
        assert merged["account_id"] == "111122223333"
        assert merged["kubeconfigs"] == {"eks-a": "/etc/kube/eks-a"}

    def test_leaving_assume_role_drops_the_role(self):
        # the provider assumes any role_arn it finds, whatever credential_source_type says
        merged = self.merge({}, switched_from="assume_role")
        assert "role_arn" not in merged and "external_id" not in merged
        assert merged["access_key_id"] == "AKIAOLD" and merged["account_id"] == "111122223333"

    def test_leaving_profile_drops_the_profile(self):
        from agenticops.credentials.store import merge_credentials
        merged = merge_credentials({"profile_name": "prod", "account_id": "1"}, {"access_key_id": "AKIA"},
                                   switched_from="profile")
        assert merged == {"account_id": "1", "access_key_id": "AKIA"}

    def test_a_value_sent_with_the_switch_still_applies(self):
        assert self.merge({"role_arn": "arn:x"}, switched_from="assume_role")["role_arn"] == "arn:x"

    def test_nothing_stored_yet(self):
        from agenticops.credentials.store import merge_credentials
        assert merge_credentials(None, {"role_arn": "arn:x", "external_id": ""}) == {"role_arn": "arn:x"}


class TestMergeUpdate:
    """The store's merge: decrypt what is stored, merge, encrypt again."""

    def setup_method(self):
        from agenticops.credentials.store import CredentialStore, LocalKeyBackend
        self.store = CredentialStore(LocalKeyBackend("merge-test-key"))

    def test_the_stored_keys_survive_an_edit_that_omits_them(self):
        stored = self.store.encrypt_credentials(
            {"role_arn": "arn:aws:iam::1:role/R", "access_key_id": "AKIAOLD", "secret_access_key": "old"})
        updated = self.store.merge_update(stored, {"role_arn": "arn:aws:iam::1:role/R"})
        assert "_encrypted" in updated and "access_key_id" not in updated
        assert self.store.decrypt_credentials(updated) == {
            "role_arn": "arn:aws:iam::1:role/R", "access_key_id": "AKIAOLD", "secret_access_key": "old"}

    def test_an_edit_that_leaves_the_secrets_keeps_the_ciphertext(self):
        # the credential fingerprint (session cache key, private kubeconfig path) hashes the stored form: a region
        # edit must not move it — Fernet would give a new ciphertext for the same secrets
        stored = self.store.encrypt_credentials({"role_arn": "arn:x", "access_key_id": "A", "secret_access_key": "S"})
        updated = self.store.merge_update(stored, {"role_arn": "arn:x", "external_id": "e"})
        assert updated == {"role_arn": "arn:x", "external_id": "e", "_encrypted": stored["_encrypted"]}

    def test_a_changed_secret_is_encrypted_again(self):
        stored = self.store.encrypt_credentials({"access_key_id": "A", "secret_access_key": "S"})
        updated = self.store.merge_update(stored, {"secret_access_key": "S2"})
        assert updated["_encrypted"] != stored["_encrypted"]
        assert self.store.decrypt_credentials(updated) == {"access_key_id": "A", "secret_access_key": "S2"}

    def test_clearing_leaves_no_encrypted_blob(self):
        stored = self.store.encrypt_credentials({"role_arn": "arn:x", "access_key_id": "A", "secret_access_key": "S"})
        assert self.store.merge_update(stored, {}, clear_secrets=True) == {"role_arn": "arn:x"}

    def test_nothing_stored(self):
        updated = self.store.merge_update({}, {"access_key_id": "A", "secret_access_key": "S"})
        assert self.store.decrypt_credentials(updated) == {"access_key_id": "A", "secret_access_key": "S"}


class TestAuditView:
    """What an audit row may say about stored credentials: the plain fields and whether secrets are stored."""

    def test_no_secret_value_and_no_blob(self):
        from agenticops.credentials.store import CredentialStore, PlaintextBackend, audit_view
        stored = CredentialStore(PlaintextBackend()).encrypt_credentials(
            {"role_arn": "arn:x", "access_key_id": "AKIAOLD", "secret_access_key": "old"})
        assert audit_view(stored) == {"fields": {"role_arn": "arn:x"}, "stored_secrets": True}

    def test_a_legacy_plaintext_secret_is_left_out(self):
        from agenticops.credentials.store import audit_view
        assert audit_view({"account_id": "1", "access_key_id": "AKIA"}) == {
            "fields": {"account_id": "1"}, "stored_secrets": True}

    def test_empty(self):
        from agenticops.credentials.store import audit_view
        assert audit_view(None) == {"fields": {}, "stored_secrets": False}
