"""AWS resource scanning tools for Strands agents.

Wraps existing core logic from scan/scanner.py and scan/services.py.
"""

import contextvars
import json
import logging
from typing import Any

from botocore.exceptions import ClientError, BotoCoreError
from strands import tool

from agenticops.scan.services import AWS_SERVICES, AWSServiceDef

logger = logging.getLogger(__name__)

# Session cache: keyed by "account_id:region" (also "web:region" from the
# dashboard paths). This is the SAME dict object as providers/base._session_cache
# — the provider layer is the single home for session caching (Phase-2 Item4),
# with one thread-safe lock and one clear_session_cache() authority. We alias it
# here so existing readers (assume_role/_get_session/web/graph) keep working.
from agenticops.providers.base import _session_cache  # noqa: E402  (shared cache)

# The account id the current agent turn is operating on (set by assume_role).
# Used so _get_session takes the session by account+region exactly — never
# region-only, which could silently return ANOTHER account's session.
_active_account_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "active_account_id", default=None
)


def _set_active_account(account_id: str | None) -> None:
    """Bind the account the current turn operates on (called by assume_role)."""
    _active_account_var.set(account_id)


def _get_active_account() -> str | None:
    return _active_account_var.get()


@tool
def assume_role(
    account_id: str, role_arn: str, region: str, external_id: str = ""
) -> str:
    """Assume an IAM role in a target AWS account and cache the session.

    Resolves credentials through the provider abstraction layer, which supports
    cross-partition roles (aws, aws-cn, aws-us-gov), named profiles, static
    keys, and the default credential chain.

    Args:
        account_id: AWS account ID
        role_arn: IAM role ARN to assume
        region: AWS region for the session
        external_id: Optional external ID for the trust policy

    Returns:
        Confirmation message with assumed role details.
    """
    cache_key = f"{account_id}:{region}"

    if cache_key in _session_cache:
        return f"Session already cached for account {account_id} in {region}."

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
        provider = get_provider(matched)
        if provider.resolve_credentials():
            session = provider.sdk_session()
            _session_cache[cache_key] = session
            _set_active_account(account_id)  # bind current-turn account context
            return f"Credentials resolved for {matched.name} ({matched.provider}) in {region}. Session cached."
        return f"Failed to resolve credentials for {matched.name}."
    except Exception as e:
        return f"Error resolving credentials: {e}"


def _get_session(region: str) -> Any:
    """Get the cached session for the CURRENT account + region.

    Fail-closed: if no account context is set, or no session is cached for that
    exact account+region, raise — NEVER fall back to another account's session
    (region-only lookup is unsafe across accounts).
    """
    account_id = _get_active_account()
    if not account_id:
        raise RuntimeError(
            "No active account context. Call assume_role first so the session "
            "is bound to a specific account (region-only lookup is unsafe across accounts)."
        )
    key = f"{account_id}:{region}"
    session = _session_cache.get(key)
    if session is None:
        raise RuntimeError(
            f"No assumed session for account {account_id} in {region}. Call assume_role first."
        )
    return session


def _get_client(service_name: str, region: str):
    """Get boto3 client from cached session."""
    session = _get_session(region)
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
    service_name: str, region: str, service_def: AWSServiceDef
) -> list[dict]:
    """Generic scan for any service using its definition."""
    client = _get_client(service_def.boto3_service, region)
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
def describe_ec2(region: str) -> str:
    """Describe all EC2 instances in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of EC2 instances with id, name, type, status, IPs.
    """
    service_def = AWS_SERVICES["EC2"]
    try:
        raw_items = _scan_service_generic("EC2", region, service_def)
        resources = []
        for reservation in raw_items:
            for instance in reservation.get("Instances", []):
                resources.append(_format_ec2_instance(instance, region))
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning EC2 in {region}: {e}"


@tool
def list_lambda_functions(region: str) -> str:
    """List all Lambda functions in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of Lambda functions with name, runtime, memory, timeout.
    """
    service_def = AWS_SERVICES["Lambda"]
    try:
        raw_items = _scan_service_generic("Lambda", region, service_def)
        resources = [_format_resource(item, service_def, region) for item in raw_items]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning Lambda in {region}: {e}"


@tool
def describe_rds(region: str) -> str:
    """Describe all RDS instances in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of RDS instances with identifier, engine, status, size.
    """
    service_def = AWS_SERVICES["RDS"]
    try:
        raw_items = _scan_service_generic("RDS", region, service_def)
        resources = [_format_resource(item, service_def, region) for item in raw_items]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning RDS in {region}: {e}"


@tool
def list_s3_buckets(region: str) -> str:
    """List all S3 buckets (S3 is global, region used for API endpoint).

    Args:
        region: AWS region for API endpoint

    Returns:
        JSON list of S3 buckets with name and creation date.
    """
    service_def = AWS_SERVICES["S3"]
    try:
        raw_items = _scan_service_generic("S3", region, service_def)
        resources = [_format_resource(item, service_def, region) for item in raw_items]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning S3 in {region}: {e}"


@tool
def describe_ecs(region: str) -> str:
    """Describe ECS clusters in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of ECS cluster ARNs.
    """
    service_def = AWS_SERVICES["ECS"]
    try:
        raw_items = _scan_service_generic("ECS", region, service_def)
        resources = [
            _format_simple_resource(item, service_def, region) for item in raw_items
        ]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning ECS in {region}: {e}"


@tool
def describe_eks(region: str) -> str:
    """Describe EKS clusters in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of EKS cluster names.
    """
    service_def = AWS_SERVICES["EKS"]
    try:
        raw_items = _scan_service_generic("EKS", region, service_def)
        resources = [
            _format_simple_resource(item, service_def, region) for item in raw_items
        ]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning EKS in {region}: {e}"


@tool
def list_dynamodb(region: str) -> str:
    """List DynamoDB tables in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of DynamoDB table names.
    """
    service_def = AWS_SERVICES["DynamoDB"]
    try:
        raw_items = _scan_service_generic("DynamoDB", region, service_def)
        resources = [
            _format_simple_resource(item, service_def, region) for item in raw_items
        ]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning DynamoDB in {region}: {e}"


@tool
def list_sqs(region: str) -> str:
    """List SQS queues in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of SQS queue URLs and names.
    """
    service_def = AWS_SERVICES["SQS"]
    try:
        raw_items = _scan_service_generic("SQS", region, service_def)
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
def list_sns(region: str) -> str:
    """List SNS topics in a region.

    Args:
        region: AWS region

    Returns:
        JSON list of SNS topic ARNs.
    """
    service_def = AWS_SERVICES["SNS"]
    try:
        raw_items = _scan_service_generic("SNS", region, service_def)
        resources = [_format_resource(item, service_def, region) for item in raw_items]
        return json.dumps(resources, default=str)
    except Exception as e:
        return f"Error scanning SNS in {region}: {e}"
