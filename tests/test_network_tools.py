"""Tests for VPC/Networking tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agenticops.tools.network_tools import (
    _extract_name_from_tags,
    _format_sg_rules,
    _format_routes,
    _classify_subnet_type,
    _build_sg_dependency_map,
    _detect_blackhole_routes,
)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestExtractNameFromTags:
    """Tests for _extract_name_from_tags helper."""

    def test_extract_name(self):
        tags = [{"Key": "Environment", "Value": "prod"}, {"Key": "Name", "Value": "my-vpc"}]
        assert _extract_name_from_tags(tags) == "my-vpc"

    def test_no_name_tag(self):
        tags = [{"Key": "Environment", "Value": "prod"}]
        assert _extract_name_from_tags(tags) is None

    def test_empty_tags(self):
        assert _extract_name_from_tags([]) is None

    def test_none_tags(self):
        assert _extract_name_from_tags(None) is None


class TestFormatSGRules:
    """Tests for _format_sg_rules helper."""

    def test_basic_rule(self):
        rules = [{
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTPS"}],
            "Ipv6Ranges": [],
            "PrefixListIds": [],
            "UserIdGroupPairs": [],
        }]
        result = _format_sg_rules(rules)
        assert len(result) == 1
        assert result[0]["protocol"] == "tcp"
        assert result[0]["ports"] == "443"
        assert "0.0.0.0/0 (HTTPS)" in result[0]["sources"]

    def test_port_range(self):
        rules = [{
            "IpProtocol": "tcp",
            "FromPort": 1024,
            "ToPort": 65535,
            "IpRanges": [{"CidrIp": "10.0.0.0/8"}],
            "Ipv6Ranges": [],
            "PrefixListIds": [],
            "UserIdGroupPairs": [],
        }]
        result = _format_sg_rules(rules)
        assert result[0]["ports"] == "1024-65535"

    def test_sg_source(self):
        rules = [{
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "IpRanges": [],
            "Ipv6Ranges": [],
            "PrefixListIds": [],
            "UserIdGroupPairs": [{"GroupId": "sg-12345", "Description": "ALB"}],
        }]
        result = _format_sg_rules(rules)
        assert "sg:sg-12345 (ALB)" in result[0]["sources"]

    def test_all_traffic(self):
        rules = [{
            "IpProtocol": "-1",
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            "Ipv6Ranges": [],
            "PrefixListIds": [],
            "UserIdGroupPairs": [],
        }]
        result = _format_sg_rules(rules)
        assert result[0]["protocol"] == "-1"
        assert result[0]["ports"] == "all"

    def test_empty_rules(self):
        assert _format_sg_rules([]) == []


class TestFormatRoutes:
    """Tests for _format_routes helper."""

    def test_local_route(self):
        routes = [{
            "DestinationCidrBlock": "10.0.0.0/16",
            "GatewayId": "local",
            "State": "active",
            "Origin": "CreateRouteTable",
        }]
        result = _format_routes(routes)
        assert len(result) == 1
        assert result[0]["destination"] == "10.0.0.0/16"
        assert result[0]["target"] == "local"
        assert result[0]["state"] == "active"

    def test_nat_gateway_route(self):
        routes = [{
            "DestinationCidrBlock": "0.0.0.0/0",
            "NatGatewayId": "nat-12345",
            "State": "active",
            "Origin": "CreateRoute",
        }]
        result = _format_routes(routes)
        assert result[0]["target"] == "nat-12345"

    def test_blackhole_route(self):
        routes = [{
            "DestinationCidrBlock": "172.16.0.0/12",
            "TransitGatewayId": "tgw-deleted",
            "State": "blackhole",
            "Origin": "CreateRoute",
        }]
        result = _format_routes(routes)
        assert result[0]["state"] == "blackhole"
        assert result[0]["target"] == "tgw-deleted"

    def test_empty_routes(self):
        assert _format_routes([]) == []


# ---------------------------------------------------------------------------
# Tool function tests (mocked boto3)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ec2_client():
    """Mock EC2 client with paginator support."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_session(mock_ec2_client):
    """Patch _get_client to return mocked client."""
    with patch("agenticops.tools.network_tools._get_client") as mock_get:
        mock_get.return_value = mock_ec2_client
        yield mock_ec2_client


