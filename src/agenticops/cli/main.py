"""CLI Main - kubectl-style Command Line Interface for AgenticOps."""

import json
import logging
import os
import sys
import time
import threading
from datetime import datetime, timedelta
from io import StringIO
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
    AWSAccount,
    AWSResource,
    HealthIssue,
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
# Thinking/Progress Display System (Claude Code Style)
# ============================================================================


class ThinkingState(Enum):
    """States for the thinking display."""
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    PROCESSING = "processing"
    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"


class ThinkingDisplay:
    """Claude Code-style thinking and progress display.

    Shows real-time status updates, tool calls, and thinking process.
    """

    SPINNERS = {
        ThinkingState.THINKING: "dots",
        ThinkingState.TOOL_CALL: "dots2",
        ThinkingState.PROCESSING: "dots3",
        ThinkingState.STREAMING: "dots12",
    }

    STATE_COLORS = {
        ThinkingState.THINKING: "blue",
        ThinkingState.TOOL_CALL: "yellow",
        ThinkingState.PROCESSING: "cyan",
        ThinkingState.STREAMING: "green",
        ThinkingState.COMPLETE: "green",
        ThinkingState.ERROR: "red",
    }

    STATE_ICONS = {
        ThinkingState.THINKING: "◐",
        ThinkingState.TOOL_CALL: "⚙",
        ThinkingState.PROCESSING: "⟳",
        ThinkingState.STREAMING: "▸",
        ThinkingState.COMPLETE: "✓",
        ThinkingState.ERROR: "✗",
    }

    def __init__(self, console: Console):
        self.console = console
        self.state = ThinkingState.IDLE
        self.steps: List[Dict[str, Any]] = []
        self.current_step = ""
        self.start_time = None
        self._live = None
        self._lock = threading.Lock()

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable form."""
        if seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        else:
            mins = int(seconds // 60)
            secs = seconds % 60
            return f"{mins}m{secs:.0f}s"

    def _build_display(self) -> Group:
        """Build the display content."""
        elements = []

        # Show completed steps
        for step in self.steps:
            icon = self.STATE_ICONS.get(step["state"], "•")
            color = self.STATE_COLORS.get(step["state"], "white")
            duration = step.get("duration", "")
            duration_str = f" [dim]({self._format_duration(duration)})[/dim]" if duration else ""

            # Use Text.from_markup() to parse Rich markup tags
            if step["state"] == ThinkingState.COMPLETE:
                elements.append(Text.from_markup(f"  [{color}]{icon}[/{color}] {step['text']}{duration_str}"))
            elif step["state"] == ThinkingState.ERROR:
                elements.append(Text.from_markup(f"  [{color}]{icon}[/{color}] {step['text']}"))
            else:
                elements.append(Text.from_markup(f"  [{color}]{icon}[/{color}] {step['text']}{duration_str}"))

        # Show current step with spinner
        if self.state not in (ThinkingState.IDLE, ThinkingState.COMPLETE, ThinkingState.ERROR):
            spinner_name = self.SPINNERS.get(self.state, "dots")
            color = self.STATE_COLORS.get(self.state, "blue")
            elapsed = ""
            if self.start_time:
                elapsed_secs = time.time() - self.start_time
                elapsed = f" [dim]({self._format_duration(elapsed_secs)})[/dim]"

            spinner = Spinner(spinner_name, text=Text.from_markup(f"[{color}]{self.current_step}[/{color}]{elapsed}"))
            elements.append(Text("  ") + spinner.render(time.time()))

        return Group(*elements) if elements else Text("")

    @contextmanager
    def live_display(self):
        """Context manager for live display updates."""
        with Live(self._build_display(), console=self.console, refresh_per_second=10, transient=False) as live:
            self._live = live
            try:
                yield self
            finally:
                self._live = None

    def _update(self):
        """Update the live display."""
        if self._live:
            self._live.update(self._build_display())

    def start(self, text: str = "Thinking"):
        """Start thinking display."""
        self.state = ThinkingState.THINKING
        self.current_step = text
        self.start_time = time.time()
        self.steps = []
        self._update()

    def thinking(self, text: str):
        """Update thinking status."""
        with self._lock:
            self.state = ThinkingState.THINKING
            self.current_step = text
            self._update()

    def tool_call(self, tool_name: str, args: str = ""):
        """Show tool call status."""
        with self._lock:
            # Complete previous step if any
            if self.current_step and self.state != ThinkingState.IDLE:
                self._complete_current_step()

            self.state = ThinkingState.TOOL_CALL
            args_str = f" ({args})" if args else ""
            self.current_step = f"Calling {tool_name}{args_str}"
            self.start_time = time.time()
            self._update()

    def processing(self, text: str):
        """Show processing status."""
        with self._lock:
            if self.current_step and self.state == ThinkingState.TOOL_CALL:
                self._complete_current_step()

            self.state = ThinkingState.PROCESSING
            self.current_step = text
            self.start_time = time.time()
            self._update()

    def streaming(self, text: str = "Generating response"):
        """Show streaming status."""
        with self._lock:
            if self.current_step:
                self._complete_current_step()

            self.state = ThinkingState.STREAMING
            self.current_step = text
            self.start_time = time.time()
            self._update()

    def step(self, text: str, state: ThinkingState = ThinkingState.COMPLETE):
        """Add a completed step."""
        with self._lock:
            self.steps.append({
                "text": text,
                "state": state,
                "duration": None,
            })
            self._update()

    def _complete_current_step(self):
        """Complete the current step and add to history."""
        if self.current_step:
            duration = time.time() - self.start_time if self.start_time else None
            self.steps.append({
                "text": self.current_step,
                "state": ThinkingState.COMPLETE,
                "duration": duration,
            })
            self.current_step = ""
            self.start_time = None

    def complete(self, text: str = None):
        """Mark thinking as complete."""
        with self._lock:
            if self.current_step:
                self._complete_current_step()

            if text:
                self.steps.append({
                    "text": text,
                    "state": ThinkingState.COMPLETE,
                    "duration": None,
                })

            self.state = ThinkingState.COMPLETE
            self._update()

    def error(self, text: str):
        """Show error status."""
        with self._lock:
            self.steps.append({
                "text": text,
                "state": ThinkingState.ERROR,
                "duration": None,
            })
            self.state = ThinkingState.ERROR
            self._update()


class ProgressTracker:
    """Track and display progress for multi-step operations."""

    def __init__(self, console: Console, total: int = None, description: str = "Processing"):
        self.console = console
        self.total = total
        self.description = description
        self.current = 0
        self.steps_log: List[str] = []

    @contextmanager
    def track(self):
        """Context manager for progress tracking."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task(self.description, total=self.total or 100)
            self._progress = progress
            self._task = task
            try:
                yield self
            finally:
                self._progress = None
                self._task = None

    def update(self, advance: int = 1, description: str = None):
        """Update progress."""
        if hasattr(self, '_progress') and self._progress:
            if description:
                self._progress.update(self._task, description=description)
            self._progress.advance(self._task, advance)
            self.current += advance

    def log(self, message: str):
        """Log a step message."""
        self.steps_log.append(message)
        self.console.print(f"  [dim]→[/dim] {message}")


