"""Tests for parallel agentic health check engine."""
import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agenticops.checker.engine import (
    check_accounts_parallel,
    _check_one_account,
    _parse_issue_count,
    CheckResult,
    AccountCheckResult,
)

# Patch targets for lazy imports inside _check_one_account
_PATCH_BUILD = "agenticops.agents.detect_agent._build_detect_agent_for_account"
_PATCH_INVOKE = "agenticops.agents.preamble.invoke_with_retry"

# Patch targets for lazy imports inside check_accounts_parallel
_PATCH_LOAD = "agenticops.scanner.engine._load_accounts"
_PATCH_GET_TOOL = "agenticops.scanner.engine._get_provider_and_tool"


# ── _parse_issue_count ──────────────────────────────────────────────


class TestParseIssueCount:
    def test_x_issues_created(self):
        assert _parse_issue_count("3 issues created") == 3

    def test_x_issue_created_singular(self):
        assert _parse_issue_count("1 issue created") == 1

    def test_found_x_health_issues(self):
        assert _parse_issue_count("Found 2 health issues") == 2

    def test_created_x_health_issues(self):
        assert _parse_issue_count("created 5 health issues") == 5

    def test_individual_created_lines(self):
        output = (
            "Created HealthIssue: high CPU on i-abc\n"
            "Created HealthIssue: disk full on i-def\n"
        )
        assert _parse_issue_count(output) == 2

    def test_no_issues_found(self):
        assert _parse_issue_count("No issues found") == 0

    def test_empty_string(self):
        assert _parse_issue_count("") == 0

    def test_mixed_output_prefers_summary(self):
        """When both a summary line and individual lines exist, the summary wins."""
        output = (
            "Created HealthIssue: disk full\n"
            "Created HealthIssue: high CPU\n"
            "Summary: 2 issues created for this account.\n"
        )
        assert _parse_issue_count(output) == 2

    def test_issues_found_variant(self):
        assert _parse_issue_count("7 issues found during scan") == 7

    def test_case_insensitive(self):
        assert _parse_issue_count("FOUND 4 HEALTH ISSUES") == 4


# ── _check_one_account ─────────────────────────────────────────────


class TestCheckOneAccount:
    def _make_acct(self, **overrides):
        defaults = dict(id=1, name="test-aws", provider="aws", regions=["us-east-1"])
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    @patch(_PATCH_INVOKE, return_value="Checked 10 resources. 2 issues created.")
    @patch(_PATCH_BUILD, return_value=MagicMock())
    def test_happy_path(self, mock_build, mock_invoke):
        acct = self._make_acct()
        result = _check_one_account(acct, MagicMock(), MagicMock(), "all", False)

        assert isinstance(result, AccountCheckResult)
        assert result.account_id == 1
        assert result.account_name == "test-aws"
        assert result.provider == "aws"
        assert result.issues_created == 2
        assert result.agent_output == "Checked 10 resources. 2 issues created."
        assert result.errors == []
        assert result.duration_s >= 0
        assert result.regions_checked == ["us-east-1"]

    @patch(_PATCH_INVOKE, return_value="OK")
    @patch(_PATCH_BUILD, return_value=MagicMock())
    def test_agent_build_receives_correct_args(self, mock_build, mock_invoke):
        cli_tool = MagicMock(name="cli_tool")
        session = MagicMock(name="session")
        acct = self._make_acct(id=42, name="prod-account")

        _check_one_account(acct, cli_tool, session, "security", True)

        mock_build.assert_called_once_with(
            acct_name="prod-account",
            acct_id=42,
            cli_tool=cli_tool,
            session=session,
        )

    @patch(_PATCH_INVOKE, return_value="OK")
    @patch(_PATCH_BUILD, return_value=MagicMock())
    def test_invoke_prompt_contains_scope_and_deep(self, mock_build, mock_invoke):
        acct = self._make_acct(name="my-acct")
        _check_one_account(acct, MagicMock(), MagicMock(), "security", True)

        prompt = mock_invoke.call_args[0][1]
        assert "my-acct" in prompt
        assert "Scope=security" in prompt
        assert "Deep=True" in prompt

    @patch(_PATCH_INVOKE)
    @patch(_PATCH_BUILD, side_effect=RuntimeError("model timeout"))
    def test_exception_captured_in_errors(self, mock_build, mock_invoke):
        acct = self._make_acct()
        result = _check_one_account(acct, MagicMock(), MagicMock(), "all", False)

        assert result.issues_created == 0
        assert result.agent_output == ""
        assert len(result.errors) == 1
        assert "model timeout" in result.errors[0]

    @patch(_PATCH_INVOKE, side_effect=Exception("Bedrock throttling"))
    @patch(_PATCH_BUILD, return_value=MagicMock())
    def test_invoke_exception_captured(self, mock_build, mock_invoke):
        acct = self._make_acct()
        result = _check_one_account(acct, MagicMock(), MagicMock(), "all", False)

        assert len(result.errors) == 1
        assert "throttling" in result.errors[0].lower()

    @patch(_PATCH_INVOKE, return_value="OK")
    @patch(_PATCH_BUILD, return_value=MagicMock())
    def test_empty_regions(self, mock_build, mock_invoke):
        acct = self._make_acct(regions=[])
        result = _check_one_account(acct, MagicMock(), MagicMock(), "all", False)

        assert result.regions_checked == []


