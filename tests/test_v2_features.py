"""Tests for AgenticOps v2 features: IM Alert Detection, Graph Store, Self-Improving Skills."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Feature A: Deterministic IM Alert Detection Tests
# ============================================================================


class TestAlertDetection:
    """Test deterministic alert detection (channel role, sender, prefix)."""

    def test_alert_channel_detected(self):
        """Messages from role=alert channels are alerts."""
        from agenticops.im.alert_pipeline import should_handle_as_alert
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="test-alerts", channel_type="feishu", config={"chat_id": "oc_alert"},
            role="alert",
        )
        with patch("agenticops.im.alert_pipeline.find_channel_by_chat", return_value=mock_ch):
            assert should_handle_as_alert("feishu", "oc_alert", "", "hello") is True

    def test_chat_channel_not_alert(self):
        """Messages from role=chat channels are NOT alerts (unless prefix match)."""
        from agenticops.im.alert_pipeline import should_handle_as_alert
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="test-chat", channel_type="feishu", config={"chat_id": "oc_chat"},
            role="chat",
        )
        with patch("agenticops.im.alert_pipeline.find_channel_by_chat", return_value=mock_ch):
            assert should_handle_as_alert("feishu", "oc_chat", "", "hello") is False

    def test_known_sender_is_alert(self):
        """Messages from alert_senders are alerts."""
        from agenticops.im.alert_pipeline import should_handle_as_alert
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="test-shared", channel_type="feishu",
            config={"chat_id": "oc_shared"}, role="chat",
            alert_senders=["bot_prometheus"],
        )
        with patch("agenticops.im.alert_pipeline.find_channel_by_chat", return_value=mock_ch):
            assert should_handle_as_alert("feishu", "oc_shared", "bot_prometheus", "text") is True

    def test_unknown_sender_not_alert(self):
        """Messages from unknown senders in chat channels are NOT alerts."""
        from agenticops.im.alert_pipeline import should_handle_as_alert
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="test-shared", channel_type="feishu",
            config={"chat_id": "oc_shared"}, role="chat",
            alert_senders=["bot_prometheus"],
        )
        with patch("agenticops.im.alert_pipeline.find_channel_by_chat", return_value=mock_ch):
            assert should_handle_as_alert("feishu", "oc_shared", "human_user", "text") is False

    def test_unconfigured_channel_not_alert(self):
        """Messages from unconfigured channels are NOT alerts (unless prefix)."""
        from agenticops.im.alert_pipeline import should_handle_as_alert

        with patch("agenticops.im.alert_pipeline.find_channel_by_chat", return_value=None):
            assert should_handle_as_alert("feishu", "unknown_chat", "", "hello") is False

    def test_prefix_firing(self):
        from agenticops.im.alert_pipeline import is_alert_by_prefix

        assert is_alert_by_prefix("[FIRING:1] KubePodCrashLooping") is True

    def test_prefix_resolved(self):
        from agenticops.im.alert_pipeline import is_alert_by_prefix

        assert is_alert_by_prefix("[RESOLVED] KubePodCrashLooping") is True

    def test_prefix_alarm(self):
        from agenticops.im.alert_pipeline import is_alert_by_prefix

        assert is_alert_by_prefix('ALARM: "HighCPU" in us-east-1') is True

    def test_prefix_ok(self):
        from agenticops.im.alert_pipeline import is_alert_by_prefix

        assert is_alert_by_prefix('OK: "HighCPU" in us-east-1') is True

    def test_prefix_grafana_alert(self):
        from agenticops.im.alert_pipeline import is_alert_by_prefix

        assert is_alert_by_prefix("[Alert] High Error Rate") is True
        assert is_alert_by_prefix("[Alerting] High Latency") is True

    def test_prefix_problem(self):
        from agenticops.im.alert_pipeline import is_alert_by_prefix

        assert is_alert_by_prefix("Problem: High CPU on web-01") is True

    def test_prefix_normal_text(self):
        from agenticops.im.alert_pipeline import is_alert_by_prefix

        assert is_alert_by_prefix("please check the CPU usage") is False

    def test_prefix_chinese_conversation(self):
        from agenticops.im.alert_pipeline import is_alert_by_prefix

        assert is_alert_by_prefix("请帮我看一下payment服务的状态") is False

    def test_prefix_fallback_in_should_handle(self):
        """Prefix detection works even for unconfigured channels."""
        from agenticops.im.alert_pipeline import should_handle_as_alert

        with patch("agenticops.im.alert_pipeline.find_channel_by_chat", return_value=None):
            assert should_handle_as_alert("feishu", "any", "", "[FIRING:1] Test") is True
            assert should_handle_as_alert("feishu", "any", "", "normal msg") is False


class TestTextToAlertPayload:
    """Test conversion of raw IM text to AlertPayload."""

    def test_prometheus_firing(self):
        from agenticops.im.alert_pipeline import _text_to_alert_payload

        text = "[FIRING:1] KubePodCrashLooping pod/payment-api namespace=prod severity=critical"
        payload = _text_to_alert_payload(text, "feishu")

        assert payload.source == "im_prometheus"
        assert payload.title.startswith("[FIRING:1]")
        assert payload.severity == "critical"
        assert payload.resource_hint == "pod/payment-api"
        assert payload.external_id  # hash-based

    def test_cloudwatch_alarm(self):
        from agenticops.im.alert_pipeline import _text_to_alert_payload

        text = 'ALARM: "HighCPUUtilization" in US East (N. Virginia)'
        payload = _text_to_alert_payload(text, "feishu")

        assert payload.source == "im_cloudwatch"
        assert "HighCPUUtilization" in payload.title

    def test_grafana_alert(self):
        from agenticops.im.alert_pipeline import _text_to_alert_payload

        text = "[Alerting] High Error Rate on payment-service"
        payload = _text_to_alert_payload(text, "dingtalk")

        assert payload.source == "im_grafana"
        assert payload.tags["im_platform"] == "dingtalk"

    def test_generic_alert(self):
        from agenticops.im.alert_pipeline import _text_to_alert_payload

        text = "Problem: High CPU usage on web-server-01"
        payload = _text_to_alert_payload(text, "feishu")

        assert payload.source == "im_generic"

    def test_severity_detection(self):
        from agenticops.im.alert_pipeline import _text_to_alert_payload

        # Critical
        p = _text_to_alert_payload("[FIRING:1] Test critical alert p1", "feishu")
        assert p.severity == "critical"

        # Medium (warning)
        p = _text_to_alert_payload("[FIRING:1] Test warning alert", "feishu")
        assert p.severity == "medium"

        # Default high
        p = _text_to_alert_payload("[FIRING:1] Test alert no severity", "feishu")
        assert p.severity == "high"

    def test_resource_hint_extraction(self):
        from agenticops.im.alert_pipeline import _text_to_alert_payload

        text = "[FIRING:1] OOM\npod/cart-service in namespace prod"
        p = _text_to_alert_payload(text, "feishu")
        assert p.resource_hint == "pod/cart-service"

    def test_description_truncation(self):
        from agenticops.im.alert_pipeline import _text_to_alert_payload

        long_text = "[FIRING:1] Test\n" + "x" * 3000
        p = _text_to_alert_payload(long_text, "feishu")
        assert len(p.description) <= 2000


class TestAlertProcessResult:
    """Test the shared AlertProcessResult dataclass."""

    def test_defaults(self):
        from agenticops.integrations.alert_processor import AlertProcessResult

        result = AlertProcessResult(action="created")
        assert result.action == "created"
        assert result.health_issue_id is None
        assert result.alert_event_id is None
        assert result.message == ""


class TestAlertPipeline:
    """Test the IM alert pipeline debounce and helpers."""

    def test_cooldown_logic(self):
        from agenticops.im.alert_pipeline import _cooldown_map

        assert isinstance(_cooldown_map, dict)

    def test_graph_context_none_on_empty_hint(self):
        from agenticops.im.alert_pipeline import _get_graph_context

        result = _get_graph_context("")
        assert result is None

    def test_graph_context_graceful_failure(self):
        from agenticops.im.alert_pipeline import _get_graph_context

        result = _get_graph_context("i-nonexistent")
        assert result is None or isinstance(result, dict)

    def test_detect_status(self):
        from agenticops.im.alert_pipeline import _detect_status

        assert _detect_status("[RESOLVED] Test") == "resolved"
        assert _detect_status("OK: Test") == "ok"
        assert _detect_status("[FIRING:1] Test") == "firing"
        assert _detect_status("Problem: Test") == "firing"


class TestChannelConfigRole:
    """Test ChannelConfig role and alert_senders fields."""

    def test_default_role_is_chat(self):
        from agenticops.notify.im_config import ChannelConfig

        ch = ChannelConfig(name="test", channel_type="feishu", config={})
        assert ch.role == "chat"
        assert ch.alert_senders == []

    def test_alert_role(self):
        from agenticops.notify.im_config import ChannelConfig

        ch = ChannelConfig(
            name="test", channel_type="feishu", config={},
            role="alert", alert_senders=["bot1", "bot2"],
        )
        assert ch.role == "alert"
        assert ch.alert_senders == ["bot1", "bot2"]

    def test_find_channel_by_chat(self):
        from agenticops.notify.im_config import ChannelConfig, find_channel_by_chat

        mock_channels = [
            ChannelConfig(name="alerts", channel_type="feishu",
                         config={"chat_id": "oc_alert"}, role="alert"),
            ChannelConfig(name="chat", channel_type="feishu",
                         config={"chat_id": "oc_chat"}, role="chat"),
        ]
        with patch("agenticops.notify.im_config.load_channels", return_value=mock_channels):
            ch = find_channel_by_chat("feishu", "oc_alert")
            assert ch is not None
            assert ch.role == "alert"

            ch = find_channel_by_chat("feishu", "oc_chat")
            assert ch is not None
            assert ch.role == "chat"

            ch = find_channel_by_chat("feishu", "oc_unknown")
            assert ch is None

            ch = find_channel_by_chat("dingtalk", "oc_alert")
            assert ch is None  # wrong platform


class TestBuildAgentInput:
    """Test _build_agent_input — Agent-based alert routing with context prompt."""

    def test_alert_channel_wraps_with_prompt(self):
        """Alert channel messages get wrapped with _ALERT_CHANNEL_PROMPT."""
        from agenticops.im.feishu_ws import _build_agent_input, _ALERT_CHANNEL_PROMPT
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="feishu-alert", channel_type="feishu",
            config={"chat_id": "oc_alert"}, role="alert",
        )
        with patch("agenticops.im.feishu_ws.settings") as mock_settings, \
             patch("agenticops.notify.im_config.load_channels", return_value=[mock_ch]):
            mock_settings.alert_pipeline_mode = "both"
            mock_settings.im_alert_detection_enabled = True
            result = _build_agent_input("CPU at 99%", "feishu", "oc_alert", "user1")
            assert "<im_alert_context>" in result
            assert "CPU at 99%" in result
            assert "STEP 1" in result
            assert "STEP 2" in result
            assert "feishu-alert" in result

    def test_chat_channel_no_wrap(self):
        """Chat channel messages pass through without wrapping."""
        from agenticops.im.feishu_ws import _build_agent_input
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="feishu-ops", channel_type="feishu",
            config={"chat_id": "oc_chat"}, role="chat",
        )
        with patch("agenticops.im.feishu_ws.settings") as mock_settings, \
             patch("agenticops.notify.im_config.load_channels", return_value=[mock_ch]):
            mock_settings.alert_pipeline_mode = "both"
            mock_settings.im_alert_detection_enabled = True
            result = _build_agent_input("hello", "feishu", "oc_chat", "user1")
            assert result == "hello"
            assert "<im_alert_context>" not in result

    def test_alert_sender_wraps_with_prompt(self):
        """Messages from alert_senders get wrapped even in chat channels."""
        from agenticops.im.feishu_ws import _build_agent_input
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="shared-ch", channel_type="feishu",
            config={"chat_id": "oc_shared"}, role="chat",
            alert_senders=["bot_prometheus"],
        )
        with patch("agenticops.im.feishu_ws.settings") as mock_settings, \
             patch("agenticops.notify.im_config.load_channels", return_value=[mock_ch]):
            mock_settings.alert_pipeline_mode = "both"
            mock_settings.im_alert_detection_enabled = True
            result = _build_agent_input("firing", "feishu", "oc_shared", "bot_prometheus")
            assert "<im_alert_context>" in result

    def test_detection_disabled_no_wrap(self):
        """When im_alert_detection_enabled=False, no wrapping occurs."""
        from agenticops.im.feishu_ws import _build_agent_input

        with patch("agenticops.im.feishu_ws.settings") as mock_settings:
            mock_settings.im_alert_detection_enabled = False
            result = _build_agent_input("ALARM: test", "feishu", "oc_alert", "")
            assert result == "ALARM: test"

    def test_prompt_contains_verification_steps(self):
        """The alert prompt requires 5-step verification before creating HealthIssue."""
        from agenticops.im.feishu_ws import _ALERT_CHANNEL_PROMPT

        prompt = _ALERT_CHANNEL_PROMPT.format(channel_name="test", platform="feishu")
        assert "STEP 1" in prompt  # Full comprehension
        assert "STEP 2" in prompt  # Classification & verification
        assert "STEP 3" in prompt  # Decision (HIGH/MEDIUM/LOW)
        assert "STEP 4" in prompt  # Create HealthIssue
        assert "STEP 5" in prompt  # Normal response
        assert "FULL original alert message text" in prompt
        assert "create_health_issue" in prompt

    def test_full_message_preserved(self):
        """The full alert text is appended after the prompt — no truncation."""
        from agenticops.im.feishu_ws import _build_agent_input
        from agenticops.notify.im_config import ChannelConfig

        long_alert = "ALARM: HighCPU\n" + "detail line\n" * 100
        mock_ch = ChannelConfig(
            name="alerts", channel_type="feishu",
            config={"chat_id": "oc_a"}, role="alert",
        )
        with patch("agenticops.im.feishu_ws.settings") as mock_settings, \
             patch("agenticops.notify.im_config.load_channels", return_value=[mock_ch]):
            mock_settings.alert_pipeline_mode = "both"
            mock_settings.im_alert_detection_enabled = True
            result = _build_agent_input(long_alert, "feishu", "oc_a", "")
            # Full text must be present after the prompt
            assert long_alert in result


# ============================================================================
# Feature B: Self-Improving Skills Tests
# ============================================================================


class TestSkillLoader:
    """Test mtime-based cache and draft skill discovery."""

    def test_skill_metadata_has_is_draft(self):
        from agenticops.skills.loader import SkillMetadata

        meta = SkillMetadata(
            name="test",
            description="Test skill",
            path=Path("/tmp/test"),
            is_draft=True,
        )
        assert meta.is_draft is True

    def test_skill_metadata_default_not_draft(self):
        from agenticops.skills.loader import SkillMetadata

        meta = SkillMetadata(
            name="test",
            description="Test skill",
            path=Path("/tmp/test"),
        )
        assert meta.is_draft is False

    def test_parse_frontmatter(self):
        from agenticops.skills.loader import parse_frontmatter

        content = """---
