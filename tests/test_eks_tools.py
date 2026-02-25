"""Tests for EKS networking tools."""

import json
from unittest.mock import MagicMock, patch, call

import pytest

from agenticops.tools.eks_tools import (
    ENI_LIMITS,
    _calc_max_pods,
    _get_eni_limits,
)


# ---------------------------------------------------------------------------
# Helper / constant tests
# ---------------------------------------------------------------------------


class TestENILimitsTable:
    """Tests for ENI_LIMITS static table."""

    def test_common_types_present(self):
        """Verify common EKS node types are in the table."""
        for itype in ["t3.medium", "m5.xlarge", "c5.2xlarge", "r5.large", "m6i.xlarge", "m7g.large"]:
            assert itype in ENI_LIMITS, f"{itype} missing from ENI_LIMITS"

    def test_formula_correctness(self):
        """Verify max_pods formula: (max_enis * (ipv4_per_eni - 1)) + 2."""
        # m5.xlarge: 4 ENIs, 15 IPv4/ENI → (4 * 14) + 2 = 58
        max_enis, ipv4_per = ENI_LIMITS["m5.xlarge"]
        assert _calc_max_pods(max_enis, ipv4_per) == (max_enis * (ipv4_per - 1)) + 2
        assert _calc_max_pods(4, 15) == 58

        # t3.micro: 2 ENIs, 2 IPv4/ENI → (2 * 1) + 2 = 4
        max_enis, ipv4_per = ENI_LIMITS["t3.micro"]
        assert _calc_max_pods(max_enis, ipv4_per) == 4


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_clients():
    """Patch _get_client to return service-specific mocks."""
    eks_client = MagicMock()
    ec2_client = MagicMock()
    elbv2_client = MagicMock()

    def get_client(service, region):
        if service == "eks":
            return eks_client
        elif service == "ec2":
            return ec2_client
        elif service == "elbv2":
            return elbv2_client
        return MagicMock()

    with patch("agenticops.tools.eks_tools._get_client", side_effect=get_client):
        yield {"eks": eks_client, "ec2": ec2_client, "elbv2": elbv2_client}


def _setup_list_clusters(eks_mock, cluster_names):
    """Helper to set up list_clusters paginator."""
    paginator = MagicMock()
    paginator.paginate.return_value = [{"clusters": cluster_names}]
    eks_mock.get_paginator.return_value = paginator


def _setup_list_nodegroups(eks_mock, nodegroup_names):
    """Helper to set up list_nodegroups paginator."""
    paginator = MagicMock()
    paginator.paginate.return_value = [{"nodegroups": nodegroup_names}]
    eks_mock.get_paginator.return_value = paginator


def _make_cluster_response(name="test-cluster", vpc_id="vpc-eks", subnets=None):
    """Helper to create a describe_cluster response."""
    return {
        "cluster": {
            "name": name,
            "version": "1.28",
            "status": "ACTIVE",
            "platformVersion": "eks.5",
            "resourcesVpcConfig": {
                "vpcId": vpc_id,
                "subnetIds": subnets or ["subnet-a", "subnet-b"],
                "securityGroupIds": ["sg-cluster"],
                "clusterSecurityGroupId": "sg-cluster-auto",
                "endpointPublicAccess": True,
                "endpointPrivateAccess": True,
                "publicAccessCidrs": ["0.0.0.0/0"],
            },
            "kubernetesNetworkConfig": {
                "serviceIpv4Cidr": "172.20.0.0/16",
                "ipFamily": "ipv4",
            },
            "logging": {
                "clusterLogging": [
                    {"types": ["api", "audit"], "enabled": True},
                    {"types": ["authenticator"], "enabled": False},
                ],
            },
            "endpoint": "https://ABCDEF.gr7.us-east-1.eks.amazonaws.com",
            "roleArn": "arn:aws:iam::123456789012:role/eks-role",
            "createdAt": "2024-01-01T00:00:00Z",
            "tags": {"env": "prod"},
        },
    }


