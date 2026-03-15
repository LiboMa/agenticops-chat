# Multi-Cloud Provider Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace AWS-only account/resource models with a multi-cloud provider abstraction supporting AWS, Azure, GCP, and Alicloud with parallel multi-account scanning.

**Architecture:** Terraform-style credential chain per provider. `CloudProvider` ABC with 4 implementations. Unified `CloudAccount`/`CloudResource` tables. CLI-tool-driven resource discovery. Manual migration in `init_db()` (no Alembic — project uses inline ALTER TABLE pattern).

**Tech Stack:** Python, SQLAlchemy, FastAPI, React/TypeScript, boto3, azure-identity, google-cloud, alibabacloud-credentials

**Spec:** `docs/superpowers/specs/2026-03-14-multi-cloud-provider-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/agenticops/providers/__init__.py` | Package init, re-exports `get_provider`, `CloudProvider` |
| `src/agenticops/providers/base.py` | `CloudProvider` ABC, `PROVIDERS` registry, `get_provider()`, session cache |
| `src/agenticops/providers/aws.py` | `AWSProvider`: AssumeRole / profile / static / default chain, `aws` CLI tool |
| `src/agenticops/providers/azure.py` | `AzureProvider`: Service Principal / CLI chain, `az` CLI tool |
| `src/agenticops/providers/gcp.py` | `GCPProvider`: SA key / ADC chain, `gcloud` CLI tool |
| `src/agenticops/providers/alicloud.py` | `AlicloudProvider`: AssumeRole / static / profile / ECS chain, `aliyun` CLI tool |
| `tests/test_providers.py` | Unit tests for all providers + credential chain |
| `tests/test_cloud_models.py` | Unit tests for CloudAccount/CloudResource models |
| `tests/test_multi_cloud_api.py` | Unit tests for new account API endpoints |

### Modified Files
| File | Change |
|------|--------|
| `src/agenticops/models.py:93-145` | Replace `AWSAccount`/`AWSResource` with `CloudAccount`/`CloudResource`; add `account_id` FK to `HealthIssue`; update `MonitoringConfig` FK |
| `src/agenticops/tools/metadata_tools.py:46-205` | `get_active_account()` → `get_enabled_accounts()`; `save_resources()` writes `CloudResource` |
| `src/agenticops/tools/aws_tools.py` | Remove auth logic (moves to providers/aws.py); keep scan helpers as optional AWS-specific tools |
| `src/agenticops/tools/aws_cli_tool.py` | Extract `_classify_command()` and `_execute_cli()` into reusable patterns for providers |
| `src/agenticops/agents/scan_agent.py:46-159` | Multi-cloud prompt; dynamic tool injection from providers |
| `src/agenticops/web/app.py:76-108,1384-1450` | New schemas (`AccountCreate`/`AccountResponse` with `provider`); updated endpoints; new `/test` endpoint |
| `src/agenticops/web/frontend/src/pages/Accounts.tsx` | Provider selector; dynamic credential form; provider column |
| `src/agenticops/web/frontend/src/api/types.ts` | Updated `Account`/`AccountCreate` types |
| `src/agenticops/web/frontend/src/hooks/useAccounts.ts` | No change needed (generic CRUD) |
| `src/agenticops/config.py` | Add `default_regions` dict setting |
| `src/agenticops/cli/main.py` | `AWSAccount` → `CloudAccount` in queries and slash commands |
| `src/agenticops/cli/init_helpers.py` | Add provider selection to account init flow |
| `src/agenticops/pipeline/health_patrol.py` | Update account queries |
| `src/agenticops/pipeline/orchestrator.py` | Update account references |
| `src/agenticops/chat/preprocessor.py` | Update resource/account references |
| `src/agenticops/integrations/cloudwatch_provider.py` | Update account FK import |
| `src/agenticops/graph/api.py` | Update resource queries |
| `src/agenticops/agents/rca_agent.py` | Replace `aws_cli_tool` import with provider-injected CLI tool |
| `src/agenticops/agents/sre_agent.py` | Replace `aws_cli_tool` import with provider-injected CLI tool |
| `src/agenticops/agents/executor_agent.py` | Replace `aws_cli_tool` import with provider-injected CLI tool |
| `src/agenticops/agents/detect_agent.py` | Replace `aws_cli_tool` import with provider-injected CLI tool |
| `src/agenticops/scheduler/scheduler.py` | Update `AWSAccount` → `CloudAccount` queries |
| `src/agenticops/report/generator.py` | Update `AWSAccount`/`AWSResource` references |
| `src/agenticops/scan/scanner.py` | Update account/resource references |
| `src/agenticops/monitor/collector.py` | Update account references |
| `src/agenticops/monitor/cloudwatch.py` | Update account references |
| `src/agenticops/agent/ops_agent.py` | Update `AWSAccount`/`AWSResource` references |
| `src/agenticops/detect/detector.py` | Update `AWSResource` queries |
| `src/agenticops/analyze/rca.py` | Update `AWSAccount`/`AWSResource` references |

---

## Chunk 1: Database Models & Migration

### Task 1: Create CloudAccount and CloudResource models

**Files:**
- Modify: `src/agenticops/models.py:93-145`
- Test: `tests/test_cloud_models.py` (new)

- [ ] **Step 1: Write failing tests for CloudAccount model**

```python
# tests/test_cloud_models.py
import pytest
from datetime import datetime
from agenticops.models import CloudAccount, CloudResource, init_db
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        yield session


def test_cloud_account_create(db):
    acct = CloudAccount(
        name="aws-prod",
        provider="aws",
        is_enabled=True,
        credentials={"role_arn": "arn:aws:iam::123456789012:role/ops", "account_id": "123456789012"},
        regions=["us-east-1", "us-west-2"],
        labels={"env": "prod"},
    )
    db.add(acct)
    db.commit()
    assert acct.id is not None
    assert acct.provider == "aws"
    assert acct.is_enabled is True
    assert acct.credentials["role_arn"] == "arn:aws:iam::123456789012:role/ops"


def test_cloud_account_multiple_enabled(db):
    aws = CloudAccount(name="aws-prod", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])
    azure = CloudAccount(name="azure-prod", provider="azure", is_enabled=True, credentials={}, regions=["eastus"])
    db.add_all([aws, azure])
    db.commit()
    enabled = db.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()
    assert len(enabled) == 2


def test_cloud_account_unique_name(db):
    a1 = CloudAccount(name="dup", provider="aws", credentials={}, regions=[])
    a2 = CloudAccount(name="dup", provider="azure", credentials={}, regions=[])
    db.add(a1)
    db.commit()
    db.add(a2)
    with pytest.raises(Exception):
        db.commit()


def test_cloud_resource_create(db):
    acct = CloudAccount(name="aws-prod", provider="aws", credentials={}, regions=["us-east-1"])
    db.add(acct)
    db.commit()

    res = CloudResource(
        account_id=acct.id,
        provider="aws",
        region="us-east-1",
        resource_type="compute",
        resource_id="arn:aws:ec2:us-east-1:123456789012:instance/i-abc123",
        name="web-server-1",
        tags={"Name": "web-server-1"},
        raw_data={"InstanceId": "i-abc123", "InstanceType": "t3.medium"},
        status="running",
        managed=True,
    )
    db.add(res)
    db.commit()
    assert res.id is not None
    assert res.account.name == "aws-prod"


def test_cloud_resource_unique_constraint(db):
    acct = CloudAccount(name="test", provider="aws", credentials={}, regions=[])
    db.add(acct)
    db.commit()

    r1 = CloudResource(account_id=acct.id, provider="aws", resource_id="arn:123", resource_type="compute", region="us-east-1", name="a")
    r2 = CloudResource(account_id=acct.id, provider="aws", resource_id="arn:123", resource_type="compute", region="us-east-1", name="b")
    db.add(r1)
    db.commit()
    db.add(r2)
    with pytest.raises(Exception):
        db.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cloud_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'CloudAccount'`

- [ ] **Step 3: Implement CloudAccount and CloudResource models**

In `src/agenticops/models.py`, add new models after the existing `AWSAccount`/`AWSResource` (keep old models temporarily for migration):

```python
# After line 145 (after AWSResource), add:

class CloudAccount(Base):
    __tablename__ = "cloud_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(20))  # aws | azure | gcp | alicloud
    is_enabled: Mapped[bool] = mapped_column(default=True)
    credentials: Mapped[dict] = mapped_column(JSON, default=dict)
    regions: Mapped[list] = mapped_column(JSON, default=list)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    resources: Mapped[list["CloudResource"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    monitoring_configs: Mapped[list["MonitoringConfig"]] = relationship(back_populates="cloud_account")


class CloudResource(Base):
    __tablename__ = "cloud_resources"
    __table_args__ = (
        UniqueConstraint("account_id", "provider", "resource_id", name="uq_cloud_resource"),
        Index("idx_cloud_resource_provider", "provider"),
        Index("idx_cloud_resource_type_region", "resource_type", "region"),
        Index("idx_cloud_resource_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"))
    provider: Mapped[str] = mapped_column(String(20))
    region: Mapped[str] = mapped_column(String(30))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(200), default="")
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    managed: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=datetime.utcnow, nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # Relationships
    account: Mapped["CloudAccount"] = relationship(back_populates="resources")
```