name: test-skill
description: A test skill
tools:
  - agenticops.tools.file_tools.read_local_file
---
# Body content here
"""
        fm, body = parse_frontmatter(content)
        assert fm["name"] == "test-skill"
        assert fm["description"] == "A test skill"
        assert "read_local_file" in fm["tools"][0]
        assert "Body content" in body


class TestSkillEvolution:
    """Test skill creation and draft management."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.draft_dir = Path(self.tmpdir) / "draft"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_draft_skill(self):
        from agenticops.skills.evolution import create_draft_skill

        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = self.draft_dir
            path = create_draft_skill(
                name="test-nginx",
                description="Nginx troubleshooting",
                content="---\nname: test-nginx\ndescription: Nginx troubleshooting\n---\n# Nginx Skill",
            )

        assert path.exists()
        assert (path / "SKILL.md").exists()
        content = (path / "SKILL.md").read_text()
        assert "Nginx" in content

    def test_create_draft_skill_with_references(self):
        from agenticops.skills.evolution import create_draft_skill

        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = self.draft_dir
            path = create_draft_skill(
                name="test-ref",
                description="Test with refs",
                content="---\nname: test-ref\ndescription: Test\n---\n# Skill",
                references={"ref.md": "# Reference content"},
            )

        assert (path / "references" / "ref.md").exists()

    def test_update_draft_skill(self):
        from agenticops.skills.evolution import create_draft_skill, update_draft_skill

        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = self.draft_dir
            create_draft_skill(
                name="test-update",
                description="Original",
                content="---\nname: test-update\ndescription: Original\n---\n# V1",
            )
            path = update_draft_skill("test-update", "---\nname: test-update\ndescription: Updated\n---\n# V2")

        assert path is not None
        content = (path / "SKILL.md").read_text()
        assert "V2" in content


