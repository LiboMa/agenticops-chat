"""What the chat's work log shows for a tool step (2026-11-07): a one-line summary of its input and a short preview of
its result, both redacted for display.

The display filter is deliberately stricter than the shared scrubber ``security.redaction.redact_secrets``: that one
guards every DB column and is precision-biased (owner mandate), so it is applied first and left unchanged; this one
also masks the credential shapes it does not catch (a ``--password`` value, ``aws_secret_access_key <value>``, a Bearer
token, a URL's ``user:password@``). Masking a word too many in a preview costs a few characters of a display aid.
"""
from __future__ import annotations

import re

from agenticops.security.redaction import PLACEHOLDER, redact_secrets

SUMMARY_MAX = 160
PREVIEW_MAX = 200
PREVIEW_SCAN_MAX = 4000   # a result is cut to this BEFORE any regex runs (a tool can return megabytes)

_VALUE = r"""("[^"]*"|'[^']*'|[^\s'",;]+)"""
_KEYWORD = r"(?:secret|password|passwd|token|api_?key|private_?key)"

# --password hunter2 / --token=abc / --secret-access-key "x"
_FLAG = re.compile(
    r"(?i)(--(?:password|passwd|pwd|secret|token|api-key|apikey|access-key|secret-access-key|private-key|"
    r"client-secret|credentials?))(=|\s+)" + _VALUE)
# scheme://user:password@host
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^/\s:@]+):([^@\s/]+)@")
# Authorization: Bearer x / Authorization: Basic x / a bare "Bearer <token>"
_AUTH_HEADER = re.compile(r"(?i)(Authorization\s*[:=]\s*(?:(?:Bearer|Basic|Token)\s+)?)" + _VALUE)
_BEARER = re.compile(r"(?i)(\bBearer\s+)([A-Za-z0-9._~+/=\-]{8,})")
# token: x / AWS_SECRET_ACCESS_KEY=x — any key holding a secret word, then "=", or ":" and a space (an ARN segment
# "arn:aws:secretsmanager:region:…" is a resource reference, not a key: no space after its colons)
_KEY_ASSIGN = re.compile(r"(?i)\b([A-Za-z0-9_.\-]*" + _KEYWORD + r"[A-Za-z0-9_.\-]*)(\s*=\s*|:\s+)" + _VALUE)
# aws_secret_access_key x — a snake_case config key (has "_") holding a secret word, then whitespace
_KEY_SPACE = re.compile(
    r"(?i)\b((?=[A-Za-z0-9_.\-]*?" + _KEYWORD + r")[A-Za-z0-9.\-]*_[A-Za-z0-9_.\-]*)(\s+)" + _VALUE)


def redact_for_display(text: str) -> str:
    """``redact_secrets``, then the display-only patterns; each keeps its label and masks the value."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = redact_secrets(text)
    out = _FLAG.sub(lambda m: m.group(1) + m.group(2) + PLACEHOLDER, out)
    out = _URL_USERINFO.sub(lambda m: m.group(1) + ":" + PLACEHOLDER + "@", out)
    out = _AUTH_HEADER.sub(lambda m: m.group(1) + PLACEHOLDER, out)
    out = _BEARER.sub(lambda m: m.group(1) + PLACEHOLDER, out)
    out = _KEY_ASSIGN.sub(lambda m: m.group(1) + m.group(2) + PLACEHOLDER, out)
    out = _KEY_SPACE.sub(lambda m: m.group(1) + m.group(2) + PLACEHOLDER, out)
    return out


def _one_line(s: str) -> str:
    return " ".join(s.split())


def _cut(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


def summarize_input(tool_input) -> str:
    """One line saying what the step was asked to do: its command, its one text field, or its scalar fields."""
    if isinstance(tool_input, str):
        raw = tool_input
    elif isinstance(tool_input, dict):
        command = tool_input.get("command")
        texts = [v for v in tool_input.values() if isinstance(v, str) and v.strip()]
        if isinstance(command, str) and command.strip():
            raw = command
        elif len(texts) == 1:
            raw = texts[0]
        else:
            raw = " ".join(f"{k}={v}" for k, v in tool_input.items()
                           if isinstance(v, (str, int, float, bool)) and not (isinstance(v, str) and not v.strip()))
    else:
        return ""
    return _cut(redact_for_display(_one_line(raw)), SUMMARY_MAX)


def result_preview(text: str | None) -> str:
    """The first ~200 characters of a tool's result, on one line, redacted."""
    if not isinstance(text, str) or not text:
        return ""
    return _cut(redact_for_display(_one_line(text[:PREVIEW_SCAN_MAX])), PREVIEW_MAX)