Also add `account_id` to `HealthIssue` model (around line 326):

```python
    # Add after existing fields in HealthIssue:
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=True)
```

Update `MonitoringConfig` (line 158) — add a second relationship field:

```python
    # Add to MonitoringConfig:
    cloud_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=True)
    cloud_account: Mapped[Optional["CloudAccount"]] = relationship(back_populates="monitoring_configs")
```

- [ ] **Step 4: Add migration logic to init_db()**

In `src/agenticops/models.py` `init_db()` function, add migration steps for creating new tables and migrating data from old tables. Follow the existing pattern of checking `inspect(engine)`:

```python
# Add inside init_db(), after existing migration blocks:

inspector = inspect(engine)
existing_tables = inspector.get_table_names()

# Create cloud_accounts if not exists
if "cloud_accounts" not in existing_tables:
    CloudAccount.__table__.create(engine)

# Create cloud_resources if not exists
if "cloud_resources" not in existing_tables:
    CloudResource.__table__.create(engine)

# Migrate AWSAccount → CloudAccount if old table exists and new is empty
if "aws_accounts" in existing_tables and "cloud_accounts" in existing_tables:
    with Session(engine) as session:
        if session.query(CloudAccount).count() == 0:
            old_accounts = session.execute(text("SELECT * FROM aws_accounts")).fetchall()
            for row in old_accounts:
                creds = {"account_id": row.account_id, "role_arn": row.role_arn}
                if row.external_id:
                    creds["external_id"] = row.external_id
                ca = CloudAccount(
                    name=row.name,
                    provider="aws",
                    is_enabled=row.is_active,
                    credentials=creds,
                    regions=json.loads(row.regions) if isinstance(row.regions, str) else row.regions,
                    labels={},
                    created_at=row.created_at,
                    last_scanned_at=row.last_scanned_at,
                )
                session.add(ca)
            session.commit()

# Migrate AWSResource → CloudResource if old table exists and new is empty
if "_legacy_aws_resources" not in existing_tables and "aws_resources" in existing_tables and "cloud_resources" in existing_tables:
    with Session(engine) as session:
        if session.query(CloudResource).count() == 0:
            # Build account_id mapping: old aws_accounts.id → new cloud_accounts.id
            id_map = {}
            old_accounts = session.execute(text("SELECT id, name FROM aws_accounts")).fetchall()
            for old in old_accounts:
                new = session.query(CloudAccount).filter_by(name=old.name).first()
                if new:
                    id_map[old.id] = new.id

            old_resources = session.execute(text("SELECT * FROM aws_resources")).fetchall()
            for row in old_resources:
                new_account_id = id_map.get(row.account_id)
                if not new_account_id:
                    continue
                cr = CloudResource(
                    account_id=new_account_id,
                    provider="aws",
                    region=row.region,
                    resource_type=row.resource_type,
                    resource_id=row.resource_arn or row.resource_id,
                    name=row.resource_name if hasattr(row, "resource_name") else "",
                    tags=json.loads(row.tags) if isinstance(row.tags, str) else (row.tags or {}),
                    raw_data=json.loads(row.resource_metadata) if isinstance(row.resource_metadata, str) else (row.resource_metadata or {}),
                    status=row.status or "unknown",
                    managed=row.managed if hasattr(row, "managed") else True,
                    created_at=row.created_at,
                    updated_at=row.updated_at if hasattr(row, "updated_at") else None,
                )
                session.add(cr)
            session.commit()

# Add account_id column to health_issues if missing
if "health_issues" in existing_tables:
    columns = [c["name"] for c in inspector.get_columns("health_issues")]
    if "account_id" not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE health_issues ADD COLUMN account_id INTEGER REFERENCES cloud_accounts(id)"))
            conn.commit()

# Add cloud_account_id to monitoring_configs if missing
if "monitoring_configs" in existing_tables:
    columns = [c["name"] for c in inspector.get_columns("monitoring_configs")]
    if "cloud_account_id" not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE monitoring_configs ADD COLUMN cloud_account_id INTEGER REFERENCES cloud_accounts(id)"))
            conn.commit()

# Rename old tables (keep for rollback)
if "aws_accounts" in existing_tables:
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE aws_accounts RENAME TO _legacy_aws_accounts"))
            conn.commit()
        except Exception:
            pass  # already renamed

if "aws_resources" in existing_tables:
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE aws_resources RENAME TO _legacy_aws_resources"))
            conn.commit()
        except Exception:
            pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cloud_models.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/models.py tests/test_cloud_models.py
git commit -m "feat(models): add CloudAccount and CloudResource with migration from AWSAccount"
```

---

## Chunk 2: Provider Abstraction Layer

### Task 2: Create CloudProvider ABC and session cache

**Files:**
- Create: `src/agenticops/providers/__init__.py`
- Create: `src/agenticops/providers/base.py`
- Test: `tests/test_providers.py` (new)

- [ ] **Step 1: Write failing tests for base provider**

```python
# tests/test_providers.py
import pytest
from unittest.mock import MagicMock
from agenticops.providers.base import (
    CloudProvider, PROVIDERS, get_provider,
    get_cached_session, set_cached_session, _session_cache, _cache_lock
)


def test_providers_registry_has_all_clouds():
    assert set(PROVIDERS.keys()) == {"aws", "azure", "gcp", "alicloud"}


def test_get_provider_returns_correct_type():
    account = MagicMock()
    account.provider = "aws"
    account.credentials = {}
    account.regions = ["us-east-1"]
    p = get_provider(account)
    assert p.provider_type == "aws"


def test_get_provider_unknown_raises():
    account = MagicMock()
    account.provider = "oracle"
    with pytest.raises(KeyError):
        get_provider(account)


def test_session_cache_set_and_get():
    _session_cache.clear()
    set_cached_session("aws:123:us-east-1", "fake-session")
    assert get_cached_session("aws:123:us-east-1") == "fake-session"
    assert get_cached_session("aws:123:us-west-2") is None
    _session_cache.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agenticops.providers'`

- [ ] **Step 3: Implement base.py**

```python
# src/agenticops/providers/__init__.py
from .base import CloudProvider, PROVIDERS, get_provider, get_cached_session, set_cached_session

__all__ = ["CloudProvider", "PROVIDERS", "get_provider", "get_cached_session", "set_cached_session"]
```

```python
# src/agenticops/providers/base.py
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any, Callable

from agenticops.models import CloudAccount

_session_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()


def get_cached_session(key: str) -> Any | None:
    with _cache_lock:
        return _session_cache.get(key)


def set_cached_session(key: str, session: Any):
    with _cache_lock:
        _session_cache[key] = session


class CloudProvider(ABC):
    """Terraform-style cloud provider with credential chain."""

    def __init__(self, account: CloudAccount):
        self.account = account

    @abstractmethod
    def resolve_credentials(self) -> bool:
        """Walk credential chain by priority. Return True on success."""

    @abstractmethod
    def cli_tool(self) -> Callable:
        """Return a @tool function: (command: str) -> str, bound to this account."""

    @abstractmethod
    def sdk_session(self) -> Any:
        """Return authenticated SDK session."""

    @property
    @abstractmethod
    def provider_type(self) -> str: ...


# Registry — imported lazily to avoid circular imports
def _get_providers() -> dict[str, type[CloudProvider]]:
    from .aws import AWSProvider
    from .azure import AzureProvider
    from .gcp import GCPProvider
    from .alicloud import AlicloudProvider
    return {
        "aws": AWSProvider,
        "azure": AzureProvider,
        "gcp": GCPProvider,
        "alicloud": AlicloudProvider,
    }


# Eager init on first access
PROVIDERS: dict[str, type[CloudProvider]] = {}


def get_provider(account: CloudAccount) -> CloudProvider:
    global PROVIDERS
    if not PROVIDERS:
        PROVIDERS.update(_get_providers())
    return PROVIDERS[account.provider](account)
```

- [ ] **Step 4: Run session cache test to verify it passes**

Run: `python -m pytest tests/test_providers.py::test_session_cache_set_and_get -v`
Expected: PASS

Note: `test_providers_registry_has_all_clouds` and `test_get_provider_returns_correct_type` will fail until all 4 providers are implemented (Tasks 3-6). `test_get_provider_unknown_raises` should also pass now. Run these two only:

