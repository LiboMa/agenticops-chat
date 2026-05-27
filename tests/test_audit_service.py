"""Unit tests for agenticops.audit.service module.

Covers: AuditService (log, query, get_entity_history, get_user_activity,
get_recent_changes, count_actions, cleanup_old_logs), log_action decorator.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from agenticops.audit.service import (
    AuditService,
    Actions,
    EntityTypes,
    log_action,
)


@pytest.fixture
def mock_db_session():
    """Mock get_db_session context manager."""
    mock_session = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_session)
    mock_cm.__exit__ = MagicMock(return_value=False)

    with patch("agenticops.audit.service.get_db_session", return_value=mock_cm):
        with patch("agenticops.audit.service.init_db"):
            yield mock_session


# ── Actions/EntityTypes constants ────────────────────────────────────


class TestConstants:
    def test_actions_defined(self):
        assert Actions.CREATE == "create"
        assert Actions.LOGIN == "login"
        assert Actions.SCAN == "scan"
        assert Actions.SCHEDULE_RUN == "schedule_run"

    def test_entity_types_defined(self):
        assert EntityTypes.USER == "user"
        assert EntityTypes.RESOURCE == "resource"
        assert EntityTypes.SYSTEM == "system"


# ── AuditService.log tests ───────────────────────────────────────────


class TestAuditServiceLog:
    def test_log_creates_entry(self, mock_db_session):
        result = AuditService.log(
            action=Actions.CREATE,
            entity_type=EntityTypes.ACCOUNT,
            entity_id="acc-123",
            entity_name="Production Account",
            user_email="admin@example.com",
        )
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()

    def test_log_with_all_fields(self, mock_db_session):
        result = AuditService.log(
            action=Actions.UPDATE,
            entity_type=EntityTypes.RESOURCE,
            entity_id="i-abc123",
            entity_name="web-server-1",
            user_id=42,
            user_email="dev@example.com",
            details={"reason": "scaling"},
            old_values={"instance_type": "t3.small"},
            new_values={"instance_type": "t3.large"},
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            request_id="req-xyz",
        )
        mock_db_session.add.assert_called_once()
        added_obj = mock_db_session.add.call_args[0][0]
        assert added_obj.action == "update"
        assert added_obj.entity_id == "i-abc123"

    def test_log_minimal_fields(self, mock_db_session):
        result = AuditService.log(
            action=Actions.READ,
            entity_type=EntityTypes.REPORT,
            entity_id="rpt-1",
        )
        mock_db_session.add.assert_called_once()


# ── AuditService.query tests ────────────────────────────────────────


class TestAuditServiceQuery:
    def test_query_no_filters(self, mock_db_session):
        mock_query = MagicMock()
        mock_db_session.query.return_value.order_by.return_value = mock_query
        mock_query.offset.return_value.limit.return_value.all.return_value = []

        result = AuditService.query()
        assert result == []

    def test_query_with_action_filter(self, mock_db_session):
        mock_query = MagicMock()
        mock_db_session.query.return_value.order_by.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.offset.return_value.limit.return_value.all.return_value = []

        AuditService.query(action=Actions.CREATE)
        mock_query.filter_by.assert_called_with(action="create")

    def test_query_with_entity_type(self, mock_db_session):
        mock_query = MagicMock()
        mock_db_session.query.return_value.order_by.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.offset.return_value.limit.return_value.all.return_value = []

        AuditService.query(entity_type=EntityTypes.USER)
        mock_query.filter_by.assert_any_call(entity_type="user")

    def test_query_with_time_range(self, mock_db_session):
        mock_query = MagicMock()
        mock_db_session.query.return_value.order_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.offset.return_value.limit.return_value.all.return_value = []

        now = datetime.now(timezone.utc)
        AuditService.query(start_time=now - timedelta(hours=1), end_time=now)
        assert mock_query.filter.call_count == 2

    def test_query_with_pagination(self, mock_db_session):
        mock_query = MagicMock()
        mock_db_session.query.return_value.order_by.return_value = mock_query
        mock_query.offset.return_value.limit.return_value.all.return_value = []

        AuditService.query(limit=50, offset=10)
        mock_query.offset.assert_called_with(10)
        mock_query.offset.return_value.limit.assert_called_with(50)


# ── Convenience methods ──────────────────────────────────────────────


class TestConvenienceMethods:
    @patch.object(AuditService, "query")
    def test_get_entity_history(self, mock_query):
        mock_query.return_value = []
        result = AuditService.get_entity_history(EntityTypes.RESOURCE, "i-123")
        mock_query.assert_called_once_with(
            entity_type="resource", entity_id="i-123", limit=50
        )

    @patch.object(AuditService, "query")
    def test_get_user_activity(self, mock_query):
        mock_query.return_value = []
        result = AuditService.get_user_activity(user_id=42, days=7)
        call_kwargs = mock_query.call_args[1]
        assert call_kwargs["user_id"] == 42
        assert call_kwargs["limit"] == 100
        assert call_kwargs["start_time"] is not None

    @patch.object(AuditService, "query")
    def test_get_recent_changes(self, mock_query):
        mock_query.return_value = []
        result = AuditService.get_recent_changes(entity_type=EntityTypes.ACCOUNT, hours=12)
        call_kwargs = mock_query.call_args[1]
        assert call_kwargs["entity_type"] == "account"


# ── count_actions tests ──────────────────────────────────────────────


class TestCountActions:
    def test_count_no_filters(self, mock_db_session):
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.count.return_value = 42

        result = AuditService.count_actions()
        assert result == 42

    def test_count_with_filters(self, mock_db_session):
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.count.return_value = 5

        result = AuditService.count_actions(action=Actions.DELETE, entity_type=EntityTypes.RESOURCE)
        assert result == 5


# ── cleanup_old_logs tests ───────────────────────────────────────────


class TestCleanupOldLogs:
    def test_cleanup(self, mock_db_session):
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.delete.return_value = 15

        result = AuditService.cleanup_old_logs(days=90)
        assert result == 15


# ── log_action decorator tests ───────────────────────────────────────


class TestLogActionDecorator:
    @patch.object(AuditService, "log")
    def test_sync_decorator(self, mock_log):
        @log_action(Actions.CREATE, EntityTypes.ACCOUNT, get_entity_id=lambda r: r["id"])
        def create_account():
            return {"id": "acc-new"}

        result = create_account()
        assert result == {"id": "acc-new"}
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == "create"
        assert call_kwargs["entity_id"] == "acc-new"

    @patch.object(AuditService, "log")
    @pytest.mark.asyncio
    async def test_async_decorator(self, mock_log):
        @log_action(Actions.DELETE, EntityTypes.RESOURCE, get_entity_id=lambda r: r)
        async def delete_resource():
            return "res-123"

        result = await delete_resource()
        assert result == "res-123"
        mock_log.assert_called_once()

    @patch.object(AuditService, "log")
    def test_decorator_handles_log_failure(self, mock_log):
        mock_log.side_effect = Exception("DB down")

        @log_action(Actions.CREATE, EntityTypes.USER, get_entity_id=lambda r: r)
        def create_user():
            return "user-1"

        # Should not raise even if logging fails
        result = create_user()
        assert result == "user-1"
