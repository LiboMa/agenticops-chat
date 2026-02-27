"""AWS data collectors for graph enrichment.

Bridges AWS APIs to plain dicts, decoupling the graph engine from boto3.
Uses the same session/client infrastructure as aws_tools.py.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_client(service_name: str, region: str):
    """Get a boto3 client via the shared session cache."""
    from agenticops.tools.aws_tools import _get_client as _aws_get_client
    return _aws_get_client(service_name, region)


def collect_vpc_compute(region: str, vpc_id: str) -> dict[str, Any]:
    """Collect compute/service resources within a VPC.

    Returns:
        Dict with keys: ec2_instances, rds_instances, lambda_functions,
        target_groups, elasticache_clusters.
    """
    result: dict[str, Any] = {
        "ec2_instances": [],
        "rds_instances": [],
        "lambda_functions": [],
        "target_groups": [],
        "elasticache_clusters": [],
    }

    # EC2 instances in the VPC
    try:
        ec2 = _get_client("ec2", region)
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ):
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    name = ""
                    for tag in inst.get("Tags", []):
                        if tag["Key"] == "Name":
                            name = tag["Value"]
                            break
                    result["ec2_instances"].append({
                        "instance_id": inst["InstanceId"],
                        "name": name,
                        "instance_type": inst.get("InstanceType", ""),
                        "state": inst.get("State", {}).get("Name", "unknown"),
                        "subnet_id": inst.get("SubnetId", ""),
                        "private_ip": inst.get("PrivateIpAddress", ""),
                        "public_ip": inst.get("PublicIpAddress"),
                        "security_group_ids": [
                            sg["GroupId"] for sg in inst.get("SecurityGroups", [])
                        ],
                    })
    except Exception as e:
        logger.warning("Failed to collect EC2 instances: %s", e)

    # RDS instances in the VPC
    try:
        rds = _get_client("rds", region)
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                db_vpc = db.get("DBSubnetGroup", {}).get("VpcId", "")
                if db_vpc != vpc_id:
                    continue
                subnet_ids = [
                    s["SubnetIdentifier"]
                    for s in db.get("DBSubnetGroup", {}).get("Subnets", [])
                ]
                result["rds_instances"].append({
                    "db_instance_id": db["DBInstanceIdentifier"],
                    "engine": db.get("Engine", ""),
                    "engine_version": db.get("EngineVersion", ""),
                    "instance_class": db.get("DBInstanceClass", ""),
                    "status": db.get("DBInstanceStatus", "unknown"),
                    "subnet_ids": subnet_ids,
                    "security_group_ids": [
                        sg["VpcSecurityGroupId"]
                        for sg in db.get("VpcSecurityGroups", [])
                    ],
                    "multi_az": db.get("MultiAZ", False),
                    "endpoint": db.get("Endpoint", {}).get("Address", ""),
                    "port": db.get("Endpoint", {}).get("Port"),
                })
    except Exception as e:
        logger.warning("Failed to collect RDS instances: %s", e)

    # Lambda functions in the VPC
    try:
        lam = _get_client("lambda", region)
        paginator = lam.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                vpc_config = fn.get("VpcConfig", {})
                fn_vpc_id = vpc_config.get("VpcId", "")
                if fn_vpc_id != vpc_id:
                    continue
                result["lambda_functions"].append({
                    "function_name": fn["FunctionName"],
                    "runtime": fn.get("Runtime", ""),
                    "memory_size": fn.get("MemorySize", 0),
                    "timeout": fn.get("Timeout", 0),
                    "state": fn.get("State", "Active"),
                    "subnet_ids": vpc_config.get("SubnetIds", []),
                    "security_group_ids": vpc_config.get("SecurityGroupIds", []),
                })
    except Exception as e:
        logger.warning("Failed to collect Lambda functions: %s", e)

    # ELBv2 Target Groups
    try:
        elbv2 = _get_client("elbv2", region)
        paginator = elbv2.get_paginator("describe_target_groups")
        for page in paginator.paginate():
            for tg in page.get("TargetGroups", []):
                if tg.get("VpcId", "") != vpc_id:
                    continue
                tg_arn = tg["TargetGroupArn"]
                # Get registered targets
                targets = []
                try:
                    health = elbv2.describe_target_health(TargetGroupArn=tg_arn)
                    for desc in health.get("TargetHealthDescriptions", []):
                        targets.append({
                            "id": desc["Target"]["Id"],
                            "port": desc["Target"].get("Port"),
                            "health_state": desc.get("TargetHealth", {}).get("State", "unknown"),
                        })
                except Exception:
                    pass
                result["target_groups"].append({
                    "target_group_arn": tg_arn,
                    "target_group_name": tg.get("TargetGroupName", ""),
                    "protocol": tg.get("Protocol", ""),
                    "port": tg.get("Port"),
                    "target_type": tg.get("TargetType", ""),
                    "load_balancer_arns": tg.get("LoadBalancerArns", []),
                    "targets": targets,
                })
    except Exception as e:
        logger.warning("Failed to collect target groups: %s", e)

    # ElastiCache clusters in the VPC
    try:
        ec_client = _get_client("elasticache", region)
        paginator = ec_client.get_paginator("describe_cache_clusters")
        for page in paginator.paginate(ShowCacheNodeInfo=True):
            for cluster in page.get("CacheClusters", []):
                cache_subnet_group = cluster.get("CacheSubnetGroupName", "")
                if not cache_subnet_group:
                    continue
                # Resolve subnet group to check VPC
                try:
                    sg_resp = ec_client.describe_cache_subnet_groups(
                        CacheSubnetGroupName=cache_subnet_group
                    )
                    groups = sg_resp.get("CacheSubnetGroups", [])
                    if not groups or groups[0].get("VpcId", "") != vpc_id:
                        continue
                    subnet_ids = [
                        s["SubnetIdentifier"]
                        for s in groups[0].get("Subnets", [])
                    ]
                except Exception:
                    continue

                result["elasticache_clusters"].append({
                    "cache_cluster_id": cluster["CacheClusterId"],
                    "engine": cluster.get("Engine", ""),
                    "engine_version": cluster.get("EngineVersion", ""),
                    "cache_node_type": cluster.get("CacheNodeType", ""),
                    "status": cluster.get("CacheClusterStatus", "unknown"),
                    "num_cache_nodes": cluster.get("NumCacheNodes", 0),
                    "subnet_ids": subnet_ids,
                    "security_group_ids": [
                        sg["SecurityGroupId"]
                        for sg in cluster.get("SecurityGroups", [])
                    ],
                })
    except Exception as e:
        logger.warning("Failed to collect ElastiCache clusters: %s", e)

    return result


def collect_eks_topology(region: str, cluster_name: str) -> dict[str, Any]:
    """Collect EKS cluster and nodegroup topology.

    Returns:
        Dict with keys: cluster, nodegroups.
    """
    result: dict[str, Any] = {"cluster": {}, "nodegroups": []}

    try:
        eks = _get_client("eks", region)

        # Cluster info
        cluster_resp = eks.describe_cluster(name=cluster_name)
        cluster = cluster_resp.get("cluster", {})
        result["cluster"] = {
            "name": cluster.get("name", cluster_name),
            "status": cluster.get("status", "unknown"),
            "version": cluster.get("version", ""),
            "subnet_ids": cluster.get("resourcesVpcConfig", {}).get("subnetIds", []),
            "security_group_ids": [
                cluster.get("resourcesVpcConfig", {}).get("clusterSecurityGroupId", ""),
            ],
            "vpc_id": cluster.get("resourcesVpcConfig", {}).get("vpcId", ""),
            "endpoint": cluster.get("endpoint", ""),
        }
        # Remove empty string from security groups
        result["cluster"]["security_group_ids"] = [
            sg for sg in result["cluster"]["security_group_ids"] if sg
        ]

        # Nodegroups
        ng_list = eks.list_nodegroups(clusterName=cluster_name)
        for ng_name in ng_list.get("nodegroups", []):
            try:
                ng_resp = eks.describe_nodegroup(
                    clusterName=cluster_name, nodegroupName=ng_name
                )
                ng = ng_resp.get("nodegroup", {})
                result["nodegroups"].append({
                    "nodegroup_name": ng.get("nodegroupName", ng_name),
                    "status": ng.get("status", "unknown"),
                    "instance_types": ng.get("instanceTypes", []),
                    "subnet_ids": ng.get("subnets", []),
                    "desired_size": ng.get("scalingConfig", {}).get("desiredSize", 0),
                    "min_size": ng.get("scalingConfig", {}).get("minSize", 0),
                    "max_size": ng.get("scalingConfig", {}).get("maxSize", 0),
                    "current_size": ng.get("scalingConfig", {}).get("desiredSize", 0),
                    "max_pods": ng.get("health", {}).get("maxPods", 110),
                })
            except Exception as e:
                logger.warning("Failed to describe nodegroup %s: %s", ng_name, e)

    except Exception as e:
        logger.warning("Failed to collect EKS topology for %s: %s", cluster_name, e)

    return result


def collect_ecs_topology(region: str, cluster_name: str) -> dict[str, Any]:
    """Collect ECS cluster, services, and tasks topology.

    Returns:
        Dict with keys: cluster, services, tasks.
    """
    result: dict[str, Any] = {"cluster": {}, "services": [], "tasks": []}

    try:
        ecs = _get_client("ecs", region)

        # Cluster info
        clusters_resp = ecs.describe_clusters(clusters=[cluster_name])
        clusters = clusters_resp.get("clusters", [])
        if clusters:
            c = clusters[0]
            result["cluster"] = {
                "cluster_name": c.get("clusterName", cluster_name),
                "cluster_arn": c.get("clusterArn", ""),
                "status": c.get("status", "unknown"),
                "running_tasks_count": c.get("runningTasksCount", 0),
                "active_services_count": c.get("activeServicesCount", 0),
            }

        # Services
        svc_arns = []
        paginator = ecs.get_paginator("list_services")
        for page in paginator.paginate(cluster=cluster_name):
            svc_arns.extend(page.get("serviceArns", []))

        if svc_arns:
            # describe_services takes max 10 at a time
            for i in range(0, len(svc_arns), 10):
                batch = svc_arns[i:i + 10]
                svc_resp = ecs.describe_services(
                    cluster=cluster_name, services=batch
                )
                for svc in svc_resp.get("services", []):
                    net_config = svc.get("networkConfiguration", {}).get(
                        "awsvpcConfiguration", {}
                    )
                    result["services"].append({
                        "service_name": svc.get("serviceName", ""),
                        "service_arn": svc.get("serviceArn", ""),
                        "status": svc.get("status", "unknown"),
                        "desired_count": svc.get("desiredCount", 0),
                        "running_count": svc.get("runningCount", 0),
                        "launch_type": svc.get("launchType", ""),
                        "subnet_ids": net_config.get("subnets", []),
                        "security_group_ids": net_config.get("securityGroups", []),
                    })

        # Tasks
        task_arns = []
        paginator = ecs.get_paginator("list_tasks")
        for page in paginator.paginate(cluster=cluster_name):
            task_arns.extend(page.get("taskArns", []))

        if task_arns:
            # describe_tasks takes max 100 at a time
            for i in range(0, len(task_arns), 100):
                batch = task_arns[i:i + 100]
                task_resp = ecs.describe_tasks(cluster=cluster_name, tasks=batch)
                for task in task_resp.get("tasks", []):
                    attachments = task.get("attachments", [])
                    subnet_id = ""
                    for att in attachments:
                        for detail in att.get("details", []):
                            if detail.get("name") == "subnetId":
                                subnet_id = detail.get("value", "")
                    result["tasks"].append({
                        "task_arn": task.get("taskArn", ""),
                        "task_definition_arn": task.get("taskDefinitionArn", ""),
                        "last_status": task.get("lastStatus", "unknown"),
                        "desired_status": task.get("desiredStatus", ""),
                        "launch_type": task.get("launchType", ""),
                        "container_instance_arn": task.get("containerInstanceArn", ""),
                        "subnet_id": subnet_id,
                        "group": task.get("group", ""),
                    })

    except Exception as e:
        logger.warning("Failed to collect ECS topology for %s: %s", cluster_name, e)

    return result
