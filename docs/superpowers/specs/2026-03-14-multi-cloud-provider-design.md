# Multi-Cloud Provider Design

**Date:** 2026-03-14
**Status:** Draft
**Scope:** Account model, provider abstraction, credential chain, parallel scanning, resource model, agent integration

## Context

AgenticOps is 100% AWS-coupled: `AWSAccount` model, STS AssumeRole auth, 15+ AWS-specific tools, boto3 sessions throughout. This design introduces multi-cloud support for AWS, Azure, GCP, and Alicloud — enabling simultaneous multi-account management with a unified view.

### Existing Abstraction

`integrations/base.py` already defines a `MonitoringProvider` ABC with CloudWatch and Datadog implementations. This pattern is proven and will be mirrored for cloud providers.

## Requirements

- **Simultaneous multi-cloud**: multiple accounts across AWS/Azure/GCP/Alicloud active and scannable in parallel
- **Terraform-style credential chain**: each provider resolves credentials by priority (explicit config > env vars > profile/CLI > instance metadata), not a single hardcoded auth method
- **CLI-driven resource discovery**: Agent uses each cloud's CLI tool (`aws`/`az`/`gcloud`/`aliyun`) — no hardcoded resource type tools per cloud
- **Unified resource table**: single `CloudResource` table with `provider` field
- **Simple and efficient**: minimal abstraction, no over-engineering

## Design

### 1. CloudAccount Model

Replaces `AWSAccount`. Multiple accounts can be enabled simultaneously.

```
CloudAccount:
  id              — PK (int, auto)
  name            — unique display name (str)
  provider        — "aws" | "azure" | "gcp" | "alicloud"
  is_enabled      — bool (multiple can be True simultaneously)
  credentials     — JSON, plaintext. Structure varies by provider (see Credential Chain).
                    Encryption at rest deferred to future spec (consider Fernet or KMS).
  regions         — JSON list (provider-native region names)
  labels          — JSON dict (user tags: env, team, etc.)
  created_at      — timestamp
  last_scanned_at — timestamp (nullable)
```

**Key changes from AWSAccount:**
- `is_active` (single) → `is_enabled` (multiple concurrent)
- `account_id`, `role_arn`, `external_id` → absorbed into `credentials` JSON
- New: `provider` enum, `labels` dict

**Migration**: existing `AWSAccount` rows migrate to `CloudAccount` with `provider="aws"` and credentials restructured to JSON.

### 2. Provider Abstraction

```
src/agenticops/providers/
  base.py       — CloudProvider ABC + PROVIDERS registry + get_provider()
  aws.py        — AWSProvider (<100 lines)
  azure.py      — AzureProvider (<100 lines)
  gcp.py        — GCPProvider (<100 lines)
  alicloud.py   — AlicloudProvider (<100 lines)
```

```python
class CloudProvider(ABC):
    def __init__(self, account: CloudAccount):
        self.account = account
        self._session = None

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
```

Registry in `base.py`:

```python
PROVIDERS = {
    "aws": AWSProvider,
    "azure": AzureProvider,
    "gcp": GCPProvider,
    "alicloud": AlicloudProvider,
}

def get_provider(account: CloudAccount) -> CloudProvider:
    return PROVIDERS[account.provider](account)
```

### 3. Credential Chain (Terraform-style)

Each provider resolves credentials top-to-bottom, stopping at first success. No `auth_type` field needed — presence of fields in `credentials` JSON determines the method.

**AWSProvider chain:**

| Priority | Trigger | Method |
|----------|---------|--------|
| 1 | `credentials.role_arn` exists | STS AssumeRole (existing code) |
| 2 | `credentials.profile_name` exists | `boto3.Session(profile_name=...)` |
| 3 | `credentials.access_key` exists | Static credentials |
| 4 | `AWS_*` env vars set | boto3 env var chain |
| 5 | (none of above) | boto3 default chain (EC2/ECS/EKS metadata) |

