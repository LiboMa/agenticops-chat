"""Unit tests for reporter_agent and scan_agent tool functions.

Tests the agent tool wrappers by mocking the Strands Agent class to avoid
real Bedrock calls. Covers error handling paths and argument validation.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestReporterAgent:
    """Tests for the reporter_agent tool function."""

    @patch("agenticops.agents.reporter_agent.Agent")
    @patch("agenticops.agents.reporter_agent.BedrockModel")
    def test_reporter_agent_daily_report(self, mock_model_cls, mock_agent_cls):
        """Test successful daily report generation."""
        from agenticops.agents.reporter_agent import reporter_agent

        mock_agent = MagicMock()
        mock_agent.return_value = "## Daily Report\n\nAll systems operational."
        mock_agent_cls.return_value = mock_agent

        result = reporter_agent._tool_func(report_type="daily", scope="all")

        assert "Daily Report" in result
        mock_agent_cls.assert_called_once()
        mock_agent.assert_called_once()

    @patch("agenticops.agents.reporter_agent.Agent")
    @patch("agenticops.agents.reporter_agent.BedrockModel")
    def test_reporter_agent_incident_report(self, mock_model_cls, mock_agent_cls):
        """Test incident report generation."""
        from agenticops.agents.reporter_agent import reporter_agent

        mock_agent = MagicMock()
        mock_agent.return_value = "## Incident Report\n\n1 critical issue found."
        mock_agent_cls.return_value = mock_agent

        result = reporter_agent._tool_func(report_type="incident", scope="EC2")

        assert result
        call_args = mock_agent.call_args[0][0]
        assert "incident" in call_args
        assert "EC2" in call_args

    @patch("agenticops.agents.reporter_agent.Agent")
    @patch("agenticops.agents.reporter_agent.BedrockModel")
    def test_reporter_agent_inventory_report(self, mock_model_cls, mock_agent_cls):
        """Test inventory report generation."""
        from agenticops.agents.reporter_agent import reporter_agent

        mock_agent = MagicMock()
        mock_agent.return_value = "## Inventory\n\n15 resources across 3 regions."
        mock_agent_cls.return_value = mock_agent

        result = reporter_agent._tool_func(report_type="inventory", scope="RDS")

        assert result
        call_args = mock_agent.call_args[0][0]
        assert "inventory" in call_args
        assert "RDS" in call_args

    @patch("agenticops.agents.reporter_agent.Agent")
    @patch("agenticops.agents.reporter_agent.BedrockModel")
    def test_reporter_agent_error_handling(self, mock_model_cls, mock_agent_cls):
        """Test error handling when agent raises exception."""
        from agenticops.agents.reporter_agent import reporter_agent

        mock_model_cls.side_effect = RuntimeError("Bedrock unavailable")

        result = reporter_agent._tool_func(report_type="daily", scope="all")

        assert "error" in result.lower()
        assert "Bedrock unavailable" in result

    @patch("agenticops.agents.reporter_agent.Agent")
    @patch("agenticops.agents.reporter_agent.BedrockModel")
    def test_reporter_agent_default_args(self, mock_model_cls, mock_agent_cls):
        """Test default arguments are applied correctly."""
        from agenticops.agents.reporter_agent import reporter_agent

        mock_agent = MagicMock()
        mock_agent.return_value = "report output"
        mock_agent_cls.return_value = mock_agent

        result = reporter_agent._tool_func()

        call_args = mock_agent.call_args[0][0]
        assert "daily" in call_args
        assert "all" in call_args


class TestScanAgent:
    """Tests for the scan_agent tool function."""

    @patch("agenticops.agents.scan_agent.Agent")
    @patch("agenticops.agents.scan_agent.BedrockModel")
    def test_scan_agent_full_scan(self, mock_model_cls, mock_agent_cls):
        """Test full resource scan."""
        from agenticops.agents.scan_agent import scan_agent

        mock_agent = MagicMock()
        mock_agent.return_value = "Scan complete: 5 resources found, 1 issue detected."
        mock_agent_cls.return_value = mock_agent

        result = scan_agent._tool_func(services="all", regions="all")

        assert result
        mock_agent_cls.assert_called_once()
        mock_agent.assert_called_once()

    @patch("agenticops.agents.scan_agent.Agent")
    @patch("agenticops.agents.scan_agent.BedrockModel")
    def test_scan_agent_scoped(self, mock_model_cls, mock_agent_cls):
        """Test scoped scan for specific resource type."""
        from agenticops.agents.scan_agent import scan_agent

        mock_agent = MagicMock()
        mock_agent.return_value = "Scan complete: 3 EC2 instances."
        mock_agent_cls.return_value = mock_agent

        result = scan_agent._tool_func(services="EC2", regions="us-east-1")

        call_args = mock_agent.call_args[0][0]
        assert "EC2" in call_args

    @patch("agenticops.agents.scan_agent.Agent")
    @patch("agenticops.agents.scan_agent.BedrockModel")
    def test_scan_agent_error_handling(self, mock_model_cls, mock_agent_cls):
        """Test error handling when scan agent fails."""
        from agenticops.agents.scan_agent import scan_agent

        mock_model_cls.side_effect = RuntimeError("Connection refused")

        result = scan_agent._tool_func(services="all", regions="all")

        assert "error" in result.lower()
        assert "Connection refused" in result
