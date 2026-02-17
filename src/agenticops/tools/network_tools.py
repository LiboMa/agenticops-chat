"""AWS VPC/Networking investigation tools for Strands agents.

Provides rich describe tools for VPC, Subnets, Security Groups, Route Tables,
NAT Gateways, Transit Gateways, and Load Balancers. These go beyond simple
list/describe — they extract the context RCA agents need during troubleshooting.
"""

import json
import logging
from typing import Any

from botocore.exceptions import ClientError
from strands import tool

from agenticops.tools.aws_tools import _get_session, _get_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_name_from_tags(tags: list[dict] | None) -> str | None:
    """Extract the 'Name' tag value from an AWS Tags list."""
    if not tags:
        return None
    for tag in tags:
        if tag.get("Key") == "Name":
            return tag.get("Value")
    return None


def _format_sg_rules(rules: list[dict]) -> list[dict]:
    """Format security group rules into readable dicts."""
    formatted = []
    for rule in rules:
        entry: dict[str, Any] = {
            "protocol": rule.get("IpProtocol", "all"),
        }
        from_port = rule.get("FromPort")
        to_port = rule.get("ToPort")
        if from_port is not None and to_port is not None:
            entry["ports"] = f"{from_port}-{to_port}" if from_port != to_port else str(from_port)
        else:
            entry["ports"] = "all"

        # Collect sources / destinations
        sources = []
        for ip_range in rule.get("IpRanges", []):
            src = ip_range.get("CidrIp", "")
            desc = ip_range.get("Description", "")
            sources.append(f"{src}" + (f" ({desc})" if desc else ""))
        for ip6 in rule.get("Ipv6Ranges", []):
            src = ip6.get("CidrIpv6", "")
            desc = ip6.get("Description", "")
            sources.append(f"{src}" + (f" ({desc})" if desc else ""))
        for prefix in rule.get("PrefixListIds", []):
            sources.append(f"pl:{prefix.get('PrefixListId', '')}")
        for sg_pair in rule.get("UserIdGroupPairs", []):
            sg_id = sg_pair.get("GroupId", "")
            desc = sg_pair.get("Description", "")
            sources.append(f"sg:{sg_id}" + (f" ({desc})" if desc else ""))

        entry["sources"] = sources
        formatted.append(entry)
    return formatted


def _format_routes(routes: list[dict]) -> list[dict]:
    """Format route table routes into readable dicts."""
    formatted = []
    for route in routes:
        entry: dict[str, Any] = {
            "destination": route.get("DestinationCidrBlock") or route.get("DestinationIpv6CidrBlock") or route.get("DestinationPrefixListId", ""),
            "state": route.get("State", "unknown"),
        }
        # Determine target
        for target_key in [
            "GatewayId", "NatGatewayId", "TransitGatewayId",
            "VpcPeeringConnectionId", "NetworkInterfaceId",
            "LocalGatewayId", "CarrierGatewayId",
        ]:
            val = route.get(target_key)
            if val:
                entry["target"] = val
                break
        else:
            entry["target"] = "local" if route.get("Origin") == "CreateRouteTable" else "unknown"
        entry["origin"] = route.get("Origin", "")
        formatted.append(entry)
    return formatted


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def describe_vpcs(region: str) -> str:
    """Describe all VPCs in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of VPCs with VpcId, CIDR, state, is_default, DHCP options, Name tag.
    """
    try:
        client = _get_client("ec2", region)
        paginator = client.get_paginator("describe_vpcs")
        vpcs = []
        for page in paginator.paginate():
            for vpc in page.get("Vpcs", []):
                vpcs.append({
                    "VpcId": vpc.get("VpcId"),
                    "Name": _extract_name_from_tags(vpc.get("Tags")),
                    "CidrBlock": vpc.get("CidrBlock"),
                    "State": vpc.get("State"),
                    "IsDefault": vpc.get("IsDefault", False),
                    "DhcpOptionsId": vpc.get("DhcpOptionsId"),
                    "InstanceTenancy": vpc.get("InstanceTenancy"),
                    "CidrBlockAssociations": [
                        assoc.get("CidrBlock")
                        for assoc in vpc.get("CidrBlockAssociationSet", [])
                    ],
                    "Tags": {
                        t["Key"]: t["Value"] for t in vpc.get("Tags", [])
                    },
                })
        return json.dumps(vpcs, default=str)
    except Exception as e:
        return f"Error describing VPCs in {region}: {e}"


