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


def _classify_subnet_type(
    subnet_id: str,
    route_tables: list[dict],
    main_rt_id: str | None,
) -> tuple[str, str | None, str | None]:
    """Classify a subnet as public or private based on its effective route table.

    Public = effective route table has a 0.0.0.0/0 (or ::/0) route pointing to an igw-*.
    Private = everything else.

    Args:
        subnet_id: The subnet to classify.
        route_tables: Raw DescribeRouteTables response items.
        main_rt_id: The main route table ID for the VPC (fallback).

    Returns:
        (type, route_table_id, default_route_target) where type is "public" or "private".
    """
    # Find the route table explicitly associated with this subnet
    effective_rt = None
    for rt in route_tables:
        for assoc in rt.get("Associations", []):
            if assoc.get("SubnetId") == subnet_id:
                effective_rt = rt
                break
        if effective_rt:
            break

    # Fall back to the main route table
    if effective_rt is None and main_rt_id:
        for rt in route_tables:
            if rt.get("RouteTableId") == main_rt_id:
                effective_rt = rt
                break

    if effective_rt is None:
        return ("private", None, None)

    rt_id = effective_rt.get("RouteTableId")

    # Check for default route to an IGW
    for route in effective_rt.get("Routes", []):
        dest = route.get("DestinationCidrBlock") or route.get("DestinationIpv6CidrBlock", "")
        if dest in ("0.0.0.0/0", "::/0"):
            target = route.get("GatewayId", "")
            if target.startswith("igw-"):
                return ("public", rt_id, target)
            # Any other default route target (NAT, TGW, etc.) → private
            for key in ["NatGatewayId", "TransitGatewayId", "VpcPeeringConnectionId",
                        "NetworkInterfaceId", "GatewayId"]:
                val = route.get(key)
                if val:
                    return ("private", rt_id, val)
            return ("private", rt_id, "unknown")

    return ("private", rt_id, None)


def _build_sg_dependency_map(
    security_groups: list[dict],
) -> dict[str, dict[str, Any]]:
    """Build a bidirectional security-group reference graph.

    Scans inbound and outbound rules for UserIdGroupPairs to find SG-to-SG
    references.

    Args:
        security_groups: Raw DescribeSecurityGroups response items.

    Returns:
        {sg_id: {"name": str, "references": [sg_ids], "referenced_by": [sg_ids]}}
    """
    sg_map: dict[str, dict[str, Any]] = {}

    # Initialize all SGs
    for sg in security_groups:
        sg_id = sg.get("GroupId", "")
        sg_map[sg_id] = {
            "name": sg.get("GroupName", ""),
            "references": set(),
            "referenced_by": set(),
        }

    # Scan rules for references
    for sg in security_groups:
        sg_id = sg.get("GroupId", "")
        for rule_set in [sg.get("IpPermissions", []), sg.get("IpPermissionsEgress", [])]:
            for rule in rule_set:
                for pair in rule.get("UserIdGroupPairs", []):
                    ref_sg = pair.get("GroupId", "")
                    if ref_sg:
                        sg_map[sg_id]["references"].add(ref_sg)
                        if ref_sg in sg_map:
                            sg_map[ref_sg]["referenced_by"].add(sg_id)

    # Convert sets to sorted lists for JSON serialization
    for sg_id in sg_map:
        sg_map[sg_id]["references"] = sorted(sg_map[sg_id]["references"])
        sg_map[sg_id]["referenced_by"] = sorted(sg_map[sg_id]["referenced_by"])

    return sg_map


