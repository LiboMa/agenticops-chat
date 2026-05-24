"""Targeted tests for agenticops.tools.notification_tools — covering uncovered paths.

Targets: list_notification_channels (exception path), send_to_channel (text/report/issue/file),
distribute_report (format grouping, severity filter, error paths, sns-report dispatch).
"""

import json
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# list_notification_channels
# ---------------------------------------------------------------------------


class TestListNotificationChannels:
    """Tests for list_notification_channels tool."""

    @patch("agenticops.tools.notification_tools.json")
    def _import_tool(self, mock_json=None):
        from agenticops.tools.notification_tools import list_notification_channels
        return list_notification_channels

    def test_channels_listed_with_im_aliases(self):
        """Covers normal path + IM alias query."""
        mock_ch = MagicMock()
        mock_ch.name = "slack-ops"
        mock_ch.channel_type = "slack"
        mock_ch.is_enabled = True
        mock_ch.preferred_format = "markdown"
        mock_ch.severity_filter = ["critical"]

        mock_alias = MagicMock()
        mock_alias.name = "ops-team"
        mock_alias.platform = "slack"
        mock_alias.chat_id = "C12345"

        with patch("agenticops.notify.im_config.load_channels", return_value=[mock_ch]):
            with patch("agenticops.models.get_session") as mock_gs:
                mock_session = MagicMock()
                mock_session.query.return_value.all.return_value = [mock_alias]
                mock_gs.return_value = mock_session

                from agenticops.tools.notification_tools import list_notification_channels
                result = json.loads(list_notification_channels._tool_func())

        assert len(result["channels"]) == 1
        assert result["channels"][0]["name"] == "slack-ops"
        assert len(result["im_aliases"]) == 1

    def test_im_aliases_exception_returns_empty(self):
        """Covers line 68-69: exception on IM alias query."""
        mock_ch = MagicMock()
        mock_ch.name = "email"
        mock_ch.channel_type = "ses"
        mock_ch.is_enabled = True
        mock_ch.preferred_format = "html"
        mock_ch.severity_filter = None

        with patch("agenticops.notify.im_config.load_channels", return_value=[mock_ch]):
            with patch("agenticops.models.get_session", side_effect=Exception("DB down")):
                from agenticops.tools.notification_tools import list_notification_channels
                result = json.loads(list_notification_channels._tool_func())

        assert result["im_aliases"] == []


# ---------------------------------------------------------------------------
# send_to_channel
# ---------------------------------------------------------------------------


class TestSendToChannel:
    """Tests for send_to_channel tool."""

    def test_invalid_content_type(self):
        from agenticops.tools.notification_tools import send_to_channel
        result = json.loads(send_to_channel._tool_func(
            target_name="ops", content="hello", content_type="invalid"
        ))
        assert result["success"] is False
        assert "Invalid content_type" in result["message"]

    def test_text_content_type(self):
        """Covers line 112: text command building."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Sent to ops"

        with patch("agenticops.chat.send_to.execute_send_to", return_value=mock_result) as mock_exec:
            from agenticops.tools.notification_tools import send_to_channel
            result = json.loads(send_to_channel._tool_func(
                target_name="ops", content="hello world", content_type="text"
            ))
            mock_exec.assert_called_once_with("/send_to ops hello world")

        assert result["success"] is True

    def test_report_content_type(self):
        """Covers report command building with #R prefix."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Sent"

        with patch("agenticops.chat.send_to.execute_send_to", return_value=mock_result) as mock_exec:
            from agenticops.tools.notification_tools import send_to_channel
            send_to_channel._tool_func(
                target_name="email", content="42", content_type="report"
            )
            mock_exec.assert_called_once_with("/send_to email #R42")

    def test_issue_content_type(self):
        """Covers issue command building with #I prefix."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Sent"

        with patch("agenticops.chat.send_to.execute_send_to", return_value=mock_result) as mock_exec:
            from agenticops.tools.notification_tools import send_to_channel
            send_to_channel._tool_func(
                target_name="slack", content="7", content_type="issue"
            )
            mock_exec.assert_called_once_with("/send_to slack #I7")

    def test_file_content_type(self):
        """Covers file command building with #D prefix."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.message = "File not found"

        with patch("agenticops.chat.send_to.execute_send_to", return_value=mock_result) as mock_exec:
            from agenticops.tools.notification_tools import send_to_channel
            result = json.loads(send_to_channel._tool_func(
                target_name="team", content="99", content_type="file"
            ))
            mock_exec.assert_called_once_with("/send_to team #D99")

        assert result["success"] is False


# ---------------------------------------------------------------------------
# distribute_report
# ---------------------------------------------------------------------------


