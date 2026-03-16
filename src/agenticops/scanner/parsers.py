# src/agenticops/scanner/parsers.py
"""Parse CLI JSON output into standardized resource dicts."""

import json
import logging

logger = logging.getLogger(__name__)


def _aws_tags_to_dict(tags: list | None) -> dict:
    """Convert AWS [{Key, Value}] tag list to dict."""
    if not tags:
        return {}
    return {t["Key"]: t["Value"] for t in tags if "Key" in t and "Value" in t}


def _name_from_tags(tags: list | None) -> str:
    """Extract Name tag value."""
    for t in (tags or []):
        if t.get("Key") == "Name":
            return t.get("Value", "")
    return ""


def parse_cli_output(parser_key: str, raw: str, region: str) -> list[dict]:
    """Parse CLI output using the parser for the given key.

    Returns list of standardized resource dicts:
        {resource_id, resource_type, name, region, status, tags, raw_data}
    """
    parser = _PARSERS.get(parser_key)
    if not parser:
        logger.debug("No parser for key '%s'", parser_key)
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    try:
        return parser(data, region)
    except Exception as e:
        logger.warning("Parser %s failed: %s", parser_key, e)
        return []


# ── Individual parsers ─────────────────────────────────────────────


def _parse_ec2_instances(data: dict, region: str) -> list[dict]:
    results = []
    for res in data.get("Reservations", []):
        for inst in res.get("Instances", []):
            tags = inst.get("Tags", [])
            results.append({
                "resource_id": inst["InstanceId"],
                "resource_type": "EC2",
                "name": _name_from_tags(tags),
                "region": region,
                "status": inst.get("State", {}).get("Name", "unknown"),
                "tags": _aws_tags_to_dict(tags),
                "raw_data": inst,
            })
    return results


def _parse_lambda_functions(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": f["FunctionName"],
        "resource_type": "Lambda",
        "name": f["FunctionName"],
        "region": region,
        "status": f.get("State", "unknown"),
        "tags": f.get("Tags", {}),
        "raw_data": f,
    } for f in data.get("Functions", [])]


def _parse_ecs_clusters(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": arn.rsplit("/", 1)[-1],
        "resource_type": "ECS",
        "name": arn.rsplit("/", 1)[-1],
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": {"clusterArn": arn},
    } for arn in data.get("clusterArns", [])]


def _parse_eks_clusters(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": name,
        "resource_type": "EKS",
        "name": name,
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": {},
    } for name in data.get("clusters", [])]


def _parse_rds_instances(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": db["DBInstanceIdentifier"],
        "resource_type": "RDS",
        "name": db["DBInstanceIdentifier"],
        "region": region,
        "status": db.get("DBInstanceStatus", "unknown"),
        "tags": {},
        "raw_data": db,
    } for db in data.get("DBInstances", [])]


def _parse_dynamodb_tables(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": name,
        "resource_type": "DynamoDB",
        "name": name,
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": {},
    } for name in data.get("TableNames", [])]


def _parse_elasticache(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": c["CacheClusterId"],
        "resource_type": "ElastiCache",
        "name": c["CacheClusterId"],
        "region": region,
        "status": c.get("CacheClusterStatus", "unknown"),
        "tags": {},
        "raw_data": c,
    } for c in data.get("CacheClusters", [])]


def _parse_s3_buckets(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": b["Name"],
        "resource_type": "S3",
        "name": b["Name"],
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": b,
    } for b in data.get("Buckets", [])]


def _parse_ebs_volumes(data: dict, region: str) -> list[dict]:
    results = []
    for v in data.get("Volumes", []):
        tags = v.get("Tags", [])
        results.append({
            "resource_id": v["VolumeId"],
            "resource_type": "EBS",
            "name": _name_from_tags(tags),
            "region": region,
            "status": v.get("State", "unknown"),
            "tags": _aws_tags_to_dict(tags),
            "raw_data": v,
        })
    return results


def _parse_vpcs(data: dict, region: str) -> list[dict]:
    results = []
    for vpc in data.get("Vpcs", []):
        tags = vpc.get("Tags", [])
        results.append({
            "resource_id": vpc["VpcId"],
            "resource_type": "VPC",
            "name": _name_from_tags(tags),
            "region": region,
            "status": vpc.get("State", "unknown"),
            "tags": _aws_tags_to_dict(tags),
            "raw_data": vpc,
        })
    return results


def _parse_security_groups(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": sg["GroupId"],
        "resource_type": "SecurityGroup",
        "name": sg.get("GroupName", ""),
        "region": region,
        "status": "active",
        "tags": _aws_tags_to_dict(sg.get("Tags", [])),
        "raw_data": sg,
    } for sg in data.get("SecurityGroups", [])]


