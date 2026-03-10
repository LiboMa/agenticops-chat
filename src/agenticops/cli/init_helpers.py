"""Init and quickstart helper functions for AgenticOps CLI.

Extracted from main.py to keep it lean. Contains:
- Dependency checking
- Deployment profile wizard (local/cloud)
- AWS account registration
- Notification channel guided config
- run_init_wizard() orchestrator
"""

import importlib
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
    """Check all dependencies, render Rich table, return pass/fail dict.

    Args:
        verbose: If True, print the results table.

    Returns:
        Dict mapping check names to pass/fail booleans.
    """
    results: dict[str, bool] = {}

    # Python version
    py_ok, py_ver = _check_python_version()
    results["python"] = py_ok

    # Pip packages
    pkgs_ok, missing = _check_pip_packages()
    results["pip_packages"] = pkgs_ok

    # Optional binaries
    for binary in OPTIONAL_BINARIES:
        results[binary] = _check_binary(binary)

    # AWS credentials
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

        table.add_row(
            "Python >= 3.11",
            _icon(py_ok),
            f"v{py_ver}",
        )
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

    # Offer to install missing packages
    if missing and verbose:
        if _offer_install_missing(missing):
            results["pip_packages"] = True

    return results


# ============================================================================
# Phase 2: Deployment Profile
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

    # Cloud profile
    env_vars["AIOPS_DEPLOYMENT_PROFILE"] = "cloud"

    # Sub-step: Database backend
    _init_cloud_database(env_vars)

    # Sub-step: Vector storage
    _init_cloud_vector_storage(env_vars)

    # Sub-step: File storage (S3 for reports + KB)
    _init_cloud_file_storage(env_vars)

    console.print("  [green]Cloud profile configured.[/green]")
    return "cloud"


def _init_cloud_database(env_vars: dict[str, str]) -> None:
    """Cloud database sub-choice: SQLite-on-EFS, RDS, or DynamoDB."""
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


def _init_cloud_vector_storage(env_vars: dict[str, str]) -> None:
    """Cloud vector storage sub-choice: RDS pgvector or S3."""
    from rich.prompt import Prompt

    console.print("\n  Vector storage backend:")
    console.print("    [bold][1][/bold] RDS PostgreSQL (pgvector)  [dim]<- recommended, native cosine search[/dim]")
    console.print("    [bold][2][/bold] S3  [dim](numpy blobs, zero DB dependency)[/dim]")
    v_choice = Prompt.ask("  Choice", choices=["1", "2"], default="1")

    if v_choice == "1":
        env_vars["AIOPS_VECTOR_STORAGE"] = "rds"
        # Reuse DB URL if already set, or prompt
        rds_url = env_vars.get("AIOPS_DATABASE_URL", "")
        if rds_url.startswith("postgresql"):
            env_vars["AIOPS_VECTOR_RDS_URL"] = rds_url
            console.print(f"    [green]Using same RDS instance for vectors.[/green]")
            if _test_pgvector(rds_url):
                console.print("    [green]pgvector extension verified.[/green]")
            else:
                console.print("    [yellow]pgvector check failed — will attempt CREATE EXTENSION at runtime.[/yellow]")
        else:
            url = Prompt.ask("    PostgreSQL URL for vectors")
            env_vars["AIOPS_VECTOR_RDS_URL"] = url

    elif v_choice == "2":
        env_vars["AIOPS_VECTOR_STORAGE"] = "s3"
        bucket = Prompt.ask("    S3 bucket for vectors")
        region = Prompt.ask("    S3 region", default="us-east-1")
        env_vars["AIOPS_VECTOR_S3_BUCKET"] = bucket
        env_vars["AIOPS_VECTOR_S3_REGION"] = region
        console.print(f"    [green]S3 vector storage: s3://{bucket}/vectors/[/green]")


