"""Centralized secret redaction for anything about to be persisted or logged.

Owner mandate (non-negotiable): AWS credentials, AK/SK, session tokens,
passwords, and private keys must NEVER be written verbatim to Agent Memory,
the DB, reports, notifications, or logs. Call :func:`redact_secrets` at every
persistence / logging boundary.

Design bias — PRECISION over recall, because a blind scan corrupts legitimate
data (and this platform's whole point is accurate data):

* **AWS key IDs** (``AKIA``/``ASIA``/``AROA``/... + 16 base32 chars) have a
  unique, collision-free shape, so they are scrubbed unconditionally.
* **Secret access keys / session tokens / passwords** have no fixed shape
  (they look like ordinary base64/text), so they are scrubbed ONLY when they
  sit next to an identifying label (``aws_secret_access_key=``,
  ``"SessionToken":``, ``password:`` ...). This deliberately avoids mangling
  hashes, ARNs, resource IDs, and other high-entropy-but-harmless text.
* **12-digit AWS account IDs are intentionally NOT redacted** — they appear in
  every ARN and resource pattern and are not secret. Redacting them would
  break inventory/correlation without improving security.

The function is idempotent (re-running on already-redacted text is a no-op)
and never raises — redaction must not be able to crash a legitimate write.
"""

from __future__ import annotations

import re

PLACEHOLDER = "[REDACTED-SECRET]"

# 1) AWS access-key IDs. The 4-letter prefixes are the documented unique-id
#    types (AKIA long-term, ASIA temporary, AROA role, AIDA user, ...). 16
#    uppercase base32 chars follow. Unique enough to scrub unconditionally.
_AWS_KEY_ID = re.compile(r"\b(?:AKIA|ASIA|AROA|AIDA|AGPA|AIPA|ANPA|ANVA|ASCA)[0-9A-Z]{16}\b")

# High-signal secret names, safe to match even as a suffix of a prefixed
# identifier (``aws_``/``db_``/…). Compound names + the password family.
# Verbose-mode fragment shared by the flat-text and dict-key matchers.
_SECRET_NAME_STRONG = r"""
      secret_?access_?key
    | aws_?session_?token
    | session_?token
    | security_?token
    | secret_?key
    | access_?token
    | client_?secret
    | app_?secret
    | signing_?secret
    | corp_?secret
    | verification_?token
    | bot_?token
    | private_?key
    | api_?key
    | passwd | password | pwd
"""

# Bare words that indicate a secret ONLY at an identifier boundary — never as a
# suffix of another word. AWS overloads "token"/"secret" for NON-secrets that
# are pervasive in API responses (ClientToken, CreationToken, NextToken,
# PaginationToken, SecretId, SecretString…). The lookbehind blocks a preceding
# letter/digit so "ClientToken"/"NextToken" are preserved, while a standalone
# "token"/"secret", "db_secret", or "x-amz-security-token" still redacts.
# ``:`` is also excluded so an ARN/namespace segment ("arn:…:secret:NAME") — a
# resource REFERENCE, not a credential — is preserved (label=value uses _/-/.
# or a word boundary, never a colon delimiter).
_SECRET_NAME_BARE = r"(?<![a-z0-9:]) (?: secret | token )"

# Label = a strong name (optional prefix) OR a bare word at a boundary.
_SECRET_LABEL = (
    r"(?: [a-z0-9_.\-]{0,24} (?:" + _SECRET_NAME_STRONG + r") | " + _SECRET_NAME_BARE + r")"
)

# 2a) Labeled secret values in FLAT TEXT: a secret label, then ``:``/``=``, then
#     the value up to a delimiter.
_LABELED_SECRET = re.compile(
    r"(?ix)"
    r"("                                    # group 1: label + separator (kept)
    r"    " + _SECRET_LABEL +
    r'    "?'                               #   optional closing quote on the key
    r"    \s* [:=] \s*"                     #   separator
    r")"
    r'"?'                                   # optional opening quote on the value
    r"(?P<val>[^\s\"',;}\[\]]{6,})"         # the secret (>=6 chars); excludes []
                                            # so re-running on [REDACTED-SECRET] no-ops
)

# 2b) A dict KEY that names a secret. Used by redact_obj to mask the VALUE in
#     JSON/structured data, where the label lives in the key and the value is a
#     separate field (``{"aws_secret_access_key": "..."}``) — the flat matcher
#     above never sees them adjacent.
_SECRET_KEY_NAME = re.compile(
    r"(?ix) ^ (?: [a-z0-9_.\-]* (?:" + _SECRET_NAME_STRONG + r") | " + _SECRET_NAME_BARE + r") $"
)

# 3) PEM private-key blocks (RSA/EC/OPENSSH/generic).
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.DOTALL,
)


def redact_secrets(text):
    """Return *text* with AWS keys, labeled secrets, and private keys masked.

    Non-string input is returned unchanged. Never raises.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        out = _PEM_PRIVATE_KEY.sub(PLACEHOLDER, text)
        out = _AWS_KEY_ID.sub(PLACEHOLDER, out)
        out = _LABELED_SECRET.sub(lambda m: m.group(1) + PLACEHOLDER, out)
        return out
    except Exception:  # pragma: no cover - defensive; must never break a write
        try:
            return _AWS_KEY_ID.sub(PLACEHOLDER, text)
        except Exception:
            return text


def redact_obj(value):
    """Recursively redact secrets in nested str / dict / list / tuple values.

    Mirrors :func:`redact_secrets` for plain strings and walks JSON-shaped
    structures (dict values, list/tuple items) so JSON DB columns and metadata
    payloads are scrubbed too. Non-string scalars (int/float/bool/None) pass
    through unchanged. Returns an equal object when nothing needed masking, so
    callers can cheaply detect "no change" via ``==``.
    """
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            # A key named like a secret (e.g. "aws_secret_access_key",
            # "SessionToken", "password") means its string value IS the secret,
            # even though the flat-text matcher never sees them adjacent.
            if isinstance(k, str) and isinstance(v, str) and v and _SECRET_KEY_NAME.match(k):
                out[k] = PLACEHOLDER
            else:
                out[k] = redact_obj(v)
        return out
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_obj(v) for v in value)
    return value


def contains_secret(text) -> bool:
    """True if *text* appears to contain a secret redact_secrets would mask."""
    if not isinstance(text, str) or not text:
        return False
    try:
        return bool(
            _AWS_KEY_ID.search(text)
            or _PEM_PRIVATE_KEY.search(text)
            or _LABELED_SECRET.search(text)
        )
    except Exception:  # pragma: no cover
        return False
