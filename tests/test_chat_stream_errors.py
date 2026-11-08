"""Stream error classification and tool outcomes (MVP-2.7.0 S5)."""
import pytest
from agenticops.chat.stream_errors import classify, rejection_detail, tool_outcome


class _ClientError(Exception):
    """botocore's ClientError shape: str() is "An error occurred (<code>) when calling …: <message>"."""
    def __init__(self, code, message=None):
        super().__init__(f"An error occurred ({code}) when calling the ConverseStream operation: {message or code}")
        self.response = {"Error": {"Code": code, "Message": message or code}}


_UNKNOWN_PARAM = "The model returned the following errors: Unknown parameter: 'reasoning_effort'."


@pytest.mark.parametrize("exc,code", [
    (_ClientError("ThrottlingException"), "throttled"),
    (_ClientError("TooManyRequestsException"), "throttled"),
    (_ClientError("ServiceUnavailableException"), "model_unavailable"),
    (_ClientError("ModelNotReadyException"), "model_unavailable"),
    (_ClientError("AccessDeniedException"), "model_unavailable"),
    (_ClientError("ValidationException"), "request_rejected"),
    # 2026-11-08: GPT-6 Astra / GPT-5.6 reject `reasoning_effort`; Bedrock says why — the user should see it
    (_ClientError("ValidationException", _UNKNOWN_PARAM), "request_rejected"),
    (_ClientError("ValidationException", "Input is too long for requested model"), "context_too_long"),
    (Exception("Input is too long for requested model"), "context_too_long"),
    (Exception("ContextWindowOverflowException"), "context_too_long"),
    (RuntimeError("boom"), "internal"),
])
def test_classify(exc, code):
    assert classify(exc) == code


def test_a_read_timeout_is_timeout():
    """The stream read nothing within the read timeout (a long silent think, 2026-11-08) — not a generic failure."""
    from urllib3.exceptions import ReadTimeoutError
    assert classify(ReadTimeoutError(None, None, "Read timed out.")) == "timeout"
    from botocore.exceptions import ReadTimeoutError as BotoReadTimeout
    assert classify(BotoReadTimeout(endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com")) == "timeout"
    assert classify(TimeoutError("The read operation timed out")) == "timeout"


def test_the_output_allowance_used_up_is_max_tokens():
    """Thinking used the whole Max tokens and no answer was written (Strands raises MaxTokensReachedException)."""
    from strands.types.exceptions import MaxTokensReachedException
    assert classify(MaxTokensReachedException("Agent has reached an unrecoverable state due to max_tokens limit")) \
        == "max_tokens"


def test_context_overflow_by_type_name():
    class ContextWindowOverflowException(Exception): ...
    assert classify(ContextWindowOverflowException("x")) == "context_too_long"


@pytest.mark.parametrize("status,out", [("success", "ok"), ("error", "error"), (None, "unknown"), ("weird", "unknown")])
def test_tool_outcome(status, out):
    assert tool_outcome(status) == out


@pytest.mark.parametrize("status,text,out", [
    ("success", "Error: this run is bound to account id=1; refusing account 'lab' (id=2)", "error"),
    ("success", "The command failed: this run is bound to account id=1; refusing", "error"),
    ("success", "Error: An error occurred (AccessDenied)", "error"),
    ("success", "3 instances found", "ok"),
    ("success", None, "ok"),
])
def test_a_refusal_returned_as_text_is_an_error(status, text, out):
    """CLI tools return failures as an "Error: …" string, which the SDK records as success (S5 review I5)."""
    assert tool_outcome(status, text) == out


# ── rejection_detail (2026-11-08) ─────────────────────────────────────

def test_the_detail_of_a_rejected_request_is_bedrocks_reason():
    assert rejection_detail(_ClientError("ValidationException", _UNKNOWN_PARAM)) == "Unknown parameter: 'reasoning_effort'."


def test_a_reason_without_the_model_prefix_is_kept_whole():
    # 2026-11-07 on the dev box: a pre-PR #36 attachment name
    msg = ("The document file name can only contain alphanumeric characters, whitespace characters, hyphens, "
           "parentheses, and square brackets.")
    assert rejection_detail(_ClientError("ValidationException", msg)) == msg


def test_the_detail_is_redacted_and_capped():
    exc = _ClientError("ValidationException",
                       "bad aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY " + "x" * 600)
    detail = rejection_detail(exc)
    assert "wJalrXUtnFEMI" not in detail and "[REDACTED" in detail
    assert len(detail) <= 300


def test_only_a_rejected_request_has_a_detail():
    assert rejection_detail(_ClientError("ThrottlingException")) is None
    assert rejection_detail(_ClientError("ValidationException", "Input is too long for requested model")) is None
    assert rejection_detail(RuntimeError("boom")) is None