def _init_cloud_file_storage(env_vars: dict[str, str]) -> None:
    """Cloud file storage: S3 bucket for reports + KB files."""
    from rich.prompt import Prompt

    console.print("\n  File storage (reports + knowledge base):")
    bucket = Prompt.ask("    S3 bucket name")
    region = Prompt.ask("    S3 region", default="us-east-1")

    # Create bucket if needed
    _create_s3_bucket_if_needed(bucket, region)

    # Reports
    env_vars["AIOPS_REPORT_STORAGE"] = "s3"
    env_vars["AIOPS_REPORT_S3_BUCKET"] = bucket
    env_vars["AIOPS_REPORT_S3_PREFIX"] = "reports/"
    env_vars["AIOPS_REPORT_S3_REGION"] = region

    # KB files
    env_vars["AIOPS_KB_STORAGE"] = "s3"
    env_vars["AIOPS_KB_S3_BUCKET"] = bucket
    env_vars["AIOPS_KB_S3_PREFIX"] = "knowledge_base/"
    env_vars["AIOPS_KB_S3_REGION"] = region

    # Also use same bucket for vectors if S3 vector chosen
    if env_vars.get("AIOPS_VECTOR_STORAGE") == "s3":
        env_vars["AIOPS_VECTOR_S3_BUCKET"] = bucket
        env_vars["AIOPS_VECTOR_S3_REGION"] = region

    console.print(f"    [green]S3 file storage: s3://{bucket}/ (reports/ + knowledge_base/)[/green]")


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
            # Check if table already exists
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

    # Wait for tables to be active
    for table_def in tables:
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=table_def["TableName"], WaiterConfig={"MaxAttempts": 25})


# ============================================================================
# Phase 3: AWS Account Registration
# ============================================================================


def init_aws_accounts(env_vars: dict[str, str], yes: bool = False) -> int:
    """Register AWS accounts. Returns count registered."""
    from rich.prompt import Prompt, Confirm

    region = env_vars.get("AIOPS_BEDROCK_REGION", "us-east-1")

    if yes:
        return _auto_register_caller(region)

    console.print("  Register AWS accounts for scanning and monitoring.\n")

    count = 0
    while True:
        if count > 0:
            if not Confirm.ask("  Add another account?", default=False):
                break

        details = _prompt_account_details(region)
        if details is None:
            break

        ok, msg = _validate_account(
            details["account_id"],
            details["role_arn"],
            details.get("external_id", ""),
            details["regions"][0] if details["regions"] else region,
        )
        if ok:
            console.print(f"    [green]Validated: {msg}[/green]")
        else:
            console.print(f"    [yellow]Validation failed: {msg}[/yellow]")
            if not Confirm.ask("    Save anyway?", default=True):
                continue

        _register_account(details)
        console.print(f"    [green]Registered: {details['name']} ({details['account_id']})[/green]")
        count += 1

    return count


def _prompt_account_details(default_region: str) -> Optional[dict]:
    """Prompt for account details. Returns dict or None to skip."""
    from rich.prompt import Prompt, Confirm

    if not Confirm.ask("  Register an AWS account?", default=True):
        return None

    name = Prompt.ask("    Account name", default="default")
    account_id = Prompt.ask("    Account ID (12 digits)")
    while not re.match(r"^\d{12}$", account_id):
        console.print("    [red]Account ID must be exactly 12 digits.[/red]")
        account_id = Prompt.ask("    Account ID (12 digits)")

    role_arn = Prompt.ask("    Role ARN (empty for direct credentials)", default="")
    if role_arn and not re.match(r"^arn:aws:iam::\d{12}:role/.+$", role_arn):
        console.print("    [yellow]Warning: Role ARN format looks unusual.[/yellow]")

    external_id = ""
    if role_arn:
        external_id = Prompt.ask("    External ID (optional)", default="")

    regions_str = Prompt.ask("    Regions (comma-separated)", default=default_region)
    regions = [r.strip() for r in regions_str.split(",") if r.strip()]

    return {
        "name": name,
        "account_id": account_id,
        "role_arn": role_arn,
        "external_id": external_id,
        "regions": regions,
    }