Run: `python -m pytest tests/test_providers.py::test_session_cache_set_and_get tests/test_providers.py::test_get_provider_unknown_raises -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/providers/
git commit -m "feat(providers): add CloudProvider ABC, session cache, and registry"
```

### Task 3: Implement AWSProvider

**Files:**
- Create: `src/agenticops/providers/aws.py`
- Test: `tests/test_providers.py` (add tests)

- [ ] **Step 1: Write failing tests for AWSProvider credential chain**

Add to `tests/test_providers.py`:

```python
from unittest.mock import patch, MagicMock
from agenticops.providers.aws import AWSProvider
from agenticops.providers.base import _session_cache


@pytest.fixture
def aws_account():
    acct = MagicMock()
    acct.name = "aws-prod"
    acct.provider = "aws"
    acct.regions = ["us-east-1"]
    return acct


def test_aws_provider_type(aws_account):
    aws_account.credentials = {}
    p = AWSProvider(aws_account)
    assert p.provider_type == "aws"


def test_aws_resolve_credentials_assume_role(aws_account):
    aws_account.credentials = {
        "role_arn": "arn:aws:iam::123456789012:role/ops",
        "account_id": "123456789012",
    }
    p = AWSProvider(aws_account)
    with patch("agenticops.providers.aws.boto3") as mock_boto3:
        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA...",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }
        mock_boto3.Session.return_value = MagicMock()
        result = p.resolve_credentials()
        assert result is True
        mock_sts.assume_role.assert_called_once()


def test_aws_resolve_credentials_profile(aws_account):
    aws_account.credentials = {"profile_name": "my-profile"}
    p = AWSProvider(aws_account)
    with patch("agenticops.providers.aws.boto3") as mock_boto3:
        mock_boto3.Session.return_value = MagicMock()
        result = p.resolve_credentials()
        assert result is True
        mock_boto3.Session.assert_called_with(profile_name="my-profile")


def test_aws_resolve_credentials_default_chain(aws_account):
    aws_account.credentials = {}
    p = AWSProvider(aws_account)
    with patch("agenticops.providers.aws.boto3") as mock_boto3:
        mock_boto3.Session.return_value = MagicMock()
        result = p.resolve_credentials()
        assert result is True
        mock_boto3.Session.assert_called_with()


def test_aws_cli_tool_returns_callable(aws_account):
    aws_account.credentials = {}
    p = AWSProvider(aws_account)
    with patch("agenticops.providers.aws.boto3"):
        p.resolve_credentials()
    tool_fn = p.cli_tool()
    assert callable(tool_fn)
    assert "aws_prod" in tool_fn.__name__
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_providers.py -k "aws" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agenticops.providers.aws'`

- [ ] **Step 3: Implement AWSProvider**

```python
# src/agenticops/providers/aws.py
from __future__ import annotations

import json
import logging
import shlex
import subprocess
from typing import Any, Callable

import boto3
from botocore.exceptions import ClientError

from agenticops.models import CloudAccount
from .base import CloudProvider, get_cached_session, set_cached_session

logger = logging.getLogger(__name__)

# CLI security tiers — reuse from aws_cli_tool.py patterns
BLOCKED_PATTERNS = [
    "iam create-user", "iam delete-user", "organizations move-account",
    "ec2 terminate-instances", "rds delete-db-instance --skip-final-snapshot",
    "s3 rm --recursive", "s3 rb --force",
]
WRITE_PREFIXES = [
    "create-", "delete-", "modify-", "update-", "put-", "start-", "stop-",
    "reboot-", "terminate-", "attach-", "detach-", "enable-", "disable-",
]


class AWSProvider(CloudProvider):
    def __init__(self, account: CloudAccount):
        super().__init__(account)
        self._boto_session: boto3.Session | None = None

    @property
    def provider_type(self) -> str:
        return "aws"

    def resolve_credentials(self) -> bool:
        creds = self.account.credentials or {}
        try:
            if creds.get("role_arn"):
                self._boto_session = self._assume_role(creds)
            elif creds.get("profile_name"):
                self._boto_session = boto3.Session(profile_name=creds["profile_name"])
            elif creds.get("access_key"):
                self._boto_session = boto3.Session(
                    aws_access_key_id=creds["access_key"],
                    aws_secret_access_key=creds["secret_key"],
                    aws_session_token=creds.get("session_token"),
                )
            else:
                # Default chain: env vars → config file → instance metadata
                self._boto_session = boto3.Session()
            return True
        except Exception as e:
            logger.error("AWS credential resolution failed for %s: %s", self.account.name, e)
            return False

    def _assume_role(self, creds: dict) -> boto3.Session:
        region = self.account.regions[0] if self.account.regions else "us-east-1"
        cache_key = f"aws:{creds.get('account_id', '')}:{region}"
        cached = get_cached_session(cache_key)
        if cached:
            return cached

        sts = boto3.client("sts", region_name=region)
        params = {"RoleArn": creds["role_arn"], "RoleSessionName": "agenticops", "DurationSeconds": 3600}
        if creds.get("external_id"):
            params["ExternalId"] = creds["external_id"]
        resp = sts.assume_role(**params)
        c = resp["Credentials"]
        session = boto3.Session(
            aws_access_key_id=c["AccessKeyId"],
            aws_secret_access_key=c["SecretAccessKey"],
            aws_session_token=c["SessionToken"],
        )
        set_cached_session(cache_key, session)
        return session

    def sdk_session(self) -> Any:
        if not self._boto_session:
            self.resolve_credentials()
        return self._boto_session

    def cli_tool(self) -> Callable:
        account_name = self.account.name.replace("-", "_").replace(" ", "_")
        tool_name = f"run_aws_cli_{account_name}"

        # Capture in closure
        session = self.sdk_session()
        env_vars = {}
        if session:
            try:
                creds = session.get_credentials()
                if creds:
                    frozen = creds.get_frozen_credentials()
                    env_vars = {
                        "AWS_ACCESS_KEY_ID": frozen.access_key,
                        "AWS_SECRET_ACCESS_KEY": frozen.secret_key,
                    }
                    if frozen.token:
                        env_vars["AWS_SESSION_TOKEN"] = frozen.token
                if session.region_name:
                    env_vars["AWS_DEFAULT_REGION"] = session.region_name
            except Exception:
                pass

        def _run_cli(command: str) -> str:
            if not command.startswith("aws "):
                return "Error: command must start with 'aws '"
            for blocked in BLOCKED_PATTERNS:
                if blocked in command:
                    return f"Error: blocked command pattern: {blocked}"
            import os
            run_env = {**os.environ, **env_vars}
            if "--output" not in command:
                command += " --output json"
            try:
                result = subprocess.run(
                    shlex.split(command), capture_output=True, text=True,
                    timeout=30, env=run_env,
                )
                if result.returncode != 0:
                    return f"Error: {result.stderr[:2000]}"
                return result.stdout[:4000]
            except subprocess.TimeoutExpired:
                return "Error: command timed out after 30s"
            except Exception as e:
                return f"Error: {e}"

        _run_cli.__name__ = tool_name
        _run_cli.__doc__ = f"Execute AWS CLI command for account '{self.account.name}'. Usage: run with 'aws <service> <command> [args]'."
        return _run_cli
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_providers.py -k "aws" -v`
Expected: All AWS tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/providers/aws.py tests/test_providers.py
git commit -m "feat(providers): implement AWSProvider with Terraform-style credential chain"
```

### Task 4: Implement AzureProvider

**Files:**
- Create: `src/agenticops/providers/azure.py`
- Test: `tests/test_providers.py` (add tests)

- [ ] **Step 1: Write failing tests for AzureProvider**

Add to `tests/test_providers.py`:

```python
from agenticops.providers.azure import AzureProvider


@pytest.fixture
def azure_account():
    acct = MagicMock()
    acct.name = "azure-prod"
    acct.provider = "azure"
    acct.regions = ["eastus"]
    return acct


def test_azure_provider_type(azure_account):
    azure_account.credentials = {}
    p = AzureProvider(azure_account)
    assert p.provider_type == "azure"


def test_azure_resolve_credentials_service_principal(azure_account):
    azure_account.credentials = {
        "subscription_id": "sub-xxx",
        "tenant_id": "t-xxx",
        "client_id": "c-xxx",
        "client_secret": "secret",
    }
    p = AzureProvider(azure_account)
    with patch("agenticops.providers.azure.ClientSecretCredential") as mock_cred:
        mock_cred.return_value = MagicMock()
        result = p.resolve_credentials()
        assert result is True
        mock_cred.assert_called_once_with(tenant_id="t-xxx", client_id="c-xxx", client_secret="secret")


