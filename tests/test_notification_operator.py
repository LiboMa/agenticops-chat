"""Tests for the notification-operator skill.

Covers:
- ChannelConfig.preferred_format field and default mapping
- list_notification_channels tool
- distribute_report tool (with mocked NotificationManager)
- send_to_channel tool (existing, quick sanity check)
- Skill discovery and tool resolution
- Main agent / reporter agent prompt changes
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticops.models import Base, Report, get_session
from agenticops.notify.im_config import (
    ChannelConfig,
    _DEFAULT_PREFERRED_FORMAT,
    _CHANNEL_RESERVED_KEYS,
    _parse_channel,
    load_channels,
    get_channel,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url
    settings.reports_dir = tmp_path / "reports"
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def channels_yaml(tmp_path, monkeypatch):
    """Create a temporary channels.yaml for testing."""
    import agenticops.notify.im_config as im_mod
    from agenticops.config import settings

    yaml_content = """
channels:
  test-feishu:
    type: feishu
    enabled: true
    preferred_format: markdown
    app_name: default
    chat_id: "oc_test123"

  test-email:
    type: email
    enabled: true
    preferred_format: html
    smtp_host: localhost
    smtp_port: 587
    from_email: test@example.com
    to_emails: ["ops@example.com"]

  test-slack:
    type: slack
    enabled: true
    severity_filter: ["critical", "high"]
    webhook_url: "https://hooks.slack.com/test"
    channel: "#alerts"

  test-sns-report:
    type: sns-report
    enabled: true
    preferred_format: html
    topic_arn: "arn:aws:sns:us-east-1:123:test"
    s3_bucket: "test-bucket"
    formats: [html, markdown]

  disabled-channel:
    type: webhook
    enabled: false
    url: "https://example.com/webhook"
