"""Tests for providers/base.py — get_all_cli_tools & get_cli_tool_for_issue."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agenticops.providers.base import (
    get_all_cli_tools,
    get_cli_tool_for_issue,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_acct(id_=1, name="acct", provider="aws", creds=None, regions=None, labels=None):
    return SimpleNamespace(
        id=id_,
        name=name,
        provider=provider,
        credentials=creds or {"key": "val"},
        regions=regions or ["us-east-1"],
        labels=labels or {},
        is_enabled=True,
    )


def _mock_db_session(accounts):
    """Create a mock get_db_session that returns accounts from query."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = accounts
    mock_db.query.return_value.filter_by.return_value.first.return_value = (
        accounts[0] if accounts else None
    )

    @contextmanager
    def ctx():
        yield mock_db

    return ctx


# ── get_all_cli_tools ────────────────────────────────────────────────

class TestGetAllCliTools:

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.base.get_provider")
    def test_returns_tools_for_enabled_accounts(self, mock_gp, mock_gdb):
        mock_gdb.side_effect = _mock_db_session([_make_acct()])

        prov = MagicMock()
        prov.resolve_credentials.return_value = True
        prov.cli_tool.return_value = lambda: "cli"
        mock_gp.return_value = prov

        tools = get_all_cli_tools()
        assert len(tools) == 1

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.base.get_provider")
    def test_skips_failed_credentials(self, mock_gp, mock_gdb):
        mock_gdb.side_effect = _mock_db_session([_make_acct()])

        prov = MagicMock()
        prov.resolve_credentials.return_value = False
        mock_gp.return_value = prov

        assert get_all_cli_tools() == []

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.base.get_provider")
    def test_skips_provider_exception(self, mock_gp, mock_gdb):
        mock_gdb.side_effect = _mock_db_session([_make_acct()])
        mock_gp.side_effect = Exception("boom")

        assert get_all_cli_tools() == []

    @patch("agenticops.models.get_db_session")
    def test_empty_on_db_failure(self, mock_gdb):
        mock_gdb.side_effect = Exception("db down")
        assert get_all_cli_tools() == []

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.base.get_provider")
    def test_multiple_mixed(self, mock_gp, mock_gdb):
        accts = [_make_acct(id_=1, name="a1"), _make_acct(id_=2, name="a2")]
        mock_gdb.side_effect = _mock_db_session(accts)

        call_n = [0]

        def _side(snap):
            call_n[0] += 1
            m = MagicMock()
            m.resolve_credentials.return_value = (call_n[0] == 1)
            m.cli_tool.return_value = lambda: "t"
            return m

        mock_gp.side_effect = _side
        assert len(get_all_cli_tools()) == 1

    @patch("agenticops.models.get_db_session")
    def test_no_accounts(self, mock_gdb):
        mock_gdb.side_effect = _mock_db_session([])
        assert get_all_cli_tools() == []


# ── get_cli_tool_for_issue ───────────────────────────────────────────

class TestGetCliToolForIssue:

    def test_none_returns_none(self):
        assert get_cli_tool_for_issue(None) is None

    def test_zero_returns_none(self):
        assert get_cli_tool_for_issue(0) is None

    @patch("agenticops.models.get_db_session")
    def test_not_found(self, mock_gdb):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        @contextmanager
        def ctx():
            yield mock_db

        mock_gdb.return_value = ctx()
        assert get_cli_tool_for_issue(999) is None

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.base.get_provider")
    def test_returns_tool(self, mock_gp, mock_gdb):
        acct = _make_acct(id_=42)
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = acct

        @contextmanager
        def ctx():
            yield mock_db

        mock_gdb.return_value = ctx()

        sentinel = lambda: "tool"
        prov = MagicMock()
        prov.resolve_credentials.return_value = True
        prov.cli_tool.return_value = sentinel
        mock_gp.return_value = prov

        assert get_cli_tool_for_issue(42) is sentinel

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.base.get_provider")
    def test_cred_fail_returns_none(self, mock_gp, mock_gdb):
        acct = _make_acct(id_=42)
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = acct

        @contextmanager
        def ctx():
            yield mock_db

        mock_gdb.return_value = ctx()

        prov = MagicMock()
        prov.resolve_credentials.return_value = False
        mock_gp.return_value = prov

        assert get_cli_tool_for_issue(42) is None
