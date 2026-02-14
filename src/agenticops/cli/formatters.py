"""Output formatters for CLI - tables, markdown, JSON, tree views."""

import json
import os
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree
from rich.box import ROUNDED, SIMPLE, MINIMAL, DOUBLE, ASCII

# Global console instance
console = Console()

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
    """Render markdown content with optional title panel."""
    md = Markdown(content)
    if title:
        console.print(Panel(md, title=title, border_style="blue"))
    else:
        console.print(md)


def render_json(data: Any, title: str = None):
    """Render JSON with syntax highlighting."""
    json_str = json.dumps(data, indent=2, default=str)
    syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
    if title:
        console.print(Panel(syntax, title=title, border_style="green"))
    else:
        console.print(syntax)


def render_yaml_style(data: Dict, indent: int = 0):
    """Render dict in YAML-like style without quotes."""
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
            console.print(f"{prefix}[cyan]{key}:[/cyan] {value}")


def render_tree(
    title: str,
    items: List[Dict],
    key_field: str = "name",
    children_field: str = None,
) -> Tree:
    """Render hierarchical data as a tree."""
    tree = Tree(f"[bold]{title}[/bold]")

    def add_items(parent, items_list):
        for item in items_list:
            name = item.get(key_field, str(item))
            node = parent.add(f"[green]{name}[/green]")
            if children_field and children_field in item:
                add_items(node, item[children_field])

    add_items(tree, items)
    return tree


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m{secs:.0f}s"


def format_bytes(num_bytes: int) -> str:
    """Format bytes in human-readable form."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}PB"


def format_number(num: int) -> str:
    """Format large numbers with K/M/B suffix."""
    if num < 1000:
        return str(num)
    elif num < 1000000:
        return f"{num/1000:.1f}K"
    elif num < 1000000000:
        return f"{num/1000000:.1f}M"
    else:
        return f"{num/1000000000:.1f}B"
