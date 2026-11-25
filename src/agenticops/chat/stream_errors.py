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
            "request_rejected": "The model rejected this request.",
            "internal": "The reply failed."}
# 2026-11-08: Bedrock rejecting our request (GPT-6 Astra: "Unknown parameter: 'reasoning_effort'"; 11-07: a document
# name) is its own kind, and the chat shows Bedrock's reason — before, it read only "The reply failed.".
_REJECTED = {"ValidationException"}
_MODEL_PREFIX = "The model returned the following errors: "
_DETAIL_MAX = 300
# 2026-11-08: a read timeout on the model stream (a long think sends no bytes unless its summary is asked for) and the
# output allowance used up by thinking are their own kinds — each tells the user what to change.
_TIMEOUT_TYPES = {"ReadTimeoutError", "ReadTimeout", "TimeoutError"}
# MVP-2.9.0 N35: the OpenAI and Anthropic SDKs (another provider's model) raise their own errors — by class, read
# through the class tree (APITimeoutError is an APIConnectionError). Strands itself turns a rate limit into
# ModelThrottledException and a context overflow into ContextWindowOverflowException, which the checks below know.
_SDKS = ("openai", "anthropic")
_SDK_TIMEOUT = {"APITimeoutError", "DeadlineExceededError"}
_SDK_THROTTLED = {"RateLimitError"}
_SDK_UNAVAILABLE = {"AuthenticationError", "PermissionDeniedError", "NotFoundError", "APIConnectionError",
                    "InternalServerError", "ServiceUnavailableError", "OverloadedError"}
_SDK_REJECTED = {"BadRequestError"}


def _sdk_classes(exc) -> set[str]:
    """The class names of an OpenAI / Anthropic SDK error and its bases; empty for anything else."""
    if (type(exc).__module__ or "").split(".")[0] not in _SDKS:
        return set()
    return {c.__name__ for c in type(exc).__mro__}


def _unavailable(exc) -> bool:
    from agenticops.llm.factory import ModelProviderUnavailable
    return isinstance(exc, ModelProviderUnavailable)


def _aws_code(exc) -> str | None:
    resp = getattr(exc, "response", None)
    return resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None


def classify(exc: BaseException) -> str:
    code = _aws_code(exc)
    if code in THROTTLED:
        return "throttled"
    if code in UNAVAILABLE or _unavailable(exc):
        return "model_unavailable"
    sdk = _sdk_classes(exc)
    if sdk & _SDK_TIMEOUT:
        return "timeout"
    if sdk & _SDK_THROTTLED:
        return "throttled"
    if sdk & _SDK_UNAVAILABLE:
        return "model_unavailable"
    name = type(exc).__name__
    if name == "MaxTokensReachedException":
        return "max_tokens"
    if name in _TIMEOUT_TYPES or "read timed out" in str(exc).lower():
        return "timeout"
    text = f"{name} {exc}".lower()
    if any(h in text for h in _OVERFLOW_HINTS):
        return "context_too_long"
    if code in _REJECTED or sdk & _SDK_REJECTED:
        return "request_rejected"
    if code is None and "throttl" in text:
        return "throttled"
    return "internal"


def _sdk_message(exc) -> str:
    """An SDK error's own reason: the `error.message` of the body the provider sent, else the error's message."""
    body = getattr(exc, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else None
    message = err.get("message") if isinstance(err, dict) else None
    return message if isinstance(message, str) else str(getattr(exc, "message", "") or "")


def rejection_detail(exc: BaseException) -> str | None:
    """The model's own reason for a rejected request — Bedrock's validation message, or the provider's for its
    `BadRequestError` (never a stack or the exception's repr) — and, for a conversation whose model cannot be built
    (MVP-2.9.0 N35), which model and why. Secrets redacted, at most _DETAIL_MAX characters. None for any other
    failure (an authentication failure's text can quote the key it was given)."""
    if _unavailable(exc):
        message = f"the model «{exc.ref}» of this conversation is not available: {exc.detail} — choose another model"
    elif classify(exc) != "request_rejected":
        return None
    elif _sdk_classes(exc):
        message = _sdk_message(exc)
    else:
        resp = getattr(exc, "response", None)
        message = (resp.get("Error", {}).get("Message") if isinstance(resp, dict) else None) or ""
    message = message.strip()
    if message.startswith(_MODEL_PREFIX):
        message = message[len(_MODEL_PREFIX):].strip()
    if not message:
        return None
    from agenticops.security.redaction import redact_secrets
    message = redact_secrets(message)
    return message if len(message) <= _DETAIL_MAX else message[:_DETAIL_MAX - 1] + "…"


_REFUSAL = "this run is bound to account"   # credentials/resolver + providers/base AccountResolutionError text


def tool_outcome(status, text: str | None = None) -> str:
    """A tool result's status → ok | error | unknown (a tool's name alone never implies success). CLI tools return a
    failure as an "Error: …" string, which the SDK records as success — that, and an account-binding refusal
    anywhere in the result, is an error (S5 review)."""
    outcome = {"success": "ok", "error": "error"}.get(status or "", "unknown")
    if outcome == "ok" and text and (text.lstrip().startswith("Error:") or _REFUSAL in text):
        return "error"
    return outcome
