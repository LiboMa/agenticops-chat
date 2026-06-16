"""Tests for the P4 simulation gate: impact_severity policy matching and
account-scoped blast-radius/node lookup in the policy engine."""

from unittest.mock import MagicMock, patch

from agenticops.services.policy_engine import PolicyEngine, _find_graph_node


def _engine_with_impact_rule() -> PolicyEngine:
    return PolicyEngine({
        "version": 1,
        "defaults": {"action": "require_human"},
        "rules": [
            {
                "name": "impact-severity-escalation",
                "match": {"impact_severity": ["critical", "high"]},
                "action": "escalate",
            },
            {
                "name": "auto-approve-low-risk",
                "match": {"risk_level": ["L0", "L1"]},
                "action": "auto_approve",
            },
            {
                "name": "l2-l3-human",
                "match": {"risk_level": ["L2", "L3"]},
                "action": "require_human",
            },
        ],
    })


class TestImpactSeverityMatching:
    def test_high_impact_escalates_l1_to_human(self):
        # L1 + high simulated impact: escalate bumps to L2 → require_human
        decision = _engine_with_impact_rule().evaluate(
            risk_level="L1", impact_severity="high"
        )
        assert decision.action == "require_human"
        assert decision.effective_risk_level == "L2"
        assert decision.escalated_from == "L1"

    def test_low_impact_does_not_match(self):
        decision = _engine_with_impact_rule().evaluate(
            risk_level="L1", impact_severity="low"
        )
        assert decision.action == "auto_approve"
        assert decision.rule_name == "auto-approve-low-risk"

    def test_none_impact_behaves_as_today(self):
        # Fail-soft: no graph data → impact_severity=None → rule doesn't match
        decision = _engine_with_impact_rule().evaluate(
            risk_level="L1", impact_severity=None
        )
        assert decision.action == "auto_approve"

    def test_default_policies_yaml_still_valid(self):
        # The shipped config/policies.yaml (with the new rule) must load
        engine = PolicyEngine.from_yaml("config/policies.yaml")
        rule_names = [r.get("name") for r in engine.rules]
        assert "impact-severity-escalation" in rule_names


class TestAccountScopedNodeLookup:
    def _store_with_hits(self, hits):
        store = MagicMock()
        store.search_nodes.return_value = hits
        return store

    def test_filters_by_account(self):
        hits = [
            {"id": "i-abc", "account_id": "111111111111"},
            {"id": "i-abc", "account_id": "222222222222"},
        ]
        with patch("agenticops.graph.store.GraphStore", return_value=self._store_with_hits(hits)):
            node = _find_graph_node("i-abc", account_id="222222222222")
        assert node == "i-abc"

    def test_account_mismatch_returns_none(self):
        hits = [{"id": "i-abc", "account_id": "111111111111"}]
        with patch("agenticops.graph.store.GraphStore", return_value=self._store_with_hits(hits)):
            node = _find_graph_node("i-abc", account_id="999999999999")
        assert node is None

    def test_no_account_filter_keeps_all(self):
        hits = [{"id": "i-abc", "account_id": "111111111111"}]
        with patch("agenticops.graph.store.GraphStore", return_value=self._store_with_hits(hits)):
            node = _find_graph_node("i-abc")
        assert node == "i-abc"

    def test_prefers_exact_id_match(self):
        hits = [
            {"id": "i-abc123-extra", "account_id": ""},
            {"id": "i-abc123", "account_id": ""},
        ]
        with patch("agenticops.graph.store.GraphStore", return_value=self._store_with_hits(hits)):
            node = _find_graph_node("i-abc123")
        assert node == "i-abc123"


class TestSimulateFixImpact:
    def test_returns_none_without_resource(self):
        from agenticops.services.policy_engine import simulate_fix_impact

        assert simulate_fix_impact(None) is None
        assert simulate_fix_impact("") is None

    def test_returns_impact_dict(self):
        from agenticops.services.policy_engine import simulate_fix_impact

        impact_result = MagicMock()
        impact_result.severity = "high"
        impact_result.affected_nodes = ["a", "b", "c"]
        impact_result.isolated_subnets = ["subnet-1"]
        impact_result.lost_connections = [("a", "b")]

        store = MagicMock()
        store.search_nodes.return_value = [{"id": "i-abc", "account_id": ""}]
        store.get_node_neighborhood.return_value = MagicMock()

        with patch("agenticops.graph.store.GraphStore", return_value=store), \
             patch("agenticops.graph.algorithms.impact_analysis", return_value=impact_result):
            result = simulate_fix_impact("i-abc")

        assert result == {
            "severity": "high",
            "affected_nodes": 3,
            "isolated_subnets": 1,
            "lost_connections": 1,
        }

    def test_fail_soft_on_graph_error(self):
        from agenticops.services.policy_engine import simulate_fix_impact

        with patch("agenticops.graph.store.GraphStore", side_effect=RuntimeError("no db")):
            assert simulate_fix_impact("i-abc") is None
