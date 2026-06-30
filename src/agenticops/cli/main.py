"""CLI Main - kubectl-style Command Line Interface for AgenticOps."""

import json
import logging
import os
import sys
import time
import threading
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from contextlib import contextmanager
from enum import Enum
import csv

import typer
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.tree import Tree
from rich.box import ROUNDED, SIMPLE, MINIMAL, DOUBLE, ASCII
from rich.text import Text
from rich.columns import Columns
from rich.live import Live
from rich.spinner import Spinner
from rich.status import Status
from rich.rule import Rule

from agenticops import __version__
from agenticops.config import settings
from agenticops.models import (
    CloudAccount,
    CloudResource,
    HealthIssue,
    FixPlan,
    FixExecution,
    Report,
    init_db,
    get_session,
    get_db_session,
)

# Import from new modular CLI components
from agenticops.cli.formatters import (
    TABLE_STYLES,
    get_table_style,
    create_table,
    render_markdown,
    render_json,
    render_yaml_style,
    render_tree,
    format_duration,
    format_bytes,
    format_number,
)
from agenticops.cli.display import (
    ThinkingState,
    ThinkingDisplay,
    TokenUsage,
    StatusBar,
)
from agenticops.cli.context import ChatContext

# Initialize app and console with better terminal support
app = typer.Typer(
    name="aiops",
    help="AgenticAIOps - kubectl-style Cloud Observability CLI",
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",  # Enable rich markup in help
)

# Console with pager support for long output
console = Console(
    highlight=True,
    tab_size=2,
    force_terminal=True if os.environ.get("FORCE_COLOR") else None,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Output Formatters - kubectl/gh style
# ============================================================================

# Table box styles
TABLE_STYLES = {
    "default": ROUNDED,
    "simple": SIMPLE,
    "minimal": MINIMAL,
    "double": DOUBLE,
    "ascii": ASCII,
}


def get_table_style():
    """Get table style from environment or default."""
    style_name = os.environ.get("AIOPS_TABLE_STYLE", "default")
    return TABLE_STYLES.get(style_name, ROUNDED)


def create_table(
    title: str = None,
    columns: List[Dict] = None,
    show_header: bool = True,
    show_lines: bool = False,
    expand: bool = False,
    box_style: str = None,
) -> Table:
    """Create a styled table like kubectl/gh output."""
    box = TABLE_STYLES.get(box_style) if box_style else get_table_style()

    table = Table(
        title=title,
        show_header=show_header,
        header_style="bold cyan",
        show_lines=show_lines,
        expand=expand,
        box=box,
        border_style="dim",
        row_styles=["", "dim"],  # Alternating row styles
        padding=(0, 1),
    )

    if columns:
        for col in columns:
            table.add_column(
                col.get("name", ""),
                style=col.get("style"),
                justify=col.get("justify", "left"),
                no_wrap=col.get("no_wrap", False),
                overflow="ellipsis",
            )

    return table


def render_markdown(content: str, title: str = None):
    """Render markdown content with optional title."""
    md = Markdown(content)
    if title:
        console.print(Panel(md, title=title, border_style="blue"))
    else:
        console.print(md)


def render_json(data: Any, title: str = None):
    """Render JSON with syntax highlighting."""
    json_str = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
    if title:
        console.print(Panel(syntax, title=title, border_style="green"))
    else:
        console.print(syntax)


def render_yaml_style(data: Dict, indent: int = 0):
    """Render dict as YAML-like output (kubectl style)."""
    prefix = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            console.print(f"{prefix}[cyan]{key}:[/cyan]")
            render_yaml_style(value, indent + 1)
        elif isinstance(value, list):
            console.print(f"{prefix}[cyan]{key}:[/cyan]")
            for item in value:
                if isinstance(item, dict):
                    console.print(f"{prefix}  -")
                    render_yaml_style(item, indent + 2)
                else:
                    console.print(f"{prefix}  - {item}")
        else:
            display_value = value if value is not None else "[dim]-[/dim]"
            console.print(f"{prefix}[cyan]{key}:[/cyan] {display_value}")


def render_tree(title: str, items: List[Dict], key_field: str = "name", children_field: str = None):
    """Render hierarchical data as a tree."""
    tree = Tree(f"[bold]{title}[/bold]")

    for item in items:
        name = item.get(key_field, "unknown")
        node = tree.add(f"[green]{name}[/green]")

        for k, v in item.items():
            if k != key_field and k != children_field:
                if v is not None:
                    node.add(f"[dim]{k}:[/dim] {v}")

        if children_field and children_field in item:
            for child in item[children_field]:
                child_node = node.add(f"[yellow]{child.get(key_field, 'item')}[/yellow]")
                for ck, cv in child.items():
                    if ck != key_field:
                        child_node.add(f"[dim]{ck}:[/dim] {cv}")

    console.print(tree)


def render_status_line(items: List[tuple], separator: str = " │ "):
    """Render a status line like gh cli."""
    parts = []
    for label, value, style in items:
        parts.append(f"[dim]{label}:[/dim] [{style}]{value}[/{style}]")
    console.print(separator.join(parts))


def pager_print(content: str):
    """Print long content directly to terminal (scrollback-friendly)."""
    console.print(content)


# ============================================================================
# Subcommand Groups (kubectl-style)
# ============================================================================

get_app = typer.Typer(help="Display one or many resources")
describe_app = typer.Typer(help="Show details of a specific resource")
create_app = typer.Typer(help="Create a resource")
delete_app = typer.Typer(help="Delete resources")
update_app = typer.Typer(help="Update a resource")
run_app = typer.Typer(help="Run operations (scan, detect, analyze)")
logs_app = typer.Typer(help="View logs and audit trail")
service_app = typer.Typer(help="Manage background services (web dashboard + IM WebSocket)")

app.add_typer(get_app, name="get")
app.add_typer(describe_app, name="describe")
app.add_typer(create_app, name="create")
app.add_typer(delete_app, name="delete")
app.add_typer(update_app, name="update")
app.add_typer(run_app, name="run")
app.add_typer(logs_app, name="logs")
app.add_typer(service_app, name="service")


# ============================================================================
# Helper Functions
# ============================================================================


def get_accounts(name: str = None) -> list:
    """Get account(s) by name, or all enabled accounts."""
    session = get_session()
    try:
        if name:
            acct = session.query(CloudAccount).filter_by(name=name).first()
            return [acct] if acct else []
        return session.query(CloudAccount).filter_by(is_enabled=True).all()
    finally:
        session.close()


def get_account(name: str = None) -> Optional[CloudAccount]:
    """Get single account by name, or first enabled (backward compat)."""
    accounts = get_accounts(name)
    return accounts[0] if accounts else None


def output_table(data: list, columns: list, title: str = None):
    """Output data as a table (kubectl style)."""
    table = create_table(title=title, columns=columns)

    for row in data:
        table.add_row(*[str(v) if v is not None else "-" for v in row])

    console.print(table)


def output_json(data, title: str = None):
    """Output data as JSON with syntax highlighting."""
    render_json(data, title)


def output_yaml(data):
    """Output data as YAML-like format (kubectl describe style)."""
    render_yaml_style(data)


def output_markdown_table(headers: List[str], rows: List[List[str]], title: str = None):
    """Output data as markdown table."""
    md_lines = []
    if title:
        md_lines.append(f"## {title}\n")

    # Header
    md_lines.append("| " + " | ".join(headers) + " |")
    md_lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    # Rows
    for row in rows:
        md_lines.append("| " + " | ".join(str(c) for c in row) + " |")

    render_markdown("\n".join(md_lines))


# ============================================================================
# GET Commands - List Resources
# ============================================================================


@get_app.command("accounts")
def get_accounts(
    output: str = typer.Option("table", "-o", "--output", help="Output format: table, json, wide"),
    all_accounts: bool = typer.Option(False, "-A", "--all", help="Show inactive accounts too"),
):
    """List AWS accounts."""
    init_db()
    session = get_session()

    try:
        query = session.query(CloudAccount)
        if not all_accounts:
            query = query.filter_by(is_enabled=True)
        accounts = query.all()

        if not accounts:
            console.print("[yellow]No accounts found.[/yellow]")
            return

        if output == "json":
            data = [{
                "name": a.name,
                "provider": a.provider,
                "account_id": (a.credentials or {}).get("account_id", ""),
                "regions": a.regions,
                "is_enabled": a.is_enabled,
                "last_scanned": a.last_scanned_at.isoformat() if a.last_scanned_at else None,
            } for a in accounts]
            output_json(data)
        elif output == "wide":
            output_table(
                [(a.name, a.provider, (a.credentials or {}).get("account_id", ""),
                  (a.credentials or {}).get("role_arn", ""), ",".join(a.regions),
                  "Active" if a.is_enabled else "Inactive",
                  a.last_scanned_at.strftime("%Y-%m-%d %H:%M") if a.last_scanned_at else "Never")
                 for a in accounts],
                [{"name": "NAME"}, {"name": "PROVIDER"}, {"name": "ACCOUNT ID"}, {"name": "ROLE ARN"},
                 {"name": "REGIONS"}, {"name": "STATUS"}, {"name": "LAST SCAN"}],
            )
        else:
            output_table(
                [(a.name, a.provider, (a.credentials or {}).get("account_id", ""),
                  ",".join(a.regions[:2]) + ("..." if len(a.regions) > 2 else ""),
                  "Active" if a.is_enabled else "Inactive")
                 for a in accounts],
                [{"name": "NAME"}, {"name": "PROVIDER"}, {"name": "ACCOUNT ID"}, {"name": "REGIONS"}, {"name": "STATUS"}],
            )
    finally:
        session.close()


@get_app.command("resources")
def get_resources(
    type: Optional[str] = typer.Option(None, "-t", "--type", help="Filter by type (EC2, Lambda, S3, RDS)"),
    region: Optional[str] = typer.Option(None, "-r", "--region", help="Filter by region"),
    status: Optional[str] = typer.Option(None, "-s", "--status", help="Filter by status"),
    limit: int = typer.Option(50, "-l", "--limit", help="Max results"),
    output: str = typer.Option("table", "-o", "--output", help="Output format: table, json, wide"),
):
    """List AWS resources."""
    init_db()
    session = get_session()

    try:
        query = session.query(CloudResource)
        if type:
            query = query.filter_by(resource_type=type)
        if region:
            query = query.filter_by(region=region)
        if status:
            query = query.filter_by(status=status)

        resources = query.limit(limit).all()

        if not resources:
            console.print("[yellow]No resources found.[/yellow]")
            return

        if output == "json":
            data = [{
                "type": r.resource_type,
                "id": r.resource_id,
                "name": r.name,
                "region": r.region,
                "status": r.status,
            } for r in resources]
            output_json(data)
        elif output == "wide":
            output_table(
                [(r.resource_type, r.resource_id, r.name or "-", r.region,
                  r.status, r.resource_id or "-", r.updated_at.strftime("%Y-%m-%d %H:%M"))
                 for r in resources],
                [{"name": "TYPE"}, {"name": "ID"}, {"name": "NAME"}, {"name": "REGION"},
                 {"name": "STATUS"}, {"name": "ARN"}, {"name": "UPDATED"}],
            )
        else:
            output_table(
                [(r.resource_type, r.resource_id, r.name or "-", r.region, r.status)
                 for r in resources],
                [{"name": "TYPE"}, {"name": "ID"}, {"name": "NAME"}, {"name": "REGION"}, {"name": "STATUS"}],
            )
    finally:
        session.close()


@get_app.command("issues")
def get_issues(
    severity: Optional[str] = typer.Option(None, "-s", "--severity", help="Filter: critical, high, medium, low"),
    status: str = typer.Option("open", "--status", help="Filter: open, investigating, resolved"),
    limit: int = typer.Option(20, "-l", "--limit", help="Max results"),
    output: str = typer.Option("table", "-o", "--output", help="Output format: table, json, wide"),
    all_status: bool = typer.Option(False, "-A", "--all", help="Show all statuses"),
):
    """List health issues."""
    init_db()
    session = get_session()

    try:
        query = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc())
        if severity:
            query = query.filter_by(severity=severity.lower())
        if not all_status and status:
            query = query.filter_by(status=status.lower())

        items = query.limit(limit).all()

        if not items:
            console.print("[green]No health issues found.[/green]")
            return

        if output == "json":
            data = [{
                "id": a.id,
                "severity": a.severity,
                "title": a.title,
                "resource": a.resource_id,
                "source": a.source,
                "status": a.status,
                "detected_at": a.detected_at.isoformat(),
            } for a in items]
            output_json(data)
        else:
            severity_colors = {"critical": "red", "high": "orange1", "medium": "yellow", "low": "blue"}
            rows = []
            for a in items:
                sev = f"[{severity_colors.get(a.severity, 'white')}]{a.severity.upper()}[/]"
                title = a.title[:40] + "..." if len(a.title) > 40 else a.title
                rows.append((str(a.id), sev, title, a.resource_id[:25],
                            a.source, a.status, a.detected_at.strftime("%m-%d %H:%M")))

            output_table(rows,
                [{"name": "ID"}, {"name": "SEVERITY"}, {"name": "TITLE"},
                 {"name": "RESOURCE"}, {"name": "SOURCE"}, {"name": "STATUS"}, {"name": "DETECTED"}])
    finally:
        session.close()


# Backward-compatible alias
@get_app.command("anomalies", hidden=True)
def get_anomalies_alias(
    severity: Optional[str] = typer.Option(None, "-s", "--severity"),
    status: str = typer.Option("open", "--status"),
    limit: int = typer.Option(20, "-l", "--limit"),
    output: str = typer.Option("table", "-o", "--output"),
    all_status: bool = typer.Option(False, "-A", "--all"),
):
    """List health issues (alias for 'get issues')."""
    get_issues(severity=severity, status=status, limit=limit, output=output, all_status=all_status)


@get_app.command("reports")
def get_reports(
    type: Optional[str] = typer.Option(None, "-t", "--type", help="Filter by type: daily, inventory"),
    limit: int = typer.Option(10, "-l", "--limit", help="Max results"),
    output: str = typer.Option("table", "-o", "--output", help="Output format: table, json"),
):
    """List generated reports."""
    init_db()
    session = get_session()

    try:
        query = session.query(Report).order_by(Report.created_at.desc())
        if type:
            query = query.filter_by(report_type=type)

        reports = query.limit(limit).all()

        if not reports:
            console.print("[yellow]No reports found.[/yellow]")
            return

        if output == "json":
            data = [{
                "id": r.id,
                "type": r.report_type,
                "title": r.title,
                "created_at": r.created_at.isoformat(),
            } for r in reports]
            output_json(data)
        else:
            output_table(
                [(str(r.id), r.report_type, r.title[:50], r.created_at.strftime("%Y-%m-%d %H:%M"))
                 for r in reports],
                [{"name": "ID"}, {"name": "TYPE"}, {"name": "TITLE"}, {"name": "CREATED"}],
            )
    finally:
        session.close()


@get_app.command("schedules")
def get_schedules(
    output: str = typer.Option("table", "-o", "--output", help="Output format: table, json"),
    all_schedules: bool = typer.Option(False, "-A", "--all", help="Show disabled schedules too"),
):
    """List scheduled tasks."""
    from agenticops.scheduler import Scheduler

    init_db()
    schedules = Scheduler.list_schedules()

    if not schedules:
        console.print("[yellow]No schedules found.[/yellow]")
        return

    if not all_schedules:
        schedules = [s for s in schedules if s.is_enabled]

    if output == "json":
        data = [{
            "name": s.name,
            "pipeline": s.pipeline_name,
            "cron": s.cron_expression,
            "enabled": s.is_enabled,
            "next_run": s.next_run_at.isoformat() if s.next_run_at else None,
        } for s in schedules]
        output_json(data)
    else:
        output_table(
            [(s.name, s.pipeline_name, s.cron_expression,
              "Yes" if s.is_enabled else "No",
              s.next_run_at.strftime("%Y-%m-%d %H:%M") if s.next_run_at else "-")
             for s in schedules],
            [{"name": "NAME"}, {"name": "PIPELINE"}, {"name": "CRON"},
             {"name": "ENABLED"}, {"name": "NEXT RUN"}],
        )


@get_app.command("channels")
def get_channels(
    output: str = typer.Option("table", "-o", "--output", help="Output format: table, json"),
):
    """List notification channels."""
    from agenticops.notify import NotificationManager

    channels = NotificationManager.list_channels()

    if not channels:
        console.print("[yellow]No notification channels found.[/yellow]")
        return

    if output == "json":
        data = [{
            "name": c.name,
            "type": c.channel_type,
            "severity_filter": c.severity_filter,
            "enabled": c.is_enabled,
        } for c in channels]
        output_json(data)
    else:
        output_table(
            [(c.name, c.channel_type, ",".join(c.severity_filter) if c.severity_filter else "all",
              "Yes" if c.is_enabled else "No")
             for c in channels],
            [{"name": "NAME"}, {"name": "TYPE"}, {"name": "SEVERITY FILTER"}, {"name": "ENABLED"}],
        )


# ============================================================================
# DESCRIBE Commands - Show Details
# ============================================================================


@describe_app.command("account")
def describe_account(name: str = typer.Argument(..., help="Account name")):
    """Show details of an AWS account."""
    init_db()
    session = get_session()

    try:
        account = session.query(CloudAccount).filter_by(name=name).first()
        if not account:
            console.print(f"[red]Account '{name}' not found.[/red]")
            raise typer.Exit(1)

        creds = account.credentials or {}
        data = {
            "Name": account.name,
            "Provider": account.provider,
            "Account ID": creds.get("account_id", ""),
            "Role ARN": creds.get("role_arn", ""),
            "External ID": creds.get("external_id", "") or "-",
            "Regions": account.regions,
            "Status": "Active" if account.is_enabled else "Inactive",
            "Created": account.created_at.strftime("%Y-%m-%d %H:%M"),
            "Last Scanned": account.last_scanned_at.strftime("%Y-%m-%d %H:%M") if account.last_scanned_at else "Never",
        }
        output_yaml(data)
    finally:
        session.close()


@describe_app.command("resource")
def describe_resource(resource_id: str = typer.Argument(..., help="Resource ID")):
    """Show details of an AWS resource."""
    init_db()
    session = get_session()

    try:
        resource = session.query(CloudResource).filter_by(resource_id=resource_id).first()
        if not resource:
            # Try by database ID
            try:
                resource = session.query(CloudResource).filter_by(id=int(resource_id)).first()
            except ValueError:
                pass

        if not resource:
            console.print(f"[red]Resource '{resource_id}' not found.[/red]")
            raise typer.Exit(1)

        data = {
            "Type": resource.resource_type,
            "ID": resource.resource_id,
            "Name": resource.name or "-",
            "ARN": resource.resource_id or "-",
            "Region": resource.region,
            "Status": resource.status,
            "Tags": resource.tags or {},
            "Metadata": resource.raw_data or {},
            "Created": resource.created_at.strftime("%Y-%m-%d %H:%M"),
            "Updated": resource.updated_at.strftime("%Y-%m-%d %H:%M"),
        }
        output_yaml(data)
    finally:
        session.close()


@describe_app.command("issue")
def describe_issue(issue_id: int = typer.Argument(..., help="Health issue ID")):
    """Show details of a health issue."""
    init_db()
    session = get_session()

    try:
        item = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not item:
            console.print(f"[red]Health issue #{issue_id} not found.[/red]")
            raise typer.Exit(1)

        severity_colors = {"critical": "red", "high": "orange1", "medium": "yellow", "low": "blue"}
        color = severity_colors.get(item.severity, "white")

        console.print(Panel(
            f"[{color}][bold]{item.severity.upper()}[/bold][/{color}] {item.title}\n\n"
            f"[bold]Description:[/bold] {item.description}",
            title=f"Health Issue #{issue_id}",
        ))

        data = {
            "Resource": item.resource_id,
            "Source": item.source,
            "Status": item.status,
            "Detected": item.detected_at.strftime("%Y-%m-%d %H:%M"),
            "Detected By": item.detected_by,
            "Resolved": item.resolved_at.strftime("%Y-%m-%d %H:%M") if item.resolved_at else "-",
        }

        if item.alarm_name:
            data["Alarm"] = item.alarm_name

        output_yaml(data)

        # Show metric data if available
        if item.metric_data:
            console.print("\n[bold]Metric Data:[/bold]")
            output_yaml(item.metric_data)

        # Show related changes if available
        if item.related_changes:
            console.print("\n[bold]Related Changes (CloudTrail):[/bold]")
            for change in item.related_changes[:5]:
                if isinstance(change, dict):
                    console.print(f"  - {change}")
                else:
                    console.print(f"  - {change}")
    finally:
        session.close()


