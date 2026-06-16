"""AWS resource scanning tools for Strands agents.

Wraps existing core logic from scan/scanner.py and scan/services.py.
"""

import json
import logging
from typing import Any

from botocore.exceptions import ClientError, BotoCoreError
from strands import tool

from agenticops.scan.services import AWS_SERVICES, AWSServiceDef
from agenticops.credentials.resolver import (
    AccountResolutionError,
    resolve_account_session,
    resolve_default_account,
)

logger = logging.getLogger(__name__)

# Session cache is owned by providers/base (single thread-safe home). We alias
# it here so existing readers (web/graph) that imported it keep working.
from agenticops.providers.base import _session_cache  # noqa: E402  (shared cache)


@tool
def assume_role(
    account_id: str, role_arn: str, region: str, external_id: str = ""
) -> str:
    """Pre-warm and cache credentials for a registered AWS account.

    Resolves credentials through the provider abstraction layer (cross-partition
    roles, named profiles, static keys, or the environment chain). Tools are
    account-addressed — you do NOT need to call this before every operation:
    pass account='<name>' to a tool, or omit it for single-account deployments.
    Use this only to validate/pre-warm an account's credentials.

    Args:
        account_id: AWS account ID
        role_arn: IAM role ARN to assume
        region: AWS region for the session
        external_id: Optional external ID for the trust policy

    Returns:
        Confirmation message with the resolved account identity.
    """
    from agenticops.providers import get_provider
    from agenticops.models import CloudAccount, get_db_session
    from types import SimpleNamespace

    matched = None
    try:
        with get_db_session() as db:
            accounts = db.query(CloudAccount).filter_by(is_enabled=True).all()
            for acct in accounts:
                creds = acct.credentials or {}
                if creds.get("role_arn") == role_arn or str(creds.get("account_id")) == account_id:
                    matched = SimpleNamespace(
                        id=acct.id, name=acct.name, provider=acct.provider,
                        credentials=dict(creds), regions=list(acct.regions or []),
                        labels=dict(acct.labels or {}),
                    )
                    break
    except Exception as e:
        return f"Error looking up account: {e}"

    if not matched:
        return f"No enabled account found matching role_arn={role_arn} or account_id={account_id}."

    try:
        resolve_account_session(matched, region)
    except AccountResolutionError as e:
        return f"Failed to resolve credentials for {matched.name}: {e}"
    except Exception as e:
        return f"Error resolving credentials: {e}"

    return (
        f"Credentials resolved for {matched.name} (account {account_id}, "
        f"{matched.provider}) in {region}. Tools are account-addressed: pass "
        f"account='{matched.name}' to target it, or omit account — single-account "
        f"deployments and inventory-matched hosts/clusters resolve automatically."
    )


def _get_session(region: str, account: str = "") -> Any:
    """Resolve a boto3 session for an explicit account, or the default account.

    Fail-closed: with an explicit account that can't resolve, or zero/ambiguous
    enabled accounts when none is given, raises AccountResolutionError — NEVER
    falls back to ambient credentials.
    """
    if account:
        return resolve_account_session(account, region)
    return resolve_account_session(resolve_default_account(), region)


def _get_client(service_name: str, region: str, account: str = ""):
    """Get a boto3 client from the resolved account session."""
    session = _get_session(region, account)
    return session.client(service_name, region_name=region)


def _extract_items(response: dict, list_key: str) -> list:
    """Extract items from response using dot-notation key."""
    data = response
    for key in list_key.split("."):
        if isinstance(data, dict):
            data = data.get(key, [])
        else:
            return []
    return data if isinstance(data, list) else []


def _format_ec2_instance(instance: dict, region: str) -> dict:
    """Format EC2 instance data."""
    name = None
    for tag in instance.get("Tags", []):
        if tag.get("Key") == "Name":
            name = tag.get("Value")
            break

    return {
        "resource_id": instance.get("InstanceId"),
        "resource_name": name,
        "resource_type": "EC2",
        "region": region,
        "status": instance.get("State", {}).get("Name", "unknown"),
        "metadata": {
            "instance_type": instance.get("InstanceType"),
            "launch_time": str(instance.get("LaunchTime", "")),
            "private_ip": instance.get("PrivateIpAddress"),
            "public_ip": instance.get("PublicIpAddress"),
            "vpc_id": instance.get("VpcId"),
            "subnet_id": instance.get("SubnetId"),
        },
        "tags": {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])},
    }


def _scan_service_generic(
    service_name: str, region: str, service_def: AWSServiceDef, account: str = ""
) -> list[dict]:
    """Generic scan for any service using its definition."""
    client = _get_client(service_def.boto3_service, region, account)
    resources = []

    try:
        if client.can_paginate(service_def.list_method):
            paginator = client.get_paginator(service_def.list_method)
            for page in paginator.paginate():
                items = _extract_items(page, service_def.list_key)
                resources.extend(items)
        else:
            method = getattr(client, service_def.list_method)
            response = method()
            items = _extract_items(response, service_def.list_key)
            resources.extend(items)
    except ClientError as e:
        raise RuntimeError(f"AWS error scanning {service_name} in {region}: {e}")

    return resources