class TestDescribeVpcs:
    """Tests for describe_vpcs tool."""

    def test_basic_vpcs(self, mock_session):
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "Vpcs": [{
                "VpcId": "vpc-12345",
                "CidrBlock": "10.0.0.0/16",
                "State": "available",
                "IsDefault": False,
                "DhcpOptionsId": "dopt-12345",
                "InstanceTenancy": "default",
                "CidrBlockAssociationSet": [{"CidrBlock": "10.0.0.0/16"}],
                "Tags": [{"Key": "Name", "Value": "prod-vpc"}],
            }],
        }]
        mock_session.get_paginator.return_value = paginator

        from agenticops.tools.network_tools import describe_vpcs
        result = describe_vpcs(region="us-east-1")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["VpcId"] == "vpc-12345"
        assert data[0]["Name"] == "prod-vpc"
        assert data[0]["CidrBlock"] == "10.0.0.0/16"

    def test_empty_vpcs(self, mock_session):
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Vpcs": []}]
        mock_session.get_paginator.return_value = paginator

        from agenticops.tools.network_tools import describe_vpcs
        result = describe_vpcs(region="us-east-1")
        data = json.loads(result)
        assert data == []


class TestDescribeSubnets:
    """Tests for describe_subnets tool."""

    def test_subnets_with_vpc_filter(self, mock_session):
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "Subnets": [{
                "SubnetId": "subnet-abc",
                "VpcId": "vpc-12345",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.0.1.0/24",
                "AvailableIpAddressCount": 250,
                "MapPublicIpOnLaunch": False,
                "State": "available",
                "DefaultForAz": False,
                "Tags": [{"Key": "Name", "Value": "private-1a"}],
            }],
        }]
        mock_session.get_paginator.return_value = paginator

        from agenticops.tools.network_tools import describe_subnets
        result = describe_subnets(region="us-east-1", vpc_id="vpc-12345")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["SubnetId"] == "subnet-abc"
        assert data[0]["AvailableIpAddressCount"] == 250
        # Verify VPC filter was applied
        mock_session.get_paginator.assert_called_with("describe_subnets")


class TestDescribeSecurityGroups:
    """Tests for describe_security_groups tool."""

    def test_sg_with_rules(self, mock_session):
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "SecurityGroups": [{
                "GroupId": "sg-12345",
                "GroupName": "web-sg",
                "VpcId": "vpc-12345",
                "Description": "Web server SG",
                "IpPermissions": [{
                    "IpProtocol": "tcp",
                    "FromPort": 80,
                    "ToPort": 80,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    "Ipv6Ranges": [],
                    "PrefixListIds": [],
                    "UserIdGroupPairs": [],
                }],
                "IpPermissionsEgress": [{
                    "IpProtocol": "-1",
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    "Ipv6Ranges": [],
                    "PrefixListIds": [],
                    "UserIdGroupPairs": [],
                }],
            }],
        }]
        mock_session.get_paginator.return_value = paginator

        from agenticops.tools.network_tools import describe_security_groups
        result = describe_security_groups(region="us-east-1")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["GroupId"] == "sg-12345"
        assert data[0]["InboundRuleCount"] == 1
        assert data[0]["OutboundRuleCount"] == 1
        assert data[0]["InboundRules"][0]["ports"] == "80"


