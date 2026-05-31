"""Tests for the Agent Memory system (Markdown-based per-agent memory)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agenticops.memory.agent_memory import (
    MEMORY_MARKER_END,
    MEMORY_MARKER_START,
    archive_memory,
    list_memories,
    load_agent_memory,
    parse_frontmatter,
    rebuild_prompt_with_memory,
    save_memory_file,
    search_memories,
    update_memory_index,
    _serialize_frontmatter,
)


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Create a temporary agent-memory directory and patch AGENT_MEMORY_DIR."""
    mem_dir = tmp_path / "agent-memory"
    for agent in ("detect", "rca", "sre", "executor", "reporter", "scan", "shared"):
        (mem_dir / agent).mkdir(parents=True)
        (mem_dir / agent / "MEMORY.md").write_text(f"# {agent.title()} Agent Memory\n")

    with patch("agenticops.memory.agent_memory.AGENT_MEMORY_DIR", mem_dir):
        yield mem_dir


# ── parse_frontmatter ───────────────────────────────────────────────


class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        content = "---\nagent: detect\ntype: feedback\nstatus: active\nconfidence: 4\n---\n\nCPU is normal."
        fm, body = parse_frontmatter(content)
        assert fm["agent"] == "detect"
        assert fm["type"] == "feedback"
        assert fm["confidence"] == 4
        assert body == "CPU is normal."

    def test_no_frontmatter(self):
        content = "Just a plain markdown file."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == "Just a plain markdown file."

    def test_invalid_yaml(self):
        content = "---\n: : invalid:\n---\n\nBody text."
        fm, body = parse_frontmatter(content)
        # Should not crash, returns empty dict
        assert isinstance(fm, dict)

    def test_empty_content(self):
        fm, body = parse_frontmatter("")
        assert fm == {}
        assert body == ""


# ── save_memory_file ────────────────────────────────────────────────


class TestSaveMemoryFile:
    def test_basic_save(self, tmp_memory_dir):
        filepath = save_memory_file(
            agent_name="detect",
            filename="cpu_spike_normal.md",
            body="CPU 50-70% on t3.medium is normal.",
            confidence=4,
            resource_pattern="EC2/t3.*",
        )
        assert filepath.exists()
        content = filepath.read_text()
        fm, body = parse_frontmatter(content)
        assert fm["agent"] == "detect"
        assert fm["confidence"] == 4
        assert fm["status"] == "active"
        assert fm["source"] == "user"
        assert fm["resource_pattern"] == "EC2/t3.*"
        assert "CPU 50-70%" in body

    def test_confidence_clamping(self, tmp_memory_dir):
        filepath = save_memory_file(
            agent_name="rca", filename="test.md", body="Test", confidence=10,
        )
        fm, _ = parse_frontmatter(filepath.read_text())
        assert fm["confidence"] == 5  # clamped to max

        filepath2 = save_memory_file(
            agent_name="rca", filename="test2.md", body="Test", confidence=0,
        )
        fm2, _ = parse_frontmatter(filepath2.read_text())
        assert fm2["confidence"] == 1  # clamped to min

    def test_auto_adds_md_extension(self, tmp_memory_dir):
        filepath = save_memory_file(
            agent_name="detect", filename="no_extension", body="Test",
        )
        assert filepath.name == "no_extension.md"

    def test_update_preserves_created_at(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="preserved.md", body="First version",
        )
        filepath = tmp_memory_dir / "detect" / "preserved.md"
        fm1, _ = parse_frontmatter(filepath.read_text())
        original_created = fm1["created_at"]

        save_memory_file(
            agent_name="detect", filename="preserved.md", body="Second version",
        )
        fm2, body2 = parse_frontmatter(filepath.read_text())
        assert str(fm2["created_at"]) == str(original_created)
        assert "Second version" in body2

    def test_updates_memory_index(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="test_idx.md", body="Index test body",
            confidence=5,
        )
        index = (tmp_memory_dir / "detect" / "MEMORY.md").read_text()
        assert "test_idx.md" in index
        assert "confidence: 5" in index


# ── archive_memory ──────────────────────────────────────────────────


class TestArchiveMemory:
    def test_archive_existing(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="to_archive.md", body="Will be archived",
        )
        assert archive_memory("detect", "to_archive.md") is True
        fm, _ = parse_frontmatter(
            (tmp_memory_dir / "detect" / "to_archive.md").read_text()
        )
        assert fm["status"] == "archived"

    def test_archive_nonexistent(self, tmp_memory_dir):
        assert archive_memory("detect", "nonexistent.md") is False


# ── load_agent_memory ───────────────────────────────────────────────


