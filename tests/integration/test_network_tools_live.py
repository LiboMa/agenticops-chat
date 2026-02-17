"""Live AWS integration tests for VPC/Networking tools.

These tests call real AWS APIs and require valid credentials.
Run with: uv run pytest tests/integration/ -v --run-integration
"""

import pytest

from agenticops.tools.network_tools import (
    describe_vpcs,
    describe_subnets,
    describe_security_groups,
    describe_route_tables,
    describe_nat_gateways,
    describe_transit_gateways,
    describe_load_balancers,
)


@pytest.mark.integration
class TestNetworkToolsLive:
    """Integration tests that hit real AWS VPC/Networking APIs."""

    def test_describe_vpcs_live(self, aws_region):
        result = describe_vpcs(region=aws_region)
        assert isinstance(result, str)
        # Every account has at least the default VPC, or the result is valid JSON
        assert "VpcId" in result or result == "[]"

    def test_describe_subnets_live(self, aws_region):
        result = describe_subnets(region=aws_region)
        assert isinstance(result, str)
        assert "SubnetId" in result or result == "[]"

    def test_describe_security_groups_live(self, aws_region):
        result = describe_security_groups(region=aws_region)
        assert isinstance(result, str)
        # Every VPC has at least a default security group
        assert "GroupId" in result

    def test_describe_route_tables_live(self, aws_region):
        result = describe_route_tables(region=aws_region)
        assert isinstance(result, str)
        assert "RouteTableId" in result or result == "[]"

    def test_describe_nat_gateways_live(self, aws_region):
        result = describe_nat_gateways(region=aws_region)
        assert isinstance(result, str)
        # NAT Gateways may not exist — just verify we get a string back
        assert result is not None

    def test_describe_transit_gateways_live(self, aws_region):
        result = describe_transit_gateways(region=aws_region)
        assert isinstance(result, str)
        assert result is not None

    def test_describe_load_balancers_live(self, aws_region):
        result = describe_load_balancers(region=aws_region)
        assert isinstance(result, str)
        assert result is not None
