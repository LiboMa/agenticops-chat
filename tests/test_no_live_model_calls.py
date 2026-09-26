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
