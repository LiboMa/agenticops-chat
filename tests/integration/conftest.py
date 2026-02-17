"""Integration test fixtures: AWS session injection for live tests."""

import os

import boto3
import pytest

import agenticops.tools.aws_tools as aws_tools_module


@pytest.fixture(scope="session")
def aws_region():
    """Return the AWS region to use for integration tests."""
    return os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(scope="session", autouse=True)
def aws_identity(aws_region):
    """Verify AWS credentials are valid before running any integration tests.

    Calls sts:GetCallerIdentity. Skips the entire test session if no
    credentials are available.
    """
    try:
        sts = boto3.client("sts", region_name=aws_region)
        identity = sts.get_caller_identity()
        print(
            f"\nAWS Identity: {identity['Arn']} "
            f"(Account: {identity['Account']}, Region: {aws_region})"
        )
        return identity
    except Exception as e:
        pytest.skip(f"No valid AWS credentials available: {e}")


@pytest.fixture(scope="session", autouse=True)
def inject_aws_session(aws_region, aws_identity):
    """Inject a real boto3 session into the aws_tools session cache.

    Uses the default credential chain (env vars, profile, instance role, etc.)
    and injects into ``agenticops.tools.aws_tools._session_cache`` with a key
    of ``integration:{region}`` so all tools can resolve it via
    ``_get_session(region)``.
    """
    session = boto3.Session(region_name=aws_region)
    cache_key = f"integration:{aws_region}"
    aws_tools_module._session_cache[cache_key] = session
    yield session
    # Cleanup
    aws_tools_module._session_cache.pop(cache_key, None)


@pytest.fixture(autouse=True)
def cleanup_session_cache():
    """Ensure no stale session cache entries leak between tests.

    Runs after each test function. Preserves the ``integration:*`` key
    injected by the session-scoped fixture but removes anything else.
    """
    yield
    keys_to_remove = [
        k for k in aws_tools_module._session_cache if not k.startswith("integration:")
    ]
    for k in keys_to_remove:
        del aws_tools_module._session_cache[k]
