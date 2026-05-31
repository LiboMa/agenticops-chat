"""E2E tests for Agent Memory system.

Tests the full flow: API feedback → file creation → prompt injection →
search → archive → hot-reload.  Uses FastAPI TestClient + real file I/O
(patched to a temp directory).
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.memory.agent_memory import (
    MEMORY_MARKER_END,
    MEMORY_MARKER_START,
    load_agent_memory,
    parse_frontmatter,
    rebuild_prompt_with_memory,
    save_memory_file,
    search_memories,
)
from agenticops.models import HealthIssue, get_db_session
from agenticops.web.app import app


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Create temp agent-memory directory and patch both agent_memory and app imports."""
    mem_dir = tmp_path / "agent-memory"
    for agent in ("detect", "rca", "sre", "executor", "reporter", "scan", "shared"):
        (mem_dir / agent).mkdir(parents=True)
        (mem_dir / agent / "MEMORY.md").write_text(f"# {agent.title()} Agent Memory\n")

    with patch("agenticops.memory.agent_memory.AGENT_MEMORY_DIR", mem_dir):
        yield mem_dir


@pytest.fixture
def seed_issue():
    """Create a test HealthIssue in the DB and return its ID."""
    with get_db_session() as session:
        issue = HealthIssue(
            resource_id="EC2/i-test123",
            severity="medium",
            source="cloudwatch",
            title="CPU utilization spike on t3.medium",
            description="CPU at 62% sustained for 10 minutes",
            alarm_name="test-alarm",
            metric_data={"metric": "CPUUtilization", "value": 62},
            related_changes=[],
            status="open",
        )
        session.add(issue)
        session.flush()
        issue_id = issue.id
    yield issue_id
    # Cleanup
    with get_db_session() as session:
        session.query(HealthIssue).filter_by(id=issue_id).delete()


# ── E2E Flow 1: False Positive Feedback via API ────────────────────