def _make_nodegroup_response(
    ng_name="ng-1",
    instance_types=None,
    capacity_type="ON_DEMAND",
    desired=3,
    subnets=None,
):
    """Helper to create a describe_nodegroup response."""
    return {
        "nodegroup": {
            "nodegroupName": ng_name,
            "status": "ACTIVE",
            "instanceTypes": instance_types or ["m5.xlarge"],
            "amiType": "AL2_x86_64",
            "capacityType": capacity_type,
            "scalingConfig": {"minSize": 1, "maxSize": 10, "desiredSize": desired},
            "subnets": subnets or ["subnet-a", "subnet-b"],
            "diskSize": 20,
            "labels": {"role": "worker"},
            "taints": [],
            "health": {"issues": []},
            "releaseVersion": "1.28.3-20240101",
            "tags": {},
        },
    }


# ---------------------------------------------------------------------------
# describe_eks_clusters tests
# ---------------------------------------------------------------------------


class TestDescribeEksClusters:
    """Tests for describe_eks_clusters tool."""

    def test_single_cluster(self, mock_clients):
        eks = mock_clients["eks"]
        _setup_list_clusters(eks, ["prod-cluster"])
        eks.describe_cluster.return_value = _make_cluster_response("prod-cluster")

        from agenticops.tools.eks_tools import describe_eks_clusters
        result = describe_eks_clusters(region="us-east-1")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["name"] == "prod-cluster"
        assert data[0]["version"] == "1.28"
        assert data[0]["status"] == "ACTIVE"
        assert data[0]["vpc_config"]["vpc_id"] == "vpc-eks"

    def test_multiple_clusters(self, mock_clients):
        eks = mock_clients["eks"]
        _setup_list_clusters(eks, ["cluster-a", "cluster-b"])
        eks.describe_cluster.side_effect = [
            _make_cluster_response("cluster-a"),
            _make_cluster_response("cluster-b"),
        ]

        from agenticops.tools.eks_tools import describe_eks_clusters
        result = describe_eks_clusters(region="us-east-1")
        data = json.loads(result)

        assert len(data) == 2
        names = {c["name"] for c in data}
        assert names == {"cluster-a", "cluster-b"}

    def test_no_clusters(self, mock_clients):
        eks = mock_clients["eks"]
        _setup_list_clusters(eks, [])

        from agenticops.tools.eks_tools import describe_eks_clusters
        result = describe_eks_clusters(region="us-east-1")
        data = json.loads(result)

        assert data == []

    def test_vpc_config_details(self, mock_clients):
        eks = mock_clients["eks"]
        _setup_list_clusters(eks, ["test"])
        eks.describe_cluster.return_value = _make_cluster_response("test")

        from agenticops.tools.eks_tools import describe_eks_clusters
        result = describe_eks_clusters(region="us-east-1")
        data = json.loads(result)

        vpc_config = data[0]["vpc_config"]
        assert vpc_config["endpoint_public_access"] is True
        assert vpc_config["endpoint_private_access"] is True
        assert vpc_config["cluster_security_group_id"] == "sg-cluster-auto"
        assert data[0]["kubernetes_network_config"]["service_ipv4_cidr"] == "172.20.0.0/16"
        assert "api" in data[0]["enabled_logging"]
        assert "authenticator" not in data[0]["enabled_logging"]

    def test_error_handling(self, mock_clients):
        eks = mock_clients["eks"]
        paginator = MagicMock()
        paginator.paginate.side_effect = Exception("EKS access denied")
        eks.get_paginator.return_value = paginator

        from agenticops.tools.eks_tools import describe_eks_clusters
        result = describe_eks_clusters(region="us-east-1")
        data = json.loads(result)

        assert "error" in data


# ---------------------------------------------------------------------------
# describe_eks_nodegroups tests
# ---------------------------------------------------------------------------


