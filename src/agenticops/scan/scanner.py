"""AWS Resource Scanner - Core scanning functionality."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError

from agenticops.models import AWSAccount, AWSResource, get_session
from agenticops.scan.services import AWS_SERVICES, AWSServiceDef, get_all_regions

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result of a resource scan."""

    account_id: str
    region: str
    service: str
    resources: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    scanned_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.resources)


class AWSScanner:
    """Scanner for AWS resources with cross-account support."""

    def __init__(self, account: AWSAccount):
        """Initialize scanner with AWS account configuration."""
        self.account = account
        self._session_cache: dict[str, boto3.Session] = {}

    def _get_assumed_session(self, region: str) -> boto3.Session:
        """Get boto3 session with assumed role for the account."""
        cache_key = f"{self.account.account_id}:{region}"

        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        sts = boto3.client("sts", region_name=region)

        assume_kwargs = {
            "RoleArn": self.account.role_arn,
            "RoleSessionName": f"AgenticOps-{self.account.account_id}",
            "DurationSeconds": 3600,
        }
        if self.account.external_id:
            assume_kwargs["ExternalId"] = self.account.external_id

        try:
            response = sts.assume_role(**assume_kwargs)
            credentials = response["Credentials"]

            session = boto3.Session(
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
                region_name=region,
            )
            self._session_cache[cache_key] = session
            return session

        except ClientError as e:
            logger.error(f"Failed to assume role {self.account.role_arn}: {e}")
            raise

    def _get_client(self, service_name: str, region: str):
        """Get boto3 client for a service."""
        session = self._get_assumed_session(region)
        return session.client(service_name)

    def scan_service(self, service_name: str, region: str) -> ScanResult:
        """Scan a specific AWS service in a region."""
        result = ScanResult(
            account_id=self.account.account_id,
            region=region,
            service=service_name,
        )

        service_def = AWS_SERVICES.get(service_name)
        if not service_def:
            result.error = f"Unknown service: {service_name}"
            return result

        try:
            client = self._get_client(service_def.boto3_service, region)
            resources = self._list_resources(client, service_def, region)
            result.resources = resources
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            result.error = f"AWS Error ({error_code}): {e.response.get('Error', {}).get('Message', str(e))}"
            logger.warning(f"Error scanning {service_name} in {region}: {result.error}")
        except BotoCoreError as e:
            result.error = f"BotoCore Error: {str(e)}"
            logger.warning(f"Error scanning {service_name} in {region}: {result.error}")
        except Exception as e:
            result.error = f"Unexpected Error: {str(e)}"
            logger.exception(f"Unexpected error scanning {service_name} in {region}")

        return result

    def _list_resources(
        self, client, service_def: AWSServiceDef, region: str
    ) -> list[dict]:
        """List resources for a service using its definition."""
        resources = []
        paginator_name = service_def.list_method

        # Handle pagination if available
        if client.can_paginate(paginator_name):
            paginator = client.get_paginator(paginator_name)
            for page in paginator.paginate():
                items = self._extract_items(page, service_def.list_key)
                resources.extend(self._process_items(items, service_def, region))
        else:
            # Single call
            method = getattr(client, service_def.list_method)
            response = method()
            items = self._extract_items(response, service_def.list_key)
            resources.extend(self._process_items(items, service_def, region))

        return resources

    def _extract_items(self, response: dict, list_key: str) -> list:
        """Extract items from response using dot-notation key."""
        data = response
        for key in list_key.split("."):
            if isinstance(data, dict):
                data = data.get(key, [])
            else:
                return []
        return data if isinstance(data, list) else []

    def _process_items(
        self, items: list, service_def: AWSServiceDef, region: str
    ) -> list[dict]:
        """Process raw items into standardized resource format."""
        resources = []

        # Special handling for EC2 (nested in Reservations)
        if service_def.name == "EC2":
            for reservation in items:
                for instance in reservation.get("Instances", []):
                    resources.append(self._format_ec2_instance(instance, region))
        # Special handling for services that return just IDs/names/ARNs
        elif service_def.name in ["ECS", "EKS", "DynamoDB", "Kinesis"]:
            for item in items:
                resources.append(self._format_simple_resource(item, service_def, region))
        elif service_def.name == "SQS":
            for queue_url in items:
                resources.append(self._format_sqs_queue(queue_url, region))
        else:
            for item in items:
                resources.append(self._format_resource(item, service_def, region))

        return resources

    def _format_ec2_instance(self, instance: dict, region: str) -> dict:
        """Format EC2 instance data."""
        # Extract name from tags
        name = None
        for tag in instance.get("Tags", []):
            if tag.get("Key") == "Name":
                name = tag.get("Value")
                break

        return {
            "resource_id": instance.get("InstanceId"),
            "resource_arn": f"arn:aws:ec2:{region}:{self.account.account_id}:instance/{instance.get('InstanceId')}",
            "resource_name": name,
            "resource_type": "EC2",
            "region": region,
            "status": instance.get("State", {}).get("Name", "unknown"),
            "metadata": {
                "instance_type": instance.get("InstanceType"),
                "launch_time": str(instance.get("LaunchTime")),
                "private_ip": instance.get("PrivateIpAddress"),
                "public_ip": instance.get("PublicIpAddress"),
                "vpc_id": instance.get("VpcId"),
                "subnet_id": instance.get("SubnetId"),
                "availability_zone": instance.get("Placement", {}).get("AvailabilityZone"),
            },
            "tags": {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])},
        }

    def _format_resource(self, item: dict, service_def: AWSServiceDef, region: str) -> dict:
        """Format a generic resource."""
        resource_id = item.get(service_def.id_field)
        resource_name = item.get(service_def.name_field) if service_def.name_field else resource_id
        resource_arn = item.get(service_def.arn_field) if service_def.arn_field else None

        # Extract status using dot notation
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

        return {
            "resource_id": resource_id,
            "resource_arn": resource_arn,
            "resource_name": resource_name,
            "resource_type": service_def.name,
            "region": region,
            "status": status,
            "metadata": self._extract_metadata(item, service_def),
            "tags": item.get("Tags", {}),
        }

    def _format_simple_resource(
        self, item: Any, service_def: AWSServiceDef, region: str
    ) -> dict:
        """Format simple resource (just ID/name/ARN)."""
        if isinstance(item, str):
            resource_id = item
        else:
            resource_id = str(item)

        return {
            "resource_id": resource_id,
            "resource_arn": resource_id if resource_id.startswith("arn:") else None,
            "resource_name": resource_id.split("/")[-1] if "/" in resource_id else resource_id,
            "resource_type": service_def.name,
            "region": region,
            "status": "unknown",
            "metadata": {},
            "tags": {},
        }

    def _format_sqs_queue(self, queue_url: str, region: str) -> dict:
        """Format SQS queue resource."""
        queue_name = queue_url.split("/")[-1]
        return {
            "resource_id": queue_url,
            "resource_arn": None,
            "resource_name": queue_name,
            "resource_type": "SQS",
            "region": region,
            "status": "available",
            "metadata": {"queue_url": queue_url},
            "tags": {},
        }

    def _extract_metadata(self, item: dict, service_def: AWSServiceDef) -> dict:
        """Extract service-specific metadata."""
        # Remove common fields and large nested objects
        skip_fields = {"Tags", service_def.id_field, service_def.name_field, service_def.arn_field}
        metadata = {}

        for key, value in item.items():
            if key in skip_fields:
                continue
            # Skip large nested objects
            if isinstance(value, (dict, list)) and len(str(value)) > 1000:
                continue
            # Convert datetime to string
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            metadata[key] = value

        return metadata

    def scan_all_services(
        self, regions: Optional[list[str]] = None, services: Optional[list[str]] = None
    ) -> list[ScanResult]:
        """Scan all services across all regions."""
        if regions is None:
            regions = self.account.regions or get_all_regions()
        if services is None:
            services = list(AWS_SERVICES.keys())

        results = []
        total = len(regions) * len(services)
        count = 0

        for region in regions:
            for service in services:
                count += 1
                logger.info(f"[{count}/{total}] Scanning {service} in {region}...")
                result = self.scan_service(service, region)
                results.append(result)
                if result.success:
                    logger.info(f"  Found {result.count} resources")
                else:
                    logger.warning(f"  Error: {result.error}")

        return results

    def save_results(self, results: list[ScanResult]) -> int:
        """Save scan results to database."""
        session = get_session()
        saved_count = 0

        try:
            for result in results:
                if not result.success:
                    continue

                for resource_data in result.resources:
                    # Check if resource already exists
                    existing = (
                        session.query(AWSResource)
                        .filter_by(
                            account_id=self.account.id,
                            resource_id=resource_data["resource_id"],
                            region=result.region,
                        )
                        .first()
                    )

                    if existing:
                        # Update existing
                        existing.resource_name = resource_data.get("resource_name")
                        existing.resource_arn = resource_data.get("resource_arn")
                        existing.status = resource_data.get("status", "unknown")
                        existing.resource_metadata = resource_data.get("metadata", {})
                        existing.tags = resource_data.get("tags", {})
                    else:
                        # Create new
                        resource = AWSResource(
                            account_id=self.account.id,
                            resource_id=resource_data["resource_id"],
                            resource_arn=resource_data.get("resource_arn"),
                            resource_type=resource_data["resource_type"],
                            resource_name=resource_data.get("resource_name"),
                            region=result.region,
                            status=resource_data.get("status", "unknown"),
                            resource_metadata=resource_data.get("metadata", {}),
                            tags=resource_data.get("tags", {}),
                        )
                        session.add(resource)
                        saved_count += 1

            # Update account last_scanned_at
            self.account.last_scanned_at = datetime.utcnow()
            session.commit()

        except Exception as e:
            session.rollback()
            logger.exception("Failed to save scan results")
            raise
        finally:
            session.close()

        return saved_count
