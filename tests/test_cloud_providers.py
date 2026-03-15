"""Tests for CloudProvider ABC, registry, SessionCache, and AWSProvider."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from agenticops.providers.base import (
    CloudProvider,
    SessionCache,
    get_provider_class,
    register_provider,
    registered_providers,
    _registry,
    _registry_lock,
)


# ---------------------------------------------------------------------------
# CloudProvider ABC tests
# ---------------------------------------------------------------------------

class TestCloudProviderABC:
    """Verify ABC cannot be instantiated directly."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            CloudProvider(account_id=1, credentials={})

    def test_concrete_subclass(self):
        class DummyProvider(CloudProvider):
            provider_name = "dummy"
            def get_session(self, region=None): return "session"
            def validate_credentials(self): return True
            def list_resources(self, region, resource_type): return []

        p = DummyProvider(account_id=1, credentials={"key": "val"}, regions=["us-east-1"])
        assert p.account_id == 1
        assert p.regions == ["us-east-1"]
        assert p.get_session() == "session"
        assert p.validate_credentials() is True
        assert p.list_resources("us-east-1", "ec2") == []


# ---------------------------------------------------------------------------
# SessionCache tests
# ---------------------------------------------------------------------------

class TestSessionCache:
    """Session cache with TTL expiry."""

    def test_put_and_get(self):
        cache = SessionCache(ttl_seconds=60)
        cache.put("k1", "session1")
        assert cache.get("k1") == "session1"

    def test_miss_returns_none(self):
        cache = SessionCache()
        assert cache.get("nonexistent") is None

    def test_expiry(self):
        cache = SessionCache(ttl_seconds=0.05)
        cache.put("k1", "session1")
        assert cache.get("k1") == "session1"
        time.sleep(0.1)
        assert cache.get("k1") is None

    def test_invalidate(self):
        cache = SessionCache()
        cache.put("k1", "s1")
        cache.invalidate("k1")
        assert cache.get("k1") is None

    def test_clear(self):
        cache = SessionCache()
        cache.put("k1", "s1")
        cache.put("k2", "s2")
        assert cache.size == 2
        cache.clear()
        assert cache.size == 0

    def test_prune_expired(self):
        cache = SessionCache(ttl_seconds=0.05)
        cache.put("k1", "s1")
        cache.put("k2", "s2")
        time.sleep(0.1)
        cache.put("k3", "s3")  # fresh
        removed = cache.prune_expired()
        assert removed == 2
        assert cache.size == 1
        assert cache.get("k3") == "s3"

    def test_thread_safety(self):
        cache = SessionCache(ttl_seconds=60)
        errors = []

        def writer(n):
            try:
                for i in range(50):
                    cache.put(f"t{n}-{i}", f"v{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert cache.size > 0


# ---------------------------------------------------------------------------
# Provider registry tests
# ---------------------------------------------------------------------------

class TestProviderRegistry:
    """Thread-safe provider registration and lookup."""

    def setup_method(self):
        # Save original state
        with _registry_lock:
            self._original = dict(_registry)

    def teardown_method(self):
        # Restore original state
        with _registry_lock:
            _registry.clear()
            _registry.update(self._original)

    def test_register_and_lookup(self):
        @register_provider
        class TestProvider(CloudProvider):
            provider_name = "test_reg"
            def get_session(self, region=None): pass
            def validate_credentials(self): return True
            def list_resources(self, region, resource_type): return []

        assert get_provider_class("test_reg") is TestProvider

    def test_lookup_missing(self):
        assert get_provider_class("nonexistent_provider") is None

    def test_registered_providers_includes_aws(self):
        # AWSProvider auto-registers on import
        assert "aws" in registered_providers()

    def test_register_without_name_raises(self):
        with pytest.raises(ValueError, match="must set provider_name"):
            @register_provider
            class BadProvider(CloudProvider):
                provider_name = ""
                def get_session(self, region=None): pass
                def validate_credentials(self): return True
                def list_resources(self, region, resource_type): return []


# ---------------------------------------------------------------------------
# AWSProvider tests
# ---------------------------------------------------------------------------

class TestAWSProvider:
    """AWSProvider with mocked boto3."""

    def setup_method(self):
        from agenticops.providers.aws import get_session_cache
        get_session_cache().clear()

    @patch("agenticops.providers.aws.boto3")
    def test_get_session_with_role_arn(self, mock_boto3):
        from agenticops.providers.aws import AWSProvider

        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA...",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        provider = AWSProvider(
            account_id=1,
            credentials={"role_arn": "arn:aws:iam::123:role/Ops", "external_id": "ext1"},
            regions=["ap-southeast-1"],
        )
        session = provider.get_session()

        mock_sts.assume_role.assert_called_once()
        call_kwargs = mock_sts.assume_role.call_args[1]
        assert call_kwargs["RoleArn"] == "arn:aws:iam::123:role/Ops"
        assert call_kwargs["ExternalId"] == "ext1"
        assert session == mock_session

    @patch("agenticops.providers.aws.boto3")
    def test_get_session_default_creds(self, mock_boto3):
        from agenticops.providers.aws import AWSProvider

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        provider = AWSProvider(
            account_id=2,
            credentials={},  # No role_arn
            regions=["us-west-2"],
        )
        session = provider.get_session("us-west-2")

        mock_boto3.Session.assert_called_once_with(region_name="us-west-2")
        assert session == mock_session

    @patch("agenticops.providers.aws.boto3")
    def test_get_session_cached(self, mock_boto3):
        from agenticops.providers.aws import AWSProvider

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        provider = AWSProvider(account_id=3, credentials={}, regions=["us-east-1"])
        s1 = provider.get_session("us-east-1")
        s2 = provider.get_session("us-east-1")

        # boto3.Session called only once (second time from cache)
        assert mock_boto3.Session.call_count == 1
        assert s1 is s2

    @patch("agenticops.providers.aws.boto3")
    def test_validate_credentials_success(self, mock_boto3):
        from agenticops.providers.aws import AWSProvider

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_sts_client = MagicMock()
        mock_session.client.return_value = mock_sts_client

        provider = AWSProvider(account_id=4, credentials={}, regions=["us-east-1"])
        assert provider.validate_credentials() is True
        mock_sts_client.get_caller_identity.assert_called_once()

    @patch("agenticops.providers.aws.boto3")
    def test_validate_credentials_failure(self, mock_boto3):
        from agenticops.providers.aws import AWSProvider

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.side_effect = Exception("InvalidToken")
        mock_session.client.return_value = mock_sts_client

        provider = AWSProvider(account_id=5, credentials={}, regions=["us-east-1"])
        assert provider.validate_credentials() is False

    @patch("agenticops.providers.aws.boto3")
    def test_list_resources(self, mock_boto3):
        from agenticops.providers.aws import AWSProvider

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "ResourceTagMappingList": [
                    {
                        "ResourceARN": "arn:aws:ec2:us-east-1:123:instance/i-abc123",
                        "Tags": [{"Key": "Name", "Value": "web-1"}],
                    }
                ]
            }
        ]

        provider = AWSProvider(account_id=6, credentials={}, regions=["us-east-1"])
        resources = provider.list_resources("us-east-1", "ec2:instance")

        assert len(resources) == 1
        assert resources[0]["resource_id"] == "i-abc123"
        assert resources[0]["name"] == "web-1"
        assert resources[0]["status"] == "active"

    def test_default_region_fallback(self):
        from agenticops.providers.aws import AWSProvider
        provider = AWSProvider(account_id=7, credentials={}, regions=[])
        # Without boto3, just verify the default region logic
        with patch("agenticops.providers.aws.boto3") as mock_boto3:
            mock_boto3.Session.return_value = MagicMock()
            provider.get_session()
            mock_boto3.Session.assert_called_once_with(region_name="us-east-1")
