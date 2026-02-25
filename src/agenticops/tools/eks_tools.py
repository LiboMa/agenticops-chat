"""AWS EKS networking tools for Strands agents.

Provides detailed EKS cluster description, nodegroup inspection,
pod IP capacity analysis, and EKS-to-VPC topology mapping.
"""

import json
import logging
from typing import Any

from strands import tool

from agenticops.tools.aws_tools import _get_client
from agenticops.tools.network_tools import (
    _extract_name_from_tags,
    _classify_subnet_type,
    _format_routes,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ENI limits per instance type: (max_enis, ipv4_per_eni)
# Source: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-eni.html
# Covers common EKS node types; unknown types fall back to describe_instance_types.
# ---------------------------------------------------------------------------

ENI_LIMITS: dict[str, tuple[int, int]] = {
    # t3 family
    "t3.nano": (2, 2),
    "t3.micro": (2, 2),
    "t3.small": (3, 4),
    "t3.medium": (3, 6),
    "t3.large": (3, 12),
    "t3.xlarge": (4, 15),
    "t3.2xlarge": (4, 15),
    # m5 family
    "m5.large": (3, 10),
    "m5.xlarge": (4, 15),
    "m5.2xlarge": (4, 15),
    "m5.4xlarge": (8, 30),
    "m5.8xlarge": (8, 30),
    "m5.12xlarge": (8, 30),
    "m5.16xlarge": (15, 50),
    "m5.24xlarge": (15, 50),
    # m6i family
    "m6i.large": (3, 10),
    "m6i.xlarge": (4, 15),
    "m6i.2xlarge": (4, 15),
    "m6i.4xlarge": (8, 30),
    "m6i.8xlarge": (8, 30),
    "m6i.12xlarge": (8, 30),
    "m6i.16xlarge": (15, 50),
    "m6i.24xlarge": (15, 50),
    # m7g family (Graviton3)
    "m7g.medium": (2, 4),
    "m7g.large": (3, 10),
    "m7g.xlarge": (4, 15),
    "m7g.2xlarge": (4, 15),
    "m7g.4xlarge": (8, 30),
    "m7g.8xlarge": (8, 30),
    "m7g.12xlarge": (8, 30),
    "m7g.16xlarge": (15, 50),
    # c5 family
    "c5.large": (3, 10),
    "c5.xlarge": (4, 15),
    "c5.2xlarge": (4, 15),
    "c5.4xlarge": (8, 30),
    "c5.9xlarge": (8, 30),
    "c5.12xlarge": (8, 30),
    "c5.18xlarge": (15, 50),
    "c5.24xlarge": (15, 50),
    # c6i family
    "c6i.large": (3, 10),
    "c6i.xlarge": (4, 15),
    "c6i.2xlarge": (4, 15),
    "c6i.4xlarge": (8, 30),
    "c6i.8xlarge": (8, 30),
    "c6i.12xlarge": (8, 30),
    "c6i.16xlarge": (15, 50),
    "c6i.24xlarge": (15, 50),
    # r5 family
    "r5.large": (3, 10),
    "r5.xlarge": (4, 15),
    "r5.2xlarge": (4, 15),
    "r5.4xlarge": (8, 30),
    "r5.8xlarge": (8, 30),
    "r5.12xlarge": (8, 30),
    "r5.16xlarge": (15, 50),
    "r5.24xlarge": (15, 50),
    # r6i family
    "r6i.large": (3, 10),
    "r6i.xlarge": (4, 15),
    "r6i.2xlarge": (4, 15),
    "r6i.4xlarge": (8, 30),
    "r6i.8xlarge": (8, 30),
    "r6i.12xlarge": (8, 30),
    "r6i.16xlarge": (15, 50),
    "r6i.24xlarge": (15, 50),
}


def _get_eni_limits(instance_type: str, ec2_client) -> tuple[int, int]:
    """Get (max_enis, ipv4_per_eni) for an instance type.

    Uses the static ENI_LIMITS table first; falls back to
    ec2.describe_instance_types() for unknown types.
    """
    if instance_type in ENI_LIMITS:
        return ENI_LIMITS[instance_type]

    try:
        resp = ec2_client.describe_instance_types(InstanceTypes=[instance_type])
        info = resp.get("InstanceTypes", [{}])[0]
        net = info.get("NetworkInfo", {})
        max_enis = net.get("MaximumNetworkInterfaces", 2)
        ipv4_per = net.get("Ipv4AddressesPerInterface", 2)
        return (max_enis, ipv4_per)
    except Exception:
        logger.warning("Could not look up ENI limits for %s, using defaults", instance_type)
        return (2, 2)


def _calc_max_pods(max_enis: int, ipv4_per_eni: int) -> int:
    """Calculate max pods per node using the AWS VPC CNI formula.

    max_pods = (max_enis * (ipv4_per_eni - 1)) + 2
    """
    return (max_enis * (ipv4_per_eni - 1)) + 2


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def describe_eks_clusters(region: str) -> str:
    """Describe all EKS clusters in a region with full configuration details.

    Enhanced replacement for the basic describe_eks tool. Returns VPC config,
    endpoint access, k8s network config, logging, and tags for each cluster.

    Args:
        region: AWS region

    Returns:
        JSON list of EKS clusters with name, version, status, VPC config,
        network config, logging, and tags.
    """
    try:
        eks = _get_client("eks", region)
        cluster_names = []
        paginator = eks.get_paginator("list_clusters")
        for page in paginator.paginate():
            cluster_names.extend(page.get("clusters", []))

        if not cluster_names:
            return json.dumps([])

        clusters = []
        for name in cluster_names:
            resp = eks.describe_cluster(name=name)
            c = resp.get("cluster", {})
            vpc_config = c.get("resourcesVpcConfig", {})
            k8s_net = c.get("kubernetesNetworkConfig", {})
            logging_config = c.get("logging", {})

            # Extract enabled log types
            enabled_logs = []
            for log_setup in logging_config.get("clusterLogging", []):
                if log_setup.get("enabled"):
                    enabled_logs.extend(log_setup.get("types", []))

            clusters.append({
                "name": c.get("name"),
                "version": c.get("version"),
                "status": c.get("status"),
                "platform_version": c.get("platformVersion"),
                "vpc_config": {
                    "vpc_id": vpc_config.get("vpcId"),
                    "subnet_ids": vpc_config.get("subnetIds", []),
                    "security_group_ids": vpc_config.get("securityGroupIds", []),
                    "cluster_security_group_id": vpc_config.get("clusterSecurityGroupId"),
                    "endpoint_public_access": vpc_config.get("endpointPublicAccess"),
                    "endpoint_private_access": vpc_config.get("endpointPrivateAccess"),
                    "public_access_cidrs": vpc_config.get("publicAccessCidrs", []),
                },
                "kubernetes_network_config": {
                    "service_ipv4_cidr": k8s_net.get("serviceIpv4Cidr"),
                    "ip_family": k8s_net.get("ipFamily"),
                },
                "enabled_logging": enabled_logs,
                "endpoint": c.get("endpoint"),
                "role_arn": c.get("roleArn"),
                "created_at": str(c.get("createdAt", "")),
                "tags": c.get("tags", {}),
            })

        return json.dumps(clusters, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error describing EKS clusters in {region}: {e}"})


@tool
def describe_eks_nodegroups(region: str, cluster_name: str) -> str:
    """Describe all managed node groups for an EKS cluster.

    Returns instance types, capacity type (ON_DEMAND/SPOT), scaling config,
    subnets, health issues, labels, and taints for each node group.

    Args:
        region: AWS region
        cluster_name: EKS cluster name

    Returns:
        JSON list of node groups with configuration and health details.
    """
    try:
        eks = _get_client("eks", region)
        ng_names = []
        paginator = eks.get_paginator("list_nodegroups")
        for page in paginator.paginate(clusterName=cluster_name):
            ng_names.extend(page.get("nodegroups", []))

        if not ng_names:
            return json.dumps([])

        nodegroups = []
        for ng_name in ng_names:
            resp = eks.describe_nodegroup(
                clusterName=cluster_name,
                nodegroupName=ng_name,
            )
            ng = resp.get("nodegroup", {})
            scaling = ng.get("scalingConfig", {})
            health = ng.get("health", {})

            health_issues = []
            for issue in health.get("issues", []):
                health_issues.append({
                    "code": issue.get("code"),
                    "message": issue.get("message"),
                    "resource_ids": issue.get("resourceIds", []),
                })

            nodegroups.append({
                "nodegroup_name": ng.get("nodegroupName"),
                "status": ng.get("status"),
                "instance_types": ng.get("instanceTypes", []),
                "ami_type": ng.get("amiType"),
                "capacity_type": ng.get("capacityType", "ON_DEMAND"),
                "scaling_config": {
                    "min_size": scaling.get("minSize"),
                    "max_size": scaling.get("maxSize"),
                    "desired_size": scaling.get("desiredSize"),
                },
                "subnets": ng.get("subnets", []),
                "disk_size": ng.get("diskSize"),
                "labels": ng.get("labels", {}),
                "taints": [
                    {"key": t.get("key"), "value": t.get("value"), "effect": t.get("effect")}
                    for t in ng.get("taints", [])
                ],
                "health_issues": health_issues,
                "release_version": ng.get("releaseVersion"),
                "tags": ng.get("tags", {}),
            })

        return json.dumps(nodegroups, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error describing nodegroups for {cluster_name} in {region}: {e}"})


@tool
def check_eks_pod_ip_capacity(region: str, cluster_name: str) -> str:
    """Check pod IP capacity for an EKS cluster's node groups.

    Calculates max pods per node using the AWS VPC CNI formula:
    max_pods = (max_enis * (ipv4_per_eni - 1)) + 2

    Cross-references with subnet available IP addresses to warn on
    subnets approaching IP exhaustion (>80% utilized).

    Args:
        region: AWS region
        cluster_name: EKS cluster name

    Returns:
        JSON with per-nodegroup pod capacity, subnet IP availability,
        total cluster capacity, and warnings.
    """
    try:
        eks = _get_client("eks", region)
        ec2 = _get_client("ec2", region)

        # Get cluster subnets
        cluster_resp = eks.describe_cluster(name=cluster_name)
        cluster = cluster_resp.get("cluster", {})
        cluster_subnets = cluster.get("resourcesVpcConfig", {}).get("subnetIds", [])

        # Get nodegroups
        ng_names = []
        paginator = eks.get_paginator("list_nodegroups")
        for page in paginator.paginate(clusterName=cluster_name):
            ng_names.extend(page.get("nodegroups", []))

        nodegroups_out = []
        all_subnet_ids: set[str] = set(cluster_subnets)
        total_pod_capacity = 0
        warnings: list[str] = []

        for ng_name in ng_names:
            ng_resp = eks.describe_nodegroup(
                clusterName=cluster_name,
                nodegroupName=ng_name,
            )
            ng = ng_resp.get("nodegroup", {})
            instance_types = ng.get("instanceTypes", [])
            scaling = ng.get("scalingConfig", {})
            desired = scaling.get("desiredSize", 0)
            ng_subnets = ng.get("subnets", [])
            all_subnet_ids.update(ng_subnets)

            # Calculate max pods for each instance type
            max_pods_per_type = {}
            for it in instance_types:
                max_enis, ipv4_per = _get_eni_limits(it, ec2)
                max_pods_per_type[it] = _calc_max_pods(max_enis, ipv4_per)

            # Use the first instance type's limit for capacity estimate
            max_pods = max_pods_per_type.get(instance_types[0], 17) if instance_types else 17
            ng_capacity = max_pods * desired
            total_pod_capacity += ng_capacity

            nodegroups_out.append({
                "nodegroup_name": ng_name,
                "instance_types": instance_types,
                "desired_size": desired,
                "max_pods_per_node": max_pods_per_type,
                "total_pod_capacity": ng_capacity,
                "subnets": ng_subnets,
            })

        # Get subnet IP availability
        subnet_availability = []
        if all_subnet_ids:
            sub_resp = ec2.describe_subnets(SubnetIds=list(all_subnet_ids))
            for s in sub_resp.get("Subnets", []):
                cidr = s.get("CidrBlock", "")
                # Calculate total IPs from CIDR (rough: 2^(32-prefix) - 5 for AWS reserved)
                try:
                    prefix = int(cidr.split("/")[1])
                    total_ips = (2 ** (32 - prefix)) - 5
                except (IndexError, ValueError):
                    total_ips = 0
                available = s.get("AvailableIpAddressCount", 0)
                used = total_ips - available if total_ips > 0 else 0
                util_pct = round((used / total_ips) * 100, 1) if total_ips > 0 else 0.0

                subnet_availability.append({
                    "subnet_id": s.get("SubnetId"),
                    "az": s.get("AvailabilityZone"),
                    "cidr": cidr,
                    "total_ips": total_ips,
                    "available_ips": available,
                    "utilization_pct": util_pct,
                })

                if util_pct > 80:
                    warnings.append(
                        f"Subnet {s.get('SubnetId')} has only {available} IPs "
                        f"available ({util_pct}% utilized)"
                    )

        result = {
            "cluster_name": cluster_name,
            "nodegroups": nodegroups_out,
            "subnet_ip_availability": subnet_availability,
            "total_cluster_pod_capacity": total_pod_capacity,
            "warnings": warnings,
        }

        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error checking pod IP capacity for {cluster_name} in {region}: {e}"})


@tool
def map_eks_to_vpc_topology(region: str, cluster_name: str) -> str:
    """Map an EKS cluster's networking to its underlying VPC topology.

    Bridges EKS to VPC: cluster → VPC → node subnets → route tables → NAT/IGW.
    Finds load balancers in the same VPC (potential LB Controller targets).
    Detects topology issues like missing NAT gateways for private subnets.

    Args:
        region: AWS region
        cluster_name: EKS cluster name

    Returns:
        JSON with cluster VPC mapping, subnet routing, NAT/IGW coverage,
        load balancers in VPC, and detected topology issues.
    """
    try:
        eks = _get_client("eks", region)
        ec2 = _get_client("ec2", region)

        # Get cluster details
        cluster_resp = eks.describe_cluster(name=cluster_name)
        cluster = cluster_resp.get("cluster", {})
        vpc_config = cluster.get("resourcesVpcConfig", {})
        vpc_id = vpc_config.get("vpcId")

        if not vpc_id:
            return json.dumps({"error": f"Cluster {cluster_name} has no VPC configured"})

        cluster_subnet_ids = vpc_config.get("subnetIds", [])

        # Get nodegroup subnets
        ng_names = []
        paginator = eks.get_paginator("list_nodegroups")
        for page in paginator.paginate(clusterName=cluster_name):
            ng_names.extend(page.get("nodegroups", []))

        node_subnet_ids: set[str] = set()
        for ng_name in ng_names:
            ng_resp = eks.describe_nodegroup(
                clusterName=cluster_name, nodegroupName=ng_name
            )
            ng = ng_resp.get("nodegroup", {})
            node_subnet_ids.update(ng.get("subnets", []))

        all_subnet_ids = set(cluster_subnet_ids) | node_subnet_ids

        # Get VPC subnets
        subnet_resp = ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        raw_subnets = subnet_resp.get("Subnets", [])
        subnet_by_id = {s.get("SubnetId"): s for s in raw_subnets}

        # Get route tables
        rt_resp = ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        raw_route_tables = rt_resp.get("RouteTables", [])

        # Find main route table
        main_rt_id = None
        for rt in raw_route_tables:
            for assoc in rt.get("Associations", []):
                if assoc.get("Main", False):
                    main_rt_id = rt.get("RouteTableId")
                    break
            if main_rt_id:
                break

        # Get NAT Gateways
        ngw_resp = ec2.describe_nat_gateways(
            Filter=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        nat_gateways = [
            ngw for ngw in ngw_resp.get("NatGateways", [])
            if ngw.get("State") not in ("deleted", "deleting")
        ]

        # Get IGWs
        igw_resp = ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )
        igws = igw_resp.get("InternetGateways", [])

        # Classify cluster/node subnets
        issues: list[str] = []
        subnet_details = []
        subnet_azs: set[str] = set()
        private_subnet_azs: set[str] = set()

        for sid in sorted(all_subnet_ids):
            s = subnet_by_id.get(sid, {})
            stype, rt_id, default_target = _classify_subnet_type(
                sid, raw_route_tables, main_rt_id
            )
            az = s.get("AvailabilityZone", "")
            subnet_azs.add(az)
            if stype == "private":
                private_subnet_azs.add(az)

            subnet_details.append({
                "subnet_id": sid,
                "name": _extract_name_from_tags(s.get("Tags")),
                "az": az,
                "cidr": s.get("CidrBlock"),
                "type": stype,
                "available_ips": s.get("AvailableIpAddressCount"),
                "route_table_id": rt_id,
                "default_route_target": default_target,
                "is_cluster_subnet": sid in cluster_subnet_ids,
                "is_node_subnet": sid in node_subnet_ids,
            })

        # Check NAT GW AZ coverage for private subnets
        nat_azs: set[str] = set()
        for ngw in nat_gateways:
            ngw_subnet = ngw.get("SubnetId", "")
            ngw_az = subnet_by_id.get(ngw_subnet, {}).get("AvailabilityZone", "")
            if ngw_az:
                nat_azs.add(ngw_az)

        if private_subnet_azs and nat_azs and not private_subnet_azs.issubset(nat_azs):
            missing_azs = private_subnet_azs - nat_azs
            issues.append(
                f"Private subnets span AZs {sorted(private_subnet_azs)} "
                f"but NAT Gateway only in AZs {sorted(nat_azs)} "
                f"(missing: {sorted(missing_azs)})"
            )

        # Find LBs in the same VPC
        try:
            elbv2 = _get_client("elbv2", region)
            lb_paginator = elbv2.get_paginator("describe_load_balancers")
            vpc_lbs = []
            for page in lb_paginator.paginate():
                for lb in page.get("LoadBalancers", []):
                    if lb.get("VpcId") == vpc_id:
                        vpc_lbs.append({
                            "name": lb.get("LoadBalancerName"),
                            "type": lb.get("Type"),
                            "scheme": lb.get("Scheme"),
                            "dns_name": lb.get("DNSName"),
                            "state": lb.get("State", {}).get("Code") if isinstance(lb.get("State"), dict) else str(lb.get("State", "")),
                            "availability_zones": [
                                az.get("ZoneName")
                                for az in lb.get("AvailabilityZones", [])
                            ],
                        })
        except Exception:
            vpc_lbs = []

        result = {
            "cluster_name": cluster_name,
            "vpc_id": vpc_id,
            "endpoint_public_access": vpc_config.get("endpointPublicAccess"),
            "endpoint_private_access": vpc_config.get("endpointPrivateAccess"),
            "cluster_security_group": vpc_config.get("clusterSecurityGroupId"),
            "subnet_topology": subnet_details,
            "nat_gateways": [
                {
                    "nat_gateway_id": ngw.get("NatGatewayId"),
                    "subnet_id": ngw.get("SubnetId"),
                    "az": subnet_by_id.get(ngw.get("SubnetId", ""), {}).get("AvailabilityZone"),
                    "state": ngw.get("State"),
                }
                for ngw in nat_gateways
            ],
            "internet_gateways": [
                igw.get("InternetGatewayId") for igw in igws
            ],
            "load_balancers_in_vpc": vpc_lbs,
            "topology_issues": issues,
        }

        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error mapping EKS to VPC topology for {cluster_name} in {region}: {e}"})