class TestDescribeEksNodegroups:
    """Tests for describe_eks_nodegroups tool."""

    def test_single_nodegroup(self, mock_clients):
        eks = mock_clients["eks"]
        _setup_list_nodegroups(eks, ["ng-1"])
        eks.describe_nodegroup.return_value = _make_nodegroup_response("ng-1")

        from agenticops.tools.eks_tools import describe_eks_nodegroups
        result = describe_eks_nodegroups(region="us-east-1", cluster_name="test")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["nodegroup_name"] == "ng-1"
        assert data[0]["status"] == "ACTIVE"
        assert data[0]["instance_types"] == ["m5.xlarge"]
        assert data[0]["scaling_config"]["desired_size"] == 3

    def test_multiple_nodegroups(self, mock_clients):
        eks = mock_clients["eks"]
        _setup_list_nodegroups(eks, ["ng-1", "ng-2"])
        eks.describe_nodegroup.side_effect = [
            _make_nodegroup_response("ng-1"),
            _make_nodegroup_response("ng-2", instance_types=["c5.xlarge"]),
        ]

        from agenticops.tools.eks_tools import describe_eks_nodegroups
        result = describe_eks_nodegroups(region="us-east-1", cluster_name="test")
        data = json.loads(result)

        assert len(data) == 2

    def test_no_nodegroups(self, mock_clients):
        eks = mock_clients["eks"]
        _setup_list_nodegroups(eks, [])

        from agenticops.tools.eks_tools import describe_eks_nodegroups
        result = describe_eks_nodegroups(region="us-east-1", cluster_name="test")
        data = json.loads(result)

        assert data == []

    def test_spot_capacity_type(self, mock_clients):
        eks = mock_clients["eks"]
        _setup_list_nodegroups(eks, ["ng-spot"])
        eks.describe_nodegroup.return_value = _make_nodegroup_response(
            "ng-spot", capacity_type="SPOT"
        )

        from agenticops.tools.eks_tools import describe_eks_nodegroups
        result = describe_eks_nodegroups(region="us-east-1", cluster_name="test")
        data = json.loads(result)

        assert data[0]["capacity_type"] == "SPOT"

    def test_error_handling(self, mock_clients):
        eks = mock_clients["eks"]
        paginator = MagicMock()
        paginator.paginate.side_effect = Exception("nodegroup error")
        eks.get_paginator.return_value = paginator

        from agenticops.tools.eks_tools import describe_eks_nodegroups
        result = describe_eks_nodegroups(region="us-east-1", cluster_name="test")
        data = json.loads(result)

        assert "error" in data


# ---------------------------------------------------------------------------
# check_eks_pod_ip_capacity tests
# ---------------------------------------------------------------------------


