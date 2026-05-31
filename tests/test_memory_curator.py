"""Tests for the Hermes-style memory Curator lifecycle."""
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_memory_dir(tmp_path):
    mem_dir = tmp_path / "agent-memory"
    for agent in ("detect", "rca", "sre", "executor", "reporter", "scan", "shared"):
        (mem_dir / agent).mkdir(parents=True)
    with patch("agenticops.memory.agent_memory.AGENT_MEMORY_DIR", mem_dir):
        yield mem_dir


def _write(mem_dir, agent, name, last_used, status="active", created_by="user"):
    from agenticops.memory.agent_memory import _serialize_frontmatter
    fm = {"agent": agent, "type": "feedback", "status": status, "confidence": 3,
          "source": "auto", "created_by": created_by, "created_at": "2026-01-01",
          "last_confirmed": str(last_used), "last_used": str(last_used)}
    (mem_dir / agent / f"{name}.md").write_text(_serialize_frontmatter(fm, f"body {name}"))


def test_active_to_stale_after_threshold(tmp_memory_dir):
    from agenticops.memory.curator import run_curator
    from agenticops.memory.agent_memory import parse_frontmatter
    today = date(2026, 6, 1)
    _write(tmp_memory_dir, "detect", "old", today - timedelta(days=40))   # >30 -> stale
    _write(tmp_memory_dir, "detect", "fresh", today - timedelta(days=5))  # active
    run_curator(stale_days=30, archive_days=60, today=today)
    old_fm, _ = parse_frontmatter((tmp_memory_dir / "detect" / "old.md").read_text())
    fresh_fm, _ = parse_frontmatter((tmp_memory_dir / "detect" / "fresh.md").read_text())
    assert old_fm["status"] == "stale"
    assert fresh_fm["status"] == "active"


def test_stale_to_archived_moves_to_archive_dir(tmp_memory_dir):
    from agenticops.memory.curator import run_curator
    today = date(2026, 6, 1)
    # stale + last_used 100 days ago (>30+60) -> archived.
    # Must be non-user (auto) — user-created memories are pinned/exempt.
    _write(tmp_memory_dir, "detect", "ancient", today - timedelta(days=100),
           status="stale", created_by="auto")
    run_curator(stale_days=30, archive_days=60, today=today)
    assert not (tmp_memory_dir / "detect" / "ancient.md").exists()
    assert (tmp_memory_dir / "detect" / ".archive" / "ancient.md").exists()


def test_user_created_memory_not_auto_archived(tmp_memory_dir):
    from agenticops.memory.curator import run_curator
    from agenticops.memory.agent_memory import parse_frontmatter
    today = date(2026, 6, 1)
    _write(tmp_memory_dir, "detect", "pinned", today - timedelta(days=200),
           status="active", created_by="user")
    run_curator(stale_days=30, archive_days=60, today=today)
    # user-created (pinned) memories are exempt from auto-archival; may go stale but never archived
    assert (tmp_memory_dir / "detect" / "pinned.md").exists()
    fm, _ = parse_frontmatter((tmp_memory_dir / "detect" / "pinned.md").read_text())
    assert fm["status"] in ("active", "stale")  # never archived


def test_maybe_run_curator_respects_disabled(monkeypatch, tmp_memory_dir):
    from agenticops.memory import curator
    calls = {"n": 0}
    monkeypatch.setattr(curator, "run_curator", lambda **kw: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr("agenticops.config.settings.memory_curator_enabled", False, raising=False)
    curator.maybe_run_curator()
    assert calls["n"] == 0
    monkeypatch.setattr("agenticops.config.settings.memory_curator_enabled", True, raising=False)
    curator.maybe_run_curator()
    assert calls["n"] == 1