"""
    yaml_path = tmp_path / "channels.yaml"
    yaml_path.write_text(yaml_content)
    settings.channels_config = yaml_path

    # Invalidate cache
    im_mod._channels_cache = None
    im_mod._channels_mtime = 0.0

    yield yaml_path

    # Cleanup
    im_mod._channels_cache = None
    im_mod._channels_mtime = 0.0


@pytest.fixture
def sample_report(db_session):
    """Create a sample report in the DB."""
    report = Report(
        report_type="daily",
        title="Test Daily Report 2026-03-05",
        summary="3 issues detected, 1 critical resolved.",
        content_markdown="# Daily Report\n\n## Summary\n- 3 issues\n- 1 resolved\n\n## Details\n\nFull report here.",
        file_path="/tmp/test-report.md",
        report_metadata={"region": "us-east-1"},
    )
    db_session.add(report)
    db_session.commit()
    return report


# ============================================================================
# ChannelConfig.preferred_format tests
# ============================================================================


class TestPreferredFormat:
    """Tests for the preferred_format field on ChannelConfig."""

    def test_reserved_keys_includes_preferred_format(self):
        assert "preferred_format" in _CHANNEL_RESERVED_KEYS

    def test_default_format_map_has_all_types(self):
        expected_types = {"feishu", "dingtalk", "wecom", "slack", "email", "sns", "sns-report", "webhook"}
        assert set(_DEFAULT_PREFERRED_FORMAT.keys()) == expected_types

    def test_default_format_values(self):
        assert _DEFAULT_PREFERRED_FORMAT["feishu"] == "markdown"
        assert _DEFAULT_PREFERRED_FORMAT["email"] == "html"
        assert _DEFAULT_PREFERRED_FORMAT["sns"] == "text"
        assert _DEFAULT_PREFERRED_FORMAT["sns-report"] == "html"
        assert _DEFAULT_PREFERRED_FORMAT["slack"] == "markdown"

    def test_channel_config_has_preferred_format_field(self):
        ch = ChannelConfig(
            name="test",
            channel_type="slack",
            config={},
            preferred_format="html",
        )
        assert ch.preferred_format == "html"

    def test_channel_config_default_empty_string(self):
        ch = ChannelConfig(name="test", channel_type="slack", config={})
        assert ch.preferred_format == ""


class TestParseChannelPreferredFormat:
    """Tests for preferred_format parsing in _parse_channel."""

    def test_explicit_preferred_format(self):
        ch = _parse_channel("test", {"type": "feishu", "preferred_format": "html"})
        assert ch.preferred_format == "html"

    def test_default_feishu(self):
        ch = _parse_channel("test", {"type": "feishu"})
        assert ch.preferred_format == "markdown"

    def test_default_email(self):
        ch = _parse_channel("test", {"type": "email"})
        assert ch.preferred_format == "html"

    def test_default_sns(self):
        ch = _parse_channel("test", {"type": "sns"})
        assert ch.preferred_format == "text"

    def test_default_sns_report(self):
        ch = _parse_channel("test", {"type": "sns-report"})
        assert ch.preferred_format == "html"

    def test_default_slack(self):
        ch = _parse_channel("test", {"type": "slack"})
        assert ch.preferred_format == "markdown"

    def test_default_dingtalk(self):
        ch = _parse_channel("test", {"type": "dingtalk"})
        assert ch.preferred_format == "markdown"

    def test_default_wecom(self):
        ch = _parse_channel("test", {"type": "wecom"})
        assert ch.preferred_format == "markdown"

    def test_default_webhook(self):
        ch = _parse_channel("test", {"type": "webhook"})
        assert ch.preferred_format == "markdown"

    def test_unknown_type_defaults_to_markdown(self):
        ch = _parse_channel("test", {"type": "custom-type"})
        assert ch.preferred_format == "markdown"

    def test_preferred_format_not_in_config_dict(self):
        ch = _parse_channel("test", {
            "type": "feishu",
            "preferred_format": "html",
            "chat_id": "oc_123",
        })
        assert "preferred_format" not in ch.config
        assert "chat_id" in ch.config

    def test_type_not_in_config_dict(self):
        ch = _parse_channel("test", {"type": "feishu", "chat_id": "oc_123"})
        assert "type" not in ch.config


class TestLoadChannelsPreferredFormat:
    """Tests for preferred_format in load_channels and get_channel."""

    def test_load_channels_includes_preferred_format(self, channels_yaml):
        channels = load_channels()
        feishu = next(c for c in channels if c.name == "test-feishu")
        assert feishu.preferred_format == "markdown"

    def test_get_channel_includes_preferred_format(self, channels_yaml):
        ch = get_channel("test-email")
        assert ch is not None
        assert ch.preferred_format == "html"

    def test_channel_without_explicit_format_gets_default(self, channels_yaml):
        ch = get_channel("test-slack")
        assert ch is not None
        # slack type defaults to markdown
        assert ch.preferred_format == "markdown"


# ============================================================================
# list_notification_channels tool tests
# ============================================================================


class TestListNotificationChannels:
    """Tests for the list_notification_channels tool."""

    def test_returns_json(self, channels_yaml, db_session):
        from agenticops.tools.notification_tools import list_notification_channels

        result = list_notification_channels()
        data = json.loads(result)
        assert "channels" in data
        assert "im_aliases" in data

    def test_lists_all_channels(self, channels_yaml, db_session):
        from agenticops.tools.notification_tools import list_notification_channels

        result = list_notification_channels()
        data = json.loads(result)
        names = {c["name"] for c in data["channels"]}
        assert "test-feishu" in names
        assert "test-email" in names
        assert "test-slack" in names
        assert "test-sns-report" in names
        assert "disabled-channel" in names  # lists all, not just enabled

    def test_includes_preferred_format(self, channels_yaml, db_session):
        from agenticops.tools.notification_tools import list_notification_channels

        result = list_notification_channels()
        data = json.loads(result)
        feishu = next(c for c in data["channels"] if c["name"] == "test-feishu")
        assert feishu["preferred_format"] == "markdown"
        email = next(c for c in data["channels"] if c["name"] == "test-email")
        assert email["preferred_format"] == "html"

    def test_includes_severity_filter(self, channels_yaml, db_session):
        from agenticops.tools.notification_tools import list_notification_channels

        result = list_notification_channels()
        data = json.loads(result)
        slack = next(c for c in data["channels"] if c["name"] == "test-slack")
        assert slack["severity_filter"] == ["critical", "high"]

    def test_includes_enabled_flag(self, channels_yaml, db_session):
        from agenticops.tools.notification_tools import list_notification_channels

        result = list_notification_channels()
        data = json.loads(result)
        disabled = next(c for c in data["channels"] if c["name"] == "disabled-channel")
        assert disabled["is_enabled"] is False

    def test_includes_channel_type(self, channels_yaml, db_session):
        from agenticops.tools.notification_tools import list_notification_channels

        result = list_notification_channels()
        data = json.loads(result)
        email = next(c for c in data["channels"] if c["name"] == "test-email")
        assert email["channel_type"] == "email"

    def test_empty_im_aliases(self, channels_yaml, db_session):
        from agenticops.tools.notification_tools import list_notification_channels

        result = list_notification_channels()
        data = json.loads(result)
        assert data["im_aliases"] == []


# ============================================================================
# distribute_report tool tests
# ============================================================================


class TestDistributeReport:
    """Tests for the distribute_report tool."""

    def test_invalid_report_id(self, db_session, channels_yaml):
        from agenticops.tools.notification_tools import distribute_report

        result = distribute_report(report_id="abc")
        data = json.loads(result)
        assert data["success"] is False
        assert "Invalid report_id" in data["message"]

    def test_report_not_found(self, db_session, channels_yaml):
        from agenticops.tools.notification_tools import distribute_report

        result = distribute_report(report_id="9999")
        data = json.loads(result)
        assert data["success"] is False
        assert "not found" in data["message"]

    def test_no_matching_channels(self, db_session, channels_yaml, sample_report):
        from agenticops.tools.notification_tools import distribute_report

        result = distribute_report(
            report_id=str(sample_report.id),
            channel_names="nonexistent-channel",
        )
        data = json.loads(result)
        assert data["success"] is False
        assert "No matching" in data["message"]

    def test_distribute_to_specific_channels(self, db_session, channels_yaml, sample_report):
        from agenticops.tools.notification_tools import distribute_report

        with patch("agenticops.notify.notifier.NotificationManager") as mock_manager_cls:
            mock_instance = MagicMock()
            mock_instance.send_notification = AsyncMock(return_value={"test-feishu": True})
            mock_manager_cls.return_value = mock_instance

            result = distribute_report(
                report_id=str(sample_report.id),
                channel_names="test-feishu",
            )
        data = json.loads(result)
        assert data["report_id"] == sample_report.id
        assert data["channels_targeted"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["channel"] == "test-feishu"
        assert data["results"][0]["format"] == "markdown"

    def test_distribute_all_enabled(self, db_session, channels_yaml, sample_report):
        from agenticops.tools.notification_tools import distribute_report

        with patch("agenticops.notify.notifier.NotificationManager") as mock_manager_cls:
            mock_instance = MagicMock()
            mock_instance.send_notification = AsyncMock(return_value={"test-feishu": True, "test-email": True, "test-slack": True})
            mock_manager_cls.return_value = mock_instance

            with patch("agenticops.notify.notifier.SNSReportNotifier") as mock_sns:
                mock_notifier = MagicMock()
                mock_notifier.send_report = AsyncMock(return_value={"formats": ["html", "markdown"], "urls": {}})
                mock_sns.return_value = mock_notifier

                result = distribute_report(report_id=str(sample_report.id))
                data = json.loads(result)

        # 4 enabled channels (feishu, email, slack, sns-report); disabled-channel excluded
        assert data["channels_targeted"] == 4
        assert len(data["results"]) == 4

    def test_severity_filter(self, db_session, channels_yaml, sample_report):
        from agenticops.tools.notification_tools import distribute_report

        with patch("agenticops.notify.notifier.NotificationManager") as mock_manager_cls:
            mock_instance = MagicMock()
            mock_instance.send_notification = AsyncMock(return_value={"test-slack": True})
            mock_manager_cls.return_value = mock_instance

            with patch("agenticops.notify.notifier.SNSReportNotifier") as mock_sns:
                mock_notifier = MagicMock()
                mock_notifier.send_report = AsyncMock(return_value={"formats": ["html"], "urls": {}})
                mock_sns.return_value = mock_notifier

                result = distribute_report(
                    report_id=str(sample_report.id),
                    severity="critical",
                )
                data = json.loads(result)

        # test-slack has severity_filter [critical, high], others have no filter (so they pass too)
        targeted_names = {r["channel"] for r in data["results"]}
        assert "test-slack" in targeted_names

    def test_formats_generated(self, db_session, channels_yaml, sample_report):
        from agenticops.tools.notification_tools import distribute_report

        with patch("agenticops.notify.notifier.NotificationManager") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.send_notification = AsyncMock(return_value={"test-feishu": True})
            mock_cls.return_value = mock_instance

            result = distribute_report(
                report_id=str(sample_report.id),
                channel_names="test-feishu",
            )
            data = json.loads(result)

        assert "markdown" in data["formats_generated"]

    def test_html_format_for_email(self, db_session, channels_yaml, sample_report):
        from agenticops.tools.notification_tools import distribute_report

        with patch("agenticops.notify.notifier.NotificationManager") as mock_manager_cls:
            mock_instance = MagicMock()
            mock_instance.send_notification = AsyncMock(return_value={"test-email": True})
            mock_manager_cls.return_value = mock_instance

            with patch("agenticops.notify.report_formatter.format_report") as mock_fmt:
                mock_fr = MagicMock()
                mock_fr.format = "html"
                mock_fr.content = b"<h1>Report</h1>"
                mock_fmt.return_value = [mock_fr]

                result = distribute_report(
                    report_id=str(sample_report.id),
                    channel_names="test-email",
                )
                data = json.loads(result)

        assert data["results"][0]["format"] == "html"
        assert "html" in data["formats_generated"]

    def test_report_with_empty_content(self, db_session, channels_yaml):
        """Report with no markdown content should fail gracefully."""
        from agenticops.tools.notification_tools import distribute_report

        report = Report(
            report_type="daily",
            title="Empty Report",
            summary="Nothing",
            content_markdown="",
            file_path="/tmp/empty.md",
        )
        db_session.add(report)
        db_session.commit()

        result = distribute_report(report_id=str(report.id))
        data = json.loads(result)
        assert data["success"] is False
        assert "no markdown content" in data["message"]


# ============================================================================
# send_to_channel tool tests
# ============================================================================


class TestSendToChannel:
    """Quick sanity checks for the send_to_channel tool."""

    def test_invalid_content_type(self):
        from agenticops.tools.notification_tools import send_to_channel

        result = send_to_channel(
            target_name="test",
            content="hello",
            content_type="invalid",
        )
        data = json.loads(result)
        assert data["success"] is False
        assert "Invalid content_type" in data["message"]

    def test_valid_content_types(self):
        """Verify valid content types are accepted (will fail on send, but validation passes)."""
        from agenticops.tools.notification_tools import send_to_channel

        for ct in ("text", "report", "issue", "file"):
            result = send_to_channel(
                target_name="nonexistent-target",
                content="42",
                content_type=ct,
            )
            data = json.loads(result)
            # Should fail on target resolution, not content_type validation
            assert "Invalid content_type" not in data["message"]


# ============================================================================
# Skill discovery tests
# ============================================================================


class TestSkillDiscovery:
    """Tests for notification-operator skill discovery and tool resolution."""

    def test_skill_discovered(self):
        from agenticops.skills.loader import discover_skills

        skills = discover_skills()
        names = [s.name for s in skills]
        assert "notification-operator" in names

    def test_skill_metadata(self):
        from agenticops.skills.loader import discover_skills

        skills = discover_skills()
        skill = next(s for s in skills if s.name == "notification-operator")
        assert "notification" in skill.description.lower()
        assert skill.metadata.get("domain") == "operations"

    def test_skill_tools_list(self):
        from agenticops.skills.loader import discover_skills

        skills = discover_skills()
        skill = next(s for s in skills if s.name == "notification-operator")
        assert len(skill.tools) == 3
        tool_names = set(skill.tools)
        assert "agenticops.tools.notification_tools.list_notification_channels" in tool_names
        assert "agenticops.tools.notification_tools.send_to_channel" in tool_names
        assert "agenticops.tools.notification_tools.distribute_report" in tool_names

    def test_skill_tools_resolve(self):
        from agenticops.skills.loader import resolve_skill_tools

        tools = resolve_skill_tools("notification-operator")
        assert len(tools) == 3
        tool_names = {t.__name__ for t in tools}
        assert tool_names == {"list_notification_channels", "send_to_channel", "distribute_report"}


# ============================================================================
# Agent prompt integration tests
# ============================================================================


class TestMainAgentPrompt:
    """Tests that main_agent system prompt references notification-operator skill."""

    def test_no_static_send_to_channel_in_prompt(self):
        from agenticops.agents.main_agent import MAIN_SYSTEM_PROMPT

        assert "list_send_targets" not in MAIN_SYSTEM_PROMPT

    def test_notification_operator_skill_in_routing(self):
        from agenticops.agents.main_agent import MAIN_SYSTEM_PROMPT

        assert "notification-operator" in MAIN_SYSTEM_PROMPT
        assert "activate_skill" in MAIN_SYSTEM_PROMPT

    def test_no_send_to_channel_in_tools_list(self):
        """Verify send_to_channel is not in the static tools list."""
        from agenticops.agents.main_agent import create_main_agent
        # Don't actually create agent (needs Bedrock), just check imports
        import agenticops.agents.main_agent as mod

        # The module should not import send_to_channel from notification_tools
        assert not hasattr(mod, "send_to_channel")
        # But it should still have activate_skill
        assert hasattr(mod, "activate_skill")


class TestReporterAgentPrompt:
    """Tests that reporter_agent system prompt references notification-operator skill."""

    def test_notification_operator_in_prompt(self):
        from agenticops.agents.reporter_agent import REPORTER_SYSTEM_PROMPT

        assert "notification-operator" in REPORTER_SYSTEM_PROMPT

    def test_distribute_report_in_prompt(self):
        from agenticops.agents.reporter_agent import REPORTER_SYSTEM_PROMPT

        assert "distribute_report" in REPORTER_SYSTEM_PROMPT

    def test_read_skill_reference_imported(self):
        import importlib
        import sys

        mod = importlib.import_module("agenticops.agents.reporter_agent")
        assert hasattr(mod, "read_skill_reference")
