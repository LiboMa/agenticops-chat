"""Tests for parallel scan engine."""
import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from agenticops.scanner.engine import (
    scan_accounts_parallel,
    scan_one_account,
    ScanResult,
    AccountScanResult,
    _save_resources,
)


class TestScanOneAccount:
    def test_runs_commands_for_focus(self):
        """scan_one_account runs CLI commands and parses output."""
        cli_tool = MagicMock(return_value='{"Reservations": []}')
        acct = SimpleNamespace(
            id=1, name="test", provider="aws", regions=["us-east-1"],
        )
        result, resources = scan_one_account(acct, cli_tool, focus="computing")
        assert isinstance(result, AccountScanResult)
        assert result.account_name == "test"
        assert "us-east-1" in result.regions_scanned
        assert cli_tool.call_count >= 1

    def test_skips_unknown_provider(self):
        cli_tool = MagicMock()
        acct = SimpleNamespace(
            id=1, name="test", provider="unknown_cloud", regions=["region-1"],
        )
        result, resources = scan_one_account(acct, cli_tool, focus="all")
        assert result.resources_found == 0
        assert len(result.errors) > 0

    def test_handles_cli_error(self):
        cli_tool = MagicMock(return_value="Error: access denied")
        acct = SimpleNamespace(
            id=1, name="test", provider="aws", regions=["us-east-1"],
        )
        result, resources = scan_one_account(acct, cli_tool, focus="computing")
        assert isinstance(result, AccountScanResult)

    def test_collects_parsed_resources(self):
        """Resources from successful parses are collected."""
        cli_tool = MagicMock(return_value='{"Reservations": [{"Instances": [{"InstanceId": "i-1", "State": {"Name": "running"}, "Tags": []}]}]}')
        acct = SimpleNamespace(id=1, name="test", provider="aws", regions=["us-east-1"])
        result, resources = scan_one_account(acct, cli_tool, focus="computing")
        assert any(r["resource_id"] == "i-1" for r in resources)

    def test_global_commands_run_once(self):
        """Global commands (S3, IAM) should run once, not per-region."""
        cli_tool = MagicMock(return_value='{"Buckets": []}')
        acct = SimpleNamespace(
            id=1, name="test", provider="aws",
            regions=["us-east-1", "us-west-2"],
        )
        result, resources = scan_one_account(acct, cli_tool, focus="storage")
        # storage has 3 commands: aws_s3_buckets (global) + aws_ebs_volumes (regional) + aws_efs_file_systems (regional)
        # s3 runs once, ebs runs per region (2), efs runs per region (2)
        # total calls = 1 (s3) + 2 (ebs) + 2 (efs) = 5
        assert cli_tool.call_count == 5

    def test_returns_tuple(self):
        """scan_one_account returns (AccountScanResult, list[dict])."""
        cli_tool = MagicMock(return_value='{"Reservations": []}')
        acct = SimpleNamespace(id=1, name="test", provider="aws", regions=["us-east-1"])
        ret = scan_one_account(acct, cli_tool, focus="computing")
        assert isinstance(ret, tuple)
        assert len(ret) == 2
        assert isinstance(ret[0], AccountScanResult)
        assert isinstance(ret[1], list)

    def test_custom_regions_override(self):
        """Explicit regions parameter overrides account regions."""
        cli_tool = MagicMock(return_value='{"Reservations": []}')
        acct = SimpleNamespace(id=1, name="test", provider="aws", regions=["us-east-1"])
        result, _ = scan_one_account(acct, cli_tool, focus="computing", regions=["eu-west-1"])
        assert result.regions_scanned == ["eu-west-1"]

    def test_default_region_fallback(self):
        """When account has no regions, defaults to us-east-1."""
        cli_tool = MagicMock(return_value='{"Reservations": []}')
        acct = SimpleNamespace(id=1, name="test", provider="aws", regions=[])
        result, _ = scan_one_account(acct, cli_tool, focus="computing")
        assert result.regions_scanned == ["us-east-1"]

    def test_cli_exception_captured(self):
        """CLI tool raising exception is captured in errors, not raised."""
        cli_tool = MagicMock(side_effect=Exception("connection timeout"))
        acct = SimpleNamespace(id=1, name="test", provider="aws", regions=["us-east-1"])
        result, resources = scan_one_account(acct, cli_tool, focus="computing")
        assert len(result.errors) > 0
        assert result.resources_found == 0


class TestSaveResources:
    def test_empty_resources_returns_zero(self):
        created, updated = _save_resources(1, "aws", [])
        assert created == 0
        assert updated == 0

    def test_parses_save_result(self):
        with patch("agenticops.tools.metadata_tools.save_resources",
                   return_value="Saved 5 new resources, updated 3 existing"):
            created, updated = _save_resources(1, "aws", [{"resource_id": "x"}])
        assert created == 5
        assert updated == 3


class TestScanAccountsParallel:
    def test_returns_scan_result(self):
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
        mock_acct = SimpleNamespace(
            id=1, name="bad-creds", provider="aws",
            credentials={}, regions=["us-east-1"], labels={}, is_enabled=True,
        )
        with patch("agenticops.scanner.engine._load_accounts", return_value=[mock_acct]), \
             patch("agenticops.scanner.engine._get_provider_and_tool", return_value=None):
            result = asyncio.run(scan_accounts_parallel())

        assert isinstance(result, ScanResult)
        assert len(result.accounts) == 0

    def test_empty_accounts(self):
        with patch("agenticops.scanner.engine._load_accounts", return_value=[]):
            result = asyncio.run(scan_accounts_parallel())
        assert isinstance(result, ScanResult)
        assert len(result.accounts) == 0
        assert result.total_found == 0

    def test_saves_resources_after_scan(self):
        """_scan_and_save calls _save_resources with collected resources."""
        mock_acct = SimpleNamespace(
            id=1, name="test-aws", provider="aws",
            credentials={}, regions=["us-east-1"], labels={}, is_enabled=True,
        )
        mock_cli = MagicMock(return_value='{"Reservations": [{"Instances": [{"InstanceId": "i-1", "State": {"Name": "running"}, "Tags": []}]}]}')

        with patch("agenticops.scanner.engine._load_accounts", return_value=[mock_acct]), \
             patch("agenticops.scanner.engine._get_provider_and_tool", return_value=(MagicMock(), mock_cli)), \
             patch("agenticops.scanner.engine._save_resources") as mock_save:
            mock_save.return_value = (1, 0)
            result = asyncio.run(scan_accounts_parallel(focus="computing"))

        # _save_resources must have been called with the resources
        assert mock_save.called
        call_args = mock_save.call_args
        assert call_args[0][0] == 1  # account_id
        assert call_args[0][1] == "aws"  # provider
        assert len(call_args[0][2]) > 0  # resources list not empty

    def test_duration_tracked(self):
        with patch("agenticops.scanner.engine._load_accounts", return_value=[]):
            result = asyncio.run(scan_accounts_parallel())
        assert result.duration_s >= 0
