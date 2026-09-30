"""Shared-secret checks for machine intake (MVP-2.6.1 spec §3.B.5 alert webhooks, §3.D change intake).

The signature is `sha256=` + hex HMAC-SHA256(secret, timestamp + "." + raw body), sent as X-AIOps-Signature beside
X-AIOps-Timestamp (epoch seconds). Every comparison is constant-time.
"""
import hashlib
import hmac
import time
from typing import Optional


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """The X-AIOps-Signature value a sender computes for `body` at `timestamp`."""
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify_hmac_signature(secret: str, timestamp: str, signature: str, body: bytes, *,
                          window_seconds: int, now: Optional[float] = None) -> bool:
    """True only for a signature by `secret` over this exact timestamp + body, with the timestamp no more than
    `window_seconds` away from `now` in either direction. An unset secret never verifies."""
    if not (secret and timestamp and signature):
        return False
    try:  # a timestamp too big for the clock's float overflows: a refusal, never a 500
        if abs((time.time() if now is None else now) - int(timestamp)) > window_seconds:
            return False
    except (ValueError, OverflowError):
        return False
    return hmac.compare_digest(sign(secret, timestamp, body).encode(), signature.strip().encode())


def token_matches(secret: str, candidate: str) -> bool:
    """`candidate` is the shared token. An unset secret never matches, not even an empty candidate."""
    return bool(secret and candidate) and hmac.compare_digest(secret.encode(), candidate.encode())