def _parse_load_balancers(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": lb["LoadBalancerName"],
        "resource_type": "ELB",
        "name": lb["LoadBalancerName"],
        "region": region,
        "status": lb.get("State", {}).get("Code", "unknown"),
        "tags": {},
        "raw_data": lb,
    } for lb in data.get("LoadBalancers", [])]


def _parse_subnets(data: dict, region: str) -> list[dict]:
    results = []
    for s in data.get("Subnets", []):
        tags = s.get("Tags", [])
        results.append({
            "resource_id": s["SubnetId"],
            "resource_type": "Subnet",
            "name": _name_from_tags(tags),
            "region": region,
            "status": s.get("State", "unknown"),
            "tags": _aws_tags_to_dict(tags),
            "raw_data": s,
        })
    return results


def _parse_iam_roles(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": r["RoleName"],
        "resource_type": "IAMRole",
        "name": r["RoleName"],
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": r,
    } for r in data.get("Roles", [])]


def _parse_autoscaling_groups(data: dict, region: str) -> list[dict]:
    results = []
    for asg in data.get("AutoScalingGroups", []):
        tags = asg.get("Tags", [])
        results.append({
            "resource_id": asg["AutoScalingGroupName"],
            "resource_type": "AutoScaling",
            "name": _name_from_tags(tags),
            "region": region,
            "status": "active",
            "tags": _aws_tags_to_dict(tags),
            "raw_data": asg,
        })
    return results


def _parse_nat_gateways(data: dict, region: str) -> list[dict]:
    results = []
    for nat in data.get("NatGateways", []):
        tags = nat.get("Tags", [])
        results.append({
            "resource_id": nat["NatGatewayId"],
            "resource_type": "NATGateway",
            "name": _name_from_tags(tags),
            "region": region,
            "status": nat.get("State", "unknown"),
            "tags": _aws_tags_to_dict(tags),
            "raw_data": nat,
        })
    return results


def _parse_route53_zones(data: dict, region: str) -> list[dict]:
    results = []
    for zone in data.get("HostedZones", []):
        zone_id = zone["Id"].split("/")[-1]  # Extract Z123ABC from /hostedzone/Z123ABC
        results.append({
            "resource_id": zone_id,
            "resource_type": "Route53",
            "name": zone["Name"],
            "region": region,
            "status": "active",
            "tags": {},
            "raw_data": zone,
        })
    return results


def _parse_opensearch_domains(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": d["DomainName"],
        "resource_type": "OpenSearch",
        "name": d["DomainName"],
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": d,
    } for d in data.get("DomainNames", [])]


def _parse_efs_file_systems(data: dict, region: str) -> list[dict]:
    results = []
    for fs in data.get("FileSystems", []):
        tags = fs.get("Tags", [])
        results.append({
            "resource_id": fs["FileSystemId"],
            "resource_type": "EFS",
            "name": _name_from_tags(tags),
            "region": region,
            "status": fs.get("LifeCycleState", "unknown"),
            "tags": _aws_tags_to_dict(tags),
            "raw_data": fs,
        })
    return results


def _parse_kms_keys(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": k["KeyId"],
        "resource_type": "KMS",
        "name": k["KeyId"],
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": k,
    } for k in data.get("Keys", [])]


# ── Parser registry ───────────────────────────────────────────────

_PARSERS: dict[str, callable] = {
    "aws_ec2_instances": _parse_ec2_instances,
    "aws_lambda_functions": _parse_lambda_functions,
    "aws_ecs_clusters": _parse_ecs_clusters,
    "aws_eks_clusters": _parse_eks_clusters,
    "aws_rds_instances": _parse_rds_instances,
    "aws_dynamodb_tables": _parse_dynamodb_tables,
    "aws_elasticache": _parse_elasticache,
    "aws_s3_buckets": _parse_s3_buckets,
    "aws_ebs_volumes": _parse_ebs_volumes,
    "aws_vpcs": _parse_vpcs,
    "aws_security_groups": _parse_security_groups,
    "aws_load_balancers": _parse_load_balancers,
    "aws_subnets": _parse_subnets,
    "aws_iam_roles": _parse_iam_roles,
    "aws_autoscaling_groups": _parse_autoscaling_groups,
    "aws_nat_gateways": _parse_nat_gateways,
    "aws_route53_zones": _parse_route53_zones,
    "aws_opensearch_domains": _parse_opensearch_domains,
    "aws_efs_file_systems": _parse_efs_file_systems,
    "aws_kms_keys": _parse_kms_keys,
}