class TestLoadAgentMemory:
    def test_empty_returns_empty_string(self, tmp_memory_dir):
        result = load_agent_memory("detect")
        assert result == ""

    def test_loads_active_only(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="active.md", body="Active memory",
        )
        save_memory_file(
            agent_name="detect", filename="archived.md", body="Archived memory",
        )
        archive_memory("detect", "archived.md")

        result = load_agent_memory("detect")
        assert "Active memory" in result
        assert "Archived memory" not in result

    def test_includes_shared_memories(self, tmp_memory_dir):
        save_memory_file(
            agent_name="shared", filename="baseline.md", body="Shared baseline info",
        )
        save_memory_file(
            agent_name="detect", filename="detect_mem.md", body="Detect-specific",
        )
        result = load_agent_memory("detect")
        assert "Shared baseline info" in result
        assert "Detect-specific" in result

    def test_confidence_sorting(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="low.md", body="Low confidence",
            confidence=1,
        )
        save_memory_file(
            agent_name="detect", filename="high.md", body="High confidence",
            confidence=5,
        )
        save_memory_file(
            agent_name="detect", filename="mid.md", body="Mid confidence",
            confidence=3,
        )
        result = load_agent_memory("detect")
        # High should appear before mid, mid before low
        high_pos = result.index("High confidence")
        mid_pos = result.index("Mid confidence")
        low_pos = result.index("Low confidence")
        assert high_pos < mid_pos < low_pos

    def test_max_entries_cap(self, tmp_memory_dir):
        for i in range(15):
            save_memory_file(
                agent_name="detect", filename=f"mem_{i}.md",
                body=f"Memory number {i}", confidence=3,
            )
        result = load_agent_memory("detect", max_entries=5)
        # Should only have 5 entries
        assert result.count("(confidence:") == 5

    def test_contains_markers(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="marked.md", body="Test markers",
        )
        result = load_agent_memory("detect")
        assert MEMORY_MARKER_START in result
        assert MEMORY_MARKER_END in result


# ── search_memories ─────────────────────────────────────────────────


class TestSearchMemories:
    def test_keyword_search(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="cpu.md", body="CPU spike is normal",
        )
        save_memory_file(
            agent_name="detect", filename="rds.md", body="RDS connections normal",
        )
        results = search_memories("CPU")
        assert len(results) == 1
        assert results[0]["filename"] == "cpu.md"

    def test_case_insensitive(self, tmp_memory_dir):
        save_memory_file(
            agent_name="rca", filename="test.md", body="ElastiCache timeout pattern",
        )
        results = search_memories("elasticache")
        assert len(results) == 1

    def test_cross_agent_search(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="d1.md", body="Shared keyword XYZ",
        )
        save_memory_file(
            agent_name="rca", filename="r1.md", body="Also has keyword XYZ",
        )
        results = search_memories("XYZ")
        assert len(results) == 2
        agents = {r["agent"] for r in results}
        assert agents == {"detect", "rca"}

    def test_filtered_by_agent(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="d1.md", body="Find me detect",
        )
        save_memory_file(
            agent_name="rca", filename="r1.md", body="Find me rca",
        )
        results = search_memories("Find me", agent_name="detect")
        assert all(r["agent"] in ("detect", "shared") for r in results)

    def test_no_results(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="cpu.md", body="CPU info",
        )
        results = search_memories("nonexistent_query_xyz")
        assert results == []


# ── rebuild_prompt_with_memory ──────────────────────────────────────


class TestRebuildPromptWithMemory:
    def test_insert_new_memory(self):
        prompt = "Base prompt.\n\nAGENT SKILLS PROTOCOL:\nSkills here."
        memory = "[Agent Memory - learned from past feedback]\nTest memory\n[End Agent Memory]"
        result = rebuild_prompt_with_memory(prompt, memory)
        assert memory in result
        # Memory should be before Skills
        assert result.index(memory) < result.index("AGENT SKILLS PROTOCOL:")

    def test_replace_existing_memory(self):
        old_memory = f"{MEMORY_MARKER_START}\nOld memory\n{MEMORY_MARKER_END}"
        prompt = f"Base prompt.\n\n{old_memory}\n\nSkills section."
        new_memory = f"{MEMORY_MARKER_START}\nNew memory\n{MEMORY_MARKER_END}"
        result = rebuild_prompt_with_memory(prompt, new_memory)
        assert "New memory" in result
        assert "Old memory" not in result

    def test_append_when_no_skills(self):
        prompt = "Simple prompt without skills."
        memory = f"{MEMORY_MARKER_START}\nTest\n{MEMORY_MARKER_END}"
        result = rebuild_prompt_with_memory(prompt, memory)
        assert result.endswith(memory)


