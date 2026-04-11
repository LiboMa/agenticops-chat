"""Tests for the audit logging service (agenticops.audit)."""

import sys
sys.path.insert(0, "src")

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops.models import Base
from agenticops.audit.models import AuditLog
from agenticops.audit.service import (
    Actions,
    AuditService,
    EntityTypes,
    log_action,
)


# ---------------------------------------------------------------------------
# Fixtures – in-memory SQLite for isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_db(tmp_path):
    """Redirect all DB access to an in-memory SQLite DB."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    _Session = sessionmaker(bind=engine, expire_on_commit=False)

    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        sess = _Session()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    with patch("agenticops.audit.service.get_db_session", _fake_session), \
         patch("agenticops.audit.service.init_db"):
        yield engine


# ---------------------------------------------------------------------------
# Actions / EntityTypes constants
# ---------------------------------------------------------------------------

class TestActionConstants:
    def test_crud_actions_exist(self):
        assert Actions.CREATE == "create"
        assert Actions.READ == "read"
        assert Actions.UPDATE == "update"
        assert Actions.DELETE == "delete"

    def test_auth_actions_exist(self):
        assert Actions.LOGIN == "login"
        assert Actions.LOGOUT == "logout"
        assert Actions.LOGIN_FAILED == "login_failed"

    def test_entity_types_exist(self):
        assert EntityTypes.USER == "user"
        assert EntityTypes.ACCOUNT == "account"
        assert EntityTypes.RESOURCE == "resource"
        assert EntityTypes.ANOMALY == "anomaly"


# ---------------------------------------------------------------------------
# AuditService.log
# ---------------------------------------------------------------------------

class TestAuditServiceLog:
    def test_log_creates_entry(self):
        entry = AuditService.log(
            action=Actions.CREATE,
            entity_type=EntityTypes.ACCOUNT,
            entity_id="acc-1",
            entity_name="My Account",
            user_id=42,
            user_email="dev@example.com",
        )
        assert isinstance(entry, AuditLog)
        assert entry.action == "create"
        assert entry.entity_type == "account"
        assert entry.entity_id == "acc-1"
        assert entry.entity_name == "My Account"
        assert entry.user_id == 42
        assert entry.user_email == "dev@example.com"

    def test_log_defaults(self):
        entry = AuditService.log(
            action=Actions.DELETE,
            entity_type=EntityTypes.RESOURCE,
            entity_id="res-99",
        )
        assert entry.details == {}
        assert entry.old_values is None
        assert entry.new_values is None
        assert entry.ip_address is None

    def test_log_with_details_and_values(self):
        entry = AuditService.log(
            action=Actions.UPDATE,
            entity_type=EntityTypes.ANOMALY,
            entity_id="ano-7",
            details={"reason": "severity change"},
            old_values={"severity": "low"},
            new_values={"severity": "high"},
            ip_address="10.0.0.1",
            user_agent="pytest",
            request_id="req-abc",
        )
        assert entry.details == {"reason": "severity change"}
        assert entry.old_values == {"severity": "low"}
        assert entry.new_values == {"severity": "high"}
        assert entry.ip_address == "10.0.0.1"
        assert entry.user_agent == "pytest"
        assert entry.request_id == "req-abc"

    def test_entity_id_coerced_to_str(self):
        entry = AuditService.log(
            action=Actions.READ,
            entity_type=EntityTypes.USER,
            entity_id=123,
        )
        assert entry.entity_id == "123"


# ---------------------------------------------------------------------------
# AuditService.query
# ---------------------------------------------------------------------------

class TestAuditServiceQuery:
    def _seed(self, n=5):
        for i in range(n):
            AuditService.log(
                action=Actions.CREATE if i % 2 == 0 else Actions.UPDATE,
                entity_type=EntityTypes.RESOURCE if i < 3 else EntityTypes.ACCOUNT,
                entity_id=f"e-{i}",
                user_id=i + 1,  # avoid 0 which is falsy
            )

    def test_query_all(self):
        self._seed()
        results = AuditService.query()
        assert len(results) == 5

    def test_query_filter_action(self):
        self._seed()
        results = AuditService.query(action=Actions.CREATE)
        assert all(r.action == "create" for r in results)
        assert len(results) == 3  # indices 0, 2, 4

    def test_query_filter_entity_type(self):
        self._seed()
        results = AuditService.query(entity_type=EntityTypes.ACCOUNT)
        assert len(results) == 2

    def test_query_filter_user_id(self):
        self._seed()
        results = AuditService.query(user_id=1)
        assert len(results) == 1
        assert results[0].entity_id == "e-0"

    def test_query_limit_offset(self):
        self._seed(10)
        page1 = AuditService.query(limit=3, offset=0)
        page2 = AuditService.query(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].id != page2[0].id

    def test_query_time_filter(self):
        self._seed()
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        results = AuditService.query(start_time=future)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# AuditService.get_entity_history / get_user_activity / get_recent_changes
# ---------------------------------------------------------------------------

class TestAuditServiceHelpers:
    def test_get_entity_history(self):
        AuditService.log(action=Actions.CREATE, entity_type=EntityTypes.RESOURCE, entity_id="r-1")
        AuditService.log(action=Actions.UPDATE, entity_type=EntityTypes.RESOURCE, entity_id="r-1")
        AuditService.log(action=Actions.DELETE, entity_type=EntityTypes.RESOURCE, entity_id="r-2")
        history = AuditService.get_entity_history(EntityTypes.RESOURCE, "r-1")
        assert len(history) == 2
        assert all(h.entity_id == "r-1" for h in history)

    def test_get_user_activity(self):
        AuditService.log(action=Actions.LOGIN, entity_type=EntityTypes.SESSION, entity_id="s-1", user_id=10)
        AuditService.log(action=Actions.READ, entity_type=EntityTypes.RESOURCE, entity_id="r-5", user_id=10)
        AuditService.log(action=Actions.READ, entity_type=EntityTypes.RESOURCE, entity_id="r-6", user_id=20)
        activity = AuditService.get_user_activity(user_id=10, days=1)
        assert len(activity) == 2

    def test_get_recent_changes(self):
        AuditService.log(action=Actions.CREATE, entity_type=EntityTypes.ACCOUNT, entity_id="a-1")
        AuditService.log(action=Actions.UPDATE, entity_type=EntityTypes.RESOURCE, entity_id="r-1")
        recent = AuditService.get_recent_changes(hours=1)
        assert len(recent) == 2

    def test_get_recent_changes_filtered(self):
        AuditService.log(action=Actions.CREATE, entity_type=EntityTypes.ACCOUNT, entity_id="a-1")
        AuditService.log(action=Actions.UPDATE, entity_type=EntityTypes.RESOURCE, entity_id="r-1")
        recent = AuditService.get_recent_changes(entity_type=EntityTypes.ACCOUNT, hours=1)
        assert len(recent) == 1


# ---------------------------------------------------------------------------
# AuditService.count_actions
# ---------------------------------------------------------------------------

class TestAuditServiceCount:
    def test_count_all(self):
        for i in range(4):
            AuditService.log(action=Actions.CREATE, entity_type=EntityTypes.RESOURCE, entity_id=f"r-{i}")
        assert AuditService.count_actions() == 4

    def test_count_filtered(self):
        AuditService.log(action=Actions.CREATE, entity_type=EntityTypes.RESOURCE, entity_id="r-1")
        AuditService.log(action=Actions.DELETE, entity_type=EntityTypes.RESOURCE, entity_id="r-2")
        assert AuditService.count_actions(action=Actions.CREATE) == 1
        assert AuditService.count_actions(entity_type=EntityTypes.RESOURCE) == 2


# ---------------------------------------------------------------------------
# AuditService.cleanup_old_logs
# ---------------------------------------------------------------------------

class TestAuditServiceCleanup:
    def test_cleanup_removes_nothing_when_recent(self):
        AuditService.log(action=Actions.CREATE, entity_type=EntityTypes.SYSTEM, entity_id="s-1")
        assert AuditService.count_actions() == 1
        deleted = AuditService.cleanup_old_logs(days=90)
        assert deleted == 0

    def test_cleanup_with_zero_days(self):
        AuditService.log(action=Actions.CREATE, entity_type=EntityTypes.SYSTEM, entity_id="s-1")
        deleted = AuditService.cleanup_old_logs(days=0)
        assert deleted == 1


# ---------------------------------------------------------------------------
# @log_action decorator – sync
# ---------------------------------------------------------------------------

class TestLogActionDecorator:
    def test_sync_decorator_logs(self):
        @log_action(
            action=Actions.CREATE,
            entity_type=EntityTypes.ACCOUNT,
            get_entity_id=lambda result: result["id"],
            get_entity_name=lambda result: result["name"],
        )
        def create_account():
            return {"id": "acc-new", "name": "Test"}

        result = create_account()
        assert result == {"id": "acc-new", "name": "Test"}
        logs = AuditService.query(action=Actions.CREATE, entity_type=EntityTypes.ACCOUNT)
        assert len(logs) == 1
        assert logs[0].entity_id == "acc-new"
        assert logs[0].entity_name == "Test"

    def test_sync_decorator_default_entity_id(self):
        @log_action(action=Actions.DELETE, entity_type=EntityTypes.USER)
        def delete_user():
            return 42

        delete_user()
        logs = AuditService.query(action=Actions.DELETE, entity_type=EntityTypes.USER)
        assert len(logs) == 1
        assert logs[0].entity_id == "42"

    def test_decorator_does_not_swallow_exceptions(self):
        @log_action(action=Actions.CREATE, entity_type=EntityTypes.SYSTEM)
        def failing():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            failing()


# ---------------------------------------------------------------------------
# @log_action decorator – async
# ---------------------------------------------------------------------------

class TestLogActionDecoratorAsync:
    def test_async_decorator_logs(self):
        @log_action(
            action=Actions.CREATE,
            entity_type=EntityTypes.RESOURCE,
            get_entity_id=lambda r: r["id"],
        )
        async def create_resource():
            return {"id": "res-async"}

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(create_resource())
        finally:
            loop.close()
        logs = AuditService.query(action=Actions.CREATE, entity_type=EntityTypes.RESOURCE)
        assert len(logs) == 1
        assert logs[0].entity_id == "res-async"
