"""Tests for detect_agent per-account factory function."""

import pytest
from unittest.mock import MagicMock, patch

from agenticops.agents.detect_agent import _build_detect_agent_for_account


@pytest.fixture
def mock_config():
    """Mock config settings."""
    with patch("agenticops.agents.detect_agent.settings") as mock_settings:
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_cache_enabled = True
        yield mock_settings


@pytest.fixture
def mock_get_agent_config():
    """Mock get_agent_model_config and get_agent_window_size."""
    with patch("agenticops.config.get_agent_model_config") as mock_model_cfg, \
         patch("agenticops.config.get_agent_window_size") as mock_window_cfg:
        mock_model_cfg.return_value = ("global.anthropic.claude-sonnet-4-6", 16384)
        mock_window_cfg.return_value = 10
        yield mock_model_cfg, mock_window_cfg


@pytest.fixture
def mock_strands_agent():
    """Mock Strands Agent and BedrockModel."""
    with patch("agenticops.agents.detect_agent.Agent") as mock_agent_cls, \
         patch("agenticops.agents.detect_agent.BedrockModel") as mock_model_cls, \
         patch("agenticops.agents.detect_agent.SlidingWindowConversationManager") as mock_conv_mgr:
        mock_agent_instance = MagicMock()
        mock_agent_cls.return_value = mock_agent_instance
        yield mock_agent_cls, mock_model_cls, mock_conv_mgr, mock_agent_instance


def test_build_detect_agent_for_account_returns_agent(
    mock_config, mock_get_agent_config, mock_strands_agent
):
    """Test that _build_detect_agent_for_account returns a Strands Agent."""
    mock_agent_cls, mock_model_cls, mock_conv_mgr, mock_agent_instance = mock_strands_agent
    mock_cli_tool = MagicMock()
    mock_session = MagicMock()

    agent = _build_detect_agent_for_account(
        acct_name="test-account",
        acct_id=42,
        cli_tool=mock_cli_tool,
        session=mock_session,
    )

    # Should return the mock agent instance
    assert agent == mock_agent_instance
    # Agent constructor should have been called once
    mock_agent_cls.assert_called_once()


def test_build_detect_agent_for_account_has_correct_tools(
    mock_config, mock_get_agent_config, mock_strands_agent
):
    """Test that the agent has exactly 17 tools (1 cli_tool + 16 shared tools)."""
    mock_agent_cls, mock_model_cls, mock_conv_mgr, mock_agent_instance = mock_strands_agent
    mock_cli_tool = MagicMock()
    mock_session = MagicMock()

    _build_detect_agent_for_account(
        acct_name="test-account",
        acct_id=42,
        cli_tool=mock_cli_tool,
        session=mock_session,
    )

    # Get the tools list from the Agent() call
    call_kwargs = mock_agent_cls.call_args[1]
    tools = call_kwargs["tools"]

    # Should have exactly 17 tools
    assert len(tools) == 20

    # First tool should be the cli_tool
    assert tools[0] == mock_cli_tool

    # Should NOT include assume_role or get_active_account
    from agenticops.tools.aws_tools import assume_role
    from agenticops.tools.metadata_tools import get_active_account

    assert assume_role not in tools
    assert get_active_account not in tools


def test_build_detect_agent_for_account_system_prompt_contains_account_context(
    mock_config, mock_get_agent_config, mock_strands_agent
):
    """Test that the system prompt contains account-specific context."""
    mock_agent_cls, mock_model_cls, mock_conv_mgr, mock_agent_instance = mock_strands_agent
    mock_cli_tool = MagicMock()
    mock_session = MagicMock()

    _build_detect_agent_for_account(
        acct_name="production-account",
        acct_id=99,
        cli_tool=mock_cli_tool,
        session=mock_session,
    )

    # Get the system_prompt from the Agent() call
    call_kwargs = mock_agent_cls.call_args[1]
    system_prompt = call_kwargs["system_prompt"]

    # Should contain account context prepended
    assert "production-account" in system_prompt
    assert "id=99" in system_prompt
    assert "Do NOT call get_active_account or assume_role" in system_prompt

    # Should also contain the original DETECT_SYSTEM_PROMPT
    assert "You are the Detect Agent for AgenticOps" in system_prompt


def test_build_detect_agent_for_account_uses_correct_model_config(
    mock_config, mock_get_agent_config, mock_strands_agent
):
    """Test that the agent uses the correct model configuration."""
    mock_agent_cls, mock_model_cls, mock_conv_mgr, mock_agent_instance = mock_strands_agent
    mock_model_cfg, mock_window_cfg = mock_get_agent_config
    mock_cli_tool = MagicMock()
    mock_session = MagicMock()

    _build_detect_agent_for_account(
        acct_name="test-account",
        acct_id=42,
        cli_tool=mock_cli_tool,
        session=mock_session,
    )

    # Should call get_agent_model_config with "detect"
    mock_model_cfg.assert_called_once_with("detect")

    # Should call get_agent_window_size with "detect"
    mock_window_cfg.assert_called_once_with("detect")

    # Should create BedrockModel with correct parameters
    mock_model_cls.assert_called_once()
    model_call_kwargs = mock_model_cls.call_args[1]
    assert model_call_kwargs["model_id"] == "global.anthropic.claude-sonnet-4-6"
    assert model_call_kwargs["region_name"] == "us-east-1"
    assert model_call_kwargs["max_tokens"] == 16384
    assert "cache_config" in model_call_kwargs


def test_build_detect_agent_for_account_respects_cache_config(
    mock_config, mock_get_agent_config, mock_strands_agent
):
    """Test that cache configuration is respected."""
    mock_agent_cls, mock_model_cls, mock_conv_mgr, mock_agent_instance = mock_strands_agent
    mock_cli_tool = MagicMock()
    mock_session = MagicMock()

    # Test with cache enabled
    mock_config.bedrock_cache_enabled = True
    _build_detect_agent_for_account(
        acct_name="test-account",
        acct_id=42,
        cli_tool=mock_cli_tool,
        session=mock_session,
    )
    model_call_kwargs_enabled = mock_model_cls.call_args[1]
    assert "cache_config" in model_call_kwargs_enabled
    assert "cache_tools" in model_call_kwargs_enabled

    # Test with cache disabled
    mock_model_cls.reset_mock()
    mock_config.bedrock_cache_enabled = False
    _build_detect_agent_for_account(
        acct_name="test-account",
        acct_id=42,
        cli_tool=mock_cli_tool,
        session=mock_session,
    )
    model_call_kwargs_disabled = mock_model_cls.call_args[1]
    assert "cache_config" not in model_call_kwargs_disabled
    assert "cache_tools" not in model_call_kwargs_disabled
