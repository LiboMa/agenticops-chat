"""Tests for Azure, GCP, and Alicloud providers."""

import json
import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Azure Provider Tests
# ---------------------------------------------------------------------------


class TestAzureProvider:
    """AzureProvider with mocked azure-identity SDK."""

    def setup_method(self):
        # Clear cache between tests
        try:
            from agenticops.providers.azure import get_session_cache
            get_session_cache().clear()
        except ImportError:
            pass

    @patch.dict("sys.modules", {
        "azure": MagicMock(),
        "azure.identity": MagicMock(),
        "azure.mgmt": MagicMock(),
        "azure.mgmt.resource": MagicMock(),
    })
    def test_azure_get_session(self):
        # Reimport with mocked SDK
        import importlib
        import agenticops.providers.azure as azure_mod
        importlib.reload(azure_mod)

        provider = azure_mod.AzureProvider(
            account_id=1,
            credentials={"subscription_id": "sub-123", "tenant_id": "t-1"},
            regions=["eastus"],
        )
        session = provider.get_session()
        assert session["subscription_id"] == "sub-123"
        assert session["region"] == "eastus"
        assert "credential" in session

    @patch.dict("sys.modules", {
        "azure": MagicMock(),
        "azure.identity": MagicMock(),
        "azure.mgmt": MagicMock(),
        "azure.mgmt.resource": MagicMock(),
    })
    def test_azure_get_session_cached(self):
        import importlib
        import agenticops.providers.azure as azure_mod
        importlib.reload(azure_mod)

        provider = azure_mod.AzureProvider(
            account_id=2,
            credentials={"subscription_id": "sub-456"},
            regions=["westus"],
        )
        s1 = provider.get_session("westus")
        s2 = provider.get_session("westus")
        assert s1 is s2

    @patch.dict("sys.modules", {
        "azure": MagicMock(),
        "azure.identity": MagicMock(),
        "azure.mgmt": MagicMock(),
        "azure.mgmt.resource": MagicMock(),
    })
    def test_azure_validate_success(self):
        import importlib
        import agenticops.providers.azure as azure_mod
        importlib.reload(azure_mod)

        mock_client_cls = azure_mod.ResourceManagementClient
        mock_client = MagicMock()
        mock_client.resource_groups.list.return_value = iter([MagicMock()])
        mock_client_cls.return_value = mock_client

        provider = azure_mod.AzureProvider(
            account_id=3,
            credentials={"subscription_id": "sub-789"},
            regions=["eastus"],
        )
        assert provider.validate_credentials() is True

    @patch.dict("sys.modules", {
        "azure": MagicMock(),
        "azure.identity": MagicMock(),
        "azure.mgmt": MagicMock(),
        "azure.mgmt.resource": MagicMock(),
    })
    def test_azure_validate_failure(self):
        import importlib
        import agenticops.providers.azure as azure_mod
        importlib.reload(azure_mod)

        mock_client_cls = azure_mod.ResourceManagementClient
        mock_client = MagicMock()
        mock_client.resource_groups.list.side_effect = Exception("Auth failed")
        mock_client_cls.return_value = mock_client

        provider = azure_mod.AzureProvider(
            account_id=4,
            credentials={"subscription_id": "sub-bad"},
            regions=["eastus"],
        )
        assert provider.validate_credentials() is False

    def test_azure_import_error(self):
        """Verify AzureProvider raises ImportError when SDK is missing."""
        import agenticops.providers.azure as azure_mod
        original = azure_mod._AZURE_SDK_AVAILABLE
        try:
            azure_mod._AZURE_SDK_AVAILABLE = False
            with pytest.raises(ImportError, match="Azure SDK not installed"):
                azure_mod.AzureProvider(
                    account_id=5,
                    credentials={"subscription_id": "sub-x"},
                )
        finally:
            azure_mod._AZURE_SDK_AVAILABLE = original

    def test_azure_is_sdk_available(self):
        from agenticops.providers.azure import is_sdk_available
        # Should be a boolean regardless of actual SDK presence
        assert isinstance(is_sdk_available(), bool)


# ---------------------------------------------------------------------------
# GCP Provider Tests
# ---------------------------------------------------------------------------