def _validate_account(
    account_id: str, role_arn: str, external_id: str, region: str
) -> tuple[bool, str]:
    """Validate AWS account access. Returns (ok, message)."""
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
        return 0

    console.print("  Configure notification channels for alerts and reports.\n")

    count = 0
    while True:
        if count > 0:
            if not Confirm.ask("\n  Add another channel?", default=False):
                break

        console.print("  Channel type:")
        console.print("    [bold][1][/bold] Slack")
        console.print("    [bold][2][/bold] Feishu")
        console.print("    [bold][3][/bold] Email (SMTP)")
        console.print("    [bold][4][/bold] SNS")
        console.print("    [bold][5][/bold] Webhook")
        console.print("    [bold][6][/bold] Skip")
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

        # Severity filter
        severity_filter = _prompt_severity_filter()

        # Save channel
        try:
            from agenticops.notify.im_config import save_channel

            save_data = {"type": channel_type, "enabled": True, **config}
            if severity_filter:
                save_data["severity_filter"] = severity_filter
            save_channel(name, save_data)
            console.print(f"    [green]Channel '{name}' saved to channels.yaml[/green]")
            count += 1
        except Exception as e:
            console.print(f"    [red]Failed to save channel: {e}[/red]")

    return count


def _init_slack_channel() -> tuple[str, str, dict]:
    """Collect Slack channel config."""
    from rich.prompt import Prompt

    name = Prompt.ask("    Channel name", default="slack-alerts")
    webhook_url = Prompt.ask("    Webhook URL")
    channel = Prompt.ask("    Slack channel (optional)", default="")
    config: dict = {"webhook_url": webhook_url}
    if channel:
        config["channel"] = channel
    return name, "slack", config


def _init_feishu_channel() -> tuple[str, str, dict]:
    """Collect Feishu channel config."""
    from rich.prompt import Prompt

    name = Prompt.ask("    Channel name", default="feishu-alerts")
    app_name = Prompt.ask("    App name (from im-apps.yaml)", default="default")
    chat_id = Prompt.ask("    Chat ID (oc_...)")

    # Offer to copy im-apps template
    from agenticops.config import PROJECT_ROOT

    im_apps_path = PROJECT_ROOT / "config" / "im-apps.yaml"
    im_apps_example = PROJECT_ROOT / "config" / "im-apps.yaml.example"
    if not im_apps_path.exists() and im_apps_example.exists():
        import shutil

        im_apps_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(im_apps_example, im_apps_path)
        console.print("    [green]Copied im-apps.yaml template — fill in your Feishu credentials.[/green]")

    return name, "feishu", {"app_name": app_name, "chat_id": chat_id}


def _init_email_channel() -> tuple[str, str, dict]:
    """Collect Email/SMTP channel config."""
    from rich.prompt import Prompt

    name = Prompt.ask("    Channel name", default="email-alerts")
    smtp_host = Prompt.ask("    SMTP host")
    smtp_port = Prompt.ask("    SMTP port", default="587")
    smtp_user = Prompt.ask("    SMTP username")
    smtp_password = Prompt.ask("    SMTP password (input hidden)", password=True)
    from_addr = Prompt.ask("    From address")
    to_addr = Prompt.ask("    To address(es) (comma-separated)")
    return name, "email", {
        "smtp_host": smtp_host,
        "smtp_port": int(smtp_port),
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
        "from_addr": from_addr,
        "to_addr": to_addr,
    }


def _init_sns_channel() -> tuple[str, str, dict]:
    """Collect SNS channel config."""
    from rich.prompt import Prompt

    name = Prompt.ask("    Channel name", default="sns-alerts")
    topic_arn = Prompt.ask("    SNS Topic ARN")
    region = Prompt.ask("    Region", default="us-east-1")
    return name, "sns", {"topic_arn": topic_arn, "region": region}


def _init_webhook_channel() -> tuple[str, str, dict]:
    """Collect Webhook channel config."""
    from rich.prompt import Prompt

    name = Prompt.ask("    Channel name", default="webhook-alerts")
    url = Prompt.ask("    Webhook URL")
    method = Prompt.ask("    HTTP method", choices=["POST", "PUT"], default="POST")
    return name, "webhook", {"url": url, "method": method}


