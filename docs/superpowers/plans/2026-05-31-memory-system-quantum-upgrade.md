# ② Memory System Quantum Upgrade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the write-once-read-forever file-based agent memory into a Hermes-style self-optimizing system (size-cap merge + stale→archive Curator + agent-autonomous `memory_manage` + frozen-snapshot injection), and freeze the dead DB cross-session memory path.

**Architecture:** All changes are additive to `src/agenticops/memory/agent_memory.py` (the single core) + a new `memory/curator.py` + an enhanced `tools/memory_tools.py`. Frontmatter schema gains `last_used`/`created_by`/`status:stale`/`absorbed_into`/`absorbed_from` with backward-compatible defaults. The DB layer (`web/memory_service.py` + `AgentMemory`/`AgentMemoryFact`) is frozen, not deleted. New config in `settings.yaml`. Each task is TDD with a regression test.

**Tech Stack:** Python 3.12, pytest, YAML frontmatter markdown, pydantic-settings (`config.py`/`settings.yaml`), Strands `@tool`. Spec: `docs/superpowers/specs/2026-05-31-memory-system-quantum-upgrade-design.md`.

**Conventions:**
- venv: `.venv/bin/python` for all python/pytest.
- Single test: `.venv/bin/python -m pytest tests/<file>::<Class>::<test> -v`
- Compile gate: `.venv/bin/python -m py_compile src/agenticops/<file>.py`
- Commits use `git commit --no-verify` (project standing rule; bypass message is expected).
- Branch: `cycle2-memory-quantum` (already created, spec committed). Do NOT switch branches.
- `agent_memory.py` baseline functions (already exist): `parse_frontmatter`, `_serialize_frontmatter`, `_agent_dir`, `_load_memories_from_dir`, `load_agent_memory(agent_name, max_entries=10)`, `save_memory_file(...)`, `archive_memory(agent_name, filename)`, `update_memory_index(agent_name)`, `search_memories(query, agent_name)`, `rebuild_prompt_with_memory`, `list_memories(agent_name, status_filter)`. Constants: `AGENT_MEMORY_DIR`, `AGENT_NAMES`, `DEFAULT_CONFIDENCE=3`, `MEMORY_MARKER_START/END`.
- Test fixture (already exists in `tests/test_agent_memory.py`): `tmp_memory_dir` patches `AGENT_MEMORY_DIR` to a tmp dir with all 7 agent subdirs.
- IMPORTANT: `date.today()` is used throughout — tests that need deterministic dates patch `agenticops.memory.agent_memory.date`.

---

## Phase P0 — Config + frontmatter schema + atomic writes (foundation)

### Task 1: Add memory config settings

**Files:**
- Modify: `src/agenticops/config.py` (add fields near the `skills_*` block, after line ~381)
- Modify: `config/settings.yaml` (append memory keys)
- Test: `tests/test_config.py` (if absent, create a minimal one)

- [ ] **Step 1: Write the failing test**

Create/append `tests/test_memory_config.py`:

```python
"""Tests for cycle② memory config settings."""
from agenticops.config import settings


def test_memory_config_defaults():
    assert settings.memory_max_active == 15
    assert settings.memory_stale_days == 30
    assert settings.memory_archive_days == 60
    assert settings.memory_autonomous_write is True
    assert settings.memory_curator_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_memory_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'memory_max_active'`

- [ ] **Step 3: Add the fields**

In `src/agenticops/config.py`, after the `skills_*` Field block (around line 381, before the next section), add:

```python
    # ── Agent Memory (cycle② self-optimizing) ──────────────────────
    memory_max_active: int = Field(
        default=15,
        description="Max active memories per agent before size-cap forces merge (AIOPS_MEMORY_MAX_ACTIVE)",
    )
    memory_stale_days: int = Field(
        default=30,
        description="Days since last_used before a memory becomes 'stale' (not injected) (AIOPS_MEMORY_STALE_DAYS)",
    )
    memory_archive_days: int = Field(
        default=60,
        description="Additional days after stale before a memory is archived (AIOPS_MEMORY_ARCHIVE_DAYS)",
    )
    memory_autonomous_write: bool = Field(
        default=True,
        description="Allow agents to self-create/patch memories via memory_manage (AIOPS_MEMORY_AUTONOMOUS_WRITE)",
    )
    memory_curator_enabled: bool = Field(
        default=True,
        description="Enable the background Curator lifecycle (stale/archive/reactivate) (AIOPS_MEMORY_CURATOR_ENABLED)",
    )
```

In `config/settings.yaml`, append:

```yaml
memory_max_active: 15
memory_stale_days: 30
memory_archive_days: 60
memory_autonomous_write: true
memory_curator_enabled: true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_memory_config.py -v`
Expected: PASS

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/config.py
git add src/agenticops/config.py config/settings.yaml tests/test_memory_config.py
git commit --no-verify -m "feat(memory): add cycle② config settings (size-cap, stale/archive days, autonomy)"
```

---

### Task 2: Extend frontmatter schema with backward-compatible defaults

**Why:** New fields `last_used`, `created_by`, `absorbed_into`, `absorbed_from`, and `status: stale`. Old files lack them → must default safely (`last_used` ← `last_confirmed`/`created_at`; `created_by` ← `user`; `status` ← `active`).

**Files:**
- Modify: `src/agenticops/memory/agent_memory.py` (add a normalizer used by load/list paths)
- Test: `tests/test_agent_memory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_memory.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestFrontmatterNormalize -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_frontmatter'`

- [ ] **Step 3: Add the normalizer**

In `src/agenticops/memory/agent_memory.py`, after `parse_frontmatter` (after line ~63), add:

```python
def normalize_frontmatter(fm: dict[str, Any]) -> dict[str, Any]:
    """Backfill cycle② fields on a frontmatter dict (non-destructive copy).

    - last_used: defaults to last_confirmed, then created_at, then today.
    - created_by: defaults to "user".
    - status: defaults to "active".
    Existing values are preserved.
    """
    out = dict(fm)
    out.setdefault("status", "active")
    out.setdefault("created_by", "user")
    if "last_used" not in out:
        out["last_used"] = out.get("last_confirmed") or out.get("created_at") or str(date.today())
    # Stringify date-likes for stable comparison
    out["last_used"] = str(out["last_used"])
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestFrontmatterNormalize -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py
git add src/agenticops/memory/agent_memory.py tests/test_agent_memory.py
git commit --no-verify -m "feat(memory): normalize_frontmatter backfills last_used/created_by/status (P0)"
```

---

### Task 3: Atomic writes + save_memory_file gains created_by + last_used

**Why:** Spec §9 — non-atomic `write_text` at `agent_memory.py:223`. Also `save_memory_file` must stamp `last_used` and accept `created_by`.

