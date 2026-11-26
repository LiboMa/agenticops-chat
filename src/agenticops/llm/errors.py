"""What is kept of a model error (MVP-2.9.0 N35 final review).

An OpenAI / Anthropic SDK error's text is the provider's own sentence, and an authentication failure's sentence quotes
part of the key it was given («Incorrect API key provided: sk-…»). What is stored and returned — a failed chat turn's
`token_usage.error`, a failed Galaxy build's `error` — is the error's class and HTTP status for those; any other error
keeps its text as before (a Bedrock ClientError names no key; a ModelProviderUnavailable says which model and why).
"""
from __future__ import annotations

import logging
from typing import Optional

_SDKS = ("openai", "anthropic")


def is_sdk_error(exc: BaseException) -> bool:
    return (type(exc).__module__ or "").split(".")[0] in _SDKS


def safe_error_text(exc: BaseException, limit: int = 500) -> str:
    if is_sdk_error(exc):
        status = getattr(exc, "status_code", None)
        return f"{type(exc).__name__} ({status})" if status else type(exc).__name__
    return str(exc)[:limit]


def _sdk_error_in(exc: Optional[BaseException]) -> Optional[BaseException]:
    """The first SDK error of an exception and the ones it was raised from or during — a traceback prints them all."""
    seen = 0
    while exc is not None and seen < 20:
        if is_sdk_error(exc):
            return exc
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return None


class SdkErrorFilter(logging.Filter):
    """Keeps an SDK error's sentence out of a log line (MVP-2.9.0 review): a traceback holding one becomes the
    message + its class and status, and an SDK error passed as an argument is formatted the same way. Every other
    record is left as it is. Installed on the service's handlers (web/app._setup_service_logging) and the CLI's."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and any(isinstance(a, BaseException) and is_sdk_error(a) for a in record.args):
            record.args = tuple(safe_error_text(a) if isinstance(a, BaseException) and is_sdk_error(a) else a
                                for a in record.args)
        found = _sdk_error_in(record.exc_info[1]) if record.exc_info else None
        if found is not None:
            record.msg = f"{record.getMessage()} — {safe_error_text(found)}"
            record.args = None
            record.exc_info = None
            record.exc_text = None
        return True
