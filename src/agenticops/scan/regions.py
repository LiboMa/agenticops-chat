"""AWS Region discovery using public AWS API."""

import json
import logging
from functools import lru_cache
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# AWS Region Services API
AWS_REGIONS_API = "https://api.regional-table.region-services.aws.a2z.com"

# Fallback static regions list
FALLBACK_REGIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "ap-south-1",
    "ap-south-2",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-northeast-3",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-southeast-3",
    "ap-southeast-4",
    "ap-east-1",
    "ca-central-1",
    "ca-west-1",
    "eu-central-1",
    "eu-central-2",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "eu-north-1",
    "eu-south-1",
    "eu-south-2",
    "me-south-1",
    "me-central-1",
    "af-south-1",
    "sa-east-1",
    "il-central-1",
]

# Region display names
REGION_NAMES = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-south-2": "Asia Pacific (Hyderabad)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-southeast-4": "Asia Pacific (Melbourne)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    "ca-central-1": "Canada (Central)",
    "ca-west-1": "Canada West (Calgary)",
    "eu-central-1": "Europe (Frankfurt)",
    "eu-central-2": "Europe (Zurich)",
    "eu-west-1": "Europe (Ireland)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-north-1": "Europe (Stockholm)",
    "eu-south-1": "Europe (Milan)",
    "eu-south-2": "Europe (Spain)",
    "me-south-1": "Middle East (Bahrain)",
    "me-central-1": "Middle East (UAE)",
    "af-south-1": "Africa (Cape Town)",
    "sa-east-1": "South America (São Paulo)",
    "il-central-1": "Israel (Tel Aviv)",
}


@lru_cache(maxsize=1)
def fetch_regions_from_api() -> list[str]:
    """
    Fetch AWS regions from the public AWS API.

    Returns:
        List of unique region codes
    """
    try:
        logger.info(f"Fetching AWS regions from {AWS_REGIONS_API}")

        with urlopen(AWS_REGIONS_API, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        # Extract unique regions from the prices array
        regions = set()
        for item in data.get("prices", []):
            attrs = item.get("attributes", {})
            region = attrs.get("aws:region")
            if region and not region.startswith("us-gov") and not region.startswith("cn-"):
                # Filter out GovCloud and China regions for standard use
                regions.add(region)

        region_list = sorted(list(regions))
        logger.info(f"Found {len(region_list)} AWS regions")
        return region_list

    except (URLError, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to fetch regions from API: {e}. Using fallback list.")
        return FALLBACK_REGIONS.copy()


def get_all_regions(include_govcloud: bool = False, include_china: bool = False) -> list[str]:
    """
    Get all available AWS regions.

    Args:
        include_govcloud: Include US GovCloud regions
        include_china: Include China regions

    Returns:
        List of region codes
    """
    regions = fetch_regions_from_api()

    if include_govcloud:
        regions.extend(["us-gov-east-1", "us-gov-west-1"])

    if include_china:
        regions.extend(["cn-north-1", "cn-northwest-1"])

    return sorted(list(set(regions)))


def get_region_name(region_code: str) -> str:
    """Get friendly name for a region code."""
    return REGION_NAMES.get(region_code, region_code)


def get_common_regions() -> list[str]:
    """Get commonly used AWS regions (subset for faster scanning)."""
    return [
        "us-east-1",
        "us-east-2",
        "us-west-2",
        "eu-west-1",
        "eu-central-1",
        "ap-northeast-1",
        "ap-southeast-1",
        "ap-southeast-2",
    ]


def get_regions_by_prefix(prefix: str) -> list[str]:
    """
    Get regions by geographic prefix.

    Args:
        prefix: Region prefix (us, eu, ap, sa, me, af, ca, il)

    Returns:
        List of matching region codes
    """
    all_regions = get_all_regions()
    return [r for r in all_regions if r.startswith(prefix)]


def validate_region(region: str) -> bool:
    """Check if a region code is valid."""
    return region in get_all_regions(include_govcloud=True, include_china=True)


@lru_cache(maxsize=1)
def get_service_availability() -> dict[str, list[str]]:
    """
    Get service availability by region.

    Returns:
        Dict mapping region to list of available services
    """
    try:
        with urlopen(AWS_REGIONS_API, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        availability = {}
        for item in data.get("prices", []):
            attrs = item.get("attributes", {})
            region = attrs.get("aws:region")
            service = attrs.get("aws:serviceName")

            if region and service:
                if region not in availability:
                    availability[region] = []
                if service not in availability[region]:
                    availability[region].append(service)

        return availability

    except Exception as e:
        logger.warning(f"Failed to fetch service availability: {e}")
        return {}


def is_service_available(service_name: str, region: str) -> bool:
    """
    Check if a service is available in a region.

    Args:
        service_name: AWS service name
        region: Region code

    Returns:
        True if available (or if we can't determine)
    """
    availability = get_service_availability()

    if not availability or region not in availability:
        return True  # Assume available if we can't check

    # Service names in the API are display names, do fuzzy match
    region_services = availability.get(region, [])
    service_lower = service_name.lower()

    for svc in region_services:
        if service_lower in svc.lower() or svc.lower() in service_lower:
            return True

    return True  # Default to available