class TestDistributeReport:
    """Tests for distribute_report tool."""

    def test_invalid_report_id(self):
        from agenticops.tools.notification_tools import distribute_report
        result = json.loads(distribute_report._tool_func(
            report_id="abc"
        ))
        assert result["success"] is False
        assert "Invalid report_id" in result["message"]

    def test_report_not_found(self):
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("agenticops.models.get_session", return_value=mock_session):
            from agenticops.tools.notification_tools import distribute_report
            result = json.loads(distribute_report._tool_func(report_id="999"))

        assert result["success"] is False
        assert "not found" in result["message"]

    def test_no_markdown_content(self):
        mock_report = MagicMock()
        mock_report.title = "Test"
        mock_report.summary = "Sum"
        mock_report.content_markdown = ""
        mock_report.report_type = "report"
        mock_report.report_metadata = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_report

        with patch("agenticops.models.get_session", return_value=mock_session):
            from agenticops.tools.notification_tools import distribute_report
            result = json.loads(distribute_report._tool_func(report_id="1"))

        assert result["success"] is False
        assert "no markdown" in result["message"]

    def test_no_matching_channels(self):
        mock_report = MagicMock()
        mock_report.title = "Test"
        mock_report.summary = "Sum"
        mock_report.content_markdown = "# Hello"
        mock_report.report_type = "report"
        mock_report.report_metadata = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_report

        with patch("agenticops.models.get_session", return_value=mock_session):
            with patch("agenticops.notify.im_config.load_channels", return_value=[]):
                from agenticops.tools.notification_tools import distribute_report
                result = json.loads(distribute_report._tool_func(report_id="1"))

        assert result["success"] is False
        assert "No matching" in result["message"]

    def test_severity_filter_excludes_channels(self):
        mock_report = MagicMock()
        mock_report.title = "Alert"
        mock_report.summary = ""
        mock_report.content_markdown = "# Alert content"
        mock_report.report_type = "alert"
        mock_report.report_metadata = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_report

        ch = MagicMock()
        ch.name = "low-priority"
        ch.channel_type = "slack"
        ch.is_enabled = True
        ch.preferred_format = "text"
        ch.severity_filter = ["low"]  # Won't match "critical"

        with patch("agenticops.models.get_session", return_value=mock_session):
            with patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
                from agenticops.tools.notification_tools import distribute_report
                result = json.loads(distribute_report._tool_func(
                    report_id="1", severity="critical"
                ))

        assert result["success"] is False

    def test_text_format_dispatch_success(self):
        """Covers text format group + NotificationManager dispatch."""
        mock_report = MagicMock()
        mock_report.title = "Daily Report"
        mock_report.summary = "Summary"
        mock_report.content_markdown = "# Report\nContent here"
        mock_report.report_type = "daily"
        mock_report.report_metadata = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_report

        ch = MagicMock()
        ch.name = "slack-ops"
        ch.channel_type = "slack"
        ch.is_enabled = True
        ch.preferred_format = "text"
        ch.severity_filter = None

        async def mock_send(*args, **kwargs):
            return {"slack-ops": True}

        mock_manager = MagicMock()
        mock_manager.send_notification = mock_send

        with patch("agenticops.models.get_session", return_value=mock_session):
            with patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
                with patch("agenticops.notify.notifier.NotificationManager", return_value=mock_manager):
                    from agenticops.tools.notification_tools import distribute_report
                    result = json.loads(distribute_report._tool_func(report_id="5"))

        assert result["success"] is True
        assert result["report_id"] == 5

    def test_html_format_with_formatter_exception(self):
        """Covers lines 244-245: report formatting failure fallback to markdown."""
        mock_report = MagicMock()
        mock_report.title = "Report"
        mock_report.summary = ""
        mock_report.content_markdown = "# Markdown content"
        mock_report.report_type = "report"
        mock_report.report_metadata = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_report

        ch = MagicMock()
        ch.name = "email-ch"
        ch.channel_type = "slack"
        ch.is_enabled = True
        ch.preferred_format = "html"
        ch.severity_filter = None

        async def mock_send(*args, **kwargs):
            return {"email-ch": True}

        mock_manager = MagicMock()
        mock_manager.send_notification = mock_send

        with patch("agenticops.models.get_session", return_value=mock_session):
            with patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
                with patch("agenticops.notify.report_formatter.format_report", side_effect=Exception("format error")):
                    with patch("agenticops.notify.notifier.NotificationManager", return_value=mock_manager):
                        from agenticops.tools.notification_tools import distribute_report
                        result = json.loads(distribute_report._tool_func(report_id="2"))

        assert result["formats_generated"] == ["html"]

    def test_sns_report_channel_dispatch_error(self):
        """Covers lines 272-273: exception in sns-report channel dispatch."""
        mock_report = MagicMock()
        mock_report.title = "Report"
        mock_report.summary = ""
        mock_report.content_markdown = "# Content"
        mock_report.report_type = "report"
        mock_report.report_metadata = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_report

        ch = MagicMock()
        ch.name = "sns-ch"
        ch.channel_type = "sns-report"
        ch.is_enabled = True
        ch.preferred_format = "html"
        ch.severity_filter = None

        with patch("agenticops.models.get_session", return_value=mock_session):
            with patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
                with patch(
                    "agenticops.tools.notification_tools._distribute_via_report_channel",
                    side_effect=Exception("SNS error"),
                ):
                    from agenticops.tools.notification_tools import distribute_report
                    result = json.loads(distribute_report._tool_func(report_id="3"))

        assert result["success"] is False
        assert result["results"][0]["status"] == "error"

    def test_standard_channel_dispatch_exception(self):
        """Covers line 529-530: exception in standard channel dispatch."""
        mock_report = MagicMock()
        mock_report.title = "Report"
        mock_report.summary = ""
        mock_report.content_markdown = "# Content"
        mock_report.report_type = "report"
        mock_report.report_metadata = {}

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_report

        ch = MagicMock()
        ch.name = "broken-ch"
        ch.channel_type = "slack"
        ch.is_enabled = True
        ch.preferred_format = "markdown"
        ch.severity_filter = None

        with patch("agenticops.models.get_session", return_value=mock_session):
            with patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
                with patch(
                    "agenticops.notify.notifier.NotificationManager",
                    side_effect=Exception("Manager init failed"),
                ):
                    from agenticops.tools.notification_tools import distribute_report
                    result = json.loads(distribute_report._tool_func(report_id="4"))

        assert result["results"][0]["status"] == "error"
