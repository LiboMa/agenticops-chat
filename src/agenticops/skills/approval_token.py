"""HMAC approval token generation and verification for T2+ operations.

Architecture: SECURE_TOOL_MIGRATION_GUIDE §3.2
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Tuple

logger = logging.getLogger(__name__)

# Secret key: from env or fallback to random (dev mode)
_SECRET_KEY: bytes = os.environ.get(
    "CLAWOPS_APPROVAL_SECRET", ""
).encode() or os.urandom(32)

# Token TTL in seconds (default 5 minutes)
TOKEN_TTL = int(os.environ.get("CLAWOPS_APPROVAL_TTL", "300"))


def generate(action: str, *, ttl: int | None = None) -> str:
    """Generate an HMAC approval token for a specific action.

    Args:
        action: Tool name or action identifier.
        ttl: Override TTL in seconds. Defaults to TOKEN_TTL.

    Returns:
        Base64-encoded token string.
    """
    expires = int(time.time()) + (ttl or TOKEN_TTL)
    payload = json.dumps({"action": action, "exp": expires}, sort_keys=True)
    sig = hmac.new(_SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    token = f"{payload}|{sig}"
    return token


def verify(token: str, expected_action: str) -> Tuple[bool, str]:
    """Verify an HMAC approval token.

    Args:
        token: Token string from generate().
        expected_action: Expected action this token authorizes.

    Returns:
        (ok, reason) tuple.
    """
    try:
        parts = token.rsplit("|", 1)
        if len(parts) != 2:
            return False, "Invalid token format"

        payload_str, provided_sig = parts
        expected_sig = hmac.new(
            _SECRET_KEY, payload_str.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(provided_sig, expected_sig):
            return False, "Invalid signature"

        payload = json.loads(payload_str)

        if payload.get("action") != expected_action:
            return False, f"Action mismatch: expected '{expected_action}', got '{payload.get('action')}'"

        if time.time() > payload.get("exp", 0):
            return False, "Token expired"

        return True, "OK"

    except Exception as e:
        return False, f"Verification error: {e}"