class TestDescribeRouteTables:
    """Tests for describe_route_tables tool."""

    def test_route_table_with_blackhole(self, mock_session):
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "RouteTables": [{
                "RouteTableId": "rtb-12345",
                "VpcId": "vpc-12345",
                "Routes": [
                    {
                        "DestinationCidrBlock": "10.0.0.0/16",
                        "GatewayId": "local",
                        "State": "active",
                        "Origin": "CreateRouteTable",
                    },
                    {
                        "DestinationCidrBlock": "0.0.0.0/0",
                        "NatGatewayId": "nat-deleted",
                        "State": "blackhole",
                        "Origin": "CreateRoute",
                    },
                ],
                "Associations": [{
                    "RouteTableAssociationId": "rtbassoc-12345",
                    "SubnetId": "subnet-abc",
                    "Main": False,
                }],
                "Tags": [{"Key": "Name", "Value": "private-rt"}],
            }],
        }]
        mock_session.get_paginator.return_value = paginator

        from agenticops.tools.network_tools import describe_route_tables
        result = describe_route_tables(region="us-east-1")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["Name"] == "private-rt"
        routes = data[0]["Routes"]
        assert len(routes) == 2
        blackhole = [r for r in routes if r["state"] == "blackhole"]
        assert len(blackhole) == 1
        assert blackhole[0]["target"] == "nat-deleted"


class TestDescribeNatGateways:
    """Tests for describe_nat_gateways tool."""

    def test_nat_gateway(self, mock_session):
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "NatGateways": [{
                "NatGatewayId": "nat-12345",
                "SubnetId": "subnet-pub1",
                "VpcId": "vpc-12345",
                "State": "available",
                "ConnectivityType": "public",
                "NatGatewayAddresses": [{
                    "AllocationId": "eipalloc-12345",
                    "PublicIp": "54.1.2.3",
                    "PrivateIp": "10.0.1.50",
                    "NetworkInterfaceId": "eni-12345",
                }],
                "CreateTime": "2024-01-01T00:00:00Z",
                "Tags": [{"Key": "Name", "Value": "prod-nat"}],
            }],
        }]
        mock_session.get_paginator.return_value = paginator

        from agenticops.tools.network_tools import describe_nat_gateways
        result = describe_nat_gateways(region="us-east-1")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["NatGatewayId"] == "nat-12345"
        assert data[0]["State"] == "available"
        assert data[0]["Addresses"][0]["PublicIp"] == "54.1.2.3"


class TestDescribeTransitGateways:
    """Tests for describe_transit_gateways tool."""

    def test_tgw_with_attachments(self, mock_session):
        mock_session.describe_transit_gateways.return_value = {
            "TransitGateways": [{
                "TransitGatewayId": "tgw-12345",
                "State": "available",
                "OwnerId": "123456789012",
                "Options": {
                    "AmazonSideAsn": 64512,
                    "AutoAcceptSharedAttachments": "disable",
                    "DefaultRouteTableAssociation": "enable",
                    "DefaultRouteTablePropagation": "enable",
                },
                "Tags": [{"Key": "Name", "Value": "hub-tgw"}],
            }],
        }
        mock_session.describe_transit_gateway_attachments.return_value = {
            "TransitGatewayAttachments": [{
                "TransitGatewayAttachmentId": "tgw-attach-1",
                "TransitGatewayId": "tgw-12345",
                "ResourceType": "vpc",
                "ResourceId": "vpc-abc",
                "ResourceOwnerId": "123456789012",
                "State": "available",
                "Association": {},
            }],
        }

        from agenticops.tools.network_tools import describe_transit_gateways
        result = describe_transit_gateways(region="us-east-1")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["TransitGatewayId"] == "tgw-12345"
        assert data[0]["AttachmentCount"] == 1
        assert data[0]["Attachments"][0]["ResourceType"] == "vpc"


