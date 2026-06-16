"""Tests for chat session rename (PATCH) endpoint and auto-naming logic."""

import json
import re
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app, _generate_session_title
from agenticops.models import ChatSession, ChatMessage, get_db_session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _seed_session():
    """Create a chat session + 2 messages for tests."""
    with get_db_session() as db:
        sess = ChatSession(
            session_id="rename-test-001",
            name="Chat 2026-03-22 10:00",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            last_activity_at=datetime.now(timezone.utc),
        )
        db.add(sess)
        db.flush()
        db.add(ChatMessage(session_id=sess.id, role="user", content="hello"))
        db.add(ChatMessage(session_id=sess.id, role="assistant", content="hi there"))
    yield "rename-test-001"
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == "rename-test-001").first()
        if row:
            db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
            db.delete(row)


class TestPatchRename:

    def test_rename_success(self, client, _seed_session):
        resp = client.patch(f"/api/chat/sessions/{_seed_session}", json={"name": "My New Title"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My New Title"
        assert data["session_id"] == _seed_session

    def test_rename_not_found(self, client):
        resp = client.patch("/api/chat/sessions/nonexistent-999", json={"name": "X"})
        assert resp.status_code == 404

    def test_rename_empty_name_rejected(self, client, _seed_session):
        resp = client.patch(f"/api/chat/sessions/{_seed_session}", json={"name": ""})
        assert resp.status_code == 422

    def test_rename_too_long_rejected(self, client, _seed_session):
        resp = client.patch(f"/api/chat/sessions/{_seed_session}", json={"name": "x" * 201})
        assert resp.status_code == 422


class TestGenerateSessionTitle:

    @patch("agenticops.config.get_bedrock_boto_session")
    def test_returns_title(self, mock_get_session):
        mock_client = MagicMock()
        mock_get_session.return_value.client.return_value = mock_client
        mock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(return_value=json.dumps({
                    "content": [{"text": "AWS Health Check Setup"}]
                }).encode())
            )
        }
        title = _generate_session_title("check my aws health", "I found 3 issues in us-east-1")
        assert title == "AWS Health Check Setup"

    @patch("agenticops.config.get_bedrock_boto_session", side_effect=Exception("No credentials"))
    def test_returns_none_on_failure(self, mock_get_session):
        result = _generate_session_title("hello", "hi")
        assert result is None

    @patch("agenticops.config.get_bedrock_boto_session")
    def test_returns_none_on_empty_response(self, mock_get_session):
        mock_client = MagicMock()
        mock_get_session.return_value.client.return_value = mock_client
        mock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(return_value=json.dumps({"content": [{"text": ""}]}).encode())
            )
        }
        result = _generate_session_title("hi", "hello")
        assert result is None


class TestAutoNamingConditions:
    """Verify the regex pattern used in app.py to detect default session names."""

    AUTO_NAME_PATTERN = r"^Chat \d{4}-\d{2}-\d{2}"

    def test_custom_name_does_not_match(self):
        assert not re.match(self.AUTO_NAME_PATTERN, "My Custom Session")

    def test_default_name_matches(self):
        assert re.match(self.AUTO_NAME_PATTERN, "Chat 2026-03-22 10:00")
