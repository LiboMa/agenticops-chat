# tests/test_scanner_parsers.py
"""Tests for scanner CLI output parsers."""
import json
import pytest
from agenticops.scanner.parsers import parse_cli_output


class TestEC2Parser:
    def test_parse_instances(self):
        raw = json.dumps({"Reservations": [{"Instances": [{
            "InstanceId": "i-abc123",
            "InstanceType": "t3.large",
            "State": {"Name": "running"},
            "Tags": [{"Key": "Name", "Value": "web-prod"}],
            "VpcId": "vpc-123",
        }]}]})
        result = parse_cli_output("aws_ec2_instances", raw, "us-east-1")
        assert len(result) == 1
        r = result[0]
        assert r["resource_id"] == "i-abc123"
        assert r["resource_type"] == "EC2"
        assert r["name"] == "web-prod"
        assert r["status"] == "running"
        assert r["region"] == "us-east-1"
        assert r["tags"] == {"Name": "web-prod"}

    def test_parse_empty_reservations(self):
        raw = json.dumps({"Reservations": []})
        result = parse_cli_output("aws_ec2_instances", raw, "us-east-1")
        assert result == []


class TestLambdaParser:
    def test_parse_functions(self):
        raw = json.dumps({"Functions": [{
            "FunctionName": "my-func",
            "FunctionArn": "arn:aws:lambda:us-east-1:123:function:my-func",
            "Runtime": "python3.12",
            "State": "Active",
        }]})
        result = parse_cli_output("aws_lambda_functions", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-func"
        assert result[0]["resource_type"] == "Lambda"


class TestRDSParser:
    def test_parse_db_instances(self):
        raw = json.dumps({"DBInstances": [{
            "DBInstanceIdentifier": "mydb",
            "DBInstanceArn": "arn:aws:rds:us-east-1:123:db:mydb",
            "Engine": "mysql",
            "DBInstanceStatus": "available",
        }]})
        result = parse_cli_output("aws_rds_instances", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "mydb"
        assert result[0]["resource_type"] == "RDS"
        assert result[0]["status"] == "available"


class TestS3Parser:
    def test_parse_buckets(self):
        raw = json.dumps({"Buckets": [
            {"Name": "my-bucket", "CreationDate": "2024-01-01T00:00:00Z"},
        ]})
        result = parse_cli_output("aws_s3_buckets", raw, "global")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-bucket"
        assert result[0]["resource_type"] == "S3"


class TestVPCParser:
    def test_parse_vpcs(self):
        raw = json.dumps({"Vpcs": [{
            "VpcId": "vpc-123",
            "CidrBlock": "10.0.0.0/16",
            "State": "available",
            "Tags": [{"Key": "Name", "Value": "prod-vpc"}],
        }]})
        result = parse_cli_output("aws_vpcs", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "vpc-123"
        assert result[0]["resource_type"] == "VPC"


class TestSecurityGroupParser:
    def test_parse_sgs(self):
        raw = json.dumps({"SecurityGroups": [{
            "GroupId": "sg-abc",
            "GroupName": "web-sg",
            "VpcId": "vpc-123",
        }]})
        result = parse_cli_output("aws_security_groups", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "sg-abc"
        assert result[0]["resource_type"] == "SecurityGroup"


class TestELBParser:
    def test_parse_load_balancers(self):
        raw = json.dumps({"LoadBalancers": [{
            "LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-lb/abc",
            "LoadBalancerName": "my-lb",
            "State": {"Code": "active"},
            "Type": "application",
        }]})
        result = parse_cli_output("aws_load_balancers", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-lb"
        assert result[0]["resource_type"] == "ELB"


class TestDynamoDBParser:
    def test_parse_tables(self):
        raw = json.dumps({"TableNames": ["users", "orders"]})
        result = parse_cli_output("aws_dynamodb_tables", raw, "us-east-1")
        assert len(result) == 2
        assert result[0]["resource_id"] == "users"
        assert result[0]["resource_type"] == "DynamoDB"


class TestECSParser:
    def test_parse_clusters(self):
        raw = json.dumps({"clusterArns": [
            "arn:aws:ecs:us-east-1:123:cluster/my-cluster",
        ]})
        result = parse_cli_output("aws_ecs_clusters", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-cluster"
        assert result[0]["resource_type"] == "ECS"


class TestEKSParser:
    def test_parse_clusters(self):
        raw = json.dumps({"clusters": ["prod-eks", "staging-eks"]})
        result = parse_cli_output("aws_eks_clusters", raw, "us-east-1")
        assert len(result) == 2
        assert result[0]["resource_id"] == "prod-eks"
        assert result[0]["resource_type"] == "EKS"


class TestSubnetParser:
    def test_parse_subnets(self):
        raw = json.dumps({"Subnets": [{
            "SubnetId": "subnet-abc",
            "VpcId": "vpc-123",
            "CidrBlock": "10.0.1.0/24",
            "AvailabilityZone": "us-east-1a",
            "State": "available",
            "Tags": [{"Key": "Name", "Value": "pub-1a"}],
        }]})
        result = parse_cli_output("aws_subnets", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "subnet-abc"
        assert result[0]["resource_type"] == "Subnet"


class TestElastiCacheParser:
    def test_parse_clusters(self):
        raw = json.dumps({"CacheClusters": [{
            "CacheClusterId": "my-redis",
            "Engine": "redis",
            "CacheClusterStatus": "available",
        }]})
        result = parse_cli_output("aws_elasticache", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-redis"
        assert result[0]["resource_type"] == "ElastiCache"


class TestEBSParser:
    def test_parse_volumes(self):
        raw = json.dumps({"Volumes": [{
            "VolumeId": "vol-abc",
            "Size": 100,
            "State": "in-use",
            "Tags": [{"Key": "Name", "Value": "data-vol"}],
        }]})
        result = parse_cli_output("aws_ebs_volumes", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "vol-abc"
        assert result[0]["resource_type"] == "EBS"


class TestIAMParser:
    def test_parse_roles(self):
        raw = json.dumps({"Roles": [{
            "RoleName": "my-role",
            "Arn": "arn:aws:iam::123:role/my-role",
        }]})
        result = parse_cli_output("aws_iam_roles", raw, "global")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-role"
        assert result[0]["resource_type"] == "IAMRole"


class TestAutoScalingParser:
    def test_parse_auto_scaling_groups(self):
        raw = json.dumps({"AutoScalingGroups": [{
            "AutoScalingGroupName": "web-asg",
            "AutoScalingGroupARN": "arn:aws:autoscaling:us-east-1:123:autoScalingGroup:abc:autoScalingGroupName/web-asg",
            "MinSize": 2,
            "MaxSize": 10,
            "DesiredCapacity": 4,
            "HealthCheckType": "ELB",
            "Tags": [{"Key": "Name", "Value": "web-asg-prod"}],
        }]})
        result = parse_cli_output("aws_autoscaling_groups", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "web-asg"
        assert result[0]["resource_type"] == "AutoScaling"
        assert result[0]["name"] == "web-asg-prod"
        assert result[0]["status"] == "active"


class TestNATGatewayParser:
    def test_parse_nat_gateways(self):
        raw = json.dumps({"NatGateways": [{
            "NatGatewayId": "nat-abc123",
            "State": "available",
            "SubnetId": "subnet-123",
            "VpcId": "vpc-123",
            "Tags": [{"Key": "Name", "Value": "prod-nat"}],
        }]})
        result = parse_cli_output("aws_nat_gateways", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "nat-abc123"
        assert result[0]["resource_type"] == "NATGateway"
        assert result[0]["name"] == "prod-nat"
        assert result[0]["status"] == "available"


class TestRoute53Parser:
    def test_parse_hosted_zones(self):
        raw = json.dumps({"HostedZones": [{
            "Id": "/hostedzone/Z123ABC",
            "Name": "example.com.",
            "CallerReference": "abc-123",
            "Config": {"PrivateZone": False},
            "ResourceRecordSetCount": 10,
        }]})
        result = parse_cli_output("aws_route53_zones", raw, "global")
        assert len(result) == 1
        assert result[0]["resource_id"] == "Z123ABC"
        assert result[0]["resource_type"] == "Route53"
        assert result[0]["name"] == "example.com."
        assert result[0]["status"] == "active"


class TestOpenSearchParser:
    def test_parse_opensearch_domains(self):
        raw = json.dumps({"DomainNames": [
            {"DomainName": "logs-cluster"},
            {"DomainName": "analytics-cluster"},
        ]})
        result = parse_cli_output("aws_opensearch_domains", raw, "us-east-1")
        assert len(result) == 2
        assert result[0]["resource_id"] == "logs-cluster"
        assert result[0]["resource_type"] == "OpenSearch"
        assert result[0]["name"] == "logs-cluster"
        assert result[1]["resource_id"] == "analytics-cluster"


class TestEFSParser:
    def test_parse_file_systems(self):
        raw = json.dumps({"FileSystems": [{
            "FileSystemId": "fs-abc123",
            "Name": "shared-data",
            "LifeCycleState": "available",
            "SizeInBytes": {"Value": 1073741824},
            "Tags": [{"Key": "Name", "Value": "shared-data-fs"}],
        }]})
        result = parse_cli_output("aws_efs_file_systems", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "fs-abc123"
        assert result[0]["resource_type"] == "EFS"
        assert result[0]["name"] == "shared-data-fs"
        assert result[0]["status"] == "available"


class TestKMSParser:
    def test_parse_kms_keys(self):
        raw = json.dumps({"Keys": [{
            "KeyId": "abc-123-def-456",
            "KeyArn": "arn:aws:kms:us-east-1:123:key/abc-123-def-456",
        }]})
        result = parse_cli_output("aws_kms_keys", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "abc-123-def-456"
        assert result[0]["resource_type"] == "KMS"
        assert result[0]["name"] == "abc-123-def-456"
        assert result[0]["status"] == "active"


class TestUnknownParser:
    def test_unknown_key_returns_empty(self):
        result = parse_cli_output("unknown_key", "{}", "us-east-1")
        assert result == []

    def test_invalid_json_returns_empty(self):
        result = parse_cli_output("aws_ec2_instances", "not json", "us-east-1")
        assert result == []

    def test_error_output_returns_empty(self):
        result = parse_cli_output("aws_ec2_instances", "Error: access denied", "us-east-1")
        assert result == []