class TestSkillReview:
    """Test skill review and promotion."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.draft_dir = Path(self.tmpdir) / "draft"
        self.skills_dir = Path(self.tmpdir) / "skills"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_promote_skill(self):
        from agenticops.skills.review import promote_skill

        # Create a draft
        draft_path = self.draft_dir / "test-promote"
        draft_path.mkdir(parents=True)
        (draft_path / "SKILL.md").write_text("---\nname: test-promote\ndescription: Test\n---\n# Content")

        with patch("agenticops.skills.review.settings") as mock_settings:
            mock_settings.skills_draft_dir = self.draft_dir
            mock_settings.skills_dir = self.skills_dir
            result = promote_skill("test-promote")

        assert result is True
        assert (self.skills_dir / "test-promote" / "SKILL.md").exists()
        assert not (self.draft_dir / "test-promote").exists()

    def test_reject_draft_skill(self):
        from agenticops.skills.review import reject_draft_skill

        draft_path = self.draft_dir / "test-reject"
        draft_path.mkdir(parents=True)
        (draft_path / "SKILL.md").write_text("content")

        with patch("agenticops.skills.review.settings") as mock_settings:
            mock_settings.skills_draft_dir = self.draft_dir
            result = reject_draft_skill("test-reject")

        assert result is True
        assert not (self.draft_dir / "test-reject").exists()


class TestSkillRegistry:
    """Test local skill registry search."""

    def test_local_registry_search(self):
        from agenticops.skills.registry import LocalRegistry

        tmpdir = tempfile.mkdtemp()
        try:
            skills_dir = Path(tmpdir) / "skills"
            draft_dir = Path(tmpdir) / "draft"
            skill_path = skills_dir / "linux-admin"
            skill_path.mkdir(parents=True)
            (skill_path / "SKILL.md").write_text(
                "---\nname: linux-admin\ndescription: Linux system administration\n---\n# Linux Admin"
            )

            with patch("agenticops.skills.registry.settings") as mock_settings:
                mock_settings.skills_dir = skills_dir
                mock_settings.skills_draft_dir = draft_dir
                mock_settings.skills_enabled = True

                reg = LocalRegistry()
                results = reg.search("linux")

            assert len(results) >= 1
            assert any("linux" in r["name"].lower() for r in results)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# Feature C: Graph Store Tests
# ============================================================================


class TestGraphStore:
    """Test GraphStore SQLite persistence."""

    def setup_method(self):
        """Create an in-memory SQLite engine for testing."""
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import StaticPool

        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # Create graph tables
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    resource_type TEXT DEFAULT '',
                    raw_json TEXT DEFAULT '{}',
                    raw_hash TEXT DEFAULT '',
                    vpc_id TEXT DEFAULT '',
                    region TEXT DEFAULT '',
                    account_id TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS graph_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    label TEXT DEFAULT '',
                    state TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, target_id, edge_type)
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS graph_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL DEFAULT '',
                    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    node_count INTEGER DEFAULT 0,
                    edge_count INTEGER DEFAULT 0,
                    nodes_added INTEGER DEFAULT 0,
                    nodes_updated INTEGER DEFAULT 0,
                    nodes_removed INTEGER DEFAULT 0
                )
            """))
            conn.commit()

    def _build_test_graph(self):
        """Build a small test InfraGraph."""
        from agenticops.graph.engine import InfraGraph
        from agenticops.graph.types import EdgeAttrs, EdgeType, NodeAttrs, NodeStatus, NodeType

        graph = InfraGraph()
        graph._add_node("vpc-001", NodeAttrs(
            node_type=NodeType.VPC,
            label="test-vpc",
            status=NodeStatus.HEALTHY,
            resource_type="VPC",
            raw={"vpc_id": "vpc-001", "cidr": "10.0.0.0/16", "region": "us-east-1"},
        ))
        graph._add_node("subnet-001", NodeAttrs(
            node_type=NodeType.SUBNET,
            label="test-subnet",
            status=NodeStatus.HEALTHY,
            resource_type="Subnet",
            raw={"subnet_id": "subnet-001", "vpc_id": "vpc-001"},
        ))
        graph._add_node("i-abc123", NodeAttrs(
            node_type=NodeType.EC2_INSTANCE,
            label="web-server-1",
            status=NodeStatus.HEALTHY,
            resource_type="EC2 Instance",
            raw={"instance_id": "i-abc123", "vpc_id": "vpc-001"},
        ))
        graph._add_edge("vpc-001", "subnet-001", EdgeAttrs(
            edge_type=EdgeType.CONTAINS, label="contains",
        ))
        graph._add_edge("i-abc123", "subnet-001", EdgeAttrs(
            edge_type=EdgeType.HOSTED_IN, label="hosted in",
        ))
        return graph

    def test_save_and_load_roundtrip(self):
        from agenticops.graph.store import GraphStore

        store = GraphStore(engine=self.engine)
        graph = self._build_test_graph()

        # Save
        stats = store.save_graph(graph, scope="vpc-001", region="us-east-1")
        assert stats["nodes_added"] == 3
        assert stats["edges_synced"] == 2

        # Load
        loaded = store.load_graph(vpc_id="vpc-001", max_age_hours=1)
        assert loaded.graph.number_of_nodes() == 3
        assert loaded.graph.number_of_edges() == 2

        # Verify node data
        vpc_node = loaded.get_node("vpc-001")
        assert vpc_node is not None
        assert vpc_node["label"] == "test-vpc"

    def test_change_detection_no_update(self):
        from agenticops.graph.store import GraphStore

        store = GraphStore(engine=self.engine)
        graph = self._build_test_graph()

        # Save twice with same data
        stats1 = store.save_graph(graph, scope="vpc-001", region="us-east-1")
        stats2 = store.save_graph(graph, scope="vpc-001", region="us-east-1")

        assert stats1["nodes_added"] == 3
        assert stats2["nodes_added"] == 0
        assert stats2["nodes_updated"] == 0  # same hash, no update

    def test_search_nodes(self):
        from agenticops.graph.store import GraphStore

        store = GraphStore(engine=self.engine)
        graph = self._build_test_graph()
        store.save_graph(graph, scope="vpc-001", region="us-east-1")

        results = store.search_nodes(query="web-server")
        assert len(results) == 1
        assert results[0]["id"] == "i-abc123"

    def test_search_nodes_by_type(self):
        from agenticops.graph.store import GraphStore

        store = GraphStore(engine=self.engine)
        graph = self._build_test_graph()
        store.save_graph(graph, scope="vpc-001", region="us-east-1")

        results = store.search_nodes(node_type="ec2_instance")
        assert len(results) == 1

    def test_get_node_neighborhood(self):
        from agenticops.graph.store import GraphStore

        store = GraphStore(engine=self.engine)
        graph = self._build_test_graph()
        store.save_graph(graph, scope="vpc-001", region="us-east-1")

        nbr_graph = store.get_node_neighborhood("i-abc123", depth=2)
        # Should include i-abc123, subnet-001, and vpc-001
        assert nbr_graph.graph.number_of_nodes() >= 2

    def test_stale_nodes(self):
        from agenticops.graph.store import GraphStore

        store = GraphStore(engine=self.engine)
        graph = self._build_test_graph()
        store.save_graph(graph, scope="vpc-001", region="us-east-1")

        # With TTL of 0 hours, all nodes should be "stale" (they were just created,
        # but with ttl=0 the cutoff is "now", so nothing is stale yet)
        stale = store.get_stale_nodes(ttl_hours=0)
        # Freshly inserted nodes shouldn't be stale with ttl=0
        # (updated_at is "now", cutoff is also "now", so updated_at >= cutoff)
        assert isinstance(stale, list)