Example `credentials` JSON:
```json
{"role_arn": "arn:aws:iam::123456789012:role/ops", "external_id": "xyz", "account_id": "123456789012"}
```
or:
```json
{"profile_name": "prod-account"}
```
or:
```json
{}
```

**AzureProvider chain:**

| Priority | Trigger | Method |
|----------|---------|--------|
| 1 | `credentials.client_id` + `client_secret` + `tenant_id` | Service Principal (`ClientSecretCredential`) |
| 2 | `ARM_*` env vars set | Same as above via env |
| 3 | (none of above) | `AzureCliCredential` (`az login` state) |

Example `credentials` JSON:
```json
{"subscription_id": "sub-xxx", "tenant_id": "t-xxx", "client_id": "c-xxx", "client_secret": "secret"}
```

**GCPProvider chain:**

| Priority | Trigger | Method |
|----------|---------|--------|
| 1 | `credentials.service_account_key` exists | JSON key file content |
| 2 | `GOOGLE_*` env vars set | ADC via env |
| 3 | (none of above) | Application Default Credentials (`gcloud auth`) |

Example `credentials` JSON:
```json
{"project_id": "my-project", "service_account_key": {"type": "service_account", ...}}
```

**AlicloudProvider chain:**

| Priority | Trigger | Method |
|----------|---------|--------|
| 1 | `credentials.assume_role` exists | RAM Role assumption (cross-account) |
| 2 | `credentials.access_key_id` + `access_key_secret` | Static credentials |
| 3 | `credentials.profile_name` exists | Shared config (`~/.aliyun/config.json`) |
| 4 | `ALIBABA_CLOUD_*` env vars set | Env var chain |
| 5 | (none of above) | ECS RAM Role (instance metadata) |

Example `credentials` JSON:
```json
{"access_key_id": "LTAI...", "access_key_secret": "secret", "account_id": "1234567890"}
```

### 4. Session Cache

Reuses existing `_session_cache` pattern. Key format changes to support multi-cloud:

```python
_session_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()

# Key format: "{provider}:{account_id}:{region}"
# e.g. "aws:123456789012:us-east-1", "azure:sub-xxx:eastus"

def get_cached_session(key: str) -> Any | None:
    with _cache_lock:
        return _session_cache.get(key)

def set_cached_session(key: str, session: Any):
    with _cache_lock:
        _session_cache[key] = session
```

Provider instances are stateless — the session cache is module-level with lock-on-read and lock-on-write. Parallel scanning uses `asyncio.to_thread()` to run each `scan_one()` in a thread (because CLI subprocess calls and SDK calls are blocking), so the `threading.Lock` is correct.

### 5. CloudResource Model

Replaces `AWSResource`. Single table, all clouds.

```
CloudResource:
  id              — PK (int, auto)
  account_id      — FK → CloudAccount.id
  provider        — "aws" | "azure" | "gcp" | "alicloud" (indexed)
  region          — resource region
  resource_type   — "compute" | "database" | "storage" | "container" | "network" | "serverless" | "other"
  resource_id     — cloud-native ID (AWS ARN / Azure Resource ID / GCP self_link / Alicloud ID)
  name            — display name
  tags            — JSON dict (cloud resource tags, migrated from AWSResource.tags)
  raw_data        — JSON (raw API response, subsumes old resource_metadata)
  status          — resource state (running / stopped / etc.)
  managed         — bool (opt-in/opt-out monitoring, migrated from AWSResource.managed)
  created_at      — timestamp
  updated_at      — timestamp
  scanned_at      — timestamp
```

**Fields migrated from AWSResource:** `tags`, `managed`, `created_at`, `updated_at` are preserved. `resource_arn` is absorbed into `resource_id` (for AWS, this holds the ARN; the old `resource_id` short form like `i-xxx` goes into `raw_data`). `resource_metadata` is absorbed into `raw_data`.

