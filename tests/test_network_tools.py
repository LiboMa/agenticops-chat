"""Tests for VPC/Networking tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agenticops.tools.network_tools import (
    _extract_name_from_tags,
    _format_sg_rules,
    _format_routes,
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
