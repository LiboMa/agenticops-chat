"""Tests for CLI formatters — tables, rendering helpers, format utilities."""

import json
import os
import pytest
from unittest.mock import patch
from io import StringIO

from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.box import ROUNDED, SIMPLE, MINIMAL, DOUBLE, ASCII

from agenticops.cli.formatters import (
    get_table_style,
    create_table,
    render_markdown,
    render_json,
    render_yaml_style,
    render_tree,
    format_duration,
    format_bytes,
    format_number,
    TABLE_STYLES,
)


# ─── get_table_style ────────────────────────────────────────────────

class TestGetTableStyle:
    def test_default_style(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AIOPS_TABLE_STYLE", None)
            assert get_table_style() == ROUNDED

    def test_simple_style(self):
        with patch.dict(os.environ, {"AIOPS_TABLE_STYLE": "simple"}):
            assert get_table_style() == SIMPLE

    def test_minimal_style(self):
        with patch.dict(os.environ, {"AIOPS_TABLE_STYLE": "minimal"}):
            assert get_table_style() == MINIMAL

    def test_double_style(self):
        with patch.dict(os.environ, {"AIOPS_TABLE_STYLE": "double"}):
            assert get_table_style() == DOUBLE

    def test_ascii_style(self):
        with patch.dict(os.environ, {"AIOPS_TABLE_STYLE": "ascii"}):
            assert get_table_style() == ASCII

    def test_unknown_style_falls_back_to_rounded(self):
        with patch.dict(os.environ, {"AIOPS_TABLE_STYLE": "fancy"}):
            assert get_table_style() == ROUNDED


# ─── create_table ────────────────────────────────────────────────────

class TestCreateTable:
    def test_basic_table(self):
        t = create_table(title="Test")
        assert isinstance(t, Table)
        assert t.title == "Test"

    def test_table_with_columns(self):
        cols = [
            {"name": "Name", "style": "green"},
            {"name": "Status", "justify": "center", "no_wrap": True},
        ]
        t = create_table(columns=cols)
        assert len(t.columns) == 2
        assert t.columns[0].header == "Name"
        assert t.columns[1].header == "Status"

    def test_table_no_columns(self):
        t = create_table()
        assert len(t.columns) == 0

    def test_table_custom_box_style(self):
        t = create_table(box_style="ascii")
        assert t.box == ASCII

    def test_table_expand(self):
        t = create_table(expand=True)
        assert t.expand is True

    def test_table_show_lines(self):
        t = create_table(show_lines=True)
        assert t.show_lines is True


# ─── render_markdown ─────────────────────────────────────────────────

class TestRenderMarkdown:
    def test_renders_without_error(self):
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_markdown("# Hello\n\nWorld")

    def test_renders_with_title(self):
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_markdown("content", title="My Title")


# ─── render_json ─────────────────────────────────────────────────────

class TestRenderJson:
    def test_renders_dict(self):
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_json({"key": "value"})

    def test_renders_with_title(self):
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_json([1, 2, 3], title="Numbers")

    def test_handles_non_serialisable(self):
        """datetime and other objects should be handled via default=str."""
        from datetime import datetime
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_json({"ts": datetime(2026, 1, 1)})


# ─── render_yaml_style ──────────────────────────────────────────────

class TestRenderYamlStyle:
    def test_flat_dict(self):
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_yaml_style({"name": "test", "count": 42})

    def test_nested_dict(self):
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_yaml_style({"parent": {"child": "value"}})

    def test_list_values(self):
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_yaml_style({"items": ["a", "b"]})

    def test_list_of_dicts(self):
        console = Console(file=StringIO(), force_terminal=True)
        with patch("agenticops.cli.formatters.console", console):
            render_yaml_style({"servers": [{"name": "s1"}, {"name": "s2"}]})


# ─── render_tree ─────────────────────────────────────────────────────

class TestRenderTree:
    def test_basic_tree(self):
        items = [{"name": "a"}, {"name": "b"}]
        tree = render_tree("Root", items)
        assert isinstance(tree, Tree)

    def test_tree_with_children(self):
        items = [
            {"name": "parent", "subs": [{"name": "child1"}, {"name": "child2"}]}
        ]
        tree = render_tree("Root", items, children_field="subs")
        assert isinstance(tree, Tree)

    def test_tree_custom_key(self):
        items = [{"label": "x"}]
        tree = render_tree("Root", items, key_field="label")
        assert isinstance(tree, Tree)


# ─── format_duration ────────────────────────────────────────────────

class TestFormatDuration:
    def test_milliseconds(self):
        assert format_duration(0.5) == "500ms"
        assert format_duration(0.001) == "1ms"

    def test_seconds(self):
        assert format_duration(1.0) == "1.0s"
        assert format_duration(59.9) == "59.9s"

    def test_minutes(self):
        assert format_duration(60) == "1m0s"
        assert format_duration(90) == "1m30s"
        assert format_duration(125.7) == "2m6s"


# ─── format_bytes ────────────────────────────────────────────────────

class TestFormatBytes:
    def test_bytes(self):
        assert format_bytes(500) == "500.0B"

    def test_kilobytes(self):
        assert format_bytes(1024) == "1.0KB"

    def test_megabytes(self):
        assert format_bytes(1024 * 1024) == "1.0MB"

    def test_gigabytes(self):
        assert format_bytes(1024 ** 3) == "1.0GB"

    def test_terabytes(self):
        assert format_bytes(1024 ** 4) == "1.0TB"

    def test_petabytes(self):
        assert format_bytes(1024 ** 5) == "1.0PB"


# ─── format_number ───────────────────────────────────────────────────

class TestFormatNumber:
    def test_small_number(self):
        assert format_number(42) == "42"
        assert format_number(999) == "999"

    def test_thousands(self):
        assert format_number(1500) == "1.5K"
        assert format_number(999999) == "1000.0K"

    def test_millions(self):
        assert format_number(1000000) == "1.0M"
        assert format_number(2500000) == "2.5M"

    def test_billions(self):
        assert format_number(1000000000) == "1.0B"
        assert format_number(3700000000) == "3.7B"