**Unique constraint:** `(account_id, provider, resource_id)`

**HealthIssue change:** add `account_id` FK → `CloudAccount.id` for issue-to-account traceability.

**MonitoringConfig change:** update `account_id` FK from `aws_accounts.id` → `cloud_accounts.id`.

### 6. Parallel Scanning

```python
async def scan_all_accounts():
    accounts = db.query(CloudAccount).filter(is_enabled=True).all()

    tasks = []
    for account in accounts:
        provider = get_provider(account)
        provider.resolve_credentials()
        for region in account.regions:
            # scan_one runs CLI subprocesses (blocking) so wrap in thread
            tasks.append(asyncio.to_thread(scan_one, provider, region))

    results = await asyncio.gather(*tasks)

    for resources in results:
        bulk_upsert(CloudResource, resources)
```

`scan_one()` is a **synchronous** function that calls `provider.cli_tool()` to execute CLI subprocesses (e.g. `aws ec2 describe-instances`, `az vm list`). It does NOT invoke a Strands Agent — it directly runs CLI commands and parses JSON output. Each `scan_one()` runs in its own thread via `asyncio.to_thread()`.

No message queue or complex scheduler needed. `asyncio.gather` + `to_thread` is sufficient for parallel blocking I/O.

### 7. Agent Integration

**CLI tool injection** — dynamic, per-scan:

```python
cli_tools = []
for acct in enabled_accounts:
    provider = get_provider(acct)
    provider.resolve_credentials()
    cli_tools.append(provider.cli_tool())

scan_agent = Agent(tools=[save_resources, get_enabled_accounts, *cli_tools])
```

Each `cli_tool()` returns a `@tool` function with account+region bound via closure. Tools are named by convention: `run_{provider}_cli_{account_name}` (e.g. `run_aws_cli_aws_prod`, `run_az_cli_azure_staging`). Account names are unique (enforced by DB), so tool names are guaranteed unique.

**Scan Agent prompt** changes from AWS-specific to multi-cloud template:

```
You are a multi-cloud resource scanner. Enabled accounts:
{% for acct in accounts %}
- {{ acct.name }} ({{ acct.provider }}) regions: {{ acct.regions }}
  CLI tool: {{ acct.cli_tool_name }}
{% endfor %}

For each account, use its CLI tool to discover resources and call save_resources to persist them.
```

**metadata_tools.py changes:**
- `get_active_account()` → `get_enabled_accounts()` returns list
- `save_resources()` writes to `CloudResource` with `account_id` + `provider`

**Unchanged agents:** RCA, SRE, Executor, Reporter operate on `HealthIssue` / `FixPlan`. They resolve the target account via `issue.account_id` → `CloudAccount` → `get_provider()` → `cli_tool()` when they need cloud access.

### 8. Web API Changes

**Account endpoints** (replace existing AWS-specific ones):

| Endpoint | Change |
|----------|--------|
| `POST /api/accounts` | Schema: `{name, provider, credentials, regions, labels, is_enabled}` |
| `GET /api/accounts` | Returns all `CloudAccount` rows, filterable by `?provider=aws` |
| `PUT /api/accounts/{id}` | Update any field |
| `DELETE /api/accounts/{id}` | Delete account |
| `POST /api/accounts/{id}/test` | New: test credential chain, return success/failure |

**Pydantic schemas:**
- `AccountCreate` → provider-agnostic: `provider` enum + `credentials` as JSON
- `AccountResponse` → includes `provider`, `labels`, drops AWS-specific fields

### 9. Frontend Changes

**Accounts page:**
- Add provider selector (AWS / Azure / GCP / Alicloud) at account creation
- Dynamic form: credential fields change based on selected provider
- Support "empty credentials" option (use environment/profile defaults)
- Table: add Provider column with icon/badge
- Filter bar: filter by provider, labels

**Dashboard:**
- Resource counts grouped by provider
- Filter by provider / account

### 10. Config Changes

