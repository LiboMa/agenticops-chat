# Parallel Multi-Account Scanner Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scan multiple cloud accounts in parallel using existing CLI tools, replacing the sequential LLM agent loop.

**Architecture:** A new `scanner/` module orchestrates parallel scanning by fan-out of existing provider CLI tools across accounts via `asyncio.gather + to_thread`. Predefined CLI command maps per provider/category drive the discovery. Output parsers normalize CLI JSON into standardized resource dicts for `save_resources()`.

**Tech Stack:** Python asyncio, existing provider CLI tools (`providers/base.py`), existing `save_resources()` from `metadata_tools.py`.

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `src/agenticops/scanner/__init__.py` | Create | Re-export `scan_accounts_parallel` |
| `src/agenticops/scanner/commands.py` | Create | Per-provider CLI command maps |
| `src/agenticops/scanner/parsers.py` | Create | Parse CLI JSON → standardized resource dicts |
| `src/agenticops/scanner/engine.py` | Create | Parallel scan orchestration |
| `src/agenticops/agents/scan_agent.py` | Modify | Add `scan_resources` tool, update prompt |
| `src/agenticops/web/app.py` | Modify | Add `POST /api/scan` endpoint |
| `tests/test_scanner_parsers.py` | Create | Parser unit tests |
| `tests/test_scanner_engine.py` | Create | Engine orchestration tests |
| `tests/test_scan_api.py` | Create | API endpoint test |

---

### Task 1: CLI Command Maps

**Files:**
- Create: `src/agenticops/scanner/__init__.py`
- Create: `src/agenticops/scanner/commands.py`

- [ ] **Step 1: Create scanner package**

```python
# src/agenticops/scanner/__init__.py
"""Parallel multi-account cloud resource scanner."""
```

- [ ] **Step 2: Create command maps**

Create `src/agenticops/scanner/commands.py` with per-provider, per-category CLI commands. Use `{region}` placeholder. Commands map to `(key, command)` tuples where `key` identifies the parser.

Reference `SCAN_FOCUS_SERVICES` from `src/agenticops/config.py:676-684` for category names.

```python
# src/agenticops/scanner/commands.py
"""Per-provider CLI command maps for resource discovery."""

# (parser_key, cli_command) — {region} is substituted at runtime
# Commands marked "global" run once, not per-region.

AWS_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "computing": [
        ("aws_ec2_instances", "aws ec2 describe-instances --region {region}"),
        ("aws_lambda_functions", "aws lambda list-functions --region {region}"),
        ("aws_ecs_clusters", "aws ecs list-clusters --region {region}"),
        ("aws_eks_clusters", "aws eks list-clusters --region {region}"),
    ],
    "networking": [
        ("aws_vpcs", "aws ec2 describe-vpcs --region {region}"),
        ("aws_security_groups", "aws ec2 describe-security-groups --region {region}"),
        ("aws_load_balancers", "aws elbv2 describe-load-balancers --region {region}"),
        ("aws_subnets", "aws ec2 describe-subnets --region {region}"),
    ],
    "databases": [
        ("aws_rds_instances", "aws rds describe-db-instances --region {region}"),
        ("aws_dynamodb_tables", "aws dynamodb list-tables --region {region}"),
        ("aws_elasticache", "aws elasticache describe-cache-clusters --region {region}"),
    ],
    "storage": [
        ("aws_s3_buckets", "aws s3api list-buckets"),  # global
        ("aws_ebs_volumes", "aws ec2 describe-volumes --region {region}"),
    ],
    "security": [
        ("aws_iam_roles", "aws iam list-roles"),  # global
    ],
}

# Global commands (no {region} placeholder) — run once, not per-region
AWS_GLOBAL_COMMANDS = {"aws_s3_buckets", "aws_iam_roles"}

PROVIDER_COMMANDS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "aws": AWS_COMMANDS,
    # "azure": AZURE_COMMANDS,  # add when needed
    # "gcp": GCP_COMMANDS,
    # "alicloud": ALICLOUD_COMMANDS,
}
```

- [ ] **Step 3: Commit**

```bash
git add src/agenticops/scanner/
git commit -m "feat(scanner): add CLI command maps for parallel scan"
```

---

### Task 2: Output Parsers

**Files:**
- Create: `src/agenticops/scanner/parsers.py`
- Create: `tests/test_scanner_parsers.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_scanner_parsers.py`. Test each parser with representative CLI output JSON. Reference actual AWS CLI output formats.