class TestDescribeLoadBalancers:
    """Tests for describe_load_balancers tool."""

    def test_alb_with_targets(self, mock_session):
        lb_paginator = MagicMock()
        lb_paginator.paginate.return_value = [{
            "LoadBalancers": [{
                "LoadBalancerName": "prod-alb",
                "LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/prod-alb/abc",
                "Type": "application",
                "Scheme": "internet-facing",
                "VpcId": "vpc-12345",
                "State": {"Code": "active"},
                "DNSName": "prod-alb-123.us-east-1.elb.amazonaws.com",
                "AvailabilityZones": [
                    {"ZoneName": "us-east-1a", "SubnetId": "subnet-a"},
                    {"ZoneName": "us-east-1b", "SubnetId": "subnet-b"},
                ],
                "SecurityGroups": ["sg-alb"],
                "IpAddressType": "ipv4",
            }],
        }]

        tg_paginator = MagicMock()
        tg_paginator.paginate.return_value = [{
            "TargetGroups": [{
                "TargetGroupName": "prod-tg",
                "TargetGroupArn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/prod-tg/xyz",
                "Protocol": "HTTP",
                "Port": 80,
                "TargetType": "instance",
                "HealthCheckPath": "/health",
                "LoadBalancerArns": [
                    "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/prod-alb/abc",
                ],
            }],
        }]

        def get_paginator(name):
            if name == "describe_load_balancers":
                return lb_paginator
            elif name == "describe_target_groups":
                return tg_paginator
            raise ValueError(f"Unknown paginator: {name}")

        mock_session.get_paginator.side_effect = get_paginator
        mock_session.describe_target_health.return_value = {
            "TargetHealthDescriptions": [
                {"TargetHealth": {"State": "healthy"}},
                {"TargetHealth": {"State": "healthy"}},
                {"TargetHealth": {"State": "unhealthy"}},
            ],
        }

        from agenticops.tools.network_tools import describe_load_balancers
        result = describe_load_balancers(region="us-east-1")
        data = json.loads(result)

        assert len(data) == 1
        lb = data[0]
        assert lb["LoadBalancerName"] == "prod-alb"
        assert lb["Type"] == "application"
        assert lb["Scheme"] == "internet-facing"
        assert len(lb["TargetGroups"]) == 1
        tg = lb["TargetGroups"][0]
        assert tg["Healthy"] == 2
        assert tg["Unhealthy"] == 1
        assert tg["TotalTargets"] == 3

    def test_no_load_balancers(self, mock_session):
        paginator = MagicMock()
        paginator.paginate.return_value = [{"LoadBalancers": []}]
        mock_session.get_paginator.return_value = paginator

        from agenticops.tools.network_tools import describe_load_balancers
        result = describe_load_balancers(region="us-east-1")
        data = json.loads(result)
        assert data == []


# ---------------------------------------------------------------------------
# New helper tests: _classify_subnet_type
# ---------------------------------------------------------------------------


class TestClassifySubnetType:
    """Tests for _classify_subnet_type helper."""

    def test_public_via_igw(self):
        """Subnet with 0.0.0.0/0 → igw-* should be public."""
        route_tables = [{
            "RouteTableId": "rtb-pub",
            "Associations": [{"SubnetId": "subnet-1", "Main": False}],
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-abc", "State": "active", "Origin": "CreateRoute"},
            ],
        }]
        stype, rt_id, target = _classify_subnet_type("subnet-1", route_tables, None)
        assert stype == "public"
        assert rt_id == "rtb-pub"
        assert target == "igw-abc"

    def test_private_via_nat(self):
        """Subnet with 0.0.0.0/0 → nat-* should be private."""
        route_tables = [{
            "RouteTableId": "rtb-priv",
            "Associations": [{"SubnetId": "subnet-2", "Main": False}],
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-123", "State": "active", "Origin": "CreateRoute"},
            ],
        }]
        stype, rt_id, target = _classify_subnet_type("subnet-2", route_tables, None)
        assert stype == "private"
        assert rt_id == "rtb-priv"
        assert target == "nat-123"

    def test_main_rt_fallback(self):
        """Subnet with no explicit association falls back to main RT."""
        route_tables = [{
            "RouteTableId": "rtb-main",
            "Associations": [{"SubnetId": None, "Main": True}],
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-xyz", "State": "active", "Origin": "CreateRoute"},
            ],
        }]
        stype, rt_id, target = _classify_subnet_type("subnet-orphan", route_tables, "rtb-main")
        assert stype == "public"
        assert rt_id == "rtb-main"
        assert target == "igw-xyz"

    def test_no_default_route(self):
        """Subnet with no 0.0.0.0/0 route should be private with no default target."""
        route_tables = [{
            "RouteTableId": "rtb-isolated",
            "Associations": [{"SubnetId": "subnet-iso", "Main": False}],
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
            ],
        }]
        stype, rt_id, target = _classify_subnet_type("subnet-iso", route_tables, None)
        assert stype == "private"
        assert rt_id == "rtb-isolated"
        assert target is None

    def test_ipv6_default_route_igw(self):
        """Subnet with ::/0 → igw-* should be public."""
        route_tables = [{
            "RouteTableId": "rtb-v6",
            "Associations": [{"SubnetId": "subnet-v6", "Main": False}],
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                {"DestinationIpv6CidrBlock": "::/0", "GatewayId": "igw-v6", "State": "active", "Origin": "CreateRoute"},
            ],
        }]
        stype, rt_id, target = _classify_subnet_type("subnet-v6", route_tables, None)
        assert stype == "public"
        assert target == "igw-v6"