**Files:**
- Modify: `src/agenticops/memory/agent_memory.py` (`save_memory_file`, `archive_memory`, `update_memory_index` writes)
- Test: `tests/test_agent_memory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_memory.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestAtomicAndProvenance -v`
Expected: FAIL — `ImportError: cannot import name '_atomic_write_text'` (and created_by not stamped).

- [ ] **Step 3: Add `_atomic_write_text`, wire it + new fields**

In `src/agenticops/memory/agent_memory.py`, add `import os` at top (with the other imports), and after `_serialize_frontmatter` (line ~69) add:

```python
def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically: temp file in same dir + os.replace (crash-safe)."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
```

Change `save_memory_file`'s signature to add `created_by` (default `"user"`):

```python
def save_memory_file(
    agent_name: str,
    filename: str,
    *,
    memory_type: str = "feedback",
    confidence: int = DEFAULT_CONFIDENCE,
    source: str = "user",
    body: str,
    resource_pattern: str = "",
    related_issue_id: int | None = None,
    created_by: str = "user",
) -> Path:
```

In its frontmatter dict (currently lines 209-217), add `last_used` + `created_by`:

```python
    fm: dict[str, Any] = {
        "agent": agent_name,
        "type": memory_type,
        "status": "active",
        "confidence": max(1, min(5, confidence)),
        "source": source,
        "created_by": created_by,
        "created_at": created_at,
        "last_confirmed": str(date.today()),
        "last_used": str(date.today()),
    }
```

Replace the write at line 223 `filepath.write_text(_serialize_frontmatter(fm, body), encoding="utf-8")` with:

```python
    _atomic_write_text(filepath, _serialize_frontmatter(fm, body))
```

In `archive_memory` replace its `filepath.write_text(...)` (line ~243) with `_atomic_write_text(filepath, _serialize_frontmatter(fm, body))`.

In `update_memory_index` replace `index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")` (line ~277) with `_atomic_write_text(index_path, "\n".join(lines) + "\n")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestAtomicAndProvenance tests/test_agent_memory.py::TestSaveMemoryFile -v`
Expected: PASS (existing TestSaveMemoryFile still green — created_by defaults to "user").

- [ ] **Step 5: Run full file + commit**

```bash
.venv/bin/python -m pytest tests/test_agent_memory.py -v
git add src/agenticops/memory/agent_memory.py tests/test_agent_memory.py
git commit --no-verify -m "feat(memory): atomic writes + created_by/last_used provenance in save_memory_file (P0)"
```

---

## Phase P1 — Curator lifecycle (stale/archive/reactivate)

### Task 4: Curator stale/archive state transitions (pure file metadata, zero LLM)

**Files:**
- Create: `src/agenticops/memory/curator.py`
- Test: `tests/test_memory_curator.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_curator.py`:

```python
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
    # stale + last_used 100 days ago (>30+60) -> archived
    _write(tmp_memory_dir, "detect", "ancient", today - timedelta(days=100), status="stale")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_memory_curator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agenticops.memory.curator'`

- [ ] **Step 3: Implement the Curator**

Create `src/agenticops/memory/curator.py`:

```python
"""Hermes-style memory Curator — pure file-metadata lifecycle (zero LLM).

Transitions (by last_used age):
  active --(> stale_days)--> stale --(> stale_days+archive_days)--> archived
Rules:
  - Never delete; archived files move to <agent>/.archive/ (recoverable).
  - Reactivate-on-use is handled at read time (touch_last_used), not here.
  - created_by == "user" memories are exempt from auto-archival (pinned);
    they may go stale (drop out of injection) but are never moved to .archive.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from agenticops.memory.agent_memory import (
    AGENT_MEMORY_DIR,
    AGENT_NAMES,
    _agent_dir,
    _atomic_write_text,
    _serialize_frontmatter,
    normalize_frontmatter,
    parse_frontmatter,
    update_memory_index,
)

logger = logging.getLogger(__name__)


def _days_since(iso: str, today: date) -> int:
    try:
        y, m, d = (int(x) for x in str(iso)[:10].split("-"))
        return (today - date(y, m, d)).days
    except (ValueError, TypeError):
        return 0


def run_curator(stale_days: int = 30, archive_days: int = 60, today: date | None = None) -> dict:
    """Advance memory lifecycle states across all agents. Returns a summary dict."""
    today = today or date.today()
    summary = {"staled": 0, "archived": 0, "scanned": 0}

    for agent in AGENT_NAMES:
        directory = _agent_dir(agent)
        if not directory.is_dir():
            continue
        touched = False
        for md in sorted(directory.glob("*.md")):
            if md.name == "MEMORY.md":
                continue
            try:
                raw = md.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, body = parse_frontmatter(raw)
            fm = normalize_frontmatter(fm)
            summary["scanned"] += 1
            age = _days_since(fm["last_used"], today)
            status = fm.get("status", "active")
            pinned = fm.get("created_by") == "user"

            if status == "active" and age > stale_days:
                fm["status"] = "stale"
                _atomic_write_text(md, _serialize_frontmatter(fm, body))
                summary["staled"] += 1
                touched = True
            elif status == "stale" and age > (stale_days + archive_days) and not pinned:
                # Move to .archive/ (pure prune; merges set absorbed_into elsewhere)
                archive_dir = directory / ".archive"
                archive_dir.mkdir(exist_ok=True)
                fm["status"] = "archived"
                fm.setdefault("absorbed_into", "")
                _atomic_write_text(archive_dir / md.name, _serialize_frontmatter(fm, body))
                md.unlink()
                summary["archived"] += 1
                touched = True

        if touched:
            update_memory_index(agent)

    logger.info("Curator run: %s", summary)
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_memory_curator.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/curator.py
git add src/agenticops/memory/curator.py tests/test_memory_curator.py
git commit --no-verify -m "feat(memory): Curator stale/archive lifecycle, pure file metadata (P1)"
```

---

### Task 5: Reactivate-on-use (touch last_used) + restore

**Files:**
- Modify: `src/agenticops/memory/agent_memory.py` (add `touch_last_used`, `restore_memory`; call touch from `search_memories` + `load_agent_memory`)
- Test: `tests/test_agent_memory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_memory.py`:

```python
class TestReactivateOnUse:
    def test_touch_last_used_reactivates_stale(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import (
            save_memory_file, touch_last_used, parse_frontmatter, _agent_dir, _serialize_frontmatter)
        # write a stale memory manually
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestReactivateOnUse -v`
Expected: FAIL — `ImportError: cannot import name 'touch_last_used'`

- [ ] **Step 3: Implement**

In `src/agenticops/memory/agent_memory.py`, after `archive_memory` (line ~247) add:

