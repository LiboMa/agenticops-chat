# Parallel Multi-Account Scan & Resource Display Fix

## Problem

1. **Sequential scanning**: The LLM scan agent iterates accounts one at a time in its agentic loop. With N accounts, scanning takes ~Nx time and costs N× LLM tokens for mechanical work.

2. **Resource display bug**: `ResourceResponse` uses legacy `AWSResource` field names (`resource_name`, `resource_arn`, `resource_metadata`) but the endpoint queries `CloudResource` which has different names (`name`, no `resource_arn`, `raw_data`). `model_validate()` fails when CloudResource records exist.

## Design

### Part A: Resource Display Fix

Add `ResourceResponse.from_resource()` classmethod that maps `CloudResource` → API schema:

```
CloudResource.name          → ResourceResponse.resource_name
CloudResource.raw_data      → ResourceResponse.resource_metadata
CloudResource.raw_data.Arn  → ResourceResponse.resource_arn (extracted if present)
CloudResource.provider      → ResourceResponse.provider
```

Replace all `ResourceResponse.model_validate(r)` calls with `ResourceResponse.from_resource(r)`.

**Files changed**: `src/agenticops/web/app.py`

### Part B: Programmatic Parallel Scanner

A new `scanner/` module that orchestrates parallel multi-account scanning using the existing CLI tools from `providers/`. No SDK calls, no new cloud abstractions — CLI tools are the universal interface for all cloud operations (scan, detect, health check, changes).

#### Architecture

```
scan_accounts_parallel(account_ids=None, focus="all", regions=None)
  │
  ├── Load enabled CloudAccounts (filter by account_ids if given)
  ├── For each account, resolve provider CLI tool via providers/base.py
  │   (skip account if credentials fail or CLI not found)
  │
  ├── asyncio.gather(*[to_thread(scan_one_account, acct, cli_tool, ...) for acct in accounts])
  │     │
  │     └── scan_one_account(acct, cli_tool, focus, regions):
  │           ├── regions = regions or acct.regions
  │           ├── commands = PROVIDER_COMMANDS[acct.provider][focus]
  │           ├── For each region:
  │           │     For each command:
  │           │       output = cli_tool(command.format(region=region))
  │           │       resources.extend(parse_output(acct.provider, command_key, output, region))
  │           ├── Bulk save to CloudResource (reuse save_resources logic)
  │           ├── Update acct.last_scanned_at
  │           └── Return AccountScanResult
  │
  └── Return ScanResult { accounts: [AccountScanResult], total_resources, duration_s }
```

#### Provider Command Maps

Predefined CLI commands per provider per scan_focus category:

```python
AWS_COMMANDS = {
    "computing": [
        ("ec2-instances", "aws ec2 describe-instances --region {region}"),
        ("lambda-functions", "aws lambda list-functions --region {region}"),
        ("ecs-clusters", "aws ecs list-clusters --region {region}"),
        ("eks-clusters", "aws eks list-clusters --region {region}"),
    ],
    "databases": [
        ("rds-instances", "aws rds describe-db-instances --region {region}"),
        ("dynamodb-tables", "aws dynamodb list-tables --region {region}"),
        ("elasticache", "aws elasticache describe-cache-clusters --region {region}"),
    ],
    "storage": [
        ("s3-buckets", "aws s3api list-buckets"),  # global, run once
        ("ebs-volumes", "aws ec2 describe-volumes --region {region}"),
    ],
    "networking": [
        ("vpcs", "aws ec2 describe-vpcs --region {region}"),
        ("security-groups", "aws ec2 describe-security-groups --region {region}"),
        ("load-balancers", "aws elbv2 describe-load-balancers --region {region}"),
    ],
}
# Azure, GCP, Alicloud: add when needed. Skip if CLI not on PATH.
```

#### Output Parsers

`parsers.py` — one parser per (provider, command_key) that extracts standardized fields:

```python
def parse_aws_ec2_instances(raw_json: str, region: str) -> list[dict]:
    """Parse 'aws ec2 describe-instances' output → resource dicts."""
    # Returns: [{resource_id, resource_type, name, region, status, tags, raw_data}, ...]
```

Each parser is a simple function: parse JSON, extract fields, return list of dicts. Error in one parser doesn't affect others.

#### File Structure

```
src/agenticops/scanner/
  __init__.py          # re-export scan_accounts_parallel
  engine.py            # scan_accounts_parallel(), scan_one_account(), ScanResult
  commands.py          # AWS_COMMANDS, AZURE_COMMANDS, etc.
  parsers.py           # parse_aws_ec2_instances(), parse_aws_rds_instances(), etc.
```

#### Integration

1. **Agent tool**: New `@tool scan_resources(account_ids, services, regions)` wraps `scan_accounts_parallel()`. Scan agent system prompt updated to prefer this tool for standard scans, CLI tools for ad-hoc investigation.

2. **Web API**: `POST /api/scan` triggers parallel scan. Accepts optional `account_ids`, `focus`, `regions`. Returns `ScanResult`.

3. **Scheduler**: Pipelines call `scan_accounts_parallel()` instead of spawning LLM scan agent.

4. **Existing LLM scan agent**: Kept as-is. Still available for user-directed ad-hoc scans via chat. Its system prompt is updated to call `scan_resources` tool first for standard full scans.

#### Error Handling

- Per-account isolation: one account failing doesn't block others
- CLI timeout (existing 30s per command): caught, logged, continue to next command
- Parse errors: logged, skip that resource type, continue
- Credential failures: skip account, include in ScanResult.errors

#### Data Types

```python
@dataclass
class AccountScanResult:
    account_id: int
    account_name: str
    provider: str
    resources_found: int
    resources_updated: int
    regions_scanned: list[str]
    errors: list[str]

@dataclass
class ScanResult:
    accounts: list[AccountScanResult]
    total_found: int
    total_updated: int
    duration_s: float
```

## Out of Scope

- Azure/GCP/Alicloud command maps (add when accounts exist)
- Incremental/delta scanning (future optimization)
- Scan progress streaming via SSE (future)