# ---------------------------------------------------------------------------
# New helper tests: _build_sg_dependency_map
# ---------------------------------------------------------------------------


class TestBuildSGDependencyMap:
    """Tests for _build_sg_dependency_map helper."""

    def test_sg_references(self):
        """SG-A inbound allows SG-B → A references B, B referenced_by A."""
        sgs = [
            {
                "GroupId": "sg-a",
                "GroupName": "app-sg",
                "IpPermissions": [{"UserIdGroupPairs": [{"GroupId": "sg-b"}]}],
                "IpPermissionsEgress": [],
            },
            {
                "GroupId": "sg-b",
                "GroupName": "db-sg",
                "IpPermissions": [],
                "IpPermissionsEgress": [],
            },
        ]
        result = _build_sg_dependency_map(sgs)
        assert "sg-b" in result["sg-a"]["references"]
        assert "sg-a" in result["sg-b"]["referenced_by"]

    def test_no_references(self):
        """SGs with no UserIdGroupPairs have empty references."""
        sgs = [{
            "GroupId": "sg-lone",
            "GroupName": "lone-sg",
            "IpPermissions": [{"IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            "IpPermissionsEgress": [],
        }]
        result = _build_sg_dependency_map(sgs)
        assert result["sg-lone"]["references"] == []
        assert result["sg-lone"]["referenced_by"] == []

    def test_bidirectional_reference(self):
        """Two SGs referencing each other."""
        sgs = [
            {
                "GroupId": "sg-x",
                "GroupName": "x-sg",
                "IpPermissions": [{"UserIdGroupPairs": [{"GroupId": "sg-y"}]}],
                "IpPermissionsEgress": [],
            },
            {
                "GroupId": "sg-y",
                "GroupName": "y-sg",
                "IpPermissions": [{"UserIdGroupPairs": [{"GroupId": "sg-x"}]}],
                "IpPermissionsEgress": [],
            },
        ]
        result = _build_sg_dependency_map(sgs)
        # sg-x inbound references sg-y, so sg-x.references = [sg-y] and sg-y.referenced_by = [sg-x]
        assert "sg-y" in result["sg-x"]["references"]
        assert "sg-y" in result["sg-x"]["referenced_by"]  # sg-y's inbound references sg-x → sg-x referenced_by sg-y
        assert "sg-x" in result["sg-y"]["references"]
        assert "sg-x" in result["sg-y"]["referenced_by"]  # sg-x's inbound references sg-y → sg-y referenced_by sg-x

    def test_self_reference(self):
        """SG referencing itself."""
        sgs = [{
            "GroupId": "sg-self",
            "GroupName": "self-sg",
            "IpPermissions": [{"UserIdGroupPairs": [{"GroupId": "sg-self"}]}],
            "IpPermissionsEgress": [],
        }]
        result = _build_sg_dependency_map(sgs)
        assert "sg-self" in result["sg-self"]["references"]
        assert "sg-self" in result["sg-self"]["referenced_by"]


# ---------------------------------------------------------------------------
# New helper tests: _detect_blackhole_routes
# ---------------------------------------------------------------------------


class TestDetectBlackholeRoutes:
    """Tests for _detect_blackhole_routes helper."""

    def test_blackhole_detected(self):
        """Route with state=blackhole is detected."""
        route_tables = [{
            "RouteTableId": "rtb-1",
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active"},
                {"DestinationCidrBlock": "172.16.0.0/12", "TransitGatewayId": "tgw-dead", "State": "blackhole"},
            ],
        }]
        rt_subnet_map = {"rtb-1": ["subnet-a", "subnet-b"]}
        result = _detect_blackhole_routes(route_tables, rt_subnet_map)
        assert len(result) == 1
        assert result[0]["route_table_id"] == "rtb-1"
        assert result[0]["destination"] == "172.16.0.0/12"
        assert result[0]["target"] == "tgw-dead"
        assert result[0]["affected_subnets"] == ["subnet-a", "subnet-b"]

    def test_no_blackholes(self):
        """All routes active → no blackholes."""
        route_tables = [{
            "RouteTableId": "rtb-ok",
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active"},
                {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-123", "State": "active"},
            ],
        }]
        result = _detect_blackhole_routes(route_tables, {})
        assert result == []

    def test_multiple_blackholes_across_tables(self):
        """Blackholes in multiple route tables."""
        route_tables = [
            {
                "RouteTableId": "rtb-1",
                "Routes": [{"DestinationCidrBlock": "172.16.0.0/12", "TransitGatewayId": "tgw-1", "State": "blackhole"}],
            },
            {
                "RouteTableId": "rtb-2",
                "Routes": [{"DestinationCidrBlock": "192.168.0.0/16", "VpcPeeringConnectionId": "pcx-dead", "State": "blackhole"}],
            },
        ]
        rt_subnet_map = {"rtb-1": ["subnet-a"], "rtb-2": ["subnet-b"]}
        result = _detect_blackhole_routes(route_tables, rt_subnet_map)
        assert len(result) == 2
        assert result[0]["target"] == "tgw-1"
        assert result[1]["target"] == "pcx-dead"


# ---------------------------------------------------------------------------
# New tool tests: analyze_vpc_topology
# ---------------------------------------------------------------------------


def _make_topology_mock():
    """Create a mock EC2 client with full VPC topology data."""
    client = MagicMock()

    # VPC
    client.describe_vpcs.return_value = {
        "Vpcs": [{
            "VpcId": "vpc-topo",
            "CidrBlock": "10.0.0.0/16",
            "Tags": [{"Key": "Name", "Value": "topo-vpc"}],
        }],
    }

    # IGW
    client.describe_internet_gateways.return_value = {
        "InternetGateways": [{
            "InternetGatewayId": "igw-topo",
            "Attachments": [{"VpcId": "vpc-topo", "State": "attached"}],
            "Tags": [],
        }],
    }

    # Peering
    client.describe_vpc_peering_connections.return_value = {
        "VpcPeeringConnections": [],
    }

    # Endpoints
    client.describe_vpc_endpoints.return_value = {
        "VpcEndpoints": [{
            "VpcEndpointId": "vpce-s3",
            "ServiceName": "com.amazonaws.us-east-1.s3",
            "VpcEndpointType": "Gateway",
            "State": "available",
            "RouteTableIds": ["rtb-pub"],
            "SubnetIds": [],
        }],
    }

    # Subnets
    client.describe_subnets.return_value = {
        "Subnets": [
            {
                "SubnetId": "subnet-pub1",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.0.1.0/24",
                "AvailableIpAddressCount": 250,
                "Tags": [{"Key": "Name", "Value": "public-1a"}],
            },
            {
                "SubnetId": "subnet-priv1",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.0.10.0/24",
                "AvailableIpAddressCount": 200,
                "Tags": [{"Key": "Name", "Value": "private-1a"}],
            },
        ],
    }

    # Route Tables
    client.describe_route_tables.return_value = {
        "RouteTables": [
            {
                "RouteTableId": "rtb-pub",
                "Associations": [{"SubnetId": "subnet-pub1", "Main": False}],
                "Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                    {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-topo", "State": "active", "Origin": "CreateRoute"},
                ],
                "Tags": [{"Key": "Name", "Value": "public-rt"}],
            },
            {
                "RouteTableId": "rtb-priv",
                "Associations": [{"SubnetId": "subnet-priv1", "Main": False}],
                "Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                    {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-topo", "State": "active", "Origin": "CreateRoute"},
                ],
                "Tags": [{"Key": "Name", "Value": "private-rt"}],
            },
            {
                "RouteTableId": "rtb-main",
                "Associations": [{"SubnetId": None, "Main": True}],
                "Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                ],
                "Tags": [],
            },
        ],
    }

    # NAT Gateways
    client.describe_nat_gateways.return_value = {
        "NatGateways": [{
            "NatGatewayId": "nat-topo",
            "SubnetId": "subnet-pub1",
            "State": "available",
            "ConnectivityType": "public",
            "Tags": [],
        }],
    }

    # Transit Gateway Attachments
    client.describe_transit_gateway_attachments.return_value = {
        "TransitGatewayAttachments": [],
    }

    # Security Groups
    client.describe_security_groups.return_value = {
        "SecurityGroups": [
            {
                "GroupId": "sg-web",
                "GroupName": "web-sg",
                "IpPermissions": [{"UserIdGroupPairs": [{"GroupId": "sg-alb"}]}],
                "IpPermissionsEgress": [],
            },
            {
                "GroupId": "sg-alb",
                "GroupName": "alb-sg",
                "IpPermissions": [],
                "IpPermissionsEgress": [{"UserIdGroupPairs": [{"GroupId": "sg-web"}]}],
            },
        ],
    }

    return client