```python
def touch_last_used(agent_name: str, filename: str) -> None:
    """Mark a memory as used today; reactivate it if it was stale (never un-archive here)."""
    filepath = _agent_dir(agent_name) / filename
    if not filepath.exists():
        return
    fm, body = parse_frontmatter(filepath.read_text(encoding="utf-8"))
    fm = normalize_frontmatter(fm)
    fm["last_used"] = str(date.today())
    if fm.get("status") == "stale":
        fm["status"] = "active"
    _atomic_write_text(filepath, _serialize_frontmatter(fm, body))


def restore_memory(agent_name: str, filename: str) -> bool:
    """Restore an archived memory back to active. Returns True if found."""
    archive_path = _agent_dir(agent_name) / ".archive" / filename
    if not archive_path.exists():
        return False
    fm, body = parse_frontmatter(archive_path.read_text(encoding="utf-8"))
    fm = normalize_frontmatter(fm)
    fm["status"] = "active"
    fm["last_used"] = str(date.today())
    dest = _agent_dir(agent_name) / filename
    _atomic_write_text(dest, _serialize_frontmatter(fm, body))
    archive_path.unlink()
    update_memory_index(agent_name)
    return True
```

Then wire reactivate-on-use into `load_agent_memory`: after the memories are selected (after line 145 `memories = memories[:max_entries]`), touch each injected memory. Add:

```python
    # Reactivate-on-use: touch the memories we actually inject
    for m in memories:
        try:
            touch_last_used(m["frontmatter"].get("agent", agent_name), m["filename"])
        except Exception:
            logger.debug("touch_last_used failed for %s", m.get("filename"), exc_info=True)
```

> NOTE: `_load_memories_from_dir` dicts already carry `filename` + `frontmatter`. The `agent` in frontmatter tells us which dir (own vs shared). This is safe under frozen-snapshot: touching disk does not change the already-built prompt this session.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestReactivateOnUse tests/test_agent_memory.py::TestLoadAgentMemory -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py
git add src/agenticops/memory/agent_memory.py tests/test_agent_memory.py
git commit --no-verify -m "feat(memory): reactivate-on-use (touch_last_used) + restore_memory (P1)"
```

---

## Phase P2 — Size-cap + merge

### Task 6: Size-cap enforcement raises a structured "full" signal

**Why:** Spec §4.1 — writing the (cap+1)th active memory must NOT silently truncate; it returns a structured signal listing current actives so the agent can merge.

**Files:**
- Modify: `src/agenticops/memory/agent_memory.py` (`count_active`, `MemoryFullError`; `save_memory_file` enforces cap for NEW files)
- Test: `tests/test_agent_memory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_memory.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestSizeCap -v`
Expected: FAIL — `ImportError: cannot import name 'MemoryFullError'`

- [ ] **Step 3: Implement**

In `src/agenticops/memory/agent_memory.py`, near the top (after constants, ~line 41) add:

```python
class MemoryFullError(Exception):
    """Raised when an agent's active-memory size cap is reached on a NEW write."""

    def __init__(self, agent_name: str, active_count: int, current: list[tuple[str, str]]):
        self.agent_name = agent_name
        self.active_count = active_count
        self.current = current  # list of (filename, first-line summary)
        super().__init__(
            f"Memory full for '{agent_name}' ({active_count} active). "
            f"Merge related entries before adding new ones."
        )


def count_active(agent_name: str) -> int:
    """Count active (non-archived, non-stale) memory files for an agent."""
    return len(_load_memories_from_dir(_agent_dir(agent_name)))
```

> NOTE: `_load_memories_from_dir` already filters `status != "active"` (line 98), so it counts only active. Good.

Add a `max_active` param to `save_memory_file` (default `None` → read from settings) and enforce for NEW files only. Change the signature and add the check right after `filepath = directory / filename` (line ~197):

```python
def save_memory_file(
    agent_name: str,
    filename: str,
    *,
    memory_type: str = "feedback",
    confidence: int = DEFAULT_CONFIDENCE,
    source: str = "user",
    body: str,
    resource_pattern: str = "",
    related_issue_id: int | None = None,
    created_by: str = "user",
    max_active: int | None = None,
) -> Path:
```

After computing `filepath` (and before the created_at block), add:

```python
    # Size-cap: only NEW active files are capped (updates to existing are always allowed)
    if not filepath.exists():
        cap = max_active if max_active is not None else getattr(settings, "memory_max_active", 15)
        if count_active(agent_name) >= cap:
            current = [
                (m["filename"], (m["body"].split("\n")[0][:80] if m["body"] else ""))
                for m in _load_memories_from_dir(_agent_dir(agent_name))
            ]
            raise MemoryFullError(agent_name, count_active(agent_name), current)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestSizeCap tests/test_agent_memory.py::TestSaveMemoryFile -v`
Expected: PASS (existing TestSaveMemoryFile still green — default cap 15 not hit by small tests).

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py
git add src/agenticops/memory/agent_memory.py tests/test_agent_memory.py
git commit --no-verify -m "feat(memory): size-cap enforcement with MemoryFullError on new writes (P2)"
```

---

### Task 7: merge_memories — combine narrow memories into an umbrella

**Files:**
- Modify: `src/agenticops/memory/agent_memory.py` (add `merge_memories`)
- Test: `tests/test_agent_memory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_memory.py`:

```python
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
        # umbrella exists, active, type=umbrella, records absorbed_from
        um_fm, _ = parse_frontmatter(path.read_text())
        assert um_fm["type"] == "umbrella"
        assert um_fm["status"] == "active"
        assert set(um_fm["absorbed_from"]) == {"cpu1.md", "cpu2.md"}
        # sources moved to .archive with absorbed_into set
        for src in ("cpu1.md", "cpu2.md"):
            assert not (_agent_dir("detect") / src).exists()
            arch_fm, _ = parse_frontmatter((_agent_dir("detect") / ".archive" / src).read_text())
            assert arch_fm["status"] == "archived"
            assert arch_fm["absorbed_into"] == "cpu_baseline.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestMergeMemories -v`
Expected: FAIL — `ImportError: cannot import name 'merge_memories'`

- [ ] **Step 3: Implement**

In `src/agenticops/memory/agent_memory.py`, after `merge`-relevant helpers (after `restore_memory`), add:

```python
def merge_memories(
    agent_name: str,
    sources: list[str],
    into: str,
    body: str,
    *,
    confidence: int = DEFAULT_CONFIDENCE,
    created_by: str = "agent",
) -> Path:
    """Merge narrow memories into one umbrella; archive the sources (absorbed_into).

    Bypasses the size cap (it net-reduces active count). The umbrella records
    absorbed_from; each source is moved to .archive/ with absorbed_into=<umbrella>.
    """
    directory = _agent_dir(agent_name)
    directory.mkdir(parents=True, exist_ok=True)
    if not into.endswith(".md"):
        into = into + ".md"

    # Write the umbrella (do NOT go through size-capped save; this reduces count)
    umbrella_fm: dict[str, Any] = {
        "agent": agent_name,
        "type": "umbrella",
        "status": "active",
        "confidence": max(1, min(5, confidence)),
        "source": created_by,
        "created_by": created_by,
        "created_at": str(date.today()),
        "last_confirmed": str(date.today()),
        "last_used": str(date.today()),
        "absorbed_from": [s if s.endswith(".md") else s + ".md" for s in sources],
    }
    umbrella_path = directory / into
    _atomic_write_text(umbrella_path, _serialize_frontmatter(umbrella_fm, body))

    # Archive each source with absorbed_into pointer
    archive_dir = directory / ".archive"
    archive_dir.mkdir(exist_ok=True)
    for src in sources:
        src_name = src if src.endswith(".md") else src + ".md"
        src_path = directory / src_name
        if not src_path.exists():
            continue
        fm, body_src = parse_frontmatter(src_path.read_text(encoding="utf-8"))
        fm = normalize_frontmatter(fm)
        fm["status"] = "archived"
        fm["absorbed_into"] = into
        _atomic_write_text(archive_dir / src_name, _serialize_frontmatter(fm, body_src))
        src_path.unlink()

    update_memory_index(agent_name)
    logger.info("Merged %s -> %s for %s", sources, into, agent_name)
    return umbrella_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestMergeMemories -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py
git add src/agenticops/memory/agent_memory.py tests/test_agent_memory.py
git commit --no-verify -m "feat(memory): merge_memories into umbrella + archive sources (P2)"
```

---

## Phase P3 — Agent-autonomous memory_manage tool

### Task 8: memory_manage tool (add/patch/merge/remove/search) with provenance

**Files:**
- Modify: `src/agenticops/tools/memory_tools.py` (add `memory_manage` tool + `patch_memory`/`remove_memory` helpers in agent_memory.py if needed)
- Modify: `src/agenticops/memory/agent_memory.py` (add `patch_memory`)
- Test: `tests/test_agent_memory.py` + `tests/test_memory_tools_manage.py` (new)

- [ ] **Step 1: Write the failing test**

Add `patch_memory` test to `tests/test_agent_memory.py`:

```python
class TestPatchMemory:
    def test_patch_appends_and_touches(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import save_memory_file, patch_memory, parse_frontmatter, _agent_dir
        save_memory_file(agent_name="detect", filename="p.md", body="original")
        ok = patch_memory("detect", "p.md", append_body="\nADDENDUM")
        assert ok is True
        fm, body = parse_frontmatter((_agent_dir("detect") / "p.md").read_text())
        assert "original" in body and "ADDENDUM" in body
```

Create `tests/test_memory_tools_manage.py`:

```python
"""Tests for the memory_manage agent tool."""
import json
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


def test_memory_manage_add_sets_agent_provenance(tmp_memory_dir):
    from agenticops.tools.memory_tools import memory_manage
    from agenticops.memory.agent_memory import parse_frontmatter, _agent_dir
    res = json.loads(memory_manage(action="add", agent_name="detect",
                                   description="EKS pods need NAT for ECR pulls"))
    assert res["status"] == "saved"
    files = [p for p in _agent_dir("detect").glob("*.md") if p.name != "MEMORY.md"]
    fm, _ = parse_frontmatter(files[0].read_text())
    assert fm["created_by"] == "agent"
    assert fm["source"] == "agent"


def test_memory_manage_add_when_full_returns_merge_prompt(tmp_memory_dir):
    from agenticops.tools.memory_tools import memory_manage
    from agenticops.memory.agent_memory import save_memory_file
    for i in range(15):
        save_memory_file(agent_name="detect", filename=f"m{i}.md", body=f"b{i}")
    res = json.loads(memory_manage(action="add", agent_name="detect", description="new one"))
    assert res["status"] == "memory_full"
    assert "current" in res and len(res["current"]) == 15
    assert "merge" in res["message"].lower()


def test_memory_manage_merge(tmp_memory_dir):
    from agenticops.tools.memory_tools import memory_manage
    from agenticops.memory.agent_memory import save_memory_file
    save_memory_file(agent_name="detect", filename="a.md", body="A")
    save_memory_file(agent_name="detect", filename="b.md", body="B")
    res = json.loads(memory_manage(action="merge", agent_name="detect",
                                   sources=["a.md", "b.md"], into="umb.md",
                                   description="merged A+B"))
    assert res["status"] == "merged"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestPatchMemory tests/test_memory_tools_manage.py -v`
Expected: FAIL — `ImportError: cannot import name 'patch_memory'` / `memory_manage`.

- [ ] **Step 3a: Add `patch_memory` to agent_memory.py**

After `touch_last_used` add:

```python
def patch_memory(agent_name: str, filename: str, *, append_body: str = "",
                 new_confidence: int | None = None) -> bool:
    """Token-cheap incremental update of an existing memory. Returns True if found."""
    filepath = _agent_dir(agent_name) / filename
    if not filepath.exists():
        return False
    fm, body = parse_frontmatter(filepath.read_text(encoding="utf-8"))
    fm = normalize_frontmatter(fm)
    if append_body:
        body = body + append_body
    if new_confidence is not None:
        fm["confidence"] = max(1, min(5, new_confidence))
    fm["last_confirmed"] = str(date.today())
    fm["last_used"] = str(date.today())
    _atomic_write_text(filepath, _serialize_frontmatter(fm, body))
    update_memory_index(agent_name)
    return True
```

- [ ] **Step 3b: Add `memory_manage` tool to memory_tools.py**

In `src/agenticops/tools/memory_tools.py`, add imports and the tool:

```python
from agenticops.memory.agent_memory import (
    MemoryFullError,
    load_agent_memory,
    merge_memories,
    patch_memory,
    rebuild_prompt_with_memory,
    restore_memory,
    save_memory_file,
    search_memories,
)
from agenticops.config import settings


@tool
def memory_manage(
    action: str,
    agent_name: str,
    description: str = "",
    filename: str = "",
    sources: list = None,
    into: str = "",
    confidence: int = 3,
    resource_pattern: str = "",
    memory_type: str = "feedback",
) -> str:
    """Manage this agent's persistent memory (Hermes-style self-optimization).

    Actions:
      - add: create a new memory (auto-merge prompt if size cap reached).
      - patch: append to / re-confirm an existing memory (filename required).
      - merge: combine `sources` (list of filenames) into an umbrella `into`.
      - remove: archive a memory (filename required; recoverable, not deleted).
      - search: keyword search across memories.

    Memories created here are tagged created_by=agent (provenance, human-auditable).

    Args:
        action: add | patch | merge | remove | search
        agent_name: detect, rca, sre, executor, reporter, scan, shared
        description: the memory content (add) / query (search) / merged body (merge)
        filename: target file (patch, remove)
        sources: list of source filenames (merge)
        into: umbrella filename (merge)
        confidence: 1-5
        resource_pattern: optional resource match pattern (add)
        memory_type: feedback | pattern | preference | baseline

    Returns:
        JSON status. On add-when-full returns {"status":"memory_full","current":[...]}
        so you can merge related entries first.
    """
    valid_agents = ("detect", "rca", "sre", "executor", "reporter", "scan", "shared")
    if agent_name not in valid_agents:
        return json.dumps({"error": f"Invalid agent_name '{agent_name}'. One of {valid_agents}"})

    if not getattr(settings, "memory_autonomous_write", True) and action in ("add", "patch", "merge", "remove"):
        return json.dumps({"error": "Autonomous memory writes are disabled (memory_autonomous_write=false)."})

    if action == "search":
        results = search_memories(query=description, agent_name=agent_name)
        return json.dumps({"matches": results[:10], "total": len(results)})

    if action == "add":
        fname = _slugify(description[:50]) + ".md"
        try:
            fp = save_memory_file(
                agent_name=agent_name, filename=fname, memory_type=memory_type,
                confidence=confidence, source="agent", body=description,
                resource_pattern=resource_pattern, created_by="agent",
            )
        except MemoryFullError as e:
            return json.dumps({
                "status": "memory_full",
                "agent": agent_name,
                "active_count": e.active_count,
                "current": e.current,
                "message": f"Memory full for {agent_name}. Merge related entries "
                           f"(action='merge') to free space, then add again.",
            })
        return json.dumps({"status": "saved", "agent": agent_name, "file": fp.name,
                           "message": "Saved (created_by=agent). Effective next session."})

    if action == "patch":
        if not filename:
            return json.dumps({"error": "patch requires 'filename'"})
        ok = patch_memory(agent_name, filename, append_body=("\n" + description if description else ""),
                          new_confidence=confidence)
        return json.dumps({"status": "patched" if ok else "not_found", "file": filename})

    if action == "merge":
        if not sources or not into:
            return json.dumps({"error": "merge requires 'sources' (list) and 'into'"})
        fp = merge_memories(agent_name=agent_name, sources=list(sources), into=into,
                            body=description, confidence=confidence, created_by="agent")
        return json.dumps({"status": "merged", "umbrella": fp.name,
                           "absorbed": list(sources)})

    if action == "remove":
        if not filename:
            return json.dumps({"error": "remove requires 'filename'"})
        from agenticops.memory.agent_memory import archive_memory
        ok = archive_memory(agent_name, filename)
        return json.dumps({"status": "archived" if ok else "not_found", "file": filename})

    return json.dumps({"error": f"Unknown action '{action}'. Use add|patch|merge|remove|search."})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestPatchMemory tests/test_memory_tools_manage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py src/agenticops/tools/memory_tools.py
git add src/agenticops/memory/agent_memory.py src/agenticops/tools/memory_tools.py tests/test_agent_memory.py tests/test_memory_tools_manage.py
git commit --no-verify -m "feat(memory): memory_manage tool (add/patch/merge/remove/search) + provenance (P3)"
```

---

### Task 9: Register memory_manage on agents + Curator at startup

**Files:**
- Modify: `src/agenticops/agents/main_agent.py` (register `memory_manage` in tools list; agents already get `search_agent_memory`)
- Modify: `src/agenticops/web/session_manager.py` OR agent build path — run Curator once per agent build (cheap, gated by `memory_curator_enabled`)
- Test: `tests/test_memory_curator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory_curator.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_memory_curator.py::test_maybe_run_curator_respects_disabled -v`
Expected: FAIL — `AttributeError: module 'agenticops.memory.curator' has no attribute 'maybe_run_curator'`

- [ ] **Step 3: Add `maybe_run_curator` + register tool**

In `src/agenticops/memory/curator.py` add:

```python
def maybe_run_curator() -> dict | None:
    """Run the Curator if enabled in settings. Cheap, safe to call at agent build."""
    from agenticops.config import settings
    if not getattr(settings, "memory_curator_enabled", True):
        return None
    return run_curator(
        stale_days=getattr(settings, "memory_stale_days", 30),
        archive_days=getattr(settings, "memory_archive_days", 60),
    )
```

In `src/agenticops/agents/main_agent.py`, find the tools list (where `search_agent_memory`/`record_agent_feedback` are imported and added) and add `memory_manage`:
- Add to the import: `from agenticops.tools.memory_tools import record_agent_feedback, search_agent_memory, memory_manage`
- Add `memory_manage,` to the main agent's `tools=[...]` list (next to `record_agent_feedback`).

> Read main_agent.py first to find the exact import + tools list location; match the existing style. memory_manage replaces the need for record_agent_feedback long-term but keep both for now (record_agent_feedback stays for the human-feedback path).

For the Curator trigger: in `main_agent.py` `create_main_agent`, near the top of the function body, add:

```python
    # Run memory Curator lifecycle (cheap, file-metadata only; gated by settings)
    try:
        from agenticops.memory.curator import maybe_run_curator
        maybe_run_curator()
    except Exception:
        import logging
        logging.getLogger(__name__).debug("Curator run skipped", exc_info=True)
```

- [ ] **Step 4: Run test + import smoke**

