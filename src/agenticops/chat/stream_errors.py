"""Stream error classification (MVP-2.7.0 S5): the user sees what kind of failure it was, never the raw exception
(that is only logged). The UI shows its own localized text per code."""
THROTTLED = {"ThrottlingException", "TooManyRequestsException"}
UNAVAILABLE = {"ServiceUnavailableException", "ModelNotReadyException", "ModelTimeoutException", "AccessDeniedException",
               "ResourceNotFoundException", "ModelErrorException"}
_OVERFLOW_HINTS = ("too long", "context window", "contextwindowoverflow", "maximum context", "too many tokens")

MESSAGES = {"throttled": "The model is rate-limited; try again shortly.",
            "model_unavailable": "The model is unavailable right now.",
            "context_too_long": "The conversation is too long for the model; start a new chat.",
            "internal": "The reply failed."}


def _aws_code(exc) -> str | None:
    resp = getattr(exc, "response", None)
    return resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None


def classify(exc: BaseException) -> str:
    code = _aws_code(exc)
    if code in THROTTLED:
        return "throttled"
    if code in UNAVAILABLE:
        return "model_unavailable"
    text = f"{type(exc).__name__} {exc}".lower()
    if any(h in text for h in _OVERFLOW_HINTS):
        return "context_too_long"
    if code is None and "throttl" in text:
        return "throttled"
    return "internal"


def tool_outcome(status) -> str:
    """A tool result's status → ok | error | unknown (a tool's name alone never implies success)."""
    return {"success": "ok", "error": "error"}.get(status or "", "unknown")