```python
# tests/test_scanner_parsers.py
"""Tests for scanner CLI output parsers."""
import json
import pytest
from agenticops.scanner.parsers import parse_cli_output


class TestEC2Parser:
    def test_parse_instances(self):
        raw = json.dumps({"Reservations": [{"Instances": [{
            "InstanceId": "i-abc123",
            "InstanceType": "t3.large",
            "State": {"Name": "running"},
            "Tags": [{"Key": "Name", "Value": "web-prod"}],
            "VpcId": "vpc-123",
        }]}]})
        result = parse_cli_output("aws_ec2_instances", raw, "us-east-1")
        assert len(result) == 1
        r = result[0]
        assert r["resource_id"] == "i-abc123"
        assert r["resource_type"] == "EC2"
        assert r["name"] == "web-prod"
        assert r["status"] == "running"
        assert r["region"] == "us-east-1"
        assert r["tags"] == {"Name": "web-prod"}

    def test_parse_empty_reservations(self):
        raw = json.dumps({"Reservations": []})
        result = parse_cli_output("aws_ec2_instances", raw, "us-east-1")
        assert result == []


class TestLambdaParser:
    def test_parse_functions(self):
        raw = json.dumps({"Functions": [{
            "FunctionName": "my-func",
            "FunctionArn": "arn:aws:lambda:us-east-1:123:function:my-func",
            "Runtime": "python3.12",
            "State": "Active",
        }]})
        result = parse_cli_output("aws_lambda_functions", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-func"
        assert result[0]["resource_type"] == "Lambda"


class TestRDSParser:
    def test_parse_db_instances(self):
        raw = json.dumps({"DBInstances": [{
            "DBInstanceIdentifier": "mydb",
            "DBInstanceArn": "arn:aws:rds:us-east-1:123:db:mydb",
            "Engine": "mysql",
            "DBInstanceStatus": "available",
        }]})
        result = parse_cli_output("aws_rds_instances", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "mydb"
        assert result[0]["resource_type"] == "RDS"
        assert result[0]["status"] == "available"


class TestS3Parser:
    def test_parse_buckets(self):
        raw = json.dumps({"Buckets": [
            {"Name": "my-bucket", "CreationDate": "2024-01-01T00:00:00Z"},
        ]})
        result = parse_cli_output("aws_s3_buckets", raw, "global")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-bucket"
        assert result[0]["resource_type"] == "S3"


class TestVPCParser:
    def test_parse_vpcs(self):
        raw = json.dumps({"Vpcs": [{
            "VpcId": "vpc-123",
            "CidrBlock": "10.0.0.0/16",
            "State": "available",
            "Tags": [{"Key": "Name", "Value": "prod-vpc"}],
        }]})
        result = parse_cli_output("aws_vpcs", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "vpc-123"
        assert result[0]["resource_type"] == "VPC"


class TestSecurityGroupParser:
    def test_parse_sgs(self):
        raw = json.dumps({"SecurityGroups": [{
            "GroupId": "sg-abc",
            "GroupName": "web-sg",
            "VpcId": "vpc-123",
        }]})
        result = parse_cli_output("aws_security_groups", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "sg-abc"
        assert result[0]["resource_type"] == "SecurityGroup"


class TestELBParser:
    def test_parse_load_balancers(self):
        raw = json.dumps({"LoadBalancers": [{
            "LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-lb/abc",
            "LoadBalancerName": "my-lb",
            "State": {"Code": "active"},
            "Type": "application",
        }]})
        result = parse_cli_output("aws_load_balancers", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-lb"
        assert result[0]["resource_type"] == "ELB"


class TestDynamoDBParser:
    def test_parse_tables(self):
        raw = json.dumps({"TableNames": ["users", "orders"]})
        result = parse_cli_output("aws_dynamodb_tables", raw, "us-east-1")
        assert len(result) == 2
        assert result[0]["resource_id"] == "users"
        assert result[0]["resource_type"] == "DynamoDB"


class TestECSParser:
    def test_parse_clusters(self):
        raw = json.dumps({"clusterArns": [
            "arn:aws:ecs:us-east-1:123:cluster/my-cluster",
        ]})
        result = parse_cli_output("aws_ecs_clusters", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-cluster"
        assert result[0]["resource_type"] == "ECS"


class TestEKSParser:
    def test_parse_clusters(self):
        raw = json.dumps({"clusters": ["prod-eks", "staging-eks"]})
        result = parse_cli_output("aws_eks_clusters", raw, "us-east-1")
        assert len(result) == 2
        assert result[0]["resource_id"] == "prod-eks"
        assert result[0]["resource_type"] == "EKS"


class TestSubnetParser:
    def test_parse_subnets(self):
        raw = json.dumps({"Subnets": [{
            "SubnetId": "subnet-abc",
            "VpcId": "vpc-123",
            "CidrBlock": "10.0.1.0/24",
            "AvailabilityZone": "us-east-1a",
            "State": "available",
            "Tags": [{"Key": "Name", "Value": "pub-1a"}],
        }]})
        result = parse_cli_output("aws_subnets", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "subnet-abc"
        assert result[0]["resource_type"] == "Subnet"


class TestElastiCacheParser:
    def test_parse_clusters(self):
        raw = json.dumps({"CacheClusters": [{
            "CacheClusterId": "my-redis",
            "Engine": "redis",
            "CacheClusterStatus": "available",
        }]})
        result = parse_cli_output("aws_elasticache", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-redis"
        assert result[0]["resource_type"] == "ElastiCache"


class TestEBSParser:
    def test_parse_volumes(self):
        raw = json.dumps({"Volumes": [{
            "VolumeId": "vol-abc",
            "Size": 100,
            "State": "in-use",
            "Tags": [{"Key": "Name", "Value": "data-vol"}],
        }]})
        result = parse_cli_output("aws_ebs_volumes", raw, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "vol-abc"
        assert result[0]["resource_type"] == "EBS"


class TestIAMParser:
    def test_parse_roles(self):
        raw = json.dumps({"Roles": [{
            "RoleName": "my-role",
            "Arn": "arn:aws:iam::123:role/my-role",
        }]})
        result = parse_cli_output("aws_iam_roles", raw, "global")
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-role"
        assert result[0]["resource_type"] == "IAMRole"


class TestUnknownParser:
    def test_unknown_key_returns_empty(self):
        result = parse_cli_output("unknown_key", "{}", "us-east-1")
        assert result == []

    def test_invalid_json_returns_empty(self):
        result = parse_cli_output("aws_ec2_instances", "not json", "us-east-1")
        assert result == []

    def test_error_output_returns_empty(self):
        result = parse_cli_output("aws_ec2_instances", "Error: access denied", "us-east-1")
        assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scanner_parsers.py -v`
