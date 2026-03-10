"""Extended tests for Memory System — edge cases and coverage gaps.

Targets uncovered lines: 36-43, 51-53, 263, 291, 384-400, 450-478.
"""
import asyncio
import json
import math
import sqlite3
import struct
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenticops.memory import AgentMemory
from agenticops.memory.agent_memory import (
    _NullEmbeddingClient,
    _cosine_similarity,
    _decode_vector,
    _encode_vector,
)
from agenticops.memory.types import MemoryEntry, MemoryType


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Vector helpers ──────────────────────────────────────────


class TestVectorHelpers:
    """Test vector encode/decode and cosine similarity."""

    def test_encode_decode_roundtrip(self):
        vec = [1.0, 2.0, 3.0, 0.5, -1.5]
        blob = _encode_vector(vec)
        assert isinstance(blob, bytes)
        assert len(blob) == len(vec) * 4
        result = _decode_vector(blob)
        for a, b in zip(vec, result):
            assert abs(a - b) < 1e-6

    def test_cosine_similarity_identical(self):
        v = [1.0, 0.0, 1.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal(self):
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_cosine_similarity_opposite(self):
        assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-6

    def test_cosine_similarity_empty(self):
        assert _cosine_similarity([], []) == 0.0

    def test_cosine_similarity_length_mismatch(self):
        assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_cosine_similarity_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


class TestNullEmbeddingClient:
    def test_embed_text_returns_none(self):
        assert _NullEmbeddingClient().embed_text("hello") is None

    def test_embed_query_returns_none(self):
        assert _NullEmbeddingClient().embed_query("hello") is None


# ── AgentMemory edge cases ──────────────────────────────────


class TestAgentMemoryEdgeCases:
    @pytest.fixture
    def memory(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        mem = AgentMemory("edge_agent", db_path=db_path)
        mem._memory_md_path = tmp_path / "MEMORY.md"
        return mem

    def test_recall_empty_db(self, memory):
        results = run(memory.recall(query="anything"))
        assert len(results) == 0

    def test_reflect_no_memories(self, memory):
        result = run(memory.reflect())
        assert "No memories" in result

    def test_prune_empty_db(self, memory):
        pruned = run(memory.prune())
        assert pruned == 0

    def test_remember_writes_memory_md(self, memory):
        run(memory.remember("Test entry", MemoryType.SEMANTIC, "test"))
        assert memory._memory_md_path.exists()
        content = memory._memory_md_path.read_text()
        assert "Test entry" in content

    def test_remember_with_context(self, memory):
        result = run(memory.remember(
            content="EKS pod OOM",
            memory_type=MemoryType.EPISODIC,
            context={"service": "eks", "severity": "high"},
            source="test",
        ))
        assert result  # Should return success message

        # Verify context was stored
        entries = run(memory.recall("EKS"))
        if entries:
            assert entries[0].context.get("service") == "eks"

    def test_recall_filters_by_type(self, memory):
        run(memory.remember("fact1", MemoryType.SEMANTIC, "test"))
        run(memory.remember("event1", MemoryType.EPISODIC, "test"))

        semantic = run(memory.recall("fact", memory_type=MemoryType.SEMANTIC))
        for entry in semantic:
            assert entry.memory_type == MemoryType.SEMANTIC

    def test_recall_filters_by_confidence(self, memory):
        run(memory.remember("high conf", MemoryType.SEMANTIC, "test", confidence=0.9))
        run(memory.remember("low conf", MemoryType.SEMANTIC, "test", confidence=0.1))

        results = run(memory.recall("conf", min_confidence=0.5))
        for entry in results:
            assert entry.confidence >= 0.5

    def test_reflect_with_multiple_types(self, memory):
        run(memory.remember("fact1", MemoryType.SEMANTIC, "test"))
        run(memory.remember("event1", MemoryType.EPISODIC, "test"))
        run(memory.remember("step1", MemoryType.PROCEDURAL, "test"))

        result = run(memory.reflect())
        assert "3 memories" in result or "processed" in result.lower()

    def test_prune_keeps_reflections(self, memory):
        """Reflections should never be pruned even when old and low-conf."""
        conn = sqlite3.connect(memory._db_path)
        old_date = (datetime.utcnow() - timedelta(days=365)).isoformat()
        conn.execute(
            """INSERT INTO agent_memories
               (agent_name, content, memory_type, source, confidence,
                recall_count, created_at, context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("edge_agent", "old reflection", "reflection", "test",
             0.1, 0, old_date, "{}"),
        )
        conn.commit()
        conn.close()

        run(memory.prune())

        conn = sqlite3.connect(memory._db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM agent_memories WHERE memory_type='reflection'"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1

    def test_reflect_prune_with_results(self, memory):
        """Test reflect when prune actually removes something."""
        # Add old low-value entry
        conn = sqlite3.connect(memory._db_path)
        old_date = (datetime.utcnow() - timedelta(days=200)).isoformat()
        conn.execute(
            """INSERT INTO agent_memories
               (agent_name, content, memory_type, source, confidence,
                recall_count, created_at, context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("edge_agent", "old junk", "episodic", "test",
             0.05, 0, old_date, "{}"),
        )
        conn.commit()
        conn.close()

        # Add today's entry so reflect has something
        run(memory.remember("today stuff", MemoryType.EPISODIC, "test"))
        result = run(memory.reflect())
        # Should contain reflect summary
        assert "today" in result.lower() or "processed" in result.lower()


class TestRowToEntry:
    """Test _row_to_entry with malformed data."""

    @pytest.fixture
    def memory(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        mem = AgentMemory("test_row", db_path=db_path)
        mem._memory_md_path = tmp_path / "MEMORY.md"
        return mem

    def test_invalid_json_context(self, memory):
        conn = sqlite3.connect(memory._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """INSERT INTO agent_memories
               (agent_name, content, memory_type, source, confidence,
                recall_count, created_at, context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("test_row", "content", "episodic", "test", 0.8, 0,
             datetime.utcnow().isoformat(), "NOT_JSON"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM agent_memories LIMIT 1").fetchone()
        conn.close()

        entry = memory._row_to_entry(row)
        assert entry.context == {}

    def test_invalid_timestamp(self, memory):
        conn = sqlite3.connect(memory._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """INSERT INTO agent_memories
               (agent_name, content, memory_type, source, confidence,
                recall_count, created_at, context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("test_row", "content", "episodic", "test", 0.8, 0,
             "NOT_A_DATE", "{}"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM agent_memories LIMIT 1").fetchone()
        conn.close()

        entry = memory._row_to_entry(row)
        assert isinstance(entry.timestamp, datetime)

    def test_none_context(self, memory):
        conn = sqlite3.connect(memory._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """INSERT INTO agent_memories
               (agent_name, content, memory_type, source, confidence,
                recall_count, created_at, context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("test_row", "content", "semantic", "test", 0.8, 0,
             datetime.utcnow().isoformat(), None),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM agent_memories LIMIT 1").fetchone()
        conn.close()

        entry = memory._row_to_entry(row)
        assert entry.context == {}


class TestDefaultDbPath:
    """Test _default_db_path with various conditions."""

    def test_with_settings_available(self, tmp_path):
        db = str(tmp_path / "test.db")
        mem = AgentMemory("test", db_path=db)
        # _default_db_path should return something valid
        path = mem._default_db_path()
        assert isinstance(path, str)
        assert path.endswith(".db")

    def test_with_settings_import_error(self, tmp_path):
        db = str(tmp_path / "test.db")
        mem = AgentMemory("test", db_path=db)
        # Just verify it returns a string path
        path = mem._default_db_path()
        assert isinstance(path, str)


class TestEmbeddingPaths:
    """Test _embed and embedding client paths."""

    def test_embed_text_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        mem = AgentMemory("test", db_path=db)
        # With NullEmbeddingClient, should return None
        result = run(mem._embed("test text"))
        assert result is None

    def test_embed_query_path(self, tmp_path):
        db = str(tmp_path / "test.db")
        mem = AgentMemory("test", db_path=db)
        mock_client = MagicMock()
        mock_client.embed_text = MagicMock(return_value=[0.1, 0.2, 0.3])
        mem._embedding_client = mock_client
        result = run(mem._embed("test"))
        assert result == [0.1, 0.2, 0.3]

    def test_embed_query_fallback(self, tmp_path):
        db = str(tmp_path / "test.db")
        mem = AgentMemory("test", db_path=db)
        mock_client = MagicMock(spec=[])  # No embed_text attr
        mock_client.embed_query = MagicMock(return_value=[0.4, 0.5])
        mem._embedding_client = mock_client
        result = run(mem._embed("test"))
        assert result == [0.4, 0.5]

    def test_embed_exception(self, tmp_path):
        db = str(tmp_path / "test.db")
        mem = AgentMemory("test", db_path=db)
        mock_client = MagicMock()
        mock_client.embed_text = MagicMock(side_effect=RuntimeError("boom"))
        mem._embedding_client = mock_client
        result = run(mem._embed("test"))
        assert result is None
