"""Live AWS integration tests for VPC/Networking tools.

These tests call real AWS APIs and require valid credentials.
Run with: uv run pytest tests/integration/ -v --run-integration
"""

import json

import pytest

from agenticops.tools.network_tools import (
    describe_vpcs,
    describe_subnets,
    describe_security_groups,
    describe_route_tables,
    describe_nat_gateways,
    describe_transit_gateways,
    describe_load_balancers,
    analyze_vpc_topology,
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


@pytest.mark.integration
class TestAnalyzeVpcTopologyLive:
    """Integration tests for analyze_vpc_topology."""

    def _get_first_vpc_id(self, aws_region):
        """Helper to discover a VPC ID for testing."""
        result = describe_vpcs(region=aws_region)
        vpcs = json.loads(result)
        if not vpcs:
            pytest.skip("No VPCs found in region")
        return vpcs[0]["VpcId"]

    def test_analyze_vpc_topology_live(self, aws_region):
        """Discover a VPC and run full topology analysis."""
        vpc_id = self._get_first_vpc_id(aws_region)
        result = analyze_vpc_topology(region=aws_region, vpc_id=vpc_id)
        data = json.loads(result)

        assert data["vpc_id"] == vpc_id
        assert "subnets" in data
        assert "reachability_summary" in data

    def test_analyze_vpc_topology_default_vpc(self, aws_region):
        """Analyze the default VPC (if present)."""
        result = describe_vpcs(region=aws_region)
        vpcs = json.loads(result)
        default_vpcs = [v for v in vpcs if v.get("IsDefault")]
        if not default_vpcs:
            pytest.skip("No default VPC in region")

        vpc_id = default_vpcs[0]["VpcId"]
        result = analyze_vpc_topology(region=aws_region, vpc_id=vpc_id)
        data = json.loads(result)

        assert data["vpc_id"] == vpc_id
        assert "reachability_summary" in data

    def test_analyze_vpc_topology_invalid_vpc(self, aws_region):
        """Invalid VPC ID returns error."""
        result = analyze_vpc_topology(region=aws_region, vpc_id="vpc-00000000000000000")
        data = json.loads(result)
        assert "error" in data

    def test_analyze_vpc_topology_has_sg_map(self, aws_region):
        """Verify security_group_dependency_map is in the output."""
        vpc_id = self._get_first_vpc_id(aws_region)
        result = analyze_vpc_topology(region=aws_region, vpc_id=vpc_id)
        data = json.loads(result)

        assert "security_group_dependency_map" in data
        # Default SG always exists
        if data["security_group_dependency_map"]:
            first_sg = next(iter(data["security_group_dependency_map"].values()))
            assert "name" in first_sg
            assert "references" in first_sg
            assert "referenced_by" in first_sg