Expected: ImportError (parsers module doesn't exist yet)

- [ ] **Step 3: Implement parsers**

Create `src/agenticops/scanner/parsers.py`. Single dispatch function `parse_cli_output(parser_key, raw_json, region)` that routes to specific parsers. Each parser is a simple function: parse JSON, extract standardized fields.

Helper `_aws_tags_to_dict()` converts AWS tag list `[{Key, Value}]` to dict.

```python
# src/agenticops/scanner/parsers.py
"""Parse CLI JSON output into standardized resource dicts."""

import json
import logging

logger = logging.getLogger(__name__)


def _aws_tags_to_dict(tags: list | None) -> dict:
    """Convert AWS [{Key, Value}] tag list to dict."""
    if not tags:
        return {}
    return {t["Key"]: t["Value"] for t in tags if "Key" in t and "Value" in t}


def _name_from_tags(tags: list | None) -> str:
    """Extract Name tag value."""
    for t in (tags or []):
        if t.get("Key") == "Name":
            return t.get("Value", "")
    return ""


def parse_cli_output(parser_key: str, raw: str, region: str) -> list[dict]:
    """Parse CLI output using the parser for the given key.

    Returns list of standardized resource dicts:
        {resource_id, resource_type, name, region, status, tags, raw_data}
    """
    parser = _PARSERS.get(parser_key)
    if not parser:
        logger.debug("No parser for key '%s'", parser_key)
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    try:
        return parser(data, region)
    except Exception as e:
        logger.warning("Parser %s failed: %s", parser_key, e)
        return []


# ── Individual parsers ─────────────────────────────────────────────


def _parse_ec2_instances(data: dict, region: str) -> list[dict]:
    results = []
    for res in data.get("Reservations", []):
        for inst in res.get("Instances", []):
            tags = inst.get("Tags", [])
            results.append({
                "resource_id": inst["InstanceId"],
                "resource_type": "EC2",
                "name": _name_from_tags(tags),
                "region": region,
                "status": inst.get("State", {}).get("Name", "unknown"),
                "tags": _aws_tags_to_dict(tags),
                "raw_data": inst,
            })
    return results


def _parse_lambda_functions(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": f["FunctionName"],
        "resource_type": "Lambda",
        "name": f["FunctionName"],
        "region": region,
        "status": f.get("State", "unknown"),
        "tags": f.get("Tags", {}),
        "raw_data": f,
    } for f in data.get("Functions", [])]


def _parse_ecs_clusters(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": arn.rsplit("/", 1)[-1],
        "resource_type": "ECS",
        "name": arn.rsplit("/", 1)[-1],
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": {"clusterArn": arn},
    } for arn in data.get("clusterArns", [])]


def _parse_eks_clusters(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": name,
        "resource_type": "EKS",
        "name": name,
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": {},
    } for name in data.get("clusters", [])]


def _parse_rds_instances(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": db["DBInstanceIdentifier"],
        "resource_type": "RDS",
        "name": db["DBInstanceIdentifier"],
        "region": region,
        "status": db.get("DBInstanceStatus", "unknown"),
        "tags": {},
        "raw_data": db,
    } for db in data.get("DBInstances", [])]


def _parse_dynamodb_tables(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": name,
        "resource_type": "DynamoDB",
        "name": name,
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": {},
    } for name in data.get("TableNames", [])]


def _parse_elasticache(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": c["CacheClusterId"],
        "resource_type": "ElastiCache",
        "name": c["CacheClusterId"],
        "region": region,
        "status": c.get("CacheClusterStatus", "unknown"),
        "tags": {},
        "raw_data": c,
    } for c in data.get("CacheClusters", [])]


def _parse_s3_buckets(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": b["Name"],
        "resource_type": "S3",
        "name": b["Name"],
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": b,
    } for b in data.get("Buckets", [])]


def _parse_ebs_volumes(data: dict, region: str) -> list[dict]:
    results = []
    for v in data.get("Volumes", []):
        tags = v.get("Tags", [])
        results.append({
            "resource_id": v["VolumeId"],
            "resource_type": "EBS",
            "name": _name_from_tags(tags),
            "region": region,
            "status": v.get("State", "unknown"),
            "tags": _aws_tags_to_dict(tags),
            "raw_data": v,
        })
    return results


def _parse_vpcs(data: dict, region: str) -> list[dict]:
    results = []
    for vpc in data.get("Vpcs", []):
        tags = vpc.get("Tags", [])
        results.append({
            "resource_id": vpc["VpcId"],
            "resource_type": "VPC",
            "name": _name_from_tags(tags),
            "region": region,
            "status": vpc.get("State", "unknown"),
            "tags": _aws_tags_to_dict(tags),
            "raw_data": vpc,
        })
    return results


def _parse_security_groups(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": sg["GroupId"],
        "resource_type": "SecurityGroup",
        "name": sg.get("GroupName", ""),
        "region": region,
        "status": "active",
        "tags": _aws_tags_to_dict(sg.get("Tags", [])),
        "raw_data": sg,
    } for sg in data.get("SecurityGroups", [])]


def _parse_load_balancers(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": lb["LoadBalancerName"],
        "resource_type": "ELB",
        "name": lb["LoadBalancerName"],
        "region": region,
        "status": lb.get("State", {}).get("Code", "unknown"),
        "tags": {},
        "raw_data": lb,
    } for lb in data.get("LoadBalancers", [])]


def _parse_subnets(data: dict, region: str) -> list[dict]:
    results = []
    for s in data.get("Subnets", []):
        tags = s.get("Tags", [])
        results.append({
            "resource_id": s["SubnetId"],
            "resource_type": "Subnet",
            "name": _name_from_tags(tags),
            "region": region,
            "status": s.get("State", "unknown"),
            "tags": _aws_tags_to_dict(tags),
            "raw_data": s,
        })
    return results


def _parse_iam_roles(data: dict, region: str) -> list[dict]:
    return [{
        "resource_id": r["RoleName"],
        "resource_type": "IAMRole",
        "name": r["RoleName"],
        "region": region,
        "status": "active",
        "tags": {},
        "raw_data": r,
    } for r in data.get("Roles", [])]


# ── Parser registry ───────────────────────────────────────────────

_PARSERS: dict[str, callable] = {
    "aws_ec2_instances": _parse_ec2_instances,
    "aws_lambda_functions": _parse_lambda_functions,
    "aws_ecs_clusters": _parse_ecs_clusters,
    "aws_eks_clusters": _parse_eks_clusters,
    "aws_rds_instances": _parse_rds_instances,
    "aws_dynamodb_tables": _parse_dynamodb_tables,
    "aws_elasticache": _parse_elasticache,
    "aws_s3_buckets": _parse_s3_buckets,
    "aws_ebs_volumes": _parse_ebs_volumes,
    "aws_vpcs": _parse_vpcs,
    "aws_security_groups": _parse_security_groups,
    "aws_load_balancers": _parse_load_balancers,
    "aws_subnets": _parse_subnets,
    "aws_iam_roles": _parse_iam_roles,
}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_scanner_parsers.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/scanner/parsers.py tests/test_scanner_parsers.py
git commit -m "feat(scanner): add CLI output parsers with tests"
```

---

### Task 3: Scan Engine

**Files:**
- Create: `src/agenticops/scanner/engine.py`
- Modify: `src/agenticops/scanner/__init__.py`
- Create: `tests/test_scanner_engine.py`

- [ ] **Step 1: Write engine tests**

Create `tests/test_scanner_engine.py`. Test the engine with mocked CLI tools and DB.

```python
# tests/test_scanner_engine.py
"""Tests for parallel scan engine."""
import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock
from agenticops.scanner.engine import scan_accounts_parallel, scan_one_account, ScanResult, AccountScanResult


class TestScanOneAccount:
    def test_runs_commands_for_focus(self):
        """scan_one_account runs CLI commands and parses output."""
        cli_tool = MagicMock(return_value='{"Reservations": []}')
        acct = SimpleNamespace(
            id=1, name="test", provider="aws", regions=["us-east-1"],
        )
        result = scan_one_account(acct, cli_tool, focus="computing")
        assert isinstance(result, AccountScanResult)
        assert result.account_name == "test"
        assert "us-east-1" in result.regions_scanned
        # CLI tool called at least once (for ec2, lambda, ecs, eks)
        assert cli_tool.call_count >= 1

    def test_skips_unknown_provider(self):
        cli_tool = MagicMock()
        acct = SimpleNamespace(
            id=1, name="test", provider="unknown_cloud", regions=["region-1"],
        )
        result = scan_one_account(acct, cli_tool, focus="all")
        assert result.resources_found == 0
        assert len(result.errors) > 0

    def test_handles_cli_error(self):
        """CLI errors are caught and logged, not raised."""
        cli_tool = MagicMock(return_value="Error: access denied")
        acct = SimpleNamespace(
            id=1, name="test", provider="aws", regions=["us-east-1"],
        )
        result = scan_one_account(acct, cli_tool, focus="computing")
        assert isinstance(result, AccountScanResult)
        # Should not raise, resources_found may be 0


class TestScanAccountsParallel:
    def test_returns_scan_result(self):
        """scan_accounts_parallel returns ScanResult with per-account results."""
        mock_acct = SimpleNamespace(
            id=1, name="test-aws", provider="aws",
            credentials={}, regions=["us-east-1"], labels={}, is_enabled=True,
        )
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_cli = MagicMock(return_value='{"Reservations": []}')
        mock_provider.cli_tool.return_value = mock_cli

        with patch("agenticops.scanner.engine._load_accounts", return_value=[mock_acct]), \
             patch("agenticops.scanner.engine._get_provider_and_tool", return_value=(mock_provider, mock_cli)), \
             patch("agenticops.scanner.engine._save_resources"):
            result = asyncio.run(scan_accounts_parallel())

        assert isinstance(result, ScanResult)
        assert len(result.accounts) == 1
        assert result.accounts[0].account_name == "test-aws"

    def test_skips_failed_credentials(self):
        """Accounts with failed credentials are skipped."""
        mock_acct = SimpleNamespace(
            id=1, name="bad-creds", provider="aws",
            credentials={}, regions=["us-east-1"], labels={}, is_enabled=True,
        )
        with patch("agenticops.scanner.engine._load_accounts", return_value=[mock_acct]), \
             patch("agenticops.scanner.engine._get_provider_and_tool", return_value=None):
            result = asyncio.run(scan_accounts_parallel())

        assert isinstance(result, ScanResult)
        assert len(result.accounts) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scanner_engine.py -v`
Expected: ImportError

- [ ] **Step 3: Implement engine**

Create `src/agenticops/scanner/engine.py`:

```python
# src/agenticops/scanner/engine.py
"""Parallel multi-account scan engine."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional

from agenticops.scanner.commands import PROVIDER_COMMANDS, AWS_GLOBAL_COMMANDS
from agenticops.scanner.parsers import parse_cli_output

logger = logging.getLogger(__name__)


@dataclass
class AccountScanResult:
    account_id: int
    account_name: str
    provider: str
    resources_found: int = 0
    resources_updated: int = 0
    regions_scanned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    accounts: list[AccountScanResult] = field(default_factory=list)
    total_found: int = 0
    total_updated: int = 0
    duration_s: float = 0.0


def _load_accounts(account_ids: list[int] | None = None) -> list:
    """Load enabled CloudAccounts from DB, return as detached snapshots."""
    from agenticops.models import CloudAccount, get_db_session
    with get_db_session() as db:
        query = db.query(CloudAccount).filter(CloudAccount.is_enabled == True)  # noqa: E712
        if account_ids:
            query = query.filter(CloudAccount.id.in_(account_ids))
        accounts = query.all()
        return [
            SimpleNamespace(
                id=a.id, name=a.name, provider=a.provider,
                credentials=dict(a.credentials or {}),
                regions=list(a.regions or []), labels=dict(a.labels or {}),
            )
            for a in accounts
        ]


def _get_provider_and_tool(acct) -> tuple | None:
    """Resolve provider and CLI tool for an account. Returns (provider, cli_tool) or None."""
    from agenticops.providers.base import get_provider
    try:
        provider = get_provider(acct)
        if provider.resolve_credentials():
            return provider, provider.cli_tool()
    except Exception as e:
        logger.warning("Failed to init provider for %s: %s", acct.name, e)
    return None


def _save_resources(account_id: int, provider: str, resources: list[dict]) -> tuple[int, int]:
    """Save resources to DB. Returns (created, updated)."""
    if not resources:
        return 0, 0
    from agenticops.tools.metadata_tools import save_resources
    result = save_resources(json.dumps(resources), account_id=account_id, provider=provider)
    # Parse "Saved N new resources, updated M existing" from result
    created = updated = 0
    if "Saved" in result:
        import re
        m = re.search(r"Saved (\d+) new.*updated (\d+)", result)
        if m:
            created, updated = int(m.group(1)), int(m.group(2))
    return created, updated


def scan_one_account(
    acct,
    cli_tool,
    focus: str = "all",
    regions: list[str] | None = None,
) -> AccountScanResult:
    """Scan a single account using its CLI tool. Runs in a thread."""
    result = AccountScanResult(
        account_id=acct.id,
        account_name=acct.name,
        provider=acct.provider,
    )

    commands_map = PROVIDER_COMMANDS.get(acct.provider)
    if not commands_map:
        result.errors.append(f"No command map for provider '{acct.provider}'")
        return result

    # Resolve categories
    if focus == "all":
        categories = list(commands_map.keys())
    else:
        categories = [c.strip() for c in focus.split(",") if c.strip() in commands_map]

    scan_regions = regions or acct.regions or ["us-east-1"]
    result.regions_scanned = list(scan_regions)
    all_resources: list[dict] = []
    global_done: set[str] = set()

    for category in categories:
        for parser_key, cmd_template in commands_map.get(category, []):
            # Global commands run once
            if parser_key in AWS_GLOBAL_COMMANDS:
                if parser_key in global_done:
                    continue
                global_done.add(parser_key)
                try:
                    raw = cli_tool(command=cmd_template)
                    parsed = parse_cli_output(parser_key, raw, "global")
                    all_resources.extend(parsed)
                except Exception as e:
                    result.errors.append(f"{parser_key}: {e}")
                continue

            for region in scan_regions:
                cmd = cmd_template.format(region=region)
                try:
                    raw = cli_tool(command=cmd)
                    parsed = parse_cli_output(parser_key, raw, region)
                    all_resources.extend(parsed)
                except Exception as e:
                    result.errors.append(f"{parser_key}/{region}: {e}")

    result.resources_found = len(all_resources)
    return result


async def scan_accounts_parallel(
    account_ids: list[int] | None = None,
    focus: str = "all",
    regions: list[str] | None = None,
) -> ScanResult:
    """Scan multiple accounts in parallel using their CLI tools.

    Args:
        account_ids: Specific account IDs to scan. None = all enabled.
        focus: Scan focus categories (computing,networking,databases,storage,security,all).
        regions: Override regions. None = use each account's configured regions.

    Returns:
        ScanResult with per-account results.
    """
    start = time.time()
    accounts = _load_accounts(account_ids)

    if not accounts:
        return ScanResult(duration_s=time.time() - start)

    # Resolve CLI tools (sequential — credential resolution may call STS)
    account_tools: list[tuple] = []
    for acct in accounts:
        result = _get_provider_and_tool(acct)
        if result:
            _, cli_tool = result
            account_tools.append((acct, cli_tool))
        else:
            logger.warning("Skipping account %s: credentials failed", acct.name)

    if not account_tools:
        return ScanResult(duration_s=time.time() - start)

    # Parallel scan
    async def _scan_and_save(acct, cli_tool):
        acct_result = await asyncio.to_thread(
            scan_one_account, acct, cli_tool, focus, regions
        )
        # Save resources in thread
        if acct_result.resources_found > 0:
            # Collect resources again for saving (scan_one_account doesn't return them)
            # Re-scan is wasteful — refactor: have scan_one_account return resources too
            pass
        return acct_result

    results = await asyncio.gather(*[
        _scan_and_save(acct, tool) for acct, tool in account_tools
    ])

    scan_result = ScanResult(
        accounts=list(results),
        total_found=sum(r.resources_found for r in results),
        total_updated=sum(r.resources_updated for r in results),
        duration_s=round(time.time() - start, 2),
    )
    return scan_result
```

**NOTE**: The `scan_one_account` function collects resources but doesn't return them for saving. The implementer should refactor so `scan_one_account` returns the resource list AND the result, then `_scan_and_save` calls `_save_resources` with that list. Update `scan_one_account` to return `(AccountScanResult, list[dict])`.

- [ ] **Step 4: Update `__init__.py`**

```python
# src/agenticops/scanner/__init__.py
"""Parallel multi-account cloud resource scanner."""
from agenticops.scanner.engine import scan_accounts_parallel, ScanResult, AccountScanResult

__all__ = ["scan_accounts_parallel", "ScanResult", "AccountScanResult"]
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_scanner_engine.py tests/test_scanner_parsers.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/scanner/ tests/test_scanner_engine.py
git commit -m "feat(scanner): parallel scan engine with asyncio fan-out"
```

---

### Task 4: Agent Tool + Scan Agent Update

**Files:**
- Modify: `src/agenticops/agents/scan_agent.py`

- [ ] **Step 1: Add scan_resources tool**

Add a new `@tool scan_resources()` function that wraps `scan_accounts_parallel()`:

```python
# Add to src/agenticops/agents/scan_agent.py, before the existing scan_agent function

@tool
def scan_resources(account_ids: str = "", focus: str = "all", regions: str = "") -> str:
    """Programmatic parallel scan of cloud resources across all enabled accounts.

    Uses predefined CLI commands per provider — much faster than manual scanning.
    Prefer this for standard full scans. Use per-account CLI tools only for ad-hoc investigation.

    Args:
        account_ids: Comma-separated account IDs to scan, or empty for all enabled.
        focus: Scan focus: computing,networking,databases,storage,security,all.
        regions: Comma-separated regions to scan, or empty for each account's configured regions.

    Returns:
        Summary of scan results per account.
    """
    import asyncio
    from agenticops.scanner import scan_accounts_parallel

    ids = [int(x.strip()) for x in account_ids.split(",") if x.strip()] or None
    rgns = [r.strip() for r in regions.split(",") if r.strip()] or None

    try:
        result = asyncio.run(scan_accounts_parallel(account_ids=ids, focus=focus, regions=rgns))
    except RuntimeError:
        # If already in an event loop (web context)
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(scan_accounts_parallel(account_ids=ids, focus=focus, regions=rgns))

    lines = [f"Scan complete in {result.duration_s}s — {result.total_found} resources found."]
    for a in result.accounts:
        lines.append(f"  {a.account_name} ({a.provider}): {a.resources_found} found, {a.resources_updated} updated, regions={a.regions_scanned}")
        for err in a.errors[:3]:
            lines.append(f"    ⚠ {err}")
    return "\n".join(lines)
```

- [ ] **Step 2: Add scan_resources to scan agent tools**

In `scan_agent()` function, add `scan_resources` to the tools list (line ~83):

```python
tools: list = [get_enabled_accounts, get_active_account, save_resources, scan_resources]
tools.extend(get_all_cli_tools())
```

- [ ] **Step 3: Update scan agent prompt**

Update `SCAN_SYSTEM_PROMPT` to prefer `scan_resources` tool for standard scans:

Add after "## Workflow" section:
```
## Preferred Approach
For standard full scans, call scan_resources() — it runs predefined CLI commands across all accounts
in parallel. Only use individual account CLI tools (run_aws_cli_*, etc.) for ad-hoc investigation
or when you need to run specific commands not covered by the standard scan.
```

- [ ] **Step 4: Verify compile**

Run: `python3 -m py_compile src/agenticops/agents/scan_agent.py`
Expected: No output (success)

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/agents/scan_agent.py
git commit -m "feat(scanner): add scan_resources tool to scan agent"
```

---

### Task 5: Web API Endpoint

**Files:**
- Modify: `src/agenticops/web/app.py`
- Create: `tests/test_scan_api.py`

- [ ] **Step 1: Write API test**

```python
# tests/test_scan_api.py
"""Test POST /api/scan endpoint."""
import pytest
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from agenticops.web.app import app
from agenticops.scanner.engine import ScanResult, AccountScanResult


@pytest.fixture
def client():
    return TestClient(app)


def test_scan_endpoint_returns_result(client):
    mock_result = ScanResult(
        accounts=[AccountScanResult(
            account_id=1, account_name="test-aws", provider="aws",
            resources_found=5, resources_updated=2, regions_scanned=["us-east-1"],
        )],
        total_found=5, total_updated=2, duration_s=1.5,
    )
    with patch("agenticops.web.app.scan_accounts_parallel", return_value=mock_result):
        resp = client.post("/api/scan", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_found"] == 5
    assert len(data["accounts"]) == 1


def test_scan_endpoint_with_filters(client):
    mock_result = ScanResult(total_found=0, duration_s=0.1)
    with patch("agenticops.web.app.scan_accounts_parallel", return_value=mock_result):
        resp = client.post("/api/scan", json={
            "account_ids": [1, 2],
            "focus": "computing",
            "regions": ["us-east-1"],
        })
    assert resp.status_code == 200
```

- [ ] **Step 2: Add endpoint to app.py**

Add near the resource endpoints section in `src/agenticops/web/app.py`:

```python
class ScanRequest(BaseModel):
    account_ids: Optional[List[int]] = None
    focus: str = "all"
    regions: Optional[List[str]] = None


@app.post("/api/scan")
async def api_trigger_scan(req: ScanRequest):
    """Trigger parallel resource scan across enabled accounts."""
    from agenticops.scanner import scan_accounts_parallel
    result = await scan_accounts_parallel(
        account_ids=req.account_ids,
        focus=req.focus,
        regions=req.regions,
    )
    return {
        "total_found": result.total_found,
        "total_updated": result.total_updated,
        "duration_s": result.duration_s,
        "accounts": [
            {
                "account_id": a.account_id,
                "account_name": a.account_name,
                "provider": a.provider,
                "resources_found": a.resources_found,
                "resources_updated": a.resources_updated,
                "regions_scanned": a.regions_scanned,
                "errors": a.errors,
            }
            for a in result.accounts
        ],
    }
```

- [ ] **Step 3: Verify compile + tests**

Run: `python3 -m py_compile src/agenticops/web/app.py && pytest tests/test_scan_api.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/web/app.py tests/test_scan_api.py
git commit -m "feat(scanner): add POST /api/scan endpoint"
```

---

### Task 6: Final Verification

- [ ] **Step 1: Full syntax check**

```bash
python3 -m py_compile src/agenticops/web/app.py
python3 -m py_compile src/agenticops/agents/scan_agent.py
python3 -m py_compile src/agenticops/scanner/engine.py
```

- [ ] **Step 2: Frontend build**

```bash
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 3: Run all scanner tests**

```bash
pytest tests/test_scanner_parsers.py tests/test_scanner_engine.py tests/test_scan_api.py tests/test_providers.py -v
```

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -q --ignore=tests/test_dashboard_trends_api.py
```
Expected: Same or fewer failures than baseline (1 pre-existing notification test failure)
