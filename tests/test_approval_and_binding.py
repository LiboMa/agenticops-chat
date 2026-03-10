"""Tests for approval_token + agent_binding."""

import time
import pytest
from agenticops.skills.approval_token import generate, verify, TOKEN_TTL
from agenticops.skills.agent_binding import (
    bind_agent,
    get_agent_tier,
    register_agent_tier,
    AGENT_TIER_BINDINGS,
)
from agenticops.skills._models import SecurityTier
from agenticops.skills._security import _agent_tier, _agent_id


class TestApprovalToken:
    def test_generate_and_verify(self):
        token = generate("scale_asg")
        ok, reason = verify(token, "scale_asg")
        assert ok, reason

    def test_wrong_action(self):
        token = generate("scale_asg")
        ok, reason = verify(token, "delete_cluster")
        assert not ok
        assert "mismatch" in reason.lower()

    def test_expired_token(self):
        token = generate("test", ttl=-1)  # Already expired
        ok, reason = verify(token, "test")
        assert not ok
        assert "expired" in reason.lower()

    def test_tampered_signature(self):
        token = generate("test")
        tampered = token[:-5] + "XXXXX"
        ok, reason = verify(tampered, "test")
        assert not ok

    def test_invalid_format(self):
        ok, reason = verify("not-a-valid-token", "test")
        assert not ok

    def test_custom_ttl(self):
        token = generate("test", ttl=3600)
        ok, reason = verify(token, "test")
        assert ok


class TestAgentBinding:
    def test_bind_known_agent(self):
        tier = bind_agent("scan_agent")
        assert tier == SecurityTier.T0_READONLY
        assert _agent_id.get() == "scan_agent"
        assert _agent_tier.get() == SecurityTier.T0_READONLY

    def test_bind_executor(self):
        tier = bind_agent("executor_agent")
        assert tier == SecurityTier.T2_HIGH_RISK

    def test_bind_sre(self):
        tier = bind_agent("sre_agent")
        assert tier == SecurityTier.T3_DESTRUCTIVE

    def test_unknown_agent_defaults_t0(self):
        tier = bind_agent("random_agent")
        assert tier == SecurityTier.T0_READONLY

    def test_get_agent_tier(self):
        assert get_agent_tier("rca_agent") == SecurityTier.T1_LOW_RISK
        assert get_agent_tier("unknown") == SecurityTier.T0_READONLY

    def test_register_agent_tier(self):
        register_agent_tier("custom_agent", SecurityTier.T2_HIGH_RISK)
        assert get_agent_tier("custom_agent") == SecurityTier.T2_HIGH_RISK
        # Cleanup
        AGENT_TIER_BINDINGS.pop("custom_agent", None)

    def test_all_7_agents_bound(self):
        expected = {
            "scan_agent", "detect_agent", "rca_agent", "reporter_agent",
            "executor_agent", "sre_agent", "main_agent", "proactive_agent",
        }
        assert expected.issubset(set(AGENT_TIER_BINDINGS.keys()))


class TestSecureToolWithBinding:
    """Integration: bind_agent + @secure_tool."""

    def test_scan_agent_t0_allowed(self):
        from agenticops.skills._security import secure_tool

        bind_agent("scan_agent")

        @secure_tool(tier=SecurityTier.T0_READONLY, skill="test")
        def list_pods():
            return "pods"
        assert list_pods() == "pods"

    def test_scan_agent_t1_blocked(self):
        import json
        from agenticops.skills._security import secure_tool

        bind_agent("scan_agent")  # T0

        @secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="test")
        def restart_pod():
            return "restarted"
        result = json.loads(restart_pod())
        assert result["status"] == "blocked"

    def test_executor_t2_with_approval(self):
        import json
        from agenticops.skills._security import secure_tool
        from agenticops.skills.approval_token import generate

        bind_agent("executor_agent")  # T2

        @secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="test")
        def scale_asg(count=1, approval_token=None):
            return f"scaled to {count}"

        token = generate("scale_asg")
        assert scale_asg(count=3, approval_token=token) == "scaled to 3"
