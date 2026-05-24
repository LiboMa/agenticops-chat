"""Tests for agenticops.scan.regions — AWS region discovery."""

import json
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    """Clear lru_cache before each test to avoid cross-test pollution."""
    from agenticops.scan.regions import fetch_regions_from_api, get_service_availability
    fetch_regions_from_api.cache_clear()
    get_service_availability.cache_clear()
    yield
    fetch_regions_from_api.cache_clear()
    get_service_availability.cache_clear()


# ── FALLBACK_REGIONS / REGION_NAMES constants ─────────────────────────

class TestConstants:
    def test_fallback_regions_not_empty(self):
        from agenticops.scan.regions import FALLBACK_REGIONS
        assert len(FALLBACK_REGIONS) > 20

    def test_fallback_no_govcloud_or_china(self):
        from agenticops.scan.regions import FALLBACK_REGIONS
        for r in FALLBACK_REGIONS:
            assert not r.startswith("us-gov")
            assert not r.startswith("cn-")

    def test_region_names_covers_fallback(self):
        from agenticops.scan.regions import FALLBACK_REGIONS, REGION_NAMES
        for r in FALLBACK_REGIONS:
            assert r in REGION_NAMES, f"Missing display name for {r}"


# ── fetch_regions_from_api ────────────────────────────────────────────

