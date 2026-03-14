"""Init and quickstart helper functions for AgenticOps CLI.

Extracted from main.py to keep it lean. Contains:
- Dependency checking
- JSON config file loading (--config setup.json)
- Auto-detect + propose setup (minimal user input)
- Deployment profile wizard (local/cloud)
- AWS account registration
- Notification channel guided config
- run_init_wizard() orchestrator
"""

import importlib
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from rich.box import SIMPLE

logger = logging.getLogger(__name__)
console = Console()

# ============================================================================
# JSON Config File Support
# ============================================================================

_CONFIG_TEMPLATE = {
    "bedrock": {
        "region": "us-east-1",
        "model": "sonnet",  # "opus", "sonnet", "haiku", or full model ID
    },
    "profile": "local",  # "local" or "cloud"
    "cloud": {
        "database": "rds",  # "rds", "sqlite-efs", "dynamodb"
        "rds_host": "",
        "rds_port": 5432,
        "rds_name": "agenticops",
        "rds_user": "agenticops",
        "rds_password": "",
        "efs_path": "/data/agenticops",
        "vector_storage": "rds",  # "rds" or "s3"
        "s3_bucket": "",  # auto-generated if empty: agenticops-{account_id}
        "s3_region": "us-east-1",
    },
    "accounts": [
        # {"name": "prod", "account_id": "123456789012", "role_arn": "", "regions": ["us-east-1"]}
    ],
    "pipeline": {
        "auto_fix": True,
        "auto_approve_l0_l1": True,
        "notifications": True,
    },
    "channels": [
        # {"name": "slack-alerts", "type": "slack", "webhook_url": "https://hooks.slack.com/..."},
        # {"name": "feishu-ops", "type": "feishu", "app_name": "default", "chat_id": "oc_xxx"},
        # {"name": "email-oncall", "type": "email", "smtp_host": "...", "smtp_port": 587, "smtp_user": "...", "smtp_password": "...", "from_addr": "...", "to_addr": "..."},
        # {"name": "sns-critical", "type": "sns", "topic_arn": "arn:aws:sns:...", "region": "us-east-1"},
        # {"name": "webhook-pd", "type": "webhook", "url": "https://...", "method": "POST"},
    ],
    "integrations": {
        "datadog": {
            "enabled": False,
            "api_key": "",
            "app_key": "",
            "site": "datadoghq.com",
        },
    },
}

from agenticops.config import MODEL_ALIASES, settings

# Derive from config's single source of truth
_MODEL_SHORTCUTS = MODEL_ALIASES
_HAIKU_ID = MODEL_ALIASES.get("haiku", settings.bedrock_model_id_cheap)
_SONNET_ID = MODEL_ALIASES.get("sonnet", settings.bedrock_model_id)
_OPUS_ID = MODEL_ALIASES.get("opus", settings.bedrock_model_id_strong)


def generate_config_template(output_path: Path) -> None:
    """Write a setup.json template file."""
    output_path.write_text(json.dumps(_CONFIG_TEMPLATE, indent=2) + "\n")
    console.print(f"[green]Generated config template:[/green] {output_path}")
    console.print("[dim]Edit the file, then run: aiops init --config setup.json[/dim]")