def test_azure_resolve_credentials_cli_fallback(azure_account):
    azure_account.credentials = {}
    p = AzureProvider(azure_account)
    with patch("agenticops.providers.azure.AzureCliCredential") as mock_cred:
        mock_cred.return_value = MagicMock()
        result = p.resolve_credentials()
        assert result is True
        mock_cred.assert_called_once()


def test_azure_cli_tool_returns_callable(azure_account):
    azure_account.credentials = {}
    p = AzureProvider(azure_account)
    with patch("agenticops.providers.azure.AzureCliCredential"):
        p.resolve_credentials()
    tool_fn = p.cli_tool()
    assert callable(tool_fn)
    assert "azure_prod" in tool_fn.__name__
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_providers.py -k "azure" -v`
Expected: FAIL

- [ ] **Step 3: Implement AzureProvider**

```python
# src/agenticops/providers/azure.py
from __future__ import annotations

import logging
import os
import shlex
import subprocess
from typing import Any, Callable

from agenticops.models import CloudAccount
from .base import CloudProvider

logger = logging.getLogger(__name__)

try:
    from azure.identity import ClientSecretCredential, AzureCliCredential
except ImportError:
    ClientSecretCredential = None
    AzureCliCredential = None


class AzureProvider(CloudProvider):
    def __init__(self, account: CloudAccount):
        super().__init__(account)
        self._credential = None
        self._subscription_id: str | None = None

    @property
    def provider_type(self) -> str:
        return "azure"

    def resolve_credentials(self) -> bool:
        creds = self.account.credentials or {}
        self._subscription_id = creds.get("subscription_id") or os.environ.get("ARM_SUBSCRIPTION_ID")
        try:
            if all(creds.get(k) for k in ("client_id", "client_secret", "tenant_id")):
                self._credential = ClientSecretCredential(
                    tenant_id=creds["tenant_id"],
                    client_id=creds["client_id"],
                    client_secret=creds["client_secret"],
                )
            elif os.environ.get("ARM_CLIENT_ID") and os.environ.get("ARM_CLIENT_SECRET"):
                self._credential = ClientSecretCredential(
                    tenant_id=os.environ["ARM_TENANT_ID"],
                    client_id=os.environ["ARM_CLIENT_ID"],
                    client_secret=os.environ["ARM_CLIENT_SECRET"],
                )
            else:
                self._credential = AzureCliCredential()
            return True
        except Exception as e:
            logger.error("Azure credential resolution failed for %s: %s", self.account.name, e)
            return False

    def sdk_session(self) -> Any:
        if not self._credential:
            self.resolve_credentials()
        return self._credential

    def cli_tool(self) -> Callable:
        account_name = self.account.name.replace("-", "_").replace(" ", "_")
        tool_name = f"run_az_cli_{account_name}"
        subscription_id = self._subscription_id

        def _run_cli(command: str) -> str:
            if not command.startswith("az "):
                return "Error: command must start with 'az '"
            cmd = command
            if subscription_id and "--subscription" not in cmd:
                cmd += f" --subscription {subscription_id}"
            if "--output" not in cmd:
                cmd += " --output json"
            try:
                result = subprocess.run(
                    shlex.split(cmd), capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    return f"Error: {result.stderr[:2000]}"
                return result.stdout[:4000]
            except subprocess.TimeoutExpired:
                return "Error: command timed out after 30s"
            except Exception as e:
                return f"Error: {e}"

        _run_cli.__name__ = tool_name
        _run_cli.__doc__ = f"Execute Azure CLI command for account '{self.account.name}'. Usage: run with 'az <group> <command> [args]'."
        return _run_cli
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_providers.py -k "azure" -v`
Expected: All Azure tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/providers/azure.py tests/test_providers.py
git commit -m "feat(providers): implement AzureProvider with Service Principal and CLI credential chain"
```

### Task 5: Implement GCPProvider

**Files:**
- Create: `src/agenticops/providers/gcp.py`
- Test: `tests/test_providers.py` (add tests)

- [ ] **Step 1: Write failing tests for GCPProvider**

Add to `tests/test_providers.py`:

```python
from agenticops.providers.gcp import GCPProvider


@pytest.fixture
def gcp_account():
    acct = MagicMock()
    acct.name = "gcp-dev"
    acct.provider = "gcp"
    acct.regions = ["us-central1"]
    return acct


def test_gcp_provider_type(gcp_account):
    gcp_account.credentials = {}
    p = GCPProvider(gcp_account)
    assert p.provider_type == "gcp"


def test_gcp_resolve_credentials_service_account_key(gcp_account):
    gcp_account.credentials = {
        "project_id": "my-project",
        "service_account_key": {"type": "service_account", "project_id": "my-project"},
    }
    p = GCPProvider(gcp_account)
    with patch("agenticops.providers.gcp.service_account") as mock_sa:
        mock_sa.Credentials.from_service_account_info.return_value = MagicMock()
        result = p.resolve_credentials()
        assert result is True
        mock_sa.Credentials.from_service_account_info.assert_called_once()


def test_gcp_resolve_credentials_adc_fallback(gcp_account):
    gcp_account.credentials = {}
    p = GCPProvider(gcp_account)
    with patch("agenticops.providers.gcp.google_auth_default") as mock_default:
        mock_default.return_value = (MagicMock(), "auto-project")
        result = p.resolve_credentials()
        assert result is True


def test_gcp_cli_tool_returns_callable(gcp_account):
    gcp_account.credentials = {"project_id": "my-project"}
    p = GCPProvider(gcp_account)
    with patch("agenticops.providers.gcp.google_auth_default", return_value=(MagicMock(), "p")):
        p.resolve_credentials()
    tool_fn = p.cli_tool()
    assert callable(tool_fn)
    assert "gcp_dev" in tool_fn.__name__
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_providers.py -k "gcp" -v`
Expected: FAIL

- [ ] **Step 3: Implement GCPProvider**

```python
# src/agenticops/providers/gcp.py
from __future__ import annotations

import logging
import os
import shlex
import subprocess
from typing import Any, Callable

from agenticops.models import CloudAccount
from .base import CloudProvider

logger = logging.getLogger(__name__)

try:
    from google.oauth2 import service_account
    from google.auth import default as google_auth_default
except ImportError:
    service_account = None
    google_auth_default = None


class GCPProvider(CloudProvider):
    def __init__(self, account: CloudAccount):
        super().__init__(account)
        self._credential = None
        self._project_id: str | None = None

    @property
    def provider_type(self) -> str:
        return "gcp"

    def resolve_credentials(self) -> bool:
        creds = self.account.credentials or {}
        self._project_id = creds.get("project_id") or os.environ.get("GOOGLE_PROJECT")
        try:
            if creds.get("service_account_key"):
                self._credential = service_account.Credentials.from_service_account_info(
                    creds["service_account_key"]
                )
                if not self._project_id:
                    self._project_id = creds["service_account_key"].get("project_id")
            else:
                self._credential, project = google_auth_default()
                if not self._project_id:
                    self._project_id = project
            return True
        except Exception as e:
            logger.error("GCP credential resolution failed for %s: %s", self.account.name, e)
            return False

    def sdk_session(self) -> Any:
        if not self._credential:
            self.resolve_credentials()
        return self._credential

    def cli_tool(self) -> Callable:
        account_name = self.account.name.replace("-", "_").replace(" ", "_")
        tool_name = f"run_gcloud_{account_name}"
        project_id = self._project_id

        def _run_cli(command: str) -> str:
            if not command.startswith("gcloud "):
                return "Error: command must start with 'gcloud '"
            cmd = command
            if project_id and "--project" not in cmd:
                cmd += f" --project {project_id}"
            if "--format" not in cmd:
                cmd += " --format json"
            try:
                result = subprocess.run(
                    shlex.split(cmd), capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    return f"Error: {result.stderr[:2000]}"
                return result.stdout[:4000]
            except subprocess.TimeoutExpired:
                return "Error: command timed out after 30s"
            except Exception as e:
                return f"Error: {e}"

        _run_cli.__name__ = tool_name
        _run_cli.__doc__ = f"Execute gcloud CLI command for account '{self.account.name}'. Usage: run with 'gcloud <group> <command> [args]'."
        return _run_cli
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_providers.py -k "gcp" -v`
Expected: All GCP tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/providers/gcp.py tests/test_providers.py
git commit -m "feat(providers): implement GCPProvider with SA key and ADC credential chain"
```

### Task 6: Implement AlicloudProvider

**Files:**
- Create: `src/agenticops/providers/alicloud.py`
- Test: `tests/test_providers.py` (add tests)

- [ ] **Step 1: Write failing tests for AlicloudProvider**

Add to `tests/test_providers.py`:

```python
from agenticops.providers.alicloud import AlicloudProvider


@pytest.fixture
def alicloud_account():
    acct = MagicMock()
    acct.name = "ali-prod"
    acct.provider = "alicloud"
    acct.regions = ["cn-hangzhou"]
    return acct


def test_alicloud_provider_type(alicloud_account):
    alicloud_account.credentials = {}
    p = AlicloudProvider(alicloud_account)
    assert p.provider_type == "alicloud"


def test_alicloud_resolve_credentials_static(alicloud_account):
    alicloud_account.credentials = {
        "access_key_id": "LTAI...",
        "access_key_secret": "secret",
    }
    p = AlicloudProvider(alicloud_account)
    result = p.resolve_credentials()
    assert result is True


def test_alicloud_resolve_credentials_env_fallback(alicloud_account):
    alicloud_account.credentials = {}
    p = AlicloudProvider(alicloud_account)
    with patch.dict(os.environ, {"ALIBABA_CLOUD_ACCESS_KEY_ID": "key", "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret"}):
        result = p.resolve_credentials()
        assert result is True


def test_alicloud_cli_tool_returns_callable(alicloud_account):
    alicloud_account.credentials = {"access_key_id": "k", "access_key_secret": "s"}
    p = AlicloudProvider(alicloud_account)
    p.resolve_credentials()
    tool_fn = p.cli_tool()
    assert callable(tool_fn)
    assert "ali_prod" in tool_fn.__name__
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_providers.py -k "alicloud" -v`
Expected: FAIL

- [ ] **Step 3: Implement AlicloudProvider**

```python
# src/agenticops/providers/alicloud.py
from __future__ import annotations

import logging
import os
import shlex
import subprocess
from typing import Any, Callable

from agenticops.models import CloudAccount
from .base import CloudProvider

logger = logging.getLogger(__name__)


class AlicloudProvider(CloudProvider):
    def __init__(self, account: CloudAccount):
        super().__init__(account)
        self._access_key_id: str | None = None
        self._access_key_secret: str | None = None
        self._security_token: str | None = None

    @property
    def provider_type(self) -> str:
        return "alicloud"

    def resolve_credentials(self) -> bool:
        creds = self.account.credentials or {}
        try:
            # Priority 1: AssumeRole
            if creds.get("assume_role"):
                return self._resolve_assume_role(creds)
            # Priority 2: Static credentials
            if creds.get("access_key_id"):
                self._access_key_id = creds["access_key_id"]
                self._access_key_secret = creds["access_key_secret"]
                self._security_token = creds.get("security_token")
                return True
            # Priority 3: Profile
            if creds.get("profile_name"):
                # Profile resolution handled by aliyun CLI itself
                return True
            # Priority 4: Environment variables
            ak = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
            sk = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
            if ak and sk:
                self._access_key_id = ak
                self._access_key_secret = sk
                self._security_token = os.environ.get("ALIBABA_CLOUD_SECURITY_TOKEN")
                return True
            # Priority 5: ECS RAM Role (handled by CLI/SDK automatically)
            return True
        except Exception as e:
            logger.error("Alicloud credential resolution failed for %s: %s", self.account.name, e)
            return False

    def _resolve_assume_role(self, creds: dict) -> bool:
        """Resolve AssumeRole credentials via Alicloud STS.
        Stub: sets base credentials for CLI --assume-role usage.
        Full STS implementation requires alibabacloud-sts20150401 SDK (deferred).
        """
        assume = creds["assume_role"]
        self._access_key_id = creds.get("access_key_id")
        self._access_key_secret = creds.get("access_key_secret")
        if not self._access_key_id:
            logger.warning("Alicloud AssumeRole requires base access_key_id — falling back to env")
            self._access_key_id = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
            self._access_key_secret = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
        # role_arn will be passed to CLI via --assume-role-arn flag
        self._role_arn = assume.get("role_arn")
        return bool(self._access_key_id)

    def sdk_session(self) -> Any:
        return {
            "access_key_id": self._access_key_id,
            "access_key_secret": self._access_key_secret,
            "security_token": self._security_token,
        }

    def cli_tool(self) -> Callable:
        account_name = self.account.name.replace("-", "_").replace(" ", "_")
        tool_name = f"run_aliyun_cli_{account_name}"
        region = self.account.regions[0] if self.account.regions else "cn-hangzhou"
        ak = self._access_key_id
        sk = self._access_key_secret
        profile = (self.account.credentials or {}).get("profile_name")

        def _run_cli(command: str) -> str:
            if not command.startswith("aliyun "):
                return "Error: command must start with 'aliyun '"
            cmd = command
            if "--region" not in cmd:
                cmd += f" --region {region}"
            if profile:
                cmd += f" --profile {profile}"
            run_env = dict(os.environ)
            if ak:
                run_env["ALIBABA_CLOUD_ACCESS_KEY_ID"] = ak
                run_env["ALIBABA_CLOUD_ACCESS_KEY_SECRET"] = sk or ""
            try:
                result = subprocess.run(
                    shlex.split(cmd), capture_output=True, text=True,
                    timeout=30, env=run_env,
                )
                if result.returncode != 0:
                    return f"Error: {result.stderr[:2000]}"
                return result.stdout[:4000]
            except subprocess.TimeoutExpired:
                return "Error: command timed out after 30s"
            except Exception as e:
                return f"Error: {e}"

        _run_cli.__name__ = tool_name
        _run_cli.__doc__ = f"Execute Alicloud CLI command for account '{self.account.name}'. Usage: run with 'aliyun <service> <action> [args]'."
        return _run_cli
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_providers.py -k "alicloud" -v`
Expected: All Alicloud tests PASS

- [ ] **Step 5: Run all provider tests together**

Run: `python -m pytest tests/test_providers.py -v`
Expected: All ~16 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/providers/alicloud.py tests/test_providers.py
git commit -m "feat(providers): implement AlicloudProvider with AssumeRole, static, profile, and env credential chain"
```

---

## Chunk 3: Tool & Metadata Refactoring

### Task 7: Update metadata_tools.py (get_enabled_accounts + save_resources)

**Files:**
- Modify: `src/agenticops/tools/metadata_tools.py:46-205`
- Test: `tests/test_cloud_models.py` (add tests)

- [ ] **Step 1: Write failing tests for get_enabled_accounts and save_resources**

Add to `tests/test_cloud_models.py`:

```python
from unittest.mock import patch, MagicMock
import json


def test_get_enabled_accounts_returns_list(db):
    aws = CloudAccount(name="a1", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])
    azure = CloudAccount(name="a2", provider="azure", is_enabled=True, credentials={}, regions=["eastus"])
    disabled = CloudAccount(name="a3", provider="gcp", is_enabled=False, credentials={}, regions=[])
    db.add_all([aws, azure, disabled])
    db.commit()

    # Simulating what get_enabled_accounts should return
    enabled = db.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()
    assert len(enabled) == 2
    providers = {a.provider for a in enabled}
    assert providers == {"aws", "azure"}


def test_save_resources_creates_cloud_resource(db):
    acct = CloudAccount(name="test-aws", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])
    db.add(acct)
    db.commit()

    res = CloudResource(
        account_id=acct.id, provider="aws", region="us-east-1",
        resource_type="compute", resource_id="arn:aws:ec2:us-east-1:123:instance/i-abc",
        name="web-1", tags={"Name": "web-1"}, raw_data={"InstanceId": "i-abc"},
        status="running",
    )
    db.add(res)
    db.commit()

    found = db.query(CloudResource).filter_by(account_id=acct.id).all()
    assert len(found) == 1
    assert found[0].provider == "aws"
    assert found[0].name == "web-1"
```

- [ ] **Step 2: Run tests to verify they fail (if CloudResource not imported)**

Run: `python -m pytest tests/test_cloud_models.py -v`
Expected: All PASS (model tests should pass from Task 1)

- [ ] **Step 3: Update metadata_tools.py**

In `src/agenticops/tools/metadata_tools.py`:

**Replace `get_active_account()` (lines 46-72) with `get_enabled_accounts()`:**

```python
@tool
def get_enabled_accounts() -> str:
    """Get all enabled cloud accounts for scanning and operations.
    Returns JSON array of accounts with id, name, provider, regions, credentials, labels."""
    try:
        with get_db() as db:
            accounts = db.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()
            if not accounts:
                return json.dumps({"error": "No enabled accounts found. Add accounts via CLI or Web UI."})
            result = []
            for acct in accounts:
                result.append({
                    "id": acct.id,
                    "name": acct.name,
                    "provider": acct.provider,
                    "regions": acct.regions,
                    "labels": acct.labels,
                    "last_scanned_at": acct.last_scanned_at.isoformat() if acct.last_scanned_at else None,
                })
            return json.dumps(result)[:MAX_RESULT_CHARS]
    except Exception as e:
        return json.dumps({"error": str(e)})
```

**Update `save_resources()` (lines 126-205) to write CloudResource:**

```python
@tool
def save_resources(resources_json: str, account_id: int, provider: str) -> str:
    """Save discovered cloud resources. Input: JSON array of resource objects.
    Each resource: {resource_id, resource_type, region, name?, status?, tags?, raw_data?}"""
    try:
        resources = json.loads(resources_json)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON: {e}"

    if not isinstance(resources, list):
        return "Error: resources_json must be a JSON array"

    new_count = 0
    updated_count = 0
    try:
        with get_db() as db:
            for r in resources:
                resource_id = r.get("resource_id")
                if not resource_id:
                    continue
                existing = db.query(CloudResource).filter_by(
                    account_id=account_id, provider=provider, resource_id=resource_id
                ).first()
                if existing:
                    existing.name = r.get("name", existing.name)
                    existing.status = r.get("status", existing.status)
                    existing.tags = r.get("tags", existing.tags)
                    existing.raw_data = r.get("raw_data", existing.raw_data)
                    existing.resource_type = r.get("resource_type", existing.resource_type)
                    existing.region = r.get("region", existing.region)
                    existing.scanned_at = datetime.utcnow()
                    updated_count += 1
                else:
                    new_res = CloudResource(
                        account_id=account_id,
                        provider=provider,
                        region=r.get("region", ""),
                        resource_type=r.get("resource_type", "other"),
                        resource_id=resource_id,
                        name=r.get("name", ""),
                        tags=r.get("tags", {}),
                        raw_data=r.get("raw_data", {}),
                        status=r.get("status", "unknown"),
                    )
                    db.add(new_res)
                    new_count += 1

            # Update account last_scanned_at
            acct = db.query(CloudAccount).get(account_id)
            if acct:
                acct.last_scanned_at = datetime.utcnow()
            db.commit()
        return f"Saved {new_count} new, updated {updated_count} existing resources."
    except Exception as e:
        return f"Error saving resources: {e}"
```

Also update imports at top of file: replace `AWSAccount, AWSResource` with `CloudAccount, CloudResource`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cloud_models.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/tools/metadata_tools.py tests/test_cloud_models.py
git commit -m "feat(tools): update metadata_tools for CloudAccount/CloudResource"
```

---

## Chunk 4: Agent Integration

### Task 8: Update scan_agent for multi-cloud

**Files:**
- Modify: `src/agenticops/agents/scan_agent.py:46-159`

- [ ] **Step 1: Update SCAN_SYSTEM_PROMPT for multi-cloud**

Replace the AWS-specific prompt (lines 46-90) with:

```python
SCAN_SYSTEM_PROMPT = """You are a multi-cloud resource scanner for AgenticOps.

## Your Job
Discover and inventory cloud resources across all enabled accounts.

## Workflow
1. Call get_enabled_accounts() to get the list of active cloud accounts
2. For each account, use its dedicated CLI tool to discover resources:
   - AWS accounts: use run_aws_cli_<account_name> with 'aws <service> describe-*' commands
   - Azure accounts: use run_az_cli_<account_name> with 'az <service> list' commands
   - GCP accounts: use run_gcloud_<account_name> with 'gcloud <service> list' commands
   - Alicloud accounts: use run_aliyun_cli_<account_name> with 'aliyun <service> <Action>' commands
3. For each discovered resource, call save_resources() with the account_id and provider

## Resource Categories
Scan these categories per cloud:
- **compute**: VMs, instances, functions/serverless
- **database**: Managed databases, caches
- **storage**: Object storage, file systems
- **container**: Kubernetes clusters, container services
- **network**: VPCs, subnets, load balancers, security groups
- **serverless**: Lambda, Functions, Cloud Functions

## CLI Tips
- Always request JSON output
- Use --query/--filter to limit results when possible
- For large accounts, scan region by region

## Output
Return a summary: how many resources found per account, per region, per type.
"""
```

- [ ] **Step 2: Update scan_agent() tool to inject provider CLI tools dynamically**

Replace the tool creation section (lines 118-152) with:

```python
@tool
def scan_agent(services: str = "all", regions: str = "all") -> str:
    """Scan cloud resources across all enabled accounts.
    Args:
        services: comma-separated resource types or 'all'
        regions: comma-separated regions or 'all' (uses account-configured regions)
    """
    from agenticops.providers import get_provider
    from agenticops.tools.metadata_tools import get_enabled_accounts, save_resources

    model_id, max_tokens = get_agent_model_config("scan")
    bedrock_model = BedrockModel(
        model_id=model_id,
        max_tokens=max_tokens,
    )
    if settings.bedrock_cache_enabled:
        bedrock_model = BedrockModel(
            model_id=model_id,
            max_tokens=max_tokens,
            additional_request_fields={"anthropic_beta": ["prompt-caching-2024-07-31"]},
        )

    # Build dynamic tool list from enabled accounts
    tools = [get_enabled_accounts, save_resources]

    # Load accounts inside session, extract data before session closes
    # to avoid DetachedInstanceError when providers access acct.credentials/regions
    with get_db() as db:
        accounts = db.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()
        # Force-load all lazy attributes while session is open
        account_snapshots = []
        for acct in accounts:
            account_snapshots.append({
                "id": acct.id, "name": acct.name, "provider": acct.provider,
                "credentials": dict(acct.credentials or {}),
                "regions": list(acct.regions or []), "labels": dict(acct.labels or {}),
            })

    for snap in account_snapshots:
        try:
            # Create a lightweight CloudAccount-like object for the provider
            from types import SimpleNamespace
            acct_obj = SimpleNamespace(**snap)
            provider = get_provider(acct_obj)
            if provider.resolve_credentials():
                tools.append(provider.cli_tool())
        except Exception as e:
            logger.warning("Failed to init provider for %s: %s", snap["name"], e)

    agent = Agent(
        model=bedrock_model,
        system_prompt=SCAN_SYSTEM_PROMPT,
        tools=tools,
    )

    prompt = f"Scan resources. Services: {services}. Regions: {regions}."
    result = invoke_with_retry(agent, prompt)
    return str(result)
```

- [ ] **Step 3: Update imports**

Replace `AWSAccount` import with `CloudAccount` at top of file. Remove individual AWS tool imports (`describe_ec2`, `list_lambda_functions`, etc.) — the agent now gets CLI tools dynamically.

- [ ] **Step 4: Verify syntax**

Run: `python3 -m py_compile src/agenticops/agents/scan_agent.py`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/agents/scan_agent.py
git commit -m "feat(agents): update scan_agent for multi-cloud with dynamic provider tool injection"
```

---

## Chunk 5: Web API

### Task 9: Update account API endpoints and schemas

**Files:**
- Modify: `src/agenticops/web/app.py:76-108,1384-1450`
- Test: `tests/test_multi_cloud_api.py` (new)

- [ ] **Step 1: Write failing tests for new account API**

```python
# tests/test_multi_cloud_api.py
import pytest
from fastapi.testclient import TestClient
from agenticops.web.app import app
from agenticops.models import init_db, CloudAccount
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    # Patch get_db to use test engine
    with TestClient(app) as c:
        yield c


def test_create_account_aws(client):
    resp = client.post("/api/accounts", json={
        "name": "aws-prod",
        "provider": "aws",
        "credentials": {"role_arn": "arn:aws:iam::123456789012:role/ops", "account_id": "123456789012"},
        "regions": ["us-east-1"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["provider"] == "aws"
    assert data["is_enabled"] is True


def test_create_account_azure(client):
    resp = client.post("/api/accounts", json={
        "name": "azure-prod",
        "provider": "azure",
        "credentials": {"subscription_id": "sub-xxx", "tenant_id": "t-xxx"},
        "regions": ["eastus"],
    })
    assert resp.status_code == 201
    assert resp.json()["provider"] == "azure"


def test_list_accounts_filter_by_provider(client):
    client.post("/api/accounts", json={"name": "a1", "provider": "aws", "credentials": {}, "regions": []})
    client.post("/api/accounts", json={"name": "a2", "provider": "azure", "credentials": {}, "regions": []})
    resp = client.get("/api/accounts?provider=aws")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["provider"] == "aws"


def test_create_account_duplicate_name(client):
    client.post("/api/accounts", json={"name": "dup", "provider": "aws", "credentials": {}, "regions": []})
    resp = client.post("/api/accounts", json={"name": "dup", "provider": "azure", "credentials": {}, "regions": []})
    assert resp.status_code == 409


def test_test_account_connection(client):
    resp = client.post("/api/accounts", json={
        "name": "test-aws", "provider": "aws",
        "credentials": {"profile_name": "default"}, "regions": ["us-east-1"],
    })
    account_id = resp.json()["id"]
    # Test endpoint — will attempt to resolve credentials
    resp = client.post(f"/api/accounts/{account_id}/test")
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
    assert data["provider"] == "aws"


def test_test_account_not_found(client):
    resp = client.post("/api/accounts/99999/test")
    assert resp.status_code == 404


def test_account_response_redacts_secrets(client):
    resp = client.post("/api/accounts", json={
        "name": "secret-test", "provider": "azure",
        "credentials": {"client_secret": "super-secret", "tenant_id": "t-xxx"},
        "regions": ["eastus"],
    })
    assert resp.status_code == 201
    data = resp.json()
    # client_secret should be redacted in response
    assert data["credentials"].get("client_secret") != "super-secret"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_multi_cloud_api.py -v`
Expected: FAIL

- [ ] **Step 3: Update schemas in app.py**

Replace `AccountCreate`, `AccountUpdate`, `AccountResponse` (lines 76-108):

```python
class AccountCreate(BaseModel):
    name: str = Field(max_length=100)
    provider: str = Field(pattern="^(aws|azure|gcp|alicloud)$")
    credentials: dict = Field(default_factory=dict)
    regions: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    is_enabled: bool = True


class AccountUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    credentials: dict | None = None
    regions: list[str] | None = None
    labels: dict[str, str] | None = None
    is_enabled: bool | None = None


REDACTED_KEYS = {"client_secret", "access_key_secret", "secret_key", "service_account_key"}


class AccountResponse(BaseModel):
    id: int
    name: str
    provider: str
    credentials: dict
    regions: list[str]
    labels: dict[str, str]
    is_enabled: bool
    created_at: datetime
    last_scanned_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def redact_secrets(self):
        if self.credentials:
            self.credentials = {
                k: "***REDACTED***" if k in REDACTED_KEYS else v
                for k, v in self.credentials.items()
            }
        return self
```

- [ ] **Step 4: Update account endpoints (lines 1384-1450)**

```python
@app.get("/api/accounts", response_model=list[AccountResponse])
async def list_accounts(provider: str | None = None):
    with get_db() as db:
        q = db.query(CloudAccount)
        if provider:
            q = q.filter(CloudAccount.provider == provider)
        return q.all()


@app.get("/api/accounts/{account_id}", response_model=AccountResponse)
async def get_account(account_id: int):
    with get_db() as db:
        acct = db.query(CloudAccount).get(account_id)
        if not acct:
            raise HTTPException(404, "Account not found")
        return acct


@app.post("/api/accounts", response_model=AccountResponse, status_code=201)
async def create_account(data: AccountCreate):
    with get_db() as db:
        if db.query(CloudAccount).filter(CloudAccount.name == data.name).first():
            raise HTTPException(409, f"Account name '{data.name}' already exists")
        acct = CloudAccount(
            name=data.name,
            provider=data.provider,
            is_enabled=data.is_enabled,
            credentials=data.credentials,
            regions=data.regions,
            labels=data.labels,
        )
        db.add(acct)
        db.commit()
        db.refresh(acct)
        return acct


@app.put("/api/accounts/{account_id}", response_model=AccountResponse)
async def update_account(account_id: int, data: AccountUpdate):
    with get_db() as db:
        acct = db.query(CloudAccount).get(account_id)
        if not acct:
            raise HTTPException(404, "Account not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(acct, field, value)
        db.commit()
        db.refresh(acct)
        return acct


@app.delete("/api/accounts/{account_id}", status_code=204)
async def delete_account(account_id: int):
    with get_db() as db:
        acct = db.query(CloudAccount).get(account_id)
        if not acct:
            raise HTTPException(404, "Account not found")
        db.delete(acct)
        db.commit()


@app.post("/api/accounts/{account_id}/test")
async def test_account_connection(account_id: int):
    """Test credential chain for an account. Returns success/failure."""
    from agenticops.providers import get_provider
    with get_db() as db:
        acct = db.query(CloudAccount).get(account_id)
        if not acct:
            raise HTTPException(404, "Account not found")
        provider = get_provider(acct)
        success = provider.resolve_credentials()
        return {"success": success, "provider": acct.provider, "name": acct.name}
```

Also update imports: replace `AWSAccount` with `CloudAccount` throughout app.py.

- [ ] **Step 5: Verify syntax**

Run: `python3 -m py_compile src/agenticops/web/app.py`
Expected: No errors

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_multi_cloud_api.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/web/app.py tests/test_multi_cloud_api.py
git commit -m "feat(api): update account endpoints for multi-cloud CloudAccount model"
```

---

## Chunk 6: Frontend

### Task 10: Update Accounts page for multi-cloud

**Files:**
- Modify: `src/agenticops/web/frontend/src/api/types.ts`
- Modify: `src/agenticops/web/frontend/src/pages/Accounts.tsx`

- [ ] **Step 1: Update TypeScript types**

In `src/agenticops/web/frontend/src/api/types.ts`, replace Account types:

```typescript
export type CloudProvider = "aws" | "azure" | "gcp" | "alicloud";

export interface Account {
  id: number;
  name: string;
  provider: CloudProvider;
  credentials: Record<string, unknown>;
  regions: string[];
  labels: Record<string, string>;
  is_enabled: boolean;
  created_at: string;
  last_scanned_at: string | null;
}

export interface AccountCreate {
  name: string;
  provider: CloudProvider;
  credentials: Record<string, unknown>;
  regions: string[];
  labels?: Record<string, string>;
  is_enabled?: boolean;
}

export interface AccountUpdate {
  name?: string;
  credentials?: Record<string, unknown>;
  regions?: string[];
  labels?: Record<string, string>;
  is_enabled?: boolean;
}
```

- [ ] **Step 2: Update Accounts.tsx**

Replace the form modal and table in `src/agenticops/web/frontend/src/pages/Accounts.tsx`:

```tsx
// Credential field definitions per provider
const PROVIDER_FIELDS: Record<CloudProvider, { key: string; label: string; type?: string; placeholder: string; required?: boolean }[]> = {
  aws: [
    { key: "role_arn", label: "Role ARN", placeholder: "arn:aws:iam::123456789012:role/AgenticOps" },
    { key: "external_id", label: "External ID", placeholder: "Optional" },
    { key: "account_id", label: "Account ID", placeholder: "123456789012" },
    { key: "profile_name", label: "Profile Name", placeholder: "default (from ~/.aws/credentials)" },
  ],
  azure: [
    { key: "subscription_id", label: "Subscription ID", placeholder: "00000000-0000-0000-0000-000000000000", required: true },
    { key: "tenant_id", label: "Tenant ID", placeholder: "00000000-0000-0000-0000-000000000000" },
    { key: "client_id", label: "Client ID", placeholder: "Service Principal App ID" },
    { key: "client_secret", label: "Client Secret", type: "password", placeholder: "Service Principal Secret" },
  ],
  gcp: [
    { key: "project_id", label: "Project ID", placeholder: "my-gcp-project", required: true },
    { key: "service_account_key", label: "Service Account Key (JSON)", type: "textarea", placeholder: '{"type": "service_account", ...}' },
  ],
  alicloud: [
    { key: "access_key_id", label: "Access Key ID", placeholder: "LTAI..." },
    { key: "access_key_secret", label: "Access Key Secret", type: "password", placeholder: "Secret" },
    { key: "account_id", label: "Account ID", placeholder: "1234567890" },
  ],
};

const PROVIDER_OPTIONS: { value: CloudProvider; label: string }[] = [
  { value: "aws", label: "AWS" },
  { value: "azure", label: "Azure" },
  { value: "gcp", label: "GCP" },
  { value: "alicloud", label: "Alicloud" },
];
```

**AccountFormModal changes:**
```tsx
function AccountFormModal({ onSubmit, initial, onClose }: FormModalProps) {
  const [provider, setProvider] = useState<CloudProvider>(initial?.provider ?? "aws");
  const [name, setName] = useState(initial?.name ?? "");
  const [regions, setRegions] = useState(initial?.regions?.join(", ") ?? "");
  const [useEnvDefaults, setUseEnvDefaults] = useState(false);
  const [creds, setCreds] = useState<Record<string, string>>({});

  const fields = PROVIDER_FIELDS[provider];

  const handleSubmit = () => {
    const credentials: Record<string, unknown> = useEnvDefaults ? {} : {};
    if (!useEnvDefaults) {
      for (const f of fields) {
        const val = creds[f.key]?.trim();
        if (val) {
          credentials[f.key] = f.key === "service_account_key" ? JSON.parse(val) : val;
        }
      }
    }
    onSubmit({
      name,
      provider,
      credentials,
      regions: regions.split(",").map((r) => r.trim()).filter(Boolean),
    });
  };

  return (
    // ... modal wrapper ...
    <>
      {/* Provider selector (disabled on edit) */}
      <select value={provider} onChange={(e) => setProvider(e.target.value as CloudProvider)} disabled={!!initial}>
        {PROVIDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>

      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Account name" />
      <input value={regions} onChange={(e) => setRegions(e.target.value)} placeholder="us-east-1, us-west-2" />

      <label><input type="checkbox" checked={useEnvDefaults} onChange={(e) => setUseEnvDefaults(e.target.checked)} /> Use environment defaults</label>

      {!useEnvDefaults && fields.map((f) => (
        f.type === "textarea" ? (
          <textarea key={f.key} value={creds[f.key] ?? ""} onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })} placeholder={f.placeholder} />
        ) : (
          <input key={f.key} type={f.type ?? "text"} value={creds[f.key] ?? ""} onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })} placeholder={f.placeholder} />
        )
      ))}
    </>
  );
}
```

**Table columns update — add Provider badge:**
```tsx
const columns: Column<Account>[] = [
  { key: "name", header: "Name" },
  { key: "provider", header: "Provider", render: (a) => <Badge variant={a.provider === "aws" ? "blue" : a.provider === "azure" ? "purple" : a.provider === "gcp" ? "green" : "orange"}>{a.provider.toUpperCase()}</Badge> },
  { key: "regions", header: "Regions", render: (a) => a.regions.map((r) => <Badge key={r} variant="gray">{r}</Badge>) },
  { key: "is_enabled", header: "Status", render: (a) => <Badge variant={a.is_enabled ? "green" : "gray"}>{a.is_enabled ? "Enabled" : "Disabled"}</Badge> },
  { key: "last_scanned_at", header: "Last Scanned", render: (a) => a.last_scanned_at ? formatShortDate(a.last_scanned_at) : "Never" },
];
```

**Add filter dropdown above table:**
```tsx
const [filterProvider, setFilterProvider] = useState<string>("");
// In useAccounts hook call, pass ?provider= query param
const { data: accounts } = useAccounts(filterProvider || undefined);
```

- [ ] **Step 3: Verify frontend builds**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/web/frontend/src/api/types.ts src/agenticops/web/frontend/src/pages/Accounts.tsx
git commit -m "feat(frontend): update Accounts page for multi-cloud provider support"
```