def _prompt_severity_filter() -> Optional[list[str]]:
    """Prompt for severity filter. Returns list or None for all."""
    from rich.prompt import Prompt

    choice = Prompt.ask(
        "    Severity filter",
        choices=["all", "critical,high", "custom"],
        default="all",
    )
    if choice == "all":
        return None
    if choice == "critical,high":
        return ["critical", "high"]
    # custom
    custom = Prompt.ask("    Severities (comma-separated)")
    return [s.strip() for s in custom.split(",") if s.strip()]


# ============================================================================
# Phase 5: Init Wizard Orchestrator
# ============================================================================


def run_init_wizard(yes: bool = False, profile: str = "local") -> dict[str, str]:
    """Full init wizard, returns env_vars dict.

    Args:
        yes: Accept all defaults (non-interactive).
        profile: Deployment profile hint ('local' or 'cloud').

    Returns:
        Dictionary of AIOPS_ env vars to write to .env.
    """
    from rich.prompt import Prompt, Confirm
    from agenticops.config import PROJECT_ROOT

    env_path = PROJECT_ROOT / ".env"
    env_vars: dict[str, str] = {}

    # ── Step 0: Welcome + Dependency Check ────────────────────────────
    console.print()
    console.print(Rule("[bold blue]AgenticOps Setup Wizard[/bold blue]"))
    console.print()
    console.print("  This wizard will guide you through essential configuration.")
    console.print("  Settings are saved to [cyan].env[/cyan] — edit anytime.\n")

    if env_path.exists():
        console.print("[yellow]Existing .env detected.[/yellow]")
        if not yes:
            reconfigure = Confirm.ask("Reconfigure? (No = skip to DB init)", default=False)
            if not reconfigure:
                return env_vars

    console.print(Rule("[bold]Step 0/7 — Dependency Check[/bold]"))
    console.print()
    results = check_dependencies(verbose=True)
    if not results.get("python"):
        console.print("[red]Python >= 3.11 is required. Aborting.[/red]")
        raise SystemExit(1)
    if not results.get("pip_packages"):
        console.print("[red]Critical packages missing and not installed. Aborting.[/red]")
        raise SystemExit(1)
    console.print()

    # ── Step 1: AWS Bedrock (Essential) ───────────────────────────────
    console.print(Rule("[bold]Step 1/7 — AWS Bedrock[/bold]"))
    console.print()
    _init_bedrock(env_vars, yes)

    # ── Step 2: Deployment Profile ────────────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 2/7 — Deployment Profile[/bold]"))
    console.print()
    if profile == "cloud" and yes:
        env_vars["AIOPS_DEPLOYMENT_PROFILE"] = "cloud"
        console.print("  [dim]Cloud profile selected via --profile flag.[/dim]")
    else:
        init_deployment_profile(env_vars, yes)

    # ── Step 3: AWS Account Registration ──────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 3/7 — AWS Accounts[/bold]"))
    console.print()
    init_aws_accounts(env_vars, yes)

    # ── Step 4: Pipeline Behavior ─────────────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 4/7 — Pipeline Behavior[/bold]"))
    console.print()
    _init_pipeline(env_vars, yes)

    # ── Step 5: Report Storage ────────────────────────────────────────
    # Only if not already configured by cloud profile
    if "AIOPS_REPORT_STORAGE" not in env_vars:
        console.print()
        console.print(Rule("[bold]Step 5/7 — Report Storage[/bold]"))
        console.print()
        _init_report_storage_step(env_vars, yes)

    # ── Step 6: Notification Channels ─────────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 6/7 — Notification Channels[/bold]"))
    console.print()
    init_notification_channels(yes)

    # ── Step 7: Optional Integrations ─────────────────────────────────
    console.print()
    console.print(Rule("[bold]Step 7/7 — Optional Integrations[/bold]"))
    console.print()
    _init_integrations(env_vars, yes)

    return env_vars


