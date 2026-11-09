"""CredentialStore — encrypt/decrypt credentials at rest.

Supports three backends:
- KMS: AWS KMS envelope encryption (production, when AIOPS_KMS_KEY_ID is set)
- LocalKey: Fernet symmetric encryption (Docker/on-prem, when AIOPS_MASTER_KEY is set)
- Plaintext: No encryption (dev only, explicit opt-in)

Credentials are stored as JSON in the DB. When encrypted, the JSON value is:
  {"_encrypted": "<base64-encoded-ciphertext>"}
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel to detect encrypted credentials
_ENCRYPTED_KEY = "_encrypted"

# What a stored secret looks like on the way out: the API's redaction (web/schemas.AccountResponse) and the masks
# list_cloud_accounts prints. An edit that sends one of them back means "unchanged", never a new value.
REDACTED_VALUE = "***REDACTED***"
_MASKED = re.compile(r"\*{4}.{0,4}")

_SENSITIVE_NAMES = frozenset({
    "access_key_id", "secret_access_key", "session_token",
    "client_secret", "private_key", "private_key_id",
    "app_secret", "bot_token", "app_token", "password",
})

# The fields a credential method owns. The AWS provider uses any of them it finds, whatever credential_source_type
# says (a role_arn is assumed, a profile_name wins over keys), so switching away from the method drops them.
_METHOD_FIELDS = {"assume_role": ("role_arn", "external_id"), "profile": ("profile_name",)}


def is_sensitive_key(key: str) -> bool:
    """A secret field: encrypted at rest, never shown, kept by an edit that does not give a new value."""
    k = key.lower()
    return k in _SENSITIVE_NAMES or any(part in k for part in ("secret", "key", "token", "password"))


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_echo(value: Any) -> bool:
    return isinstance(value, str) and (value == REDACTED_VALUE or bool(_MASKED.fullmatch(value)))


def merge_credentials(current: dict | None, incoming: dict | None, *, clear_secrets: bool = False,
                      switched_from: str | None = None) -> dict:
    """Apply an edit to plaintext credentials (2026-11-09: a region edit replaced them and lost a key pair).

    The edit form never sees a stored secret (the API redacts them), so a secret field is replaced only by a new,
    non-empty value — empty or left out keeps it. A plain field is set by a value and deleted by "" or None. A field
    the edit leaves out is kept (account_id, kubeconfigs: the form has no input for them). A redaction or mask sent
    back changes nothing. `clear_secrets` removes every stored secret first; `switched_from` is the previous
    credential_source_type when it changes, whose own fields are dropped before the edit applies.
    """
    merged = dict(current or {})
    if clear_secrets:
        merged = {k: v for k, v in merged.items() if not is_sensitive_key(k)}
    for k in _METHOD_FIELDS.get(switched_from or "", ()):
        merged.pop(k, None)
    for k, v in (incoming or {}).items():
        if k == _ENCRYPTED_KEY or _is_echo(v):
            continue
        if is_sensitive_key(k):
            if not _is_empty(v):
                merged[k] = v
        elif _is_empty(v):
            merged.pop(k, None)
        else:
            merged[k] = v
    return merged


def audit_view(stored: dict | None) -> dict:
    """What an audit row may say about credentials as stored: the plain fields and whether a secret is stored —
    never a secret value, never the encrypted blob."""
    stored = stored or {}
    return {"fields": {k: v for k, v in stored.items() if k != _ENCRYPTED_KEY and not is_sensitive_key(k)},
            "stored_secrets": any(k == _ENCRYPTED_KEY or is_sensitive_key(k) for k in stored)}


class EncryptionBackend(ABC):
    """Abstract encryption backend."""

    @abstractmethod
    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt plaintext bytes, return ciphertext bytes."""
        ...

    @abstractmethod
    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt ciphertext bytes, return plaintext bytes."""
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...


class KMSBackend(EncryptionBackend):
    """AWS KMS envelope encryption.

    Uses GenerateDataKey for encryption, Decrypt for decryption.
    Stores: encrypted_data_key + ciphertext (AES-256-GCM via Fernet).
    """

    def __init__(self, kms_key_id: str, region: str = "us-east-1"):
        self._kms_key_id = kms_key_id
        self._region = region

    @property
    def backend_name(self) -> str:
        return "kms"

    def encrypt(self, plaintext: bytes) -> bytes:
        import boto3
        from cryptography.fernet import Fernet

        kms = boto3.client("kms", region_name=self._region)
        # Generate data key
        resp = kms.generate_data_key(KeyId=self._kms_key_id, KeySpec="AES_256")
        data_key = resp["Plaintext"]
        encrypted_data_key = resp["CiphertextBlob"]

        # Encrypt with data key using Fernet
        fernet_key = base64.urlsafe_b64encode(data_key[:32])
        f = Fernet(fernet_key)
        ciphertext = f.encrypt(plaintext)

        # Pack: encrypted_data_key_length (4 bytes) + encrypted_data_key + ciphertext
        edk_len = len(encrypted_data_key).to_bytes(4, "big")
        return edk_len + encrypted_data_key + ciphertext

    def decrypt(self, ciphertext: bytes) -> bytes:
        import boto3
        from cryptography.fernet import Fernet

        kms = boto3.client("kms", region_name=self._region)

        # Unpack
        edk_len = int.from_bytes(ciphertext[:4], "big")
        encrypted_data_key = ciphertext[4 : 4 + edk_len]
        encrypted_payload = ciphertext[4 + edk_len :]

        # Decrypt data key via KMS
        resp = kms.decrypt(CiphertextBlob=encrypted_data_key)
        data_key = resp["Plaintext"]

        # Decrypt payload with data key
        fernet_key = base64.urlsafe_b64encode(data_key[:32])
        f = Fernet(fernet_key)
        return f.decrypt(encrypted_payload)


class LocalKeyBackend(EncryptionBackend):
    """Fernet symmetric encryption using a local master key.

    Master key from AIOPS_MASTER_KEY env var (32-byte base64url-encoded).
    If the env var is a raw string (not valid Fernet key), it's hashed to derive one.
    """

    def __init__(self, master_key: str):
        self._fernet = self._build_fernet(master_key)

    @property
    def backend_name(self) -> str:
        return "local_key"

    @staticmethod
    def _build_fernet(key_str: str) -> Any:
        from cryptography.fernet import Fernet

        # Try using as-is (valid Fernet key = 32 bytes base64url)
        try:
            return Fernet(key_str.encode() if isinstance(key_str, str) else key_str)
        except Exception:
            pass
        # Derive a Fernet key from arbitrary string via SHA-256
        import hashlib

        derived = hashlib.sha256(key_str.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(derived)
        return Fernet(fernet_key)

    @staticmethod
    def generate_key() -> str:
        """Generate a new random Fernet key (for initial setup)."""
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode()

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self._fernet.decrypt(ciphertext)


class PlaintextBackend(EncryptionBackend):
    """No-op backend for local development. Stores credentials unencrypted."""

    @property
    def backend_name(self) -> str:
        return "plaintext"

    def encrypt(self, plaintext: bytes) -> bytes:
        return plaintext

    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext


class CredentialStore:
    """Manages encryption/decryption of credential dicts stored in DB."""

    def __init__(self, backend: EncryptionBackend):
        self._backend = backend

    @property
    def backend_name(self) -> str:
        return self._backend.backend_name

    def encrypt_credentials(self, creds: dict) -> dict:
        """Encrypt a credentials dict for DB storage.

        Args:
            creds: Plaintext credentials dict (e.g., {"access_key_id": "...", ...})

        Returns:
            Dict with {"_encrypted": "<base64-encoded-ciphertext>"} for DB storage.
            Fields that are NOT sensitive (role_arn, external_id, profile_name) are
            stored in plaintext alongside the encrypted blob.
        """
        if not creds:
            return creds

        # Separate sensitive vs non-sensitive fields
        sensitive = {}
        non_sensitive = {}
        for k, v in creds.items():
            if is_sensitive_key(k):
                sensitive[k] = v
            else:
                non_sensitive[k] = v

        if not sensitive:
            return creds  # Nothing to encrypt

        # Encrypt sensitive fields
        plaintext_bytes = json.dumps(sensitive).encode("utf-8")
        ciphertext = self._backend.encrypt(plaintext_bytes)
        encoded = base64.b64encode(ciphertext).decode("ascii")

        result = dict(non_sensitive)
        result[_ENCRYPTED_KEY] = encoded
        return result

    def decrypt_credentials(self, stored: dict) -> dict:
        """Decrypt credentials from DB storage.

        Args:
            stored: Dict from DB, possibly containing {"_encrypted": "..."}.

        Returns:
            Full plaintext credentials dict.
        """
        if not stored or _ENCRYPTED_KEY not in stored:
            return stored or {}

        # Decrypt the encrypted portion
        encoded = stored[_ENCRYPTED_KEY]
        ciphertext = base64.b64decode(encoded)
        plaintext_bytes = self._backend.decrypt(ciphertext)
        sensitive = json.loads(plaintext_bytes)

        # Merge non-encrypted fields with decrypted fields
        result = {k: v for k, v in stored.items() if k != _ENCRYPTED_KEY}
        result.update(sensitive)
        return result

    def merge_update(self, stored: dict | None, incoming: dict | None, *, clear_secrets: bool = False,
                     switched_from: str | None = None) -> dict:
        """Apply an edit to credentials as stored in the DB (rules: merge_credentials); returns them encrypted."""
        current = self.decrypt_credentials(stored or {})
        merged = merge_credentials(current, incoming, clear_secrets=clear_secrets, switched_from=switched_from)
        secrets = {k: v for k, v in merged.items() if is_sensitive_key(k)}
        if (secrets and _ENCRYPTED_KEY in (stored or {})
                and secrets == {k: v for k, v in current.items() if is_sensitive_key(k)}):
            # Every secret as it was: keep the stored ciphertext. The credential fingerprint (session cache key,
            # private kubeconfig path) hashes the stored form, and a new ciphertext would move it on a region edit.
            plain = {k: v for k, v in merged.items() if not is_sensitive_key(k)}
            return {**plain, _ENCRYPTED_KEY: stored[_ENCRYPTED_KEY]}
        return self.encrypt_credentials(merged)

    def is_encrypted(self, stored: dict) -> bool:
        """Check if credentials dict contains encrypted data."""
        return bool(stored and _ENCRYPTED_KEY in stored)


# ── Singleton ─────────────────────────────────────────────────────────

_store_instance: CredentialStore | None = None
_store_lock = threading.Lock()


def get_credential_store() -> CredentialStore:
    """Get or create the singleton CredentialStore.

    Backend auto-detection priority:
    1. AIOPS_KMS_KEY_ID env → KMS backend
    2. AIOPS_MASTER_KEY env → LocalKey backend
    3. AIOPS_CREDENTIAL_BACKEND=plaintext → Plaintext (dev only)
    4. Default → Plaintext with warning
    """
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    with _store_lock:
        if _store_instance is not None:
            return _store_instance

        backend = _detect_backend()
        _store_instance = CredentialStore(backend)
        logger.info("CredentialStore initialized with backend: %s", backend.backend_name)
        return _store_instance


def _detect_backend() -> EncryptionBackend:
    """Auto-detect the best available encryption backend."""
    kms_key_id = os.environ.get("AIOPS_KMS_KEY_ID")
    if kms_key_id:
        region = os.environ.get("AIOPS_BEDROCK_REGION", "us-east-1")
        logger.info("Using KMS encryption backend (key: %s...)", kms_key_id[:20])
        return KMSBackend(kms_key_id, region)

    master_key = os.environ.get("AIOPS_MASTER_KEY")
    if master_key:
        logger.info("Using local key encryption backend")
        return LocalKeyBackend(master_key)

    explicit = os.environ.get("AIOPS_CREDENTIAL_BACKEND", "")
    if explicit == "plaintext":
        logger.warning("Using PLAINTEXT credential backend — NOT for production!")
        return PlaintextBackend()

    # Default: plaintext with warning (backwards compatible)
    logger.warning(
        "No encryption backend configured. Credentials stored in plaintext. "
        "Set AIOPS_MASTER_KEY or AIOPS_KMS_KEY_ID for production use."
    )
    return PlaintextBackend()


def reset_credential_store() -> None:
    """Reset the singleton (for testing)."""
    global _store_instance
    with _store_lock:
        _store_instance = None
