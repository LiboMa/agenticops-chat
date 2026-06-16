"""Tests for the P2 RCA topology-context injection (_build_topology_context)."""

from unittest.mock import MagicMock, patch

from agenticops.agents.rca_agent import _build_topology_context


def _alert_ctx():
    return {
        "topology_summary": "ec2 'web-1' (i-abc), in VPC vpc-1, 3 direct neighbors",
        "dependencies": {
            "downstream": [
                {"id": "elb-1", "label": "web-alb", "node_type": "elb", "edge_type": "ROUTES_TO"},
            ],
            "upstream": [
                {"id": "subnet-1", "label": "private-a", "node_type": "subnet", "edge_type": "CONTAINS"},
            ],
        },
    }


def _snapshots(changed=True):
    if changed:
        return [
            {"id": 2, "scope": "vpc-1", "snapshot_at": "2026-06-12 01:00:00",
             "node_count": 50, "edge_count": 80,
             "nodes_added": 2, "nodes_updated": 1, "nodes_removed": 0},
        ]
    return [
        {"id": 1, "scope": "vpc-1", "snapshot_at": "2026-06-11 01:00:00",
         "node_count": 48, "edge_count": 78,
         "nodes_added": 0, "nodes_updated": 0, "nodes_removed": 0},
    ]


class TestBuildTopologyContext:
    def test_full_block(self):
        store = MagicMock()
        store.get_recent_snapshots.return_value = _snapshots(changed=True)
        with patch("agenticops.graph.context.get_alert_context", return_value=_alert_ctx()), \
             patch("agenticops.graph.store.GraphStore", return_value=store):
            block = _build_topology_context("i-abc")

        assert block.startswith("TOPOLOGY CONTEXT")
        assert "web-1" in block
        assert "Downstream dependents: web-alb (elb)" in block
        assert "Upstream dependencies: private-a (subnet)" in block
        assert "Recent topology changes" in block
        assert "+2 added" in block

    def test_no_changes_omits_change_section(self):
        store = MagicMock()
        store.get_recent_snapshots.return_value = _snapshots(changed=False)
        with patch("agenticops.graph.context.get_alert_context", return_value=_alert_ctx()), \
             patch("agenticops.graph.store.GraphStore", return_value=store):
            block = _build_topology_context("i-abc")
        assert "Recent topology changes" not in block
        assert "Resource position" in block

    def test_empty_when_resource_unknown(self):
        assert _build_topology_context("") == ""
        assert _build_topology_context("unknown") == ""

    def test_disabled_by_settings(self):
        with patch("agenticops.agents.rca_agent.settings") as mock_settings:
            mock_settings.rca_topology_context_enabled = False
            assert _build_topology_context("i-abc") == ""

    def test_fail_soft_on_error(self):
        with patch("agenticops.graph.context.get_alert_context", side_effect=RuntimeError("boom")):
            assert _build_topology_context("i-abc") == ""

    def test_truncated_to_max_chars(self):
        ctx = _alert_ctx()
        ctx["topology_summary"] = "x" * 5000
        store = MagicMock()
        store.get_recent_snapshots.return_value = []
        with patch("agenticops.graph.context.get_alert_context", return_value=ctx), \
             patch("agenticops.graph.store.GraphStore", return_value=store):
            block = _build_topology_context("i-abc", max_chars=2000)
        assert len(block) <= 2000

    def test_no_graph_data_returns_empty(self):
        store = MagicMock()
        store.get_recent_snapshots.return_value = []
        with patch("agenticops.graph.context.get_alert_context", return_value=None), \
             patch("agenticops.graph.store.GraphStore", return_value=store):
            assert _build_topology_context("i-abc") == ""
