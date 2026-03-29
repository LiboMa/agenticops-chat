"""Unit tests for SummaryService — generate_summary and get_summaries."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import Base, SessionSummary, ChatSession, get_engine, init_db
from agenticops.web.summary_service import SummaryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_engine():
    """Create an in-memory SQLite engine with all tables."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def db_session(db_engine):
    """Yield a DB session bound to the in-memory engine."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def chat_session(db_session) -> ChatSession:
    """Create a ChatSession row and return it."""
    cs = ChatSession(
        session_id="test-uuid-1234",
        name="Test Session",
    )
    db_session.add(cs)
    db_session.commit()
    db_session.refresh(cs)
    return cs


@pytest.fixture()
def service():
    """Return a SummaryService with a mocked Bedrock client."""
    svc = SummaryService.__new__(SummaryService)
    svc.region = "us-east-1"
    svc.model_id = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    svc._client = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# _format_messages
# ---------------------------------------------------------------------------

class TestFormatMessages:
    def test_simple_text_messages(self, service):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = service._format_messages(msgs)
        assert "user: Hello" in result
        assert "assistant: Hi there" in result

    def test_strands_content_blocks(self, service):
        msgs = [
            {"role": "assistant", "content": [
                {"text": "Let me check."},
                {"toolUse": {"name": "list_resources", "input": {}}},
            ]},
            {"role": "user", "content": [
                {"toolResult": {"toolUseId": "x", "content": [{"text": "ok"}]}},
            ]},
        ]
        result = service._format_messages(msgs)
        assert "Let me check." in result
        assert "[Tool: list_resources]" in result
        assert "[Tool Result]" in result

    def test_empty_messages(self, service):
        assert service._format_messages([]) == ""

    def test_missing_content(self, service):
        msgs = [{"role": "user"}]
        # Should not crash — empty content is skipped
        result = service._format_messages(msgs)
        assert result == ""


# ---------------------------------------------------------------------------
# generate_summary
# ---------------------------------------------------------------------------

class TestGenerateSummary:
    def _mock_bedrock_response(self, mock_client, text="This is a summary."):
        body_bytes = json.dumps({"content": [{"text": text}]}).encode()
        mock_body = MagicMock()
        mock_body.read.return_value = body_bytes
        mock_client.invoke_model.return_value = {"body": mock_body}

    @patch("agenticops.web.summary_service.get_db_session")
    def test_generates_and_stores_summary(self, mock_get_db, service):
        self._mock_bedrock_response(service._client, "Summary of conversation.")
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        messages = [
            {"role": "user", "content": "What is EC2?", "_db_id": 10},
            {"role": "assistant", "content": "EC2 is a compute service.", "_db_id": 11},
        ]
        result = service.generate_summary(messages, session_id=1)

        assert result == "Summary of conversation."
        # Verify invoke_model was called
        service._client.invoke_model.assert_called_once()
        call_kwargs = service._client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == service.model_id
        # Verify DB add was called
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, SessionSummary)
        assert added.session_id == 1
        assert added.summary_text == "Summary of conversation."
        assert added.message_range_start == 10
        assert added.message_range_end == 11

    def test_returns_none_for_empty_messages(self, service):
        result = service.generate_summary([], session_id=1)
        assert result is None
        service._client.invoke_model.assert_not_called()

    @patch("agenticops.web.summary_service.get_db_session")
    def test_returns_none_on_bedrock_error(self, mock_get_db, service):
        from botocore.exceptions import ClientError

        service._client.invoke_model.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "InvokeModel",
        )
        messages = [{"role": "user", "content": "test", "_db_id": 1}]
        result = service.generate_summary(messages, session_id=1)

        assert result is None
        # DB should NOT have been called since error happened before persist
        mock_get_db.assert_not_called()

    @patch("agenticops.web.summary_service.get_db_session")
    def test_max_tokens_in_request(self, mock_get_db, service):
        self._mock_bedrock_response(service._client)
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        messages = [{"role": "user", "content": "hi", "_db_id": 1}]
        service.generate_summary(messages, session_id=1)

        call_kwargs = service._client.invoke_model.call_args[1]
        body = json.loads(call_kwargs["body"])
        assert body["max_tokens"] == 500


# ---------------------------------------------------------------------------
# get_summaries
# ---------------------------------------------------------------------------

class TestGetSummaries:
    @patch("agenticops.web.summary_service.get_db_session")
    def test_returns_summaries_ordered_by_created_at(self, mock_get_db):
        s1 = SessionSummary(
            id=1, session_id=1, summary_text="First",
            message_range_start=1, message_range_end=5,
            created_at=datetime(2026, 1, 1, 10, 0),
        )
        s2 = SessionSummary(
            id=2, session_id=1, summary_text="Second",
            message_range_start=6, message_range_end=10,
            created_at=datetime(2026, 1, 1, 11, 0),
        )

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.order_by.return_value = mock_order
        mock_order.all.return_value = [s1, s2]

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = SummaryService.__new__(SummaryService)
        svc.region = "us-east-1"
        svc.model_id = "test"
        svc._client = None

        result = svc.get_summaries(session_id=1)
        assert len(result) == 2
        assert result[0].summary_text == "First"
        assert result[1].summary_text == "Second"

    @patch("agenticops.web.summary_service.get_db_session")
    def test_returns_empty_list_when_no_summaries(self, mock_get_db):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.order_by.return_value = mock_order
        mock_order.all.return_value = []

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        svc = SummaryService.__new__(SummaryService)
        svc.region = "us-east-1"
        svc.model_id = "test"
        svc._client = None

        result = svc.get_summaries(session_id=999)
        assert result == []