def load_config_file(config_path: Path) -> dict[str, str]:
    """Load a JSON config file and return env_vars dict.

    This is the zero-prompt path for advanced users.
    """
    cfg = json.loads(config_path.read_text())
    env_vars: dict[str, str] = {}

    # ── Bedrock ──
    bedrock = cfg.get("bedrock", {})
    region = bedrock.get("region", "us-east-1")
    env_vars["AIOPS_BEDROCK_REGION"] = region

    model = bedrock.get("model", "sonnet")
    model_id = _MODEL_SHORTCUTS.get(model, model)
    env_vars["AIOPS_BEDROCK_MODEL_ID"] = model_id
    if model == "haiku":
        env_vars["AIOPS_BEDROCK_MODEL_ID_CHEAP"] = _HAIKU_ID
        env_vars["AIOPS_BEDROCK_MODEL_ID_STRONG"] = _SONNET_ID
    else:
        env_vars["AIOPS_BEDROCK_MODEL_ID_CHEAP"] = _HAIKU_ID
        env_vars["AIOPS_BEDROCK_MODEL_ID_STRONG"] = _OPUS_ID

    # ── Profile ──
    profile = cfg.get("profile", "local")
    env_vars["AIOPS_DEPLOYMENT_PROFILE"] = profile

    if profile == "cloud":
        cloud = cfg.get("cloud", {})

        # Database
        db_type = cloud.get("database", "rds")
        if db_type == "rds":
            host = cloud.get("rds_host", "")
            port = cloud.get("rds_port", 5432)
            name = cloud.get("rds_name", "agenticops")
            user = cloud.get("rds_user", "agenticops")
            pwd = cloud.get("rds_password", "")
            if host:
                url = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{name}"
                env_vars["AIOPS_DATABASE_URL"] = url
        elif db_type == "sqlite-efs":
            efs_path = cloud.get("efs_path", "/data/agenticops")
            env_vars["AIOPS_DATABASE_URL"] = f"sqlite:///{efs_path}/agenticops.db"
            env_vars["AIOPS_DATA_DIR"] = efs_path

        # Vector storage
        vec = cloud.get("vector_storage", "rds")
        env_vars["AIOPS_VECTOR_STORAGE"] = vec
        if vec == "rds" and "AIOPS_DATABASE_URL" in env_vars:
            db_url = env_vars["AIOPS_DATABASE_URL"]
            if db_url.startswith("postgresql"):
                env_vars["AIOPS_VECTOR_RDS_URL"] = db_url
        elif vec == "s3":
            bucket = cloud.get("s3_bucket", "")
            s3_region = cloud.get("s3_region", region)
            if bucket:
                env_vars["AIOPS_VECTOR_S3_BUCKET"] = bucket
                env_vars["AIOPS_VECTOR_S3_REGION"] = s3_region

        # S3 file storage (reports + KB)
        bucket = cloud.get("s3_bucket", "")
        s3_region = cloud.get("s3_region", region)
        if bucket:
            env_vars["AIOPS_REPORT_STORAGE"] = "s3"
            env_vars["AIOPS_REPORT_S3_BUCKET"] = bucket
            env_vars["AIOPS_REPORT_S3_PREFIX"] = "reports/"
            env_vars["AIOPS_REPORT_S3_REGION"] = s3_region
            env_vars["AIOPS_KB_STORAGE"] = "s3"
            env_vars["AIOPS_KB_S3_BUCKET"] = bucket
            env_vars["AIOPS_KB_S3_PREFIX"] = "knowledge_base/"
            env_vars["AIOPS_KB_S3_REGION"] = s3_region

    # ── Pipeline ──
    pipeline = cfg.get("pipeline", {})
    env_vars["AIOPS_AUTO_FIX_ENABLED"] = str(pipeline.get("auto_fix", True)).lower()
    env_vars["AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1"] = str(pipeline.get("auto_approve_l0_l1", True)).lower()
    env_vars["AIOPS_NOTIFICATIONS_ENABLED"] = str(pipeline.get("notifications", True)).lower()

    # ── Accounts ──
    for acct in cfg.get("accounts", []):
        _register_account(acct)
        console.print(f"  [green]Registered account:[/green] {acct.get('name', 'default')} ({acct.get('account_id', '?')})")

    # ── Notification Channels ──
    for ch in cfg.get("channels", []):
        ch_name = ch.pop("name", "unnamed")
        ch_type = ch.pop("type", "webhook")
        sev = ch.pop("severity_filter", None)
        save_data = {"type": ch_type, "enabled": True, **ch}
        if sev:
            save_data["severity_filter"] = sev
        try:
            from agenticops.notify.im_config import save_channel
            save_channel(ch_name, save_data)
            console.print(f"  [green]Saved channel:[/green] {ch_name} ({ch_type})")
        except Exception as e:
            console.print(f"  [yellow]Channel {ch_name} failed: {e}[/yellow]")

    # ── Integrations ──
    integrations = cfg.get("integrations", {})
    dd = integrations.get("datadog", {})
    if dd.get("enabled"):
        env_vars["AIOPS_MONITORING_PROVIDERS"] = "datadog"
        env_vars["AIOPS_DATADOG_API_KEY"] = dd.get("api_key", "")
        env_vars["AIOPS_DATADOG_APP_KEY"] = dd.get("app_key", "")
        env_vars["AIOPS_DATADOG_SITE"] = dd.get("site", "datadoghq.com")

    return env_vars


# ============================================================================
# Phase 1: Dependency Check
# ============================================================================

REQUIRED_PIP_PACKAGES = [
    "boto3",
    "typer",
    "fastapi",
    "sqlalchemy",
    "strands_agents",
    "rich",
    "uvicorn",
    "sse_starlette",
    "pydantic",
    "pydantic_settings",
    "numpy",
    "networkx",
]

OPTIONAL_BINARIES = ["aws", "npm", "git"]


def _check_python_version() -> tuple[bool, str]:
    """Check Python >= 3.11."""
    v = sys.version_info
    ok = v >= (3, 11)
    return ok, f"{v.major}.{v.minor}.{v.micro}"


def _check_pip_packages() -> tuple[bool, list[str]]:
    """Check required pip packages, return (all_ok, missing_list)."""
    missing = []
    for pkg in REQUIRED_PIP_PACKAGES:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    return len(missing) == 0, missing


def _check_binary(name: str) -> bool:
    """Check if a binary is available on PATH."""
    return shutil.which(name) is not None


def _check_aws_credentials(region: str) -> tuple[bool, str]:
    """Check AWS credentials via STS. Returns (ok, account_id_or_error)."""
    try:
        import boto3

        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        return True, identity["Account"]
    except Exception as e:
        return False, str(e)


def _offer_install_missing(missing: list[str]) -> bool:
    """Offer to install missing pip packages. Returns True if installed."""
    from rich.prompt import Confirm

    if not Confirm.ask(
        f"  Install missing packages ({', '.join(missing)})?", default=True
    ):
        return False
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install"] + missing,
            check=True,
            capture_output=True,
        )
        console.print(f"  [green]Installed {len(missing)} package(s).[/green]")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"  [red]pip install failed: {e}[/red]")
        return False