class TestCheckEksPodIpCapacity:
    """Tests for check_eks_pod_ip_capacity tool."""

    def _setup_capacity_mocks(self, mock_clients, instance_type="m5.xlarge", desired=3):
        eks = mock_clients["eks"]
        ec2 = mock_clients["ec2"]

        eks.describe_cluster.return_value = _make_cluster_response(
            "cap-test", subnets=["subnet-a"]
        )
        _setup_list_nodegroups(eks, ["ng-1"])
        eks.describe_nodegroup.return_value = _make_nodegroup_response(
            "ng-1", instance_types=[instance_type], desired=desired,
            subnets=["subnet-a"],
        )

        ec2.describe_subnets.return_value = {
            "Subnets": [{
                "SubnetId": "subnet-a",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.0.1.0/24",
                "AvailableIpAddressCount": 200,
            }],
        }

    def test_basic_capacity_calculation(self, mock_clients):
        self._setup_capacity_mocks(mock_clients)

        from agenticops.tools.eks_tools import check_eks_pod_ip_capacity
        result = check_eks_pod_ip_capacity(region="us-east-1", cluster_name="cap-test")
        data = json.loads(result)

        assert data["cluster_name"] == "cap-test"
        assert len(data["nodegroups"]) == 1
        ng = data["nodegroups"][0]
        # m5.xlarge: (4*14)+2 = 58 max pods
        assert ng["max_pods_per_node"]["m5.xlarge"] == 58
        assert ng["total_pod_capacity"] == 58 * 3  # 174

    def test_subnet_availability(self, mock_clients):
        self._setup_capacity_mocks(mock_clients)

        from agenticops.tools.eks_tools import check_eks_pod_ip_capacity
        result = check_eks_pod_ip_capacity(region="us-east-1", cluster_name="cap-test")
        data = json.loads(result)

        assert len(data["subnet_ip_availability"]) == 1
        subnet = data["subnet_ip_availability"][0]
        assert subnet["subnet_id"] == "subnet-a"
        assert subnet["available_ips"] == 200

    def test_low_ip_warning(self, mock_clients):
        """Subnet with >80% utilization triggers a warning."""
        eks = mock_clients["eks"]
        ec2 = mock_clients["ec2"]

        eks.describe_cluster.return_value = _make_cluster_response(
            "warn-test", subnets=["subnet-low"]
        )
        _setup_list_nodegroups(eks, ["ng-1"])
        eks.describe_nodegroup.return_value = _make_nodegroup_response(
            "ng-1", subnets=["subnet-low"]
        )

        ec2.describe_subnets.return_value = {
            "Subnets": [{
                "SubnetId": "subnet-low",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.0.1.0/24",
                "AvailableIpAddressCount": 15,  # /24 = 251 usable, 15 avail = ~94%
            }],
        }

        from agenticops.tools.eks_tools import check_eks_pod_ip_capacity
        result = check_eks_pod_ip_capacity(region="us-east-1", cluster_name="warn-test")
        data = json.loads(result)

        assert len(data["warnings"]) > 0
        assert any("subnet-low" in w for w in data["warnings"])

    def test_unknown_instance_type_fallback(self, mock_clients):
        """Unknown instance type falls back to describe_instance_types."""
        eks = mock_clients["eks"]
        ec2 = mock_clients["ec2"]

        eks.describe_cluster.return_value = _make_cluster_response(
            "fb-test", subnets=["subnet-a"]
        )
        _setup_list_nodegroups(eks, ["ng-custom"])
        eks.describe_nodegroup.return_value = _make_nodegroup_response(
            "ng-custom", instance_types=["x99.special"],
            subnets=["subnet-a"],
        )

        # Mock describe_instance_types for the unknown type
        ec2.describe_instance_types.return_value = {
            "InstanceTypes": [{
                "NetworkInfo": {
                    "MaximumNetworkInterfaces": 8,
                    "Ipv4AddressesPerInterface": 30,
                },
            }],
        }
        ec2.describe_subnets.return_value = {
            "Subnets": [{
                "SubnetId": "subnet-a",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.0.1.0/24",
                "AvailableIpAddressCount": 200,
            }],
        }

        from agenticops.tools.eks_tools import check_eks_pod_ip_capacity
        result = check_eks_pod_ip_capacity(region="us-east-1", cluster_name="fb-test")
        data = json.loads(result)

        ng = data["nodegroups"][0]
        # x99.special: (8 * 29) + 2 = 234
        assert ng["max_pods_per_node"]["x99.special"] == 234

    def test_error_handling(self, mock_clients):
        eks = mock_clients["eks"]
        eks.describe_cluster.side_effect = Exception("access denied")

        from agenticops.tools.eks_tools import check_eks_pod_ip_capacity
        result = check_eks_pod_ip_capacity(region="us-east-1", cluster_name="err")
        data = json.loads(result)

        assert "error" in data


# ---------------------------------------------------------------------------
# map_eks_to_vpc_topology tests
# ---------------------------------------------------------------------------