def _detect_blackhole_routes(
    route_tables: list[dict],
    rt_subnet_map: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Find routes with state='blackhole' and map them to affected subnets.

    Args:
        route_tables: Raw DescribeRouteTables response items.
        rt_subnet_map: {route_table_id: [subnet_ids]} from associations.

    Returns:
        List of {"route_table_id", "destination", "target", "affected_subnets"}.
    """
    blackholes = []
    for rt in route_tables:
        rt_id = rt.get("RouteTableId", "")
        for route in rt.get("Routes", []):
            if route.get("State") == "blackhole":
                dest = (route.get("DestinationCidrBlock")
                        or route.get("DestinationIpv6CidrBlock")
                        or route.get("DestinationPrefixListId", ""))
                # Determine target
                target = "unknown"
                for key in ["GatewayId", "NatGatewayId", "TransitGatewayId",
                            "VpcPeeringConnectionId", "NetworkInterfaceId"]:
                    val = route.get(key)
                    if val:
                        target = val
                        break
                blackholes.append({
                    "route_table_id": rt_id,
                    "destination": dest,
                    "target": target,
                    "affected_subnets": rt_subnet_map.get(rt_id, []),
                })
    return blackholes


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


@tool
def describe_region_topology(region: str) -> str:
    """Describe region-level network topology: all VPCs, Transit Gateways, and VPC Peering connections.

    Provides a high-level view of how VPCs are interconnected via TGWs and peering.

    Args:
        region: AWS region

    Returns:
        JSON object with vpcs, transit_gateways (with attachments), and peering_connections.
    """
    try:
        ec2 = _get_client("ec2", region)

        # 1. All VPCs
        vpcs = []
        paginator = ec2.get_paginator("describe_vpcs")
        for page in paginator.paginate():
            for vpc in page.get("Vpcs", []):
                vpc_id = vpc.get("VpcId", "")
                # Count subnets for this VPC
                sub_resp = ec2.describe_subnets(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                subnet_count = len(sub_resp.get("Subnets", []))
                vpcs.append({
                    "vpc_id": vpc_id,
                    "name": _extract_name_from_tags(vpc.get("Tags")),
                    "cidr_block": vpc.get("CidrBlock", ""),
                    "state": vpc.get("State", ""),
                    "is_default": vpc.get("IsDefault", False),
                    "subnet_count": subnet_count,
                })

        # 2. Transit Gateways + attachments
        transit_gateways = []
        tgw_resp = ec2.describe_transit_gateways()
        attach_resp = ec2.describe_transit_gateway_attachments()
        all_attachments = attach_resp.get("TransitGatewayAttachments", [])

        # Index attachments by TGW ID
        attach_by_tgw: dict[str, list] = {}
        for att in all_attachments:
            tgw_id = att.get("TransitGatewayId", "")
            attach_by_tgw.setdefault(tgw_id, []).append({
                "attachment_id": att.get("TransitGatewayAttachmentId"),
                "resource_type": att.get("ResourceType"),
                "resource_id": att.get("ResourceId"),
                "state": att.get("State"),
            })

        for tgw in tgw_resp.get("TransitGateways", []):
            tgw_id = tgw.get("TransitGatewayId", "")
            transit_gateways.append({
                "transit_gateway_id": tgw_id,
                "name": _extract_name_from_tags(tgw.get("Tags")),
                "state": tgw.get("State"),
                "attachments": attach_by_tgw.get(tgw_id, []),
            })

        # 3. All VPC Peering Connections in region
        peering_connections = []
        peer_resp = ec2.describe_vpc_peering_connections()
        for pcx in peer_resp.get("VpcPeeringConnections", []):
            req = pcx.get("RequesterVpcInfo", {})
            acc = pcx.get("AccepterVpcInfo", {})
            peering_connections.append({
                "pcx_id": pcx.get("VpcPeeringConnectionId"),
                "status": pcx.get("Status", {}).get("Code"),
                "requester_vpc": req.get("VpcId"),
                "requester_cidr": req.get("CidrBlock"),
                "requester_owner": req.get("OwnerId"),
                "accepter_vpc": acc.get("VpcId"),
                "accepter_cidr": acc.get("CidrBlock"),
                "accepter_owner": acc.get("OwnerId"),
            })

        result = {
            "region": region,
            "vpcs": vpcs,
            "transit_gateways": transit_gateways,
            "peering_connections": peering_connections,
        }
        return json.dumps(result, default=str)
    except Exception as e:
        return f"Error describing region topology in {region}: {e}"


@tool
def describe_tgw_peering_attachments(region: str) -> str:
    """Describe Transit Gateway peering attachments in a region.

    Returns TGW-to-TGW peering attachments that connect Transit Gateways
    across regions or accounts. These are attachment type 'peering' and are
    not included in standard TGW VPC attachment listings.

    Args:
        region: AWS region

    Returns:
        JSON list of TGW peering attachments with local/remote TGW IDs,
        state, and requester/accepter info.
    """
    try:
        ec2 = _get_client("ec2", region)
        resp = ec2.describe_transit_gateway_peering_attachments()
        attachments = []
        for att in resp.get("TransitGatewayPeeringAttachments", []):
            req = att.get("RequesterTgwInfo", {})
            acc = att.get("AccepterTgwInfo", {})
            attachments.append({
                "attachment_id": att.get("TransitGatewayAttachmentId"),
                "state": att.get("State"),
                "requester_tgw_id": req.get("TransitGatewayId"),
                "requester_region": req.get("Region"),
                "requester_owner": req.get("OwnerId"),
                "accepter_tgw_id": acc.get("TransitGatewayId"),
                "accepter_region": acc.get("Region"),
                "accepter_owner": acc.get("OwnerId"),
                "tags": {
                    t["Key"]: t["Value"] for t in att.get("Tags", [])
                },
            })
        return json.dumps(attachments, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error describing TGW peering attachments in {region}: {e}"})


@tool
def describe_cross_region_topology(regions: str = "") -> str:
    """Describe network topology across multiple AWS regions.

    Aggregates per-region topology data, cross-region VPC peering connections,
    and TGW peering attachments into a single multi-region view.

    Args:
        regions: Comma-separated region codes (e.g. 'us-east-1,eu-west-1').
                 If empty, discovers all enabled regions in the account.

    Returns:
        JSON object with per-region topologies, cross-region VPC peerings,
        and cross-region TGW peerings.
    """
    try:
        # Resolve region list
        if regions and regions.strip():
            region_list = [r.strip() for r in regions.split(",") if r.strip()]
        else:
            ec2 = _get_client("ec2", "us-east-1")
            resp = ec2.describe_regions(
                Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
            )
            region_list = [r["RegionName"] for r in resp.get("Regions", [])]

        region_topologies = []
        cross_region_peerings: list[dict] = []
        tgw_peerings: list[dict] = []
        seen_pcx: set[str] = set()
        seen_tgw_att: set[str] = set()

        for reg in region_list:
            try:
                # Per-region topology
                raw = describe_region_topology(region=reg)
                topo = json.loads(raw)
                region_topologies.append(topo)

                # Cross-region VPC peerings
                ec2 = _get_client("ec2", reg)
                peer_resp = ec2.describe_vpc_peering_connections()
                for pcx in peer_resp.get("VpcPeeringConnections", []):
                    pcx_id = pcx.get("VpcPeeringConnectionId", "")
                    if pcx_id in seen_pcx:
                        continue
                    req = pcx.get("RequesterVpcInfo", {})
                    acc = pcx.get("AccepterVpcInfo", {})
                    req_region = req.get("Region", reg)
                    acc_region = acc.get("Region", reg)
                    if req_region != acc_region:
                        seen_pcx.add(pcx_id)
                        cross_region_peerings.append({
                            "pcx_id": pcx_id,
                            "status": pcx.get("Status", {}).get("Code"),
                            "requester_vpc": req.get("VpcId"),
                            "requester_cidr": req.get("CidrBlock"),
                            "requester_region": req_region,
                            "requester_owner": req.get("OwnerId"),
                            "accepter_vpc": acc.get("VpcId"),
                            "accepter_cidr": acc.get("CidrBlock"),
                            "accepter_region": acc_region,
                            "accepter_owner": acc.get("OwnerId"),
                        })

                # TGW peering attachments
                try:
                    tgw_peer_resp = ec2.describe_transit_gateway_peering_attachments()
                    for att in tgw_peer_resp.get("TransitGatewayPeeringAttachments", []):
                        att_id = att.get("TransitGatewayAttachmentId", "")
                        if att_id in seen_tgw_att:
                            continue
                        seen_tgw_att.add(att_id)
                        req_info = att.get("RequesterTgwInfo", {})
                        acc_info = att.get("AccepterTgwInfo", {})
                        tgw_peerings.append({
                            "attachment_id": att_id,
                            "state": att.get("State"),
                            "requester_tgw_id": req_info.get("TransitGatewayId"),
                            "requester_region": req_info.get("Region"),
                            "requester_owner": req_info.get("OwnerId"),
                            "accepter_tgw_id": acc_info.get("TransitGatewayId"),
                            "accepter_region": acc_info.get("Region"),
                            "accepter_owner": acc_info.get("OwnerId"),
                        })
                except ClientError:
                    pass
            except Exception as region_err:
                logger.warning("Failed to collect topology for %s: %s", reg, region_err)

        result = {
            "regions": region_topologies,
            "cross_region_peerings": cross_region_peerings,
            "tgw_peerings": tgw_peerings,
        }
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error describing cross-region topology: {e}"})


@tool
def analyze_vpc_topology(region: str, vpc_id: str) -> str:
    """Analyze complete VPC topology: subnets, routing, gateways, peering, endpoints, and SG dependencies.

    Provides a holistic view of VPC connectivity including subnet classification
    (public/private), blackhole route detection, security group dependency mapping,
    and a reachability summary with potential issues.

    Args:
        region: AWS region
        vpc_id: VPC ID to analyze

    Returns:
        JSON object with full VPC topology: subnets (classified), route tables,
        internet/NAT/transit gateways, peering connections, VPC endpoints,
        SG dependency map, blackhole routes, and reachability summary.
    """
    try:
        ec2 = _get_client("ec2", region)

        # 1. VPC details
        vpc_resp = ec2.describe_vpcs(VpcIds=[vpc_id])
        vpcs = vpc_resp.get("Vpcs", [])
        if not vpcs:
            return json.dumps({"error": f"VPC {vpc_id} not found in {region}"})
        vpc = vpcs[0]
        vpc_name = _extract_name_from_tags(vpc.get("Tags"))
        vpc_cidr = vpc.get("CidrBlock", "")

        # 2. Internet Gateways attached to this VPC
        igw_resp = ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )
        internet_gateways = []
        for igw in igw_resp.get("InternetGateways", []):
            internet_gateways.append({
                "igw_id": igw.get("InternetGatewayId"),
                "name": _extract_name_from_tags(igw.get("Tags")),
                "attachments": [
                    {"vpc_id": a.get("VpcId"), "state": a.get("State")}
                    for a in igw.get("Attachments", [])
                ],
            })

        # 3. VPC Peering Connections (requester or accepter)
        peering_connections = []
        for filter_name in ["requester-vpc-info.vpc-id", "accepter-vpc-info.vpc-id"]:
            peer_resp = ec2.describe_vpc_peering_connections(
                Filters=[{"Name": filter_name, "Values": [vpc_id]}]
            )
            for pcx in peer_resp.get("VpcPeeringConnections", []):
                pcx_id = pcx.get("VpcPeeringConnectionId")
                if not any(p["pcx_id"] == pcx_id for p in peering_connections):
                    req = pcx.get("RequesterVpcInfo", {})
                    acc = pcx.get("AccepterVpcInfo", {})
                    peering_connections.append({
                        "pcx_id": pcx_id,
                        "status": pcx.get("Status", {}).get("Code"),
                        "requester_vpc": req.get("VpcId"),
                        "requester_cidr": req.get("CidrBlock"),
                        "requester_owner": req.get("OwnerId"),
                        "accepter_vpc": acc.get("VpcId"),
                        "accepter_cidr": acc.get("CidrBlock"),
                        "accepter_owner": acc.get("OwnerId"),
                    })

        # 4. VPC Endpoints
        vpce_resp = ec2.describe_vpc_endpoints(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        vpc_endpoints = []
        for ep in vpce_resp.get("VpcEndpoints", []):
            vpc_endpoints.append({
                "endpoint_id": ep.get("VpcEndpointId"),
                "service_name": ep.get("ServiceName"),
                "type": ep.get("VpcEndpointType"),
                "state": ep.get("State"),
                "route_table_ids": ep.get("RouteTableIds", []),
                "subnet_ids": ep.get("SubnetIds", []),
            })

        # 5. Subnets
        subnet_resp = ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        raw_subnets = subnet_resp.get("Subnets", [])

        # 6. Route Tables
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

        # Build rt → subnet map
        rt_subnet_map: dict[str, list[str]] = {}
        for rt in raw_route_tables:
            rt_id = rt.get("RouteTableId", "")
            for assoc in rt.get("Associations", []):
                sid = assoc.get("SubnetId")
                if sid:
                    rt_subnet_map.setdefault(rt_id, []).append(sid)

        # Classify subnets
        subnets = []
        public_count = 0
        private_count = 0
        issues: list[str] = []
        for s in raw_subnets:
            sid = s.get("SubnetId", "")
            stype, rt_id, default_target = _classify_subnet_type(
                sid, raw_route_tables, main_rt_id
            )
            if stype == "public":
                public_count += 1
            else:
                private_count += 1
                # Check for isolated subnets (private with no default route at all)
                if default_target is None:
                    issues.append(
                        f"Subnet {sid} has no route to 0.0.0.0/0 (isolated)"
                    )
            subnets.append({
                "subnet_id": sid,
                "name": _extract_name_from_tags(s.get("Tags")),
                "az": s.get("AvailabilityZone"),
                "cidr": s.get("CidrBlock"),
                "type": stype,
                "available_ips": s.get("AvailableIpAddressCount"),
                "route_table_id": rt_id,
                "default_route_target": default_target,
            })

        # Format route tables
        route_tables_out = []
        for rt in raw_route_tables:
            rt_id = rt.get("RouteTableId", "")
            is_main = any(
                a.get("Main", False) for a in rt.get("Associations", [])
            )
            route_tables_out.append({
                "route_table_id": rt_id,
                "name": _extract_name_from_tags(rt.get("Tags")),
                "associated_subnets": rt_subnet_map.get(rt_id, []),
                "is_main": is_main,
                "routes": _format_routes(rt.get("Routes", [])),
            })

        # 7. NAT Gateways
        ngw_resp = ec2.describe_nat_gateways(
            Filter=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        nat_gateways = []
        for ngw in ngw_resp.get("NatGateways", []):
            if ngw.get("State") in ("deleted", "deleting"):
                continue
            nat_gateways.append({
                "nat_gateway_id": ngw.get("NatGatewayId"),
                "name": _extract_name_from_tags(ngw.get("Tags")),
                "subnet_id": ngw.get("SubnetId"),
                "state": ngw.get("State"),
                "connectivity_type": ngw.get("ConnectivityType", "public"),
                "az": None,  # filled below
            })
        # Enrich NAT GW with AZ from subnet data
        subnet_az_map = {s.get("SubnetId"): s.get("AvailabilityZone") for s in raw_subnets}
        for ngw in nat_gateways:
            ngw["az"] = subnet_az_map.get(ngw["subnet_id"])

        # 8. Transit Gateway Attachments for this VPC
        try:
            tgw_resp = ec2.describe_transit_gateway_attachments(
                Filters=[{"Name": "resource-id", "Values": [vpc_id]}]
            )
            tgw_attachments = []
            for att in tgw_resp.get("TransitGatewayAttachments", []):
                tgw_attachments.append({
                    "attachment_id": att.get("TransitGatewayAttachmentId"),
                    "transit_gateway_id": att.get("TransitGatewayId"),
                    "resource_type": att.get("ResourceType"),
                    "state": att.get("State"),
                })
        except ClientError:
            tgw_attachments = []

        # 9. Security Groups
        sg_resp = ec2.describe_security_groups(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        raw_sgs = sg_resp.get("SecurityGroups", [])
        sg_dep_map = _build_sg_dependency_map(raw_sgs)

        # 10. Blackhole routes
        blackhole_routes = _detect_blackhole_routes(raw_route_tables, rt_subnet_map)
        if blackhole_routes:
            for bh in blackhole_routes:
                issues.append(
                    f"Blackhole route in {bh['route_table_id']}: "
                    f"{bh['destination']} → {bh['target']}"
                )

        # Reachability summary
        reachability = {
            "has_internet_gateway": len(internet_gateways) > 0,
            "public_subnet_count": public_count,
            "private_subnet_count": private_count,
            "nat_gateway_count": len(nat_gateways),
            "transit_gateway_attachments": len(tgw_attachments),
            "vpc_peering_count": len(peering_connections),
            "vpc_endpoint_count": len(vpc_endpoints),
            "blackhole_route_count": len(blackhole_routes),
            "issues": issues,
        }

        result = {
            "vpc_id": vpc_id,
            "vpc_name": vpc_name,
            "vpc_cidr": vpc_cidr,
            "region": region,
            "internet_gateways": internet_gateways,
            "vpc_peering_connections": peering_connections,
            "vpc_endpoints": vpc_endpoints,
            "subnets": subnets,
            "route_tables": route_tables_out,
            "nat_gateways": nat_gateways,
            "transit_gateway_attachments": tgw_attachments,
            "security_group_dependency_map": sg_dep_map,
            "blackhole_routes": blackhole_routes,
            "reachability_summary": reachability,
        }

        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error analyzing VPC topology for {vpc_id} in {region}: {e}"})