# ── list_memories ───────────────────────────────────────────────────


class TestListMemories:
    def test_list_all_active(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="a.md", body="Active one",
        )
        save_memory_file(
            agent_name="detect", filename="b.md", body="Active two",
        )
        save_memory_file(
            agent_name="detect", filename="c.md", body="Will archive",
        )
        archive_memory("detect", "c.md")

        results = list_memories(agent_name="detect", status_filter="active")
        assert len(results) == 2
        filenames = {r["filename"] for r in results}
        assert filenames == {"a.md", "b.md"}

    def test_list_all_statuses(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="a.md", body="Active",
        )
        save_memory_file(
            agent_name="detect", filename="b.md", body="Archived",
        )
        archive_memory("detect", "b.md")

        results = list_memories(agent_name="detect", status_filter="all")
        assert len(results) == 2


# ── update_memory_index ─────────────────────────────────────────────


class TestUpdateMemoryIndex:
    def test_index_only_active(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="active.md", body="Active entry",
            confidence=4,
        )
        save_memory_file(
            agent_name="detect", filename="archived.md", body="Archived entry",
        )
        archive_memory("detect", "archived.md")
        update_memory_index("detect")

        index = (tmp_memory_dir / "detect" / "MEMORY.md").read_text()
        assert "active.md" in index
        assert "archived.md" not in index


# ── _serialize_frontmatter ──────────────────────────────────────────


class TestSerializeFrontmatter:
    def test_roundtrip(self):
        fm = {"agent": "detect", "type": "feedback", "confidence": 5}
        body = "Test body content."
        serialized = _serialize_frontmatter(fm, body)
        parsed_fm, parsed_body = parse_frontmatter(serialized)
        assert parsed_fm["agent"] == "detect"
        assert parsed_fm["confidence"] == 5
        assert parsed_body == "Test body content."


# ── Tool functions (integration) ────────────────────────────────────


class TestMemoryTools:
    def test_record_agent_feedback(self, tmp_memory_dir):
        from agenticops.tools.memory_tools import record_agent_feedback

        # Call the underlying function (not the @tool wrapper)
        result_str = record_agent_feedback.__wrapped__(
            agent_name="detect",
            description="CPU 60% on t3.medium is normal",
            confidence=5,
            resource_pattern="EC2/t3.*",
        )
        result = json.loads(result_str)
        assert result["status"] == "saved"
        assert result["agent"] == "detect"
        assert result["confidence"] == 5

        # Verify file was created
        files = list((tmp_memory_dir / "detect").glob("*.md"))
        mem_files = [f for f in files if f.name != "MEMORY.md"]
        assert len(mem_files) == 1

    def test_record_invalid_agent(self, tmp_memory_dir):
        from agenticops.tools.memory_tools import record_agent_feedback

        result_str = record_agent_feedback.__wrapped__(
            agent_name="invalid_agent",
            description="test",
        )
        result = json.loads(result_str)
        assert "error" in result

    def test_search_agent_memory(self, tmp_memory_dir):
        from agenticops.tools.memory_tools import search_agent_memory

        save_memory_file(
            agent_name="detect", filename="cpu.md", body="CPU spike is normal",
        )
        result_str = search_agent_memory.__wrapped__(query="CPU")
        result = json.loads(result_str)
        assert len(result["matches"]) == 1

    def test_search_no_results(self, tmp_memory_dir):
        from agenticops.tools.memory_tools import search_agent_memory

        result_str = search_agent_memory.__wrapped__(query="nonexistent")
        result = json.loads(result_str)
        assert result["matches"] == []


# ── normalize_frontmatter ───────────────────────────────────────────


class TestFrontmatterNormalize:
    def test_normalize_backfills_missing_fields(self):
        from agenticops.memory.agent_memory import normalize_frontmatter
        fm = {"agent": "detect", "type": "feedback", "status": "active",
              "confidence": 4, "created_at": "2026-01-01", "last_confirmed": "2026-02-01"}
        out = normalize_frontmatter(fm)
        assert out["last_used"] == "2026-02-01"   # falls back to last_confirmed
        assert out["created_by"] == "user"
        assert out["status"] == "active"

    def test_normalize_last_used_falls_back_to_created_at(self):
        from agenticops.memory.agent_memory import normalize_frontmatter
        fm = {"agent": "detect", "confidence": 3, "created_at": "2026-01-01"}
        out = normalize_frontmatter(fm)
        assert out["last_used"] == "2026-01-01"

    def test_normalize_preserves_existing_new_fields(self):
        from agenticops.memory.agent_memory import normalize_frontmatter
        fm = {"agent": "detect", "last_used": "2026-05-01", "created_by": "agent",
              "status": "stale"}
        out = normalize_frontmatter(fm)
        assert out["last_used"] == "2026-05-01"
        assert out["created_by"] == "agent"
        assert out["status"] == "stale"


