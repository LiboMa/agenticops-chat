"""Tests for memory extraction integration in session archive and TTL cleanup flows.

Validates Requirements: 5.1, 6.2, 7.2
- Session archiving triggers MemoryService.extract_facts() and extract_experiences()
- Agent TTL expiry triggers SummaryService.generate_summary() + memory extraction
- Extraction failures are logged as errors but never block the normal flow
"""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import ChatMessage, ChatSession, get_db_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session_with_messages():
    """Create a session with a few messages for testing."""
    sid = "mem-extract-test-001"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        session = ChatSession(
            session_id=sid, name="Memory Extract Test",
            created_at=now, updated_at=now, last_activity_at=now,
        )
        db.add(session)
        db.flush()
        db.add(ChatMessage(session_id=session.id, role="user", content="My preferred region is us-west-2"))
        db.add(ChatMessage(session_id=session.id, role="assistant", content="Noted, I'll use us-west-2."))
    yield sid
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
        if row:
            db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
            db.delete(row)


@pytest.fixture
def empty_session():
    """Create a session with no messages."""
    sid = "mem-extract-empty-002"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        session = ChatSession(
            session_id=sid, name="Empty Session",
            created_at=now, updated_at=now, last_activity_at=now,
        )
        db.add(session)
    yield sid
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
        if row:
            db.delete(row)


# ---------------------------------------------------------------------------
# _load_raw_messages
# ---------------------------------------------------------------------------

class TestLoadRawMessages:
    def test_loads_messages_for_existing_session(self, session_with_messages):
        from agenticops.web.session_manager import _load_raw_messages
        msgs = _load_raw_messages(session_with_messages)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_returns_empty_for_nonexistent_session(self):
        from agenticops.web.session_manager import _load_raw_messages
        msgs = _load_raw_messages("nonexistent-session-999")
        assert msgs == []

    def test_returns_empty_for_session_without_messages(self, empty_session):
        from agenticops.web.session_manager import _load_raw_messages
        msgs = _load_raw_messages(empty_session)
        assert msgs == []


# ---------------------------------------------------------------------------
# _trigger_memory_extraction
# ---------------------------------------------------------------------------

class TestTriggerMemoryExtraction:
    @patch("agenticops.web.memory_service.MemoryService")
    def test_calls_extract_facts_and_experiences(self, MockMemSvc, session_with_messages):
        from agenticops.web.session_manager import _trigger_memory_extraction
        mock_instance = MockMemSvc.return_value

        _trigger_memory_extraction(session_with_messages)

        mock_instance.extract_facts.assert_called_once()
        args = mock_instance.extract_facts.call_args
        assert args[0][0] == session_with_messages
        assert len(args[0][1]) == 2  # 2 messages

        mock_instance.extract_experiences.assert_called_once()
        args = mock_instance.extract_experiences.call_args
        assert args[0][0] == session_with_messages

    @patch("agenticops.web.memory_service.MemoryService")
    def test_skips_extraction_for_empty_session(self, MockMemSvc, empty_session):
        from agenticops.web.session_manager import _trigger_memory_extraction
        _trigger_memory_extraction(empty_session)
        MockMemSvc.return_value.extract_facts.assert_not_called()
        MockMemSvc.return_value.extract_experiences.assert_not_called()

    @patch("agenticops.web.memory_service.MemoryService")
    def test_fact_extraction_failure_does_not_block_experience_extraction(
        self, MockMemSvc, session_with_messages, caplog
    ):
        from agenticops.web.session_manager import _trigger_memory_extraction
        mock_instance = MockMemSvc.return_value
        mock_instance.extract_facts.side_effect = RuntimeError("LLM timeout")

        with caplog.at_level(logging.ERROR):
            _trigger_memory_extraction(session_with_messages)

        # Facts failed but experiences should still be called
        mock_instance.extract_experiences.assert_called_once()
        assert "Failed to extract facts" in caplog.text

    @patch("agenticops.web.memory_service.MemoryService")
    def test_experience_extraction_failure_logged(
        self, MockMemSvc, session_with_messages, caplog
    ):
        from agenticops.web.session_manager import _trigger_memory_extraction
        mock_instance = MockMemSvc.return_value
        mock_instance.extract_experiences.side_effect = RuntimeError("Embedding error")

        with caplog.at_level(logging.ERROR):
            _trigger_memory_extraction(session_with_messages)

        mock_instance.extract_facts.assert_called_once()
        assert "Failed to extract experiences" in caplog.text


# ---------------------------------------------------------------------------
# _trigger_summary_and_memory
# ---------------------------------------------------------------------------