def _setup_topology_mocks(mock_clients, has_nat=True, has_lb=True):
    """Configure mocks for map_eks_to_vpc_topology tests."""
    eks = mock_clients["eks"]
    ec2 = mock_clients["ec2"]
    elbv2 = mock_clients["elbv2"]

    eks.describe_cluster.return_value = _make_cluster_response(
        "topo-cluster", vpc_id="vpc-topo", subnets=["subnet-pub", "subnet-priv"]
    )

    ng_paginator = MagicMock()
    ng_paginator.paginate.return_value = [{"nodegroups": ["ng-1"]}]
    eks.get_paginator.return_value = ng_paginator

    eks.describe_nodegroup.return_value = {
        "nodegroup": {
            "nodegroupName": "ng-1",
            "subnets": ["subnet-priv"],
        },
    }

    ec2.describe_subnets.return_value = {
        "Subnets": [
            {
                "SubnetId": "subnet-pub",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.0.1.0/24",
                "AvailableIpAddressCount": 250,
                "Tags": [{"Key": "Name", "Value": "public"}],
            },
            {
                "SubnetId": "subnet-priv",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.0.10.0/24",
                "AvailableIpAddressCount": 200,
                "Tags": [{"Key": "Name", "Value": "private"}],
            },
        ],
    }

    ec2.describe_route_tables.return_value = {
        "RouteTables": [
            {
                "RouteTableId": "rtb-pub",
                "Associations": [{"SubnetId": "subnet-pub", "Main": False}],
                "Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                    {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-1", "State": "active", "Origin": "CreateRoute"},
                ],
            },
            {
                "RouteTableId": "rtb-priv",
                "Associations": [{"SubnetId": "subnet-priv", "Main": False}],
                "Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                    {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-1", "State": "active", "Origin": "CreateRoute"},
                ],
            },
            {
                "RouteTableId": "rtb-main",
                "Associations": [{"SubnetId": None, "Main": True}],
                "Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                ],
            },
        ],
    }

    if has_nat:
        ec2.describe_nat_gateways.return_value = {
            "NatGateways": [{
                "NatGatewayId": "nat-1",
                "SubnetId": "subnet-pub",
                "State": "available",
            }],
        }
    else:
        ec2.describe_nat_gateways.return_value = {"NatGateways": []}

    ec2.describe_internet_gateways.return_value = {
        "InternetGateways": [{"InternetGatewayId": "igw-1"}],
    }

    if has_lb:
        lb_paginator = MagicMock()
        lb_paginator.paginate.return_value = [{
            "LoadBalancers": [{
                "LoadBalancerName": "k8s-alb",
                "Type": "application",
                "Scheme": "internet-facing",
                "VpcId": "vpc-topo",
                "State": {"Code": "active"},
                "DNSName": "k8s-alb-123.elb.amazonaws.com",
                "AvailabilityZones": [{"ZoneName": "us-east-1a"}],
            }],
        }]
        elbv2.get_paginator.return_value = lb_paginator
    else:
        lb_paginator = MagicMock()
        lb_paginator.paginate.return_value = [{"LoadBalancers": []}]
        elbv2.get_paginator.return_value = lb_paginator