@tool
def describe_subnets(region: str, vpc_id: str = "") -> str:
    """Describe subnets in a region, optionally filtered by VPC.

    Args:
        region: AWS region
        vpc_id: Optional VPC ID to filter subnets

    Returns:
        JSON list of subnets with SubnetId, VpcId, AZ, CIDR, available IPs, state.
    """
    try:
        client = _get_client("ec2", region)
        kwargs: dict[str, Any] = {}
        if vpc_id:
            kwargs["Filters"] = [{"Name": "vpc-id", "Values": [vpc_id]}]

        paginator = client.get_paginator("describe_subnets")
        subnets = []
        for page in paginator.paginate(**kwargs):
            for subnet in page.get("Subnets", []):
                subnets.append({
                    "SubnetId": subnet.get("SubnetId"),
                    "Name": _extract_name_from_tags(subnet.get("Tags")),
                    "VpcId": subnet.get("VpcId"),
                    "AvailabilityZone": subnet.get("AvailabilityZone"),
                    "CidrBlock": subnet.get("CidrBlock"),
                    "AvailableIpAddressCount": subnet.get("AvailableIpAddressCount"),
                    "MapPublicIpOnLaunch": subnet.get("MapPublicIpOnLaunch", False),
                    "State": subnet.get("State"),
                    "DefaultForAz": subnet.get("DefaultForAz", False),
                })
        return json.dumps(subnets, default=str)
    except Exception as e:
        return f"Error describing subnets in {region}: {e}"


@tool
def describe_security_groups(region: str, vpc_id: str = "", group_ids: str = "") -> str:
    """Describe security groups with full rule breakdown.

    Args:
        region: AWS region
        vpc_id: Optional VPC ID to filter security groups
        group_ids: Optional comma-separated security group IDs to filter

    Returns:
        JSON list of security groups with GroupId, GroupName, VpcId, inbound/outbound rules.
    """
    try:
        client = _get_client("ec2", region)
        kwargs: dict[str, Any] = {}
        filters = []
        if vpc_id:
            filters.append({"Name": "vpc-id", "Values": [vpc_id]})
        if filters:
            kwargs["Filters"] = filters
        if group_ids:
            kwargs["GroupIds"] = [gid.strip() for gid in group_ids.split(",") if gid.strip()]

        paginator = client.get_paginator("describe_security_groups")
        sgs = []
        for page in paginator.paginate(**kwargs):
            for sg in page.get("SecurityGroups", []):
                sgs.append({
                    "GroupId": sg.get("GroupId"),
                    "GroupName": sg.get("GroupName"),
                    "VpcId": sg.get("VpcId"),
                    "Description": sg.get("Description"),
                    "InboundRules": _format_sg_rules(sg.get("IpPermissions", [])),
                    "OutboundRules": _format_sg_rules(sg.get("IpPermissionsEgress", [])),
                    "InboundRuleCount": len(sg.get("IpPermissions", [])),
                    "OutboundRuleCount": len(sg.get("IpPermissionsEgress", [])),
                })
        return json.dumps(sgs, default=str)
    except Exception as e:
        return f"Error describing security groups in {region}: {e}"


@tool
def describe_route_tables(region: str, vpc_id: str = "") -> str:
    """Describe route tables with full route and association details.

    Args:
        region: AWS region
        vpc_id: Optional VPC ID to filter route tables

    Returns:
        JSON list of route tables with RouteTableId, VpcId, routes (destination, target, state),
        subnet associations. Route state (active/blackhole) is key for network troubleshooting.
    """
    try:
        client = _get_client("ec2", region)
        kwargs: dict[str, Any] = {}
        if vpc_id:
            kwargs["Filters"] = [{"Name": "vpc-id", "Values": [vpc_id]}]

        paginator = client.get_paginator("describe_route_tables")
        tables = []
        for page in paginator.paginate(**kwargs):
            for rt in page.get("RouteTables", []):
                associations = []
                for assoc in rt.get("Associations", []):
                    associations.append({
                        "RouteTableAssociationId": assoc.get("RouteTableAssociationId"),
                        "SubnetId": assoc.get("SubnetId"),
                        "Main": assoc.get("Main", False),
                    })

                tables.append({
                    "RouteTableId": rt.get("RouteTableId"),
                    "Name": _extract_name_from_tags(rt.get("Tags")),
                    "VpcId": rt.get("VpcId"),
                    "Routes": _format_routes(rt.get("Routes", [])),
                    "Associations": associations,
                })
        return json.dumps(tables, default=str)
    except Exception as e:
        return f"Error describing route tables in {region}: {e}"


