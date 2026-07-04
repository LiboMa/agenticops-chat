"""E2E tests for multi-cloud provider abstraction refactoring.

Validates:
1. Multi-account enable/disable (no single-account enforcement)
2. Scanner, CloudWatch, aws_tools all use provider layer (no direct boto3)
3. AWSScanner rejects non-AWS accounts
4. assume_role tool resolves via provider
5. ops_agent multi-account disambiguation (no unsafe .first())
6. Legacy AWSAccount fallback removed from metadata_tools
7. graph/api and cloudwatch_provider use provider layer
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.models import Base, CloudAccount, CloudResource, init_db

# Patch targets: lazy imports resolve through these modules.
# - scanner.py / cloudwatch.py / aws_tools.py: `from agenticops.providers import get_provider`
#   → resolves via __init__.py → patch "agenticops.providers.get_provider"
# - scanner/engine.py: `from agenticops.providers.base import get_provider`
#   → resolves via base.py → patch "agenticops.providers.base.get_provider"
_PROVIDERS_PKG = "agenticops.providers.get_provider"
_PROVIDERS_BASE = "agenticops.providers.base.get_provider"
_MODELS_DB_SESSION = "agenticops.models.get_db_session"


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def one_aws_account(db_session):
    """Create a single enabled AWS account (default-account resolution succeeds)."""
    a = CloudAccount(
        name="aws-prod", provider="aws", is_enabled=True,
        credentials={"role_arn": "arn:aws:iam::111:role/Ops", "account_id": "111"},
        regions=["us-east-1"],
    )
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture
def two_aws_accounts(db_session):
    """Create two enabled AWS accounts."""
    a1 = CloudAccount(
        name="aws-prod", provider="aws", is_enabled=True,
        credentials={"role_arn": "arn:aws:iam::111:role/Ops", "account_id": "111"},
        regions=["us-east-1"],
    )
    a2 = CloudAccount(
        name="aws-staging", provider="aws", is_enabled=True,
        credentials={"role_arn": "arn:aws:iam::222:role/Ops", "account_id": "222"},
        regions=["us-west-2"],
    )
    db_session.add_all([a1, a2])
    db_session.commit()
    return a1, a2


@pytest.fixture
def multi_cloud_accounts(db_session):
    """Create accounts across AWS, Azure, GCP."""
    aws = CloudAccount(
        name="aws-prod", provider="aws", is_enabled=True,
        credentials={"role_arn": "arn:aws:iam::111:role/Ops"},
        regions=["us-east-1"],
    )
    azure = CloudAccount(
        name="azure-prod", provider="azure", is_enabled=True,
        credentials={"subscription_id": "sub-xxx", "tenant_id": "t-xxx"},
        regions=["eastus"],
    )
    gcp = CloudAccount(
        name="gcp-prod", provider="gcp", is_enabled=True,
        credentials={"project_id": "my-proj"},
        regions=["us-central1"],
    )
    db_session.add_all([aws, azure, gcp])
    db_session.commit()
    return aws, azure, gcp


# ══════════════════════════════════════════════════════════════════
# 1. Multi-Account Enable/Disable — no single-account enforcement
# ══════════════════════════════════════════════════════════════════


class TestMultiAccountEnable:
    """Verify that enabling one account does NOT disable others."""

    def test_multiple_accounts_stay_enabled(self, db_session, two_aws_accounts):
        a1, a2 = two_aws_accounts
        assert a1.is_enabled is True
        assert a2.is_enabled is True

        # Simulate enabling a1 — must NOT affect a2
        a1.is_enabled = True
        db_session.commit()

        db_session.refresh(a2)
        assert a2.is_enabled is True, "Enabling a1 must NOT disable a2"

    def test_all_three_providers_enabled(self, db_session, multi_cloud_accounts):
        aws, azure, gcp = multi_cloud_accounts
        enabled = db_session.query(CloudAccount).filter_by(is_enabled=True).all()
        assert len(enabled) == 3

    def test_no_bulk_disable_in_codebase(self):
        """Grep verification: no '.update({"is_enabled": False})' in source."""
        import subprocess
        result = subprocess.run(
            ["grep", "-rn", "is_enabled", "src/agenticops/"],
            capture_output=True, text=True,
        )
        lines = [
            l for l in result.stdout.splitlines()
            if ".update(" in l and "is_enabled" in l and "False" in l
        ]
        assert lines == [], f"Found bulk disable pattern: {lines}"


# ══════════════════════════════════════════════════════════════════
# 2. Scanner uses provider layer
# ══════════════════════════════════════════════════════════════════


class TestScannerUsesProvider:
    def test_scanner_init_calls_provider(self):
        """AWSScanner.__init__ must call get_provider + resolve_credentials."""
        acct = SimpleNamespace(
            provider="aws", name="test",
            credentials={"role_arn": "arn:aws:iam::123:role/X"},
            regions=["us-east-1"], labels={},
        )
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True

        with patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            from agenticops.scan.scanner import AWSScanner
            scanner = AWSScanner(acct)

        mock_provider.resolve_credentials.assert_called_once()
        assert scanner._provider is mock_provider

    def test_scanner_get_client_uses_provider_session(self):
        """_get_client must call provider.sdk_session().client()."""
        acct = SimpleNamespace(
            provider="aws", name="test",
            credentials={}, regions=[], labels={},
        )
        mock_session = MagicMock()
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_provider.sdk_session.return_value = mock_session

        with patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            from agenticops.scan.scanner import AWSScanner
            scanner = AWSScanner(acct)
            scanner._get_client("ec2", "us-east-1")

        mock_provider.sdk_session.assert_called_once()
        mock_session.client.assert_called_with("ec2", region_name="us-east-1")

    def test_scanner_rejects_non_aws(self):
        """AWSScanner must raise ValueError for non-AWS accounts."""
        from agenticops.scan.scanner import AWSScanner
        acct = SimpleNamespace(
            provider="azure", name="az-test",
            credentials={}, regions=[], labels={},
        )
        with pytest.raises(ValueError, match="AWSScanner only supports AWS"):
            AWSScanner(acct)

    def test_scanner_no_direct_boto3_import(self):
        """scanner.py must NOT import boto3 directly."""
        import agenticops.scan.scanner as mod
        import inspect
        source = inspect.getsource(mod)
        # Check module-level imports (before class definition)
        header = source.split("class AWSScanner")[0]
        assert "import boto3" not in header


# ══════════════════════════════════════════════════════════════════
# 3. CloudWatch Monitor uses provider layer
# ══════════════════════════════════════════════════════════════════


class TestCloudWatchUsesProvider:
    def test_monitor_init_calls_provider(self):
        acct = SimpleNamespace(
            provider="aws", name="cw-test",
            credentials={}, regions=[], labels={},
        )
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True

        with patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            from agenticops.monitor.cloudwatch import CloudWatchMonitor
            monitor = CloudWatchMonitor(acct)

        mock_provider.resolve_credentials.assert_called_once()

    def test_get_cloudwatch_client_uses_provider(self):
        acct = SimpleNamespace(
            provider="aws", name="cw-test",
            credentials={}, regions=[], labels={},
        )
        mock_session = MagicMock()
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_provider.sdk_session.return_value = mock_session

        with patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            from agenticops.monitor.cloudwatch import CloudWatchMonitor
            monitor = CloudWatchMonitor(acct)
            monitor._get_cloudwatch_client("us-east-1")

        mock_session.client.assert_called_with("cloudwatch", region_name="us-east-1")

    def test_get_logs_client_uses_provider(self):
        acct = SimpleNamespace(
            provider="aws", name="cw-test",
            credentials={}, regions=[], labels={},
        )
        mock_session = MagicMock()
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_provider.sdk_session.return_value = mock_session

        with patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            from agenticops.monitor.cloudwatch import CloudWatchMonitor
            monitor = CloudWatchMonitor(acct)
            monitor._get_logs_client("eu-west-1")

        mock_session.client.assert_called_with("logs", region_name="eu-west-1")

    def test_no_direct_boto3_import(self):
        import agenticops.monitor.cloudwatch as mod
        import inspect
        source = inspect.getsource(mod)
        header = source.split("class CloudWatchMonitor")[0]
        assert "import boto3" not in header


# ══════════════════════════════════════════════════════════════════
# 4. aws_tools assume_role uses provider layer
# ══════════════════════════════════════════════════════════════════


class TestAssumeRoleUsesProvider:
    def _get_assume_fn(self):
        """Get the raw assume_role function (unwrap @tool)."""
        import agenticops.tools.aws_tools as mod
        fn = mod.assume_role
        return fn.__wrapped__ if hasattr(fn, "__wrapped__") else fn

    def test_assume_role_resolves_via_provider(self, db_session, two_aws_accounts):
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_session = MagicMock()
        mock_provider.sdk_session.return_value = mock_session

        @contextmanager
        def fake_db():
            yield db_session

        import agenticops.tools.aws_tools as tools_mod
        tools_mod._session_cache.clear()

        with patch(_MODELS_DB_SESSION, fake_db), \
             patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            result = self._get_assume_fn()(
                account_id="111",
                role_arn="arn:aws:iam::111:role/Ops",
                region="us-east-1",
            )

        assert "Credentials resolved" in result
        mock_provider.resolve_credentials.assert_called_once()

    def test_assume_role_no_match_returns_error(self, db_session):
        @contextmanager
        def fake_db():
            yield db_session

        import agenticops.tools.aws_tools as tools_mod
        tools_mod._session_cache.clear()

        with patch(_MODELS_DB_SESSION, fake_db):
            result = self._get_assume_fn()(
                account_id="999",
                role_arn="arn:aws:iam::999:role/Nope",
                region="us-east-1",
            )

        assert "No enabled account found" in result

    def test_session_cache_populated_after_assume(self, db_session, two_aws_accounts):
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_session = MagicMock()
        mock_provider.sdk_session.return_value = mock_session

        @contextmanager
        def fake_db():
            yield db_session

        import agenticops.tools.aws_tools as tools_mod
        tools_mod._session_cache.clear()

        with patch(_MODELS_DB_SESSION, fake_db), \
             patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            self._get_assume_fn()(
                account_id="111",
                role_arn="arn:aws:iam::111:role/Ops",
                region="us-east-1",
            )

        assert "111:us-east-1" in tools_mod._session_cache
        assert tools_mod._session_cache["111:us-east-1"] is mock_session

    def test_no_direct_boto3_in_aws_tools(self):
        """aws_tools.py must not import boto3 at module level."""
        import agenticops.tools.aws_tools as mod
        import inspect
        source = inspect.getsource(mod)
        header = source.split("@tool")[0]
        assert "import boto3" not in header


# ══════════════════════════════════════════════════════════════════
# 5. ops_agent multi-account disambiguation
# ══════════════════════════════════════════════════════════════════


class TestOpsAgentMultiAccount:
    def test_legacy_ops_agent_removed(self):
        """Legacy OpsAgent module has been removed (tech debt cleanup)."""
        import pytest
        with pytest.raises(ImportError, match="removed"):
            import agenticops.agent  # noqa: F401


# ══════════════════════════════════════════════════════════════════
# 6. metadata_tools — no legacy AWSAccount fallback
# ══════════════════════════════════════════════════════════════════


class TestMetadataToolsNoLegacy:
    def test_no_aws_account_import(self):
        """metadata_tools must not import AWSAccount."""
        import agenticops.tools.metadata_tools as mod
        import inspect
        source = inspect.getsource(mod)
        import_section = source.split("@tool")[0]
        assert "AWSAccount" not in import_section

    def test_no_aws_resource_import(self):
        import agenticops.tools.metadata_tools as mod
        import inspect
        source = inspect.getsource(mod)
        import_section = source.split("@tool")[0]
        assert "AWSResource" not in import_section

    def test_get_enabled_accounts_empty_returns_error(self, db_session):
        from agenticops.tools.metadata_tools import get_enabled_accounts
        fn = get_enabled_accounts.__wrapped__ if hasattr(get_enabled_accounts, "__wrapped__") else get_enabled_accounts

        with patch("agenticops.tools.metadata_tools.get_session", return_value=db_session):
            result = fn()

        data = json.loads(result)
        assert "error" in data
        assert "No enabled accounts" in data["error"]

    def test_get_enabled_accounts_returns_multi(self, db_session, multi_cloud_accounts):
        from agenticops.tools.metadata_tools import get_enabled_accounts
        fn = get_enabled_accounts.__wrapped__ if hasattr(get_enabled_accounts, "__wrapped__") else get_enabled_accounts

        with patch("agenticops.tools.metadata_tools.get_session", return_value=db_session):
            result = fn()

        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 3
        providers = {a["provider"] for a in data}
        assert providers == {"aws", "azure", "gcp"}


# ══════════════════════════════════════════════════════════════════
# 7. graph/api uses provider layer (not bare boto3)
# ══════════════════════════════════════════════════════════════════


class TestGraphApiUsesProvider:
    def test_ensure_aws_session_uses_provider(self, db_session, one_aws_account):
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_session = MagicMock()
        mock_provider.sdk_session.return_value = mock_session

        @contextmanager
        def fake_db():
            yield db_session

        import agenticops.tools.aws_tools as tools_mod
        tools_mod._session_cache.clear()

        with patch(_MODELS_DB_SESSION, fake_db), \
             patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            from agenticops.graph.api import _ensure_aws_session
            _ensure_aws_session("us-east-1")

        mock_provider.resolve_credentials.assert_called_once()
        # Resolver caches under the account-addressed keys, NOT a "web:" key.
        assert not any(k.startswith("web:") for k in tools_mod._session_cache)
        assert any(k.endswith(":us-east-1") for k in tools_mod._session_cache)

    def test_ensure_aws_session_ambiguous_degrades(self, db_session, two_aws_accounts):
        # Two enabled accounts → default resolution is ambiguous; the pre-warm
        # logs-and-degrades (no raise, no cache write) rather than guessing.
        @contextmanager
        def fake_db():
            yield db_session

        import agenticops.tools.aws_tools as tools_mod
        tools_mod._session_cache.clear()

        with patch(_MODELS_DB_SESSION, fake_db):
            from agenticops.graph.api import _ensure_aws_session
            _ensure_aws_session("us-east-1")  # must not raise

        assert tools_mod._session_cache == {}

    def test_no_direct_boto3_in_ensure_session(self):
        import agenticops.graph.api as mod
        import inspect
        source = inspect.getsource(mod)
        fn_start = source.index("def _ensure_aws_session")
        fn_end = source.index("def _build_vpc_graph")
        fn_source = source[fn_start:fn_end]
        assert "import boto3" not in fn_source


# ══════════════════════════════════════════════════════════════════
# 8. cloudwatch_provider uses provider layer
# ══════════════════════════════════════════════════════════════════


class TestCloudWatchProviderIntegration:
    def test_no_aws_tools_session_cache_steal(self):
        """cloudwatch_provider must NOT import from aws_tools._session_cache."""
        import agenticops.integrations.cloudwatch_provider as mod
        import inspect
        source = inspect.getsource(mod)
        assert "from agenticops.tools.aws_tools import _session_cache" not in source

    def test_get_client_uses_provider(self, db_session, two_aws_accounts):
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_session = MagicMock()
        mock_provider.sdk_session.return_value = mock_session
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        @contextmanager
        def fake_db():
            yield db_session

        with patch(_MODELS_DB_SESSION, fake_db), \
             patch(_PROVIDERS_PKG, return_value=mock_provider), \
             patch(_PROVIDERS_BASE, return_value=mock_provider):
            from agenticops.integrations.cloudwatch_provider import CloudWatchProvider
            cw = CloudWatchProvider(region="us-east-1")
            client = cw._get_client("cloudwatch")

        mock_provider.resolve_credentials.assert_called_once()
        mock_session.client.assert_called_with("cloudwatch", region_name="us-east-1")


# ══════════════════════════════════════════════════════════════════
# 9. Full flow: multi-account scan via scanner/engine
# ══════════════════════════════════════════════════════════════════


class TestScannerEngineMultiAccount:
    def test_scan_loads_multiple_accounts(self, db_session, multi_cloud_accounts):
        @contextmanager
        def fake_db():
            yield db_session

        with patch(_MODELS_DB_SESSION, fake_db):
            from agenticops.scanner.engine import _load_accounts
            accounts = _load_accounts()

        assert len(accounts) == 3
        providers = {a.provider for a in accounts}
        assert providers == {"aws", "azure", "gcp"}

    def test_get_provider_and_tool_uses_provider_layer(self):
        acct = SimpleNamespace(
            id=1, name="test-aws", provider="aws",
            credentials={}, regions=["us-east-1"], labels={},
        )
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_tool = MagicMock()
        mock_provider.cli_tool.return_value = mock_tool

        with patch("agenticops.providers.base.get_provider", return_value=mock_provider):
            from agenticops.scanner.engine import _get_provider_and_tool
            result = _get_provider_and_tool(acct)

        assert result is not None
        provider, tool = result
        assert provider is mock_provider
        assert tool is mock_tool
        mock_provider.resolve_credentials.assert_called_once()