class TestAnalyzeVpcTopology:
    """Tests for analyze_vpc_topology tool."""

    def test_basic_topology(self):
        """Basic VPC topology with public and private subnets."""
        client = _make_topology_mock()
        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        assert data["vpc_id"] == "vpc-topo"
        assert data["vpc_name"] == "topo-vpc"
        assert data["vpc_cidr"] == "10.0.0.0/16"
        assert len(data["subnets"]) == 2

    def test_subnet_classification(self):
        """Subnets are classified as public/private correctly."""
        client = _make_topology_mock()
        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        sub_by_id = {s["subnet_id"]: s for s in data["subnets"]}
        assert sub_by_id["subnet-pub1"]["type"] == "public"
        assert sub_by_id["subnet-priv1"]["type"] == "private"

    def test_reachability_counts(self):
        """Reachability summary has correct counts."""
        client = _make_topology_mock()
        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        summary = data["reachability_summary"]
        assert summary["has_internet_gateway"] is True
        assert summary["public_subnet_count"] == 1
        assert summary["private_subnet_count"] == 1
        assert summary["nat_gateway_count"] == 1
        assert summary["vpc_endpoint_count"] == 1
        assert summary["blackhole_route_count"] == 0

    def test_igw_in_output(self):
        """Internet gateways appear in output."""
        client = _make_topology_mock()
        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        assert len(data["internet_gateways"]) == 1
        assert data["internet_gateways"][0]["igw_id"] == "igw-topo"

    def test_vpc_endpoints_in_output(self):
        """VPC endpoints appear in output."""
        client = _make_topology_mock()
        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        assert len(data["vpc_endpoints"]) == 1
        assert data["vpc_endpoints"][0]["service_name"] == "com.amazonaws.us-east-1.s3"

    def test_sg_dependency_map(self):
        """Security group dependency map is populated."""
        client = _make_topology_mock()
        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        sg_map = data["security_group_dependency_map"]
        assert "sg-web" in sg_map
        assert "sg-alb" in sg_map["sg-web"]["references"]

    def test_blackhole_detection(self):
        """Blackhole routes are detected and reported in issues."""
        client = _make_topology_mock()
        # Add a blackhole route
        rts = client.describe_route_tables.return_value["RouteTables"]
        rts[1]["Routes"].append({
            "DestinationCidrBlock": "172.16.0.0/12",
            "TransitGatewayId": "tgw-dead",
            "State": "blackhole",
            "Origin": "CreateRoute",
        })

        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        assert data["reachability_summary"]["blackhole_route_count"] == 1
        assert len(data["blackhole_routes"]) == 1
        assert any("Blackhole" in i for i in data["reachability_summary"]["issues"])

    def test_peering_connections(self):
        """VPC peering connections appear in output."""
        client = _make_topology_mock()
        client.describe_vpc_peering_connections.return_value = {
            "VpcPeeringConnections": [{
                "VpcPeeringConnectionId": "pcx-123",
                "Status": {"Code": "active"},
                "RequesterVpcInfo": {"VpcId": "vpc-topo", "CidrBlock": "10.0.0.0/16", "OwnerId": "111"},
                "AccepterVpcInfo": {"VpcId": "vpc-peer", "CidrBlock": "10.1.0.0/16", "OwnerId": "222"},
            }],
        }

        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        assert data["reachability_summary"]["vpc_peering_count"] == 1
        assert data["vpc_peering_connections"][0]["pcx_id"] == "pcx-123"

    def test_isolated_subnet_warning(self):
        """Subnet with no default route generates an isolated warning."""
        client = _make_topology_mock()
        # Add an isolated subnet with its own RT that has no default route
        client.describe_subnets.return_value["Subnets"].append({
            "SubnetId": "subnet-iso",
            "AvailabilityZone": "us-east-1b",
            "CidrBlock": "10.0.99.0/24",
            "AvailableIpAddressCount": 250,
            "Tags": [{"Key": "Name", "Value": "isolated"}],
        })
        client.describe_route_tables.return_value["RouteTables"].append({
            "RouteTableId": "rtb-iso",
            "Associations": [{"SubnetId": "subnet-iso", "Main": False}],
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
            ],
            "Tags": [],
        })

        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-topo")
            data = json.loads(result)

        issues = data["reachability_summary"]["issues"]
        assert any("subnet-iso" in i and "isolated" in i for i in issues)

    def test_error_handling_invalid_vpc(self):
        """Invalid VPC ID returns error in JSON."""
        client = MagicMock()
        client.describe_vpcs.return_value = {"Vpcs": []}

        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-invalid")
            data = json.loads(result)

        assert "error" in data
        assert "not found" in data["error"]

    def test_empty_vpc(self):
        """VPC with no subnets or gateways returns empty lists."""
        client = MagicMock()
        client.describe_vpcs.return_value = {
            "Vpcs": [{"VpcId": "vpc-empty", "CidrBlock": "10.0.0.0/16", "Tags": []}],
        }
        client.describe_internet_gateways.return_value = {"InternetGateways": []}
        client.describe_vpc_peering_connections.return_value = {"VpcPeeringConnections": []}
        client.describe_vpc_endpoints.return_value = {"VpcEndpoints": []}
        client.describe_subnets.return_value = {"Subnets": []}
        client.describe_route_tables.return_value = {"RouteTables": []}
        client.describe_nat_gateways.return_value = {"NatGateways": []}
        client.describe_transit_gateway_attachments.return_value = {"TransitGatewayAttachments": []}
        client.describe_security_groups.return_value = {"SecurityGroups": []}

        with patch("agenticops.tools.network_tools._get_client", return_value=client):
            from agenticops.tools.network_tools import analyze_vpc_topology
            result = analyze_vpc_topology(region="us-east-1", vpc_id="vpc-empty")
            data = json.loads(result)

        assert data["vpc_id"] == "vpc-empty"
        assert data["subnets"] == []
        assert data["internet_gateways"] == []
        assert data["reachability_summary"]["public_subnet_count"] == 0
        assert data["reachability_summary"]["private_subnet_count"] == 0