def check_dependencies(verbose: bool = True) -> dict[str, bool]:
    """Check all dependencies, render Rich table, return pass/fail dict."""
    results: dict[str, bool] = {}

    py_ok, py_ver = _check_python_version()
    results["python"] = py_ok

    pkgs_ok, missing = _check_pip_packages()
    results["pip_packages"] = pkgs_ok

    for binary in OPTIONAL_BINARIES:
        results[binary] = _check_binary(binary)

    aws_ok, aws_info = _check_aws_credentials("us-east-1")
    results["aws_credentials"] = aws_ok

    if verbose:
        table = Table(title="Dependency Check", box=SIMPLE, show_header=True)
        table.add_column("Check", style="cyan")
        table.add_column("Status")
        table.add_column("Details", style="dim")

        def _icon(ok: bool, required: bool = True) -> str:
            if ok:
                return "[green]PASS[/green]"
            return "[red]FAIL[/red]" if required else "[yellow]WARN[/yellow]"

        table.add_row("Python >= 3.11", _icon(py_ok), f"v{py_ver}")
        table.add_row(
            "Core pip packages",
            _icon(pkgs_ok),
            f"missing: {', '.join(missing)}" if missing else "all present",
        )
        for binary in OPTIONAL_BINARIES:
            table.add_row(
                f"{binary} CLI",
                _icon(results[binary], required=False),
                shutil.which(binary) or "not found",
            )
        table.add_row(
            "AWS credentials",
            _icon(aws_ok, required=False),
            f"Account {aws_info}" if aws_ok else str(aws_info)[:60],
        )
        console.print(table)

    if missing and verbose:
        if _offer_install_missing(missing):
            results["pip_packages"] = True

    return results


# ============================================================================
# Auto-Detect Helpers
# ============================================================================


def _detect_aws_context(region: str = "us-east-1") -> dict:
    """Auto-detect AWS account, region, caller identity.

    Returns dict with keys: account_id, arn, region, ok.
    """
    try:
        import boto3

        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        return {
            "ok": True,
            "account_id": identity["Account"],
            "arn": identity["Arn"],
            "region": region,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "region": region}


def _propose_s3_bucket(account_id: str) -> str:
    """Generate a proposed S3 bucket name from account ID."""
    return f"agenticops-{account_id}"


# ============================================================================
# Phase 2: Deployment Profile (Propose + Confirm)
# ============================================================================


def init_deployment_profile(env_vars: dict[str, str], yes: bool = False) -> str:
    """Deployment profile wizard. Returns 'local' or 'cloud'."""
    from rich.prompt import Prompt, Confirm

    if yes:
        env_vars["AIOPS_DEPLOYMENT_PROFILE"] = "local"
        console.print("  [dim]Using default: local deployment profile[/dim]")
        return "local"

    console.print("  Select deployment profile:")
    console.print("    [bold][1][/bold] Local    — SQLite + local filesystem  [dim]<- default[/dim]")
    console.print("    [bold][2][/bold] Cloud    — RDS/EFS + S3 (production)")
    choice = Prompt.ask("\n  Choice", choices=["1", "2"], default="1")

    if choice == "1":
        env_vars["AIOPS_DEPLOYMENT_PROFILE"] = "local"
        console.print("  [green]Local profile selected.[/green]")
        return "local"

    # Cloud profile — auto-propose as much as possible
    env_vars["AIOPS_DEPLOYMENT_PROFILE"] = "cloud"
    region = env_vars.get("AIOPS_BEDROCK_REGION", "us-east-1")
    ctx = _detect_aws_context(region)
    account_id = ctx.get("account_id", "")

    # Database
    _init_cloud_database(env_vars)

    # Vector storage — auto-derive from DB choice
    db_url = env_vars.get("AIOPS_DATABASE_URL", "")
    if db_url.startswith("postgresql"):
        env_vars["AIOPS_VECTOR_STORAGE"] = "rds"
        env_vars["AIOPS_VECTOR_RDS_URL"] = db_url
        console.print("    [green]Vector storage: pgvector (same RDS instance)[/green]")
    else:
        env_vars["AIOPS_VECTOR_STORAGE"] = "s3"
        console.print("    [green]Vector storage: S3 (no RDS available)[/green]")

    # S3 file storage — propose bucket name
    proposed_bucket = _propose_s3_bucket(account_id) if account_id else "agenticops-data"
    bucket = Prompt.ask("  S3 bucket for reports + KB", default=proposed_bucket)
    _create_s3_bucket_if_needed(bucket, region)

    env_vars["AIOPS_REPORT_STORAGE"] = "s3"
    env_vars["AIOPS_REPORT_S3_BUCKET"] = bucket
    env_vars["AIOPS_REPORT_S3_PREFIX"] = "reports/"
    env_vars["AIOPS_REPORT_S3_REGION"] = region
    env_vars["AIOPS_KB_STORAGE"] = "s3"
    env_vars["AIOPS_KB_S3_BUCKET"] = bucket
    env_vars["AIOPS_KB_S3_PREFIX"] = "knowledge_base/"
    env_vars["AIOPS_KB_S3_REGION"] = region

    if env_vars.get("AIOPS_VECTOR_STORAGE") == "s3":
        env_vars["AIOPS_VECTOR_S3_BUCKET"] = bucket
        env_vars["AIOPS_VECTOR_S3_REGION"] = region

    console.print(f"    [green]S3 storage: s3://{bucket}/ (reports/ + knowledge_base/)[/green]")
    console.print("  [green]Cloud profile configured.[/green]")
    return "cloud"