---

## Chunk 7: Codebase-wide AWSAccount → CloudAccount Migration

### Task 11: Refactor sub-agents to use provider-injected CLI tools

**Files:**
- Modify: `src/agenticops/agents/rca_agent.py`
- Modify: `src/agenticops/agents/sre_agent.py`
- Modify: `src/agenticops/agents/executor_agent.py`
- Modify: `src/agenticops/agents/detect_agent.py`

These 4 agents currently import `run_aws_cli` / `run_aws_cli_readonly` directly. They need to resolve the target account from `HealthIssue.account_id` and inject the provider's CLI tool dynamically.

- [ ] **Step 1: Add helper function for provider tool resolution**

Add to `src/agenticops/providers/base.py`:

```python
def get_cli_tool_for_issue(issue_account_id: int | None) -> Callable | None:
    """Resolve CLI tool from a HealthIssue's account_id."""
    if not issue_account_id:
        return None
    from agenticops.models import CloudAccount, get_db
    with get_db() as db:
        acct = db.query(CloudAccount).get(issue_account_id)
        if not acct:
            return None
        # Snapshot to avoid detached instance
        from types import SimpleNamespace
        snap = SimpleNamespace(
            id=acct.id, name=acct.name, provider=acct.provider,
            credentials=dict(acct.credentials or {}),
            regions=list(acct.regions or []), labels=dict(acct.labels or {}),
        )
    provider = get_provider(snap)
    if provider.resolve_credentials():
        return provider.cli_tool()
    return None
```

