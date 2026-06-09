"""Comprehensive tests for the CloudProvider abstraction layer."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agenticops.providers.base import (
    CloudProvider,
    clear_session_cache,
    get_cached_session,
    get_provider,
    set_cached_session,
    PROVIDERS,
)


# ── Helpers ─────────────────────────────────────────────────────────


def make_account(provider: str, name: str = "test-acct", credentials: dict | None = None, regions: list | None = None):
    """Create a mock CloudAccount."""
    return SimpleNamespace(
        provider=provider,
        name=name,
        credentials=credentials or {},
        regions=regions or [],
    )


# ── Registry & get_provider tests ──────────────────────────────────


class TestProviderRegistry:
    def test_registry_has_all_clouds(self):
        """All four cloud providers are registered."""
        from agenticops.providers.base import _load_providers
        _load_providers()
        assert "aws" in PROVIDERS
        assert "azure" in PROVIDERS
        assert "gcp" in PROVIDERS
        assert "alicloud" in PROVIDERS
        assert len(PROVIDERS) == 4

    def test_get_provider_aws(self):
        from agenticops.providers.aws import AWSProvider
        account = make_account("aws")
        provider = get_provider(account)
        assert isinstance(provider, AWSProvider)
        assert provider.provider_type == "aws"

    def test_get_provider_azure(self):
        from agenticops.providers.azure import AzureProvider
        account = make_account("azure")
        provider = get_provider(account)
        assert isinstance(provider, AzureProvider)
        assert provider.provider_type == "azure"

    def test_get_provider_gcp(self):
        from agenticops.providers.gcp import GCPProvider
        account = make_account("gcp")
        provider = get_provider(account)
        assert isinstance(provider, GCPProvider)
        assert provider.provider_type == "gcp"

    def test_get_provider_alicloud(self):
        from agenticops.providers.alicloud import AlicloudProvider
        account = make_account("alicloud")
        provider = get_provider(account)
        assert isinstance(provider, AlicloudProvider)
        assert provider.provider_type == "alicloud"

    def test_get_provider_case_insensitive(self):
        account = make_account("AWS")
        provider = get_provider(account)
        assert provider.provider_type == "aws"

    def test_get_provider_unknown_raises(self):
        account = make_account("oracle")
        with pytest.raises(ValueError, match="Unsupported provider 'oracle'"):
            get_provider(account)


# ── Session cache tests ────────────────────────────────────────────


class TestSessionCache:
    def setup_method(self):
        clear_session_cache()

    def test_set_and_get(self):
        session = MagicMock()
        set_cached_session("aws:prod:us-east-1", session)
        assert get_cached_session("aws:prod:us-east-1") is session

    def test_get_missing_returns_none(self):
        assert get_cached_session("nonexistent") is None

    def test_clear(self):
        set_cached_session("key1", "val1")
        set_cached_session("key2", "val2")
        clear_session_cache()
        assert get_cached_session("key1") is None
        assert get_cached_session("key2") is None

    def test_overwrite(self):
        set_cached_session("k", "old")
        set_cached_session("k", "new")
        assert get_cached_session("k") == "new"


# ── AWS Provider tests ─────────────────────────────────────────────


class TestAWSProvider:
    def test_resolve_credentials_role_arn(self):
        """Test STS AssumeRole path: base session → base_session.client('sts').assume_role()."""
        account = make_account("aws", credentials={"role_arn": "arn:aws:iam::123:role/test"})
        provider = get_provider(account)

        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA...",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }

        # base_session (default chain, no profile) — used for STS AssumeRole
        mock_base_session = MagicMock()
        mock_base_session.client.return_value = mock_sts

        # assumed_session — created from assumed credentials
        mock_assumed_session = MagicMock()
        mock_assumed_session.client.return_value.get_caller_identity.return_value = {}

        mock_boto3 = MagicMock()
        mock_boto3.Session.side_effect = [mock_base_session, mock_assumed_session]

        import agenticops.providers.aws as aws_mod
        original = aws_mod.boto3
        try:
            aws_mod.boto3 = mock_boto3
            result = provider.resolve_credentials()
        finally:
            aws_mod.boto3 = original

        assert result is True
        mock_base_session.client.assert_called_with("sts")
        mock_sts.assume_role.assert_called_once()

    def test_resolve_credentials_profile_plus_role_arn(self):
        """Test profile_name + role_arn: base session uses profile, then assumes role."""
        account = make_account("aws", credentials={
            "profile_name": "china-profile",
            "role_arn": "arn:aws-cn:iam::113:role/OpsRole",
        })
        provider = get_provider(account)

        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA...",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }

        mock_base_session = MagicMock()
        mock_base_session.client.return_value = mock_sts

        mock_assumed_session = MagicMock()
        mock_assumed_session.client.return_value.get_caller_identity.return_value = {}

        mock_boto3 = MagicMock()
        mock_boto3.Session.side_effect = [mock_base_session, mock_assumed_session]

        import agenticops.providers.aws as aws_mod
        original = aws_mod.boto3
        try:
            aws_mod.boto3 = mock_boto3
            result = provider.resolve_credentials()
        finally:
            aws_mod.boto3 = original

        assert result is True
        # Base session uses profile
        mock_boto3.Session.assert_any_call(profile_name="china-profile")
        # AssumeRole called via base session's STS client (cn-north-1 for aws-cn partition)
        mock_base_session.client.assert_called_with("sts", region_name="cn-north-1")
        mock_sts.assume_role.assert_called_once()

    def test_resolve_credentials_profile(self):
        """Test profile_name path."""
        account = make_account("aws", credentials={"profile_name": "myprofile"})
        provider = get_provider(account)

        mock_session = MagicMock()
        mock_session.client.return_value.get_caller_identity.return_value = {}

        import agenticops.providers.aws as aws_mod
        mock_boto3 = MagicMock()
        mock_boto3.Session.return_value = mock_session
        original = aws_mod.boto3
        try:
            aws_mod.boto3 = mock_boto3
            result = provider.resolve_credentials()
        finally:
            aws_mod.boto3 = original

        assert result is True
        mock_boto3.Session.assert_called_with(profile_name="myprofile")

    def test_resolve_credentials_static(self):
        """Test static access key path."""
        account = make_account("aws", credentials={
            "access_key_id": "AKIA...",
            "secret_access_key": "secret",
        })
        provider = get_provider(account)

        mock_session = MagicMock()
        mock_session.client.return_value.get_caller_identity.return_value = {}

        import agenticops.providers.aws as aws_mod
        mock_boto3 = MagicMock()
        mock_boto3.Session.return_value = mock_session
        original = aws_mod.boto3
        try:
            aws_mod.boto3 = mock_boto3
            result = provider.resolve_credentials()
        finally:
            aws_mod.boto3 = original

        assert result is True
        mock_boto3.Session.assert_called_with(
            aws_access_key_id="AKIA...",
            aws_secret_access_key="secret",
            aws_session_token=None,
        )

    def test_resolve_credentials_default(self):
        """Test default chain (no credentials)."""
        account = make_account("aws")
        provider = get_provider(account)

        mock_session = MagicMock()
        mock_session.client.return_value.get_caller_identity.return_value = {}

        import agenticops.providers.aws as aws_mod
        mock_boto3 = MagicMock()
        mock_boto3.Session.return_value = mock_session
        original = aws_mod.boto3
        try:
            aws_mod.boto3 = mock_boto3
            result = provider.resolve_credentials()
        finally:
            aws_mod.boto3 = original

        assert result is True
        mock_boto3.Session.assert_called_with()

    def test_resolve_credentials_validation_fails(self):
        """Test that validation failure returns False."""
        account = make_account("aws")
        provider = get_provider(account)

        mock_session = MagicMock()
        mock_session.client.return_value.get_caller_identity.side_effect = Exception("denied")

        import agenticops.providers.aws as aws_mod
        mock_boto3 = MagicMock()
        mock_boto3.Session.return_value = mock_session
        original = aws_mod.boto3
        try:
            aws_mod.boto3 = mock_boto3
            result = provider.resolve_credentials()
        finally:
            aws_mod.boto3 = original

        assert result is False

    def test_resolve_credentials_no_boto3(self):
        """When boto3 is None, returns False."""
        account = make_account("aws")
        provider = get_provider(account)

        import agenticops.providers.aws as aws_mod
        original = aws_mod.boto3
        try:
            aws_mod.boto3 = None
            result = provider.resolve_credentials()
        finally:
            aws_mod.boto3 = original

        assert result is False

    def test_cli_tool_returns_callable(self):
        """cli_tool() returns a callable with the right name."""
        account = make_account("aws", name="prod-account")
        provider = get_provider(account)
        tool = provider.cli_tool()
        assert callable(tool)
        assert tool.__name__ == "run_aws_cli_prod_account"

    def test_cli_tool_rejects_non_aws(self):
        account = make_account("aws")
        provider = get_provider(account)
        tool = provider.cli_tool()
        result = tool("gcloud compute list")
        assert "Error" in result

    def test_cli_tool_blocks_dangerous(self):
        account = make_account("aws")
        provider = get_provider(account)
        tool = provider.cli_tool()
        result = tool("aws iam create-user --user-name evil")
        assert "Blocked" in result or "Error" in result

    def test_cli_tool_blocks_shell_injection(self):
        account = make_account("aws")
        provider = get_provider(account)
        tool = provider.cli_tool()
        result = tool("aws s3 ls | rm -rf /")
        assert "Error" in result
        assert "not allowed" in result

    def test_cli_tool_auto_appends_output_json(self):
        """Verify --output json is appended."""
        account = make_account("aws")
        provider = get_provider(account)
        # cli_tool now fails closed without a resolved session; give it one so we
        # reach the subprocess call this test is actually asserting on.
        frozen = MagicMock(access_key="k", secret_key="s", token="t")
        sess = MagicMock()
        sess.get_credentials.return_value.get_frozen_credentials.return_value = frozen
        provider._session = sess
        tool = provider.cli_tool()

        with patch("agenticops.providers.aws.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
            tool("aws ec2 describe-instances")

            called_args = mock_run.call_args[0][0]
            assert "--output" in called_args
            assert "json" in called_args


# ── Azure Provider tests ───────────────────────────────────────────


class TestAzureProvider:
    def test_resolve_credentials_client_secret(self):
        """Test ClientSecretCredential path."""
        account = make_account("azure", credentials={
            "client_id": "cid",
            "client_secret": "csecret",
            "tenant_id": "tid",
        })
        provider = get_provider(account)

        import agenticops.providers.azure as az_mod
        mock_csc = MagicMock()
        orig_csc = az_mod.ClientSecretCredential
        orig_has = az_mod._HAS_AZURE
        try:
            az_mod.ClientSecretCredential = mock_csc
            az_mod._HAS_AZURE = True
            result = provider.resolve_credentials()
        finally:
            az_mod.ClientSecretCredential = orig_csc
            az_mod._HAS_AZURE = orig_has

        assert result is True
        mock_csc.assert_called_with(tenant_id="tid", client_id="cid", client_secret="csecret")

    def test_resolve_credentials_env_vars(self):
        """Test ARM_* env var path."""
        account = make_account("azure")
        provider = get_provider(account)

        import agenticops.providers.azure as az_mod
        mock_csc = MagicMock()
        orig_csc = az_mod.ClientSecretCredential
        orig_has = az_mod._HAS_AZURE
        env = {
            "ARM_CLIENT_ID": "c",
            "ARM_CLIENT_SECRET": "s",
            "ARM_TENANT_ID": "t",
        }
        try:
            az_mod.ClientSecretCredential = mock_csc
            az_mod._HAS_AZURE = True
            with patch.dict(os.environ, env):
                result = provider.resolve_credentials()
        finally:
            az_mod.ClientSecretCredential = orig_csc
            az_mod._HAS_AZURE = orig_has

        assert result is True
        mock_csc.assert_called_once()

    def test_resolve_credentials_cli_fallback(self):
        """Test AzureCliCredential fallback."""
        account = make_account("azure")
        provider = get_provider(account)

        import agenticops.providers.azure as az_mod
        mock_cli_cred = MagicMock()
        orig_cli = az_mod.AzureCliCredential
        orig_has = az_mod._HAS_AZURE
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ARM_")}
        try:
            az_mod.AzureCliCredential = mock_cli_cred
            az_mod._HAS_AZURE = True
            with patch.dict(os.environ, clean_env, clear=True):
                result = provider.resolve_credentials()
        finally:
            az_mod.AzureCliCredential = orig_cli
            az_mod._HAS_AZURE = orig_has

        assert result is True
        mock_cli_cred.assert_called_once()

    def test_resolve_credentials_no_azure_sdk(self):
        """When azure-identity is not installed, returns True (CLI-only mode)."""
        account = make_account("azure")
        provider = get_provider(account)

        import agenticops.providers.azure as az_mod
        orig_has = az_mod._HAS_AZURE
        try:
            az_mod._HAS_AZURE = False
            result = provider.resolve_credentials()
        finally:
            az_mod._HAS_AZURE = orig_has

        assert result is True

    def test_cli_tool_returns_callable(self):
        account = make_account("azure", name="my-sub")
        provider = get_provider(account)
        tool = provider.cli_tool()
        assert callable(tool)
        assert tool.__name__ == "run_az_cli_my_sub"

    def test_cli_tool_rejects_non_az(self):
        account = make_account("azure")
        provider = get_provider(account)
        tool = provider.cli_tool()
        result = tool("aws ec2 describe-instances")
        assert "Error" in result

    def test_cli_tool_auto_appends_subscription(self):
        account = make_account("azure", credentials={"subscription_id": "sub-123"})
        provider = get_provider(account)
        tool = provider.cli_tool()

        with patch("agenticops.providers.azure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='[]', stderr="")
            tool("az vm list")

            called_args = mock_run.call_args[0][0]
            assert "--subscription" in called_args
            assert "sub-123" in called_args


# ── GCP Provider tests ─────────────────────────────────────────────


class TestGCPProvider:
    def test_resolve_credentials_service_account(self):
        """Test service_account_key path."""
        sa_key = {"type": "service_account", "project_id": "test"}
        account = make_account("gcp", credentials={"service_account_key": sa_key})
        provider = get_provider(account)

        import agenticops.providers.gcp as gcp_mod
        mock_sa = MagicMock()
        mock_cred = MagicMock()
        mock_sa.Credentials.from_service_account_info.return_value = mock_cred
        orig_sa = gcp_mod.google_service_account
        orig_has = gcp_mod._HAS_GOOGLE
        try:
            gcp_mod.google_service_account = mock_sa
            gcp_mod._HAS_GOOGLE = True
            result = provider.resolve_credentials()
        finally:
            gcp_mod.google_service_account = orig_sa
            gcp_mod._HAS_GOOGLE = orig_has

        assert result is True
        mock_sa.Credentials.from_service_account_info.assert_called_with(sa_key)

    def test_resolve_credentials_default(self):
        """Test google.auth.default() fallback."""
        account = make_account("gcp")
        provider = get_provider(account)

        import agenticops.providers.gcp as gcp_mod
        mock_auth = MagicMock()
        mock_cred = MagicMock()
        mock_auth.default.return_value = (mock_cred, "my-project")
        orig_auth = gcp_mod.google_auth
        orig_has = gcp_mod._HAS_GOOGLE
        try:
            gcp_mod.google_auth = mock_auth
            gcp_mod._HAS_GOOGLE = True
            result = provider.resolve_credentials()
        finally:
            gcp_mod.google_auth = orig_auth
            gcp_mod._HAS_GOOGLE = orig_has

        assert result is True

    def test_resolve_credentials_no_google_sdk(self):
        """When google-auth is not installed, returns True (CLI-only mode)."""
        account = make_account("gcp")
        provider = get_provider(account)

        import agenticops.providers.gcp as gcp_mod
        orig_has = gcp_mod._HAS_GOOGLE
        try:
            gcp_mod._HAS_GOOGLE = False
            result = provider.resolve_credentials()
        finally:
            gcp_mod._HAS_GOOGLE = orig_has

        assert result is True

    def test_cli_tool_returns_callable(self):
        account = make_account("gcp", name="my-project")
        provider = get_provider(account)
        tool = provider.cli_tool()
        assert callable(tool)
        assert tool.__name__ == "run_gcloud_my_project"

    def test_cli_tool_rejects_non_gcloud(self):
        account = make_account("gcp")
        provider = get_provider(account)
        tool = provider.cli_tool()
        result = tool("aws ec2 describe-instances")
        assert "Error" in result

    def test_cli_tool_auto_appends_project(self):
        account = make_account("gcp", credentials={"project_id": "proj-42"})
        provider = get_provider(account)
        tool = provider.cli_tool()

        with patch("agenticops.providers.gcp.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='[]', stderr="")
            tool("gcloud compute instances list")

            called_args = mock_run.call_args[0][0]
            assert "--project" in called_args
            assert "proj-42" in called_args


# ── Alicloud Provider tests ────────────────────────────────────────


class TestAlicloudProvider:
    def test_resolve_credentials_static(self):
        """Test static AK/SK path."""
        account = make_account("alicloud", credentials={
            "access_key_id": "LTAI...",
            "access_key_secret": "secret",
        })
        provider = get_provider(account)
        result = provider.resolve_credentials()
        assert result is True
        session = provider.sdk_session()
        assert session["access_key_id"] == "LTAI..."

    def test_resolve_credentials_assume_role(self):
        """Test assume_role path."""
        account = make_account("alicloud", credentials={
            "access_key_id": "LTAI...",
            "access_key_secret": "secret",
            "assume_role": {"role_arn": "acs:ram::123:role/test"},
        })
        provider = get_provider(account)
        result = provider.resolve_credentials()
        assert result is True
        session = provider.sdk_session()
        assert session["role_arn"] == "acs:ram::123:role/test"

    def test_resolve_credentials_assume_role_no_ak_warns(self):
        """Warn when assume_role has no access_key_id."""
        account = make_account("alicloud", credentials={
            "assume_role": {"role_arn": "acs:ram::123:role/test"},
        })
        provider = get_provider(account)

        import logging
        with patch.object(logging.getLogger("agenticops.providers.alicloud"), "warning") as mock_warn:
            result = provider.resolve_credentials()

        assert result is True
        mock_warn.assert_called_once()
        assert "no access_key_id" in mock_warn.call_args[0][0]

    def test_resolve_credentials_env_vars(self):
        """Test ALIBABA_CLOUD_* env var path."""
        account = make_account("alicloud")
        provider = get_provider(account)

        env = {
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "env-ak",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "env-sk",
        }
        with patch.dict(os.environ, env):
            result = provider.resolve_credentials()

        assert result is True
        session = provider.sdk_session()
        assert session["access_key_id"] == "env-ak"

    def test_resolve_credentials_empty(self):
        """Empty creds -> ECS RAM Role (empty dict)."""
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ALIBABA_CLOUD_")}
        account = make_account("alicloud")
        provider = get_provider(account)

        with patch.dict(os.environ, clean_env, clear=True):
            result = provider.resolve_credentials()

        assert result is True
        assert provider.sdk_session() == {}

    def test_resolve_credentials_profile(self):
        """Test profile_name path."""
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ALIBABA_CLOUD_")}
        account = make_account("alicloud", credentials={"profile_name": "myprofile"})
        provider = get_provider(account)

        with patch.dict(os.environ, clean_env, clear=True):
            result = provider.resolve_credentials()

        assert result is True
        session = provider.sdk_session()
        assert session["profile_name"] == "myprofile"

    def test_cli_tool_returns_callable(self):
        account = make_account("alicloud", name="ali-prod")
        provider = get_provider(account)
        provider._resolved_creds = {}
        tool = provider.cli_tool()
        assert callable(tool)
        assert tool.__name__ == "run_aliyun_cli_ali_prod"

    def test_cli_tool_rejects_non_aliyun(self):
        account = make_account("alicloud")
        provider = get_provider(account)
        provider._resolved_creds = {}
        tool = provider.cli_tool()
        result = tool("aws ec2 describe-instances")
        assert "Error" in result

    def test_cli_tool_auto_appends_region(self):
        account = make_account("alicloud", regions=["cn-shanghai"])
        provider = get_provider(account)
        provider._resolved_creds = {"access_key_id": "ak", "access_key_secret": "sk"}
        tool = provider.cli_tool()

        with patch("agenticops.providers.alicloud.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='{}', stderr="")
            tool("aliyun ecs DescribeInstances")

            called_args = mock_run.call_args[0][0]
            assert "--region" in called_args
            assert "cn-shanghai" in called_args

    def test_cli_tool_sets_env_vars(self):
        account = make_account("alicloud")
        provider = get_provider(account)
        provider._resolved_creds = {"access_key_id": "ak123", "access_key_secret": "sk456"}
        tool = provider.cli_tool()

        with patch("agenticops.providers.alicloud.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='{}', stderr="")
            tool("aliyun ecs DescribeInstances")

            env_used = mock_run.call_args[1]["env"]
            assert env_used["ALIBABA_CLOUD_ACCESS_KEY_ID"] == "ak123"
            assert env_used["ALIBABA_CLOUD_ACCESS_KEY_SECRET"] == "sk456"


# ── CloudProvider ABC tests ────────────────────────────────────────


class TestCloudProviderABC:
    def test_cannot_instantiate_abc(self):
        """CloudProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            CloudProvider(make_account("test"))

    def test_account_stored(self):
        """Provider stores the account reference."""
        account = make_account("aws", name="my-acct")
        provider = get_provider(account)
        assert provider.account is account