class TestMapEksToVpcTopology:
    """Tests for map_eks_to_vpc_topology tool."""

    def test_full_mapping(self, mock_clients):
        _setup_topology_mocks(mock_clients)

        from agenticops.tools.eks_tools import map_eks_to_vpc_topology
        result = map_eks_to_vpc_topology(region="us-east-1", cluster_name="topo-cluster")
        data = json.loads(result)

        assert data["cluster_name"] == "topo-cluster"
        assert data["vpc_id"] == "vpc-topo"
        assert len(data["subnet_topology"]) == 2
        assert len(data["nat_gateways"]) == 1
        assert len(data["internet_gateways"]) == 1

    def test_private_subnet_routing(self, mock_clients):
        _setup_topology_mocks(mock_clients)

        from agenticops.tools.eks_tools import map_eks_to_vpc_topology
        result = map_eks_to_vpc_topology(region="us-east-1", cluster_name="topo-cluster")
        data = json.loads(result)

        sub_by_id = {s["subnet_id"]: s for s in data["subnet_topology"]}
        assert sub_by_id["subnet-pub"]["type"] == "public"
        assert sub_by_id["subnet-priv"]["type"] == "private"
        assert sub_by_id["subnet-priv"]["default_route_target"] == "nat-1"

    def test_load_balancers_in_vpc(self, mock_clients):
        _setup_topology_mocks(mock_clients, has_lb=True)

        from agenticops.tools.eks_tools import map_eks_to_vpc_topology
        result = map_eks_to_vpc_topology(region="us-east-1", cluster_name="topo-cluster")
        data = json.loads(result)

        assert len(data["load_balancers_in_vpc"]) == 1
        assert data["load_balancers_in_vpc"][0]["name"] == "k8s-alb"

    def test_topology_issues_missing_nat_az(self, mock_clients):
        """Detect when private subnets span AZs but NAT is only in some."""
        eks = mock_clients["eks"]
        ec2 = mock_clients["ec2"]
        elbv2 = mock_clients["elbv2"]

        eks.describe_cluster.return_value = _make_cluster_response(
            "issue-cluster", vpc_id="vpc-issue",
            subnets=["subnet-priv-1a", "subnet-priv-1b"],
        )
        ng_paginator = MagicMock()
        ng_paginator.paginate.return_value = [{"nodegroups": ["ng-1"]}]
        eks.get_paginator.return_value = ng_paginator
        eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "nodegroupName": "ng-1",
                "subnets": ["subnet-priv-1a", "subnet-priv-1b"],
            },
        }

        ec2.describe_subnets.return_value = {
            "Subnets": [
                {"SubnetId": "subnet-priv-1a", "AvailabilityZone": "us-east-1a",
                 "CidrBlock": "10.0.1.0/24", "AvailableIpAddressCount": 200, "Tags": []},
                {"SubnetId": "subnet-priv-1b", "AvailabilityZone": "us-east-1b",
                 "CidrBlock": "10.0.2.0/24", "AvailableIpAddressCount": 200, "Tags": []},
                {"SubnetId": "subnet-pub-1a", "AvailabilityZone": "us-east-1a",
                 "CidrBlock": "10.0.101.0/24", "AvailableIpAddressCount": 250, "Tags": []},
            ],
        }

        ec2.describe_route_tables.return_value = {
            "RouteTables": [
                {
                    "RouteTableId": "rtb-priv",
                    "Associations": [
                        {"SubnetId": "subnet-priv-1a", "Main": False},
                        {"SubnetId": "subnet-priv-1b", "Main": False},
                    ],
                    "Routes": [
                        {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                        {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-1a", "State": "active", "Origin": "CreateRoute"},
                    ],
                },
                {
                    "RouteTableId": "rtb-main",
                    "Associations": [{"SubnetId": None, "Main": True}],
                    "Routes": [
                        {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"},
                    ],
                },
            ],
        }

        # NAT only in us-east-1a
        ec2.describe_nat_gateways.return_value = {
            "NatGateways": [{
                "NatGatewayId": "nat-1a",
                "SubnetId": "subnet-pub-1a",
                "State": "available",
            }],
        }

        ec2.describe_internet_gateways.return_value = {"InternetGateways": []}
        lb_paginator = MagicMock()
        lb_paginator.paginate.return_value = [{"LoadBalancers": []}]
        elbv2.get_paginator.return_value = lb_paginator

        from agenticops.tools.eks_tools import map_eks_to_vpc_topology
        result = map_eks_to_vpc_topology(region="us-east-1", cluster_name="issue-cluster")
        data = json.loads(result)

        # Private subnets in 1a and 1b, NAT only in 1a → issue
        assert len(data["topology_issues"]) > 0
        assert any("NAT" in issue for issue in data["topology_issues"])

    def test_error_handling(self, mock_clients):
        eks = mock_clients["eks"]
        eks.describe_cluster.side_effect = Exception("cluster not found")

        from agenticops.tools.eks_tools import map_eks_to_vpc_topology
        result = map_eks_to_vpc_topology(region="us-east-1", cluster_name="missing")
        data = json.loads(result)

        assert "error" in data