def _init_cloud_database(env_vars: dict[str, str]) -> None:
    """Cloud database sub-choice: RDS or SQLite-on-EFS."""
    from rich.prompt import Prompt

    console.print("\n  Database backend:")
    console.print("    [bold][1][/bold] RDS PostgreSQL  [dim]<- recommended[/dim]")
    console.print("    [bold][2][/bold] SQLite on EFS")
    console.print("    [bold][3][/bold] DynamoDB  [dim](tables only, data layer coming soon)[/dim]")
    db_choice = Prompt.ask("  Choice", choices=["1", "2", "3"], default="1")

    if db_choice == "1":
        host = Prompt.ask("    RDS host")
        port = Prompt.ask("    RDS port", default="5432")
        db_name = Prompt.ask("    Database name", default="agenticops")
        user = Prompt.ask("    Username", default="agenticops")
        password = Prompt.ask("    Password (input hidden)", password=True)
        url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
        if _test_rds_connection(url):
            console.print("    [green]RDS connection verified.[/green]")
        else:
            console.print("    [yellow]RDS connection failed — saved anyway, fix later.[/yellow]")
        env_vars["AIOPS_DATABASE_URL"] = url

    elif db_choice == "2":
        efs_path = Prompt.ask("    EFS mount path", default="/data/agenticops")
        env_vars["AIOPS_DATABASE_URL"] = f"sqlite:///{efs_path}/agenticops.db"
        env_vars["AIOPS_DATA_DIR"] = efs_path
        console.print(f"    [green]SQLite on EFS: {efs_path}[/green]")

    elif db_choice == "3":
        region = env_vars.get("AIOPS_BEDROCK_REGION", "us-east-1")
        console.print(f"    Creating DynamoDB tables in {region}...")
        _create_dynamodb_tables(region)
        env_vars["AIOPS_DATABASE_BACKEND"] = "dynamodb"
        console.print("    [yellow]DynamoDB tables created. Data access layer coming in a future release.[/yellow]")


def _create_s3_bucket_if_needed(bucket: str, region: str) -> bool:
    """Create S3 bucket if it doesn't exist. Returns True on success."""
    try:
        import boto3

        s3 = boto3.client("s3", region_name=region)
        try:
            s3.head_bucket(Bucket=bucket)
            console.print(f"    [dim]Bucket {bucket} already exists.[/dim]")
            return True
        except Exception:
            pass

        create_kwargs: dict = {"Bucket": bucket}
        if region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": region
            }
        s3.create_bucket(**create_kwargs)
        s3.put_bucket_tagging(
            Bucket=bucket,
            Tagging={"TagSet": [{"Key": "Project", "Value": "AgenticOps"}]},
        )
        console.print(f"    [green]Created S3 bucket: {bucket}[/green]")
        return True
    except Exception as e:
        console.print(f"    [yellow]S3 bucket creation failed: {e}[/yellow]")
        return False


def _test_rds_connection(url: str) -> bool:
    """Test RDS connection."""
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception as e:
        logger.debug("RDS connection test failed: %s", e)
        return False


def _test_pgvector(url: str) -> bool:
    """Test pgvector extension availability."""
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("SELECT 1"))
            conn.commit()
        engine.dispose()
        return True
    except Exception as e:
        logger.debug("pgvector test failed: %s", e)
        return False