@tool
def describe_nat_gateways(region: str, vpc_id: str = "") -> str:
    """Describe NAT Gateways with connectivity and elastic IP details.

    Args:
        region: AWS region
        vpc_id: Optional VPC ID to filter NAT Gateways

    Returns:
        JSON list of NAT Gateways with NatGatewayId, SubnetId, VpcId, state,
        connectivity type (public/private), elastic IP addresses.
    """
    try:
        client = _get_client("ec2", region)
        kwargs: dict[str, Any] = {}
        if vpc_id:
            kwargs["Filter"] = [{"Name": "vpc-id", "Values": [vpc_id]}]

        paginator = client.get_paginator("describe_nat_gateways")
        gateways = []
        for page in paginator.paginate(**kwargs):
            for ngw in page.get("NatGateways", []):
                addresses = []
                for addr in ngw.get("NatGatewayAddresses", []):
                    addresses.append({
                        "AllocationId": addr.get("AllocationId"),
                        "PublicIp": addr.get("PublicIp"),
                        "PrivateIp": addr.get("PrivateIp"),
                        "NetworkInterfaceId": addr.get("NetworkInterfaceId"),
                    })

                gateways.append({
                    "NatGatewayId": ngw.get("NatGatewayId"),
                    "Name": _extract_name_from_tags(ngw.get("Tags")),
                    "SubnetId": ngw.get("SubnetId"),
                    "VpcId": ngw.get("VpcId"),
                    "State": ngw.get("State"),
                    "ConnectivityType": ngw.get("ConnectivityType", "public"),
                    "Addresses": addresses,
                    "CreateTime": str(ngw.get("CreateTime", "")),
                    "FailureMessage": ngw.get("FailureMessage"),
                })
        return json.dumps(gateways, default=str)
    except Exception as e:
        return f"Error describing NAT Gateways in {region}: {e}"


@tool
def describe_transit_gateways(region: str) -> str:
    """Describe Transit Gateways with attachment details.

    Args:
        region: AWS region

    Returns:
        JSON list of Transit Gateways with TGW ID, state, ASN, and attachments
        (VPC/VPN/peering with their states). Shows full connectivity picture.
    """
    try:
        client = _get_client("ec2", region)

        # Get Transit Gateways
        tgw_response = client.describe_transit_gateways()
        tgws = tgw_response.get("TransitGateways", [])

        # Get all attachments
        attach_response = client.describe_transit_gateway_attachments()
        all_attachments = attach_response.get("TransitGatewayAttachments", [])

        # Index attachments by TGW ID
        attach_by_tgw: dict[str, list] = {}
        for att in all_attachments:
            tgw_id = att.get("TransitGatewayId", "")
            attach_by_tgw.setdefault(tgw_id, []).append({
                "AttachmentId": att.get("TransitGatewayAttachmentId"),
                "ResourceType": att.get("ResourceType"),
                "ResourceId": att.get("ResourceId"),
                "ResourceOwnerId": att.get("ResourceOwnerId"),
                "State": att.get("State"),
                "Association": att.get("Association", {}),
            })

        result = []
        for tgw in tgws:
            tgw_id = tgw.get("TransitGatewayId", "")
            options = tgw.get("Options", {})
            result.append({
                "TransitGatewayId": tgw_id,
                "Name": _extract_name_from_tags(tgw.get("Tags")),
                "State": tgw.get("State"),
                "OwnerId": tgw.get("OwnerId"),
                "AmazonSideAsn": options.get("AmazonSideAsn"),
                "AutoAcceptSharedAttachments": options.get("AutoAcceptSharedAttachments"),
                "DefaultRouteTableAssociation": options.get("DefaultRouteTableAssociation"),
                "DefaultRouteTablePropagation": options.get("DefaultRouteTablePropagation"),
                "Attachments": attach_by_tgw.get(tgw_id, []),
                "AttachmentCount": len(attach_by_tgw.get(tgw_id, [])),
            })

        return json.dumps(result, default=str)
    except Exception as e:
        return f"Error describing Transit Gateways in {region}: {e}"