class TestTriggerSummaryAndMemory:
    @patch("agenticops.web.memory_service.MemoryService")
    @patch("agenticops.web.summary_service.SummaryService")
    def test_calls_summary_and_memory_services(
        self, MockSumSvc, MockMemSvc, session_with_messages
    ):
        from agenticops.web.session_manager import _trigger_summary_and_memory

        _trigger_summary_and_memory(session_with_messages)

        MockSumSvc.return_value.generate_summary.assert_called_once()
        MockMemSvc.return_value.extract_facts.assert_called_once()
        MockMemSvc.return_value.extract_experiences.assert_called_once()

    @patch("agenticops.web.memory_service.MemoryService")
    @patch("agenticops.web.summary_service.SummaryService")
    def test_summary_failure_does_not_block_memory(
        self, MockSumSvc, MockMemSvc, session_with_messages, caplog
    ):
        from agenticops.web.session_manager import _trigger_summary_and_memory
        MockSumSvc.return_value.generate_summary.side_effect = RuntimeError("LLM down")

        with caplog.at_level(logging.ERROR):
            _trigger_summary_and_memory(session_with_messages)

        # Memory extraction should still proceed
        MockMemSvc.return_value.extract_facts.assert_called_once()
        MockMemSvc.return_value.extract_experiences.assert_called_once()
        assert "Failed to generate summary" in caplog.text

    @patch("agenticops.web.memory_service.MemoryService")
    @patch("agenticops.web.summary_service.SummaryService")
    def test_skips_all_for_empty_session(
        self, MockSumSvc, MockMemSvc, empty_session
    ):
        from agenticops.web.session_manager import _trigger_summary_and_memory
        _trigger_summary_and_memory(empty_session)
        MockSumSvc.return_value.generate_summary.assert_not_called()
        MockMemSvc.return_value.extract_facts.assert_not_called()


# ---------------------------------------------------------------------------
# _remove_stale integration
# ---------------------------------------------------------------------------

class TestRemoveStaleMemoryIntegration:
    @patch("agenticops.web.session_manager._trigger_summary_and_memory")
    def test_remove_stale_triggers_extraction(self, mock_trigger):
        from agenticops.web.session_manager import ChatSessionManager

        mgr = ChatSessionManager()
        sid = "stale-test-001"
        # Manually inject a stale agent
        mgr._agents[sid] = MagicMock()
        mgr._last_activity[sid] = datetime.now(timezone.utc) - timedelta(hours=2)

        mgr._remove_stale()

        # Agent should be cleaned up
        assert sid not in mgr._agents
        assert sid not in mgr._last_activity
        # Memory extraction should be triggered
        mock_trigger.assert_called_once_with(sid)

    @patch("agenticops.web.session_manager._trigger_summary_and_memory")
    def test_remove_stale_extraction_failure_does_not_crash(self, mock_trigger, caplog):
        from agenticops.web.session_manager import ChatSessionManager

        mock_trigger.side_effect = RuntimeError("Unexpected error")
        mgr = ChatSessionManager()
        sid = "stale-crash-002"
        mgr._agents[sid] = MagicMock()
        mgr._last_activity[sid] = datetime.now(timezone.utc) - timedelta(hours=2)

        with caplog.at_level(logging.ERROR):
            mgr._remove_stale()

        # Agent should still be cleaned up even if extraction fails
        assert sid not in mgr._agents
        assert "Unexpected error during summary/memory extraction" in caplog.text

    @patch("agenticops.web.session_manager._trigger_summary_and_memory")
    def test_remove_stale_no_trigger_for_active_sessions(self, mock_trigger):
        from agenticops.web.session_manager import ChatSessionManager

        mgr = ChatSessionManager()
        sid = "active-test-003"
        mgr._agents[sid] = MagicMock()
        mgr._last_activity[sid] = datetime.now(timezone.utc)  # just now — not stale

        mgr._remove_stale()

        assert sid in mgr._agents
        mock_trigger.assert_not_called()


# ---------------------------------------------------------------------------
# PATCH archive triggers memory extraction (API level)
# ---------------------------------------------------------------------------

class TestArchiveApiMemoryExtraction:
    @patch("agenticops.web.session_manager._trigger_memory_extraction")
    def test_archive_triggers_memory_extraction(self, mock_trigger, session_with_messages):
        from starlette.testclient import TestClient
        from agenticops.web.app import app

        client = TestClient(app)
        resp = client.patch(
            f"/api/chat/sessions/{session_with_messages}",
            json={"archived": True},
        )
        assert resp.status_code == 200
        assert resp.json()["archived"] is True
        mock_trigger.assert_called_once_with(session_with_messages)

    @patch("agenticops.web.session_manager._trigger_memory_extraction")
    def test_unarchive_does_not_trigger_extraction(self, mock_trigger, session_with_messages):
        from starlette.testclient import TestClient
        from agenticops.web.app import app

        client = TestClient(app)
        # First archive
        client.patch(
            f"/api/chat/sessions/{session_with_messages}",
            json={"archived": True},
        )
        mock_trigger.reset_mock()

        # Now unarchive — should NOT trigger extraction
        resp = client.patch(
            f"/api/chat/sessions/{session_with_messages}",
            json={"archived": False},
        )
        assert resp.status_code == 200
        assert resp.json()["archived"] is False
        mock_trigger.assert_not_called()

    @patch("agenticops.web.session_manager._trigger_memory_extraction")
    def test_non_archive_patch_does_not_trigger(self, mock_trigger, session_with_messages):
        from starlette.testclient import TestClient
        from agenticops.web.app import app

        client = TestClient(app)
        resp = client.patch(
            f"/api/chat/sessions/{session_with_messages}",
            json={"pinned": True},
        )
        assert resp.status_code == 200
        mock_trigger.assert_not_called()