- [ ] **Step 2: Update each sub-agent**

For each of rca_agent.py, sre_agent.py, executor_agent.py, detect_agent.py:
1. Replace `from agenticops.tools.aws_cli_tool import run_aws_cli, run_aws_cli_readonly` with `from agenticops.providers.base import get_cli_tool_for_issue`
2. In the agent `@tool` function, resolve CLI tool dynamically:
   ```python
   cli_tool = get_cli_tool_for_issue(issue_account_id)
   tools = [...]
   if cli_tool:
       tools.append(cli_tool)
   ```
3. Keep `aws_cli_tool.py` as-is for backwards compatibility (it will still work for single-AWS setups)
4. **Update system prompts**: Each sub-agent's system prompt references `run_aws_cli_readonly` by name. Update these to say "use the provided CLI tool" generically, so the agent uses whatever CLI tool was injected (could be `run_az_cli_*`, `run_gcloud_*`, etc.)

- [ ] **Step 3: Verify syntax for all 4 agents**

Run: `python3 -m py_compile src/agenticops/agents/rca_agent.py && python3 -m py_compile src/agenticops/agents/sre_agent.py && python3 -m py_compile src/agenticops/agents/executor_agent.py && python3 -m py_compile src/agenticops/agents/detect_agent.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/agents/ src/agenticops/providers/base.py
git commit -m "feat(agents): refactor sub-agents to use provider-injected CLI tools"
```