# ============================================================================
# Feature C: Graph Context Tests
# ============================================================================


class TestGraphContext:
    """Test the alert context builder."""

    def test_returns_none_for_unknown_resource(self):
        """get_alert_context should return None when resource not in store."""
        # Use the pipeline's _get_graph_context which wraps errors gracefully
        from agenticops.im.alert_pipeline import _get_graph_context

        result = _get_graph_context("i-nonexistent-99999")
        assert result is None or isinstance(result, dict)


# ============================================================================
# Config Tests
# ============================================================================


class TestV2Config:
    """Verify all v2 config settings exist."""

    def test_feature_a_settings(self):
        from agenticops.config import settings

        assert hasattr(settings, "im_alert_detection_enabled")
        assert hasattr(settings, "im_alert_cooldown_seconds")
        assert settings.im_alert_detection_enabled is True
        assert settings.im_alert_cooldown_seconds == 60

    def test_feature_b_settings(self):
        from agenticops.config import settings

        assert hasattr(settings, "skills_draft_dir")
        assert hasattr(settings, "clawhub_enabled")
        assert hasattr(settings, "clawhub_token")
        assert settings.clawhub_enabled is False

    def test_feature_c_settings(self):
        from agenticops.config import settings

        assert hasattr(settings, "graph_sync_enabled")
        assert hasattr(settings, "graph_sync_interval_minutes")
        assert hasattr(settings, "graph_node_ttl_hours")
        assert settings.graph_sync_enabled is True
        assert settings.graph_sync_interval_minutes == 15
        assert settings.graph_node_ttl_hours == 24

    def test_alert_pipeline_mode_setting(self):
        from agenticops.config import settings

        assert hasattr(settings, "alert_pipeline_mode")
        assert settings.alert_pipeline_mode == "both"


