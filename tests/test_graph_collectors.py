"""Tests for agenticops.graph.collectors — AWS data collectors for graph enrichment.

Covers:
- collect_vpc_compute: EC2, RDS, Lambda, Target Groups, ElastiCache
- collect_eks_topology: cluster + nodegroups
- collect_ecs_topology: cluster + services + tasks
- VPC filtering (only resources in the target VPC)
- Exception isolation (one resource type failure doesn't block others)
- Empty results / pagination
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────


def _paginator(pages: list[dict]):
    """Build a mock paginator that yields pages."""
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = pages
    return mock_paginator


def _client_factory(clients: dict[str, MagicMock]):
    """Return a function that returns the right mock client for each service."""
    def factory(service_name, region):
        return clients.get(service_name, MagicMock())
    return factory


# ── collect_vpc_compute ──────────────────────────────────────────────


class TestCollectVpcCompute:

    @pytest.fixture(autouse=True)
    def _patch_client(self):
        self.ec2 = MagicMock()
        self.rds = MagicMock()
        self.lam = MagicMock()
        self.elbv2 = MagicMock()
        self.elasticache = MagicMock()

        clients = {
            "ec2": self.ec2,
            "rds": self.rds,
            "lambda": self.lam,
            "elbv2": self.elbv2,
            "elasticache": self.elasticache,
        }
        with patch("agenticops.graph.collectors._get_client", side_effect=_client_factory(clients)):
            yield

    def _setup_empty(self):
        """Set all paginators to return empty pages."""
        self.ec2.get_paginator.return_value = _paginator([{"Reservations": []}])
        self.rds.get_paginator.return_value = _paginator([{"DBInstances": []}])
        self.lam.get_paginator.return_value = _paginator([{"Functions": []}])
        self.elbv2.get_paginator.return_value = _paginator([{"TargetGroups": []}])
        self.elasticache.get_paginator.return_value = _paginator([{"CacheClusters": []}])

    def test_empty_vpc(self):
        self._setup_empty()
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-empty")
        assert result == {
            "ec2_instances": [],
            "rds_instances": [],
            "lambda_functions": [],
            "target_groups": [],
            "elasticache_clusters": [],
        }

    def test_ec2_instances_collected(self):
        self._setup_empty()
        self.ec2.get_paginator.return_value = _paginator([{
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-abc123",
                    "InstanceType": "t3.micro",
                    "State": {"Name": "running"},
                    "SubnetId": "subnet-1",
                    "PrivateIpAddress": "10.0.1.5",
                    "PublicIpAddress": "1.2.3.4",
                    "SecurityGroups": [{"GroupId": "sg-1"}],
                    "Tags": [{"Key": "Name", "Value": "web-1"}],
                }]
            }]
        }])
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["ec2_instances"]) == 1
        inst = result["ec2_instances"][0]
        assert inst["instance_id"] == "i-abc123"
        assert inst["name"] == "web-1"
        assert inst["state"] == "running"
        assert inst["security_group_ids"] == ["sg-1"]

    def test_ec2_no_name_tag(self):
        self._setup_empty()
        self.ec2.get_paginator.return_value = _paginator([{
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-noname",
                    "State": {"Name": "running"},
                    "Tags": [{"Key": "Env", "Value": "prod"}],
                }]
            }]
        }])
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert result["ec2_instances"][0]["name"] == ""

    def test_rds_filters_by_vpc(self):
        self._setup_empty()
        self.rds.get_paginator.return_value = _paginator([{
            "DBInstances": [
                {  # In target VPC
                    "DBInstanceIdentifier": "db-prod",
                    "Engine": "postgres",
                    "DBInstanceStatus": "available",
                    "DBSubnetGroup": {"VpcId": "vpc-1", "Subnets": [{"SubnetIdentifier": "sub-1"}]},
                    "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-db"}],
                    "MultiAZ": True,
                    "Endpoint": {"Address": "db.example.com", "Port": 5432},
                },
                {  # Different VPC — should be excluded
                    "DBInstanceIdentifier": "db-other",
                    "Engine": "mysql",
                    "DBSubnetGroup": {"VpcId": "vpc-other"},
                    "VpcSecurityGroups": [],
                    "Endpoint": {},
                },
            ]
        }])
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["rds_instances"]) == 1
        assert result["rds_instances"][0]["db_instance_id"] == "db-prod"
        assert result["rds_instances"][0]["multi_az"] is True

    def test_lambda_filters_by_vpc(self):
        self._setup_empty()
        self.lam.get_paginator.return_value = _paginator([{
            "Functions": [
                {
                    "FunctionName": "fn-in-vpc",
                    "Runtime": "python3.12",
                    "MemorySize": 256,
                    "Timeout": 30,
                    "VpcConfig": {"VpcId": "vpc-1", "SubnetIds": ["sub-1"], "SecurityGroupIds": ["sg-1"]},
                },
                {
                    "FunctionName": "fn-no-vpc",
                    "Runtime": "python3.12",
                    "VpcConfig": {"VpcId": ""},
                },
            ]
        }])
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["lambda_functions"]) == 1
        assert result["lambda_functions"][0]["function_name"] == "fn-in-vpc"

    def test_target_groups_with_health(self):
        self._setup_empty()
        self.elbv2.get_paginator.return_value = _paginator([{
            "TargetGroups": [{
                "TargetGroupArn": "arn:tg:1",
                "TargetGroupName": "tg-web",
                "Protocol": "HTTP",
                "Port": 80,
                "TargetType": "instance",
                "LoadBalancerArns": ["arn:lb:1"],
                "VpcId": "vpc-1",
            }]
        }])
        self.elbv2.describe_target_health.return_value = {
            "TargetHealthDescriptions": [{
                "Target": {"Id": "i-abc", "Port": 80},
                "TargetHealth": {"State": "healthy"},
            }]
        }
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["target_groups"]) == 1
        tg = result["target_groups"][0]
        assert tg["target_group_name"] == "tg-web"
        assert len(tg["targets"]) == 1
        assert tg["targets"][0]["health_state"] == "healthy"

    def test_target_health_failure_still_returns_tg(self):
        """describe_target_health failure should not block the TG itself."""
        self._setup_empty()
        self.elbv2.get_paginator.return_value = _paginator([{
            "TargetGroups": [{
                "TargetGroupArn": "arn:tg:1",
                "TargetGroupName": "tg-web",
                "VpcId": "vpc-1",
            }]
        }])
        self.elbv2.describe_target_health.side_effect = Exception("access denied")
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["target_groups"]) == 1
        assert result["target_groups"][0]["targets"] == []

    def test_elasticache_resolves_subnet_group(self):
        self._setup_empty()
        self.elasticache.get_paginator.return_value = _paginator([{
            "CacheClusters": [{
                "CacheClusterId": "redis-prod",
                "Engine": "redis",
                "EngineVersion": "7.0",
                "CacheNodeType": "cache.t3.micro",
                "CacheClusterStatus": "available",
                "NumCacheNodes": 1,
                "CacheSubnetGroupName": "redis-subnets",
                "SecurityGroups": [{"SecurityGroupId": "sg-redis"}],
            }]
        }])
        self.elasticache.describe_cache_subnet_groups.return_value = {
            "CacheSubnetGroups": [{
                "VpcId": "vpc-1",
                "Subnets": [{"SubnetIdentifier": "sub-a"}, {"SubnetIdentifier": "sub-b"}],
            }]
        }
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["elasticache_clusters"]) == 1
        ec = result["elasticache_clusters"][0]
        assert ec["cache_cluster_id"] == "redis-prod"
        assert ec["subnet_ids"] == ["sub-a", "sub-b"]

    def test_elasticache_wrong_vpc_excluded(self):
        self._setup_empty()
        self.elasticache.get_paginator.return_value = _paginator([{
            "CacheClusters": [{
                "CacheClusterId": "redis-other",
                "CacheSubnetGroupName": "other-subnets",
            }]
        }])
        self.elasticache.describe_cache_subnet_groups.return_value = {
            "CacheSubnetGroups": [{
                "VpcId": "vpc-other",
                "Subnets": [],
            }]
        }
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["elasticache_clusters"]) == 0

    def test_elasticache_no_subnet_group_skipped(self):
        """Cluster without CacheSubnetGroupName is skipped."""
        self._setup_empty()
        self.elasticache.get_paginator.return_value = _paginator([{
            "CacheClusters": [{
                "CacheClusterId": "redis-no-sg",
                "CacheSubnetGroupName": "",
            }]
        }])
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["elasticache_clusters"]) == 0

    def test_elasticache_subnet_lookup_failure_skipped(self):
        """describe_cache_subnet_groups failure → cluster skipped."""
        self._setup_empty()
        self.elasticache.get_paginator.return_value = _paginator([{
            "CacheClusters": [{
                "CacheClusterId": "redis-fail",
                "CacheSubnetGroupName": "broken-group",
            }]
        }])
        self.elasticache.describe_cache_subnet_groups.side_effect = Exception("not found")
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert len(result["elasticache_clusters"]) == 0

    # ── Fault isolation tests ────────────────────────────────────────

    def test_ec2_failure_doesnt_block_rds(self):
        """EC2 exception should not prevent RDS collection."""
        self._setup_empty()
        self.ec2.get_paginator.side_effect = Exception("EC2 error")
        self.rds.get_paginator.return_value = _paginator([{
            "DBInstances": [{
                "DBInstanceIdentifier": "db-1",
                "DBSubnetGroup": {"VpcId": "vpc-1", "Subnets": []},
                "VpcSecurityGroups": [],
                "Endpoint": {},
            }]
        }])
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        assert result["ec2_instances"] == []
        assert len(result["rds_instances"]) == 1

    def test_all_services_fail_returns_empty(self):
        for client in [self.ec2, self.rds, self.lam, self.elbv2, self.elasticache]:
            client.get_paginator.side_effect = Exception("boom")
        from agenticops.graph.collectors import collect_vpc_compute
        result = collect_vpc_compute("us-east-1", "vpc-1")
        for key in result:
            assert result[key] == []


# ── collect_eks_topology ─────────────────────────────────────────────


class TestCollectEksTopology:

    @pytest.fixture(autouse=True)
    def _patch_client(self):
        self.eks = MagicMock()
        with patch("agenticops.graph.collectors._get_client", return_value=self.eks):
            yield

    def test_cluster_and_nodegroups(self):
        self.eks.describe_cluster.return_value = {
            "cluster": {
                "name": "prod-cluster",
                "status": "ACTIVE",
                "version": "1.28",
                "resourcesVpcConfig": {
                    "subnetIds": ["sub-1", "sub-2"],
                    "clusterSecurityGroupId": "sg-cluster",
                    "vpcId": "vpc-1",
                },
                "endpoint": "https://eks.example.com",
            }
        }
        self.eks.list_nodegroups.return_value = {"nodegroups": ["ng-1"]}
        self.eks.describe_nodegroup.return_value = {
            "nodegroup": {
                "nodegroupName": "ng-1",
                "status": "ACTIVE",
                "instanceTypes": ["t3.medium"],
                "subnets": ["sub-1"],
                "scalingConfig": {"desiredSize": 3, "minSize": 1, "maxSize": 5},
            }
        }
        from agenticops.graph.collectors import collect_eks_topology
        result = collect_eks_topology("us-east-1", "prod-cluster")
        assert result["cluster"]["name"] == "prod-cluster"
        assert result["cluster"]["vpc_id"] == "vpc-1"
        assert len(result["nodegroups"]) == 1
        assert result["nodegroups"][0]["desired_size"] == 3

    def test_empty_security_group_filtered(self):
        self.eks.describe_cluster.return_value = {
            "cluster": {
                "name": "test",
                "resourcesVpcConfig": {"clusterSecurityGroupId": "", "subnetIds": []},
            }
        }
        self.eks.list_nodegroups.return_value = {"nodegroups": []}
        from agenticops.graph.collectors import collect_eks_topology
        result = collect_eks_topology("us-east-1", "test")
        assert result["cluster"]["security_group_ids"] == []

    def test_nodegroup_describe_failure_continues(self):
        self.eks.describe_cluster.return_value = {
            "cluster": {"name": "c1", "resourcesVpcConfig": {"subnetIds": [], "clusterSecurityGroupId": ""}},
        }
        self.eks.list_nodegroups.return_value = {"nodegroups": ["ng-ok", "ng-fail"]}
        self.eks.describe_nodegroup.side_effect = [
            {"nodegroup": {"nodegroupName": "ng-ok", "status": "ACTIVE", "scalingConfig": {}}},
            Exception("forbidden"),
        ]
        from agenticops.graph.collectors import collect_eks_topology
        result = collect_eks_topology("us-east-1", "c1")
        assert len(result["nodegroups"]) == 1

    def test_complete_failure_returns_empty(self):
        self.eks.describe_cluster.side_effect = Exception("not found")
        from agenticops.graph.collectors import collect_eks_topology
        result = collect_eks_topology("us-east-1", "missing")
        assert result == {"cluster": {}, "nodegroups": []}


# ── collect_ecs_topology ─────────────────────────────────────────────


class TestCollectEcsTopology:

    @pytest.fixture(autouse=True)
    def _patch_client(self):
        self.ecs = MagicMock()
        with patch("agenticops.graph.collectors._get_client", return_value=self.ecs):
            yield

    def test_cluster_services_tasks(self):
        self.ecs.describe_clusters.return_value = {
            "clusters": [{
                "clusterName": "prod",
                "clusterArn": "arn:ecs:prod",
                "status": "ACTIVE",
                "runningTasksCount": 5,
                "activeServicesCount": 2,
            }]
        }
        svc_paginator = _paginator([{"serviceArns": ["arn:svc:1"]}])
        task_paginator = _paginator([{"taskArns": ["arn:task:1"]}])
        self.ecs.get_paginator.side_effect = lambda name: {
            "list_services": svc_paginator,
            "list_tasks": task_paginator,
        }[name]
        self.ecs.describe_services.return_value = {
            "services": [{
                "serviceName": "web-svc",
                "serviceArn": "arn:svc:1",
                "status": "ACTIVE",
                "desiredCount": 3,
                "runningCount": 3,
                "launchType": "FARGATE",
                "networkConfiguration": {
                    "awsvpcConfiguration": {
                        "subnets": ["sub-1"],
                        "securityGroups": ["sg-1"],
                    }
                },
            }]
        }
        self.ecs.describe_tasks.return_value = {
            "tasks": [{
                "taskArn": "arn:task:1",
                "taskDefinitionArn": "arn:taskdef:1",
                "lastStatus": "RUNNING",
                "desiredStatus": "RUNNING",
                "launchType": "FARGATE",
                "group": "service:web-svc",
                "attachments": [{
                    "details": [
                        {"name": "subnetId", "value": "sub-1"},
                    ]
                }],
            }]
        }
        from agenticops.graph.collectors import collect_ecs_topology
        result = collect_ecs_topology("us-east-1", "prod")
        assert result["cluster"]["cluster_name"] == "prod"
        assert len(result["services"]) == 1
        assert result["services"][0]["service_name"] == "web-svc"
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["subnet_id"] == "sub-1"

    def test_no_cluster_found(self):
        self.ecs.describe_clusters.return_value = {"clusters": []}
        self.ecs.get_paginator.return_value = _paginator([{"serviceArns": []}])
        # Need different paginators for services and tasks
        svc_paginator = _paginator([{"serviceArns": []}])
        task_paginator = _paginator([{"taskArns": []}])
        self.ecs.get_paginator.side_effect = lambda name: {
            "list_services": svc_paginator,
            "list_tasks": task_paginator,
        }[name]
        from agenticops.graph.collectors import collect_ecs_topology
        result = collect_ecs_topology("us-east-1", "missing")
        assert result["cluster"] == {}

    def test_complete_failure_returns_empty(self):
        self.ecs.describe_clusters.side_effect = Exception("access denied")
        from agenticops.graph.collectors import collect_ecs_topology
        result = collect_ecs_topology("us-east-1", "broken")
        assert result == {"cluster": {}, "services": [], "tasks": []}

    def test_task_without_subnet_attachment(self):
        """Task with no subnetId in attachments → empty subnet_id."""
        self.ecs.describe_clusters.return_value = {"clusters": [{"clusterName": "c1"}]}
        svc_paginator = _paginator([{"serviceArns": []}])
        task_paginator = _paginator([{"taskArns": ["arn:task:1"]}])
        self.ecs.get_paginator.side_effect = lambda name: {
            "list_services": svc_paginator,
            "list_tasks": task_paginator,
        }[name]
        self.ecs.describe_tasks.return_value = {
            "tasks": [{
                "taskArn": "arn:task:1",
                "lastStatus": "RUNNING",
                "attachments": [],
            }]
        }
        from agenticops.graph.collectors import collect_ecs_topology
        result = collect_ecs_topology("us-east-1", "c1")
        assert result["tasks"][0]["subnet_id"] == ""