**New settings in `config/settings.yaml`:**

```yaml
# No new mandatory settings. Provider config lives in CloudAccount.credentials.
# Optional: default regions per provider for account creation UI
default_regions:
  aws: ["us-east-1", "us-west-2"]
  azure: ["eastus", "westus2"]
  gcp: ["us-central1", "us-east1"]
  alicloud: ["cn-hangzhou", "cn-beijing"]
```

**LLM backend** remains Bedrock by default. Configurable LLM backend (Anthropic API direct, Azure OpenAI, Vertex AI) is a separate future spec — not in scope here.

## Migration Plan

1. Create `CloudAccount` table
2. Migrate `AWSAccount` rows → `CloudAccount` with `provider="aws"`, restructure credential fields to JSON
3. Create `CloudResource` table
4. Migrate `AWSResource` rows → `CloudResource` with `provider="aws"` (preserve `tags`, `managed`, timestamps)
5. Add `account_id` FK to `HealthIssue`
6. Update `MonitoringConfig.account_id` FK to point to `cloud_accounts`
7. Rename old tables to `_legacy_aws_accounts` / `_legacy_aws_resources` (keep for rollback safety)
8. Follow-up migration (after validation): drop `_legacy_*` tables

**Important:** Test migration against a copy of production data before running. Step 7 renames instead of drops to allow rollback.

## Out of Scope

- LLM backend abstraction (Bedrock → multi-provider): separate spec
- Per-cloud hardcoded resource tools (EC2, RDS, etc.): CLI-driven approach replaces these
- Monitoring provider expansion (Azure Monitor, GCP Cloud Monitoring): extend existing `MonitoringProvider` ABC separately
- Cloud-specific auto-fix recipes: future work per cloud

## File Impact Summary

| File | Change |
|------|--------|
| `models.py` | New: `CloudAccount`, `CloudResource`. Modify: `HealthIssue` (add `account_id` FK), `MonitoringConfig` (update FK). Remove: `AWSAccount`, `AWSResource` |
| `providers/base.py` | New file: `CloudProvider` ABC, `PROVIDERS`, `get_provider()`, session cache |
| `providers/aws.py` | New file: `AWSProvider` (refactor from `tools/aws_tools.py`) |
| `providers/azure.py` | New file: `AzureProvider` |
| `providers/gcp.py` | New file: `GCPProvider` |
| `providers/alicloud.py` | New file: `AlicloudProvider` |
| `tools/metadata_tools.py` | `get_active_account()` → `get_enabled_accounts()`, `save_resources()` writes `CloudResource` |
| `tools/aws_tools.py` | Refactor: auth logic moves to `providers/aws.py`, file may be removed |
| `tools/aws_cli_tool.py` | Refactor: generalize or move to `providers/aws.py` |
| `agents/scan_agent.py` | Multi-cloud prompt, dynamic tool injection |
| `web/app.py` | Account endpoints: new schemas, query `CloudAccount` |
| `web/frontend/src/pages/Accounts.tsx` | Provider selector, dynamic form, provider column |
| `web/frontend/src/pages/Dashboard.tsx` | Provider filter, grouped counts |
| `config.py` | Optional: `default_regions` per provider |
| `cli/main.py` | Update `AWSAccount` → `CloudAccount` queries, slash commands |
| `cli/init_helpers.py` | Account init flow: add provider selection |
| `pipeline/health_patrol.py` | Update account queries |
| `pipeline/orchestrator.py` | Update account references |
| `chat/preprocessor.py` | Update resource/account references |
| `integrations/cloudwatch_provider.py` | Update account FK |
| `graph/api.py` | Update resource queries |
| Alembic migration | `AWSAccount` → `CloudAccount`, `AWSResource` → `CloudResource` |

**Note:** All files importing `AWSAccount` or `AWSResource` must be updated. The `Anomaly`/`OpsAgent` legacy models are unchanged (not in scope).