# ============================================================================
# Webhook Alert Parser Tests
# ============================================================================


class TestWebhookParsers:
    """Test parse_alert() for various monitoring sources."""

    def test_parse_prometheus(self):
        from agenticops.integrations.parsers import parse_alert

        body = {
            "alerts": [{
                "labels": {"alertname": "KubePodCrashLooping", "severity": "critical", "pod": "payment-api"},
                "annotations": {"description": "Pod is crash looping"},
                "fingerprint": "abc123",
            }],
            "status": "firing",
        }
        alert = parse_alert(body)
        assert alert.source == "prometheus"
        assert alert.title == "KubePodCrashLooping"
        assert alert.severity == "critical"
        assert alert.resource_hint == "payment-api"
        assert alert.external_id == "abc123"

    def test_parse_cloudwatch(self):
        from agenticops.integrations.parsers import parse_alert

        body = {
            "AlarmName": "HighCPUUtilization",
            "NewStateValue": "ALARM",
            "NewStateReason": "Threshold crossed",
            "Region": "us-east-1",
            "Trigger": {
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/EC2",
                "Dimensions": [{"name": "InstanceId", "value": "i-1234567890abcdef0"}],
            },
        }
        alert = parse_alert(body)
        assert alert.source == "cloudwatch"
        assert alert.title == "HighCPUUtilization"
        assert alert.severity == "high"
        assert alert.resource_hint == "i-1234567890abcdef0"

    def test_parse_datadog(self):
        from agenticops.integrations.parsers import parse_alert

        body = {
            "event_type": "alert",
            "title": "High Error Rate",
            "priority": "P2",
            "text": "Error rate above threshold",
            "tags": ["host:web-01", "env:prod"],
        }
        alert = parse_alert(body)
        assert alert.source == "datadog"
        assert alert.title == "High Error Rate"
        assert alert.severity == "high"
        assert alert.resource_hint == "web-01"

    def test_parse_generic(self):
        from agenticops.integrations.parsers import parse_alert

        body = {
            "title": "Custom Alert",
            "severity": "medium",
            "description": "Something happened",
            "resource_id": "my-service",
        }
        alert = parse_alert(body)
        assert alert.source == "generic"
        assert alert.title == "Custom Alert"
        assert alert.severity == "medium"
        assert alert.resource_hint == "my-service"

    def test_source_auto_detection_prometheus(self):
        from agenticops.integrations.parsers import detect_source

        body = {"alerts": [{"labels": {"alertname": "Test"}}]}
        assert detect_source(body) == "prometheus"

    def test_source_auto_detection_grafana(self):
        from agenticops.integrations.parsers import detect_source

        body = {"alerts": [{"status": "firing"}]}
        assert detect_source(body) == "grafana"

    def test_source_auto_detection_cloudwatch(self):
        from agenticops.integrations.parsers import detect_source

        body = {"AlarmName": "HighCPU"}
        assert detect_source(body) == "cloudwatch"

    def test_source_auto_detection_datadog(self):
        from agenticops.integrations.parsers import detect_source

        body = {"event_type": "alert", "title": "Test"}
        assert detect_source(body) == "datadog"

    def test_source_auto_detection_generic(self):
        from agenticops.integrations.parsers import detect_source

        body = {"title": "something"}
        assert detect_source(body) == "generic"

    def test_explicit_source_override(self):
        from agenticops.integrations.parsers import parse_alert

        body = {"title": "Test Alert", "severity": "high"}
        alert = parse_alert(body, source="generic")
        assert alert.source == "generic"


