"""Tests for WAL enforcement decorator."""

import asyncio
from unittest.mock import MagicMock

import pytest

from agenticops.memory import AgentMemory, MemoryType
from agenticops.memory.agent_memory import _NullEmbeddingClient
from agenticops.memory.wal import set_wal_agent, wal_enforced


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_wal.db")


@pytest.fixture
def memory(tmp_db, tmp_path):
    mem = AgentMemory("test_agent", db_path=tmp_db)
    mem._memory_md_path = tmp_path / "test_MEMORY.md"
    mem._embedding_client = _NullEmbeddingClient()
    return mem


def run(coro):
    return asyncio.run(coro)


class TestWalEnforced:
    """Test the @wal_enforced decorator."""

    def test_sync_function_recorded(self, memory, monkeypatch):
        """Sync function execution is recorded in memory."""
        set_wal_agent("test_agent")
        monkeypatch.setattr(
            "agenticops.memory.wal.get_agent_memory",
            lambda name: memory,
        )

        @wal_enforced
        def my_tool(x: int) -> str:
            return f"result_{x}"

        result = my_tool(42)
        assert result == "result_42"

        # Check memory was written
        memories = run(memory.recall_recent(limit=5))
        assert len(memories) >= 1
        assert "my_tool" in memories[0].content
        assert "result_42" in memories[0].content

    def test_async_function_recorded(self, memory, monkeypatch):
        """Async function execution is recorded in memory."""
        set_wal_agent("test_agent")
        monkeypatch.setattr(
            "agenticops.memory.wal.get_agent_memory",
            lambda name: memory,
        )

        @wal_enforced
        async def async_tool(name: str) -> dict:
            return {"status": "ok", "name": name}

        result = run(async_tool("test"))
        assert result == {"status": "ok", "name": "test"}

        memories = run(memory.recall_recent(limit=5))
        assert len(memories) >= 1
        assert "async_tool" in memories[0].content

    def test_preserves_function_name(self):
        """Decorator preserves original function name."""

        @wal_enforced
        def important_operation():
            return "done"

        assert important_operation.__name__ == "important_operation"

    def test_custom_memory_type(self, memory, monkeypatch):
        """Can specify custom memory type."""
        set_wal_agent("test_agent")
        monkeypatch.setattr(
            "agenticops.memory.wal.get_agent_memory",
            lambda name: memory,
        )

        @wal_enforced(memory_type=MemoryType.PROCEDURAL)
        def procedural_tool():
            return "step completed"

        procedural_tool()

        memories = run(memory.recall_recent(limit=5))
        assert memories[0].memory_type == MemoryType.PROCEDURAL

    def test_failure_does_not_block_tool(self, monkeypatch):
        """WAL failure must never block the tool execution."""
        set_wal_agent("test_agent")

        # Make memory fail
        def failing_memory(name):
            raise Exception("DB connection lost")

        monkeypatch.setattr(
            "agenticops.memory.wal.get_agent_memory",
            failing_memory,
        )

        @wal_enforced
        def critical_tool():
            return "important_result"

        # Tool should still work even if WAL fails
        result = critical_tool()
        assert result == "important_result"

    def test_context_includes_args(self, memory, monkeypatch):
        """WAL context includes tool arguments."""
        set_wal_agent("test_agent")
        monkeypatch.setattr(
            "agenticops.memory.wal.get_agent_memory",
            lambda name: memory,
        )

        @wal_enforced
        def check_resource(resource_id: str, region: str = "us-east-1"):
            return f"checked {resource_id}"

        check_resource("i-abc123", region="ap-southeast-1")

        memories = run(memory.recall_recent(limit=5))
        assert memories[0].context.get("tool") == "check_resource"

    def test_result_summary_truncated(self, memory, monkeypatch):
        """Long results are truncated in WAL entry."""
        set_wal_agent("test_agent")
        monkeypatch.setattr(
            "agenticops.memory.wal.get_agent_memory",
            lambda name: memory,
        )

        @wal_enforced
        def verbose_tool():
            return "x" * 500

        verbose_tool()

        memories = run(memory.recall_recent(limit=5))
        # Content should be truncated
        assert len(memories[0].content) < 300

    def test_wal_source_tag(self, memory, monkeypatch):
        """WAL entries have source tag 'wal:<tool_name>'."""
        set_wal_agent("test_agent")
        monkeypatch.setattr(
            "agenticops.memory.wal.get_agent_memory",
            lambda name: memory,
        )

        @wal_enforced
        def tagged_tool():
            return "ok"

        tagged_tool()

        memories = run(memory.recall_recent(limit=5))
        assert memories[0].source == "wal:tagged_tool"

    def test_agent_isolation(self, tmp_db, tmp_path, monkeypatch):
        """Different agents get separate WAL entries."""
        mem_a = AgentMemory("agent_a", db_path=tmp_db)
        mem_a._memory_md_path = tmp_path / "a_MEMORY.md"
        mem_a._embedding_client = _NullEmbeddingClient()

        mem_b = AgentMemory("agent_b", db_path=tmp_db)
        mem_b._memory_md_path = tmp_path / "b_MEMORY.md"
        mem_b._embedding_client = _NullEmbeddingClient()

        memories = {"agent_a": mem_a, "agent_b": mem_b}
        monkeypatch.setattr(
            "agenticops.memory.wal.get_agent_memory",
            lambda name: memories[name],
        )

        @wal_enforced
        def shared_tool():
            return "done"

        set_wal_agent("agent_a")
        shared_tool()

        set_wal_agent("agent_b")
        shared_tool()

        a_mems = run(mem_a.recall_recent(limit=5))
        b_mems = run(mem_b.recall_recent(limit=5))
        assert all(m.agent_name == "agent_a" for m in a_mems)
        assert all(m.agent_name == "agent_b" for m in b_mems)