class TestFetchRegionsFromApi:
    def _make_api_response(self, regions):
        prices = [{"attributes": {"aws:region": r}} for r in regions]
        return json.dumps({"prices": prices}).encode()

    @patch("agenticops.scan.regions.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = self._make_api_response(["us-east-1", "eu-west-1"])
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from agenticops.scan.regions import fetch_regions_from_api
        result = fetch_regions_from_api()
        assert "us-east-1" in result
        assert "eu-west-1" in result

    @patch("agenticops.scan.regions.urlopen")
    def test_filters_govcloud_and_china(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = self._make_api_response(
            ["us-east-1", "us-gov-west-1", "cn-north-1"]
        )
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from agenticops.scan.regions import fetch_regions_from_api
        result = fetch_regions_from_api()
        assert "us-east-1" in result
        assert "us-gov-west-1" not in result
        assert "cn-north-1" not in result

    @patch("agenticops.scan.regions.urlopen")
    def test_fallback_on_network_error(self, mock_urlopen):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("timeout")

        from agenticops.scan.regions import fetch_regions_from_api, FALLBACK_REGIONS
        result = fetch_regions_from_api()
        assert result == FALLBACK_REGIONS

    @patch("agenticops.scan.regions.urlopen")
    def test_fallback_on_bad_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from agenticops.scan.regions import fetch_regions_from_api, FALLBACK_REGIONS
        result = fetch_regions_from_api()
        assert result == FALLBACK_REGIONS


# ── get_all_regions ───────────────────────────────────────────────────

class TestGetAllRegions:
    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_default(self, mock_fetch):
        mock_fetch.return_value = ["us-east-1", "eu-west-1"]
        from agenticops.scan.regions import get_all_regions
        result = get_all_regions()
        assert "us-east-1" in result
        assert "us-gov-east-1" not in result

    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_include_govcloud(self, mock_fetch):
        mock_fetch.return_value = ["us-east-1"]
        from agenticops.scan.regions import get_all_regions
        result = get_all_regions(include_govcloud=True)
        assert "us-gov-east-1" in result
        assert "us-gov-west-1" in result

    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_include_china(self, mock_fetch):
        mock_fetch.return_value = ["us-east-1"]
        from agenticops.scan.regions import get_all_regions
        result = get_all_regions(include_china=True)
        assert "cn-north-1" in result
        assert "cn-northwest-1" in result

    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_sorted_and_unique(self, mock_fetch):
        mock_fetch.return_value = ["us-west-2", "us-east-1", "us-east-1"]
        from agenticops.scan.regions import get_all_regions
        result = get_all_regions()
        assert result == sorted(set(result))


# ── get_region_name ───────────────────────────────────────────────────

class TestGetRegionName:
    def test_known_region(self):
        from agenticops.scan.regions import get_region_name
        assert get_region_name("us-east-1") == "US East (N. Virginia)"

    def test_unknown_region_returns_code(self):
        from agenticops.scan.regions import get_region_name
        assert get_region_name("xx-unknown-1") == "xx-unknown-1"


# ── get_common_regions ────────────────────────────────────────────────

class TestGetCommonRegions:
    def test_returns_subset(self):
        from agenticops.scan.regions import get_common_regions
        common = get_common_regions()
        assert len(common) > 0
        assert "us-east-1" in common

    def test_all_valid(self):
        from agenticops.scan.regions import get_common_regions, FALLBACK_REGIONS
        for r in get_common_regions():
            assert r in FALLBACK_REGIONS


# ── get_regions_by_prefix ─────────────────────────────────────────────

class TestGetRegionsByPrefix:
    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_us_prefix(self, mock_fetch):
        mock_fetch.return_value = ["us-east-1", "us-west-2", "eu-west-1"]
        from agenticops.scan.regions import get_regions_by_prefix
        result = get_regions_by_prefix("us")
        assert all(r.startswith("us") for r in result)
        assert "eu-west-1" not in result

    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_no_match(self, mock_fetch):
        mock_fetch.return_value = ["us-east-1"]
        from agenticops.scan.regions import get_regions_by_prefix
        assert get_regions_by_prefix("zz") == []


# ── validate_region ───────────────────────────────────────────────────

class TestValidateRegion:
    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_valid(self, mock_fetch):
        mock_fetch.return_value = ["us-east-1"]
        from agenticops.scan.regions import validate_region
        assert validate_region("us-east-1") is True

    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_invalid(self, mock_fetch):
        mock_fetch.return_value = ["us-east-1"]
        from agenticops.scan.regions import validate_region
        assert validate_region("xx-fake-1") is False

    @patch("agenticops.scan.regions.fetch_regions_from_api")
    def test_govcloud_valid(self, mock_fetch):
        mock_fetch.return_value = ["us-east-1"]
        from agenticops.scan.regions import validate_region
        assert validate_region("us-gov-west-1") is True


# ── get_service_availability ──────────────────────────────────────────

class TestGetServiceAvailability:
    @patch("agenticops.scan.regions.urlopen")
    def test_success(self, mock_urlopen):
        data = {"prices": [
            {"attributes": {"aws:region": "us-east-1", "aws:serviceName": "Amazon EC2"}},
            {"attributes": {"aws:region": "us-east-1", "aws:serviceName": "Amazon S3"}},
        ]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from agenticops.scan.regions import get_service_availability
        result = get_service_availability()
        assert "us-east-1" in result
        assert "Amazon EC2" in result["us-east-1"]

    @patch("agenticops.scan.regions.urlopen")
    def test_error_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("boom")
        from agenticops.scan.regions import get_service_availability
        assert get_service_availability() == {}


# ── is_service_available ──────────────────────────────────────────────

class TestIsServiceAvailable:
    @patch("agenticops.scan.regions.get_service_availability")
    def test_available(self, mock_avail):
        mock_avail.return_value = {"us-east-1": ["Amazon EC2", "Amazon S3"]}
        from agenticops.scan.regions import is_service_available
        assert is_service_available("EC2", "us-east-1") is True

    @patch("agenticops.scan.regions.get_service_availability")
    def test_default_true_when_empty(self, mock_avail):
        mock_avail.return_value = {}
        from agenticops.scan.regions import is_service_available
        assert is_service_available("EC2", "us-east-1") is True

    @patch("agenticops.scan.regions.get_service_availability")
    def test_default_true_unknown_region(self, mock_avail):
        mock_avail.return_value = {"eu-west-1": ["Amazon S3"]}
        from agenticops.scan.regions import is_service_available
        assert is_service_available("EC2", "us-east-1") is True
