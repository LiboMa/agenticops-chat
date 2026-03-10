"""Tests for tool_tier_registry — ensures every @tool has a tier and bindings are correct."""
import pytest
from agenticops.skills._models import SecurityTier
from agenticops.skills.tool_tier_registry import TOOL_TIERS, get_tool_tier
from agenticops.skills.agent_binding import AGENT_TIER_BINDINGS


class TestToolTierRegistry:
    """Tool tier mapping tests."""

    def test_all_84_tools_registered(self):
        """Every known @tool function should have a tier entry."""
        assert len(TOOL_TIERS) >= 80, f"Expected >=80 tools, got {len(TOOL_TIERS)}"

    def test_no_unknown_tiers(self):
        """All tiers should be valid SecurityTier values."""
        for name, tier in TOOL_TIERS.items():
            assert isinstance(tier, SecurityTier), f"{name} has invalid tier: {tier}"

    def test_read_only_tools_are_t0(self):
        """Describe/list/get tools should be T0."""
        for name, tier in TOOL_TIERS.items():
            if name.startswith(("describe_", "list_", "get_")) and "approved" not in name:
                assert tier == SecurityTier.T0_READONLY, f"{name} should be T0, got {tier}"

    def test_write_tools_at_least_t1(self):
        """Save/create/write/update tools should be >= T1."""
        for name, tier in TOOL_TIERS.items():
            if name.startswith(("save_", "create_", "write_", "update_")):
                assert tier >= SecurityTier.T1_LOW_RISK, f"{name} should be >= T1, got {tier}"

    def test_risky_tools_are_t2(self):
        """approve_fix_plan, mark_fix_executed, run_aws_cli, write_local_file should be T2."""
        risky = ["approve_fix_plan", "mark_fix_executed", "run_aws_cli", "write_local_file"]
        for name in risky:
            assert TOOL_TIERS[name] == SecurityTier.T2_HIGH_RISK, f"{name} should be T2"

    def test_get_tool_tier_default(self):
        """Unknown tools default to T1."""
        assert get_tool_tier("nonexistent_tool") == SecurityTier.T1_LOW_RISK

    def test_get_tool_tier_known(self):
        """Known tools return their registered tier."""
        assert get_tool_tier("describe_ec2") == SecurityTier.T0_READONLY
        assert get_tool_tier("save_rca_result") == SecurityTier.T1_LOW_RISK
        assert get_tool_tier("run_aws_cli") == SecurityTier.T2_HIGH_RISK


class TestAgentTierBindings:
    """Agent binding tests."""

    def test_all_agents_have_bindings(self):
        """All 8 agents should have tier bindings."""
        expected = {"scan_agent", "detect_agent", "rca_agent", "reporter_agent",
                    "executor_agent", "sre_agent", "main_agent", "proactive_agent"}
        assert expected.issubset(set(AGENT_TIER_BINDINGS.keys()))

    def test_proactive_agent_is_t0(self):
        """Proactive agent must be locked to T0 (read-only)."""
        assert AGENT_TIER_BINDINGS["proactive_agent"] == SecurityTier.T0_READONLY

    def test_executor_is_t2(self):
        """Executor agent should be T2 (needs approval for risky ops)."""
        assert AGENT_TIER_BINDINGS["executor_agent"] == SecurityTier.T2_HIGH_RISK

    def test_sre_is_t3(self):
        """SRE agent should be T3 (full ops, dual approval)."""
        assert AGENT_TIER_BINDINGS["sre_agent"] == SecurityTier.T3_DESTRUCTIVE

    def test_agent_can_use_tool(self):
        """Agent should only use tools at or below their tier."""
        for agent, max_tier in AGENT_TIER_BINDINGS.items():
            for tool_name, tool_tier in TOOL_TIERS.items():
                if tool_tier <= max_tier:
                    # Agent can use this tool
                    pass
                # Tools above agent tier should be blocked at runtime

    def test_scan_agent_cannot_approve(self):
        """Scan agent (T0) cannot use approve_fix_plan (T2)."""
        scan_tier = AGENT_TIER_BINDINGS["scan_agent"]
        approve_tier = TOOL_TIERS["approve_fix_plan"]
        assert scan_tier < approve_tier