### Task 12: Update all remaining files that reference AWSAccount/AWSResource

**Files:**
- Modify: `src/agenticops/cli/main.py`
- Modify: `src/agenticops/cli/init_helpers.py`
- Modify: `src/agenticops/pipeline/health_patrol.py`
- Modify: `src/agenticops/pipeline/orchestrator.py`
- Modify: `src/agenticops/chat/preprocessor.py`
- Modify: `src/agenticops/integrations/cloudwatch_provider.py`
- Modify: `src/agenticops/graph/api.py`
- Modify: `src/agenticops/config.py`
- Modify: `src/agenticops/scheduler/scheduler.py`
- Modify: `src/agenticops/report/generator.py`
- Modify: `src/agenticops/scan/scanner.py`
- Modify: `src/agenticops/monitor/collector.py`
- Modify: `src/agenticops/monitor/cloudwatch.py`
- Modify: `src/agenticops/agent/ops_agent.py`
- Modify: `src/agenticops/detect/detector.py`
- Modify: `src/agenticops/analyze/rca.py`

- [ ] **Step 1: Find all remaining AWSAccount/AWSResource references**

Run: `grep -rn "AWSAccount\|AWSResource\|aws_accounts\|aws_resources" src/agenticops/ --include="*.py" | grep -v __pycache__ | grep -v _legacy`