# Global thinking display instance
thinking = ThinkingDisplay(console)


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
    """Print with pager for long content."""
    lines = content.count('\n')
    terminal_height = console.size.height

    if lines > terminal_height - 5:
        with console.pager(styles=True):
            console.print(content)
    else:
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

app.add_typer(get_app, name="get")
app.add_typer(describe_app, name="describe")
app.add_typer(create_app, name="create")
app.add_typer(delete_app, name="delete")
app.add_typer(update_app, name="update")
app.add_typer(run_app, name="run")
app.add_typer(logs_app, name="logs")


# ============================================================================
# Helper Functions
# ============================================================================


def get_account(name: str = None) -> Optional[AWSAccount]:
    """Get AWS account by name or the first active account."""
    session = get_session()
    try:
        if name:
            return session.query(AWSAccount).filter_by(name=name).first()
        return session.query(AWSAccount).filter_by(is_active=True).first()
    finally:
        session.close()


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
        query = session.query(AWSAccount)
        if not all_accounts:
            query = query.filter_by(is_active=True)
        accounts = query.all()

        if not accounts:
            console.print("[yellow]No accounts found.[/yellow]")
            return

        if output == "json":
            data = [{
                "name": a.name,
                "account_id": a.account_id,
                "regions": a.regions,
                "is_active": a.is_active,
                "last_scanned": a.last_scanned_at.isoformat() if a.last_scanned_at else None,
            } for a in accounts]
            output_json(data)
        elif output == "wide":
            output_table(
                [(a.name, a.account_id, a.role_arn, ",".join(a.regions),
                  "Active" if a.is_active else "Inactive",
                  a.last_scanned_at.strftime("%Y-%m-%d %H:%M") if a.last_scanned_at else "Never")
                 for a in accounts],
                [{"name": "NAME"}, {"name": "ACCOUNT ID"}, {"name": "ROLE ARN"},
                 {"name": "REGIONS"}, {"name": "STATUS"}, {"name": "LAST SCAN"}],
            )
        else:
            output_table(
                [(a.name, a.account_id, ",".join(a.regions[:2]) + ("..." if len(a.regions) > 2 else ""),
                  "Active" if a.is_active else "Inactive")
                 for a in accounts],
                [{"name": "NAME"}, {"name": "ACCOUNT ID"}, {"name": "REGIONS"}, {"name": "STATUS"}],
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
        query = session.query(AWSResource)
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
                "name": r.resource_name,
                "region": r.region,
                "status": r.status,
            } for r in resources]
            output_json(data)
        elif output == "wide":
            output_table(
                [(r.resource_type, r.resource_id, r.resource_name or "-", r.region,
                  r.status, r.resource_arn or "-", r.updated_at.strftime("%Y-%m-%d %H:%M"))
                 for r in resources],
                [{"name": "TYPE"}, {"name": "ID"}, {"name": "NAME"}, {"name": "REGION"},
                 {"name": "STATUS"}, {"name": "ARN"}, {"name": "UPDATED"}],
            )
        else:
            output_table(
                [(r.resource_type, r.resource_id, r.resource_name or "-", r.region, r.status)
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
        account = session.query(AWSAccount).filter_by(name=name).first()
        if not account:
            console.print(f"[red]Account '{name}' not found.[/red]")
            raise typer.Exit(1)

        data = {
            "Name": account.name,
            "Account ID": account.account_id,
            "Role ARN": account.role_arn,
            "External ID": account.external_id or "-",
            "Regions": account.regions,
            "Status": "Active" if account.is_active else "Inactive",
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
        resource = session.query(AWSResource).filter_by(resource_id=resource_id).first()
        if not resource:
            # Try by database ID
            try:
                resource = session.query(AWSResource).filter_by(id=int(resource_id)).first()
            except ValueError:
                pass

        if not resource:
            console.print(f"[red]Resource '{resource_id}' not found.[/red]")
            raise typer.Exit(1)

        data = {
            "Type": resource.resource_type,
            "ID": resource.resource_id,
            "Name": resource.resource_name or "-",
            "ARN": resource.resource_arn or "-",
            "Region": resource.region,
            "Status": resource.status,
            "Tags": resource.tags or {},
            "Metadata": resource.resource_metadata or {},
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
        existing = session.query(AWSAccount).filter_by(name=name).first()
        if existing:
            console.print(f"[red]Account '{name}' already exists.[/red]")
            raise typer.Exit(1)

        region_list = [r.strip() for r in regions.split(",")]

        # Deactivate all other accounts if activating this one
        if activate:
            session.query(AWSAccount).update({"is_active": False})

        account = AWSAccount(
            name=name,
            account_id=account_id,
            role_arn=role_arn,
            external_id=external_id,
            regions=region_list,
            is_active=activate,
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
        account = session.query(AWSAccount).filter_by(name=name).first()
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
        account = session.query(AWSAccount).filter_by(name=name).first()
        if not account:
            console.print(f"[red]Account '{name}' not found.[/red]")
            raise typer.Exit(1)

        if role_arn:
            account.role_arn = role_arn
        if external_id is not None:
            account.external_id = external_id
        if regions:
            account.regions = [r.strip() for r in regions.split(",")]
        if enable:
            # Deactivate ALL other accounts first (only one active at a time)
            session.query(AWSAccount).filter(AWSAccount.id != account.id).update({"is_active": False})
            account.is_active = True
            console.print(f"[yellow]All other accounts deactivated.[/yellow]")
        if disable:
            account.is_active = False

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
            item.resolved_at = datetime.utcnow()
            console.print(f"[green]issue/{issue_id} resolved[/green]")

        if status:
            item.status = status
            if status == "resolved":
                item.resolved_at = datetime.utcnow()
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
    """Show health issue details. RCA Agent coming in Phase 2."""
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
            f"[bold]Resource:[/bold] {item.resource_id}\n"
            f"[bold]Source:[/bold] {item.source}\n"
            f"[bold]Description:[/bold] {item.description}",
            title=f"Health Issue #{issue_id}",
        ))

        if item.metric_data:
            console.print("\n[bold]Metric Data:[/bold]")
            console.print(json.dumps(item.metric_data, indent=2))

        if item.related_changes:
            console.print("\n[bold]Related Changes:[/bold]")
            for change in item.related_changes[:5]:
                console.print(f"  - {change}")

        console.print("\n[yellow]RCA Agent coming in Phase 2. "
                      "Use 'aiops chat' and ask the agent to investigate this issue.[/yellow]")

    finally:
        session.close()


@run_app.command("report")
def run_report(
    type: str = typer.Option("daily", "--type", "-t", help="Report type: daily, inventory"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account name"),
):
    """Generate an operations report."""
    from agenticops.report import ReportGenerator

    acc = get_account(account)
    generator = ReportGenerator(acc)

    console.print(f"[bold]Generating {type} report...[/bold]")

    with console.status("Generating report..."):
        if type == "daily":
            content = generator.generate_daily_report()
        elif type == "inventory":
            content = generator.generate_inventory_report()
        else:
            console.print(f"[red]Unknown report type: {type}[/red]")
            raise typer.Exit(1)

    console.print(Panel(content[:2000] + ("..." if len(content) > 2000 else ""), title="Report Preview"))
    console.print(f"\n[green]Full report saved to: {settings.reports_dir}[/green]")


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
    start_time = datetime.utcnow() - timedelta(hours=hours)

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
def init():
    """Initialize the AgenticOps database and directories."""
    console.print("[bold blue]Initializing AgenticOps...[/bold blue]")
    settings.ensure_dirs()
    init_db()

    # Also create tables for new modules
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution
    from agenticops.notify.notifier import NotificationChannel, NotificationLog
    from agenticops.auth.models import User, APIKey, Session
    from agenticops.audit.models import AuditLog
    from agenticops.models import Base, get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)

    console.print("[green]Database initialized successfully![/green]")
    console.print(f"Data directory: {settings.data_dir.absolute()}")


# ============================================================================
# Chat Slash Commands
# ============================================================================

class ChatContext:
    """Context for chat session, holding state like output format."""

    def __init__(self):
        self.output_format = "table"  # table, json, wide
        self.table_style = os.environ.get("AIOPS_TABLE_STYLE", "default")
        self.account = None
        self.verbose = False
        self.output_history: List[Dict[str, str]] = []  # Store conversation history
        self.pager_threshold = 0  # 0 = auto (terminal height - 8)
        self.auto_pager = True  # Enable auto-truncation for long outputs
        self.last_full_output = ""  # Full output for /less when truncated
        self.token_usage = TokenUsage()  # Track token consumption

    def set_output(self, fmt: str):
        if fmt in ["table", "json", "wide", "yaml"]:
            self.output_format = fmt
            return True
        return False

    def set_table_style(self, style: str) -> bool:
        """Set table style (default, simple, minimal, double, ascii)."""
        if style in TABLE_STYLES:
            self.table_style = style
            # Also update environment for child functions
            os.environ["AIOPS_TABLE_STYLE"] = style
            return True
        return False

    def add_to_history(self, role: str, content: str):
        """Add message to output history."""
        self.output_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        # Keep last 100 messages
        if len(self.output_history) > 100:
            self.output_history = self.output_history[-100:]

    def get_history(self, count: int = 10) -> List[Dict[str, str]]:
        """Get recent history."""
        return self.output_history[-count:]

    def add_tokens(self, input_tokens: int = 0, output_tokens: int = 0):
        """Add token usage."""
        self.token_usage.add(input_tokens, output_tokens)

    def get_token_summary(self) -> str:
        """Get token usage summary."""
        return self.token_usage.format()

    def reset_tokens(self):
        """Reset token counters."""
        self.token_usage.reset()


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

  /session list             List saved sessions
  /session save [name]      Save current session state
  /session load <name>      Load a saved session
  /session delete <name>    Delete a saved session

[dim]Sessions preserve context, output format, and account selection.[/dim]"""

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

[cyan]Workflows:[/cyan]  [dim](/help workflow for details)[/dim]
  /workflow full-scan              Full infrastructure scan
  /workflow daily                  Daily operations pipeline
  /workflow incident <id>          Incident response
  /workflow health                 System health check

[cyan]Automation:[/cyan]
  /schedule list | run <name>      Manage schedules
  /notify list | test | send       Notifications

[cyan]Session & Context:[/cyan]
  /session list | save | load      Session management
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
  /verbose                         Toggle verbose mode
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
            accounts = session.query(AWSAccount).all()
            if not accounts:
                return "[yellow]No accounts found.[/yellow]"

            if ctx.output_format == "json":
                data = [{"name": a.name, "account_id": a.account_id,
                        "regions": a.regions, "is_active": a.is_active} for a in accounts]
                return json.dumps(data, indent=2)

            lines = ["[bold]AWS Accounts:[/bold] [dim](only one can be active)[/dim]"]
            for a in accounts:
                status = "[green]● Active[/green]" if a.is_active else "[dim]○ Inactive[/dim]"
                lines.append(f"  {status} {a.name}: {a.account_id}")
            return "\n".join(lines)

        elif args[0] in ["show", "describe"] and len(args) > 1:
            name = args[1]
            account = session.query(AWSAccount).filter_by(name=name).first()
            if not account:
                return f"[red]Account '{name}' not found.[/red]"

            status = "[green]Active[/green]" if account.is_active else "[red]Inactive[/red]"
            return f"""[bold]Account: {account.name}[/bold] {status}
  Account ID: {account.account_id}
  Role ARN: {account.role_arn}
  External ID: {account.external_id or '-'}
  Regions: {', '.join(account.regions)}
  Last Scanned: {account.last_scanned_at.strftime('%Y-%m-%d %H:%M') if account.last_scanned_at else 'Never'}"""

        elif args[0] in ["activate", "enable", "use"] and len(args) > 1:
            name = args[1]
            account = session.query(AWSAccount).filter_by(name=name).first()
            if not account:
                return f"[red]Account '{name}' not found.[/red]"

            if account.is_active:
                return f"[yellow]Account '{name}' is already active.[/yellow]"

            # Deactivate all other accounts first
            session.query(AWSAccount).update({"is_active": False})
            account.is_active = True
            session.commit()
            return f"[green]Account '{name}' is now active. All other accounts deactivated.[/green]"

        elif args[0] in ["deactivate", "disable"] and len(args) > 1:
            name = args[1]
            account = session.query(AWSAccount).filter_by(name=name).first()
            if not account:
                return f"[red]Account '{name}' not found.[/red]"

            if not account.is_active:
                return f"[yellow]Account '{name}' is already inactive.[/yellow]"

            account.is_active = False
            session.commit()
            return f"[yellow]Account '{name}' deactivated.[/yellow]"

        elif args[0] == "delete" and len(args) > 1:
            name = args[1]
            account = session.query(AWSAccount).filter_by(name=name).first()
            if not account:
                return f"[red]Account '{name}' not found.[/red]"

            # Check if --force flag is provided
            if "--force" not in args and "-f" not in args:
                return f"[yellow]Are you sure? Use '/account delete {name} --force' to confirm.[/yellow]"

            session.delete(account)
            session.commit()
            return f"[green]Account '{name}' deleted.[/green]"

        elif args[0] == "active":
            active = session.query(AWSAccount).filter_by(is_active=True).first()
            if active:
                return f"[green]Active account: {active.name}[/green] ({active.account_id})"
            return "[yellow]No active account. Use '/account activate <name>' to set one.[/yellow]"

        else:
            return """[bold]Account Commands:[/bold]

  /account list                 List all accounts
  /account show <name>          Show account details
  /account active               Show current active account
  /account activate <name>      Activate account (deactivates others)
  /account deactivate <name>    Deactivate account
  /account delete <name> -f     Delete account

[dim]Note: Only ONE account can be active at a time.[/dim]"""
    finally:
        session.close()


def _slash_resource(ctx: ChatContext, args: list) -> str:
    """Handle /resource commands."""
    init_db()
    session = get_session()

    try:
        if not args or args[0] == "list":
            query = session.query(AWSResource)
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
                        "name": r.resource_name, "region": r.region} for r in resources]
                return json.dumps(data, indent=2)

            lines = [f"[bold]Resources:[/bold] (showing {len(resources)} of {total}, use --limit N for more)"]
            for r in resources:
                name = r.resource_name or r.resource_id[:20]
                # Escape brackets so Rich doesn't interpret them as markup
                lines.append(f"  \\[{r.resource_type}] {name} ({r.region})")
            return "\n".join(lines)

        elif args[0] == "show" and len(args) > 1:
            resource_id = args[1]
            resource = session.query(AWSResource).filter_by(resource_id=resource_id).first()
            if not resource:
                try:
                    resource = session.query(AWSResource).filter_by(id=int(resource_id)).first()
                except ValueError:
                    pass

            if not resource:
                return f"[red]Resource '{resource_id}' not found.[/red]"

            return f"""[bold]Resource: {resource.resource_name or resource.resource_id}[/bold]
  Type: {resource.resource_type}
  ID: {resource.resource_id}
  ARN: {resource.resource_arn or '-'}
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

        lines.append(f"\n[yellow]RCA Agent coming in Phase 2. "
                     f"Use 'aiops chat' and ask the agent to investigate this issue.[/yellow]")

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
        item.resolved_at = datetime.utcnow()
        session.commit()

        return f"[green]Issue #{issue_id} resolved.[/green]"
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

    # Use pager for long output
    if len(lines) > 30:
        with console.pager(styles=True):
            console.print(output)
        return ""
    else:
        return output


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
    """Handle /less command - view last output in pager."""
    content = ctx.last_full_output
    if not content:
        # Fallback to last assistant message in history
        for msg in reversed(ctx.output_history):
            if msg["role"] in ("assistant", "system"):
                content = msg["content"]
                break

    if not content:
        return "[yellow]No output to display.[/yellow]"

    with console.pager(styles=True):
        rendered = Markdown(content) if content.startswith("#") or "```" in content else content
        console.print(rendered)
    return ""


def _slash_tokens(ctx: ChatContext, args: list) -> str:
    """Handle /tokens command - show token usage statistics."""
    if args and args[0] == "reset":
        ctx.reset_tokens()
        return "[green]Token counters reset.[/green]"

    usage = ctx.token_usage

    table = create_table(columns=[
        {"name": "Metric", "style": "cyan"},
        {"name": "Value", "justify": "right"},
    ])
    table.add_row("Input Tokens", f"{usage.input_tokens:,}")
    table.add_row("Output Tokens", f"{usage.output_tokens:,}")
    table.add_row("Total Tokens", f"[bold]{usage.total_tokens:,}[/bold]")
    table.add_row("API Requests", str(usage.requests))

    console.print("\n[bold]Token Usage (this session)[/bold]")
    console.print(table)

    # Show compact format
    return f"\n[dim]Compact: {usage.format()}[/dim]"


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
        ctx.verbose and console.print("[dim]Starting full-scan workflow...[/dim]")
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
            resource_count = session.query(AWSResource).count()
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
            accounts = session.query(AWSAccount).filter_by(is_active=True).count()
            resources = session.query(AWSResource).count()
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
  Verbose: {'ON' if ctx.verbose else 'OFF'}

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
        ctx.verbose = False
        return "[green]Context reset to defaults.[/green]"

    return "[yellow]Usage: /context [account <name> | reset][/yellow]"


def _slash_session(ctx: ChatContext, args: list) -> str:
    """Handle /session commands - session management."""
    import hashlib
    from pathlib import Path

    session_dir = Path.home() / ".aiops" / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)

    if not args or args[0] == "list":
        sessions = list(session_dir.glob("*.json"))
        if not sessions:
            return "[yellow]No saved sessions.[/yellow]"

        lines = ["[bold]Saved Sessions:[/bold]"]
        for s in sessions[-10:]:
            name = s.stem
            mtime = datetime.fromtimestamp(s.stat().st_mtime)
            lines.append(f"  {name} - {mtime.strftime('%Y-%m-%d %H:%M')}")
        return "\n".join(lines)

    cmd = args[0].lower()

    if cmd == "save":
        name = args[1] if len(args) > 1 else datetime.now().strftime("%Y%m%d_%H%M%S")
        session_file = session_dir / f"{name}.json"
        session_data = {
            "account": ctx.account,
            "output_format": ctx.output_format,
            "verbose": ctx.verbose,
            "saved_at": datetime.now().isoformat(),
        }
        session_file.write_text(json.dumps(session_data, indent=2))
        return f"[green]Session saved: {name}[/green]"

    elif cmd == "load" and len(args) > 1:
        name = args[1]
        session_file = session_dir / f"{name}.json"
        if not session_file.exists():
            return f"[red]Session '{name}' not found.[/red]"

        data = json.loads(session_file.read_text())
        ctx.account = data.get("account")
        ctx.output_format = data.get("output_format", "table")
        ctx.verbose = data.get("verbose", False)
        return f"[green]Session loaded: {name}[/green]"

    elif cmd == "delete" and len(args) > 1:
        name = args[1]
        session_file = session_dir / f"{name}.json"
        if session_file.exists():
            session_file.unlink()
            return f"[green]Session deleted: {name}[/green]"
        return f"[red]Session '{name}' not found.[/red]"

    return "[yellow]Usage: /session [list | save [name] | load <name> | delete <name>][/yellow]"


def _slash_status(ctx: ChatContext, args: list) -> str:
    """Handle /status command - quick system status."""
    init_db()
    session = get_session()

    try:
        accounts = session.query(AWSAccount).filter_by(is_active=True).count()
        resources = session.query(AWSResource).count()
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
            resources = session.query(AWSResource).limit(100).all()
            data = [{"type": r.resource_type, "id": r.resource_id, "name": r.resource_name,
                    "region": r.region, "status": r.status} for r in resources]
        elif entity in ("issues", "anomalies"):
            items = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc()).limit(100).all()
            data = [{"id": a.id, "severity": a.severity, "title": a.title, "source": a.source,
                    "status": a.status} for a in items]
        elif entity == "accounts":
            accounts = session.query(AWSAccount).all()
            data = [{"name": a.name, "account_id": a.account_id, "regions": a.regions} for a in accounts]
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
        accounts = session.query(AWSAccount).count()
        active = session.query(AWSAccount).filter_by(is_active=True).first()
        resources = session.query(AWSResource).count()
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
  ├── Accounts:  {accounts} ({active.name if active else 'none'} active)
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

    # Workflows
    "workflow": _slash_workflow,
    "wf": _slash_workflow,

    # Session & Context
    "context": _slash_context,
    "ctx": _slash_context,
    "session": _slash_session,

    # Automation
    "schedule": _slash_schedule,
    "notify": _slash_notify,

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

    # Check for verbose toggle
    if cmd == "verbose":
        ctx.verbose = not ctx.verbose
        return f"[green]Verbose mode: {'ON' if ctx.verbose else 'OFF'}[/green]"

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
        query = session.query(AWSResource).filter_by(resource_id=resource_id)
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
        query = session.query(AWSResource).filter_by(resource_id=resource_id)
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


@app.command()
def chat(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account name"),
):
    """Start an interactive chat with the AI operations agent.

    Features:
    - Arrow keys for history navigation (up/down)
    - Ctrl+A/E for line start/end
    - Ctrl+W to delete word
    - Ctrl+U to clear line
    - Tab completion for slash commands
    - Copy/paste support (Ctrl+C/V or system clipboard)
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.styles import Style
    from pathlib import Path

    from agenticops.agents import create_main_agent
    agent = create_main_agent()

    # Initialize chat context
    ctx = ChatContext()
    ctx.account = account

    # Setup history file
    history_dir = Path.home() / ".aiops"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "chat_history"

    # Slash command completer
    slash_commands = [
        "/help", "/status", "/alias", "/clear",
        "/account", "/resource", "/issue", "/issues", "/report",
        "/scan", "/detect", "/analyze", "/ack", "/resolve",
        "/workflow", "/schedule", "/notify",
        "/session", "/context", "/export", "/output",
        "/exit", "/quit",
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
        mouse_support=True,
    )

    # Welcome message
    console.print(Panel(
        "[bold]AgenticAIOps Chat[/bold] — [dim]Strands Multi-Agent[/dim]\n\n"
        "Chat with your AI operations assistant using natural language.\n"
        "Examples: [cyan]\"scan my EC2 instances\"[/cyan], [cyan]\"check health of my resources\"[/cyan], [cyan]\"list issues\"[/cyan]\n\n"
        "[dim]Shortcuts:[/dim]  ↑/↓ History  |  Tab Complete  |  Ctrl+R Search  |  Ctrl+C Exit\n"
        "[dim]Scroll:[/dim]     Mouse wheel  |  /scroll  |  /less\n"
        "[dim]Tokens:[/dim]     Displayed after each response (↑input ↓output Σtotal)\n",
        title="Welcome",
        border_style="blue",
    ))

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
                if result:
                    ctx.add_to_history("system", result)
                    print_with_truncation(console, result, ctx, header="System")
                continue

            # Store user input in history
            ctx.add_to_history("user", user_input)

            # Call agent with simple spinner
            display = ThinkingDisplay(console)

            with display.live_display():
                display.start("Thinking...")

                try:
                    result = agent(user_input)
                    response = str(result)
                    display.complete("Done")
                except Exception as e:
                    display.error(f"Error: {str(e)}")
                    response = f"Error: {str(e)}"

            # Store response in history
            ctx.add_to_history("assistant", response)

            # Display with smart truncation
            print_with_truncation(console, response, ctx, header="Agent")

            # Show session token summary in status bar
            console.print(f"[dim]─── Session: {ctx.get_token_summary()} | Requests: {ctx.token_usage.requests} ───[/dim]", justify="right")

        except KeyboardInterrupt:
            console.print("\n[yellow]Press Ctrl+C again to exit, or continue typing.[/yellow]")
            try:
                session.prompt([('class:prompt', '❯ ')], default='')
            except KeyboardInterrupt:
                console.print("\n[yellow]Session ended.[/yellow]")
                break
        except EOFError:
            console.print("\n[yellow]Session ended.[/yellow]")
            break


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Host to bind"),
    port: int = typer.Option(8080, "--port", "-p", help="Port to bind"),
):
    """Start the web dashboard."""
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
            query = session.query(AWSResource)
            if type:
                query = query.filter_by(resource_type=type)
            if region:
                query = query.filter_by(region=region)
            records = query.limit(limit).all()
            data = [{"id": r.id, "resource_id": r.resource_id, "type": r.resource_type,
                    "name": r.resource_name, "region": r.region, "status": r.status} for r in records]

        elif entity in ("issues", "anomalies"):
            query = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc())
            if severity:
                query = query.filter_by(severity=severity)
            records = query.limit(limit).all()
            data = [{"id": a.id, "title": a.title, "severity": a.severity, "status": a.status,
                    "resource": a.resource_id, "source": a.source,
                    "detected_at": a.detected_at.isoformat()} for a in records]

        elif entity == "accounts":
            records = session.query(AWSAccount).limit(limit).all()
            data = [{"name": a.name, "account_id": a.account_id, "regions": a.regions,
                    "is_active": a.is_active} for a in records]

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
        accounts = session.query(AWSAccount).count()
        active_account = session.query(AWSAccount).filter_by(is_active=True).first()
        resources = session.query(AWSResource).count()
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
            state.add(f"Accounts: {accounts} ({'[green]' + active_account.name + '[/green] active' if active_account else '[yellow]none active[/yellow]'})")
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

    import boto3
    from botocore.exceptions import ClientError

    console.print(f"[bold]Testing credentials for account '{name}'...[/bold]")

    try:
        sts = boto3.client("sts")
        assume_kwargs = {"RoleArn": acc.role_arn, "RoleSessionName": "AgenticOps-Test"}
        if acc.external_id:
            assume_kwargs["ExternalId"] = acc.external_id

        with console.status("Assuming role..."):
            response = sts.assume_role(**assume_kwargs)

        console.print("[green]Credentials valid![/green]")
        console.print(f"  Account ID: {response['AssumedRoleUser']['Arn'].split(':')[4]}")
        console.print(f"  Expiration: {response['Credentials']['Expiration']}")

    except ClientError as e:
        console.print(f"[red]Credential test failed: {e.response['Error']['Message']}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
