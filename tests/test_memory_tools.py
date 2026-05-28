"""Tests for agenticops.tools.memory_tools — coverage for remember_this and recall_memories."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticops.tools.memory_tools import (
    _current_agent,
    recall_memories,
    remember_this,
    set_current_agent,
)


class TestSetCurrentAgent:
    def test_sets_context_var(self):
        set_current_agent("test_agent_1")
        assert _current_agent.get() == "test_agent_1"

    def test_default_value(self):
        # Reset by creating a new context (check default)
        import contextvars
        ctx = contextvars.copy_context()
        # default is 'default_agent'
        assert _current_agent.get() in ("test_agent_1", "default_agent")


class TestRememberThis:
    @patch("agenticops.tools.memory_tools.asyncio")
    @patch("agenticops.memory.get_agent_memory")
    def test_remember_episodic(self, mock_get_memory, mock_asyncio):
        set_current_agent("sre_agent")

        fake_entry = MagicMock()
        fake_entry.id = "mem-123"

        mock_memory = MagicMock()
        mock_get_memory.return_value = mock_memory

        # Simulate RuntimeError path (no running loop)
        mock_asyncio.get_event_loop.side_effect = RuntimeError("no loop")
        mock_asyncio.run = MagicMock(return_value=fake_entry)

        result = remember_this._tool_func(
            content="EKS pods crash when memory exceeds 512Mi",
            memory_type="episodic",
            source="rca:issue-42",
        )

        assert "Remembered (episodic)" in result
        assert "EKS pods crash" in result
        assert "mem-123" in result

    @patch("agenticops.tools.memory_tools.asyncio")
    @patch("agenticops.memory.get_agent_memory")
    def test_remember_invalid_type_defaults_episodic(self, mock_get_memory, mock_asyncio):
        set_current_agent("sre_agent")

        fake_entry = MagicMock()
        fake_entry.id = "mem-456"

        mock_memory = MagicMock()
        mock_get_memory.return_value = mock_memory

        mock_asyncio.get_event_loop.side_effect = RuntimeError("no loop")
        mock_asyncio.run = MagicMock(return_value=fake_entry)

        result = remember_this._tool_func(
            content="some content",
            memory_type="invalid_type",
            source="",
        )

        assert "episodic" in result

    @patch("agenticops.tools.memory_tools.asyncio")
    @patch("agenticops.memory.get_agent_memory")
    def test_remember_running_loop_path(self, mock_get_memory, mock_asyncio):
        set_current_agent("sre_agent")

        fake_entry = MagicMock()
        fake_entry.id = "mem-789"

        mock_memory = MagicMock()
        mock_get_memory.return_value = mock_memory

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        mock_asyncio.get_event_loop.return_value = fake_loop
        mock_asyncio.run = MagicMock(return_value=fake_entry)

        result = remember_this._tool_func(
            content="fix: increase memory limit",
            memory_type="procedural",
            source="fix:pr-100",
        )

        assert "Remembered (procedural)" in result
        assert "mem-789" in result

    @patch("agenticops.tools.memory_tools.asyncio")
    @patch("agenticops.memory.get_agent_memory")
    def test_remember_non_running_loop_path(self, mock_get_memory, mock_asyncio):
        set_current_agent("sre_agent")

        fake_entry = MagicMock()
        fake_entry.id = "mem-abc"

        mock_memory = MagicMock()
        mock_get_memory.return_value = mock_memory

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = False
        fake_loop.run_until_complete.return_value = fake_entry
        mock_asyncio.get_event_loop.return_value = fake_loop

        result = remember_this._tool_func(
            content="semantic knowledge about VPC networking",
            memory_type="semantic",
            source="",
        )

        assert "Remembered (semantic)" in result
        assert "mem-abc" in result
        fake_loop.run_until_complete.assert_called_once()


class TestRecallMemories:
    @patch("agenticops.tools.memory_tools.asyncio")
    @patch("agenticops.memory.get_agent_memory")
    def test_recall_no_results(self, mock_get_memory, mock_asyncio):
        set_current_agent("sre_agent")

        mock_memory = MagicMock()
        mock_get_memory.return_value = mock_memory

        mock_asyncio.get_event_loop.side_effect = RuntimeError("no loop")
        mock_asyncio.run = MagicMock(return_value=[])

        result = recall_memories._tool_func(query="nonexistent topic", top_k=5)
        assert "No relevant memories found" in result

    @patch("agenticops.tools.memory_tools.asyncio")
    @patch("agenticops.memory.get_agent_memory")
    def test_recall_with_results(self, mock_get_memory, mock_asyncio):
        set_current_agent("sre_agent")

        from agenticops.memory.types import MemoryType

        entry1 = MagicMock()
        entry1.memory_type = MemoryType.EPISODIC
        entry1.content = "EKS pod OOM crash resolved by increasing limits"
        entry1.confidence = 0.92
        entry1.recall_count = 3
        entry1.source = "rca:issue-42"

        entry2 = MagicMock()
        entry2.memory_type = MemoryType.PROCEDURAL
        entry2.content = "Use kubectl top to check memory usage"
        entry2.confidence = 0.85
        entry2.recall_count = 1
        entry2.source = ""

        mock_memory = MagicMock()
        mock_get_memory.return_value = mock_memory

        mock_asyncio.get_event_loop.side_effect = RuntimeError("no loop")
        mock_asyncio.run = MagicMock(return_value=[entry1, entry2])

        result = recall_memories._tool_func(query="EKS pod OOM", top_k=5)

        assert "Found 2 relevant memories" in result
        assert "episodic" in result
        assert "procedural" in result
        assert "0.92" in result
        assert "Source: rca:issue-42" in result
        # entry2 has no source, should not have "Source:" for it
        lines = result.split("\n")
        assert any("kubectl top" in l for l in lines)

    @patch("agenticops.tools.memory_tools.asyncio")
    @patch("agenticops.memory.get_agent_memory")
    def test_recall_running_loop_path(self, mock_get_memory, mock_asyncio):
        set_current_agent("sre_agent")

        mock_memory = MagicMock()
        mock_get_memory.return_value = mock_memory

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        mock_asyncio.get_event_loop.return_value = fake_loop
        mock_asyncio.run = MagicMock(return_value=[])

        result = recall_memories._tool_func(query="test query", top_k=3)
        assert "No relevant memories found" in result

    @patch("agenticops.tools.memory_tools.asyncio")
    @patch("agenticops.memory.get_agent_memory")
    def test_recall_non_running_loop(self, mock_get_memory, mock_asyncio):
        set_current_agent("sre_agent")

        mock_memory = MagicMock()
        mock_get_memory.return_value = mock_memory

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = False
        fake_loop.run_until_complete.return_value = []
        mock_asyncio.get_event_loop.return_value = fake_loop

        result = recall_memories._tool_func(query="test", top_k=2)
        assert "No relevant memories found" in result
        fake_loop.run_until_complete.assert_called_once()
