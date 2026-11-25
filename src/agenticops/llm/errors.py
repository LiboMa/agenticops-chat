"""What is kept of a model error (MVP-2.9.0 N35 final review).

An OpenAI / Anthropic SDK error's text is the provider's own sentence, and an authentication failure's sentence quotes
part of the key it was given («Incorrect API key provided: sk-…»). What is stored and returned — a failed chat turn's
`token_usage.error`, a failed Galaxy build's `error` — is the error's class and HTTP status for those; any other error
keeps its text as before (a Bedrock ClientError names no key; a ModelProviderUnavailable says which model and why).
"""
from __future__ import annotations

_SDKS = ("openai", "anthropic")


def is_sdk_error(exc: BaseException) -> bool:
    return (type(exc).__module__ or "").split(".")[0] in _SDKS


def safe_error_text(exc: BaseException, limit: int = 500) -> str:
    if is_sdk_error(exc):
        status = getattr(exc, "status_code", None)
        return f"{type(exc).__name__} ({status})" if status else type(exc).__name__
    return str(exc)[:limit]
