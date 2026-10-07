"""Stream error classification and tool outcomes (MVP-2.7.0 S5)."""
import pytest
from agenticops.chat.stream_errors import classify, tool_outcome


class _ClientError(Exception):
    def __init__(self, code): super().__init__(code); self.response = {"Error": {"Code": code}}


@pytest.mark.parametrize("exc,code", [
    (_ClientError("ThrottlingException"), "throttled"),
    (_ClientError("TooManyRequestsException"), "throttled"),
    (_ClientError("ServiceUnavailableException"), "model_unavailable"),
    (_ClientError("ModelNotReadyException"), "model_unavailable"),
    (_ClientError("AccessDeniedException"), "model_unavailable"),
    (_ClientError("ValidationException"), "internal"),
    (Exception("Input is too long for requested model"), "context_too_long"),
    (Exception("ContextWindowOverflowException"), "context_too_long"),
    (RuntimeError("boom"), "internal"),
])
def test_classify(exc, code):
    assert classify(exc) == code


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
