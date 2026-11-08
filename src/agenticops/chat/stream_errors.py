"""Stream error classification (MVP-2.7.0 S5): the user sees what kind of failure it was, never the raw exception
(that is only logged). The UI shows its own localized text per code."""
THROTTLED = {"ThrottlingException", "TooManyRequestsException"}
UNAVAILABLE = {"ServiceUnavailableException", "ModelNotReadyException", "ModelTimeoutException", "AccessDeniedException",
               "ResourceNotFoundException", "ModelErrorException"}
_OVERFLOW_HINTS = ("too long", "context window", "contextwindowoverflow", "maximum context", "too many tokens")

MESSAGES = {"throttled": "The model is rate-limited; try again shortly.",
            "model_unavailable": "The model is unavailable right now.",
            "context_too_long": "The conversation is too long for the model; start a new chat.",
            "timeout": "The model sent nothing within the wait limit; lower the effort or raise the limit in Settings.",
            "max_tokens": "The model used its whole output allowance (Max tokens) and wrote no answer; raise Max tokens "
                          "in Settings or lower the effort.",
            "internal": "The reply failed."}
# 2026-11-08: a read timeout on the model stream (a long think sends no bytes unless its summary is asked for) and the
# output allowance used up by thinking are their own kinds — each tells the user what to change.
_TIMEOUT_TYPES = {"ReadTimeoutError", "ReadTimeout", "TimeoutError"}


def _aws_code(exc) -> str | None:
    resp = getattr(exc, "response", None)
    return resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None


def classify(exc: BaseException) -> str:
    code = _aws_code(exc)
    if code in THROTTLED:
        return "throttled"
    if code in UNAVAILABLE:
        return "model_unavailable"
    name = type(exc).__name__
    if name == "MaxTokensReachedException":
        return "max_tokens"
    if name in _TIMEOUT_TYPES or "read timed out" in str(exc).lower():
        return "timeout"
    text = f"{name} {exc}".lower()
    if any(h in text for h in _OVERFLOW_HINTS):
        return "context_too_long"
    if code is None and "throttl" in text:
        return "throttled"
    return "internal"


_REFUSAL = "this run is bound to account"   # credentials/resolver + providers/base AccountResolutionError text


def tool_outcome(status, text: str | None = None) -> str:
    """A tool result's status → ok | error | unknown (a tool's name alone never implies success). CLI tools return a
    failure as an "Error: …" string, which the SDK records as success — that, and an account-binding refusal
    anywhere in the result, is an error (S5 review)."""
    outcome = {"success": "ok", "error": "error"}.get(status or "", "unknown")
    if outcome == "ok" and text and (text.lstrip().startswith("Error:") or _REFUSAL in text):
        return "error"
    return outcome
