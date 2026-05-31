"""Tests for memory API endpoints (facts + experiences).

Validates Requirements: 6.5, 7.1
"""

from datetime import datetime

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app
from agenticops.models import AgentMemory, AgentMemoryFact, get_db_session, init_db


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    """Ensure all tables (including agent_memory_facts) exist."""
    init_db()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _seed_facts():
    """Create sample facts with varying confidence scores."""
    fact_ids = []
    with get_db_session() as db:
        facts = [
            AgentMemoryFact(
                category="user_preference",
                key="preferred_region",
                value="us-west-2",
                confidence_score=0.95,
                source_session_id="test-session-001",
            ),
            AgentMemoryFact(
                category="infra_context",
                key="naming_convention",
                value="kebab-case",
                confidence_score=0.8,
                source_session_id="test-session-001",
            ),
            AgentMemoryFact(
                category="team_info",
                key="oncall_team",
                value="platform-eng",
                confidence_score=0.5,
                source_session_id="test-session-002",
            ),
        ]
        db.add_all(facts)
        db.flush()
        fact_ids = [f.id for f in facts]
    yield fact_ids
    # Cleanup
    with get_db_session() as db:
        for fid in fact_ids:
            row = db.query(AgentMemoryFact).filter(AgentMemoryFact.id == fid).first()
            if row:
                db.delete(row)


# ---------------------------------------------------------------------------
# GET /api/memory/facts
# ---------------------------------------------------------------------------