# Backward-compatible alias
@describe_app.command("anomaly", hidden=True)
def describe_anomaly_alias(anomaly_id: int = typer.Argument(..., help="Health issue ID")):
    """Show details of a health issue (alias for 'describe issue')."""
    describe_issue(issue_id=anomaly_id)


@describe_app.command("report")
def describe_report(report_id: int = typer.Argument(..., help="Report ID")):
    """Show details of a report."""
    init_db()
    session = get_session()

    try:
        report = session.query(Report).filter_by(id=report_id).first()
        if not report:
            console.print(f"[red]Report #{report_id} not found.[/red]")
            raise typer.Exit(1)

        console.print(Panel(report.content_markdown[:2000] + ("..." if len(report.content_markdown) > 2000 else ""),
                          title=report.title))
    finally:
        session.close()


# ============================================================================
# CREATE Commands - Create Resources
# ============================================================================


@create_app.command("account")
def create_account(
    name: str = typer.Argument(..., help="Account name"),
    account_id: str = typer.Option(..., "--account-id", "-a", help="AWS Account ID"),
    role_arn: str = typer.Option(..., "--role-arn", "-r", help="IAM Role ARN"),
    external_id: Optional[str] = typer.Option(None, "--external-id", "-e", help="External ID"),
    regions: str = typer.Option("us-east-1,us-west-2", "--regions", help="Comma-separated regions"),
    activate: bool = typer.Option(True, "--activate/--no-activate", help="Activate this account (deactivates others)"),
):
    """Create an AWS account configuration. Only ONE account can be active at a time."""
    init_db()
    session = get_session()

    try:
        existing = session.query(CloudAccount).filter_by(name=name).first()
        if existing:
            console.print(f"[red]Account '{name}' already exists.[/red]")
            raise typer.Exit(1)

        region_list = [r.strip() for r in regions.split(",")]

        # Multi-account: multiple accounts can be enabled simultaneously

        account = CloudAccount(
            name=name,
            provider="aws",
            credentials={
                "account_id": account_id,
                "role_arn": role_arn,
                "external_id": external_id or "",
            },
            regions=region_list,
            is_enabled=activate,
        )
        session.add(account)
        session.commit()

        console.print(f"[green]account/{name} created[/green]")
        if activate:
            console.print(f"[yellow]Account '{name}' is now the active account.[/yellow]")

    except Exception as e:
        session.rollback()
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        session.close()


