"""Credential encryption for cloud account secrets.

Uses Fernet symmetric encryption. Key source priority:
1. ENV: CLAWOPS_CREDENTIAL_KEY (base64-encoded Fernet key)
2. File: ~/.agenticops/credential.key (auto-generated if missing)
3. Auto-generate: Fernet.generate_key() → write to file, chmod 600
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_KEY_ENV_VAR = "CLAWOPS_CREDENTIAL_KEY"
_KEY_FILE_PATH = Path.home() / ".agenticops" / "credential.key"

# Singleton
_store: CredentialStore | None = None


class CredentialStore:
    """Encrypt/decrypt credential dicts using Fernet."""

    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    def encrypt(self, creds: dict) -> str:
        """Encrypt a credentials dict to a base64 token string."""
        plaintext = json.dumps(creds, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(plaintext).decode("ascii")

    def decrypt(self, token: str) -> dict:
        """Decrypt a token string back to a credentials dict."""
        plaintext = self._fernet.decrypt(token.encode("ascii"))
        return json.loads(plaintext)


def _resolve_key() -> bytes:
    """Resolve encryption key from env var, file, or auto-generate."""
    # Priority 1: Environment variable
    env_key = os.environ.get(_KEY_ENV_VAR)
    if env_key:
        logger.debug("CredentialStore: using key from %s", _KEY_ENV_VAR)
        return env_key.encode("ascii")

    # Priority 2: Key file
    if _KEY_FILE_PATH.exists():
        logger.debug("CredentialStore: using key from %s", _KEY_FILE_PATH)
        return _KEY_FILE_PATH.read_bytes().strip()

    # Priority 3: Auto-generate
    logger.info("CredentialStore: generating new key at %s", _KEY_FILE_PATH)
    key = Fernet.generate_key()
    _KEY_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE_PATH.write_bytes(key)
    os.chmod(_KEY_FILE_PATH, 0o600)
    return key


def get_credential_store() -> CredentialStore:
    """Get or create the singleton CredentialStore."""
    global _store
    if _store is None:
        key = _resolve_key()
        _store = CredentialStore(key)
    return _store


def reset_credential_store():
    """Reset singleton (for testing)."""
    global _store
    _store = None