class TestGCPProvider:
    """GCPProvider with mocked google-auth SDK."""

    def setup_method(self):
        try:
            from agenticops.providers.gcp import get_session_cache
            get_session_cache().clear()
        except ImportError:
            pass

    @patch.dict("sys.modules", {
        "google": MagicMock(),
        "google.auth": MagicMock(),
        "google.auth.credentials": MagicMock(),
        "google.auth.transport": MagicMock(),
        "google.auth.transport.requests": MagicMock(),
        "google.oauth2": MagicMock(),
        "google.oauth2.service_account": MagicMock(),
    })
    def test_gcp_get_session_default_creds(self):
        import importlib
        import agenticops.providers.gcp as gcp_mod
        importlib.reload(gcp_mod)

        mock_cred = MagicMock()
        gcp_mod.google.auth.default.return_value = (mock_cred, "proj-123")

        provider = gcp_mod.GCPProvider(
            account_id=1,
            credentials={"project_id": "proj-123"},
            regions=["us-central1"],
        )
        session = provider.get_session()
        assert session["project_id"] == "proj-123"
        assert session["region"] == "us-central1"
        gcp_mod.google.auth.default.assert_called_once()

    @patch.dict("sys.modules", {
        "google": MagicMock(),
        "google.auth": MagicMock(),
        "google.auth.credentials": MagicMock(),
        "google.auth.transport": MagicMock(),
        "google.auth.transport.requests": MagicMock(),
        "google.oauth2": MagicMock(),
        "google.oauth2.service_account": MagicMock(),
    })
    def test_gcp_get_session_service_account(self):
        import importlib
        import agenticops.providers.gcp as gcp_mod
        importlib.reload(gcp_mod)

        sa_info = {"project_id": "sa-proj", "client_email": "test@test.iam.gserviceaccount.com"}
        provider = gcp_mod.GCPProvider(
            account_id=2,
            credentials={"project_id": "sa-proj", "service_account_json": sa_info},
            regions=["asia-east1"],
        )
        session = provider.get_session()
        assert session["project_id"] == "sa-proj"

    @patch.dict("sys.modules", {
        "google": MagicMock(),
        "google.auth": MagicMock(),
        "google.auth.credentials": MagicMock(),
        "google.auth.transport": MagicMock(),
        "google.auth.transport.requests": MagicMock(),
        "google.oauth2": MagicMock(),
        "google.oauth2.service_account": MagicMock(),
    })
    def test_gcp_get_session_cached(self):
        import importlib
        import agenticops.providers.gcp as gcp_mod
        importlib.reload(gcp_mod)

        mock_cred = MagicMock()
        gcp_mod.google.auth.default.return_value = (mock_cred, "proj-cached")

        provider = gcp_mod.GCPProvider(
            account_id=3,
            credentials={"project_id": "proj-cached"},
            regions=["us-west1"],
        )
        s1 = provider.get_session("us-west1")
        s2 = provider.get_session("us-west1")
        assert s1 is s2

    @patch.dict("sys.modules", {
        "google": MagicMock(),
        "google.auth": MagicMock(),
        "google.auth.credentials": MagicMock(),
        "google.auth.transport": MagicMock(),
        "google.auth.transport.requests": MagicMock(),
    })
    def test_gcp_validate_success(self):
        import importlib
        import agenticops.providers.gcp as gcp_mod
        importlib.reload(gcp_mod)

        mock_cred = MagicMock()
        gcp_mod.google.auth.default.return_value = (mock_cred, "proj-val")

        provider = gcp_mod.GCPProvider(
            account_id=4,
            credentials={"project_id": "proj-val"},
            regions=["us-central1"],
        )
        assert provider.validate_credentials() is True

    @patch.dict("sys.modules", {
        "google": MagicMock(),
        "google.auth": MagicMock(),
        "google.auth.credentials": MagicMock(),
        "google.auth.transport": MagicMock(),
        "google.auth.transport.requests": MagicMock(),
    })
    def test_gcp_validate_failure(self):
        import importlib
        import agenticops.providers.gcp as gcp_mod
        importlib.reload(gcp_mod)

        mock_cred = MagicMock()
        mock_cred.refresh.side_effect = Exception("Token refresh failed")
        gcp_mod.google.auth.default.return_value = (mock_cred, "proj-bad")

        provider = gcp_mod.GCPProvider(
            account_id=5,
            credentials={"project_id": "proj-bad"},
            regions=["us-central1"],
        )
        assert provider.validate_credentials() is False

    def test_gcp_import_error(self):
        """Verify GCPProvider raises ImportError when SDK is missing."""
        import agenticops.providers.gcp as gcp_mod
        original = gcp_mod._GCP_SDK_AVAILABLE
        try:
            gcp_mod._GCP_SDK_AVAILABLE = False
            with pytest.raises(ImportError, match="GCP SDK not installed"):
                gcp_mod.GCPProvider(
                    account_id=6,
                    credentials={"project_id": "proj-x"},
                )
        finally:
            gcp_mod._GCP_SDK_AVAILABLE = original

    def test_gcp_scope_constant(self):
        """Verify cloud-platform scope is set correctly."""
        from agenticops.providers.gcp import _GCP_SCOPE
        assert _GCP_SCOPE == "https://www.googleapis.com/auth/cloud-platform"