# ── check_accounts_parallel ────────────────────────────────────────


class TestCheckAccountsParallel:
    def _make_acct(self, id, name, provider="aws", regions=None):
        return SimpleNamespace(
            id=id, name=name, provider=provider,
            credentials={}, regions=regions or ["us-east-1"],
            labels={}, is_enabled=True,
        )

    def _make_provider(self):
        provider = MagicMock()
        provider.resolve_credentials.return_value = True
        provider.cli_tool.return_value = MagicMock()
        provider.sdk_session.return_value = MagicMock()
        return provider

    def test_empty_accounts(self):
        with patch(_PATCH_LOAD, return_value=[]):
            result = asyncio.run(check_accounts_parallel())
        assert isinstance(result, CheckResult)
        assert len(result.accounts) == 0
        assert result.total_issues == 0
        assert result.duration_s >= 0

    def test_no_valid_credentials(self):
        acct = self._make_acct(1, "bad-creds")
        with patch(_PATCH_LOAD, return_value=[acct]), \
             patch(_PATCH_GET_TOOL, return_value=None):
            result = asyncio.run(check_accounts_parallel())
        assert isinstance(result, CheckResult)
        assert len(result.accounts) == 0

    @patch("agenticops.checker.engine._check_one_account")
    def test_two_accounts_parallel(self, mock_check):
        acct1 = self._make_acct(1, "prod-aws")
        acct2 = self._make_acct(2, "staging-aws")
        provider = self._make_provider()

        mock_check.side_effect = [
            AccountCheckResult(
                account_id=1, account_name="prod-aws", provider="aws",
                issues_created=3, duration_s=1.5,
            ),
            AccountCheckResult(
                account_id=2, account_name="staging-aws", provider="aws",
                issues_created=1, duration_s=0.8,
            ),
        ]

        with patch(_PATCH_LOAD, return_value=[acct1, acct2]), \
             patch(_PATCH_GET_TOOL, return_value=(provider, MagicMock())):
            result = asyncio.run(check_accounts_parallel())

        assert len(result.accounts) == 2
        assert result.total_issues == 4
        assert result.duration_s >= 0
        names = {r.account_name for r in result.accounts}
        assert names == {"prod-aws", "staging-aws"}

    @patch("agenticops.checker.engine._check_one_account")
    def test_aggregates_zero_issues(self, mock_check):
        acct = self._make_acct(1, "clean-account")
        provider = self._make_provider()

        mock_check.return_value = AccountCheckResult(
            account_id=1, account_name="clean-account", provider="aws",
            issues_created=0, duration_s=0.5,
        )

        with patch(_PATCH_LOAD, return_value=[acct]), \
             patch(_PATCH_GET_TOOL, return_value=(provider, MagicMock())):
            result = asyncio.run(check_accounts_parallel())

        assert result.total_issues == 0
        assert len(result.accounts) == 1

    @patch("agenticops.checker.engine._check_one_account")
    def test_passes_scope_and_deep(self, mock_check):
        acct = self._make_acct(1, "test-account")
        provider = self._make_provider()

        mock_check.return_value = AccountCheckResult(
            account_id=1, account_name="test-account", provider="aws",
        )

        with patch(_PATCH_LOAD, return_value=[acct]), \
             patch(_PATCH_GET_TOOL, return_value=(provider, MagicMock())):
            asyncio.run(check_accounts_parallel(scope="security", deep=True))

        # _check_one_account receives scope and deep via to_thread
        call_args = mock_check.call_args
        assert call_args[0][3] == "security"  # scope
        assert call_args[0][4] is True  # deep

    @patch("agenticops.checker.engine._check_one_account")
    def test_account_ids_filter(self, mock_check):
        """account_ids parameter is forwarded to _load_accounts."""
        mock_check.return_value = AccountCheckResult(
            account_id=5, account_name="filtered", provider="aws",
        )
        provider = self._make_provider()

        with patch(_PATCH_LOAD, return_value=[
                self._make_acct(5, "filtered")]) as mock_load, \
             patch(_PATCH_GET_TOOL, return_value=(provider, MagicMock())):
            asyncio.run(check_accounts_parallel(account_ids=[5]))

        mock_load.assert_called_once_with([5])

    def test_duration_tracked(self):
        with patch(_PATCH_LOAD, return_value=[]):
            result = asyncio.run(check_accounts_parallel())
        assert result.duration_s >= 0


# ── __init__.py re-exports ─────────────────────────────────────────


class TestModuleExports:
    def test_imports_from_package(self):
        from agenticops.checker import check_accounts_parallel, CheckResult, AccountCheckResult
        assert callable(check_accounts_parallel)
        assert CheckResult is not None
        assert AccountCheckResult is not None