@tool
def describe_load_balancers(region: str) -> str:
    """Describe Application/Network Load Balancers with target health.

    Args:
        region: AWS region

    Returns:
        JSON list of load balancers with name, type (ALB/NLB/GLB), scheme,
        VPC, AZs, state, and target health summary (healthy/unhealthy/draining
        counts per target group). Unhealthy targets are a top-3 root cause category.
    """
    try:
        client = _get_client("elbv2", region)

        # Get load balancers
        lb_paginator = client.get_paginator("describe_load_balancers")
        load_balancers = []
        for page in lb_paginator.paginate():
            load_balancers.extend(page.get("LoadBalancers", []))

        if not load_balancers:
            return json.dumps([])

        # Get all target groups
        tg_paginator = client.get_paginator("describe_target_groups")
        all_target_groups = []
        for page in tg_paginator.paginate():
            all_target_groups.extend(page.get("TargetGroups", []))

        # Index target groups by LB ARN
        tg_by_lb: dict[str, list] = {}
        for tg in all_target_groups:
            for lb_arn in tg.get("LoadBalancerArns", []):
                tg_by_lb.setdefault(lb_arn, []).append(tg)

        result = []
        for lb in load_balancers:
            lb_arn = lb.get("LoadBalancerArn", "")
            lb_state = lb.get("State", {})

            azs = [
                {
                    "ZoneName": az.get("ZoneName"),
                    "SubnetId": az.get("SubnetId"),
                }
                for az in lb.get("AvailabilityZones", [])
            ]

            # Get target health for each target group
            target_groups_info = []
            for tg in tg_by_lb.get(lb_arn, []):
                tg_arn = tg.get("TargetGroupArn", "")
                try:
                    health_resp = client.describe_target_health(TargetGroupArn=tg_arn)
                    targets = health_resp.get("TargetHealthDescriptions", [])

                    healthy = sum(1 for t in targets if t.get("TargetHealth", {}).get("State") == "healthy")
                    unhealthy = sum(1 for t in targets if t.get("TargetHealth", {}).get("State") == "unhealthy")
                    draining = sum(1 for t in targets if t.get("TargetHealth", {}).get("State") == "draining")
                    other = len(targets) - healthy - unhealthy - draining

                    target_groups_info.append({
                        "TargetGroupName": tg.get("TargetGroupName"),
                        "TargetGroupArn": tg_arn,
                        "Protocol": tg.get("Protocol"),
                        "Port": tg.get("Port"),
                        "TargetType": tg.get("TargetType"),
                        "HealthCheckPath": tg.get("HealthCheckPath"),
                        "TotalTargets": len(targets),
                        "Healthy": healthy,
                        "Unhealthy": unhealthy,
                        "Draining": draining,
                        "Other": other,
                    })
                except ClientError:
                    target_groups_info.append({
                        "TargetGroupName": tg.get("TargetGroupName"),
                        "TargetGroupArn": tg_arn,
                        "Error": "Failed to get target health",
                    })

            result.append({
                "LoadBalancerName": lb.get("LoadBalancerName"),
                "LoadBalancerArn": lb_arn,
                "Type": lb.get("Type"),
                "Scheme": lb.get("Scheme"),
                "VpcId": lb.get("VpcId"),
                "State": lb_state.get("Code") if isinstance(lb_state, dict) else str(lb_state),
                "DNSName": lb.get("DNSName"),
                "AvailabilityZones": azs,
                "SecurityGroups": lb.get("SecurityGroups", []),
                "IpAddressType": lb.get("IpAddressType"),
                "TargetGroups": target_groups_info,
            })

        return json.dumps(result, default=str)
    except Exception as e:
        return f"Error describing load balancers in {region}: {e}"