Fix each file by:
1. Updating imports: `AWSAccount` → `CloudAccount`, `AWSResource` → `CloudResource`
2. Updating queries: `.query(AWSAccount)` → `.query(CloudAccount)`
3. Updating field references: `account.account_id` → `account.credentials.get("account_id")`, `account.role_arn` → `account.credentials.get("role_arn")`, `account.is_active` → `account.is_enabled`

- [ ] **Step 2: Update cli/init_helpers.py**

Add provider selection to the account init flow. After the user provides account name, ask for provider type, then show provider-specific credential prompts.

- [ ] **Step 3: Update config.py — add default_regions schema only**

Add to Settings class (schema only, actual defaults go in `config/settings.yaml` per project convention):

```python
default_regions: dict[str, list[str]] = Field(
    default_factory=dict,
    description="Default regions per cloud provider for account creation UI",
)
```

Add to `config/settings.yaml`:

```yaml
default_regions:
  aws: ["us-east-1", "us-west-2"]
  azure: ["eastus", "westus2"]
  gcp: ["us-central1", "us-east1"]
  alicloud: ["cn-hangzhou", "cn-beijing"]
```

- [ ] **Step 4: Verify no remaining references**

Run: `grep -rn "AWSAccount\|AWSResource" src/agenticops/ --include="*.py" | grep -v __pycache__ | grep -v _legacy | grep -v "# legacy"`
Expected: No matches (or only in migration/legacy code)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (some existing tests may need updates — fix inline)

- [ ] **Step 6: Verify frontend builds**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: Build succeeds

- [ ] **Step 7: Verify backend compiles**

Run: `python3 -m py_compile src/agenticops/web/app.py && python3 -m py_compile src/agenticops/models.py && python3 -m py_compile src/agenticops/config.py`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: migrate all AWSAccount/AWSResource references to CloudAccount/CloudResource"
```

---

## Final Verification

### Task 13: End-to-end validation

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Verify backend starts**

Run: `python3 -m py_compile src/agenticops/web/app.py`
Expected: No errors

- [ ] **Step 3: Verify frontend builds**

Run: `cd src/agenticops/web/frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Final commit with test verification**

```bash
git add -A
git commit -m "test: verify multi-cloud provider implementation passes all tests"
```