class TestFalsePositiveFeedbackFlow:
    """User marks issue as false positive via API → memory file created →
    detect agent prompt injection includes it → search finds it."""

    def test_full_false_positive_flow(self, client, tmp_memory_dir, seed_issue):
        issue_id = seed_issue

        # Step 1: POST feedback — mark as false positive
        resp = client.post(
            f"/api/health-issues/{issue_id}/feedback",
            json={"type": "false_positive", "note": "Normal CPU fluctuation", "confidence": 4},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "recorded"
        assert data["type"] == "false_positive"
        assert data["agent"] == "detect"
        assert data["confidence"] == 4
        memory_file = data["memory_file"]

        # Step 2: Verify file was created
        filepath = tmp_memory_dir / "detect" / memory_file
        assert filepath.exists()
        fm, body = parse_frontmatter(filepath.read_text())
        assert fm["agent"] == "detect"
        assert fm["type"] == "feedback"
        assert fm["confidence"] == 4
        assert fm["status"] == "active"
        assert fm["resource_pattern"] == "EC2/*"
        assert fm["related_issue_id"] == issue_id
        assert "false positive" in body.lower()
        assert "Normal CPU fluctuation" in body

        # Step 3: Verify MEMORY.md index was updated
        index = (tmp_memory_dir / "detect" / "MEMORY.md").read_text()
        assert memory_file in index
        assert "confidence: 4" in index

        # Step 4: Verify memory loads into agent prompt
        prompt_block = load_agent_memory("detect")
        assert MEMORY_MARKER_START in prompt_block
        assert "CPU utilization spike" in prompt_block
        assert "(confidence: 4/5)" in prompt_block

        # Step 5: Verify search finds it
        results = search_memories("CPU", agent_name="detect")
        assert len(results) >= 1
        assert any("CPU" in r["body"] for r in results)

        # Step 6: Verify issue was dismissed
        with get_db_session() as session:
            issue = session.query(HealthIssue).filter_by(id=issue_id).first()
            assert issue.status == "resolved"

    def test_false_positive_default_confidence(self, client, tmp_memory_dir, seed_issue):
        """Confidence defaults to 3 when not provided."""
        resp = client.post(
            f"/api/health-issues/{seed_issue}/feedback",
            json={"type": "false_positive"},
        )
        assert resp.status_code == 201
        assert resp.json()["confidence"] == 3

    def test_feedback_nonexistent_issue(self, client, tmp_memory_dir):
        resp = client.post(
            "/api/health-issues/99999/feedback",
            json={"type": "false_positive"},
        )
        assert resp.status_code == 404


# ── E2E Flow 2: Confirmed Feedback → Archive Memory ────────────────


class TestConfirmedFeedbackFlow:
    """User confirms an issue → any suppressing memories get archived."""

    def test_confirmed_archives_matching_memory(self, client, tmp_memory_dir, seed_issue):
        issue_id = seed_issue

        # Step 1: Create a false positive memory first
        save_memory_file(
            agent_name="detect",
            filename="cpu_spike_fp.md",
            body="CPU utilization spike on t3.medium is normal",
            confidence=4,
            resource_pattern="EC2/t3.*",
            related_issue_id=issue_id,
        )

        # Verify it loads
        assert "CPU utilization spike" in load_agent_memory("detect")

        # Step 2: Now confirm the issue — should archive the memory
        resp = client.post(
            f"/api/health-issues/{issue_id}/feedback",
            json={"type": "confirmed"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "confirmed"
        assert data["archived_memories"] >= 1

        # Step 3: Memory should no longer load
        prompt_block = load_agent_memory("detect")
        assert "CPU utilization spike on t3.medium is normal" not in prompt_block

        # Step 4: Memory file status should be archived
        fm, _ = parse_frontmatter(
            (tmp_memory_dir / "detect" / "cpu_spike_fp.md").read_text()
        )
        assert fm["status"] == "archived"


# ── E2E Flow 3: Agent Memory CRUD API ──────────────────────────────


class TestAgentMemoryCRUDAPI:
    """GET/PUT/DELETE /api/agent-memory endpoints."""

    def test_list_empty(self, client, tmp_memory_dir):
        resp = client.get("/api/agent-memory?agent=detect&status=active")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_create(self, client, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="test_list.md", body="List test body",
            confidence=5,
        )
        resp = client.get("/api/agent-memory?agent=detect")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["filename"] == "test_list.md"
        assert data[0]["confidence"] == 5
        assert data[0]["status"] == "active"

    def test_list_all_agents(self, client, tmp_memory_dir):
        save_memory_file(agent_name="detect", filename="d.md", body="Detect")
        save_memory_file(agent_name="rca", filename="r.md", body="RCA")
        resp = client.get("/api/agent-memory")
        assert resp.status_code == 200
        data = resp.json()
        agents = {m["agent"] for m in data}
        assert "detect" in agents
        assert "rca" in agents

    def test_list_invalid_agent(self, client, tmp_memory_dir):
        resp = client.get("/api/agent-memory?agent=invalid")
        assert resp.status_code == 400

    def test_get_single_memory(self, client, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="get_test.md",
            body="Get test body", confidence=4,
        )
        resp = client.get("/api/agent-memory/detect/get_test.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"] == "detect"
        assert data["frontmatter"]["confidence"] == 4
        assert "Get test body" in data["body"]

    def test_get_nonexistent(self, client, tmp_memory_dir):
        resp = client.get("/api/agent-memory/detect/nonexistent.md")
        assert resp.status_code == 404

    def test_update_confidence(self, client, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="update_test.md",
            body="Update test", confidence=3,
        )
        resp = client.put(
            "/api/agent-memory/detect/update_test.md",
            json={"confidence": 5},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

        # Verify file updated
        fm, _ = parse_frontmatter(
            (tmp_memory_dir / "detect" / "update_test.md").read_text()
        )
        assert fm["confidence"] == 5

    def test_update_status_to_archived(self, client, tmp_memory_dir):
        save_memory_file(
            agent_name="rca", filename="archive_via_api.md", body="Will archive",
        )
        resp = client.put(
            "/api/agent-memory/rca/archive_via_api.md",
            json={"status": "archived"},
        )
        assert resp.status_code == 200
        fm, _ = parse_frontmatter(
            (tmp_memory_dir / "rca" / "archive_via_api.md").read_text()
        )
        assert fm["status"] == "archived"

    def test_update_body(self, client, tmp_memory_dir):
        save_memory_file(
            agent_name="sre", filename="body_update.md", body="Original body",
        )
        resp = client.put(
            "/api/agent-memory/sre/body_update.md",
            json={"body": "Updated body content"},
        )
        assert resp.status_code == 200
        _, body = parse_frontmatter(
            (tmp_memory_dir / "sre" / "body_update.md").read_text()
        )
        assert body == "Updated body content"

    def test_delete_archives_memory(self, client, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="to_delete.md", body="Delete me",
        )
        resp = client.delete("/api/agent-memory/detect/to_delete.md")
        assert resp.status_code == 204

        # File still exists but status is archived
        fm, _ = parse_frontmatter(
            (tmp_memory_dir / "detect" / "to_delete.md").read_text()
        )
        assert fm["status"] == "archived"

    def test_delete_nonexistent(self, client, tmp_memory_dir):
        resp = client.delete("/api/agent-memory/detect/nonexistent.md")
        assert resp.status_code == 404


# ── E2E Flow 4: Prompt Injection & Confidence Priority ─────────────


class TestPromptInjectionE2E:
    """Memories are injected into system prompt sorted by confidence."""

    def test_confidence_priority_in_prompt(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="low.md", body="Low priority item",
            confidence=1,
        )
        save_memory_file(
            agent_name="detect", filename="high.md", body="High priority item",
            confidence=5,
        )
        save_memory_file(
            agent_name="detect", filename="mid.md", body="Mid priority item",
            confidence=3,
        )
        prompt = load_agent_memory("detect")
        high_pos = prompt.index("High priority item")
        mid_pos = prompt.index("Mid priority item")
        low_pos = prompt.index("Low priority item")
        assert high_pos < mid_pos < low_pos

    def test_shared_memories_included(self, tmp_memory_dir):
        save_memory_file(
            agent_name="shared", filename="baseline.md",
            body="Infrastructure baseline: us-east-1 primary",
            confidence=5,
        )
        prompt = load_agent_memory("rca")
        assert "Infrastructure baseline" in prompt

    def test_hot_reload_replaces_memory_block(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="v1.md", body="Version 1 memory",
        )
        prompt_v1 = load_agent_memory("detect")
        full_prompt = f"Base system prompt.\n\n{prompt_v1}\n\nSkills section."

        # Simulate adding a new high-confidence memory
        save_memory_file(
            agent_name="detect", filename="v2.md", body="Version 2 critical memory",
            confidence=5,
        )
        prompt_v2 = load_agent_memory("detect")
        updated = rebuild_prompt_with_memory(full_prompt, prompt_v2)

        assert "Version 2 critical memory" in updated
        assert "Version 1 memory" in updated  # Both should be there
        # Should only have ONE memory block (not duplicated)
        assert updated.count(MEMORY_MARKER_START) == 1
        assert updated.count(MEMORY_MARKER_END) == 1

    def test_max_entries_respects_cap(self, tmp_memory_dir):
        # max_active=25 lets all 20 writes through (we're testing the LOAD-side
        # injection cap here, not the cycle② write-side size-cap which defaults to 15).
        for i in range(20):
            save_memory_file(
                agent_name="detect", filename=f"mem_{i:02d}.md",
                body=f"Memory number {i}", confidence=3, max_active=25,
            )
        prompt = load_agent_memory("detect", max_entries=5)
        assert prompt.count("(confidence:") == 5


# ── E2E Flow 5: Cross-Agent Search ─────────────────────────────────


class TestCrossAgentSearchE2E:
    """search_agent_memory tool searches across agents."""

    def test_cross_agent_keyword_search(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="cpu_d.md",
            body="CPU spike false positive on t3.medium",
        )
        save_memory_file(
            agent_name="rca", filename="cpu_r.md",
            body="CPU issue usually caused by background jobs",
        )
        save_memory_file(
            agent_name="sre", filename="disk.md",
            body="Disk usage on m5.large normal at 70%",
        )

        # Search for CPU — should find 2
        results = search_memories("CPU")
        assert len(results) == 2
        agents = {r["agent"] for r in results}
        assert agents == {"detect", "rca"}

        # Search for disk — should find 1
        results = search_memories("Disk")
        assert len(results) == 1
        assert results[0]["agent"] == "sre"

    def test_search_via_api_tool(self, client, tmp_memory_dir):
        """Verify the search_agent_memory @tool function works end-to-end."""
        from agenticops.tools.memory_tools import search_agent_memory

        save_memory_file(
            agent_name="detect", filename="api_search.md",
            body="RDS connection pool exhaustion pattern",
            confidence=5,
        )

        result_str = search_agent_memory.__wrapped__(query="RDS connection")
        result = json.loads(result_str)
        assert len(result["matches"]) >= 1
        assert "RDS connection" in result["matches"][0]["body"]


# ── E2E Flow 6: Multi-Agent Memory Isolation ───────────────────────


class TestAgentIsolation:
    """Each agent only sees its own memories + shared."""

    def test_detect_does_not_see_rca_memories(self, tmp_memory_dir):
        save_memory_file(
            agent_name="detect", filename="detect_only.md",
            body="Detect-specific knowledge",
        )
        save_memory_file(
            agent_name="rca", filename="rca_only.md",
            body="RCA-specific knowledge",
        )

        detect_prompt = load_agent_memory("detect")
        assert "Detect-specific knowledge" in detect_prompt
        assert "RCA-specific knowledge" not in detect_prompt

        rca_prompt = load_agent_memory("rca")
        assert "RCA-specific knowledge" in rca_prompt
        assert "Detect-specific knowledge" not in rca_prompt

    def test_shared_visible_to_all(self, tmp_memory_dir):
        save_memory_file(
            agent_name="shared", filename="global.md",
            body="Global operational baseline",
            confidence=5,
        )
        for agent in ("detect", "rca", "sre", "executor", "reporter", "scan"):
            prompt = load_agent_memory(agent)
            assert "Global operational baseline" in prompt, f"{agent} should see shared memory"


# ── E2E Flow 7: Record Feedback Tool → Memory → Injection ──────────


class TestRecordFeedbackToolE2E:
    """record_agent_feedback @tool → file creation → prompt injection."""

    def test_chat_feedback_to_prompt_injection(self, tmp_memory_dir):
        from agenticops.tools.memory_tools import record_agent_feedback

        # Simulate user giving feedback in chat
        result_str = record_agent_feedback.__wrapped__(
            agent_name="detect",
            description="ElastiCache connection count under 500 is normal for our workload",
            confidence=5,
            resource_pattern="ElastiCache/*",
            memory_type="baseline",
        )
        result = json.loads(result_str)
        assert result["status"] == "saved"
        assert result["confidence"] == 5

        # Verify it's in the prompt
        prompt = load_agent_memory("detect")
        assert "ElastiCache connection count" in prompt
        assert "(confidence: 5/5)" in prompt

        # Verify it's searchable
        results = search_memories("ElastiCache")
        assert len(results) == 1
        assert results[0]["type"] == "baseline"
        assert results[0]["resource_pattern"] == "ElastiCache/*"

    def test_multiple_feedbacks_accumulate(self, tmp_memory_dir):
        from agenticops.tools.memory_tools import record_agent_feedback

        record_agent_feedback.__wrapped__(
            agent_name="detect",
            description="CPU 60% on t3 is normal",
            confidence=4,
        )
        record_agent_feedback.__wrapped__(
            agent_name="detect",
            description="RDS connections under 80% is normal",
            confidence=3,
        )
        record_agent_feedback.__wrapped__(
            agent_name="rca",
            description="EC2 timeout usually means security group issue",
            confidence=5,
        )

        detect_prompt = load_agent_memory("detect")
        assert "CPU 60%" in detect_prompt
        assert "RDS connections" in detect_prompt
        # RCA memory should not leak to detect
        assert "security group issue" not in detect_prompt

        rca_prompt = load_agent_memory("rca")
        assert "security group issue" in rca_prompt


# ── E2E Flow 8: Auto-Learning from Dismissed Issues ──────────────


class TestAutoLearnDismissed:
    """When a user dismisses an issue via status update, auto-create detect memory."""

    def test_dismiss_creates_auto_memory(self, client, tmp_memory_dir, seed_issue):
        issue_id = seed_issue

        # Dismiss the issue
        resp = client.put(
            f"/api/anomalies/{issue_id}/status",
            json={"status": "dismissed"},
        )
        assert resp.status_code == 200

        # Verify auto-memory was created for detect agent
        mem_files = [
            f for f in (tmp_memory_dir / "detect").glob("auto_*.md")
            if f.name != "MEMORY.md"
        ]
        assert len(mem_files) >= 1

        # Check the memory content
        content = mem_files[0].read_text()
        fm, body = parse_frontmatter(content)
        assert fm["source"] == "auto"
        assert fm["confidence"] == 2  # auto-learned = low confidence
        assert fm["agent"] == "detect"
        assert "dismissed" in body.lower()
        assert f"I#{issue_id}" in body

    def test_auto_memory_searchable(self, client, tmp_memory_dir, seed_issue):
        issue_id = seed_issue

        client.put(
            f"/api/anomalies/{issue_id}/status",
            json={"status": "dismissed"},
        )

        # Search should find the auto-created memory
        results = search_memories("CPU utilization")
        assert len(results) >= 1
        assert any(r["type"] == "feedback" for r in results)

    def test_auto_memory_in_detect_prompt(self, client, tmp_memory_dir, seed_issue):
        issue_id = seed_issue

        client.put(
            f"/api/anomalies/{issue_id}/status",
            json={"status": "dismissed"},
        )

        prompt = load_agent_memory("detect")
        assert "dismissed" in prompt.lower()
        assert "(confidence: 2/5)" in prompt  # auto confidence

    def test_non_dismiss_status_no_memory(self, client, tmp_memory_dir, seed_issue):
        issue_id = seed_issue

        # Move to investigating — should NOT create memory
        client.put(
            f"/api/anomalies/{issue_id}/status",
            json={"status": "investigating"},
        )

        mem_files = [
            f for f in (tmp_memory_dir / "detect").glob("auto_*.md")
            if f.name != "MEMORY.md"
        ]
        assert len(mem_files) == 0