# ── Reactivate-on-use & restore ─────────────────────────────────────


class TestReactivateOnUse:
    def test_touch_last_used_reactivates_stale(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import (
            touch_last_used, parse_frontmatter, _agent_dir, _serialize_frontmatter)
        fm = {"agent": "detect", "type": "feedback", "status": "stale", "confidence": 3,
              "source": "auto", "created_by": "auto", "created_at": "2026-01-01",
              "last_confirmed": "2026-01-01", "last_used": "2026-01-01"}
        fp = _agent_dir("detect") / "s.md"
        fp.write_text(_serialize_frontmatter(fm, "body"))
        touch_last_used("detect", "s.md")
        out, _ = parse_frontmatter(fp.read_text())
        assert out["status"] == "active"          # reactivated
        assert out["last_used"] != "2026-01-01"   # touched

    def test_restore_brings_back_archived(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import restore_memory, _agent_dir, _serialize_frontmatter
        arch = _agent_dir("detect") / ".archive"
        arch.mkdir()
        fm = {"agent": "detect", "status": "archived", "confidence": 3, "created_by": "auto",
              "created_at": "2026-01-01", "last_used": "2026-01-01"}
        (arch / "a.md").write_text(_serialize_frontmatter(fm, "body"))
        assert restore_memory("detect", "a.md") is True
        assert (_agent_dir("detect") / "a.md").exists()
        assert not (arch / "a.md").exists()


# ── Atomic and Provenance ───────────────────────────────────────────


class TestAtomicAndProvenance:
    def test_save_stamps_last_used_and_created_by(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import save_memory_file, parse_frontmatter
        fp = save_memory_file(agent_name="detect", filename="x.md", body="b",
                              created_by="agent", source="agent")
        fm, _ = parse_frontmatter(fp.read_text())
        assert fm["created_by"] == "agent"
        assert "last_used" in fm
        assert fm["source"] == "agent"

    def test_atomic_write_helper_no_temp_residue(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import _atomic_write_text, _agent_dir
        target = _agent_dir("detect") / "atomic.md"
        _atomic_write_text(target, "hello")
        assert target.read_text() == "hello"
        assert list(_agent_dir("detect").glob(".*tmp*")) == []


# ── Size-cap enforcement ────────────────────────────────────────────


class TestSizeCap:
    def test_save_new_when_full_raises_memory_full(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import save_memory_file, MemoryFullError
        for i in range(3):
            save_memory_file(agent_name="detect", filename=f"m{i}.md", body=f"b{i}")
        with pytest.raises(MemoryFullError) as exc:
            save_memory_file(agent_name="detect", filename="overflow.md", body="x", max_active=3)
        assert "detect" in str(exc.value)
        assert exc.value.active_count == 3
        assert len(exc.value.current) == 3   # list of (filename, summary)

    def test_update_existing_when_full_is_allowed(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import save_memory_file
        for i in range(3):
            save_memory_file(agent_name="detect", filename=f"m{i}.md", body=f"b{i}")
        # Updating an existing file does NOT count as new → allowed even at cap
        fp = save_memory_file(agent_name="detect", filename="m0.md", body="updated", max_active=3)
        assert "updated" in fp.read_text()


# ── Merge into umbrella ─────────────────────────────────────────────


class TestMergeMemories:
    def test_merge_creates_umbrella_archives_sources(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import (
            save_memory_file, merge_memories, parse_frontmatter, _agent_dir)
        save_memory_file(agent_name="detect", filename="cpu1.md", body="CPU spike A")
        save_memory_file(agent_name="detect", filename="cpu2.md", body="CPU spike B")
        path = merge_memories(
            agent_name="detect",
            sources=["cpu1.md", "cpu2.md"],
            into="cpu_baseline.md",
            body="CPU on t3.* 50-85% <10min normal; >90% >10min alerts.",
            created_by="agent",
        )
        um_fm, _ = parse_frontmatter(path.read_text())
        assert um_fm["type"] == "umbrella"
        assert um_fm["status"] == "active"
        assert set(um_fm["absorbed_from"]) == {"cpu1.md", "cpu2.md"}
        for src in ("cpu1.md", "cpu2.md"):
            assert not (_agent_dir("detect") / src).exists()
            arch_fm, _ = parse_frontmatter((_agent_dir("detect") / ".archive" / src).read_text())
            assert arch_fm["status"] == "archived"
            assert arch_fm["absorbed_into"] == "cpu_baseline.md"