# ---------------------------------------------------------------------------
# Alicloud Provider Tests
# ---------------------------------------------------------------------------


class TestAlicloudProvider:
    """AlicloudProvider with mocked CLI."""

    def setup_method(self):
        from agenticops.providers.alicloud import get_session_cache
        get_session_cache().clear()

    def test_alicloud_get_session(self):
        from agenticops.providers.alicloud import AlicloudProvider
        provider = AlicloudProvider(
            account_id=1,
            credentials={"access_key_id": "AK123", "access_key_secret": "SK456"},
            regions=["cn-hangzhou"],
        )
        session = provider.get_session()
        assert session["region"] == "cn-hangzhou"
        assert session["access_key_id"] == "AK123"

    def test_alicloud_get_session_cached(self):
        from agenticops.providers.alicloud import AlicloudProvider
        provider = AlicloudProvider(
            account_id=2,
            credentials={"access_key_id": "AK", "access_key_secret": "SK"},
            regions=["cn-beijing"],
        )
        s1 = provider.get_session("cn-beijing")
        s2 = provider.get_session("cn-beijing")
        assert s1 is s2

    def test_alicloud_get_session_default_region(self):
        from agenticops.providers.alicloud import AlicloudProvider
        provider = AlicloudProvider(
            account_id=3,
            credentials={},
            regions=[],
        )
        session = provider.get_session()
        assert session["region"] == "cn-hangzhou"

    @patch("agenticops.providers.alicloud.subprocess.run")
    def test_alicloud_validate_success(self, mock_run):
        from agenticops.providers.alicloud import AlicloudProvider
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"AccountId": "123456", "Arn": "acs:ram::123456:root"}),
        )
        provider = AlicloudProvider(
            account_id=4,
            credentials={"access_key_id": "AK", "access_key_secret": "SK"},
            regions=["cn-hangzhou"],
        )
        assert provider.validate_credentials() is True

    @patch("agenticops.providers.alicloud.subprocess.run")
    def test_alicloud_validate_failure(self, mock_run):
        from agenticops.providers.alicloud import AlicloudProvider
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="InvalidAccessKeyId",
            stdout="",
        )
        provider = AlicloudProvider(
            account_id=5,
            credentials={"access_key_id": "BAD", "access_key_secret": "BAD"},
            regions=["cn-hangzhou"],
        )
        assert provider.validate_credentials() is False

    @patch("agenticops.providers.alicloud.subprocess.run")
    def test_alicloud_list_resources_ecs(self, mock_run):
        from agenticops.providers.alicloud import AlicloudProvider
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "Instances": {
                    "Instance": [
                        {"InstanceId": "i-abc", "InstanceName": "web-1", "Status": "Running", "Tags": {}},
                    ]
                }
            }),
        )
        provider = AlicloudProvider(
            account_id=6,
            credentials={"access_key_id": "AK", "access_key_secret": "SK"},
            regions=["cn-hangzhou"],
        )
        resources = provider.list_resources("cn-hangzhou", "ecs")
        assert len(resources) == 1
        assert resources[0]["resource_id"] == "i-abc"
        assert resources[0]["name"] == "web-1"
        assert resources[0]["status"] == "running"

    @patch("agenticops.providers.alicloud.subprocess.run")
    def test_alicloud_cli_error(self, mock_run):
        from agenticops.providers.alicloud import AlicloudProvider
        mock_run.return_value = MagicMock(returncode=1, stderr="Network error", stdout="")
        provider = AlicloudProvider(
            account_id=7,
            credentials={"access_key_id": "AK", "access_key_secret": "SK"},
            regions=["cn-hangzhou"],
        )
        # list_resources should catch the error and return empty
        resources = provider.list_resources("cn-hangzhou", "ecs")
        assert resources == []

    @patch("agenticops.providers.alicloud._cli_available", return_value=False)
    def test_alicloud_no_cli_warning(self, mock_cli):
        """AlicloudProvider should warn but not raise when CLI is missing."""
        from agenticops.providers.alicloud import AlicloudProvider
        # Should not raise — just logs a warning
        provider = AlicloudProvider(
            account_id=8,
            credentials={},
            regions=["cn-hangzhou"],
        )
        assert provider.account_id == 8


# ---------------------------------------------------------------------------
# Cross-provider registration
# ---------------------------------------------------------------------------


class TestMultiProviderRegistry:
    """Verify all providers register correctly."""

    def test_all_built_in_providers_registered(self):
        from agenticops.providers.base import registered_providers
        providers = registered_providers()
        assert "aws" in providers
        assert "alicloud" in providers
        # azure and gcp may not be registered if SDKs are missing
        # but they should be in the list if the test environment has the mocks
