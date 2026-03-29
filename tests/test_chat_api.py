"""Tests for chat session metadata CRUD (pinned/starred/archived) and include_archived filtering.

Validates Requirements: 3.1-3.6, 3.9, 3.10
"""

from datetime import datetime, timedelta

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app
from agenticops.models import ChatSession, ChatMessage, get_db_session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _seed_sessions():
    """Create 3 sessions: one normal, one archived, one pinned+starred."""
    ids = {
        "normal": "meta-test-normal-001",
        "archived": "meta-test-archived-002",
        "pinned_starred": "meta-test-pinstar-003",
    }
    now = datetime.utcnow()
    with get_db_session() as db:
        s1 = ChatSession(
            session_id=ids["normal"], name="Normal Session",
            created_at=now, updated_at=now, last_activity_at=now,
        )
        s2 = ChatSession(
            session_id=ids["archived"], name="Archived Session",
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
            last_activity_at=now - timedelta(hours=1),
            archived=True,
        )
        s3 = ChatSession(
            session_id=ids["pinned_starred"], name="Pinned Starred Session",
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=30),
            last_activity_at=now - timedelta(minutes=30),
            pinned=True, starred=True,
        )
        db.add_all([s1, s2, s3])
    yield ids
    # Cleanup
    with get_db_session() as db:
        for sid in ids.values():
            row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)


# ---------------------------------------------------------------------------
# PATCH pinned / starred / archived
# ---------------------------------------------------------------------------

class TestPatchPinned:
    """Validates: Requirements 3.1, 3.4"""

    def test_pin_session(self, client, _seed_sessions):
        sid = _seed_sessions["normal"]
        resp = client.patch(f"/api/chat/sessions/{sid}", json={"pinned": True})
        assert resp.status_code == 200
        assert resp.json()["pinned"] is True

    def test_unpin_session(self, client, _seed_sessions):
        sid = _seed_sessions["pinned_starred"]
        resp = client.patch(f"/api/chat/sessions/{sid}", json={"pinned": False})
        assert resp.status_code == 200
        assert resp.json()["pinned"] is False

    def test_pin_preserves_other_fields(self, client, _seed_sessions):
        sid = _seed_sessions["pinned_starred"]
        resp = client.patch(f"/api/chat/sessions/{sid}", json={"pinned": False})
        data = resp.json()
        assert data["starred"] is True  # starred unchanged
        assert data["name"] == "Pinned Starred Session"


class TestPatchStarred:
    """Validates: Requirements 3.2, 3.5"""

    def test_star_session(self, client, _seed_sessions):
        sid = _seed_sessions["normal"]
        resp = client.patch(f"/api/chat/sessions/{sid}", json={"starred": True})
        assert resp.status_code == 200
        assert resp.json()["starred"] is True

    def test_unstar_session(self, client, _seed_sessions):
        sid = _seed_sessions["pinned_starred"]
        resp = client.patch(f"/api/chat/sessions/{sid}", json={"starred": False})
        assert resp.status_code == 200
        assert resp.json()["starred"] is False


class TestPatchArchived:
    """Validates: Requirements 3.3, 3.6"""

    def test_archive_session(self, client, _seed_sessions):
        sid = _seed_sessions["normal"]
        resp = client.patch(f"/api/chat/sessions/{sid}", json={"archived": True})
        assert resp.status_code == 200
        assert resp.json()["archived"] is True

    def test_unarchive_session(self, client, _seed_sessions):
        sid = _seed_sessions["archived"]
        resp = client.patch(f"/api/chat/sessions/{sid}", json={"archived": False})
        assert resp.status_code == 200
        assert resp.json()["archived"] is False


class TestPatchMultipleFields:
    """Validates: Requirements 3.1-3.6 — multiple fields in one PATCH."""

    def test_update_all_metadata_at_once(self, client, _seed_sessions):
        sid = _seed_sessions["normal"]
        resp = client.patch(
            f"/api/chat/sessions/{sid}",
            json={"pinned": True, "starred": True, "archived": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pinned"] is True
        assert data["starred"] is True
        assert data["archived"] is True

    def test_patch_nonexistent_session(self, client):
        resp = client.patch(
            "/api/chat/sessions/does-not-exist-999",
            json={"pinned": True},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET sessions — include_archived filtering
# ---------------------------------------------------------------------------

class TestListSessionsArchiveFilter:
    """Validates: Requirements 3.9, 3.10"""

    def test_default_excludes_archived(self, client, _seed_sessions):
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        session_ids = [s["session_id"] for s in resp.json()]
        assert _seed_sessions["archived"] not in session_ids
        assert _seed_sessions["normal"] in session_ids

    def test_include_archived_true(self, client, _seed_sessions):
        resp = client.get("/api/chat/sessions", params={"include_archived": True})
        assert resp.status_code == 200
        session_ids = [s["session_id"] for s in resp.json()]
        assert _seed_sessions["archived"] in session_ids
        assert _seed_sessions["normal"] in session_ids

    def test_include_archived_false_explicit(self, client, _seed_sessions):
        resp = client.get("/api/chat/sessions", params={"include_archived": False})
        assert resp.status_code == 200
        session_ids = [s["session_id"] for s in resp.json()]
        assert _seed_sessions["archived"] not in session_ids


class TestListSessionsResponseFields:
    """Validates: Requirements 3.1-3.3 — response includes metadata fields."""

    def test_response_contains_metadata_fields(self, client, _seed_sessions):
        resp = client.get("/api/chat/sessions", params={"include_archived": True})
        assert resp.status_code == 200
        sessions_by_id = {s["session_id"]: s for s in resp.json()}

        normal = sessions_by_id.get(_seed_sessions["normal"])
        assert normal is not None
        assert normal["pinned"] is False
        assert normal["starred"] is False
        assert normal["archived"] is False

        archived = sessions_by_id.get(_seed_sessions["archived"])
        assert archived is not None
        assert archived["archived"] is True

        pinstar = sessions_by_id.get(_seed_sessions["pinned_starred"])
        assert pinstar is not None
        assert pinstar["pinned"] is True
        assert pinstar["starred"] is True
        assert pinstar["archived"] is False
