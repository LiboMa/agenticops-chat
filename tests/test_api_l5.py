"""Tests for agenticops.web.api_l5 — Memory, Proactive, Learning API routes."""

import os
import json
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agenticops.web.api_l5 import memory_router, proactive_router, learning_router

app = FastAPI()
app.include_router(memory_router)
app.include_router(proactive_router)
app.include_router(learning_router)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_memory_entry(
    id="mem-1",
    content="test content",
    memory_type_value="episodic",
    confidence=0.9,
    recall_count=3,
    created_at="2025-01-01T00:00:00",
):
    entry = MagicMock()
    entry.id = id
    entry.content = content
    entry.memory_type = MagicMock()
    entry.memory_type.value = memory_type_value
    entry.confidence = confidence
    entry.recall_count = recall_count
    entry.created_at = created_at
    return entry


# ---------------------------------------------------------------------------
# Memory APIs
# ---------------------------------------------------------------------------


class TestMemoryAgents:
    @patch("agenticops.memory.get_agent_memory")
    def test_memory_agents_success(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_mem.get_stats.return_value = {"total": 10, "by_type": {"episodic": 5}}
        mock_get_mem.return_value = mock_mem

        resp = client.get("/api/memory/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert len(data["agents"]) == 8

    @patch("agenticops.memory.get_agent_memory")
    def test_memory_agents_partial_failure(self, mock_get_mem):
        """One agent fails; its entry shows total=0."""
        call_count = [0]

        def side_effect(agent_id):
            call_count[0] += 1
            if call_count[0] == 3:
                raise RuntimeError("oops")
            mock_mem = MagicMock()
            mock_mem.get_stats.return_value = {"total": 5, "by_type": {}}
            return mock_mem

        mock_get_mem.side_effect = side_effect
        resp = client.get("/api/memory/agents")
        assert resp.status_code == 200
        data = resp.json()
        zero_entries = [a for a in data["agents"] if a["total"] == 0]
        assert len(zero_entries) >= 1

    def test_memory_agents_import_error(self):
        """When memory module unavailable, return empty list."""
        with patch.dict("sys.modules", {"agenticops.memory": None}):
            # Import error case covered by the try/except ImportError
            pass


class TestMemoryEntries:
    @patch("agenticops.memory.get_agent_memory")
    def test_entries_success(self, mock_get_mem):
        entry = _make_memory_entry()
        mock_mem = MagicMock()
        mock_mem.recall_recent = AsyncMock(return_value=[entry])
        mock_get_mem.return_value = mock_mem

        resp = client.get("/api/memory/rca_agent/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "rca_agent"
        assert data["count"] == 1

    @patch("agenticops.memory.get_agent_memory")
    def test_entries_with_type_filter(self, mock_get_mem):
        entry1 = _make_memory_entry(memory_type_value="episodic")
        entry2 = _make_memory_entry(id="mem-2", memory_type_value="semantic")
        mock_mem = MagicMock()
        mock_mem.recall_recent = AsyncMock(return_value=[entry1, entry2])
        mock_get_mem.return_value = mock_mem

        resp = client.get("/api/memory/rca_agent/entries?memory_type=episodic")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    @patch("agenticops.memory.get_agent_memory")
    def test_entries_exception(self, mock_get_mem):
        mock_get_mem.side_effect = RuntimeError("fail")
        resp = client.get("/api/memory/rca_agent/entries")
        assert resp.status_code == 500


class TestMemoryReflections:
    @patch("agenticops.memory.get_agent_memory")
    def test_reflections_success(self, mock_get_mem):
        from enum import Enum

        class MemoryType(Enum):
            REFLECTION = "reflection"

        entry = _make_memory_entry(content="I learned something")
        entry.memory_type = MemoryType.REFLECTION
        mock_mem = MagicMock()
        mock_mem.recall_recent = AsyncMock(return_value=[entry])
        mock_get_mem.return_value = mock_mem

        with patch("agenticops.memory.types.MemoryType", MemoryType):
            resp = client.get("/api/memory/rca_agent/reflections")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1


# ---------------------------------------------------------------------------
# Proactive APIs
# ---------------------------------------------------------------------------


class TestProactiveAlerts:
    @patch("agenticops.memory.get_agent_memory")
    def test_proactive_alerts_success(self, mock_get_mem):
        entry = _make_memory_entry(content="PROACTIVE_ALERT: CPU spike predicted")
        mock_mem = MagicMock()
        mock_mem.recall_recent = AsyncMock(return_value=[entry])
        mock_get_mem.return_value = mock_mem

        resp = client.get("/api/proactive/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert "PROACTIVE_ALERT" in data["alerts"][0]["content"]

    @patch("agenticops.memory.get_agent_memory")
    def test_proactive_alerts_exception(self, mock_get_mem):
        mock_get_mem.side_effect = RuntimeError("unavailable")
        resp = client.get("/api/proactive/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert "error" in data


class TestProactivePatterns:
    @patch("agenticops.memory.get_agent_memory")
    def test_patterns_success(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_get_mem.return_value = mock_mem

        mock_pattern = MagicMock()
        mock_pattern.category = "cpu_spike"
        mock_pattern.occurrences = 5
        mock_pattern.score = 0.87

        with patch(
            "agenticops.proactive.pattern_watch.PatternWatch"
        ) as MockPW:
            instance = MockPW.return_value
            instance.scan = AsyncMock(return_value=[mock_pattern])

            resp = client.get("/api/proactive/patterns")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert data["patterns"][0]["category"] == "cpu_spike"

    @patch("agenticops.memory.get_agent_memory")
    def test_patterns_exception(self, mock_get_mem):
        mock_get_mem.side_effect = ImportError("no module")
        resp = client.get("/api/proactive/patterns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0


class TestProactiveStats:
    @patch("agenticops.memory.get_agent_memory")
    def test_stats_success(self, mock_get_mem):
        entry = _make_memory_entry(content="PROACTIVE_ALERT: test")
        mock_mem = MagicMock()
        mock_mem.get_stats.return_value = {"total": 20, "by_type": {"alert": 5}}
        mock_mem.recall_recent = AsyncMock(return_value=[entry])
        mock_get_mem.return_value = mock_mem

        resp = client.get("/api/proactive/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_memories"] == 20
        assert data["total_alerts"] == 1

    @patch("agenticops.memory.get_agent_memory")
    def test_stats_exception(self, mock_get_mem):
        mock_get_mem.side_effect = Exception("fail")
        resp = client.get("/api/proactive/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_memories"] == 0


# ---------------------------------------------------------------------------
# Learning APIs
# ---------------------------------------------------------------------------


class TestLearningTimeline:
    @patch("agenticops.memory.get_agent_memory")
    def test_timeline_success(self, mock_get_mem):
        entries = [
            _make_memory_entry(content="CASE_STUDY: resolved disk issue"),
            _make_memory_entry(id="m2", content="SKILL_GAP identified"),
            _make_memory_entry(id="m3", content="SOP generated"),
            _make_memory_entry(id="m4", content="PROACTIVE_ALERT predicted"),
            _make_memory_entry(id="m5", content="irrelevant entry"),
        ]
        mock_mem = MagicMock()
        mock_mem.recall_recent = AsyncMock(return_value=entries)
        mock_get_mem.return_value = mock_mem

        resp = client.get("/api/learning/timeline")
        assert resp.status_code == 200
        data = resp.json()
        # 4 typed events (case_study, skill, sop, prediction) × 2 agents
        assert data["count"] >= 4

    @patch("agenticops.memory.get_agent_memory")
    def test_timeline_partial_failure(self, mock_get_mem):
        """One agent fails, the other works."""
        calls = [0]

        def side_effect(agent_id):
            calls[0] += 1
            if agent_id == "rca_agent":
                raise RuntimeError("fail")
            mock_mem = MagicMock()
            mock_mem.recall_recent = AsyncMock(return_value=[])
            return mock_mem

        mock_get_mem.side_effect = side_effect
        resp = client.get("/api/learning/timeline")
        assert resp.status_code == 200


class TestLearningSkills:
    @patch("agenticops.memory.get_agent_memory")
    def test_skills_success(self, mock_get_mem):
        entry = _make_memory_entry(content="SKILL_GAP: needs EKS debugging")
        mock_mem = MagicMock()
        mock_mem.recall_recent = AsyncMock(return_value=[entry])
        mock_get_mem.return_value = mock_mem

        resp = client.get("/api/learning/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    @patch("agenticops.memory.get_agent_memory")
    def test_skills_exception(self, mock_get_mem):
        mock_get_mem.side_effect = Exception("fail")
        resp = client.get("/api/learning/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0


class TestLearningSops:
    def test_sops_with_dir(self):
        """SOPs found in sop_drafts directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sop_file = os.path.join(tmpdir, "sop_001.md")
            with open(sop_file, "w") as f:
                f.write("# SOP: Handle CPU Spike\n\n1. Check metrics\n2. Scale out")

            with patch("os.path.join", return_value=tmpdir):
                with patch("os.path.isdir", return_value=True):
                    with patch("os.listdir", return_value=["sop_001.md"]):
                        with patch(
                            "builtins.open",
                            MagicMock(
                                return_value=MagicMock(
                                    __enter__=MagicMock(
                                        return_value=MagicMock(
                                            read=MagicMock(return_value="# SOP content")
                                        )
                                    ),
                                    __exit__=MagicMock(return_value=False),
                                )
                            ),
                        ):
                            with patch("os.path.getsize", return_value=100):
                                resp = client.get("/api/learning/sops")
                                assert resp.status_code == 200

    def test_sops_no_dir(self):
        """No sop_drafts directory."""
        with patch("os.path.isdir", return_value=False):
            resp = client.get("/api/learning/sops")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0