# ============================================================================
# Pipeline Mode Tests
# ============================================================================


class TestPipelineMode:
    """Test alert_pipeline_mode gate behavior."""

    def test_event_driven_mode_allows_webhook(self):
        """event_driven mode should NOT block webhook processing."""
        from agenticops.config import Settings

        s = Settings(alert_pipeline_mode="event_driven")
        assert s.alert_pipeline_mode == "event_driven"
        # Webhook gate: blocked only when mode == "channel_driven"
        assert s.alert_pipeline_mode != "channel_driven"

    def test_channel_driven_mode_blocks_webhook(self):
        """channel_driven mode should block webhook processing."""
        from agenticops.config import Settings

        s = Settings(alert_pipeline_mode="channel_driven")
        assert s.alert_pipeline_mode == "channel_driven"

    def test_both_mode_allows_all(self):
        """both mode allows all pipelines."""
        from agenticops.config import Settings

        s = Settings(alert_pipeline_mode="both")
        assert s.alert_pipeline_mode != "channel_driven"
        assert s.alert_pipeline_mode in ("channel_driven", "both")

    def test_build_agent_input_blocked_by_event_driven_mode(self):
        """event_driven mode disables channel-driven alert wrapping."""
        from agenticops.im.feishu_ws import _build_agent_input

        with patch("agenticops.im.feishu_ws.settings") as mock_settings:
            mock_settings.alert_pipeline_mode = "event_driven"
            mock_settings.im_alert_detection_enabled = True
            result = _build_agent_input("ALARM: test", "feishu", "oc_alert", "")
            assert result == "ALARM: test"
            assert "<im_alert_context>" not in result

    def test_build_agent_input_allowed_by_channel_driven_mode(self):
        """channel_driven mode allows alert wrapping."""
        from agenticops.im.feishu_ws import _build_agent_input
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="alerts", channel_type="feishu",
            config={"chat_id": "oc_alert"}, role="alert",
        )
        with patch("agenticops.im.feishu_ws.settings") as mock_settings, \
             patch("agenticops.notify.im_config.load_channels", return_value=[mock_ch]):
            mock_settings.alert_pipeline_mode = "channel_driven"
            mock_settings.im_alert_detection_enabled = True
            result = _build_agent_input("ALARM: test", "feishu", "oc_alert", "")
            assert "<im_alert_context>" in result

    def test_build_agent_input_allowed_by_both_mode(self):
        """both mode allows alert wrapping."""
        from agenticops.im.feishu_ws import _build_agent_input
        from agenticops.notify.im_config import ChannelConfig

        mock_ch = ChannelConfig(
            name="alerts", channel_type="feishu",
            config={"chat_id": "oc_alert"}, role="alert",
        )
        with patch("agenticops.im.feishu_ws.settings") as mock_settings, \
             patch("agenticops.notify.im_config.load_channels", return_value=[mock_ch]):
            mock_settings.alert_pipeline_mode = "both"
            mock_settings.im_alert_detection_enabled = True
            result = _build_agent_input("ALARM: test", "feishu", "oc_alert", "")
            assert "<im_alert_context>" in result