def _format_resource(item: dict, service_def: AWSServiceDef, region: str) -> dict:
    """Format a generic resource."""
    resource_id = item.get(service_def.id_field)
    resource_name = (
        item.get(service_def.name_field) if service_def.name_field else resource_id
    )
    resource_arn = item.get(service_def.arn_field) if service_def.arn_field else None

    status = "unknown"
    if service_def.status_field:
        status_data = item
        for key in service_def.status_field.split("."):
            if isinstance(status_data, dict):
                status_data = status_data.get(key)
            else:
                status_data = None
                break
        if status_data:
            status = str(status_data)

    # Extract metadata (skip large fields)
    metadata = {}
    skip_fields = {
        "Tags",
        service_def.id_field,
        service_def.name_field,
        service_def.arn_field,
    }
    for key, value in item.items():
        if key in skip_fields:
            continue
        if isinstance(value, (dict, list)) and len(str(value)) > 1000:
            continue
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        metadata[key] = value

    return {
        "resource_id": resource_id,
        "resource_arn": resource_arn,
        "resource_name": resource_name,
        "resource_type": service_def.name,
        "region": region,
        "status": status,
        "metadata": metadata,
        "tags": item.get("Tags", {}),
    }


def _format_simple_resource(item: Any, service_def: AWSServiceDef, region: str) -> dict:
    """Format simple resource (just ID/name/ARN)."""
    resource_id = item if isinstance(item, str) else str(item)
    return {
        "resource_id": resource_id,
        "resource_arn": resource_id if resource_id.startswith("arn:") else None,
        "resource_name": (
            resource_id.split("/")[-1] if "/" in resource_id else resource_id
        ),
        "resource_type": service_def.name,
        "region": region,
        "status": "unknown",
        "metadata": {},
        "tags": {},
    }


@tool
def describe_ec2(region: str, account: str = "") -> str:
    """Describe all EC2 instances in a region.

    Args:
        region: AWS region
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of EC2 instances with id, name, type, status, IPs.
    """
    service_def = AWS_SERVICES["EC2"]
    try:
        raw_items = _scan_service_generic("EC2", region, service_def, account)
        resources = []
        for reservation in raw_items:
            for instance in reservation.get("Instances", []):
                resources.append(_format_ec2_instance(instance, region))
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning EC2 in {region}: {e}"


@tool
def list_lambda_functions(region: str, account: str = "") -> str:
    """List all Lambda functions in a region.

    Args:
        region: AWS region
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of Lambda functions with name, runtime, memory, timeout.
    """
    service_def = AWS_SERVICES["Lambda"]
    try:
        raw_items = _scan_service_generic("Lambda", region, service_def, account)
        resources = [_format_resource(item, service_def, region) for item in raw_items]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning Lambda in {region}: {e}"


@tool
def describe_rds(region: str, account: str = "") -> str:
    """Describe all RDS instances in a region.

    Args:
        region: AWS region
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of RDS instances with identifier, engine, status, size.
    """
    service_def = AWS_SERVICES["RDS"]
    try:
        raw_items = _scan_service_generic("RDS", region, service_def, account)
        resources = [_format_resource(item, service_def, region) for item in raw_items]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning RDS in {region}: {e}"


@tool
def list_s3_buckets(region: str, account: str = "") -> str:
    """List all S3 buckets (S3 is global, region used for API endpoint).

    Args:
        region: AWS region for API endpoint
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of S3 buckets with name and creation date.
    """
    service_def = AWS_SERVICES["S3"]
    try:
        raw_items = _scan_service_generic("S3", region, service_def, account)
        resources = [_format_resource(item, service_def, region) for item in raw_items]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning S3 in {region}: {e}"


@tool
def describe_ecs(region: str, account: str = "") -> str:
    """Describe ECS clusters in a region.

    Args:
        region: AWS region
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of ECS cluster ARNs.
    """
    service_def = AWS_SERVICES["ECS"]
    try:
        raw_items = _scan_service_generic("ECS", region, service_def, account)
        resources = [
            _format_simple_resource(item, service_def, region) for item in raw_items
        ]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning ECS in {region}: {e}"


@tool
def describe_eks(region: str, account: str = "") -> str:
    """Describe EKS clusters in a region.

    Args:
        region: AWS region
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of EKS cluster names.
    """
    service_def = AWS_SERVICES["EKS"]
    try:
        raw_items = _scan_service_generic("EKS", region, service_def, account)
        resources = [
            _format_simple_resource(item, service_def, region) for item in raw_items
        ]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning EKS in {region}: {e}"


@tool
def list_dynamodb(region: str, account: str = "") -> str:
    """List DynamoDB tables in a region.

    Args:
        region: AWS region
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of DynamoDB table names.
    """
    service_def = AWS_SERVICES["DynamoDB"]
    try:
        raw_items = _scan_service_generic("DynamoDB", region, service_def, account)
        resources = [
            _format_simple_resource(item, service_def, region) for item in raw_items
        ]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning DynamoDB in {region}: {e}"


@tool
def list_sqs(region: str, account: str = "") -> str:
    """List SQS queues in a region.

    Args:
        region: AWS region
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of SQS queue URLs and names.
    """
    service_def = AWS_SERVICES["SQS"]
    try:
        raw_items = _scan_service_generic("SQS", region, service_def, account)
        resources = []
        for queue_url in raw_items:
            queue_name = queue_url.split("/")[-1] if isinstance(queue_url, str) else str(queue_url)
            resources.append({
                "resource_id": queue_url,
                "resource_name": queue_name,
                "resource_type": "SQS",
                "region": region,
                "status": "available",
                "metadata": {"queue_url": queue_url},
                "tags": {},
            })
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning SQS in {region}: {e}"


@tool
def list_sns(region: str, account: str = "") -> str:
    """List SNS topics in a region.

    Args:
        region: AWS region
        account: Registered account name. Omit for single-account deployments.

    Returns:
        JSON list of SNS topic ARNs.
    """
    service_def = AWS_SERVICES["SNS"]
    try:
        raw_items = _scan_service_generic("SNS", region, service_def, account)
        resources = [_format_resource(item, service_def, region) for item in raw_items]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning SNS in {region}: {e}"