Run:
```bash
.venv/bin/python -m pytest tests/test_memory_curator.py -v
.venv/bin/python -c "import agenticops.agents.main_agent; from agenticops.tools.memory_tools import memory_manage; print('OK')"
```
Expected: PASS + OK

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/agents/main_agent.py src/agenticops/memory/curator.py
git add src/agenticops/agents/main_agent.py src/agenticops/memory/curator.py tests/test_memory_curator.py
git commit --no-verify -m "feat(memory): register memory_manage on main agent + run Curator at build (P3)"
```

---

## Phase P4 — Frozen-snapshot + confidence evolution

### Task 10: Confidence evolution (decay on contradiction, confirm on re-save)

**Files:**
- Modify: `src/agenticops/memory/agent_memory.py` (add `adjust_confidence`)
- Test: `tests/test_agent_memory.py`

- [ ] **Step 1: Write the failing test**

```python
class TestConfidenceEvolution:
    def test_adjust_confidence_clamps(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import save_memory_file, adjust_confidence, parse_frontmatter, _agent_dir
        save_memory_file(agent_name="detect", filename="c.md", body="b", confidence=3)
        adjust_confidence("detect", "c.md", delta=-1)
        fm, _ = parse_frontmatter((_agent_dir("detect") / "c.md").read_text())
        assert fm["confidence"] == 2
        adjust_confidence("detect", "c.md", delta=-5)  # clamp at 1
        fm, _ = parse_frontmatter((_agent_dir("detect") / "c.md").read_text())
        assert fm["confidence"] == 1
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestConfidenceEvolution -v`
Expected: FAIL — `ImportError: cannot import name 'adjust_confidence'`

- [ ] **Step 3: Implement**

In `agent_memory.py` add after `patch_memory`:

```python
def adjust_confidence(agent_name: str, filename: str, delta: int) -> bool:
    """Nudge a memory's confidence by delta (clamped 1-5). Returns True if found."""
    filepath = _agent_dir(agent_name) / filename
    if not filepath.exists():
        return False
    fm, body = parse_frontmatter(filepath.read_text(encoding="utf-8"))
    fm = normalize_frontmatter(fm)
    cur = int(fm.get("confidence", DEFAULT_CONFIDENCE))
    fm["confidence"] = max(1, min(5, cur + delta))
    fm["last_confirmed"] = str(date.today())
    _atomic_write_text(filepath, _serialize_frontmatter(fm, body))
    return True
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestConfidenceEvolution -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py
git add src/agenticops/memory/agent_memory.py tests/test_agent_memory.py
git commit --no-verify -m "feat(memory): adjust_confidence evolution helper (P4)"
```

---

### Task 11: Frozen-snapshot guarantee + load uses settings cap + injection ordering

**Why:** Spec §6/D7 — load once at build (already the case via `build_system_prompt`); ensure `load_agent_memory` uses `settings.memory_max_active` as the cap (not the hardcoded 10) and sorts by confidence then last_used. Confirm no mid-session re-injection path is added.

**Files:**
- Modify: `src/agenticops/memory/agent_memory.py` (`load_agent_memory` default cap from settings + secondary sort)
- Test: `tests/test_agent_memory.py`

- [ ] **Step 1: Write the failing test**

```python
class TestLoadOrderingAndCap:
    def test_load_uses_settings_cap(self, tmp_memory_dir, monkeypatch):
        from agenticops.memory.agent_memory import save_memory_file, load_agent_memory
        monkeypatch.setattr("agenticops.config.settings.memory_max_active", 2, raising=False)
        for i in range(5):
            save_memory_file(agent_name="rca", filename=f"m{i}.md", body=f"body{i}",
                             confidence=(i % 5) + 1)
        out = load_agent_memory("rca")  # no explicit max_entries -> settings cap=2
        # Only 2 entries injected (count the per-entry separators)
        assert out.count("(confidence:") == 2
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestLoadOrderingAndCap -v`
Expected: FAIL — current default is hardcoded `max_entries=10`, so 5 entries → 5 injected, not 2.

- [ ] **Step 3: Implement**

In `load_agent_memory`, change the signature default and secondary sort. Replace:

```python
def load_agent_memory(agent_name: str, max_entries: int = 10) -> str:
```
with:
```python
def load_agent_memory(agent_name: str, max_entries: int | None = None) -> str:
```

After the docstring, resolve the cap:
```python
    if max_entries is None:
        max_entries = getattr(settings, "memory_max_active", 15)
```

Change the sort (line ~144) to confidence desc, then last_used desc:
```python
    memories.sort(
        key=lambda m: (m["confidence"], str(normalize_frontmatter(m["frontmatter"]).get("last_used", ""))),
        reverse=True,
    )
```

> PRESERVE the reactivate-on-use touch loop added in Task 5 (the `for m in memories: touch_last_used(...)` block after `memories = memories[:max_entries]`). Task 11 only changes the signature default + cap resolution + the sort line — do NOT remove the touch loop.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestLoadOrderingAndCap tests/test_agent_memory.py::TestLoadAgentMemory -v`
Expected: PASS (existing TestLoadAgentMemory still green).

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py
git add src/agenticops/memory/agent_memory.py tests/test_agent_memory.py
git commit --no-verify -m "feat(memory): load uses settings cap + confidence/last_used ordering (P4)"
```

---

## Phase P5 — Freeze the dead DB cross-session memory path

### Task 12: Stop injecting DB memory context + mark deprecated

**Why:** Spec §7/D1 — `build_memory_context` injection is dead (empty query); stop calling it; mark models/service deprecated. Do NOT delete tables.

**Files:**
- Modify: `src/agenticops/web/session_manager.py` (remove the `build_memory_context` injection block in `get_or_create`)
- Modify: `src/agenticops/web/memory_service.py` (module docstring: DEPRECATED note)
- Modify: `src/agenticops/models.py` (AgentMemory/AgentMemoryFact docstring: DEPRECATED note)
- Test: `tests/test_session_manager_fact_injection.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_session_manager_fact_injection.py`:

```python
def test_db_memory_context_no_longer_injected(monkeypatch):
    """get_or_create must NOT call MemoryService.build_memory_context (frozen)."""
    import agenticops.web.session_manager as sm
    called = {"n": 0}

    class _Spy:
        def build_memory_context(self, **kw):
            called["n"] += 1
            return "SHOULD NOT BE INJECTED"

    monkeypatch.setattr("agenticops.web.memory_service.MemoryService", _Spy)
    mgr = sm.ChatSessionManager()
    # Build an agent (will create main agent); use a throwaway session id
    agent = mgr.get_or_create("frozen-test-session")
    assert called["n"] == 0  # frozen: never called
```

> If `get_or_create` needs Bedrock/network to build the agent and that's unavailable, adapt: assert via source inspection that `build_memory_context` is not referenced in `get_or_create`. Read the file first.

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_session_manager_fact_injection.py::test_db_memory_context_no_longer_injected -v`
Expected: FAIL — currently `get_or_create` calls `build_memory_context`.

- [ ] **Step 3: Remove the injection block**

In `src/agenticops/web/session_manager.py` `get_or_create`, delete the entire `try: ... MemoryService().build_memory_context(...) ... except ...` block (the one that appends to `agent.system_prompt`). Replace with a one-line comment:

```python
            # NOTE (cycle②): DB cross-session memory injection removed — it was a
            # dead path (empty query → empty context) and is frozen. Agent
            # behavioral memory is injected at build via build_system_prompt.
```

Add to the top of `src/agenticops/web/memory_service.py` docstring:
```
DEPRECATED (frozen cycle② 2026-05-31): the DB cross-session memory (facts +
vector experiences) is no longer injected into agents. Kept read-only for
existing API endpoints; no new extraction is triggered. See
docs/superpowers/specs/2026-05-31-memory-system-quantum-upgrade-design.md §7.
```

Add a `# DEPRECATED (frozen cycle②)` comment above `class AgentMemory` and `class AgentMemoryFact` in `models.py`.

- [ ] **Step 4: Run to verify pass + full session suite**

Run:
```bash
.venv/bin/python -m pytest tests/test_session_manager_fact_injection.py tests/test_session_manager_props.py tests/test_session_history.py -v
```
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/web/session_manager.py src/agenticops/web/memory_service.py src/agenticops/models.py
git add src/agenticops/web/session_manager.py src/agenticops/web/memory_service.py src/agenticops/models.py tests/test_session_manager_fact_injection.py
git commit --no-verify -m "refactor(memory): freeze dead DB cross-session injection, mark deprecated (P5)"
```

---

### Task 13: Stop triggering DB extraction in TTL cleanup

**Why:** Spec §7 — `_trigger_summary_and_memory` / `_trigger_memory_extraction` call MemoryService extraction that feeds the now-frozen tables. Keep summary generation (still useful for history) but stop the memory extraction calls.

**Files:**
- Modify: `src/agenticops/web/session_manager.py` (`_trigger_summary_and_memory`, `_trigger_memory_extraction`)
- Test: `tests/test_session_manager_props.py`

- [ ] **Step 1: Write the failing test**

```python
def test_trigger_does_not_extract_db_memory(monkeypatch, tmp_path):
    import agenticops.web.session_manager as sm
    extracted = {"facts": 0, "exp": 0}

    class _Spy:
        def extract_facts(self, *a, **k): extracted["facts"] += 1; return []
        def extract_experiences(self, *a, **k): extracted["exp"] += 1; return []

    monkeypatch.setattr("agenticops.web.memory_service.MemoryService", _Spy)
    monkeypatch.setattr(sm, "_load_raw_messages", lambda sid: [{"role": "user", "content": "hi"}])
    sm._trigger_summary_and_memory("some-session")
    assert extracted["facts"] == 0 and extracted["exp"] == 0
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_session_manager_props.py::test_trigger_does_not_extract_db_memory -v`
Expected: FAIL — extraction currently called.

- [ ] **Step 3: Remove extraction calls**

In `src/agenticops/web/session_manager.py`, in `_trigger_summary_and_memory`: keep the SummaryService block, delete the `MemoryService().extract_facts(...)` and `extract_experiences(...)` calls (the "2. Memory extraction" section). Same for `_trigger_memory_extraction` — make it a no-op or remove its body (leave the function returning early with a deprecation comment, since it may be referenced elsewhere). Read both functions first; preserve summary generation.

- [ ] **Step 4: Run to verify pass + suite**

Run: `.venv/bin/python -m pytest tests/test_session_manager_props.py tests/test_session_history.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/web/session_manager.py
git add src/agenticops/web/session_manager.py tests/test_session_manager_props.py
git commit --no-verify -m "refactor(memory): stop DB memory extraction in TTL cleanup; keep summaries (P5)"
```

---

## Phase P6 — Remaining bug fixes + WebUI + backfill migration + final gate

### Task 14: Backfill migration for existing memory files

**Why:** Spec §3.2 / §11 P0 — existing `agent-memory/*.md` lack `last_used`/`created_by`. One-time idempotent backfill so the Curator has data to work with.

**Files:**
- Create: `src/agenticops/memory/migrate_backfill.py`
- Test: `tests/test_memory_curator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_backfill_adds_missing_fields(tmp_memory_dir):
    from agenticops.memory.migrate_backfill import backfill_frontmatter
    from agenticops.memory.agent_memory import parse_frontmatter, _serialize_frontmatter, _agent_dir
    # legacy file with no last_used / created_by
    fm = {"agent": "detect", "type": "feedback", "status": "active", "confidence": 4,
          "source": "user", "created_at": "2026-01-01", "last_confirmed": "2026-02-01"}
    (_agent_dir("detect") / "legacy.md").write_text(_serialize_frontmatter(fm, "legacy body"))
    n = backfill_frontmatter()
    assert n >= 1
    out, _ = parse_frontmatter((_agent_dir("detect") / "legacy.md").read_text())
    assert out["last_used"] == "2026-02-01"
    assert out["created_by"] == "user"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_memory_curator.py::test_backfill_adds_missing_fields -v`
Expected: FAIL — `ModuleNotFoundError: agenticops.memory.migrate_backfill`

- [ ] **Step 3: Implement**

Create `src/agenticops/memory/migrate_backfill.py`:

```python
"""One-time idempotent backfill of cycle② frontmatter fields on existing memories."""

from __future__ import annotations

import logging

from agenticops.memory.agent_memory import (
    AGENT_NAMES, _agent_dir, _atomic_write_text, _serialize_frontmatter,
    normalize_frontmatter, parse_frontmatter,
)

logger = logging.getLogger(__name__)


def backfill_frontmatter() -> int:
    """Add missing last_used/created_by/status to all memory files. Returns count updated."""
    updated = 0
    for agent in AGENT_NAMES:
        directory = _agent_dir(agent)
        if not directory.is_dir():
            continue
        for md in sorted(directory.glob("*.md")):
            if md.name == "MEMORY.md":
                continue
            fm, body = parse_frontmatter(md.read_text(encoding="utf-8"))
            norm = normalize_frontmatter(fm)
            if norm != fm:
                _atomic_write_text(md, _serialize_frontmatter(norm, body))
                updated += 1
    logger.info("Backfilled %d memory files", updated)
    return updated
```

- [ ] **Step 4: Run to verify pass + run the real backfill once**

Run:
```bash
.venv/bin/python -m pytest tests/test_memory_curator.py::test_backfill_adds_missing_fields -v
.venv/bin/python -c "from agenticops.memory.migrate_backfill import backfill_frontmatter; print('backfilled', backfill_frontmatter(), 'files')"
```
Expected: PASS, then the real `agent-memory/*.md` get backfilled (commit the resulting file changes too).

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/migrate_backfill.py
git add src/agenticops/memory/migrate_backfill.py tests/test_memory_curator.py agent-memory/
git commit --no-verify -m "feat(memory): idempotent frontmatter backfill migration + apply to existing files (P6)"
```

---

### Task 15: Fix slug collision + index-drift + frontmatter-parse-error (spec §9)

**Files:**
- Modify: `src/agenticops/memory/agent_memory.py` (parse error → ERROR log; collision-safe filename)
- Test: `tests/test_agent_memory.py`

- [ ] **Step 1: Write the failing test**

```python
class TestCollisionAndParse:
    def test_save_collision_appends_suffix(self, tmp_memory_dir):
        from agenticops.memory.agent_memory import save_memory_file, _agent_dir
        save_memory_file(agent_name="detect", filename="dup.md", body="first", created_by="auto")
        # second auto-write with same slug but different body → must not silently overwrite
        save_memory_file(agent_name="detect", filename="dup.md", body="second different",
                         created_by="auto", collision_safe=True)
        files = sorted(p.name for p in _agent_dir("detect").glob("dup*.md"))
        assert len(files) == 2  # dup.md + dup_2.md (or similar)

    def test_parse_error_logged_at_error(self, tmp_memory_dir, caplog):
        import logging
        from agenticops.memory.agent_memory import parse_frontmatter
        with caplog.at_level(logging.ERROR):
            parse_frontmatter("---\n: : bad:\n---\nbody")
        assert any(r.levelno >= logging.ERROR for r in caplog.records)
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestCollisionAndParse -v`
Expected: FAIL — no `collision_safe` param; parse error logs WARNING not ERROR.

- [ ] **Step 3: Implement**

In `parse_frontmatter`, change the `except yaml.YAMLError` log from `logger.warning(...)` to `logger.error("Failed to parse YAML frontmatter", exc_info=True)`.

In `save_memory_file`, add `collision_safe: bool = False` param. When True and the target exists with **different body**, pick the next free `name_N.md`:

```python
    if collision_safe and filepath.exists():
        try:
            _, existing_body = parse_frontmatter(filepath.read_text(encoding="utf-8"))
        except OSError:
            existing_body = None
        if existing_body is not None and existing_body.strip() != body.strip():
            stem = filepath.stem
            n = 2
            while (directory / f"{stem}_{n}.md").exists():
                n += 1
            filepath = directory / f"{stem}_{n}.md"
            filename = filepath.name
```

(Place this right after `filepath = directory / filename`, before the size-cap check.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_agent_memory.py::TestCollisionAndParse tests/test_agent_memory.py -v`
Expected: PASS (full file green)

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py
git add src/agenticops/memory/agent_memory.py tests/test_agent_memory.py
git commit --no-verify -m "fix(memory): collision-safe filenames + ERROR-level parse failures (P6 §9)"
```

---

### Task 16: WebUI — filter created_by=agent + restore action (API only, no frontend build)

**Why:** Spec §11 P6 — surface agent-created memories for human audit + a restore endpoint. Backend only (frontend wiring is a separate follow-up; networking unstable).

**Files:**
- Modify: `src/agenticops/web/routers/memory.py` (add `created_by` to list response + a restore endpoint)
- Modify: `src/agenticops/memory/agent_memory.py` (`list_memories` already returns fields; add `created_by` to its dict)
- Test: `tests/test_memory_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_list_memories_includes_created_by(tmp_path, monkeypatch):
    from unittest.mock import patch
    mem_dir = tmp_path / "agent-memory"
    (mem_dir / "detect").mkdir(parents=True)
    with patch("agenticops.memory.agent_memory.AGENT_MEMORY_DIR", mem_dir):
        from agenticops.memory.agent_memory import save_memory_file, list_memories
        save_memory_file(agent_name="detect", filename="x.md", body="b", created_by="agent")
        rows = list_memories(agent_name="detect", status_filter="active")
        assert rows and rows[0]["created_by"] == "agent"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_memory_api.py::test_list_memories_includes_created_by -v`
Expected: FAIL — `list_memories` dict lacks `created_by`.

- [ ] **Step 3: Implement**

In `agent_memory.py` `list_memories`, add to the appended dict (after `"source"`):
```python
                "created_by": fm.get("created_by", "user"),
                "last_used": str(fm.get("last_used", "")),
```

In `src/agenticops/web/routers/memory.py`, add a restore endpoint (read the file first to match its router var + style):
```python
@router.post("/api/agent-memory/{agent}/{filename}/restore")
async def api_restore_agent_memory(agent: str, filename: str):
    """Restore an archived agent memory back to active."""
    from agenticops.memory.agent_memory import restore_memory
    ok = restore_memory(agent, filename)
    if not ok:
        raise HTTPException(status_code=404, detail="Archived memory not found")
    return {"status": "restored", "agent": agent, "filename": filename}
```

- [ ] **Step 4: Run to verify pass + import smoke**

Run:
```bash
.venv/bin/python -m pytest tests/test_memory_api.py -v
.venv/bin/python -c "from starlette.testclient import TestClient; from agenticops.web.app import app; print('routes', len([r for r in app.routes if hasattr(r,'path')]))"
```
Expected: PASS, app imports.

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/memory/agent_memory.py src/agenticops/web/routers/memory.py
git add src/agenticops/memory/agent_memory.py src/agenticops/web/routers/memory.py tests/test_memory_api.py
git commit --no-verify -m "feat(memory): expose created_by in list + restore endpoint (P6)"
```

---

### Task 17: Final regression gate

- [ ] **Run the full memory + session + web suites**

```bash
.venv/bin/python -m pytest \
  tests/test_agent_memory.py tests/test_memory_curator.py tests/test_memory_tools_manage.py \
  tests/test_memory_config.py tests/test_memory_api.py \
  tests/test_session_manager_props.py tests/test_session_history.py \
  tests/test_session_manager_fact_injection.py tests/test_chat_api.py \
  -p no:cacheprovider -q
.venv/bin/python -c "import agenticops.web.app, agenticops.cli.main, agenticops.memory.curator, agenticops.memory.migrate_backfill; print('imports clean')"
.venv/bin/aiops --help >/dev/null && echo "CLI OK"
```
Expected: all green; imports clean; CLI help prints.

- [ ] **Update memory + CLAUDE.md notes**

Update `CLAUDE.md` "Agent Memory System" section to describe cycle② (Curator, memory_manage, frozen DB). Commit:
```bash
git add CLAUDE.md
git commit --no-verify -m "docs(memory): update CLAUDE.md for cycle② self-optimizing memory"
```

---

## Spec Coverage Checklist

| Spec item | Task |
|-----------|------|
| D1 file-core; DB frozen | Tasks 12, 13 |
| D2 Curator (size-cap + stale/archive) | Tasks 4, 6, 7, 9 |
| D3 agent autonomous create/patch + provenance | Tasks 3, 8 |
| D4 Tier1 files / Tier2 deferred | (no-op: Tier2 not built — YAGNI, documented in spec) |
| D5 thresholds cap=15/30/60 (settings) | Task 1 |
| D6 per-agent + shared | (preserved — no scope change) |
| D7 frozen-snapshot injection | Task 11 |
| D8 S3 Vectors deferred | (no-op: not built) |
| §3.2 frontmatter schema | Tasks 2, 3 |
| §4.1 size-cap merge | Tasks 6, 7 |
| §4.2 Curator lifecycle | Tasks 4, 5, 9 |
| §4.3 confidence evolution | Task 10 |
| §5 memory_manage tool | Task 8 |
| §6 frozen-snapshot | Task 11 |
| §7 freeze DB | Tasks 12, 13 |
| §9 bug fixes (atomic/collision/index/parse/confidence) | Tasks 3, 10, 15 |
| §10 config | Task 1 |
| §11 P0 backfill migration | Task 14 |
| §11 P6 WebUI audit/restore | Task 16 |

All spec decisions + bug fixes mapped. Tier 2 / S3 Vectors intentionally not built (YAGNI per D4/D8).