class TestGetMemoryFacts:
    """Validates: Requirement 6.5 — query structured facts."""

    def test_get_facts_default_confidence(self, client, _seed_facts):
        resp = client.get("/api/memory/facts")
        assert resp.status_code == 200
        data = resp.json()
        # Default min_confidence=0.7 should exclude the 0.5 fact
        assert len(data) >= 2
        for fact in data:
            assert fact["confidence_score"] >= 0.7

    def test_get_facts_custom_confidence(self, client, _seed_facts):
        resp = client.get("/api/memory/facts", params={"min_confidence": 0.4})
        assert resp.status_code == 200
        data = resp.json()
        # All 3 seeded facts should be returned
        assert len(data) >= 3
        for fact in data:
            assert fact["confidence_score"] >= 0.4

    def test_get_facts_high_confidence_filter(self, client, _seed_facts):
        resp = client.get("/api/memory/facts", params={"min_confidence": 0.9})
        assert resp.status_code == 200
        data = resp.json()
        # Only the 0.95 fact should pass
        assert len(data) >= 1
        for fact in data:
            assert fact["confidence_score"] >= 0.9

    def test_get_facts_response_fields(self, client, _seed_facts):
        resp = client.get("/api/memory/facts", params={"min_confidence": 0.0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        fact = data[0]
        assert "id" in fact
        assert "category" in fact
        assert "key" in fact
        assert "value" in fact
        assert "confidence_score" in fact
        assert "source_session_id" in fact
        assert "created_at" in fact
        assert "updated_at" in fact

    def test_get_facts_empty_when_high_threshold(self, client, _seed_facts):
        resp = client.get("/api/memory/facts", params={"min_confidence": 1.0})
        assert resp.status_code == 200
        data = resp.json()
        # No facts have confidence_score == 1.0
        high_conf = [f for f in data if f["confidence_score"] >= 1.0]
        assert len(high_conf) == 0


# ---------------------------------------------------------------------------
# DELETE /api/memory/facts/{id}
# ---------------------------------------------------------------------------


class TestDeleteMemoryFact:
    """Validates: Requirement 6.5 — delete a specific fact."""

    def test_delete_fact_success(self, client, _seed_facts):
        fact_id = _seed_facts[0]
        resp = client.delete(f"/api/memory/facts/{fact_id}")
        assert resp.status_code == 204

        # Verify it's gone
        with get_db_session() as db:
            row = db.query(AgentMemoryFact).filter(AgentMemoryFact.id == fact_id).first()
            assert row is None

    def test_delete_fact_not_found(self, client):
        resp = client.delete("/api/memory/facts/999999")
        assert resp.status_code == 404

    def test_delete_fact_removes_from_query(self, client, _seed_facts):
        fact_id = _seed_facts[0]
        # Delete the fact
        resp = client.delete(f"/api/memory/facts/{fact_id}")
        assert resp.status_code == 204

        # Query should no longer include it
        resp = client.get("/api/memory/facts", params={"min_confidence": 0.0})
        assert resp.status_code == 200
        ids_returned = [f["id"] for f in resp.json()]
        assert fact_id not in ids_returned


# ---------------------------------------------------------------------------
# GET /api/memory/experiences
# ---------------------------------------------------------------------------


@pytest.fixture
def _seed_experiences():
    """Create sample experience memories."""
    exp_ids = []
    with get_db_session() as db:
        experiences = [
            AgentMemory(
                session_id="test-session-001",
                memory_type="problem",
                content_text="EC2 instance i-abc123 had high CPU utilization above 95%",
                embedding_vector=None,
            ),
            AgentMemory(
                session_id="test-session-001",
                memory_type="root_cause",
                content_text="Memory leak in Java application caused excessive GC",
                embedding_vector=b"\x00" * 16,  # dummy bytes
            ),
            AgentMemory(
                session_id="test-session-002",
                memory_type="solution",
                content_text="Restarted the application and increased heap size to 4GB",
                embedding_vector=None,
            ),
        ]
        db.add_all(experiences)
        db.flush()
        exp_ids = [e.id for e in experiences]
    yield exp_ids
    # Cleanup
    with get_db_session() as db:
        for eid in exp_ids:
            row = db.query(AgentMemory).filter(AgentMemory.id == eid).first()
            if row:
                db.delete(row)


class TestGetMemoryExperiences:
    """Validates: Requirement 7.1 — query vectorized experiences."""

    def test_get_experiences_returns_all(self, client, _seed_experiences):
        resp = client.get("/api/memory/experiences")
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = [e["id"] for e in data]
        for eid in _seed_experiences:
            assert eid in returned_ids

    def test_get_experiences_response_fields(self, client, _seed_experiences):
        resp = client.get("/api/memory/experiences")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        exp = data[0]
        assert "id" in exp
        assert "session_id" in exp
        assert "memory_type" in exp
        assert "content_text" in exp
        assert "created_at" in exp

    def test_get_experiences_excludes_embedding_vector(self, client, _seed_experiences):
        resp = client.get("/api/memory/experiences")
        assert resp.status_code == 200
        data = resp.json()
        for exp in data:
            assert "embedding_vector" not in exp

    def test_get_experiences_empty_when_none(self, client):
        # Clean all experiences first
        with get_db_session() as db:
            db.query(AgentMemory).delete()
        resp = client.get("/api/memory/experiences")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_experiences_ordered_by_created_at_desc(self, client, _seed_experiences):
        resp = client.get("/api/memory/experiences")
        assert resp.status_code == 200
        data = resp.json()
        if len(data) >= 2:
            dates = [e["created_at"] for e in data]
            assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# Agent Memory (file-based) — list with created_by
# ---------------------------------------------------------------------------


def test_list_memories_includes_created_by(tmp_path):
    from unittest.mock import patch
    mem_dir = tmp_path / "agent-memory"
    (mem_dir / "detect").mkdir(parents=True)
    with patch("agenticops.memory.agent_memory.AGENT_MEMORY_DIR", mem_dir):
        from agenticops.memory.agent_memory import save_memory_file, list_memories
        save_memory_file(agent_name="detect", filename="x.md", body="b", created_by="agent")
        rows = list_memories(agent_name="detect", status_filter="active")
        assert rows and rows[0]["created_by"] == "agent"
        assert "last_used" in rows[0]
