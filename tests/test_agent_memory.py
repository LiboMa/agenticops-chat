"""Tests for the per-agent memory system."""

import asyncio
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenticops.memory import AgentMemory, clear_memory_cache, get_agent_memory
from agenticops.memory.types import MemoryEntry, MemoryType, decayed_confidence
from agenticops.utils.timeutils import utc_now


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite DB path."""
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def memory(tmp_db, tmp_path):
    """Create an AgentMemory instance for testing."""
    mem = AgentMemory("test_agent", db_path=tmp_db)
    mem._memory_md_path = tmp_path / "test_agent_MEMORY.md"
    return mem


@pytest.fixture
def memory_b(tmp_db, tmp_path):
    """Create a second AgentMemory for isolation tests."""
    mem = AgentMemory("other_agent", db_path=tmp_db)
    mem._memory_md_path = tmp_path / "other_agent_MEMORY.md"
    return mem


def run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestMemoryTypes:
    """Test data types and helpers."""

    def test_memory_type_values(self):
        assert MemoryType.EPISODIC.value == "episodic"
        assert MemoryType.PROCEDURAL.value == "procedural"
        assert MemoryType.SEMANTIC.value == "semantic"
        assert MemoryType.REFLECTION.value == "reflection"

    def test_memory_entry_id(self):
        entry = MemoryEntry(
            agent_name="rca_agent",
            memory_type=MemoryType.EPISODIC,
            content="Test memory",
        )
        assert entry.memory_id.startswith("rca_agent:")

    def test_decayed_confidence_no_decay(self):
        entry = MemoryEntry(
            agent_name="test",
            memory_type=MemoryType.EPISODIC,
            content="test",
            confidence=1.0,
            recall_count=0,
        )
        now = entry.timestamp
        assert decayed_confidence(entry, now) == pytest.approx(1.0)

    def test_decayed_confidence_with_age(self):
        entry = MemoryEntry(
            agent_name="test",
            memory_type=MemoryType.EPISODIC,
            content="test",
            confidence=1.0,
            recall_count=0,
            timestamp=utc_now() - timedelta(days=100),
        )
        dc = decayed_confidence(entry)
        # 0.99^100 ≈ 0.366
        assert 0.3 < dc < 0.4

    def test_decayed_confidence_recall_boost(self):
        entry = MemoryEntry(
            agent_name="test",
            memory_type=MemoryType.EPISODIC,
            content="test",
            confidence=1.0,
            recall_count=10,
        )
        now = entry.timestamp
        # recall_boost = 1 + 0.1 * 10 = 2.0
        assert decayed_confidence(entry, now) == pytest.approx(2.0)


class TestAgentMemory:
    """Test core AgentMemory operations."""

    def test_remember_and_recall(self, memory):
        """remember() → recall() returns the entry."""
        entry = run(memory.remember("EKS pod crashed due to OOM", source="rca:42"))
        assert entry.id is not None
        assert entry.agent_name == "test_agent"

        results = run(memory.recall("EKS pod OOM crash"))
        assert len(results) >= 1
        assert results[0].content == "EKS pod crashed due to OOM"

    def test_remember_sets_type(self, memory):
        """memory_type is correctly stored."""
        entry = run(memory.remember(
            "Redis diagnosis: check client list first",
            memory_type=MemoryType.PROCEDURAL,
        ))
        assert entry.memory_type == MemoryType.PROCEDURAL

        results = run(memory.recall_recent())
        assert results[0].memory_type == MemoryType.PROCEDURAL

    def test_recall_filters_by_type(self, memory):
        """memory_type filter works."""
        run(memory.remember("episodic memory", memory_type=MemoryType.EPISODIC))
        run(memory.remember("procedural memory", memory_type=MemoryType.PROCEDURAL))

        results = run(memory.recall("memory", memory_type=MemoryType.PROCEDURAL))
        assert all(r.memory_type == MemoryType.PROCEDURAL for r in results)

    def test_recall_filters_by_confidence(self, memory):
        """min_confidence filter excludes low-confidence entries."""
        run(memory.remember("high confidence", confidence=0.9))
        run(memory.remember("low confidence", confidence=0.1))

        results = run(memory.recall("confidence", min_confidence=0.5))
        assert all(r.confidence >= 0.5 for r in results)

    def test_recall_increments_recall_count(self, memory):
        """recall() increments the recall_count on returned entries."""
        run(memory.remember("important fact"))
        results1 = run(memory.recall("important"))
        assert results1[0].recall_count == 1

        results2 = run(memory.recall("important"))
        assert results2[0].recall_count == 2

    def test_recall_recent(self, memory):
        """recall_recent returns entries in reverse chronological order."""
        run(memory.remember("first"))
        run(memory.remember("second"))
        run(memory.remember("third"))

        results = run(memory.recall_recent(limit=2))
        assert len(results) == 2
        assert results[0].content == "third"
        assert results[1].content == "second"

    def test_recall_semantic_search_with_mock_embeddings(self, memory):
        """Similar query finds related memories via cosine similarity."""
        # Mock embedding client with deterministic vectors
        mock_client = MagicMock()
        vectors = {
            "EKS pod crashed due to OOM": [1.0, 0.0, 0.0],
            "Lambda function timeout": [0.0, 1.0, 0.0],
            "EKS pod memory issue": [0.9, 0.1, 0.0],  # Similar to first
        }
        mock_client.embed_text.side_effect = lambda t: vectors.get(t, [0.0, 0.0, 0.0])
        memory._embedding_client = mock_client

        run(memory.remember("EKS pod crashed due to OOM"))
        run(memory.remember("Lambda function timeout"))

        results = run(memory.recall("EKS pod memory issue"))
        assert len(results) >= 1
        # The OOM entry should rank higher than Lambda
        assert "OOM" in results[0].content

    def test_prune_keeps_high_value(self, memory):
        """High confidence + high recall entries survive pruning."""
        # Create entries with varying quality
        for i in range(5):
            run(memory.remember(f"low value {i}", confidence=0.1))

        high_entry = run(memory.remember("high value", confidence=1.0))
        # Simulate recalls
        conn = memory._get_conn()
        conn.execute(
            "UPDATE agent_memories SET recall_count = 10 WHERE id = ?",
            (high_entry.id,),
        )
        conn.commit()
        conn.close()

        pruned = run(memory.prune(keep=3))
        assert pruned == 3

        remaining = run(memory.recall_recent(limit=10))
        contents = [r.content for r in remaining]
        assert "high value" in contents

    def test_prune_removes_old_low_value(self, memory):
        """Old entries with low confidence and 0 recalls are pruned."""
        # Insert old low-value entries directly
        conn = memory._get_conn()
        old_date = (utc_now() - timedelta(days=200)).isoformat()
        for i in range(5):
            conn.execute(
                "INSERT INTO agent_memories (agent_name, memory_type, content, confidence, recall_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test_agent", "episodic", f"old entry {i}", 0.1, 0, old_date),
            )
        conn.commit()
        conn.close()

        # Add fresh high-value entry
        run(memory.remember("fresh important", confidence=1.0))

        pruned = run(memory.prune(keep=3))
        assert pruned >= 3

    def test_prune_never_removes_reflections(self, memory):
        """REFLECTION type entries are never pruned."""
        run(memory.remember("reflection summary", memory_type=MemoryType.REFLECTION))
        for i in range(5):
            run(memory.remember(f"filler {i}", confidence=0.1))

        run(memory.prune(keep=2))

        # Check reflection still exists
        conn = memory._get_conn()
        reflections = conn.execute(
            "SELECT * FROM agent_memories WHERE agent_name = ? AND memory_type = 'reflection'",
            ("test_agent",),
        ).fetchall()
        conn.close()
        assert len(reflections) == 1

    def test_memory_isolation(self, memory, memory_b):
        """Agent A's memory is invisible to Agent B."""
        run(memory.remember("secret A"))
        run(memory_b.remember("secret B"))

        results_a = run(memory.recall("secret"))
        results_b = run(memory_b.recall("secret"))

        assert all(r.agent_name == "test_agent" for r in results_a)
        assert all(r.agent_name == "other_agent" for r in results_b)
        assert "secret A" in results_a[0].content
        assert "secret B" in results_b[0].content

    def test_memory_md_append(self, memory):
        """remember() appends to MEMORY.md file."""
        run(memory.remember("test content", source="test:1"))
        assert memory._memory_md_path.exists()
        content = memory._memory_md_path.read_text()
        assert "test content" in content
        assert "test:1" in content

    def test_null_embedding_fallback(self, tmp_db, tmp_path):
        """Works with NullEmbeddingClient (no vector search, only recency)."""
        mem = AgentMemory("null_test", db_path=tmp_db)
        mem._memory_md_path = tmp_path / "null_MEMORY.md"
        # Force null embedding
        from agenticops.memory.agent_memory import _NullEmbeddingClient
        mem._embedding_client = _NullEmbeddingClient()

        run(mem.remember("memory without vectors"))
        results = run(mem.recall("memory"))
        assert len(results) == 1
        assert results[0].content == "memory without vectors"

    def test_reflect(self, memory):
        """reflect() creates a REFLECTION summary."""
        run(memory.remember("incident 1: CPU spike"))
        run(memory.remember("incident 2: memory leak"))

        summary = run(memory.reflect())
        assert "2 memories" in summary or "processed" in summary

        # Check reflection was stored
        reflections = run(memory.recall_recent(memory_type=MemoryType.REFLECTION))
        assert len(reflections) >= 1

    def test_reflect_with_llm(self, memory):
        """reflect(llm=...) uses self-questioning pattern."""
        run(memory.remember("incident: CPU spike on i-abc123"))
        run(memory.remember("fix: scaled ASG from 2 to 4"))
        run(memory.remember("incident: OOM on pod frontend-xyz"))

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            # Question generation
            '["What recurring resource issues appeared?", "Which fixes were most effective?", "What should be monitored?"]',
            # Insight 1
            "CPU and memory pressure are the dominant patterns.",
            # Insight 2
            "ASG scaling resolved CPU issues quickly.",
            # Insight 3
            "Monitor resource utilization proactively.",
        ]

        summary = run(memory.reflect(llm=mock_llm))
        assert "What recurring" in summary
        assert mock_llm.invoke.call_count == 4  # 1 question + 3 insights

        # Reflection stored
        reflections = run(memory.recall_recent(memory_type=MemoryType.REFLECTION))
        assert any("daily_reflect_llm" in r.source for r in reflections)

    def test_reflect_llm_fallback(self, memory):
        """reflect(llm=...) falls back to basic if LLM fails."""
        run(memory.remember("incident: disk full"))

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("LLM unavailable")

        summary = run(memory.reflect(llm=mock_llm))
        # Should still produce a basic summary
        assert "1 memories" in summary or "processed" in summary

    def test_get_stats(self, memory):
        """get_stats returns correct counts."""
        run(memory.remember("ep1", memory_type=MemoryType.EPISODIC))
        run(memory.remember("ep2", memory_type=MemoryType.EPISODIC))
        run(memory.remember("proc1", memory_type=MemoryType.PROCEDURAL))

        stats = memory.get_stats()
        assert stats["total_memories"] == 3
        assert stats["by_type"]["episodic"] == 2
        assert stats["by_type"]["procedural"] == 1

    def test_confidence_clamping(self, memory):
        """Confidence is clamped to [0.0, 1.0]."""
        entry = run(memory.remember("over", confidence=1.5))
        assert entry.confidence == 1.0

        entry = run(memory.remember("under", confidence=-0.5))
        assert entry.confidence == 0.0


class TestGetAgentMemory:
    """Test factory function."""

    def test_singleton_pattern(self, tmp_db):
        clear_memory_cache()
        with patch("agenticops.memory.AgentMemory") as MockMem:
            MockMem.return_value = MagicMock()
            m1 = get_agent_memory("test", db_path=tmp_db)
            m2 = get_agent_memory("test", db_path=tmp_db)
            assert m1 is m2

    def test_different_agents(self, tmp_db):
        clear_memory_cache()
        m1 = get_agent_memory("agent_a", db_path=tmp_db)
        m2 = get_agent_memory("agent_b", db_path=tmp_db)
        assert m1 is not m2
        assert m1.agent_name == "agent_a"
        assert m2.agent_name == "agent_b"
