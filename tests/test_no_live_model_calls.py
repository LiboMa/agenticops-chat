"""The unit-test guard against live model calls (tests/conftest.py::_block_live_bedrock_runtime)."""

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

_MESSAGES = [{"role": "user", "content": [{"text": "hi"}]}]
_FAKE_CREDS = {"aws_access_key_id": "testing", "aws_secret_access_key": "testing"}


class _Sent(Exception):
    """Raised by a before-send hook: the request got past the guard to botocore's send step, and no further."""


def _record_and_refuse(client) -> list:
    """Register a before-send hook (the layer moto answers at) that records the request's URL and raises _Sent
    instead of sending it."""
    sent = []

    def _hook(request, **_):
        sent.append(request.url)
        raise _Sent(request.url)
    client.meta.events.register("before-send", _hook)
    return sent


@pytest.fixture
def guard_on(request):
    """pytest_configure installs the guard unless --run-integration."""
    if request.config.getoption("--run-integration"):
        pytest.skip("the live-call guard is off under --run-integration")


@pytest.fixture
def runtime_client(guard_on):
    return boto3.client("bedrock-runtime", region_name="us-east-1", **_FAKE_CREDS)


def test_live_bedrock_runtime_request_is_refused(runtime_client):
    """The guard raises first: a before-send hook on bedrock-runtime is never called."""
    sent = _record_and_refuse(runtime_client)
    with pytest.raises(RuntimeError, match="blocked in unit tests"):
        runtime_client.converse(modelId="global.anthropic.claude-haiku-4-5-20251001-v1:0", messages=_MESSAGES)
    assert sent == []


def test_stubbed_bedrock_runtime_client_is_untouched(runtime_client):
    with Stubber(runtime_client) as stub:
        stub.add_client_error("converse", service_error_code="ValidationException", service_message="stubbed")
        with pytest.raises(ClientError, match="stubbed"):
            runtime_client.converse(modelId="m", messages=_MESSAGES)


def test_other_services_pass_the_guard_without_the_network(guard_on):
    """Only bedrock-runtime is guarded: an STS request reaches the send step below the guard, where the hook's
    sentinel stops it before anything is sent."""
    sts = boto3.client("sts", region_name="us-east-1", **_FAKE_CREDS)
    sent = _record_and_refuse(sts)
    with pytest.raises(_Sent):
        sts.get_caller_identity()
    assert len(sent) == 1


def test_installing_the_guard_again_keeps_the_same_guard(guard_on):
    """A second call is a no-op, never a guard wrapped around the guard."""
    from botocore.client import BaseClient
    from tests.conftest import _block_live_bedrock_runtime
    guard = BaseClient._make_request
    assert guard._aiops_live_model_guard
    _block_live_bedrock_runtime()
    assert BaseClient._make_request is guard


# ── the real-AWS send guard (tests/conftest.py::_block_real_aws_http) ──────────


# Hosts only these tests send to: a stray background send may land in the record meanwhile, and stays there.
_PROBE_HOSTS = ("sts.eu-north-1.", "aiops-send-guard-probe.")


@pytest.fixture
def aws_guard_on():
    """pytest_configure installs it unless AIOPS_TESTS_ALLOW_AWS=1. Yields the calls recorded since the test
    began that hit a probe `host`; those are taken back out of the record afterwards, so the terminal summary
    lists only the unintended ones."""
    import os
    from tests.conftest import _BLOCKED_AWS_CALLS
    if os.environ.get("AIOPS_TESTS_ALLOW_AWS") == "1":
        pytest.skip("the real-AWS send guard is off under AIOPS_TESTS_ALLOW_AWS=1")
    before = len(_BLOCKED_AWS_CALLS)
    yield lambda host: [line for line in _BLOCKED_AWS_CALLS[before:] if f"://{host}" in line]
    _BLOCKED_AWS_CALLS[before:] = [line for line in _BLOCKED_AWS_CALLS[before:]
                                   if not any(f"://{host}" in line for host in _PROBE_HOSTS)]


def test_a_real_aws_send_is_refused_and_recorded(aws_guard_on):
    sts = boto3.client("sts", region_name="eu-north-1", **_FAKE_CREDS)
    with pytest.raises(RuntimeError, match=r"real AWS call blocked in tests: POST https://sts\.eu-north-1\."):
        sts.get_caller_identity()
    [line] = aws_guard_on("sts.eu-north-1.")
    assert "test_a_real_aws_send_is_refused_and_recorded" in line and "thread=MainThread" in line


def test_a_send_from_a_background_thread_is_refused_and_recorded(aws_guard_on):
    """The fire-and-forget notifier / upload threads swallow the error; the record still has the call."""
    import threading
    s3 = boto3.client("s3", region_name="us-east-1", **_FAKE_CREDS)
    errors = []

    def put():
        try:
            s3.put_object(Bucket="aiops-send-guard-probe", Key="k", Body=b"x")
        except RuntimeError as exc:
            errors.append(exc)
    t = threading.Thread(target=put, name="bg-upload")
    t.start()
    t.join()
    [line] = aws_guard_on("aiops-send-guard-probe.")
    assert len(errors) == 1 and line.startswith("real AWS call blocked in tests: PUT ") and "thread=bg-upload" in line


def test_a_before_send_answer_never_reaches_the_send_guard(aws_guard_on):
    """moto and Stubber answer above URLLib3Session.send: the guard never sees them."""
    sts = boto3.client("sts", region_name="eu-north-1", **_FAKE_CREDS)
    with Stubber(sts) as stub:
        stub.add_response("get_caller_identity", {"Account": "111111111111", "UserId": "AIDAEXAMPLE",
                                                  "Arn": "arn:aws:iam::111111111111:user/u"})
        assert sts.get_caller_identity()["Account"] == "111111111111"
    sent = _record_and_refuse(sts)
    with pytest.raises(_Sent):
        sts.get_caller_identity()
    assert len(sent) == 1 and aws_guard_on("sts.eu-north-1.") == []


def test_installing_the_send_guard_again_keeps_the_same_guard(aws_guard_on):
    from botocore.httpsession import URLLib3Session
    from tests.conftest import _block_real_aws_http
    guard = URLLib3Session.send
    assert guard._aiops_aws_guard
    _block_real_aws_http()
    assert URLLib3Session.send is guard