@create_app.command("schedule")
def create_schedule(
    name: str = typer.Argument(..., help="Schedule name"),
    pipeline: str = typer.Argument(..., help="Pipeline: FullScan, Monitoring, DailyReport"),
    cron: str = typer.Argument(..., help="Cron expression (e.g., '0 0 * * *')"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account name"),
):
    """Create a scheduled task."""
    from agenticops.scheduler import Scheduler

    try:
        schedule = Scheduler.add_schedule(
            name=name,
            pipeline_name=pipeline,
            cron_expression=cron,
            account_name=account,
        )
        console.print(f"[green]schedule/{name} created[/green]")
        console.print(f"  Next run: {schedule.next_run_at.strftime('%Y-%m-%d %H:%M')}")

    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@create_app.command("channel")
def create_channel(
    name: str = typer.Argument(..., help="Channel name"),
    type: str = typer.Option(..., "--type", "-t", help="Type: slack, email, sns, webhook"),
    config: str = typer.Option(..., "--config", "-c", help="JSON config string"),
    severity: Optional[str] = typer.Option(None, "--severity", "-s", help="Comma-separated severities to filter"),
):
    """Create a notification channel."""
    from agenticops.notify import NotificationManager

    try:
        config_dict = json.loads(config)
        severity_list = [s.strip() for s in severity.split(",")] if severity else []

        NotificationManager.add_channel(
            name=name,
            channel_type=type,
            config=config_dict,
            severity_filter=severity_list,
        )
        console.print(f"[green]channel/{name} created[/green]")

    except json.JSONDecodeError:
        console.print("[red]Error: Invalid JSON config[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


# ============================================================================
# DELETE Commands - Delete Resources
# ============================================================================


@delete_app.command("account")
def delete_account(
    name: str = typer.Argument(..., help="Account name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete an AWS account configuration."""
    init_db()
    session = get_session()

    try:
        account = session.query(CloudAccount).filter_by(name=name).first()
        if not account:
            console.print(f"[red]Account '{name}' not found.[/red]")
            raise typer.Exit(1)

        if not force:
            confirm = typer.confirm(f"Delete account '{name}'?")
            if not confirm:
                raise typer.Exit(0)

        session.delete(account)
        session.commit()
        console.print(f"[green]account/{name} deleted[/green]")

    except Exception as e:
        session.rollback()
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        session.close()


@delete_app.command("schedule")
def delete_schedule(
    name: str = typer.Argument(..., help="Schedule name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a scheduled task."""
    from agenticops.scheduler import Scheduler

    if not force:
        confirm = typer.confirm(f"Delete schedule '{name}'?")
        if not confirm:
            raise typer.Exit(0)

    if Scheduler.delete_schedule(name):
        console.print(f"[green]schedule/{name} deleted[/green]")
    else:
        console.print(f"[red]Schedule '{name}' not found.[/red]")
        raise typer.Exit(1)


# ============================================================================
# UPDATE Commands - Update Resources
# ============================================================================


@update_app.command("account")
def update_account(
    name: str = typer.Argument(..., help="Account name"),
    role_arn: Optional[str] = typer.Option(None, "--role-arn", "-r", help="New Role ARN"),
    external_id: Optional[str] = typer.Option(None, "--external-id", "-e", help="New External ID"),
    regions: Optional[str] = typer.Option(None, "--regions", help="New regions (comma-separated)"),
    enable: bool = typer.Option(False, "--enable", help="Enable account (deactivates others)"),
    disable: bool = typer.Option(False, "--disable", help="Disable account"),
):
    """Update an AWS account configuration. Only ONE account can be active at a time."""
    init_db()
    session = get_session()

    try:
        account = session.query(CloudAccount).filter_by(name=name).first()
        if not account:
            console.print(f"[red]Account '{name}' not found.[/red]")
            raise typer.Exit(1)

        if role_arn or external_id is not None:
            creds = dict(account.credentials or {})
            if role_arn:
                creds["role_arn"] = role_arn
            if external_id is not None:
                creds["external_id"] = external_id
            account.credentials = creds
        if regions:
            account.regions = [r.strip() for r in regions.split(",")]
        if enable:
            account.is_enabled = True
            console.print(f"[green]Account '{name}' enabled.[/green]")
        if disable:
            account.is_enabled = False

        session.commit()
        console.print(f"[green]account/{name} updated[/green]")

    except Exception as e:
        session.rollback()
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        session.close()


@update_app.command("issue")
def update_issue(
    issue_id: int = typer.Argument(..., help="Health issue ID"),
    investigate: bool = typer.Option(False, "--investigate", "-i", help="Mark as investigating"),
    resolve: bool = typer.Option(False, "--resolve", "-r", help="Resolve the issue"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Set status directly"),
):
    """Update a health issue status."""
    init_db()
    session = get_session()

    try:
        item = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not item:
            console.print(f"[red]Health issue #{issue_id} not found.[/red]")
            raise typer.Exit(1)

        if investigate:
            if item.status != "open":
                console.print(f"[yellow]Issue is already {item.status}.[/yellow]")
                return
            item.status = "investigating"
            console.print(f"[green]issue/{issue_id} investigating[/green]")

        if resolve:
            if item.status == "resolved":
                console.print("[yellow]Issue is already resolved.[/yellow]")
                return
            item.status = "resolved"
            item.resolved_at = datetime.now(timezone.utc)
            console.print(f"[green]issue/{issue_id} resolved[/green]")

        if status:
            item.status = status
            if status == "resolved":
                item.resolved_at = datetime.now(timezone.utc)
            console.print(f"[green]issue/{issue_id} status set to {status}[/green]")

        session.commit()

    except Exception as e:
        session.rollback()
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        session.close()


# Backward-compatible alias
@update_app.command("anomaly", hidden=True)
def update_anomaly_alias(
    anomaly_id: int = typer.Argument(..., help="Health issue ID"),
    investigate: bool = typer.Option(False, "--investigate", "-i"),
    resolve: bool = typer.Option(False, "--resolve", "-r"),
    status: Optional[str] = typer.Option(None, "--status", "-s"),
):
    """Update a health issue (alias for 'update issue')."""
    update_issue(issue_id=anomaly_id, investigate=investigate, resolve=resolve, status=status)


@update_app.command("schedule")
def update_schedule(
    name: str = typer.Argument(..., help="Schedule name"),
    enable: bool = typer.Option(False, "--enable", help="Enable schedule"),
    disable: bool = typer.Option(False, "--disable", help="Disable schedule"),
):
    """Update a schedule."""
    from agenticops.scheduler import Scheduler

    if enable:
        if Scheduler.enable_schedule(name):
            console.print(f"[green]schedule/{name} enabled[/green]")
        else:
            console.print(f"[red]Schedule '{name}' not found.[/red]")
            raise typer.Exit(1)

    if disable:
        if Scheduler.disable_schedule(name):
            console.print(f"[yellow]schedule/{name} disabled[/yellow]")
        else:
            console.print(f"[red]Schedule '{name}' not found.[/red]")
            raise typer.Exit(1)


# ============================================================================
# RUN Commands - Execute Operations
# ============================================================================


@run_app.command("scan")
def run_scan(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account name"),
    services: str = typer.Option("EC2,Lambda,RDS,S3", "--services", "-s", help="Services to scan"),
    regions: Optional[str] = typer.Option(None, "--regions", "-r", help="Override regions"),
):
    """Scan AWS resources via the Scan Agent."""
    from agenticops.agents.scan_agent import scan_agent

    regions_str = regions if regions else "all"

    console.print(f"[bold]Running scan agent (services={services}, regions={regions_str})...[/bold]")

    with console.status("Scanning via agent..."):
        result = scan_agent._tool_func(services=services, regions=regions_str)

    console.print(f"\n[green]Scan complete:[/green]\n{result}")


@run_app.command("detect")
def run_detect(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account name"),
    scope: str = typer.Option("all", "--scope", "-s", help="Resource type filter or 'all'"),
):
    """Run health detection via the Detect Agent."""
    from agenticops.agents.detect_agent import detect_agent

    console.print(f"[bold]Running detect agent (scope={scope})...[/bold]")

    with console.status("Running health checks via agent..."):
        result = detect_agent._tool_func(scope=scope, deep=False)

    console.print(f"\n[green]Detection complete:[/green]\n{result}")


@run_app.command("analyze")
def run_analyze(
    issue_id: int = typer.Argument(..., help="Health issue ID to analyze"),
):
    """Run Root Cause Analysis on a health issue using the RCA Agent."""
    init_db()
    session = get_session()

    try:
        item = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not item:
            console.print(f"[red]Health issue #{issue_id} not found.[/red]")
            raise typer.Exit(1)
    finally:
        session.close()

    from agenticops.agents.rca_agent import rca_agent

    console.print(f"[bold]Running RCA on HealthIssue #{issue_id}...[/bold]")

    with console.status("RCA Agent investigating..."):
        result = rca_agent(issue_id=issue_id)

    console.print(f"\n{result}")


@run_app.command("report")
def run_report(
    type: str = typer.Option("daily", "--type", "-t", help="Report type: daily, incident, inventory"),
    scope: str = typer.Option("all", "--scope", "-s", help="Resource scope filter (e.g., EC2, RDS) or 'all'"),
):
    """Generate an operations report using the Reporter Agent."""
    init_db()

    from agenticops.agents.reporter_agent import reporter_agent

    console.print(f"[bold]Generating {type} report (scope={scope})...[/bold]")

    with console.status("Reporter Agent generating report..."):
        result = reporter_agent(report_type=type, scope=scope)

    console.print(f"\n{result}")


@run_app.command("schedule")
def run_schedule_now(
    name: str = typer.Argument(..., help="Schedule name to run"),
):
    """Manually trigger a scheduled task."""
    from agenticops.scheduler import Scheduler

    console.print(f"[bold]Running schedule '{name}'...[/bold]")

    with console.status("Executing pipeline..."):
        execution = Scheduler.run_now(name)

    if not execution:
        console.print(f"[red]Schedule '{name}' not found.[/red]")
        raise typer.Exit(1)

    if execution.status == "completed":
        console.print(f"[green]schedule/{name} completed[/green]")
        if execution.duration_ms:
            console.print(f"  Duration: {execution.duration_ms}ms")
    else:
        console.print(f"[red]schedule/{name} failed[/red]")
        if execution.error:
            console.print(f"  Error: {execution.error}")
        raise typer.Exit(1)


@run_app.command("notify")
def run_notify(
    subject: str = typer.Argument(..., help="Notification subject"),
    body: str = typer.Option("", "--body", "-b", help="Notification body"),
    severity: Optional[str] = typer.Option(None, "--severity", "-s", help="Severity level"),
    channel: Optional[str] = typer.Option(None, "--channel", "-c", help="Specific channel"),
):
    """Send a notification."""
    import asyncio
    from agenticops.notify import NotificationManager

    manager = NotificationManager()
    channel_names = [channel] if channel else None

    console.print("[bold]Sending notification...[/bold]")

    results = asyncio.run(manager.send_notification(
        subject=subject,
        body=body,
        severity=severity,
        channel_names=channel_names,
    ))

    if not results:
        console.print("[yellow]No channels matched.[/yellow]")
        return

    for ch_name, success in results.items():
        if success:
            console.print(f"  [green]+ {ch_name}: sent[/green]")
        else:
            console.print(f"  [red]- {ch_name}: failed[/red]")


# ============================================================================
# LOGS Commands - View Audit Trail
# ============================================================================


@logs_app.command("audit")
def logs_audit(
    entity_type: Optional[str] = typer.Option(None, "--entity-type", "-e", help="Filter by entity type"),
    action: Optional[str] = typer.Option(None, "--action", "-a", help="Filter by action"),
    hours: int = typer.Option(24, "--hours", "-H", help="Hours to look back"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    output: str = typer.Option("table", "-o", "--output", help="Output format: table, json"),
):
    """View audit logs."""
    from agenticops.audit import AuditService

    init_db()
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    logs = AuditService.query(
        action=action,
        entity_type=entity_type,
        start_time=start_time,
        limit=limit,
    )

    if not logs:
        console.print("[yellow]No audit logs found.[/yellow]")
        return

    if output == "json":
        data = [{
            "timestamp": log.timestamp.isoformat(),
            "action": log.action,
            "entity": f"{log.entity_type}/{log.entity_id}",
            "user": log.user_email or str(log.user_id) if log.user_id else "system",
            "details": log.details,
        } for log in logs]
        output_json(data)
    else:
        action_colors = {"create": "green", "update": "yellow", "delete": "red", "login": "cyan"}
        rows = []
        for log in logs:
            action_style = action_colors.get(log.action, "white")
            rows.append((
                log.timestamp.strftime("%m-%d %H:%M"),
                f"[{action_style}]{log.action}[/]",
                f"{log.entity_type}/{log.entity_id[:15]}",
                log.user_email or str(log.user_id) if log.user_id else "system",
            ))

        output_table(rows, [{"name": "TIME"}, {"name": "ACTION"}, {"name": "ENTITY"}, {"name": "USER"}])


@logs_app.command("entity")
def logs_entity(
    entity_type: str = typer.Argument(..., help="Entity type"),
    entity_id: str = typer.Argument(..., help="Entity ID"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
):
    """View audit history for a specific entity."""
    from agenticops.audit import AuditService

    init_db()
    logs = AuditService.get_entity_history(entity_type=entity_type, entity_id=entity_id, limit=limit)

    if not logs:
        console.print(f"[yellow]No audit history for {entity_type}/{entity_id}[/yellow]")
        return

    console.print(f"[bold]Audit History: {entity_type}/{entity_id}[/bold]\n")

    for log in logs:
        action_colors = {"create": "green", "update": "yellow", "delete": "red"}
        color = action_colors.get(log.action, "white")
        console.print(f"  [{color}]{log.action.upper()}[/] at {log.timestamp.strftime('%Y-%m-%d %H:%M')}")
        if log.user_email:
            console.print(f"    User: {log.user_email}")
        if log.details:
            console.print(f"    Details: {log.details}")
        console.print()


# ============================================================================
# Top-Level Commands
# ============================================================================


@app.command()
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all defaults (non-interactive)"),
    profile: str = typer.Option("local", "--profile", "-P", help="Deployment profile: local or cloud"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to setup.json for zero-prompt setup"),
    generate_config: bool = typer.Option(False, "--generate-config", help="Generate setup.json.example template and exit"),
):
    """Interactive setup wizard for AgenticOps.

    Guides you through 5 steps: dependency check, Bedrock config, deployment
    profile, AWS accounts, pipeline behavior, and notifications.

    For advanced users, use --config setup.json to load everything with zero prompts.
    Generate a template with --generate-config.
    """
    from agenticops.config import PROJECT_ROOT
    from agenticops.cli.init_helpers import run_init_wizard, generate_config_template

    if generate_config:
        output = Path("setup.json.example")
        generate_config_template(output)
        console.print(f"[green]Template written to[/green] [cyan]{output}[/cyan]")
        console.print("Edit and rename to setup.json, then run: [cyan]aiops init --config setup.json[/cyan]")
        return

    env_path = PROJECT_ROOT / ".env"
    config_path = Path(config) if config else None
    env_vars = run_init_wizard(yes=yes, profile=profile, config_path=config_path)
    _init_finalize(env_path, env_vars)


@app.command()
def quickstart(
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all defaults (non-interactive)"),
    profile: str = typer.Option("local", "--profile", "-P", help="Deployment profile: local or cloud"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to setup.json for zero-prompt setup"),
    start: bool = typer.Option(True, "--start/--no-start", help="Start services after init"),
    scan: bool = typer.Option(False, "--scan", help="Run initial resource scan after start"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Host to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind"),
):
    """One-click setup: init + start + optional scan.

    Runs the full init wizard, starts the service, and optionally triggers
    an initial resource scan.

    Examples:
      aiops quickstart --yes                     # fully automated local setup
      aiops quickstart --config setup.json       # zero-prompt from JSON config
      aiops quickstart --yes --no-start          # init only, don't start services
      aiops quickstart --yes --scan              # init, start, and scan
      aiops quickstart --profile cloud           # interactive cloud setup
    """
    import time as _time
    from agenticops.config import PROJECT_ROOT
    from agenticops.cli.init_helpers import run_init_wizard, check_dependencies

    env_path = PROJECT_ROOT / ".env"

    # Step 1: Dependency check
    console.print()
    console.print(Rule("[bold blue]AgenticOps Quickstart[/bold blue]"))
    console.print()
    results = check_dependencies(verbose=True)
    if not results.get("python") or not results.get("pip_packages"):
        console.print("[red]Critical dependencies missing. Aborting.[/red]")
        raise typer.Exit(1)

    # Step 2: Full init wizard
    config_path = Path(config) if config else None
    env_vars = run_init_wizard(yes=yes, profile=profile, config_path=config_path)
    _init_finalize(env_path, env_vars)

    if not start:
        console.print()
        console.print("[green]Setup complete.[/green] Run [cyan]aiops service start[/cyan] when ready.")
        return

    # Step 3: Start service
    console.print()
    console.print(Rule("[bold]Starting Services[/bold]"))
    console.print()

    # Check for existing service
    existing = _read_pid()
    if existing:
        console.print(f"[yellow]Service already running (PID {existing}). Skipping start.[/yellow]")
    else:
        be_pid = _start_backend(host, port)
        console.print(f"[bold green]Service started (PID {be_pid})[/bold green]")
        _print_service_info(host, port)

        # Wait for readiness
        console.print("\n  Waiting for service readiness...", end="")
        import httpx

        ready = False
        for _ in range(30):
            try:
                resp = httpx.get(f"http://{host}:{port}/api/health", timeout=2)
                if resp.status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            _time.sleep(0.5)
            console.print(".", end="")

        if ready:
            console.print(" [green]ready![/green]")
        else:
            console.print(" [yellow]timeout — service may still be starting.[/yellow]")

    # Step 4: Optional scan
    if scan:
        console.print()
        console.print(Rule("[bold]Initial Resource Scan[/bold]"))
        console.print()
        try:
            import httpx

            # Create a quickstart chat session
            resp = httpx.post(
                f"http://{host}:{port}/api/chat/sessions",
                json={"name": "quickstart"},
                timeout=10,
            )
            if resp.status_code in (200, 201):
                session_id = resp.json().get("session_id") or resp.json().get("id")
                console.print(f"  Created chat session: {session_id}")
                console.print("  Sending scan command... (check web dashboard for results)")
                httpx.post(
                    f"http://{host}:{port}/api/chat/sessions/{session_id}/messages",
                    json={"content": "scan all resources"},
                    timeout=10,
                )
                console.print("  [green]Scan triggered.[/green]")
            else:
                console.print(f"  [yellow]Could not create session: {resp.status_code}[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]Scan trigger failed: {e}[/yellow]")

    # Summary
    console.print()
    console.print(Rule("[bold green]Quickstart Complete[/bold green]"))
    console.print()
    console.print(f"  Dashboard : http://{host}:{port}/app/")
    console.print(f"  API       : http://{host}:{port}/api/health")
    console.print(f"  CLI chat  : [cyan]aiops chat[/cyan]")
    console.print()


def _init_finalize(env_path: Path, env_vars: dict[str, str]) -> None:
    """Write .env, init DB, copy templates, print summary."""
    import shutil
    from agenticops.config import PROJECT_ROOT

    # Write env vars
    if env_vars:
        for key, value in env_vars.items():
            _write_env_var(key, value, env_path)
        console.print(f"\n[green]Settings saved to {env_path.relative_to(PROJECT_ROOT)}[/green]")

    # Directory creation + DB init
    console.print("\n[bold]Initializing database and directories...[/bold]")
    settings.ensure_dirs()
    init_db()

    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution
    from agenticops.notify.notifier import NotificationLog
    from agenticops.auth.models import User, APIKey, Session
    from agenticops.audit.models import AuditLog
    from agenticops.models import Base, get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)
    console.print("[green]Database initialized.[/green]")

    # Copy config templates if missing
    _init_copy_template(
        PROJECT_ROOT / "config" / "channels.yaml.example",
        PROJECT_ROOT / "config" / "channels.yaml",
    )
    _init_copy_template(
        PROJECT_ROOT / "config" / "im-apps.yaml.example",
        PROJECT_ROOT / "config" / "im-apps.yaml",
    )

    # ── Summary ──────────────────────────────────────────────────────────
    if env_vars:
        console.print()
        console.print(Rule("[bold green]Configuration Summary[/bold green]"))
        summary = Table(show_header=True, box=SIMPLE)
        summary.add_column("Setting", style="cyan")
        summary.add_column("Value")
        for key, value in env_vars.items():
            # Mask sensitive values
            display = "****" if any(s in key.lower() for s in ("secret", "password", "token", "api_key", "app_key")) else value
            summary.add_row(key, display)
        console.print(summary)

    console.print()
    console.print(Rule("[bold]Next Steps[/bold]"))
    console.print("  1. [cyan]aiops chat[/cyan]           — start interactive chat")
    console.print("  2. [cyan]aiops service start[/cyan]   — run as background service")
    console.print("  3. Edit [cyan]config/channels.yaml[/cyan] to configure notification channels")
    console.print()


# ── Init Helpers ────────────────────────────────────────────────────────────


def _init_report_storage(env_vars: dict[str, str]) -> None:
    """Prompt user to choose report storage backend (local or S3)."""
    from rich.prompt import Prompt

    console.print("  Reports can be stored locally or on S3.")
    console.print("  S3 is recommended for production.\n")

    choice = Prompt.ask(
        "  Storage backend",
        choices=["local", "s3"],
        default="local",
    )

    if choice == "s3":
        bucket = Prompt.ask("  S3 bucket name")
        prefix = Prompt.ask("  S3 key prefix", default="reports/")
        region = Prompt.ask("  S3 region", default="us-east-1")

        try:
            _validate_s3_bucket(bucket, region)
        except Exception as e:
            console.print(f"  [red]S3 validation failed: {e}[/red]")
            console.print("  [yellow]Falling back to local storage.[/yellow]")
            env_vars["AIOPS_REPORT_STORAGE"] = "local"
            return

        env_vars["AIOPS_REPORT_STORAGE"] = "s3"
        env_vars["AIOPS_REPORT_S3_BUCKET"] = bucket
        env_vars["AIOPS_REPORT_S3_PREFIX"] = prefix
        env_vars["AIOPS_REPORT_S3_REGION"] = region
        console.print(f"  [green]S3 storage configured: s3://{bucket}/{prefix}[/green]")
    else:
        env_vars["AIOPS_REPORT_STORAGE"] = "local"
        console.print(f"  [green]Local storage: {settings.reports_dir}[/green]")


def _init_copy_template(src: Path, dest: Path) -> None:
    """Copy a config template file if destination doesn't exist."""
    import shutil

    if dest.exists():
        return
    if not src.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    console.print(f"  [green]Created[/green] {dest.name} from template")


def _validate_s3_bucket(bucket: str, region: str) -> None:
    """Verify S3 bucket exists and is writable."""
    import boto3

    s3 = boto3.client("s3", region_name=region)
    s3.head_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key=".agenticops-probe", Body=b"ok")
    s3.delete_object(Bucket=bucket, Key=".agenticops-probe")


def _write_env_var(key: str, value: str, env_path: Optional[Path] = None) -> None:
    """Set a variable in .env (create if needed, update if exists)."""
    if env_path is None:
        from agenticops.config import PROJECT_ROOT
        env_path = PROJECT_ROOT / ".env"

    lines: list[str] = []
    found = False

    if env_path.exists():
        lines = env_path.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
                lines[i] = f"{key}={value}"
                found = True
                break

    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")


# ============================================================================
# Chat Slash Commands
# ============================================================================

def _slash_help(ctx: ChatContext, args: list) -> str:
    """Show available slash commands."""
    # Check for specific topic help
    if args:
        topic = args[0].lower()
        if topic in ["workflow", "workflows", "wf"]:
            return """[bold]Workflow Commands:[/bold]

  /workflow full-scan       Complete scan → detect → report pipeline
  /workflow daily           Daily ops: scan → detect → analyze → report
  /workflow incident <id>   Incident response for anomaly
  /workflow health          System-wide health check

[dim]Workflows orchestrate multiple operations in sequence.[/dim]"""

        elif topic in ["session", "sessions"]:
            return """[bold]Session Commands:[/bold]

  /session list             List DB sessions (id, name, msgs, activity, pin/star)
  /session resume [id|name] Switch to a session (default: most recent active)
  /session rename <id> <name>  Rename a session
  /session pin <id>         Toggle pinned status
  /session star <id>        Toggle starred status
  /session archive <id>     Toggle archived status
  /session save [name]      Save context to local JSON (backward compat)
  /session load <name>      Load context from local JSON (backward compat)
  /session delete <name>    Delete a local JSON session

[dim]DB sessions are shared with the Web Dashboard. save/load use local JSON files.[/dim]"""

        elif topic in ["context", "ctx"]:
            return """[bold]Context Commands:[/bold]

  /context                  Show current context
  /context account <name>   Switch to account
  /context reset            Reset to defaults

[dim]Context affects which account operations target.[/dim]"""

    return """[bold]AgenticOps Chat Commands[/bold]

[cyan]Quick Status:[/cyan]
  /status                          System status overview
  /alias                           Show command aliases

[cyan]Resources:[/cyan]
  /account list | show <name>      AWS accounts
  /resource list | show <id>       AWS resources
  /issue list | show <id>          Health issues
  /report list                     Generated reports

[cyan]Operations:[/cyan]
  /scan [--services SVC]           Scan AWS resources (via agent)
  /detect [SCOPE]                  Run health detection (via agent)
  /analyze <issue_id>              Show issue details
  /acknowledge <id>                Start investigating issue
  /resolve <id>                    Resolve issue

[cyan]Fix Plans:[/cyan]
  /fix list [issue_id] [--status S] [--risk L]   List fix plans
  /fix show <plan_id>              Show fix plan details
  /approve <plan_id>               Approve a fix plan (L2/L3 human gate)
  /execute <plan_id>               Execute an approved fix plan

[cyan]Workflows:[/cyan]  [dim](/help workflow for details)[/dim]
  /workflow full-scan              Full infrastructure scan
  /workflow daily                  Daily operations pipeline
  /workflow incident <id>          Incident response
  /workflow health                 System health check

[cyan]Automation:[/cyan]
  /schedule list | run <name>      Manage schedules
  /notify list | test | send       Notifications
  /channel list | show | sync | test  Channel management

[cyan]Session & Context:[/cyan]
  /session list | resume | pin     Session management (DB-backed)
  /context [account <name>]        Context management

[cyan]Export & Output:[/cyan]
  /export <entity> [--csv]         Export data
  /output <format>                 Set format (table/json/wide/yaml)
  /style <style>                   Set table style (default/simple/ascii)

[cyan]Scroll & Pager:[/cyan]
  /scroll [N|all]                  View conversation history (scrollable)
  /less                            View full last output in pager
  /pager on|off|auto|<N>           Toggle auto-truncation (auto = terminal height)

[cyan]Token Usage:[/cyan]
  /tokens                          Show token usage statistics
  /tokens reset                    Reset token counters

[cyan]Other:[/cyan]
  /clear                           Clear screen
  /detail [concise|medium|detailed] Set agent output detail level
  /model [agent] [alias]             Switch agent model (or /model reset)
  /help [topic]                    Show help

[cyan]Exit:[/cyan]
  /exit, /quit, /q                 End session

[dim]Tip: Most commands have shortcuts. Type /alias to see them.[/dim]
[dim]Scroll: Use Page Up/Down, mouse wheel, or /scroll to view history.[/dim]
"""


def _slash_account(ctx: ChatContext, args: list) -> str:
    """Handle /account commands."""
    init_db()
    session = get_session()

    try:
        if not args or args[0] == "list":
            accounts = session.query(CloudAccount).all()
            if not accounts:
                return "[yellow]No accounts found.[/yellow]"

            if ctx.output_format == "json":
                data = [{"name": a.name, "provider": a.provider,
                        "account_id": (a.credentials or {}).get("account_id", ""),
                        "regions": a.regions, "is_enabled": a.is_enabled} for a in accounts]
                return json.dumps(data, indent=2)

            lines = ["[bold]Cloud Accounts:[/bold] [dim](only one can be active)[/dim]"]
            for a in accounts:
                status = "[green]● Active[/green]" if a.is_enabled else "[dim]○ Inactive[/dim]"
                acct_id = (a.credentials or {}).get("account_id", "")
                lines.append(f"  {status} {a.name}: {a.provider}/{acct_id}")
            return "\n".join(lines)

        elif args[0] in ["show", "describe"] and len(args) > 1:
            name = args[1]
            account = session.query(CloudAccount).filter_by(name=name).first()
            if not account:
                return f"[red]Account '{name}' not found.[/red]"

            status = "[green]Active[/green]" if account.is_enabled else "[red]Inactive[/red]"
            creds = account.credentials or {}
            return f"""[bold]Account: {account.name}[/bold] {status}
  Provider: {account.provider}
  Account ID: {creds.get('account_id', '')}
  Role ARN: {creds.get('role_arn', '')}
  External ID: {creds.get('external_id', '') or '-'}
  Regions: {', '.join(account.regions)}
  Last Scanned: {account.last_scanned_at.strftime('%Y-%m-%d %H:%M') if account.last_scanned_at else 'Never'}"""

        elif args[0] in ["activate", "enable", "use"] and len(args) > 1:
            name = args[1]
            account = session.query(CloudAccount).filter_by(name=name).first()
            if not account:
                return f"[red]Account '{name}' not found.[/red]"

            if account.is_enabled:
                return f"[yellow]Account '{name}' is already active.[/yellow]"

            account.is_enabled = True
            session.commit()
            return f"[green]Account '{name}' is now active.[/green]"

        elif args[0] in ["deactivate", "disable"] and len(args) > 1:
            name = args[1]
            account = session.query(CloudAccount).filter_by(name=name).first()
            if not account:
                return f"[red]Account '{name}' not found.[/red]"

            if not account.is_enabled:
                return f"[yellow]Account '{name}' is already inactive.[/yellow]"

            account.is_enabled = False
            session.commit()
            return f"[yellow]Account '{name}' deactivated.[/yellow]"

        elif args[0] == "delete" and len(args) > 1:
            name = args[1]
            account = session.query(CloudAccount).filter_by(name=name).first()
            if not account:
                return f"[red]Account '{name}' not found.[/red]"

            # Check if --force flag is provided
            if "--force" not in args and "-f" not in args:
                return f"[yellow]Are you sure? Use '/account delete {name} --force' to confirm.[/yellow]"

            session.delete(account)
            session.commit()
            return f"[green]Account '{name}' deleted.[/green]"

        elif args[0] == "active":
            active_list = session.query(CloudAccount).filter_by(is_enabled=True).all()
            if active_list:
                lines = ["[bold]Enabled accounts:[/bold]"]
                for a in active_list:
                    acct_id = (a.credentials or {}).get("account_id", "")
                    lines.append(f"  [green]{a.name}[/green] ({a.provider}/{acct_id})")
                return "\n".join(lines)
            return "[yellow]No active account. Use '/account activate <name>' to set one.[/yellow]"

        else:
            return """[bold]Account Commands:[/bold]

  /account list                 List all accounts
  /account show <name>          Show account details
  /account active               Show all enabled accounts
  /account activate <name>      Enable account
  /account deactivate <name>    Disable account
  /account delete <name> -f     Delete account"""
    finally:
        session.close()


def _slash_resource(ctx: ChatContext, args: list) -> str:
    """Handle /resource commands."""
    init_db()
    session = get_session()

    try:
        if not args or args[0] == "list":
            query = session.query(CloudResource)
            limit = settings.default_list_limit

            # Parse --type flag
            if "--type" in args or "-t" in args:
                flag = "--type" if "--type" in args else "-t"
                idx = args.index(flag)
                if idx + 1 < len(args):
                    query = query.filter_by(resource_type=args[idx + 1])

            # Parse --limit flag
            if "--limit" in args or "-l" in args:
                flag = "--limit" if "--limit" in args else "-l"
                idx = args.index(flag)
                if idx + 1 < len(args):
                    try:
                        limit = min(int(args[idx + 1]), settings.max_list_limit)
                    except ValueError:
                        pass

            # Parse --region flag
            if "--region" in args or "-r" in args:
                flag = "--region" if "--region" in args else "-r"
                idx = args.index(flag)
                if idx + 1 < len(args):
                    query = query.filter_by(region=args[idx + 1])

            total = query.count()
            resources = query.limit(limit).all()
            if not resources:
                return "[yellow]No resources found.[/yellow]"

            if ctx.output_format == "json":
                data = [{"type": r.resource_type, "id": r.resource_id,
                        "name": r.name, "region": r.region} for r in resources]
                return json.dumps(data, indent=2)

            lines = [f"[bold]Resources:[/bold] (showing {len(resources)} of {total}, use --limit N for more)"]
            for r in resources:
                name = r.name or r.resource_id[:20]
                # Escape brackets so Rich doesn't interpret them as markup
                lines.append(f"  \\[{r.resource_type}] {name} ({r.region})")
            return "\n".join(lines)

        elif args[0] == "show" and len(args) > 1:
            resource_id = args[1]
            resource = session.query(CloudResource).filter_by(resource_id=resource_id).first()
            if not resource:
                try:
                    resource = session.query(CloudResource).filter_by(id=int(resource_id)).first()
                except ValueError:
                    pass

            if not resource:
                return f"[red]Resource '{resource_id}' not found.[/red]"

            return f"""[bold]Resource: {resource.name or resource.resource_id}[/bold]
  Type: {resource.resource_type}
  ID: {resource.resource_id}
  ARN: {resource.resource_id or '-'}
  Region: {resource.region}
  Status: {resource.status}
  Tags: {resource.tags or {}}"""

        else:
            return "[yellow]Usage: /resource list [--type TYPE] | /resource show <id>[/yellow]"
    finally:
        session.close()


def _slash_issue(ctx: ChatContext, args: list) -> str:
    """Handle /issue commands."""
    init_db()
    session = get_session()

    try:
        if not args or args[0] == "list":
            query = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc())
            limit = settings.default_list_limit

            # Parse --status flag
            if "--status" in args or "-s" in args:
                flag = "--status" if "--status" in args else "-s"
                idx = args.index(flag)
                if idx + 1 < len(args):
                    query = query.filter_by(status=args[idx + 1])
            elif "-A" not in args and "--all" not in args:
                query = query.filter_by(status="open")

            # Parse --limit flag
            if "--limit" in args or "-l" in args:
                flag = "--limit" if "--limit" in args else "-l"
                idx = args.index(flag)
                if idx + 1 < len(args):
                    try:
                        limit = min(int(args[idx + 1]), settings.max_list_limit)
                    except ValueError:
                        pass

            total = query.count()
            items = query.limit(limit).all()
            if not items:
                return "[green]No health issues found.[/green]"

            if ctx.output_format == "json":
                data = [{"id": a.id, "severity": a.severity, "title": a.title,
                        "source": a.source, "status": a.status} for a in items]
                return json.dumps(data, indent=2)

            severity_colors = {"critical": "red", "high": "orange1", "medium": "yellow", "low": "blue"}
            lines = [f"[bold]Health Issues:[/bold] (showing {len(items)} of {total}, use --limit N for more)"]
            for a in items:
                color = severity_colors.get(a.severity, "white")
                title = a.title[:40] + "..." if len(a.title) > 40 else a.title
                # Escape brackets around status so Rich doesn't interpret them
                lines.append(f"  [{color}]#{a.id}[/] {title} \\[{a.status}]")
            return "\n".join(lines)

        elif args[0] == "show" and len(args) > 1:
            try:
                issue_id = int(args[1])
            except ValueError:
                return "[red]Invalid issue ID.[/red]"

            item = session.query(HealthIssue).filter_by(id=issue_id).first()
            if not item:
                return f"[red]Health issue #{issue_id} not found.[/red]"

            severity_colors = {"critical": "red", "high": "orange1", "medium": "yellow", "low": "blue"}
            color = severity_colors.get(item.severity, "white")

            return f"""[{color}][bold]{item.severity.upper()}[/bold][/{color}] {item.title}

[bold]Description:[/bold] {item.description}

[bold]Details:[/bold]
  Resource: {item.resource_id}
  Source: {item.source}
  Status: {item.status}
  Detected: {item.detected_at.strftime('%Y-%m-%d %H:%M')}
  Detected By: {item.detected_by}"""

        else:
            return "[yellow]Usage: /issue list [--status STATUS] | /issue show <id>[/yellow]"
    finally:
        session.close()


def _slash_report(ctx: ChatContext, args: list) -> str:
    """Handle /report commands."""
    init_db()
    session = get_session()

    try:
        reports = session.query(Report).order_by(Report.created_at.desc()).limit(10).all()
        if not reports:
            return "[yellow]No reports found.[/yellow]"

        if ctx.output_format == "json":
            data = [{"id": r.id, "type": r.report_type, "title": r.title} for r in reports]
            return json.dumps(data, indent=2)

        lines = ["[bold]Reports:[/bold]"]
        for r in reports:
            # Escape brackets around report_type
            lines.append(f"  #{r.id} \\[{r.report_type}] {r.title[:40]}")
        return "\n".join(lines)
    finally:
        session.close()


def _slash_scan(ctx: ChatContext, args: list) -> str:
    """Handle /scan command via scan_agent tool."""
    from agenticops.agents.scan_agent import scan_agent

    services = "all"
    if "--services" in args:
        idx = args.index("--services")
        if idx + 1 < len(args):
            services = args[idx + 1]

    regions = "all"
    if "--regions" in args:
        idx = args.index("--regions")
        if idx + 1 < len(args):
            regions = args[idx + 1]

    # Show thinking progress
    display = ThinkingDisplay(console)
    result = None

    with display.live_display():
        display.start("Initializing scan agent")
        time.sleep(0.2)
        display.tool_call("scan_agent", f"services={services}")
        display.processing("Scanning resources via agent")
        result = scan_agent._tool_func(services=services, regions=regions)
        display.complete("Scan completed")

    return f"[green]✓ Scan complete[/green]\n{result}"


def _slash_detect(ctx: ChatContext, args: list) -> str:
    """Handle /detect command via detect_agent tool."""
    from agenticops.agents.detect_agent import detect_agent

    scope = "all"
    if args:
        scope = args[0]

    # Show thinking progress
    display = ThinkingDisplay(console)
    result = None

    with display.live_display():
        display.start("Initializing detect agent")
        time.sleep(0.2)
        display.tool_call("detect_agent", f"scope={scope}")
        display.processing("Running health checks via agent")
        result = detect_agent._tool_func(scope=scope, deep=False)
        display.complete("Detection completed")

    return f"[green]✓ Detection complete[/green]\n{result}"


def _slash_analyze(ctx: ChatContext, args: list) -> str:
    """Handle /analyze <issue_id> command."""
    if not args:
        return "[yellow]Usage: /analyze <issue_id>[/yellow]"

    try:
        issue_id = int(args[0])
    except ValueError:
        return "[red]Invalid issue ID.[/red]"

    init_db()
    session = get_session()

    try:
        item = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not item:
            return f"[red]Health issue #{issue_id} not found.[/red]"

        severity_colors = {"critical": "red", "high": "orange1", "medium": "yellow", "low": "blue"}
        color = severity_colors.get(item.severity, "white")

        lines = [
            f"[bold]Health Issue #{issue_id}[/bold]",
            f"",
            f"[{color}][bold]{item.severity.upper()}[/bold][/{color}] {item.title}",
            f"",
            f"[bold]Resource:[/bold] {item.resource_id}",
            f"[bold]Source:[/bold] {item.source}",
            f"[bold]Status:[/bold] {item.status}",
        ]

        if item.metric_data:
            lines.append(f"\n[bold]Metric Data:[/bold]")
            lines.append(f"  {json.dumps(item.metric_data, indent=2)}")

        if item.related_changes:
            lines.append(f"\n[bold]Related Changes:[/bold]")
            for change in item.related_changes[:5]:
                lines.append(f"  - {change}")

        lines.append(f"\n[dim]Use 'aiops run analyze {issue_id}' or ask in chat to run RCA.[/dim]")

        return "\n".join(lines)
    finally:
        session.close()


def _slash_acknowledge(ctx: ChatContext, args: list) -> str:
    """Handle /acknowledge <issue_id> command — sets status to investigating."""
    if not args:
        return "[yellow]Usage: /acknowledge <issue_id>[/yellow]"

    try:
        issue_id = int(args[0])
    except ValueError:
        return "[red]Invalid issue ID.[/red]"

    init_db()
    session = get_session()

    try:
        item = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not item:
            return f"[red]Health issue #{issue_id} not found.[/red]"

        if item.status != "open":
            return f"[yellow]Issue is already {item.status}.[/yellow]"

        item.status = "investigating"
        session.commit()

        return f"[green]Issue #{issue_id} is now investigating.[/green]"
    finally:
        session.close()


def _slash_resolve(ctx: ChatContext, args: list) -> str:
    """Handle /resolve <issue_id> command."""
    if not args:
        return "[yellow]Usage: /resolve <issue_id>[/yellow]"

    try:
        issue_id = int(args[0])
    except ValueError:
        return "[red]Invalid issue ID.[/red]"

    init_db()
    session = get_session()

    try:
        item = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not item:
            return f"[red]Health issue #{issue_id} not found.[/red]"

        if item.status == "resolved":
            return "[yellow]Issue is already resolved.[/yellow]"

        item.status = "resolved"
        item.resolved_at = datetime.now(timezone.utc)
        session.commit()

        return f"[green]Issue #{issue_id} resolved.[/green]"
    finally:
        session.close()


# ── Fix Plan Commands ──────────────────────────────────────────────────


def _slash_fix(ctx: ChatContext, args: list) -> str:
    """Handle /fix list|show commands for fix plans."""
    from rich.prompt import Prompt

    if not args:
        return """[yellow]Usage:
  /fix list [issue_id] [--status S] [--risk L]
  /fix show <plan_id>[/yellow]"""

    sub = args[0].lower()

    if sub in ("list", "ls"):
        init_db()
        session = get_session()
        try:
            query = session.query(FixPlan).order_by(FixPlan.created_at.desc())

            # Parse optional filters
            rest = args[1:]
            i = 0
            while i < len(rest):
                if rest[i] == "--status" and i + 1 < len(rest):
                    query = query.filter_by(status=rest[i + 1])
                    i += 2
                elif rest[i] == "--risk" and i + 1 < len(rest):
                    query = query.filter_by(risk_level=rest[i + 1].upper())
                    i += 2
                else:
                    try:
                        issue_id = int(rest[i])
                        query = query.filter_by(health_issue_id=issue_id)
                    except ValueError:
                        pass
                    i += 1

            plans = query.limit(50).all()

            if not plans:
                return "[dim]No fix plans found.[/dim]"

            table = create_table("Fix Plans")
            table.add_column("ID", style="dim", width=5)
            table.add_column("Risk", width=5)
            table.add_column("Title", max_width=40)
            table.add_column("Status", width=18)
            table.add_column("Issue #", width=8)
            table.add_column("Approved By", width=15)
            table.add_column("Created")

            risk_colors = {"L0": "white", "L1": "blue", "L2": "yellow", "L3": "red"}

            for p in plans:
                rc = risk_colors.get(p.risk_level, "white")
                status_str = p.status.replace("_", " ")
                table.add_row(
                    str(p.id),
                    f"[{rc}]{p.risk_level}[/{rc}]",
                    p.title[:40],
                    status_str,
                    str(p.health_issue_id),
                    p.approved_by or "-",
                    p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "-",
                )

            buf = StringIO()
            temp_console = Console(file=buf, force_terminal=True, width=ctx.console.size.width if hasattr(ctx, 'console') else 120)
            temp_console.print(table)
            return buf.getvalue()
        finally:
            session.close()

    elif sub == "show":
        if len(args) < 2:
            return "[yellow]Usage: /fix show <plan_id>[/yellow]"

        try:
            plan_id = int(args[1])
        except ValueError:
            return "[red]Invalid plan ID.[/red]"

        init_db()
        session = get_session()
        try:
            plan = session.query(FixPlan).filter_by(id=plan_id).first()
            if not plan:
                return f"[red]Fix plan #{plan_id} not found.[/red]"

            risk_colors = {"L0": "white", "L1": "blue", "L2": "yellow", "L3": "red"}
            rc = risk_colors.get(plan.risk_level, "white")

            lines = [
                f"[bold]Fix Plan #{plan.id}[/bold]",
                f"  Title:    {plan.title}",
                f"  Risk:     [{rc}]{plan.risk_level}[/{rc}]",
                f"  Status:   {plan.status.replace('_', ' ')}",
                f"  Issue:    #{plan.health_issue_id}",
                f"  Impact:   {plan.estimated_impact or '-'}",
                f"  Summary:  {plan.summary[:200]}",
                "",
            ]

            if plan.steps:
                lines.append("[bold]Steps:[/bold]")
                for i, step in enumerate(plan.steps, 1):
                    step_text = step if isinstance(step, str) else json.dumps(step)
                    lines.append(f"  {i}. {step_text}")
                lines.append("")

            if plan.pre_checks:
                lines.append("[bold]Pre-checks:[/bold]")
                for c in plan.pre_checks:
                    lines.append(f"  - {c if isinstance(c, str) else json.dumps(c)}")
                lines.append("")

            if plan.post_checks:
                lines.append("[bold]Post-checks:[/bold]")
                for c in plan.post_checks:
                    lines.append(f"  - {c if isinstance(c, str) else json.dumps(c)}")
                lines.append("")

            if plan.rollback_plan:
                lines.append("[bold]Rollback Plan:[/bold]")
                lines.append(f"  {json.dumps(plan.rollback_plan, indent=2)}")
                lines.append("")

            if plan.approved_by:
                lines.append(f"  Approved by: [green]{plan.approved_by}[/green]")
            if plan.approved_at:
                lines.append(f"  Approved at: {plan.approved_at.strftime('%Y-%m-%d %H:%M')}")
            if plan.created_at:
                lines.append(f"  Created:     {plan.created_at.strftime('%Y-%m-%d %H:%M')}")

            return "\n".join(lines)
        finally:
            session.close()

    else:
        return """[yellow]Usage:
  /fix list [issue_id] [--status S] [--risk L]
  /fix show <plan_id>[/yellow]"""


def _slash_approve(ctx: ChatContext, args: list) -> str:
    """Handle /approve <plan_id> command — approve a fix plan."""
    from rich.prompt import Prompt, Confirm

    if not args:
        return "[yellow]Usage: /approve <plan_id>[/yellow]"

    try:
        plan_id = int(args[0])
    except ValueError:
        return "[red]Invalid plan ID.[/red]"

    init_db()
    session = get_session()

    try:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            return f"[red]Fix plan #{plan_id} not found.[/red]"

        if plan.status == "approved":
            return "[yellow]Fix plan is already approved.[/yellow]"
        if plan.status == "rejected":
            return "[yellow]Fix plan was rejected. Create a new plan instead.[/yellow]"
        if plan.status not in ("draft", "pending_approval"):
            return f"[yellow]Fix plan status is '{plan.status}', cannot approve.[/yellow]"

        # L2/L3 warning
        if plan.risk_level in ("L2", "L3"):
            console.print(
                f"[bold yellow]Warning:[/bold yellow] This is a [bold]{plan.risk_level}[/bold] fix plan "
                f"— requires human approval.\n"
                f"  Title: {plan.title}\n"
                f"  Impact: {plan.estimated_impact or 'N/A'}"
            )
            if not Confirm.ask("Proceed with approval?"):
                return "[dim]Approval cancelled.[/dim]"

        approver = Prompt.ask("Your name (approver)")
        if not approver.strip():
            return "[red]Approver name is required.[/red]"

        plan.status = "approved"
        plan.approved_by = approver.strip()
        plan.approved_at = datetime.now(timezone.utc)

        # Sync HealthIssue status
        issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first()
        if issue:
            issue.status = "fix_approved"

        session.commit()

        return f"[green]Fix plan #{plan_id} approved by {approver.strip()}.[/green]"
    finally:
        session.close()


def _slash_execute(ctx: ChatContext, args: list) -> str:
    """Handle /execute <plan_id> command — execute an approved fix plan."""
    from rich.prompt import Confirm

    if not args:
        return "[yellow]Usage: /execute <plan_id>[/yellow]"

    try:
        plan_id = int(args[0])
    except ValueError:
        return "[red]Invalid plan ID.[/red]"

    init_db()
    session = get_session()

    try:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            return f"[red]Fix plan #{plan_id} not found.[/red]"

        if plan.status != "approved":
            return f"[yellow]Fix plan status is '{plan.status}', must be 'approved' to execute.[/yellow]"

        if not settings.executor_enabled:
            return "[red]Executor is disabled. Set AIOPS_EXECUTOR_ENABLED=true to enable.[/red]"

        console.print(
            f"[bold]Execute fix plan #{plan_id}?[/bold]\n"
            f"  Title: {plan.title}\n"
            f"  Risk:  {plan.risk_level}\n"
            f"  Steps: {len(plan.steps or [])}"
        )
        if not Confirm.ask("Confirm execution?"):
            return "[dim]Execution cancelled.[/dim]"

        # Create FixExecution record
        execution = FixExecution(
            fix_plan_id=plan.id,
            health_issue_id=plan.health_issue_id,
            status="pending",
            executed_by="cli_user",
            started_at=datetime.now(timezone.utc),
        )
        plan.status = "executing"
        session.add(execution)
        session.commit()

        return (
            f"[green]Execution #{execution.id} created for fix plan #{plan_id}.[/green]\n"
            f"[dim]Status: pending — the executor agent will pick it up.[/dim]"
        )
    finally:
        session.close()


def _slash_output(ctx: ChatContext, args: list) -> str:
    """Handle /output <format> command."""
    if not args:
        return f"Current output format: [cyan]{ctx.output_format}[/cyan]\nUsage: /output <table|json|wide|yaml>"

    fmt = args[0].lower()
    if ctx.set_output(fmt):
        return f"[green]Output format set to: {fmt}[/green]"
    else:
        return f"[red]Invalid format. Use: table, json, wide, yaml[/red]"


def _slash_clear(ctx: ChatContext, args: list) -> str:
    """Handle /clear command."""
    console.clear()
    return "[dim]Screen cleared.[/dim]"


def _slash_style(ctx: ChatContext, args: list) -> str:
    """Handle /style <table_style> command for ASCII or Unicode tables."""
    available = ", ".join(TABLE_STYLES.keys())

    if not args:
        return f"Current table style: [cyan]{ctx.table_style}[/cyan]\nAvailable styles: {available}"

    style = args[0].lower()
    if ctx.set_table_style(style):
        # Show a sample table with the new style
        sample = create_table(columns=[
            {"name": "Style", "style": "cyan"},
            {"name": "Description"},
        ])
        sample.add_row("default", "Rounded Unicode borders")
        sample.add_row("simple", "Simple line borders")
        sample.add_row("minimal", "Minimal borders")
        sample.add_row("double", "Double-line borders")
        sample.add_row("ascii", "ASCII-only (compatible with all terminals)")

        console.print(f"[green]Table style set to: {style}[/green]\n")
        console.print(sample)
        return ""
    else:
        return f"[red]Invalid style. Available: {available}[/red]"


def _slash_scroll(ctx: ChatContext, args: list) -> str:
    """Handle /scroll command - view conversation history with pager."""
    count = 20  # Default number of messages

    if args:
        if args[0] == "all":
            count = len(ctx.output_history)
        else:
            try:
                count = int(args[0])
            except ValueError:
                pass

    history = ctx.get_history(count)
    if not history:
        return "[yellow]No conversation history yet.[/yellow]"

    # Build scrollable output
    lines = []
    for msg in history:
        role_color = "cyan" if msg["role"] == "user" else "green"
        lines.append(f"[dim]{msg['timestamp']}[/dim] [{role_color}]{msg['role'].upper()}[/{role_color}]")
        lines.append(msg["content"])
        lines.append("")

    output = "\n".join(lines)

    # Use pager for long history, direct print for short
    term_height = console.size.height
    if len(lines) > term_height:
        with console.pager(styles=False):
            console.print(output)
    else:
        console.print(output)
    return ""


def print_with_truncation(console: Console, content: str, ctx: ChatContext, header: str = "Agent"):
    """Print content with smart truncation based on terminal height.

    If content exceeds visible terminal area, truncate and show a hint line.
    Full output is saved to ctx.last_full_output for /less access.
    """
    term_height = console.size.height
    threshold = ctx.pager_threshold if ctx.pager_threshold > 0 else max(term_height - 8, 10)

    # Render markdown if content looks like it contains markdown
    rendered = Markdown(content) if content.startswith("#") or "```" in content else content

    # Header separator
    console.print()
    console.print(Rule(f"[bold green]{header}[/bold green]", style="green"))

    lines = content.split("\n")
    total_lines = len(lines)

    if ctx.auto_pager and total_lines > threshold:
        # Truncate: show first (threshold - 2) lines
        show_lines = max(threshold - 2, 5)
        truncated_text = "\n".join(lines[:show_lines])
        rendered_truncated = Markdown(truncated_text) if content.startswith("#") or "```" in content else truncated_text
        console.print(rendered_truncated)
        console.print(f"\n[dim]─── ✂ {show_lines} / {total_lines} 行 | /less 查看完整输出 ───[/dim]")
        ctx.last_full_output = content
    else:
        console.print(rendered)
        ctx.last_full_output = content


def _slash_pager(ctx: ChatContext, args: list) -> str:
    """Handle /pager command - toggle auto-truncation for long outputs."""
    if not args:
        status = "[green]ON[/green]" if ctx.auto_pager else "[red]OFF[/red]"
        thresh = "auto (terminal height)" if ctx.pager_threshold == 0 else f"{ctx.pager_threshold} lines"
        return f"Auto-truncation: {status} (threshold: {thresh})\nUsage: /pager on|off|auto|<threshold>"

    arg = args[0].lower()
    if arg == "on":
        ctx.auto_pager = True
        return "[green]Auto-truncation enabled.[/green]"
    elif arg == "off":
        ctx.auto_pager = False
        return "[yellow]Auto-truncation disabled. Full output will be shown.[/yellow]"
    elif arg == "auto":
        ctx.pager_threshold = 0
        ctx.auto_pager = True
        return "[green]Threshold set to auto (terminal height).[/green]"
    else:
        try:
            ctx.pager_threshold = int(arg)
            ctx.auto_pager = True
            return f"[green]Truncation threshold set to {ctx.pager_threshold} lines.[/green]"
        except ValueError:
            return "[red]Usage: /pager on|off|auto|<threshold>[/red]"


def _slash_less(ctx: ChatContext, args: list) -> str:
    """Handle /less command - view full last output in system pager."""
    content = ctx.last_full_output
    if not content:
        # Fallback to last assistant message in history
        for msg in reversed(ctx.output_history):
            if msg["role"] in ("assistant", "system"):
                content = msg["content"]
                break

    if not content:
        return "[yellow]No output to display.[/yellow]"

    # Use styles=False to strip ANSI escape codes before piping to pager.
    # Rich's 24-bit RGB codes (ESC[38;2;r;g;b) garble in most pagers.
    with console.pager(styles=False):
        console.print(Markdown(content))
    return ""


def _slash_tokens(ctx: ChatContext, args: list) -> str:
    """Handle /tokens command - show token usage with per-agent breakdown and cost."""
    if args and args[0] == "reset":
        ctx.reset_tokens()
        return "[green]Token counters reset.[/green]"

    return f"[bold]Token Usage (this session)[/bold]\n\n{ctx.token_usage.format_detailed()}"


# ============================================================================
# Additional Slash Commands - Workflows & Tools
# ============================================================================


def _slash_workflow(ctx: ChatContext, args: list) -> str:
    """Handle /workflow commands - multi-step pipelines."""
    if not args:
        return """[bold]Available Workflows:[/bold]

  /workflow full-scan       Full infrastructure scan + detect + report
  /workflow daily           Daily operations: scan → detect → analyze → report
  /workflow incident <id>   Incident response: analyze anomaly → RCA → notify
  /workflow health          System health check across all accounts

Usage: /workflow <name> [options]"""

    workflow_name = args[0].lower()

    if workflow_name in ["full-scan", "fullscan"]:
        (ctx.detail_level == "detailed") and console.print("[dim]Starting full-scan workflow...[/dim]")
        results = []
        results.append(_slash_scan(ctx, []))
        results.append(_slash_detect(ctx, []))
        return "\n\n".join(results) + "\n\n[green]Full-scan workflow complete.[/green]"

    elif workflow_name == "daily":
        results = []
        results.append("[bold]Step 1/3: Scanning resources...[/bold]")
        results.append(_slash_scan(ctx, []))
        results.append("\n[bold]Step 2/3: Running detection...[/bold]")
        results.append(_slash_detect(ctx, []))
        results.append("\n[bold]Step 3/3: Generating report...[/bold]")
        # Generate report summary
        init_db()
        session = get_session()
        try:
            issue_count = session.query(HealthIssue).filter_by(status="open").count()
            resource_count = session.query(CloudResource).count()
            results.append(f"  Resources: {resource_count}, Open issues: {issue_count}")
        finally:
            session.close()
        return "\n".join(results) + "\n\n[green]Daily workflow complete.[/green]"

    elif workflow_name == "incident" and len(args) > 1:
        try:
            issue_id = int(args[1])
        except ValueError:
            return "[red]Usage: /workflow incident <issue_id>[/red]"

        results = []
        results.append(f"[bold]Incident Response for Issue #{issue_id}[/bold]\n")
        results.append("[bold]Step 1/3: Fetching issue details...[/bold]")
        results.append(_slash_issue(ctx, ["show", str(issue_id)]))
        results.append("\n[bold]Step 2/3: Analyzing issue...[/bold]")
        results.append(_slash_analyze(ctx, [str(issue_id)]))
        results.append("\n[bold]Step 3/3: Incident documented.[/bold]")
        return "\n".join(results)

    elif workflow_name == "health":
        init_db()
        session = get_session()
        try:
            accounts = session.query(CloudAccount).filter_by(is_enabled=True).count()
            resources = session.query(CloudResource).count()
            open_issues = session.query(HealthIssue).filter_by(status="open").count()
            critical = session.query(HealthIssue).filter_by(status="open", severity="critical").count()
            high = session.query(HealthIssue).filter_by(status="open", severity="high").count()

            status = "[green]HEALTHY[/green]" if critical == 0 else "[red]CRITICAL[/red]" if critical > 0 else "[yellow]WARNING[/yellow]"

            return f"""[bold]System Health Check[/bold]

  Status: {status}

  [cyan]Infrastructure:[/cyan]
    Active Accounts: {accounts}
    Total Resources: {resources}

  [cyan]Health Issues:[/cyan]
    Open: {open_issues}
    Critical: [red]{critical}[/red]
    High: [orange1]{high}[/orange1]
"""
        finally:
            session.close()

    return f"[yellow]Unknown workflow: {workflow_name}[/yellow]"


def _slash_context(ctx: ChatContext, args: list) -> str:
    """Handle /context commands - manage conversation context."""
    if not args:
        return f"""[bold]Current Context:[/bold]
  Account: {ctx.account or 'default'}
  Output Format: {ctx.output_format}
  Detail Level: {ctx.detail_level}

Usage:
  /context account <name>   Switch account context
  /context reset            Reset to defaults"""

    cmd = args[0].lower()

    if cmd == "account" and len(args) > 1:
        acc = get_account(args[1])
        if acc:
            ctx.account = args[1]
            return f"[green]Context switched to account: {args[1]}[/green]"
        return f"[red]Account '{args[1]}' not found.[/red]"

    elif cmd == "reset":
        ctx.account = None
        ctx.output_format = "table"
        ctx.detail_level = "medium"
        return "[green]Context reset to defaults.[/green]"

    return "[yellow]Usage: /context [account <name> | reset][/yellow]"


def _slash_session(ctx: ChatContext, args: list) -> str:
    """Handle /session commands - DB-backed session management with local JSON backward compat."""
    from pathlib import Path
    from agenticops.models import ChatSession, ChatMessage, get_db_session
    from agenticops.web.session_manager import _load_history_messages
    from agenticops.config import settings
    from sqlalchemy import func

    cmd = args[0].lower() if args else "list"

    # ------------------------------------------------------------------
    # /session list — query DB for ChatSession list
    # ------------------------------------------------------------------
    if cmd == "list":
        try:
            init_db()
            with get_db_session() as db:
                sessions = (
                    db.query(ChatSession)
                    .filter(ChatSession.archived == False)
                    .order_by(
                        ChatSession.pinned.desc(),
                        ChatSession.starred.desc(),
                        ChatSession.last_activity_at.desc(),
                    )
                    .limit(20)
                    .all()
                )
                if not sessions:
                    return "[yellow]No sessions found.[/yellow]"

                lines = ["[bold]Chat Sessions:[/bold]\n"]
                for s in sessions:
                    msg_count = db.query(func.count(ChatMessage.id)).filter(
                        ChatMessage.session_id == s.id
                    ).scalar()
                    icons = ""
                    if s.pinned:
                        icons += "📌"
                    if s.starred:
                        icons += "⭐"
                    activity = s.last_activity_at.strftime("%Y-%m-%d %H:%M") if s.last_activity_at else "-"
                    current = " [green](current)[/green]" if ctx.db_session_id == s.id else ""
                    lines.append(
                        f"  {icons:3s} [cyan]{s.id:>4}[/cyan]  {s.name[:30]:<30s}  "
                        f"[dim]{msg_count:>3} msgs[/dim]  {activity}{current}"
                    )
                return "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to list DB sessions: %s", e)
            return f"[red]Error listing sessions: {e}[/red]"

    # ------------------------------------------------------------------
    # /session resume [id|name] — switch to a DB session
    # ------------------------------------------------------------------
    if cmd == "resume":
        try:
            init_db()
            with get_db_session() as db:
                if len(args) > 1:
                    identifier = args[1]
                    # Try by DB id first, then UUID, then name
                    row = None
                    try:
                        row = db.query(ChatSession).filter(ChatSession.id == int(identifier)).first()
                    except (ValueError, TypeError):
                        pass
                    if row is None:
                        row = db.query(ChatSession).filter(
                            ChatSession.session_id == identifier
                        ).first()
                    if row is None:
                        row = db.query(ChatSession).filter(
                            ChatSession.name.ilike(f"%{identifier}%")
                        ).first()
                    if row is None:
                        return f"[red]Session '{identifier}' not found.[/red]"
                else:
                    # No argument: most recent non-archived session
                    row = (
                        db.query(ChatSession)
                        .filter(ChatSession.archived == False)
                        .order_by(ChatSession.last_activity_at.desc())
                        .first()
                    )
                    if row is None:
                        return "[yellow]No active sessions to resume.[/yellow]"

                ctx.db_session_id = row.id
                ctx.db_session_uuid = row.session_id
                msg_count = db.query(func.count(ChatMessage.id)).filter(
                    ChatMessage.session_id == row.id
                ).scalar()
                session_name = row.name
                session_uuid = row.session_id

            # Load history and inject into agent
            history = _load_history_messages(session_uuid, settings.session_history_depth)
            if ctx.agent is not None and history:
                ctx.agent.messages.clear()
                ctx.agent.messages.extend(history)

            return f"[green]Resumed session: {session_name} ({msg_count} messages)[/green]"
        except Exception as e:
            logger.warning("Failed to resume session: %s", e)
            return f"[red]Error resuming session: {e}[/red]"

    # ------------------------------------------------------------------
    # /session rename <id> <name> — update session name in DB
    # ------------------------------------------------------------------
    if cmd == "rename":
        if len(args) < 3:
            return "[yellow]Usage: /session rename <id> <new_name>[/yellow]"
        identifier = args[1]
        new_name = " ".join(args[2:])
        try:
            init_db()
            with get_db_session() as db:
                row = None
                try:
                    row = db.query(ChatSession).filter(ChatSession.id == int(identifier)).first()
                except (ValueError, TypeError):
                    pass
                if row is None:
                    row = db.query(ChatSession).filter(
                        ChatSession.session_id == identifier
                    ).first()
                if row is None:
                    return f"[red]Session '{identifier}' not found.[/red]"
                old_name = row.name
                row.name = new_name
            return f"[green]Renamed session: '{old_name}' → '{new_name}'[/green]"
        except Exception as e:
            logger.warning("Failed to rename session: %s", e)
            return f"[red]Error renaming session: {e}[/red]"

    # ------------------------------------------------------------------
    # /session pin <id> — toggle pinned status
    # ------------------------------------------------------------------
    if cmd == "pin":
        if len(args) < 2:
            return "[yellow]Usage: /session pin <id>[/yellow]"
        return _session_toggle_field(args[1], "pinned")

    # ------------------------------------------------------------------
    # /session star <id> — toggle starred status
    # ------------------------------------------------------------------
    if cmd == "star":
        if len(args) < 2:
            return "[yellow]Usage: /session star <id>[/yellow]"
        return _session_toggle_field(args[1], "starred")

    # ------------------------------------------------------------------
    # /session archive <id> — toggle archived status
    # ------------------------------------------------------------------
    if cmd == "archive":
        if len(args) < 2:
            return "[yellow]Usage: /session archive <id>[/yellow]"
        return _session_toggle_field(args[1], "archived")

    # ------------------------------------------------------------------
    # /session save [name] — backward compat: save context to local JSON
    # ------------------------------------------------------------------
    if cmd == "save":
        session_dir = Path.home() / ".aiops" / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        name = args[1] if len(args) > 1 else datetime.now().strftime("%Y%m%d_%H%M%S")
        session_file = session_dir / f"{name}.json"
        session_data = {
            "account": ctx.account,
            "output_format": ctx.output_format,
            "detail_level": ctx.detail_level,
            "saved_at": datetime.now().isoformat(),
        }
        session_file.write_text(json.dumps(session_data, indent=2))
        return f"[green]Session saved: {name}[/green]"

    # ------------------------------------------------------------------
    # /session load <name> — backward compat: load context from local JSON
    # ------------------------------------------------------------------
    if cmd == "load" and len(args) > 1:
        session_dir = Path.home() / ".aiops" / "sessions"
        name = args[1]
        session_file = session_dir / f"{name}.json"
        if not session_file.exists():
            return f"[red]Session '{name}' not found.[/red]"
        data = json.loads(session_file.read_text())
        ctx.account = data.get("account")
        ctx.output_format = data.get("output_format", "table")
        ctx.detail_level = data.get("detail_level", "medium")
        return f"[green]Session loaded: {name}[/green]"

    # ------------------------------------------------------------------
    # /session delete <name> — backward compat: delete local JSON
    # ------------------------------------------------------------------
    if cmd == "delete" and len(args) > 1:
        session_dir = Path.home() / ".aiops" / "sessions"
        name = args[1]
        session_file = session_dir / f"{name}.json"
        if session_file.exists():
            session_file.unlink()
            return f"[green]Session deleted: {name}[/green]"
        return f"[red]Session '{name}' not found.[/red]"

    return (
        "[yellow]Usage: /session [list | resume [id|name] | rename <id> <name> | "
        "pin <id> | star <id> | archive <id> | save [name] | load <name> | delete <name>][/yellow]"
    )


def _session_toggle_field(identifier: str, field: str) -> str:
    """Toggle a boolean field (pinned/starred/archived) on a ChatSession."""
    from agenticops.models import ChatSession, get_db_session

    try:
        init_db()
        with get_db_session() as db:
            row = None
            try:
                row = db.query(ChatSession).filter(ChatSession.id == int(identifier)).first()
            except (ValueError, TypeError):
                pass
            if row is None:
                row = db.query(ChatSession).filter(
                    ChatSession.session_id == identifier
                ).first()
            if row is None:
                return f"[red]Session '{identifier}' not found.[/red]"

            current = getattr(row, field)
            setattr(row, field, not current)
            new_val = not current
            session_name = row.name

        icon = {"pinned": "📌", "starred": "⭐", "archived": "📦"}.get(field, "")
        state = "on" if new_val else "off"
        return f"[green]{icon} {field.capitalize()} {state}: {session_name}[/green]"
    except Exception as e:
        logger.warning("Failed to toggle %s: %s", field, e)
        return f"[red]Error toggling {field}: {e}[/red]"


def _slash_status(ctx: ChatContext, args: list) -> str:
    """Handle /status command - quick system status."""
    init_db()
    session = get_session()

    try:
        accounts = session.query(CloudAccount).filter_by(is_enabled=True).count()
        resources = session.query(CloudResource).count()
        open_issues = session.query(HealthIssue).filter_by(status="open").count()
        investigating_issues = session.query(HealthIssue).filter_by(status="investigating").count()

        # Get recent activity
        recent_issues = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc()).limit(3).all()

        severity_colors = {"critical": "red", "high": "orange1", "medium": "yellow", "low": "blue"}

        lines = [
            "[bold]AgenticOps Status[/bold]",
            "",
            f"  Accounts: {accounts} active",
            f"  Resources: {resources} tracked",
            f"  Issues: [red]{open_issues} open[/red], [yellow]{investigating_issues} investigating[/yellow]",
        ]

        if recent_issues:
            lines.append("\n  [bold]Recent Issues:[/bold]")
            for a in recent_issues:
                color = severity_colors.get(a.severity, "white")
                lines.append(f"    [{color}]#{a.id}[/] {a.title[:35]}...")

        return "\n".join(lines)
    finally:
        session.close()


def _slash_history(ctx: ChatContext, args: list) -> str:
    """Handle /history command - show command history."""
    # This would ideally be stored in context, simplified version
    return """[bold]Recent Commands:[/bold]
  (Command history tracking not yet implemented)

Tip: Use up/down arrows to navigate command history in terminal."""


def _slash_alias(ctx: ChatContext, args: list) -> str:
    """Handle /alias command - show command aliases."""
    return """[bold]Command Aliases:[/bold]

  /h, /?          → /help
  /accounts       → /account list
  /resources      → /resource list
  /issues         → /issue list
  /anomalies      → /issue list  (backward compat)
  /reports        → /report list
  /ack <id>       → /acknowledge <id>
  /rca <id>       → /analyze <id>
  /cls            → /clear
  /q, /quit       → /exit

  [dim]Use full command or alias interchangeably.[/dim]"""


def _slash_schedule(ctx: ChatContext, args: list) -> str:
    """Handle /schedule commands."""
    from agenticops.scheduler import Scheduler

    if not args or args[0] == "list":
        init_db()
        schedules = Scheduler.list_schedules()

        if not schedules:
            return "[yellow]No schedules configured.[/yellow]"

        lines = ["[bold]Schedules:[/bold]"]
        for s in schedules:
            status = "[green]ON[/green]" if s.is_enabled else "[red]OFF[/red]"
            next_run = s.next_run_at.strftime("%m-%d %H:%M") if s.next_run_at else "-"
            lines.append(f"  {s.name}: {s.pipeline_name} ({s.cron_expression}) {status} → {next_run}")
        return "\n".join(lines)

    cmd = args[0].lower()

    if cmd == "run" and len(args) > 1:
        name = args[1]
        execution = Scheduler.run_now(name)
        if execution:
            if execution.status == "completed":
                return f"[green]Schedule '{name}' executed successfully.[/green]"
            else:
                return f"[red]Schedule '{name}' failed: {execution.error}[/red]"
        return f"[red]Schedule '{name}' not found.[/red]"

    elif cmd in ["enable", "on"] and len(args) > 1:
        if Scheduler.enable_schedule(args[1]):
            return f"[green]Schedule '{args[1]}' enabled.[/green]"
        return f"[red]Schedule '{args[1]}' not found.[/red]"

    elif cmd in ["disable", "off"] and len(args) > 1:
        if Scheduler.disable_schedule(args[1]):
            return f"[yellow]Schedule '{args[1]}' disabled.[/yellow]"
        return f"[red]Schedule '{args[1]}' not found.[/red]"

    return "[yellow]Usage: /schedule [list | run <name> | enable <name> | disable <name>][/yellow]"


def _slash_run(ctx: ChatContext, args: list) -> str:
    """Handle /run command — execute a one-shot task immediately via Agent."""
    if not args:
        return "[yellow]Usage: /run <task description>[/yellow]\nExample: /run check all S3 buckets for public access"

    # Send as a message to the Agent, which will call run_task tool
    task_desc = " ".join(args)
    return f"__agent__:Execute this task immediately: {task_desc}"


def _slash_notify(ctx: ChatContext, args: list) -> str:
    """Handle /notify commands."""
    import asyncio
    from agenticops.notify import NotificationManager

    if not args:
        return """[bold]Notification Commands:[/bold]

  /notify test [channel]    Test notification channel
  /notify list              List notification channels
  /notify send <message>    Send a notification

Usage: /notify <command> [options]"""

    cmd = args[0].lower()

    if cmd == "list":
        channels = NotificationManager.list_channels()
        if not channels:
            return "[yellow]No notification channels configured.[/yellow]"

        lines = ["[bold]Notification Channels:[/bold]"]
        for c in channels:
            status = "[green]ON[/green]" if c.is_enabled else "[red]OFF[/red]"
            lines.append(f"  {c.name} ({c.channel_type}) {status}")
        return "\n".join(lines)

    elif cmd == "test":
        channel_name = args[1] if len(args) > 1 else None
        manager = NotificationManager()
        results = asyncio.run(manager.send_notification(
            subject="Test Notification",
            body="This is a test notification from AgenticOps.",
            channel_names=[channel_name] if channel_name else None,
        ))

        if not results:
            return "[yellow]No channels to test.[/yellow]"

        lines = ["[bold]Notification Test Results:[/bold]"]
        for ch, success in results.items():
            status = "[green]OK[/green]" if success else "[red]FAILED[/red]"
            lines.append(f"  {ch}: {status}")
        return "\n".join(lines)

    elif cmd == "send" and len(args) > 1:
        message = " ".join(args[1:])
        manager = NotificationManager()
        results = asyncio.run(manager.send_notification(
            subject="AgenticOps Alert",
            body=message,
        ))

        if results:
            sent = sum(1 for v in results.values() if v)
            return f"[green]Notification sent to {sent} channel(s).[/green]"
        return "[yellow]No channels available.[/yellow]"

    return "[yellow]Usage: /notify [list | test [channel] | send <message>][/yellow]"


def _slash_channel(ctx: ChatContext, args: list) -> str:
    """Handle /channel commands."""
    from agenticops.chat.channel import execute_channel

    # Reconstruct the full command for the shared processor
    cmd = "/channel " + " ".join(args) if args else "/channel"
    result = execute_channel(cmd)

    if result.success:
        return f"[green]{result.message}[/green]"
    return f"[yellow]{result.message}[/yellow]"


def _slash_skill(ctx: ChatContext, args: list) -> str:
    """Handle /skill commands for skill management."""
    if not args:
        return """[bold]Skill Commands:[/bold]

  /skill list                         List all skills (published + draft)
  /skill show <name>                  Show full skill detail
  /skill search <query>               Search local + registry skills
  /skill create                       Interactive skill creator
  /skill create <name> <description>  Create a draft skill from description
  /skill review <name>                Review a draft skill
  /skill promote <name>               Promote draft to published
  /skill reject <name>                Delete a draft skill"""

    sub = args[0].lower()

    if sub == "list":
        from agenticops.skills.loader import discover_skills
        skills = discover_skills()
        if not skills:
            return "[yellow]No skills found.[/yellow]"
        lines = [f"[bold]Skills ({len(skills)}):[/bold]"]
        for s in skills:
            tag = " [magenta][DRAFT][/magenta]" if s.is_draft else ""
            lines.append(f"  {s.name}{tag} — {s.description[:80]}")
        return "\n".join(lines)

    elif sub == "show":
        if len(args) < 2:
            return "[yellow]Usage: /skill show <name>[/yellow]"
        skill_name = args[1]
        from agenticops.skills.loader import discover_skills, load_skill_body
        skills = discover_skills()
        skill = None
        for s in skills:
            if s.name == skill_name:
                skill = s
                break
        if not skill:
            return f"[yellow]Skill '{skill_name}' not found[/yellow]"
        body = load_skill_body(skill_name) or "(empty)"
        refs_dir = skill.path / "references"
        refs = [f.name for f in sorted(refs_dir.glob("*.md"))] if refs_dir.is_dir() else []
        tag = " [magenta][DRAFT][/magenta]" if skill.is_draft else " [green][Published][/green]"
        lines = [
            f"[bold]{skill.name}[/bold]{tag}",
            f"  {skill.description}",
        ]
        if skill.tools:
            lines.append(f"  Tools: {', '.join(t.rsplit('.', 1)[-1] for t in skill.tools)}")
        if refs:
            lines.append(f"  References: {', '.join(refs)}")
        if skill.metadata:
            domain = skill.metadata.get("domain", "")
            if domain:
                lines.append(f"  Domain: {domain}")
        lines.append("")
        lines.append(body[:3000])
        if len(body) > 3000:
            lines.append("\n[dim]... truncated (use WebUI for full view)[/dim]")
        return "\n".join(lines)

    elif sub == "search":
        if len(args) < 2:
            return "[yellow]Usage: /skill search <query>[/yellow]"
        query = " ".join(args[1:])
        from agenticops.skills.registry import search_skills
        results = search_skills(query)
        if not results:
            return f"[yellow]No skills found matching '{query}'[/yellow]"
        lines = [f"[bold]Search results for '{query}':[/bold]"]
        for r in results:
            source = r.get("source", "local")
            lines.append(f"  {r['name']} [{source}] — {r.get('description', '')[:80]}")
        return "\n".join(lines)

    elif sub == "create":
        if len(args) < 3:
            # Interactive mode
            from rich.prompt import Prompt, Confirm
            from rich.console import Console
            console = Console()
            console.print("\n[bold]Interactive Skill Creator[/bold]\n")
            name = Prompt.ask("  Skill name", default="").strip()
            if not name:
                return "[yellow]Cancelled — no name provided.[/yellow]"
            description = Prompt.ask("  Description", default="").strip()
            if not description:
                return "[yellow]Cancelled — no description provided.[/yellow]"
            console.print("  [dim]Generating skill via LLM...[/dim]")
            from agenticops.skills.evolution import generate_skill_from_description, create_draft_skill
            result = generate_skill_from_description(description)
            if "error" in result:
                return f"[red]Generation failed: {result['error']}[/red]"
            content = result.get("content", "")
            preview = content[:1500]
            console.print(f"\n[bold]Preview:[/bold]\n")
            console.print(f"  Name: {result.get('name', name)}")
            console.print(f"  Description: {result.get('description', description)}")
            console.print(f"  Content ({len(content)} chars):\n")
            for line in preview.split("\n")[:30]:
                console.print(f"    {line}")
            if len(content) > 1500:
                console.print("    [dim]... (truncated)[/dim]")
            console.print()
            action = Prompt.ask("  Action", choices=["save", "regenerate", "cancel"], default="save")
            if action == "cancel":
                return "[yellow]Cancelled.[/yellow]"
            if action == "regenerate":
                console.print("  [dim]Regenerating...[/dim]")
                result = generate_skill_from_description(description)
                if "error" in result:
                    return f"[red]Regeneration failed: {result['error']}[/red]"
                content = result.get("content", "")
                if not Confirm.ask("  Save this version?", default=True):
                    return "[yellow]Cancelled.[/yellow]"
            path = create_draft_skill(
                name=result.get("name", name),
                description=result.get("description", description),
                content=result.get("content", ""),
                references=result.get("references"),
            )
            return f"[green]Draft skill created at {path}[/green]"
        name = args[1]
        description = " ".join(args[2:])
        from agenticops.skills.evolution import generate_skill_from_description, create_draft_skill
        result = generate_skill_from_description(description)
        if "error" in result:
            return f"[red]Generation failed: {result['error']}[/red]"
        path = create_draft_skill(
            name=result.get("name", name),
            description=result.get("description", description),
            content=result.get("content", ""),
            references=result.get("references"),
        )
        return f"[green]Draft skill created at {path}[/green]"

    elif sub == "review":
        if len(args) < 2:
            return "[yellow]Usage: /skill review <name>[/yellow]"
        from agenticops.skills.review import review_draft_skill
        info = review_draft_skill(args[1])
        if info is None:
            return f"[yellow]Draft skill '{args[1]}' not found[/yellow]"
        lines = [f"[bold]Draft Review: {info['name']}[/bold]"]
        lines.append(f"  {info['diff_summary']}")
        lines.append(f"  New skill: {'yes' if info['is_new'] else 'no (has published version)'}")
        lines.append(f"\n  Use /skill promote {args[1]} to publish, or /skill reject {args[1]} to delete.")
        return "\n".join(lines)

    elif sub == "promote":
        if len(args) < 2:
            return "[yellow]Usage: /skill promote <name>[/yellow]"
        from agenticops.skills.review import promote_skill
        if promote_skill(args[1]):
            return f"[green]Skill '{args[1]}' promoted to published.[/green]"
        return f"[red]Draft skill '{args[1]}' not found.[/red]"

    elif sub == "reject":
        if len(args) < 2:
            return "[yellow]Usage: /skill reject <name>[/yellow]"
        from agenticops.skills.review import reject_draft_skill
        if reject_draft_skill(args[1]):
            return f"[green]Draft skill '{args[1]}' deleted.[/green]"
        return f"[red]Draft skill '{args[1]}' not found.[/red]"

    else:
        return f"[yellow]Unknown subcommand '{sub}'. Use /skill for help.[/yellow]"


def _slash_export(ctx: ChatContext, args: list) -> str:
    """Handle /export command - quick data export."""
    if not args:
        return """[bold]Export Commands:[/bold]

  /export resources [--type TYPE]    Export resources
  /export issues [--status ST]       Export health issues
  /export accounts                   Export accounts

Options:
  --json    Output as JSON (default)
  --csv     Output as CSV"""

    entity = args[0].lower()
    fmt = "json"
    if "--csv" in args:
        fmt = "csv"

    init_db()
    session = get_session()

    try:
        if entity == "resources":
            resources = session.query(CloudResource).limit(100).all()
            data = [{"type": r.resource_type, "id": r.resource_id, "name": r.name,
                    "region": r.region, "status": r.status} for r in resources]
        elif entity in ("issues", "anomalies"):
            items = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc()).limit(100).all()
            data = [{"id": a.id, "severity": a.severity, "title": a.title, "source": a.source,
                    "status": a.status} for a in items]
        elif entity == "accounts":
            accounts = session.query(CloudAccount).all()
            data = [{"name": a.name, "provider": a.provider, "account_id": (a.credentials or {}).get("account_id", ""), "regions": a.regions} for a in accounts]
        else:
            return f"[red]Unknown entity: {entity}. Use: resources, issues, accounts[/red]"

        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        else:
            if data:
                from io import StringIO
                buffer = StringIO()
                writer = csv.DictWriter(buffer, fieldnames=data[0].keys())
                writer.writeheader()
                for row in data:
                    flat = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
                    writer.writerow(flat)
                return buffer.getvalue()
            return ""
    finally:
        session.close()


def _slash_arch(ctx: ChatContext, args: list) -> str:
    """Handle /arch command - show system architecture."""
    init_db()
    session = get_session()

    try:
        # Gather stats
        accounts = session.query(CloudAccount).count()
        active_list = session.query(CloudAccount).filter_by(is_enabled=True).all()
        active_names = ", ".join(a.name for a in active_list) if active_list else "none"
        resources = session.query(CloudResource).count()
        anomalies = session.query(HealthIssue).filter_by(status="open").count()

        fmt = args[0] if args else "tree"

        if fmt == "tree":
            return f"""[bold blue]AgenticAIOps Architecture[/bold blue]

[cyan]Core Modules[/cyan]
  ├── [green]scan[/green]     - AWS Resource Discovery (15 services)
  ├── [green]monitor[/green]  - CloudWatch Metrics & Logs
  ├── [green]detect[/green]   - Anomaly Detection (Z-Score, IQR, Rules)
  ├── [green]analyze[/green]  - Root Cause Analysis (Bedrock Claude)
  ├── [green]report[/green]   - Report Generation
  └── [green]agent[/green]    - AI Agent (13 tools)

[cyan]Automation[/cyan]
  ├── [yellow]pipeline[/yellow]  - Workflow Orchestration
  ├── [yellow]scheduler[/yellow] - Cron-based Scheduling
  └── [yellow]notify[/yellow]    - Multi-channel Notifications

[cyan]Security[/cyan]
  ├── [magenta]auth[/magenta]     - User Authentication & API Keys
  └── [magenta]audit[/magenta]    - Audit Logging

[cyan]Interfaces[/cyan]
  ├── [blue]cli[/blue]      - kubectl-style (33 slash commands)
  └── [blue]web[/blue]      - REST API (30+ endpoints) & Dashboard

[cyan]Current State[/cyan]
  ├── Accounts:  {accounts} ({active_names} enabled)
  ├── Resources: {resources}
  └── Anomalies: {anomalies} open"""

        elif fmt == "md" or fmt == "markdown":
            return f"""## AgenticAIOps Architecture

| Module | Category | Description |
|--------|----------|-------------|
| scan | Core | AWS Resource Discovery |
| monitor | Core | CloudWatch Metrics & Logs |
| detect | Core | Anomaly Detection |
| analyze | Core | Root Cause Analysis |
| report | Core | Report Generation |
| agent | Core | AI Agent (13 tools) |
| pipeline | Automation | Workflow Orchestration |
| scheduler | Automation | Cron Scheduling |
| notify | Automation | Notifications |
| auth | Security | Authentication |
| audit | Security | Audit Logging |

**State:** {accounts} accounts, {resources} resources, {anomalies} open anomalies"""

        else:
            return "[yellow]Usage: /arch [tree|md][/yellow]"
    finally:
        session.close()


def _slash_send_to(ctx: ChatContext, args: list) -> str:
    """Handle /send_to command — push content to notification channels or IM groups."""
    command = "/send_to " + " ".join(args)
    from agenticops.chat.send_to import execute_send_to
    result = execute_send_to(command)
    if result.success:
        return f"[green]{result.message}[/green]"
    else:
        return f"[yellow]{result.message}[/yellow]"


# Map of slash commands to handlers
SLASH_COMMANDS = {
    # Help & Info
    "help": _slash_help,
    "h": _slash_help,
    "?": _slash_help,
    "status": _slash_status,
    "arch": _slash_arch,
    "architecture": _slash_arch,
    "alias": _slash_alias,
    "history": _slash_history,

    # Resources
    "account": _slash_account,
    "accounts": _slash_account,
    "resource": _slash_resource,
    "resources": _slash_resource,
    "issue": _slash_issue,
    "issues": _slash_issue,
    "anomaly": _slash_issue,       # backward-compatible alias
    "anomalies": _slash_issue,     # backward-compatible alias
    "report": _slash_report,
    "reports": _slash_report,

    # Operations
    "scan": _slash_scan,
    "detect": _slash_detect,
    "analyze": _slash_analyze,
    "rca": _slash_analyze,

    # Issue management
    "acknowledge": _slash_acknowledge,
    "ack": _slash_acknowledge,
    "resolve": _slash_resolve,

    # Fix plans
    "fix": _slash_fix,
    "fixplan": _slash_fix,
    "fixplans": _slash_fix,
    "approve": _slash_approve,
    "execute": _slash_execute,
    "exec": _slash_execute,

    # Workflows
    "workflow": _slash_workflow,
    "wf": _slash_workflow,

    # Session & Context
    "context": _slash_context,
    "ctx": _slash_context,
    "session": _slash_session,

    # Automation
    "schedule": _slash_schedule,
    "run": _slash_run,
    "notify": _slash_notify,

    # Send to channels/IM
    "send_to": _slash_send_to,
    "sendto": _slash_send_to,

    # Channel management
    "channel": _slash_channel,
    "channels": _slash_channel,

    # Skills
    "skill": _slash_skill,
    "skills": _slash_skill,

    # Export
    "export": _slash_export,

    # UI
    "output": _slash_output,
    "format": _slash_output,
    "style": _slash_style,
    "table-style": _slash_style,
    "clear": _slash_clear,
    "cls": _slash_clear,

    # Scroll & Pager
    "scroll": _slash_scroll,
    "scrollback": _slash_scroll,
    "pager": _slash_pager,
    "less": _slash_less,
    "more": _slash_less,

    # Token usage
    "tokens": _slash_tokens,
    "usage": _slash_tokens,

    # Detail level (handled inline in handle_slash_command, but listed for /alias)
}


def handle_slash_command(ctx: ChatContext, command: str) -> Optional[str]:
    """Parse and execute a slash command. Returns response or None if not a command."""
    if not command.startswith("/"):
        return None

    parts = command[1:].split()
    if not parts:
        return None

    cmd = parts[0].lower()
    args = parts[1:]

    # Check for exit commands
    if cmd in ["exit", "quit", "q"]:
        return "__EXIT__"

    # Detail level command
    if cmd in ("detail", "verbosity", "verbose"):
        from agenticops.config import VALID_DETAIL_LEVELS
        if args:
            level = args[0].lower()
            if ctx.set_detail(level):
                return f"[green]Detail level set to: {level}[/green]"
            return f"[yellow]Invalid level '{level}'. Use: {', '.join(VALID_DETAIL_LEVELS)}[/yellow]"
        # No args — cycle: concise → medium → detailed → concise
        levels = list(VALID_DETAIL_LEVELS)
        idx = (levels.index(ctx.detail_level) + 1) % len(levels)
        ctx.set_detail(levels[idx])
        return f"[green]Detail level: {ctx.detail_level}[/green]"

    # Scan focus command
    if cmd in ("focus", "scan_focus"):
        from agenticops.config import VALID_SCAN_FOCUS
        if args:
            focus = args[0].lower()
            if ctx.set_scan_focus(focus):
                return f"[green]Scan focus set to: {ctx.scan_focus}[/green]"
            return f"[yellow]Invalid focus '{focus}'. Use: {', '.join(VALID_SCAN_FOCUS)}[/yellow]"
        return f"[cyan]Current scan focus: {ctx.scan_focus}[/cyan]\n  Options: {', '.join(VALID_SCAN_FOCUS)}\n  Combine: /focus computing,security"

    # Model switching command
    if cmd == "model":
        from agenticops.cli.context import MODEL_ALIASES
        from agenticops.config import AGENT_NAMES, get_agent_model_config, save_to_yaml
        if args:
            # /model reset — reset all agents to YAML defaults
            if args[0].lower() == "reset":
                ctx.reset_agent_models()
                save_to_yaml({f"agent_{n}_model_id": "" for n in AGENT_NAMES}
                             | {f"agent_{n}_max_tokens": 0 for n in AGENT_NAMES})
                return "[green]All agent models reset to tier defaults (saved).[/green]"
            # /model <agent> <alias> — set per-agent model and persist
            if len(args) >= 2 and args[0].lower() in AGENT_NAMES:
                agent_name = args[0].lower()
                alias = args[1].lower()
                if ctx.set_agent_model(agent_name, alias):
                    save_to_yaml({f"agent_{agent_name}_model_id": MODEL_ALIASES[alias]})
                    return f"[green]{agent_name} → {MODEL_ALIASES[alias]} (saved)[/green]"
                valid = ", ".join(MODEL_ALIASES.keys())
                return f"[yellow]Invalid model '{alias}'. Use: {valid}[/yellow]"
            # /model <alias> — switch main agent and persist
            alias = args[0].lower()
            if ctx.set_model(alias):
                save_to_yaml({"agent_main_model_id": MODEL_ALIASES[alias]})
                return f"[green]main → {MODEL_ALIASES[alias]} (saved)[/green]"
            valid = ", ".join(f"{k} ({v})" for k, v in MODEL_ALIASES.items())
            return f"[yellow]Invalid model '{alias}'. Use:[/yellow]\n  {valid}"
        # No args — show all agents with resolved models + available models
        lines = []
        for name in AGENT_NAMES:
            model_id, max_tokens = get_agent_model_config(name)
            is_override = bool(getattr(settings, f"agent_{name}_model_id", ""))
            marker = " *" if is_override else ""
            # Shorten model_id for display
            short = model_id.split(".")[-1] if "." in model_id else model_id
            lines.append(f"  {name:10s} {short}{marker}")
        # Resolve actual main agent model for header
        main_model_id, _ = get_agent_model_config("main")
        main_short = main_model_id.split(".")[-1] if "." in main_model_id else main_model_id
        header = f"[cyan]Main agent: {main_short}[/cyan]"
        table = "\n".join(lines)
        aliases = "|".join(MODEL_ALIASES.keys())

        # Show available models from dynamic service
        try:
            from agenticops.services.model_service import get_model_presets
            presets = get_model_presets()
            model_lines = [f"  {p['label']:25s} {p['value']}" for p in presets[:12]]
            available = "\n".join(model_lines)
            available_section = f"\n\n[cyan]Available models ({len(presets)}):[/cyan]\n{available}"
        except Exception:
            available_section = ""

        return (
            f"{header}\n\n[cyan]All agents:[/cyan]\n{table}{available_section}\n\n"
            f"  /model <{aliases}>          Switch main agent\n"
            f"  /model <agent> <{aliases}>  Switch specific agent\n"
            f"  /model reset                        Clear all overrides\n"
            f"  (* = per-agent override active)"
        )

    handler = SLASH_COMMANDS.get(cmd)
    if handler:
        try:
            return handler(ctx, args)
        except Exception as e:
            return f"[red]Error: {e}[/red]"

    return f"[yellow]Unknown command: /{cmd}. Type /help for available commands.[/yellow]"


@app.command()
def manage(
    resource_id: str = typer.Argument(..., help="AWS resource ID (e.g., i-1234567890abcdef0)"),
    region: Optional[str] = typer.Option(None, "-r", "--region", help="Region filter if resource_id is ambiguous"),
):
    """Opt a resource into agent monitoring (managed=True)."""
    init_db()
    session = get_session()
    try:
        query = session.query(CloudResource).filter_by(resource_id=resource_id)
        if region:
            query = query.filter_by(region=region)
        resource = query.first()
        if not resource:
            console.print(f"[red]Resource '{resource_id}' not found in inventory.[/red]")
            raise typer.Exit(1)
        if resource.managed:
            console.print(f"[yellow]Resource '{resource_id}' is already managed.[/yellow]")
            return
        resource.managed = True
        session.commit()
        console.print(f"[green]Resource '{resource_id}' ({resource.resource_type}/{resource.region}) is now managed.[/green]")
    finally:
        session.close()


@app.command()
def unmanage(
    resource_id: str = typer.Argument(..., help="AWS resource ID (e.g., i-1234567890abcdef0)"),
    region: Optional[str] = typer.Option(None, "-r", "--region", help="Region filter if resource_id is ambiguous"),
):
    """Opt a resource out of agent monitoring (managed=False)."""
    init_db()
    session = get_session()
    try:
        query = session.query(CloudResource).filter_by(resource_id=resource_id)
        if region:
            query = query.filter_by(region=region)
        resource = query.first()
        if not resource:
            console.print(f"[red]Resource '{resource_id}' not found in inventory.[/red]")
            raise typer.Exit(1)
        if not resource.managed:
            console.print(f"[yellow]Resource '{resource_id}' is already unmanaged.[/yellow]")
            return
        resource.managed = False
        session.commit()
        console.print(f"[green]Resource '{resource_id}' ({resource.resource_type}/{resource.region}) is now unmanaged.[/green]")
    finally:
        session.close()


@app.command()
def issues(
    severity: Optional[str] = typer.Option(None, "-s", "--severity", help="Filter by severity: critical, high, medium, low"),
    status: Optional[str] = typer.Option("open", "--status", help="Filter by status: open, investigating, resolved"),
    limit: int = typer.Option(50, "-l", "--limit", help="Max results"),
):
    """List health issues detected by the Detect Agent."""
    from agenticops.models import HealthIssue

    init_db()
    session = get_session()

    try:
        query = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc())
        if severity:
            query = query.filter_by(severity=severity.lower())
        if status:
            query = query.filter_by(status=status.lower())

        total = query.count()
        items = query.limit(limit).all()

        if not items:
            console.print("[yellow]No health issues found.[/yellow]")
            return

        table = create_table(
            title=f"Health Issues ({len(items)} of {total})",
            columns=[
                {"name": "ID", "style": "dim"},
                {"name": "SEVERITY", "style": "bold"},
                {"name": "SOURCE"},
                {"name": "TITLE"},
                {"name": "RESOURCE"},
                {"name": "STATUS"},
                {"name": "DETECTED"},
            ],
        )

        severity_colors = {
            "critical": "red bold",
            "high": "red",
            "medium": "yellow",
            "low": "blue",
        }

        for item in items:
            color = severity_colors.get(item.severity, "white")
            table.add_row(
                str(item.id),
                f"[{color}]{item.severity.upper()}[/{color}]",
                item.source,
                item.title[:60],
                item.resource_id[:30],
                item.status,
                item.detected_at.strftime("%Y-%m-%d %H:%M") if item.detected_at else "",
            )

        console.print(table)
    finally:
        session.close()


@app.command()
def issue(
    issue_id: int = typer.Argument(..., help="Health issue ID"),
):
    """Show details of a specific health issue."""
    from agenticops.models import HealthIssue

    init_db()
    session = get_session()

    try:
        item = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not item:
            console.print(f"[red]Health issue #{issue_id} not found.[/red]")
            raise typer.Exit(1)

        severity_colors = {
            "critical": "red bold",
            "high": "red",
            "medium": "yellow",
            "low": "blue",
        }
        color = severity_colors.get(item.severity, "white")

        panel_content = (
            f"[bold]Title:[/bold] {item.title}\n"
            f"[bold]Severity:[/bold] [{color}]{item.severity.upper()}[/{color}]\n"
            f"[bold]Source:[/bold] {item.source}\n"
            f"[bold]Resource:[/bold] {item.resource_id}\n"
            f"[bold]Status:[/bold] {item.status}\n"
            f"[bold]Detected:[/bold] {item.detected_at}\n"
            f"[bold]Detected by:[/bold] {item.detected_by}\n"
        )
        if item.alarm_name:
            panel_content += f"[bold]Alarm:[/bold] {item.alarm_name}\n"
        if item.resolved_at:
            panel_content += f"[bold]Resolved:[/bold] {item.resolved_at}\n"

        panel_content += f"\n[bold]Description:[/bold]\n{item.description}\n"

        if item.metric_data:
            panel_content += f"\n[bold]Metric Data:[/bold]\n{json.dumps(item.metric_data, indent=2)}\n"
        if item.related_changes:
            panel_content += f"\n[bold]Related Changes:[/bold]\n{json.dumps(item.related_changes, indent=2)}\n"

        console.print(Panel(
            panel_content,
            title=f"Health Issue #{item.id}",
            border_style=color.split()[0] if color else "white",
        ))
    finally:
        session.close()


def _run_headless(query: str, account: Optional[str] = None):
    """Execute a single agent query and print the result. No REPL."""
    import sys
    from rich.markdown import Markdown

    init_db()

    from agenticops.agents import create_main_agent
    from agenticops.chat.preprocessor import preprocess_message

    agent = create_main_agent()
    enriched, warnings = preprocess_message(query, resolve_file_refs=True)

    # Set trace_id for this headless invocation
    from agenticops.config import generate_trace_id, set_trace_id
    from agenticops.services.agent_log_service import track_agent
    set_trace_id(generate_trace_id())

    is_tty = sys.stdout.isatty()

    if is_tty:
        for w in warnings:
            console.print(f"[yellow]Warning: {w}[/yellow]")
        if isinstance(enriched, list):
            media_count = sum(1 for b in enriched if "image" in b or "document" in b)
            if media_count:
                console.print(f"[dim]Attached {media_count} media file(s) for analysis[/dim]")
        display = ThinkingDisplay(console)
        with display.live_display():
            display.start("Thinking...")
            try:
                with track_agent("main", "chat_headless", query[:200],
                                actor_type="cli", actor_id=__import__("getpass").getuser()) as tracker:
                    result = agent(enriched)
                    tracker.set_result(result)
                display.complete("Done")
            except Exception as e:
                display.error(str(e))
                raise typer.Exit(1)

        response = str(result)
        console.print()
        if response.startswith("#") or "```" in response:
            console.print(Markdown(response))
        else:
            console.print(response)

        # Token summary
        from agenticops.agents.metrics import extract_token_usage
        _u = extract_token_usage(result)
        inp, out = _u["input"], _u["output"]
        if inp or out:
            console.print(f"\n[dim]Tokens: ↑{inp} ↓{out} Σ{inp + out}[/dim]")
    else:
        # Piped output: plain text, no Rich formatting
        for w in warnings:
            print(f"Warning: {w}", file=sys.stderr)
        try:
            with track_agent("main", "chat_headless", query[:200],
                            actor_type="cli", actor_id=__import__("getpass").getuser()) as tracker:
                result = agent(enriched)
                tracker.set_result(result)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            raise typer.Exit(1)
        print(str(result))


def _cli_persist_message(
    ctx: ChatContext,
    role: str,
    content: str,
    tool_calls: Optional[list] = None,
    token_usage: Optional[dict] = None,
) -> None:
    """Persist a chat message to the DB, shared with Web Dashboard.

    Silently skips when ``ctx.db_session_id`` is None (non-DB mode).
    On DB write failure, logs a warning and degrades gracefully — the chat
    continues without persistence.
    """
    if ctx.db_session_id is None:
        return
    try:
        from agenticops.models import ChatSession, ChatMessage, get_db_session
        from datetime import datetime as _dt, timezone as _tz

        with get_db_session() as db:
            db.add(ChatMessage(
                session_id=ctx.db_session_id,
                role=role,
                content=content,
                tool_calls=tool_calls if tool_calls else None,
                token_usage=token_usage if token_usage else None,
            ))
            # Update session last_activity_at so Web Dashboard sees fresh activity
            row = db.query(ChatSession).filter(
                ChatSession.id == ctx.db_session_id
            ).first()
            if row:
                row.last_activity_at = _dt.now(_tz.utc)
    except Exception:
        logger.warning(
            "Failed to persist %s message to DB for session %s — "
            "continuing in non-persistent mode",
            role,
            ctx.db_session_id,
            exc_info=True,
        )


def _persist_slash_interaction(ctx: ChatContext, command: str, result: str) -> None:
    """Persist a slash command and its textual result to DB (parity with agent turns)."""
    _cli_persist_message(ctx, "user", command)
    if result:
        _cli_persist_message(ctx, "system", result)


def _cli_setup_db_session(
    ctx: ChatContext,
    agent,
    console: Console,
    resume: bool,
    session_id: Optional[str],
) -> None:
    """Create a new DB ChatSession or resume an existing one.

    Sets ``ctx.db_session_id`` and ``ctx.db_session_uuid``.  When resuming,
    loads history messages and injects them into the agent.
    """
    import uuid as _uuid
    from agenticops.models import ChatSession, ChatMessage, get_db_session
    from agenticops.web.session_manager import _load_history_messages
    from sqlalchemy import func

    if session_id:
        # --session <id>: resume a specific session by UUID or DB id
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row is None:
                # Try matching by DB integer id
                try:
                    row = db.query(ChatSession).filter(ChatSession.id == int(session_id)).first()
                except (ValueError, TypeError):
                    pass
            if row is None:
                console.print(f"[red]Session '{session_id}' not found.[/red]")
                # List recent sessions as a hint
                recent = (
                    db.query(ChatSession)
                    .filter(ChatSession.archived == False)
                    .order_by(ChatSession.last_activity_at.desc())
                    .limit(5)
                    .all()
                )
                if recent:
                    console.print("[yellow]Recent sessions:[/yellow]")
                    for s in recent:
                        cnt = db.query(func.count(ChatMessage.id)).filter(
                            ChatMessage.session_id == s.id
                        ).scalar()
                        console.print(
                            f"  {s.session_id}  {s.name}  ({cnt} msgs)  "
                            f"{s.last_activity_at.strftime('%Y-%m-%d %H:%M')}"
                        )
                raise typer.Exit(1)

            ctx.db_session_id = row.id
            ctx.db_session_uuid = row.session_id
            msg_count = db.query(func.count(ChatMessage.id)).filter(
                ChatMessage.session_id == row.id
            ).scalar()
            session_name = row.name

        # Load history and inject into agent
        history = _load_history_messages(ctx.db_session_uuid, settings.session_history_depth)
        if history:
            agent.messages.extend(history)
        console.print(
            f"[green]Resumed session: {session_name} ({msg_count} messages)[/green]"
        )

    elif resume:
        # --resume: find the most recent non-archived session
        with get_db_session() as db:
            row = (
                db.query(ChatSession)
                .filter(ChatSession.archived == False)
                .order_by(ChatSession.last_activity_at.desc())
                .first()
            )
            if row is None:
                # No existing session — create a new one
                console.print(
                    "[yellow]No active sessions found. Creating a new session.[/yellow]"
                )
                sid = str(_uuid.uuid4())
                from datetime import datetime as _dt, timezone as _tz
                row = ChatSession(
                    session_id=sid,
                    name=f"CLI Chat {_dt.now(_tz.utc).strftime('%Y-%m-%d %H:%M')}",
                )
                db.add(row)
                db.flush()
                ctx.db_session_id = row.id
                ctx.db_session_uuid = row.session_id
                return

            ctx.db_session_id = row.id
            ctx.db_session_uuid = row.session_id
            msg_count = db.query(func.count(ChatMessage.id)).filter(
                ChatMessage.session_id == row.id
            ).scalar()
            session_name = row.name

        # Load history and inject into agent
        history = _load_history_messages(ctx.db_session_uuid, settings.session_history_depth)
        if history:
            agent.messages.extend(history)
        console.print(
            f"[green]Resumed session: {session_name} ({msg_count} messages)[/green]"
        )

    else:
        # Default: create a new DB session
        sid = str(_uuid.uuid4())
        from datetime import datetime as _dt, timezone as _tz
        with get_db_session() as db:
            row = ChatSession(
                session_id=sid,
                name=f"CLI Chat {_dt.now(_tz.utc).strftime('%Y-%m-%d %H:%M')}",
            )
            db.add(row)
            db.flush()
            ctx.db_session_id = row.id
            ctx.db_session_uuid = row.session_id


@app.command()
def chat(
    query: Optional[str] = typer.Argument(None, help="Single query (headless mode)"),
    query_flag: Optional[str] = typer.Option(None, "--query", "-q", help="Query string (headless mode)"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account name"),
    detail: Optional[str] = typer.Option(None, "--detail", "-d", help="Output detail level: concise, medium, detailed"),
    focus: Optional[str] = typer.Option(None, "--focus", "-f", help="Resource focus: computing,networking,databases,storage,security,billing,all"),
    debug: bool = typer.Option(False, "--debug", help="Show debug logs (default: clean streaming output only)"),
    resume: bool = typer.Option(False, "--resume", help="Resume the most recently active non-archived session"),
    session_id: Optional[str] = typer.Option(None, "--session", help="Resume a specific session by ID (UUID or DB id)"),
):
    """Start an interactive chat, or run a single query in headless mode.

    Examples:
      aiops chat                              # interactive REPL
      aiops chat --resume                     # resume last active session
      aiops chat --session <id>               # resume specific session
      aiops chat "check health of prod"       # single query, exit
      aiops chat -q "scan us-east-1"          # explicit flag
      echo "list issues" | aiops chat         # pipe mode
      aiops chat "analyze I#42 and check R#17"
      aiops chat "review this log @/tmp/error.log"
      aiops chat -d concise "quick status"    # concise output
      aiops chat -f security "scan my account"  # security-only scan
    """
    import sys
    from agenticops.config import VALID_DETAIL_LEVELS, set_detail_level
    from agenticops.config import VALID_SCAN_FOCUS, set_scan_focus

    # Suppress log noise by default — only show WARNING+
    # With --debug, show INFO level for troubleshooting
    if not debug:
        logging.getLogger().setLevel(logging.WARNING)
        # Silence noisy libraries entirely
        for noisy in ("botocore", "urllib3", "strands", "httpcore", "httpx"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    else:
        logging.getLogger().setLevel(logging.DEBUG)

    # Apply detail level if specified
    if detail:
        if detail not in VALID_DETAIL_LEVELS:
            console.print(f"[red]Invalid detail level '{detail}'. Use: {', '.join(VALID_DETAIL_LEVELS)}[/red]")
            raise typer.Exit(1)
        set_detail_level(detail)

    # Apply scan focus if specified
    if focus:
        parts = [p.strip().lower() for p in focus.split(",") if p.strip()]
        invalid = [p for p in parts if p not in VALID_SCAN_FOCUS]
        if invalid:
            console.print(f"[red]Invalid scan focus '{','.join(invalid)}'. Use: {', '.join(VALID_SCAN_FOCUS)}[/red]")
            raise typer.Exit(1)
        set_scan_focus(focus)

    # Determine headless input
    headless_input = query or query_flag or None
    if not headless_input and not sys.stdin.isatty():
        headless_input = sys.stdin.read().strip()

    if headless_input:
        _run_headless(headless_input, account)
        return

    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.styles import Style
    from pathlib import Path

    from agenticops.agents import create_main_agent
    from agenticops.cli.display import StreamingCallbackHandler

    # Start agent creation in background while showing welcome message
    _agent_container: dict = {}
    _agent_error: list = []

    def _init_agent():
        try:
            _agent_container["agent"] = create_main_agent()
        except Exception as e:
            _agent_error.append(e)

    _agent_thread = threading.Thread(target=_init_agent, daemon=True)
    _agent_thread.start()

    # Initialize chat context (agent will be set after thread completes)
    ctx = ChatContext()
    ctx.account = account
    if focus:
        ctx.scan_focus = focus.lower()

    # Detect initial model alias from settings
    from agenticops.cli.context import MODEL_ALIASES
    for alias, model_id in MODEL_ALIASES.items():
        if settings.bedrock_model_id == model_id:
            ctx.current_model = alias
            break

    # Setup history file
    history_dir = Path.home() / ".aiops"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "chat_history"

    # Slash command completer
    slash_commands = [
        "/help", "/status", "/alias", "/clear",
        "/account", "/resource", "/issue", "/issues", "/report",
        "/scan", "/detect", "/analyze", "/ack", "/resolve",
        "/workflow", "/schedule", "/notify", "/channel",
        "/session", "/context", "/export", "/output",
        "/detail", "/model", "/exit", "/quit",
    ]
    completer = WordCompleter(slash_commands, ignore_case=True)

    # Prompt style
    prompt_style = Style.from_dict({
        'prompt': 'cyan bold',
    })

    # Create prompt session with history and completion
    session = PromptSession(
        history=FileHistory(str(history_file)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
        complete_while_typing=False,
        style=prompt_style,
        enable_history_search=True,  # Ctrl+R for reverse search
        mouse_support=False,
    )

    # Welcome message
    console.print(Panel(
        "[bold]AgenticAIOps Chat[/bold] — [dim]Strands Multi-Agent[/dim]\n\n"
        "Chat with your AI operations assistant using natural language.\n"
        "Examples: [cyan]\"scan my EC2 instances\"[/cyan], [cyan]\"check health of my resources\"[/cyan], [cyan]\"list issues\"[/cyan]\n\n"
        "[dim]Shortcuts:[/dim]  ↑/↓ History  |  Tab Complete  |  Ctrl+R Search  |  Ctrl+C Exit\n"
        "[dim]Scroll:[/dim]     Terminal native  |  /less full output  |  /scroll history\n"
        "[dim]Tokens:[/dim]     Displayed after each response (↑input ↓output Σtotal)\n",
        title="Welcome",
        border_style="blue",
    ))

    # Wait for background agent init to complete before first prompt
    _agent_thread.join()
    if _agent_error:
        console.print(f"[red]Failed to initialize agent: {_agent_error[0]}[/red]")
        raise typer.Exit(1)
    agent = _agent_container["agent"]
    ctx.agent = agent  # Enable /model to swap model at runtime

    # --- DB Session: create new or resume existing ---
    init_db()
    _cli_setup_db_session(ctx, agent, console, resume, session_id)

    while True:
        try:
            # Use prompt_toolkit for input
            user_input = session.prompt(
                [('class:prompt', '❯ ')],
                default='',
            ).strip()

            if user_input.lower() in ["exit", "quit", "q"]:
                console.print("[yellow]Goodbye![/yellow]")
                break

            if not user_input:
                continue

            # Check for slash commands
            if user_input.startswith("/"):
                ctx.add_to_history("user", user_input)
                result = handle_slash_command(ctx, user_input)
                if result == "__EXIT__":
                    console.print("[yellow]Goodbye![/yellow]")
                    break
                if result and result.startswith("__agent__:"):
                    # Forward to agent as user input
                    user_input = result[len("__agent__:"):]
                elif result:
                    ctx.add_to_history("system", result)
                    _persist_slash_interaction(ctx, user_input, result)
                    print_with_truncation(console, result, ctx, header="System")
                    continue
                else:
                    continue

            # Store user input in history
            ctx.add_to_history("user", user_input)

            # Persist user message to DB (shared with Web Dashboard)
            _cli_persist_message(ctx, "user", user_input)

            # Preprocess message: resolve I#/R# references, @file/path attachments
            from agenticops.chat.preprocessor import preprocess_message
            enriched_input, preprocess_warnings = preprocess_message(
                user_input, resolve_file_refs=True,
            )
            for w in preprocess_warnings:
                console.print(f"[yellow]Warning: {w}[/yellow]")
            if isinstance(enriched_input, list):
                media_count = sum(1 for b in enriched_input if "image" in b or "document" in b)
                if media_count:
                    console.print(f"[dim]Attached {media_count} media file(s) for analysis[/dim]")

            # Set detail level and scan focus from context before each agent call
            from agenticops.config import set_detail_level as _set_dl, set_scan_focus as _set_sf
            _set_dl(ctx.detail_level)
            _set_sf(ctx.scan_focus)

            # Set trace_id for this REPL turn
            from agenticops.config import generate_trace_id as _gen_tid, set_trace_id as _set_tid
            _set_tid(_gen_tid())

            # Call agent with streaming output + animated spinner
            try:
                handler = StreamingCallbackHandler(console)
                agent.callback_handler = handler
                handler.start()
                try:
                    from agenticops.services.agent_log_service import track_agent as _track
                    with _track("main", "chat", user_input[:200],
                                actor_type="cli", actor_id=__import__("getpass").getuser()) as _trk:
                        result = agent(enriched_input)
                        _trk.set_result(result)
                except Exception as e:
                    handler.stop()
                    console.print(f"[red]Error: {str(e)}[/red]")
                    response = f"Error: {str(e)}"
                    ctx.add_to_history("assistant", response)
                    continue
                response = str(result)

                # Extract token usage from Strands metrics (main + sub-agents)
                from agenticops.agents.metrics import extract_token_usage
                _u = extract_token_usage(result)
                if any(_u.values()):
                    ctx.add_tokens(
                        input_tokens=_u["input"],
                        output_tokens=_u["output"],
                        cache_read=_u["cache_read"],
                        cache_write=_u["cache_write"],
                    )

            except Exception as e:
                console.print(f"[red]Error: {str(e)}[/red]")
                response = f"Error: {str(e)}"

            # Store response in history
            ctx.add_to_history("assistant", response)

            # Persist assistant response to DB (shared with Web Dashboard)
            _u2 = extract_token_usage(result)
            _token_usage_dict = {"input": _u2["input"], "output": _u2["output"]} if any(_u2.values()) else None
            _cli_persist_message(ctx, "assistant", response, token_usage=_token_usage_dict)

            # Show session token summary in status bar
            from agenticops.config import get_agent_model_config
            _main_mid, _ = get_agent_model_config("main")
            _main_short = _main_mid.split(".")[-1] if "." in _main_mid else _main_mid
            console.print(f"[dim]─── {_main_short} | {ctx.get_token_summary()} | Requests: {ctx.token_usage.requests} ───[/dim]", justify="right")

            # Show clickable reference links for I#N / R#N
            from agenticops.cli.display import format_reference_links
            ref_links = format_reference_links(response, settings.web_base_url)
            if ref_links:
                console.print(f"\n[dim]{ref_links}[/dim]")

        except KeyboardInterrupt:
            # NOTE: agent() runs synchronously, so an in-flight Bedrock call cannot
            # be hard-cancelled here — we stop the spinner and let the call finish.
            # True cancellation would require an async stream refactor (out of scope).
            if hasattr(agent, 'callback_handler') and hasattr(agent.callback_handler, 'stop'):
                agent.callback_handler.stop()
            console.print("\n[yellow]Stopping display. Press Ctrl+C again to exit, or continue typing.[/yellow]")
            try:
                session.prompt([('class:prompt', '❯ ')], default='')
            except KeyboardInterrupt:
                console.print("\n[yellow]Session ended.[/yellow]")
                break
        except EOFError:
            console.print("\n[yellow]Session ended.[/yellow]")
            break


# ============================================================================
# Service Management (aiops service start|stop|status|restart|logs)
# ============================================================================

_SERVICE_PID_FILE = settings.data_dir / "service.pid"
_FRONTEND_PID_FILE = settings.data_dir / "frontend.pid"
_SERVICE_LOG_DIR = settings.data_dir.parent / "logs"
_SERVICE_LOG_FILE = _SERVICE_LOG_DIR / "backend.log"  # default log for service start
_FRONTEND_DIR = Path(__file__).parent.parent / "web" / "frontend"


def _read_pid() -> Optional[int]:
    """Read PID from file. Returns None if missing or stale."""
    import signal
    if not _SERVICE_PID_FILE.exists():
        return None
    try:
        pid = int(_SERVICE_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check if alive
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        _SERVICE_PID_FILE.unlink(missing_ok=True)
        return None


def _write_pid(pid: int) -> None:
    _SERVICE_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SERVICE_PID_FILE.write_text(str(pid))


def _start_backend(host: str, port: int) -> int:
    """Spawn uvicorn as a detached background process. Returns PID."""
    import subprocess

    _SERVICE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_fd = open(_SERVICE_LOG_FILE, "a")

    cmd = [
        sys.executable, "-m", "uvicorn",
        "agenticops.web.app:app",
        "--host", host,
        "--port", str(port),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True,
    )
    _write_pid(proc.pid)
    return proc.pid


def _start_frontend_dev(backend_port: int) -> int:
    """Spawn vite dev server as a detached background process. Returns PID."""
    import subprocess

    _SERVICE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_fd = open(_SERVICE_LOG_DIR / "frontend.log", "a")

    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--clearScreen", "false"],
        cwd=str(_FRONTEND_DIR),
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True,
        env={**os.environ, "VITE_API_TARGET": f"http://127.0.0.1:{backend_port}"},
    )
    _FRONTEND_PID_FILE.write_text(str(proc.pid))
    return proc.pid


def _read_frontend_pid() -> Optional[int]:
    """Read frontend dev PID. Returns None if missing or stale."""
    if not _FRONTEND_PID_FILE.exists():
        return None
    try:
        pid = int(_FRONTEND_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        _FRONTEND_PID_FILE.unlink(missing_ok=True)
        return None


def _stop_frontend() -> None:
    """Stop the frontend dev server if running."""
    import signal
    pid = _read_frontend_pid()
    if not pid:
        return
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGINT)
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except ProcessLookupError:
        pass
    _FRONTEND_PID_FILE.unlink(missing_ok=True)


@service_app.command("start")
def service_start(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Host to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind"),
    daemon: bool = typer.Option(True, "--daemon/--foreground", help="Run as background daemon (default) or foreground"),
    frontend: bool = typer.Option(False, "--frontend", help="Also start Vite dev server (hot-reload, port 5173)"),
):
    """Start web dashboard + IM WebSocket services.

    Modes:
      --daemon (default)  Backend runs as background daemon
      --foreground        Backend runs in foreground (blocking)
      --frontend          Also start Vite dev server for frontend hot-reload
    """
    existing = _read_pid()
    if existing:
        console.print(f"[yellow]Service already running (PID {existing}).[/yellow]")
        console.print("Use [bold]aiops service stop[/bold] first, or [bold]aiops service restart[/bold].")
        raise typer.Exit(1)

    if not daemon:
        # Foreground mode — blocking
        from agenticops.web.app import run_server

        if frontend:
            fe_pid = _start_frontend_dev(port)
            console.print(f"[bold green]Frontend dev server started (PID {fe_pid})[/bold green]")
            console.print(f"  Vite dev      : http://localhost:5173/app/")

        _write_pid(os.getpid())
        console.print(f"[bold green]Starting AgenticOps services (foreground)...[/bold green]")
        _print_service_info(host, port, frontend=frontend)
        try:
            run_server(host=host, port=port)
        finally:
            _SERVICE_PID_FILE.unlink(missing_ok=True)
            if frontend:
                _stop_frontend()
        return

    # Daemon mode — spawn background processes
    be_pid = _start_backend(host, port)

    console.print(f"[bold green]AgenticOps services started (PID {be_pid})[/bold green]")

    if frontend:
        fe_pid = _start_frontend_dev(port)
        console.print(f"[bold green]Frontend dev server started (PID {fe_pid})[/bold green]")

    _print_service_info(host, port, frontend=frontend)


def _print_service_info(host: str, port: int, *, frontend: bool = False) -> None:
    """Print service startup summary."""
    # Auto-detect IM WS from channels.yaml (same logic as app.py startup)
    try:
        from agenticops.notify.im_config import load_channels
        _channels = load_channels()
        _feishu_active = any(c.channel_type == "feishu" and c.is_enabled for c in _channels) or settings.feishu_ws_enabled
        _slack_active = any(c.channel_type == "slack" and c.is_enabled for c in _channels) or settings.slack_ws_enabled
    except Exception:
        _feishu_active = settings.feishu_ws_enabled
        _slack_active = settings.slack_ws_enabled

    console.print(f"  Backend API   : http://{host}:{port}")
    if frontend:
        console.print(f"  Vite dev      : http://localhost:5173/app/  (hot-reload)")
    else:
        console.print(f"  Web dashboard : http://{host}:{port}/app/")
    console.print(f"  Feishu WS     : {'enabled' if _feishu_active else 'disabled'}")
    console.print(f"  Slack WS      : {'enabled' if _slack_active else 'disabled'}")
    console.print(f"  PID file      : {_SERVICE_PID_FILE}")
    console.print(f"  Logs:")
    console.print(f"    backend.log   : {_SERVICE_LOG_DIR / 'backend.log'}")
    console.print(f"    frontend.log  : {_SERVICE_LOG_DIR / 'frontend.log'}")
    if _feishu_active:
        console.print(f"    feishu_ws.log : {_SERVICE_LOG_DIR / 'feishu_ws.log'}")
    if _slack_active:
        console.print(f"    slack_ws.log  : {_SERVICE_LOG_DIR / 'slack_ws.log'}")


@service_app.command("stop")
def service_stop():
    """Stop running services (backend + frontend dev if running)."""
    import signal

    # Stop frontend dev server first
    fe_pid = _read_frontend_pid()
    if fe_pid:
        console.print(f"Stopping frontend dev server (PID {fe_pid})...")
        _stop_frontend()
        console.print("[green]Frontend dev server stopped.[/green]")

    pid = _read_pid()
    if not pid:
        if not fe_pid:
            console.print("[yellow]No running service found.[/yellow]")
        return

    console.print(f"Stopping backend service (PID {pid})...")
    try:
        pgid = os.getpgid(pid)
        # SIGINT triggers uvicorn's graceful shutdown
        os.killpg(pgid, signal.SIGINT)
        # Wait up to 3 seconds — WS daemon threads may block longer, SIGKILL is fine
        for _ in range(30):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            console.print("[yellow]Graceful shutdown timed out, sending SIGKILL...[/yellow]")
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except ProcessLookupError:
        pass

    _SERVICE_PID_FILE.unlink(missing_ok=True)
    console.print("[green]Service stopped.[/green]")


@service_app.command("status")
def service_status():
    """Show service status."""
    import urllib.request

    pid = _read_pid()
    fe_pid = _read_frontend_pid()

    if not pid and not fe_pid:
        console.print("[dim]Service:[/dim] [red]not running[/red]")
        return

    if pid:
        console.print(f"[dim]Backend: [/dim] [green]running[/green] (PID {pid})")
    else:
        console.print(f"[dim]Backend: [/dim] [red]not running[/red]")

    if fe_pid:
        console.print(f"[dim]Frontend:[/dim] [green]running[/green] (PID {fe_pid}) → http://localhost:5173/app/")
    else:
        console.print(f"[dim]Frontend:[/dim] [dim]not started[/dim]")

    # Show log files that exist
    if _SERVICE_LOG_DIR.exists():
        log_files = sorted(f for f in _SERVICE_LOG_DIR.glob("*.log") if f.stat().st_size > 0)
        if log_files:
            console.print(f"[dim]Log dir: [/dim] {_SERVICE_LOG_DIR}")
            for lf in log_files:
                size = lf.stat().st_size
                label = f"{size / 1024:.1f}KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f}MB"
                console.print(f"  [dim]{lf.name:20s}[/dim] {label}")

    if not pid:
        return

    # Try to reach the health endpoint
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as resp:
            data = json.loads(resp.read())
            status_color = {"healthy": "green", "degraded": "yellow"}.get(data.get("status", ""), "red")
            console.print(f"[dim]Health:  [/dim] [{status_color}]{data.get('status', 'unknown')}[/{status_color}]")

            checks = data.get("checks", {})
            for name, info in checks.items():
                c = "green" if info.get("status") == "ok" else "yellow" if info.get("status") == "error" else "red"
                detail = ""
                if name == "aws" and info.get("details", {}).get("account_id"):
                    detail = f" (account: {info['details']['account_id']})"
                elif name == "disk" and info.get("details", {}).get("used_pct"):
                    detail = f" ({info['details']['used_pct']:.0f}% used, {info['details']['free_gb']:.1f}GB free)"
                console.print(f"  [dim]{name:>10}:[/dim] [{c}]{info.get('status', '?')}[/{c}]{detail}")
    except Exception:
        console.print("[dim]Health:  [/dim] [yellow]unreachable[/yellow] (service may still be starting)")


@service_app.command("restart")
def service_restart(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Host to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind"),
    frontend: bool = typer.Option(False, "--frontend", help="Also start Vite dev server"),
):
    """Restart services (stop + start)."""
    pid = _read_pid()
    fe_pid = _read_frontend_pid()
    if pid or fe_pid:
        service_stop()
        time.sleep(0.5)
    service_start(host=host, port=port, frontend=frontend)


@service_app.command("logs")
def service_logs(
    component: Optional[str] = typer.Argument(
        None,
        help="Log component: backend, frontend, feishu_ws, slack_ws (default: all)",
    ),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output (like tail -f)"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
):
    """View service logs.

    Examples:
      aiops service logs              # show recent backend logs
      aiops service logs backend -f   # follow backend log
      aiops service logs feishu_ws    # show Feishu WS logs
      aiops service logs slack_ws -f  # follow Slack WS log
      aiops service logs frontend     # show HTTP access logs
    """
    import subprocess as sp

    _LOG_MAP = {
        "backend": "backend.log",
        "frontend": "frontend.log",
        "feishu_ws": "feishu_ws.log",
        "feishu": "feishu_ws.log",
        "slack_ws": "slack_ws.log",
        "slack": "slack_ws.log",
    }

    if component and component not in _LOG_MAP:
        console.print(f"[red]Unknown component: {component}[/red]")
        console.print(f"[dim]Available: {', '.join(sorted(set(_LOG_MAP.values()), key=lambda x: x))}[/dim]")
        raise typer.Exit(1)

    # Default to backend if no component given
    log_name = _LOG_MAP.get(component, "backend.log") if component else "backend.log"
    log_file = _SERVICE_LOG_DIR / log_name

    if not log_file.exists():
        console.print(f"[yellow]Log file not found: {log_file}[/yellow]")
        # Show which logs exist
        existing = [f.name for f in _SERVICE_LOG_DIR.glob("*.log")] if _SERVICE_LOG_DIR.exists() else []
        if existing:
            console.print(f"[dim]Available logs: {', '.join(sorted(existing))}[/dim]")
        return

    if follow:
        console.print(f"[dim]Following {log_file} (Ctrl+C to stop)...[/dim]")
        try:
            sp.run(["tail", "-f", "-n", str(lines), str(log_file)])
        except KeyboardInterrupt:
            pass
    else:
        sp.run(["tail", "-n", str(lines), str(log_file)])


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Host to bind"),
    port: int = typer.Option(8080, "--port", "-p", help="Port to bind"),
):
    """Start the web dashboard (foreground). Prefer 'aiops service start'."""
    from agenticops.web.app import run_server

    console.print(f"[bold]Starting AgenticAIOps Web Dashboard...[/bold]")
    console.print(f"Open http://{host}:{port} in your browser")
    run_server(host=host, port=port)


@app.command()
def export(
    entity: str = typer.Argument(..., help="Entity: resources, issues, accounts, reports (anomalies = alias for issues)"),
    output: str = typer.Option("json", "-o", "--output", help="Format: json, csv"),
    file: Optional[str] = typer.Option(None, "-f", "--file", help="Output file path"),
    type: Optional[str] = typer.Option(None, "-t", "--type", help="Filter by type"),
    region: Optional[str] = typer.Option(None, "-r", "--region", help="Filter by region"),
    severity: Optional[str] = typer.Option(None, "-s", "--severity", help="Filter by severity"),
    limit: int = typer.Option(1000, "-l", "--limit", help="Max records"),
):
    """Export data to JSON or CSV."""
    init_db()
    session = get_session()

    try:
        if entity == "resources":
            query = session.query(CloudResource)
            if type:
                query = query.filter_by(resource_type=type)
            if region:
                query = query.filter_by(region=region)
            records = query.limit(limit).all()
            data = [{"id": r.id, "resource_id": r.resource_id, "type": r.resource_type,
                    "name": r.name, "region": r.region, "status": r.status} for r in records]

        elif entity in ("issues", "anomalies"):
            query = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc())
            if severity:
                query = query.filter_by(severity=severity)
            records = query.limit(limit).all()
            data = [{"id": a.id, "title": a.title, "severity": a.severity, "status": a.status,
                    "resource": a.resource_id, "source": a.source,
                    "detected_at": a.detected_at.isoformat()} for a in records]

        elif entity == "accounts":
            records = session.query(CloudAccount).limit(limit).all()
            data = [{"name": a.name, "provider": a.provider,
                    "account_id": (a.credentials or {}).get("account_id", ""),
                    "regions": a.regions, "is_enabled": a.is_enabled} for a in records]

        elif entity == "reports":
            records = session.query(Report).order_by(Report.created_at.desc()).limit(limit).all()
            data = [{"id": r.id, "type": r.report_type, "title": r.title,
                    "created_at": r.created_at.isoformat()} for r in records]
        else:
            console.print(f"[red]Unknown entity: {entity}. Use: resources, issues, accounts, reports[/red]")
            raise typer.Exit(1)

        if output == "json":
            output_str = json.dumps(data, indent=2, default=str)
        elif output == "csv":
            if data:
                buffer = StringIO()
                writer = csv.DictWriter(buffer, fieldnames=data[0].keys())
                writer.writeheader()
                for row in data:
                    flat_row = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
                    writer.writerow(flat_row)
                output_str = buffer.getvalue()
            else:
                output_str = ""
        else:
            console.print(f"[red]Unknown format: {output}[/red]")
            raise typer.Exit(1)

        if file:
            from pathlib import Path
            Path(file).write_text(output_str)
            console.print(f"[green]Exported {len(data)} {entity} to {file}[/green]")
        else:
            console.print(output_str)

    finally:
        session.close()


@app.command()
def version():
    """Show version information."""
    console.print(f"[bold]AgenticAIOps[/bold] v{__version__}")


@app.command()
def arch(
    output: str = typer.Option("tree", "-o", "--output", help="Output format: tree, markdown, json"),
):
    """Show system architecture and module overview."""
    init_db()
    session = get_session()

    try:
        # Gather stats
        accounts = session.query(CloudAccount).count()
        active_accounts = session.query(CloudAccount).filter_by(is_enabled=True).all()
        active_names = ", ".join(a.name for a in active_accounts) if active_accounts else "none"
        resources = session.query(CloudResource).count()
        anomalies_open = session.query(HealthIssue).filter_by(status="open").count()
        anomalies_total = session.query(HealthIssue).count()
        reports = session.query(Report).count()

        if output == "tree":
            # Build tree view
            tree = Tree("[bold blue]AgenticAIOps[/bold blue]")

            # Core modules
            core = tree.add("[cyan]Core Modules[/cyan]")
            core.add("[green]scan[/green] - AWS Resource Discovery (15 services)")
            core.add("[green]monitor[/green] - CloudWatch Metrics & Logs")
            core.add("[green]detect[/green] - Anomaly Detection (Z-Score, IQR, Rules)")
            core.add("[green]analyze[/green] - Root Cause Analysis (Bedrock Claude)")
            core.add("[green]report[/green] - Report Generation")
            core.add("[green]agent[/green] - AI Agent (13 tools)")

            # Automation modules
            auto = tree.add("[cyan]Automation Modules[/cyan]")
            auto.add("[yellow]pipeline[/yellow] - Workflow Orchestration")
            auto.add("[yellow]scheduler[/yellow] - Cron-based Scheduling")
            auto.add("[yellow]notify[/yellow] - Multi-channel Notifications")

            # Security modules
            sec = tree.add("[cyan]Security Modules[/cyan]")
            sec.add("[magenta]auth[/magenta] - User Authentication & API Keys")
            sec.add("[magenta]audit[/magenta] - Audit Logging")

            # Interfaces
            iface = tree.add("[cyan]Interfaces[/cyan]")
            cli_node = iface.add("[blue]cli[/blue] - kubectl-style CLI")
            cli_node.add("[dim]33 slash commands in chat[/dim]")
            web_node = iface.add("[blue]web[/blue] - REST API & Dashboard")
            web_node.add("[dim]30+ API endpoints[/dim]")

            # Current state
            state = tree.add("[cyan]Current State[/cyan]")
            state.add(f"Accounts: {accounts} ({active_names} enabled)")
            state.add(f"Resources: {resources}")
            state.add(f"Anomalies: {anomalies_open} open / {anomalies_total} total")
            state.add(f"Reports: {reports}")

            console.print(tree)

        elif output == "markdown":
            md = f"""# AgenticAIOps Architecture

## Core Modules

| Module | Description |
|--------|-------------|
| scan | AWS Resource Discovery (15 services) |
| monitor | CloudWatch Metrics & Logs |
| detect | Anomaly Detection (Z-Score, IQR, Rules) |
| analyze | Root Cause Analysis (Bedrock Claude) |
| report | Report Generation |
| agent | AI Agent (13 tools) |

## Automation Modules

| Module | Description |
|--------|-------------|
| pipeline | Workflow Orchestration |
| scheduler | Cron-based Scheduling |
| notify | Multi-channel Notifications |

## Security Modules

| Module | Description |
|--------|-------------|
| auth | User Authentication & API Keys |
| audit | Audit Logging |

## Interfaces

| Interface | Description |
|-----------|-------------|
| cli | kubectl-style CLI, 33 slash commands |
| web | REST API (30+) & Dashboard |

## Current State

- **Accounts**: {accounts} ({active_account.name if active_account else 'none'} active)
- **Resources**: {resources}
- **Anomalies**: {anomalies_open} open / {anomalies_total} total
- **Reports**: {reports}
"""
            render_markdown(md)

        elif output == "json":
            data = {
                "version": __version__,
                "modules": {
                    "core": ["scan", "monitor", "detect", "analyze", "report", "agent"],
                    "automation": ["pipeline", "scheduler", "notify"],
                    "security": ["auth", "audit"],
                    "interfaces": ["cli", "web"],
                },
                "state": {
                    "accounts": accounts,
                    "active_account": active_account.name if active_account else None,
                    "resources": resources,
                    "anomalies_open": anomalies_open,
                    "anomalies_total": anomalies_total,
                    "reports": reports,
                },
            }
            render_json(data, title="AgenticAIOps Architecture")

    finally:
        session.close()


@app.command()
def test_account(name: str = typer.Argument(..., help="Account name to test")):
    """Test AWS account credentials."""
    acc = get_account(name)
    if not acc:
        console.print(f"[red]Account '{name}' not found.[/red]")
        raise typer.Exit(1)

    from agenticops.providers import get_provider

    console.print(f"[bold]Testing credentials for account '{name}'...[/bold]")

    try:
        provider = get_provider(acc)
        with console.status("Resolving credentials..."):
            success = provider.resolve_credentials()

        if success:
            console.print(f"[green]Credentials valid! Provider: {acc.provider}[/green]")
        else:
            console.print(f"[red]Credential test failed for {acc.provider} account '{name}'.[/red]")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Credential test failed: {e}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