def _init_bedrock(env_vars: dict[str, str], yes: bool) -> None:
    """Step 1: Bedrock model configuration."""
    from rich.prompt import Prompt, Confirm

    haiku_id = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    sonnet_id = "global.anthropic.claude-sonnet-4-6-v1"
    opus_id = "global.anthropic.claude-opus-4-6-v1"

    # Region
    default_region = "us-east-1"
    if yes:
        region = default_region
    else:
        region = Prompt.ask("Bedrock region", default=default_region)
        while not re.match(r"^[a-z]{2}-[a-z]+-\d+$", region):
            console.print("[red]Invalid region format (e.g., us-east-1)[/red]")
            region = Prompt.ask("Bedrock region", default=default_region)
    env_vars["AIOPS_BEDROCK_REGION"] = region

    # Model picker
    models = {
        "1": ("Claude Opus 4.6", opus_id),
        "2": ("Claude Sonnet 4.6", sonnet_id),
        "3": ("Claude Haiku 4.5", haiku_id),
    }

    if yes:
        choice = "2"
    else:
        console.print("\n  Select primary Bedrock model:")
        console.print("    [bold][1][/bold] Claude Opus 4.6    (strongest reasoning, higher cost)")
        console.print("    [bold][2][/bold] Claude Sonnet 4.6  (balanced performance/cost)  [dim]<- default[/dim]")
        console.print("    [bold][3][/bold] Claude Haiku 4.5   (fastest, lowest cost)")
        console.print("    [bold][4][/bold] Custom model ID")
        choice = Prompt.ask("\n  Choice", choices=["1", "2", "3", "4"], default="2")

    if choice == "4":
        model_id = Prompt.ask("Custom model ID")
        env_vars["AIOPS_BEDROCK_MODEL_ID"] = model_id
        env_vars["AIOPS_BEDROCK_MODEL_ID_CHEAP"] = haiku_id
        env_vars["AIOPS_BEDROCK_MODEL_ID_STRONG"] = opus_id
    else:
        _, model_id = models[choice]
        env_vars["AIOPS_BEDROCK_MODEL_ID"] = model_id
        if choice == "3":  # Haiku as primary
            env_vars["AIOPS_BEDROCK_MODEL_ID_CHEAP"] = haiku_id
            env_vars["AIOPS_BEDROCK_MODEL_ID_STRONG"] = sonnet_id
        else:
            env_vars["AIOPS_BEDROCK_MODEL_ID_CHEAP"] = haiku_id
            env_vars["AIOPS_BEDROCK_MODEL_ID_STRONG"] = opus_id

    console.print(f"\n  [green]Primary:[/green] {env_vars['AIOPS_BEDROCK_MODEL_ID']}")
    console.print(f"  [green]Economy:[/green] {env_vars['AIOPS_BEDROCK_MODEL_ID_CHEAP']}")
    console.print(f"  [green]Strong:[/green]  {env_vars['AIOPS_BEDROCK_MODEL_ID_STRONG']}")

    # Optional AWS connectivity test
    if not yes:
        if Confirm.ask("\n  Test AWS connectivity?", default=False):
            ok, info = _check_aws_credentials(region)
            if ok:
                console.print(f"  [green]OK[/green] — Account: {info}")
            else:
                console.print(f"  [yellow]AWS check failed: {info}[/yellow]")
                console.print("  [dim]You can fix credentials later.[/dim]")


def _init_pipeline(env_vars: dict[str, str], yes: bool) -> None:
    """Step 4: Pipeline behavior configuration."""
    from rich.prompt import Confirm

    if yes:
        env_vars["AIOPS_AUTO_FIX_ENABLED"] = "true"
        env_vars["AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1"] = "true"
        env_vars["AIOPS_NOTIFICATIONS_ENABLED"] = "true"
        console.print("  [dim]Using defaults: auto-fix=true, auto-approve L0/L1=true, notifications=true[/dim]")
    else:
        skip = Confirm.ask("  Skip pipeline config? (use defaults)", default=False)
        if skip:
            env_vars["AIOPS_AUTO_FIX_ENABLED"] = "true"
            env_vars["AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1"] = "true"
            env_vars["AIOPS_NOTIFICATIONS_ENABLED"] = "true"
            console.print("  [dim]Using defaults.[/dim]")
        else:
            auto_fix = Confirm.ask("  Enable auto-fix pipeline (RCA -> SRE -> Approve -> Execute)?", default=True)
            env_vars["AIOPS_AUTO_FIX_ENABLED"] = str(auto_fix).lower()

            auto_approve = Confirm.ask("  Auto-approve L0/L1 fix plans?", default=True)
            env_vars["AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1"] = str(auto_approve).lower()

            notifications = Confirm.ask("  Enable auto-notifications on pipeline events?", default=True)
            env_vars["AIOPS_NOTIFICATIONS_ENABLED"] = str(notifications).lower()


