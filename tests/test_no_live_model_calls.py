"""The unit-test guard against live model calls (tests/conftest.py::_block_live_bedrock_runtime)."""

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import Stubber

_MESSAGES = [{"role": "user", "content": [{"text": "hi"}]}]
_FAKE_CREDS = {"aws_access_key_id": "testing", "aws_secret_access_key": "testing"}


@pytest.fixture
def runtime_client(request):
    if request.config.getoption("--run-integration"):
        pytest.skip("the live-call guard is off under --run-integration")
    return boto3.client("bedrock-runtime", region_name="us-east-1", **_FAKE_CREDS)


def test_live_bedrock_runtime_request_is_refused(runtime_client):
    with pytest.raises(RuntimeError, match="blocked in unit tests"):
        runtime_client.converse(modelId="global.anthropic.claude-haiku-4-5-20251001-v1:0", messages=_MESSAGES)


def test_stubbed_bedrock_runtime_client_is_untouched(runtime_client):
    with Stubber(runtime_client) as stub:
        stub.add_client_error("converse", service_error_code="ValidationException", service_message="stubbed")
        with pytest.raises(ClientError, match="stubbed"):
            runtime_client.converse(modelId="m", messages=_MESSAGES)


def test_other_services_still_reach_the_http_layer():
    """Only bedrock-runtime is guarded: an STS request goes on to the (unreachable) endpoint."""
    sts = boto3.client(
        "sts", region_name="us-east-1", endpoint_url="http://127.0.0.1:9", **_FAKE_CREDS,
        config=Config(retries={"max_attempts": 1, "mode": "standard"}, connect_timeout=1, read_timeout=1),
    )
    with pytest.raises(EndpointConnectionError):
        sts.get_caller_identity()
