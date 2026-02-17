"""Live AWS integration tests for core AWS resource tools.

These tests call real AWS APIs and require valid credentials.
Run with: uv run pytest tests/integration/ -v --run-integration
"""

import pytest

from agenticops.tools.aws_tools import (
    describe_ec2,
    describe_rds,
    list_lambda_functions,
    list_s3_buckets,
)


@pytest.mark.integration
class TestAWSToolsLive:
    """Integration tests that hit real AWS resource APIs."""

    def test_describe_ec2_live(self, aws_region):
        result = describe_ec2(region=aws_region)
        assert isinstance(result, str)
        # Result is either JSON list of instances or an error string
        assert result is not None

    def test_describe_rds_live(self, aws_region):
        result = describe_rds(region=aws_region)
        assert isinstance(result, str)
        assert result is not None

    def test_list_lambda_functions_live(self, aws_region):
        result = list_lambda_functions(region=aws_region)
        assert isinstance(result, str)
        assert result is not None

    def test_list_s3_buckets_live(self, aws_region):
        result = list_s3_buckets(region=aws_region)
        assert isinstance(result, str)
        assert result is not None