def _create_dynamodb_tables(region: str) -> None:
    """Create DynamoDB tables matching core models (init-only, no data layer yet)."""
    import boto3

    dynamodb = boto3.client("dynamodb", region_name=region)

    tables = [
        {
            "TableName": "agenticops-accounts",
            "KeySchema": [{"AttributeName": "account_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "account_id", "AttributeType": "S"},
            ],
        },
        {
            "TableName": "agenticops-resources",
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "id", "AttributeType": "N"},
                {"AttributeName": "account_id", "AttributeType": "S"},
                {"AttributeName": "resource_type", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "account_id-index",
                    "KeySchema": [{"AttributeName": "account_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "resource_type-index",
                    "KeySchema": [{"AttributeName": "resource_type", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        },
        {
            "TableName": "agenticops-issues",
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "id", "AttributeType": "N"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "fingerprint", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "status-index",
                    "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "fingerprint-index",
                    "KeySchema": [{"AttributeName": "fingerprint", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        },
        {
            "TableName": "agenticops-fixplans",
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "id", "AttributeType": "N"},
                {"AttributeName": "health_issue_id", "AttributeType": "N"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "health_issue_id-index",
                    "KeySchema": [{"AttributeName": "health_issue_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        },
        {
            "TableName": "agenticops-rca",
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "id", "AttributeType": "N"},
                {"AttributeName": "health_issue_id", "AttributeType": "N"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "health_issue_id-index",
                    "KeySchema": [{"AttributeName": "health_issue_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        },
        {
            "TableName": "agenticops-events",
            "KeySchema": [
                {"AttributeName": "health_issue_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "health_issue_id", "AttributeType": "N"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
        },
        {
            "TableName": "agenticops-reports",
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "id", "AttributeType": "N"},
            ],
        },
        {
            "TableName": "agenticops-chat-sessions",
            "KeySchema": [{"AttributeName": "session_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "session_id", "AttributeType": "S"},
            ],
        },
        {
            "TableName": "agenticops-chat-messages",
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "id", "AttributeType": "N"},
                {"AttributeName": "session_id", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "session_id-index",
                    "KeySchema": [{"AttributeName": "session_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        },
        {
            "TableName": "agenticops-alert-events",
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "id", "AttributeType": "N"},
                {"AttributeName": "source", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "source-index",
                    "KeySchema": [{"AttributeName": "source", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        },
    ]

    for table_def in tables:
        table_name = table_def["TableName"]
        try:
            dynamodb.describe_table(TableName=table_name)
            console.print(f"    [dim]{table_name} already exists, skipping.[/dim]")
            continue
        except dynamodb.exceptions.ResourceNotFoundException:
            pass

        create_kwargs = {
            "TableName": table_name,
            "KeySchema": table_def["KeySchema"],
            "AttributeDefinitions": table_def["AttributeDefinitions"],
            "BillingMode": "PAY_PER_REQUEST",
        }
        if "GlobalSecondaryIndexes" in table_def:
            create_kwargs["GlobalSecondaryIndexes"] = table_def["GlobalSecondaryIndexes"]

        dynamodb.create_table(**create_kwargs)
        console.print(f"    [green]Created {table_name}[/green]")

    for table_def in tables:
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=table_def["TableName"], WaiterConfig={"MaxAttempts": 25})


# ============================================================================
# Phase 3: AWS Account Registration (Auto-Detect + Propose)
# ============================================================================


def init_aws_accounts(env_vars: dict[str, str], yes: bool = False) -> int:
    """Register AWS accounts. Auto-detects current caller and proposes."""
    from rich.prompt import Prompt, Confirm

    region = env_vars.get("AIOPS_BEDROCK_REGION", "us-east-1")

    if yes:
        return _auto_register_caller(region)

    # Auto-detect and propose
    ctx = _detect_aws_context(region)
    if ctx["ok"]:
        console.print(f"  Detected AWS account: [cyan]{ctx['account_id']}[/cyan] ({ctx['arn']})")
        if Confirm.ask("  Register this account?", default=True):
            name = Prompt.ask("    Account name", default="default")
            _register_account({
                "name": name,
                "account_id": ctx["account_id"],
                "role_arn": "",
                "external_id": "",
                "regions": [region],
            })
            console.print(f"    [green]Registered: {name} ({ctx['account_id']})[/green]")

            # Offer cross-account
            count = 1
            while Confirm.ask("\n  Add a cross-account role?", default=False):
                details = _prompt_cross_account(region)
                if details:
                    _register_account(details)
                    console.print(f"    [green]Registered: {details['name']} ({details['account_id']})[/green]")
                    count += 1
            return count
        else:
            console.print("  [dim]Skipped account registration.[/dim]")
            return 0
    else:
        console.print(f"  [yellow]No AWS credentials detected: {ctx.get('error', 'unknown')}[/yellow]")
        if Confirm.ask("  Register an account manually?", default=False):
            details = _prompt_account_details(region)
            if details:
                _register_account(details)
                console.print(f"    [green]Registered: {details['name']} ({details['account_id']})[/green]")
                return 1
        return 0


def _prompt_cross_account(default_region: str) -> Optional[dict]:
    """Prompt for cross-account role details (minimal: name + role ARN)."""
    from rich.prompt import Prompt

    name = Prompt.ask("    Account name")
    role_arn = Prompt.ask("    Role ARN (arn:aws:iam::ACCOUNT:role/NAME)")
    if not role_arn:
        return None

    # Extract account_id from ARN
    match = re.match(r"^arn:aws:iam::(\d{12}):role/.+$", role_arn)
    account_id = match.group(1) if match else Prompt.ask("    Account ID (12 digits)")

    external_id = Prompt.ask("    External ID (optional, press Enter to skip)", default="")
    regions = Prompt.ask("    Regions", default=default_region)

    return {
        "name": name,
        "account_id": account_id,
        "role_arn": role_arn,
        "external_id": external_id,
        "regions": [r.strip() for r in regions.split(",") if r.strip()],
    }


def _prompt_account_details(default_region: str) -> Optional[dict]:
    """Prompt for manual account details."""
    from rich.prompt import Prompt

    name = Prompt.ask("    Account name", default="default")
    account_id = Prompt.ask("    Account ID (12 digits)")
    while not re.match(r"^\d{12}$", account_id):
        console.print("    [red]Account ID must be exactly 12 digits.[/red]")
        account_id = Prompt.ask("    Account ID (12 digits)")

    role_arn = Prompt.ask("    Role ARN (empty for direct credentials)", default="")
    external_id = ""
    if role_arn:
        external_id = Prompt.ask("    External ID (optional)", default="")

    regions_str = Prompt.ask("    Regions", default=default_region)

    return {
        "name": name,
        "account_id": account_id,
        "role_arn": role_arn,
        "external_id": external_id,
        "regions": [r.strip() for r in regions_str.split(",") if r.strip()],
    }


def _validate_account(
    account_id: str, role_arn: str, external_id: str, region: str
) -> tuple[bool, str]:
    """Validate AWS account access."""
    try:
        import boto3

        if role_arn:
            sts = boto3.client("sts", region_name=region)
            assume_kwargs: dict = {
                "RoleArn": role_arn,
                "RoleSessionName": "agenticops-init-validate",
            }
            if external_id:
                assume_kwargs["ExternalId"] = external_id
            resp = sts.assume_role(**assume_kwargs)
            assumed_account = resp["AssumedRoleUser"]["Arn"].split(":")[4]
            return True, f"Assumed role in account {assumed_account}"
        else:
            sts = boto3.client("sts", region_name=region)
            identity = sts.get_caller_identity()
            if identity["Account"] != account_id:
                return False, f"Caller account {identity['Account']} != {account_id}"
            return True, f"Direct credentials for account {account_id}"
    except Exception as e:
        return False, str(e)


def _register_account(details: dict) -> None:
    """Register account in DB (idempotent — skip if account_id exists)."""
    from agenticops.models import AWSAccount, get_db_session

    with get_db_session() as session:
        existing = (
            session.query(AWSAccount)
            .filter(AWSAccount.account_id == details["account_id"])
            .first()
        )
        if existing:
            console.print(f"    [dim]Account {details['account_id']} already registered, updating.[/dim]")
            existing.name = details["name"]
            existing.role_arn = details["role_arn"]
            existing.external_id = details.get("external_id", "")
            existing.regions = details["regions"]
            return

        account = AWSAccount(
            name=details["name"],
            account_id=details["account_id"],
            role_arn=details["role_arn"],
            external_id=details.get("external_id", ""),
            regions=details["regions"],
            is_active=True,
        )
        session.add(account)


def _auto_register_caller(region: str) -> int:
    """Auto-detect and register the caller's AWS account (for --yes mode)."""
    try:
        import boto3

        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        account_id = identity["Account"]

        _register_account({
            "name": "default",
            "account_id": account_id,
            "role_arn": "",
            "external_id": "",
            "regions": [region],
        })
        console.print(f"  [green]Auto-registered account {account_id} as 'default'[/green]")
        return 1
    except Exception as e:
        console.print(f"  [yellow]Auto-registration skipped: {e}[/yellow]")
        return 0


# ============================================================================
# Phase 4: Notification Channel Config
# ============================================================================


def init_notification_channels(yes: bool = False) -> int:
    """Guided notification channel setup. Returns count configured."""
    from rich.prompt import Prompt, Confirm

    if yes:
        console.print("  [dim]Skipping notification channel setup (--yes mode).[/dim]")
        console.print("  [dim]Tip: use --config setup.json to pre-configure channels.[/dim]")
        return 0

    if not Confirm.ask("  Configure a notification channel?", default=False):
        console.print("  [dim]Skipped. Configure later via /channel command or setup.json.[/dim]")
        return 0

    count = 0
    while True:
        console.print("  Channel type:")
        console.print("    [bold][1][/bold] Slack     [bold][2][/bold] Feishu    [bold][3][/bold] Email")
        console.print("    [bold][4][/bold] SNS       [bold][5][/bold] Webhook   [bold][6][/bold] Done")
        choice = Prompt.ask("  Choice", choices=["1", "2", "3", "4", "5", "6"], default="6")

        if choice == "6":
            break

        handlers = {
            "1": _init_slack_channel,
            "2": _init_feishu_channel,
            "3": _init_email_channel,
            "4": _init_sns_channel,
            "5": _init_webhook_channel,
        }
        name, channel_type, config = handlers[choice]()

        try:
            from agenticops.notify.im_config import save_channel
            save_data = {"type": channel_type, "enabled": True, **config}
            save_channel(name, save_data)
            console.print(f"    [green]Channel '{name}' saved.[/green]")
            count += 1
        except Exception as e:
            console.print(f"    [red]Failed to save channel: {e}[/red]")

    return count


def _init_slack_channel() -> tuple[str, str, dict]:
    from rich.prompt import Prompt
    name = Prompt.ask("    Channel name", default="slack-alerts")
    webhook_url = Prompt.ask("    Webhook URL")
    config: dict = {"webhook_url": webhook_url}
    return name, "slack", config


def _init_feishu_channel() -> tuple[str, str, dict]:
    from rich.prompt import Prompt
    from agenticops.config import PROJECT_ROOT

    name = Prompt.ask("    Channel name", default="feishu-alerts")
    app_name = Prompt.ask("    App name (from im-apps.yaml)", default="default")
    chat_id = Prompt.ask("    Chat ID (oc_...)")

    im_apps_path = PROJECT_ROOT / "config" / "im-apps.yaml"
    im_apps_example = PROJECT_ROOT / "config" / "im-apps.yaml.example"
    if not im_apps_path.exists() and im_apps_example.exists():
        im_apps_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(im_apps_example, im_apps_path)
        console.print("    [green]Copied im-apps.yaml template — fill in credentials.[/green]")

    return name, "feishu", {"app_name": app_name, "chat_id": chat_id}


def _init_email_channel() -> tuple[str, str, dict]:
    from rich.prompt import Prompt
    name = Prompt.ask("    Channel name", default="email-alerts")
    smtp_host = Prompt.ask("    SMTP host")
    smtp_port = Prompt.ask("    SMTP port", default="587")
    smtp_user = Prompt.ask("    SMTP username")
    smtp_password = Prompt.ask("    SMTP password", password=True)
    from_addr = Prompt.ask("    From address")
    to_addr = Prompt.ask("    To address(es)")
    return name, "email", {
        "smtp_host": smtp_host, "smtp_port": int(smtp_port),
        "smtp_user": smtp_user, "smtp_password": smtp_password,
        "from_addr": from_addr, "to_addr": to_addr,
    }


def _init_sns_channel() -> tuple[str, str, dict]:
    from rich.prompt import Prompt
    name = Prompt.ask("    Channel name", default="sns-alerts")
    topic_arn = Prompt.ask("    SNS Topic ARN")
    region = Prompt.ask("    Region", default="us-east-1")
    return name, "sns", {"topic_arn": topic_arn, "region": region}


def _init_webhook_channel() -> tuple[str, str, dict]:
    from rich.prompt import Prompt
    name = Prompt.ask("    Channel name", default="webhook-alerts")
    url = Prompt.ask("    Webhook URL")
    return name, "webhook", {"url": url, "method": "POST"}


# ============================================================================
# Phase 5: Init Wizard Orchestrator
# ============================================================================


def run_init_wizard(
    yes: bool = False,
    profile: str = "local",
    config_path: Optional[Path] = None,
) -> dict[str, str]:
    """Full init wizard, returns env_vars dict.

    Args:
        yes: Accept all defaults (non-interactive).
        profile: Deployment profile hint ('local' or 'cloud').
        config_path: Path to setup.json for zero-prompt mode.

    Returns:
        Dictionary of AIOPS_ env vars to write to .env.
    """
    from agenticops.config import PROJECT_ROOT

    # ── JSON config file path — zero prompts ──────────────────────────
    if config_path:
        console.print()
        console.print(Rule("[bold blue]AgenticOps Setup (from config)[/bold blue]"))
        console.print(f"  Loading: [cyan]{config_path}[/cyan]\n")
        env_vars = load_config_file(config_path)
        _print_config_summary(env_vars)
        return env_vars

    from rich.prompt import Confirm

    env_path = PROJECT_ROOT / ".env"
    env_vars: dict[str, str] = {}

    # ── Step 0: Welcome + Dependency Check ────────────────────────────
    console.print()
    console.print(Rule("[bold blue]AgenticOps Setup Wizard[/bold blue]"))
    console.print()
    console.print("  This wizard will guide you through essential configuration.")
    console.print("  Settings are saved to [cyan].env[/cyan] — edit anytime.")
    console.print("  [dim]Tip: use --config setup.json to skip all prompts.[/dim]\n")

    if env_path.exists():
        console.print("[yellow]Existing .env detected.[/yellow]")
        if not yes:
            reconfigure = Confirm.ask("Reconfigure? (No = skip to DB init)", default=False)
            if not reconfigure:
                return env_vars

    console.print(Rule("[bold]Step 0/5 — Dependency Check[/bold]"))
    console.print()
    results = check_dependencies(verbose=True)
    if not results.get("python"):
        console.print("[red]Python >= 3.11 is required. Aborting.[/red]")
        raise SystemExit(1)
    if not results.get("pip_packages"):
        console.print("[red]Critical packages missing and not installed. Aborting.[/red]")
        raise SystemExit(1)
    console.print()

    # ── Step 1: AWS Bedrock ───────────────────────────────────────────
    console.print(Rule("[bold]Step 1/5 — AWS Bedrock[/bold]"))
    console.print()
    _init_bedrock(env_vars, yes)

    # ── Step 2: Deployment Profile + Storage ──────────────────────────
    console.print()
    console.print(Rule("[bold]Step 2/5 — Deployment Profile[/bold]"))
    console.print()
    if profile == "cloud" and yes:
        env_vars["AIOPS_DEPLOYMENT_PROFILE"] = "cloud"
        console.print("  [dim]Cloud profile selected via --profile flag.[/dim]")
    else:
        init_deployment_profile(env_vars, yes)

    # ── Step 3: AWS Account + Pipeline ────────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 3/5 — AWS Account & Pipeline[/bold]"))
    console.print()
    init_aws_accounts(env_vars, yes)
    console.print()
    _init_pipeline(env_vars, yes)

    # ── Step 4: Notification Channels ─────────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 4/5 — Notification Channels[/bold]"))
    console.print()
    init_notification_channels(yes)

    # ── Step 5: Optional Integrations ─────────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 5/5 — Optional Integrations[/bold]"))
    console.print()
    _init_integrations(env_vars, yes)

    _print_config_summary(env_vars)
    return env_vars


def _init_bedrock(env_vars: dict[str, str], yes: bool) -> None:
    """Step 1: Bedrock model configuration — auto-detect region from credentials."""
    from rich.prompt import Prompt, Confirm

    # Try to auto-detect region from AWS config
    default_region = "us-east-1"
    try:
        import boto3
        session = boto3.Session()
        detected = session.region_name
        if detected:
            default_region = detected
    except Exception:
        pass

    if yes:
        region = default_region
    else:
        region = Prompt.ask("Bedrock region", default=default_region)
        while not re.match(r"^[a-z]{2}-[a-z]+-\d+$", region):
            console.print("[red]Invalid region format (e.g., us-east-1)[/red]")
            region = Prompt.ask("Bedrock region", default=default_region)
    env_vars["AIOPS_BEDROCK_REGION"] = region

    if yes:
        choice = "2"
    else:
        console.print("\n  Select primary Bedrock model:")
        console.print("    [bold][1][/bold] Opus 4.6    (strongest, higher cost)")
        console.print("    [bold][2][/bold] Sonnet 4.6  (balanced)  [dim]<- default[/dim]")
        console.print("    [bold][3][/bold] Haiku 4.5   (fastest, lowest cost)")
        console.print("    [bold][4][/bold] Custom model ID")
        choice = Prompt.ask("\n  Choice", choices=["1", "2", "3", "4"], default="2")

    if choice == "4":
        model_id = Prompt.ask("Custom model ID")
        env_vars["AIOPS_BEDROCK_MODEL_ID"] = model_id
        env_vars["AIOPS_BEDROCK_MODEL_ID_CHEAP"] = _HAIKU_ID
        env_vars["AIOPS_BEDROCK_MODEL_ID_STRONG"] = _OPUS_ID
    else:
        models = {"1": _OPUS_ID, "2": _SONNET_ID, "3": _HAIKU_ID}
        env_vars["AIOPS_BEDROCK_MODEL_ID"] = models[choice]
        if choice == "3":
            env_vars["AIOPS_BEDROCK_MODEL_ID_CHEAP"] = _HAIKU_ID
            env_vars["AIOPS_BEDROCK_MODEL_ID_STRONG"] = _SONNET_ID
        else:
            env_vars["AIOPS_BEDROCK_MODEL_ID_CHEAP"] = _HAIKU_ID
            env_vars["AIOPS_BEDROCK_MODEL_ID_STRONG"] = _OPUS_ID

    console.print(f"\n  [green]Primary:[/green] {env_vars['AIOPS_BEDROCK_MODEL_ID']}")
    console.print(f"  [green]Economy:[/green] {env_vars['AIOPS_BEDROCK_MODEL_ID_CHEAP']}")
    console.print(f"  [green]Strong:[/green]  {env_vars['AIOPS_BEDROCK_MODEL_ID_STRONG']}")


def _init_pipeline(env_vars: dict[str, str], yes: bool) -> None:
    """Pipeline behavior — defaults are good, just confirm."""
    from rich.prompt import Confirm

    if yes:
        env_vars["AIOPS_AUTO_FIX_ENABLED"] = "true"
        env_vars["AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1"] = "true"
        env_vars["AIOPS_NOTIFICATIONS_ENABLED"] = "true"
        console.print("  [dim]Pipeline: auto-fix=true, auto-approve L0/L1=true, notifications=true[/dim]")
        return

    console.print("  Pipeline defaults: auto-fix [green]ON[/green], auto-approve L0/L1 [green]ON[/green], notifications [green]ON[/green]")
    if Confirm.ask("  Accept pipeline defaults?", default=True):
        env_vars["AIOPS_AUTO_FIX_ENABLED"] = "true"
        env_vars["AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1"] = "true"
        env_vars["AIOPS_NOTIFICATIONS_ENABLED"] = "true"
    else:
        auto_fix = Confirm.ask("  Enable auto-fix pipeline?", default=True)
        env_vars["AIOPS_AUTO_FIX_ENABLED"] = str(auto_fix).lower()
        auto_approve = Confirm.ask("  Auto-approve L0/L1 fix plans?", default=True)
        env_vars["AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1"] = str(auto_approve).lower()
        notifications = Confirm.ask("  Enable auto-notifications?", default=True)
        env_vars["AIOPS_NOTIFICATIONS_ENABLED"] = str(notifications).lower()


def _init_integrations(env_vars: dict[str, str], yes: bool) -> None:
    """Optional integrations (IM, Datadog) — skip by default."""
    from rich.prompt import Prompt, Confirm
    from agenticops.config import PROJECT_ROOT

    if yes:
        console.print("  [dim]Skipping optional integrations.[/dim]")
        return

    if Confirm.ask("  Configure Datadog integration?", default=False):
        dd_api_key = Prompt.ask("    Datadog API key")
        dd_app_key = Prompt.ask("    Datadog Application key")
        dd_site = Prompt.ask("    Datadog site", default="datadoghq.com")
        env_vars["AIOPS_MONITORING_PROVIDERS"] = "datadog"
        env_vars["AIOPS_DATADOG_API_KEY"] = dd_api_key
        env_vars["AIOPS_DATADOG_APP_KEY"] = dd_app_key
        env_vars["AIOPS_DATADOG_SITE"] = dd_site
        console.print("    [green]Datadog configured.[/green]")
    else:
        console.print("  [dim]No additional integrations configured.[/dim]")


def _print_config_summary(env_vars: dict[str, str]) -> None:
    """Print a summary table of configured env vars."""
    if not env_vars:
        return
    console.print()
    console.print(Rule("[bold green]Configuration Summary[/bold green]"))
    summary = Table(show_header=True, box=SIMPLE)
    summary.add_column("Setting", style="cyan")
    summary.add_column("Value")
    sensitive = ("secret", "password", "token", "api_key", "app_key")
    for key, value in env_vars.items():
        display = "****" if any(s in key.lower() for s in sensitive) else value
        summary.add_row(key, display)
    console.print(summary)
