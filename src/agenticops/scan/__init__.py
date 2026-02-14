"""SCAN Module - AWS Resource Scanning."""

from agenticops.scan.scanner import AWSScanner, ScanResult
from agenticops.scan.services import get_supported_services
from agenticops.scan.regions import (
    get_all_regions,
    get_common_regions,
    get_region_name,
    validate_region,
)

__all__ = [
    "AWSScanner",
    "ScanResult",
    "get_supported_services",
    "get_all_regions",
    "get_common_regions",
    "get_region_name",
    "validate_region",
]