def _init_report_storage_step(env_vars: dict[str, str], yes: bool) -> None:
    """Step 5: Report storage configuration."""
    from rich.prompt import Prompt, Confirm
    from agenticops.config import settings

    if yes:
        env_vars["AIOPS_REPORT_STORAGE"] = "local"
        console.print(f"  [dim]Using default: local storage ({settings.reports_dir})[/dim]")
    else:
        skip = Confirm.ask("  Skip report storage config? (use local)", default=True)
        if skip:
            env_vars["AIOPS_REPORT_STORAGE"] = "local"
        else:
            console.print("  Reports can be stored locally or on S3.")
            console.print("  S3 is recommended for production.\n")
            choice = Prompt.ask("  Storage backend", choices=["local", "s3"], default="local")
            if choice == "s3":
                bucket = Prompt.ask("  S3 bucket name")
                prefix = Prompt.ask("  S3 key prefix", default="reports/")
                region = Prompt.ask("  S3 region", default="us-east-1")
                env_vars["AIOPS_REPORT_STORAGE"] = "s3"
                env_vars["AIOPS_REPORT_S3_BUCKET"] = bucket
                env_vars["AIOPS_REPORT_S3_PREFIX"] = prefix
                env_vars["AIOPS_REPORT_S3_REGION"] = region
                console.print(f"  [green]S3 storage configured: s3://{bucket}/{prefix}[/green]")
            else:
                env_vars["AIOPS_REPORT_STORAGE"] = "local"
                console.print(f"  [green]Local storage: {settings.reports_dir}[/green]")


def _init_integrations(env_vars: dict[str, str], yes: bool) -> None:
    """Step 7: Optional integrations (IM, Datadog)."""
    from rich.prompt import Prompt, Confirm
    from agenticops.config import PROJECT_ROOT

    if yes:
        console.print("  [dim]Skipping optional integrations.[/dim]")
        return

    # IM Integration
    if Confirm.ask("  Configure an IM platform (Feishu/Slack/DingTalk/WeCom)?", default=False):
        im_choice = Prompt.ask(
            "    Platform",
            choices=["feishu", "slack", "dingtalk", "wecom"],
            default="feishu",
        )
        src = PROJECT_ROOT / "config" / "im-apps.yaml.example"
        dest = PROJECT_ROOT / "config" / "im-apps.yaml"
        if not dest.exists() and src.exists():
            import shutil

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        console.print(f"\n    [green]Edit[/green] config/im-apps.yaml with your {im_choice} credentials.")
        docs = {
            "feishu": "https://open.feishu.cn/app",
            "slack": "https://api.slack.com/apps",
            "dingtalk": "https://open-dev.dingtalk.com",
            "wecom": "https://work.weixin.qq.com/wework_admin",
        }
        console.print(f"    [dim]Docs: {docs[im_choice]}[/dim]")

    # Datadog
    if Confirm.ask("  Configure Datadog integration?", default=False):
        dd_api_key = Prompt.ask("    Datadog API key")
        dd_app_key = Prompt.ask("    Datadog Application key")
        dd_site = Prompt.ask("    Datadog site", default="datadoghq.com")
        env_vars["AIOPS_MONITORING_PROVIDERS"] = "datadog"
        env_vars["AIOPS_DATADOG_API_KEY"] = dd_api_key
        env_vars["AIOPS_DATADOG_APP_KEY"] = dd_app_key
        env_vars["AIOPS_DATADOG_SITE"] = dd_site
        console.print("    [green]Datadog configured.[/green]")
