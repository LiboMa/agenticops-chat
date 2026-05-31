# ③ Skills Autonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AgenticOps Skills self-optimizing and autonomous like Hermes — a unified `skill_manage` tool (add/improve/merge/deprecate/restore/search) with `created_by` provenance, a Curator lifecycle (agent drafts only; human skills pinned), multi-generation recoverable backups, and frozen-snapshot injection — by mirroring the proven cycle② memory pattern.

**Architecture:** Additive. New `skills/curator.py` mirrors `memory/curator.py`. New `skill_manage` tool in `skills/tools.py` mirrors `memory_manage`. Frontmatter gains `created_by/created_at/last_improved_at/improved_from/skill_version/status` with backward-compatible backfill (human skills → `created_by=user` pinned). Security-gated promotion (skills are executable). Existing draft→publish + LLM generation + progressive disclosure are ENHANCED, not rebuilt. Each task is TDD with a regression test.

**Tech Stack:** Python 3.12, pytest, YAML-frontmatter markdown SKILL.md packages, Strands `@tool`, pydantic-settings. Spec: `docs/superpowers/specs/2026-05-31-skills-autonomy-design.md`.

**Conventions:**
- venv: `.venv/bin/python` for all python/pytest.
- Single test: `.venv/bin/python -m pytest tests/<file>::<Class>::<test> -v`
- Compile gate: `.venv/bin/python -m py_compile src/agenticops/<file>.py`
- Commits use `git commit --no-verify` (project standing rule; bypass message is expected/benign).
- Branch: `cycle3-skills-autonomy` (already created, spec committed). Do NOT switch branches.
- **Existing skills baseline** (already implemented — DO NOT rebuild):
  - `skills/loader.py`: `SkillMetadata(name, description, metadata{}, tools[], is_draft)`, `discover_skills()`, `parse_frontmatter()`, `get_available_skills_xml()`, `load_skill_body()`, `load_skill_reference()`, `resolve_skill_tools()`, `_invalidate_skills_cache()`. Constants: `settings.skills_dir`, `settings.skills_draft_dir`.
  - `skills/evolution.py`: `create_draft_skill(name,description,content,references)`, `create_published_skill(...)`, `update_draft_skill(name,updated_content)`, `generate_skill_from_description(description)`, `auto_improve_skill(skill_name,gap,agent_context)`, `_atomic_write_text(path,text)` (cycle① added). Frontmatter currently `name` + `description: {json.dumps(description)}` only.
  - `skills/tools.py`: `@tool list_skills/activate_skill/read_skill_reference/create_skill/improve_skill/search_skill_registry`.
  - `skills/review.py`: `list_draft_skills/review_draft_skill/promote_skill(name)/reject_draft_skill`. `promote_skill` uses a single lossy `<name>.bak`.
  - `skills/improvement_store.py`: `add_improvement(skill_name,improvement,source,trigger,status,result)`, `update_improvement(id,status,result)`, `list_pending/list_history/list_all`. JSON at `data_dir/skill_improvements.json`.
  - `skills/security.py`: `classify_shell_command()`, `classify_kubectl()` → 'readonly'|'write'|'blocked'.
  - `services/skill_improvement_service.py`: `run_skill_improvement()` ALREADY wires add_improvement+update_improvement around auto_improve_skill. **The gap is the `improve_skill` TOOL path (tools.py:252) which calls auto_improve_skill WITHOUT recording.**
- **Pattern to mirror** (cycle②, on main): `memory/curator.py` (`run_curator`, `maybe_run_curator`, `_days_since`), `memory/agent_memory.py` (`normalize_frontmatter`, `_atomic_write_text`), `tools/memory_tools.py` (`memory_manage`).

---

## Phase P0 — Config + frontmatter provenance + backfill

### Task 1: Add skills autonomy config settings

**Files:**
- Modify: `src/agenticops/config.py` (add fields near the existing `skills_*` block, after `skills_post_resolution_review`/`skills_improvement_notify` ~line 377-385)
- Modify: `config/settings.yaml` (append)
- Test: `tests/test_skills_config.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_skills_config.py`:

```python
"""Tests for cycle③ skills autonomy config settings."""
from agenticops.config import settings


def test_skills_autonomy_config_defaults():
    assert settings.skills_autonomous_write is True
    assert settings.skills_curator_enabled is True
    assert settings.skills_draft_stale_days == 30
    assert settings.skills_draft_archive_days == 60
    assert settings.skills_security_scan_on_promote is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skills_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'skills_autonomous_write'`

- [ ] **Step 3: Add the fields**

First Read `src/agenticops/config.py` around lines 369-390 to find the end of the `skills_*` block. Insert (4-space indent, inside Settings class):

```python
    skills_autonomous_write: bool = Field(
        default=True,
        description="Allow agents to self-create/improve skills via skill_manage (drafts only) (AIOPS_SKILLS_AUTONOMOUS_WRITE)",
    )
    skills_curator_enabled: bool = Field(
        default=True,
        description="Enable the skills Curator lifecycle (agent drafts stale/archive; human skills pinned) (AIOPS_SKILLS_CURATOR_ENABLED)",
    )
    skills_draft_stale_days: int = Field(
        default=30,
        description="Days an unused agent draft stays before becoming stale (AIOPS_SKILLS_DRAFT_STALE_DAYS)",
    )
    skills_draft_archive_days: int = Field(
        default=60,
        description="Additional days after stale before an agent draft is archived (AIOPS_SKILLS_DRAFT_ARCHIVE_DAYS)",
    )
    skills_security_scan_on_promote: bool = Field(
        default=True,
        description="Security-scan a skill before promoting draft->published (blocks dangerous run_on_host) (AIOPS_SKILLS_SECURITY_SCAN_ON_PROMOTE)",
    )
```

Append to `config/settings.yaml`:

```yaml
skills_autonomous_write: true
skills_curator_enabled: true
skills_draft_stale_days: 30
skills_draft_archive_days: 60
skills_security_scan_on_promote: true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_skills_config.py -v`
Expected: PASS

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/config.py
git add src/agenticops/config.py config/settings.yaml tests/test_skills_config.py
git commit --no-verify -m "feat(skills): add cycle③ autonomy config (autonomous_write, curator, stale/archive days, security scan)"
```

---

### Task 2: Skill frontmatter provenance helpers + write provenance on create

**Why:** Spec §3 — add `created_by/created_at/last_improved_at/improved_from/skill_version/status` to generated SKILL.md, with a `normalize_skill_frontmatter` backfill (human skills default `created_by=user`).

**Files:**
- Modify: `src/agenticops/skills/loader.py` (add `normalize_skill_frontmatter`; `SkillMetadata` gains `created_by`)
- Modify: `src/agenticops/skills/evolution.py` (`create_draft_skill`/`create_published_skill` write provenance frontmatter)
- Test: `tests/test_skills_evolution.py` + `tests/test_skills_loader_coverage.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills_evolution.py`:

```python
class TestSkillProvenance:
    def test_create_draft_writes_provenance(self, tmp_path):
        import yaml
        from unittest.mock import patch
        from agenticops.skills.evolution import create_draft_skill
        with patch("agenticops.skills.evolution.settings") as ms:
            ms.skills_draft_dir = tmp_path
            d = create_draft_skill(name="x", description="d", content="body", created_by="agent")
        fm = yaml.safe_load((d / "SKILL.md").read_text().split("---")[1])
        assert fm["created_by"] == "agent"
        assert fm["status"] == "active"
        assert "created_at" in fm
        assert fm["skill_version"] == "1.0"

    def test_create_draft_defaults_created_by_user(self, tmp_path):
        import yaml
        from unittest.mock import patch
        from agenticops.skills.evolution import create_draft_skill
        with patch("agenticops.skills.evolution.settings") as ms:
            ms.skills_draft_dir = tmp_path
            d = create_draft_skill(name="y", description="d", content="body")
        fm = yaml.safe_load((d / "SKILL.md").read_text().split("---")[1])
        assert fm["created_by"] == "user"
```

Add to `tests/test_skills_loader_coverage.py`:

```python
class TestNormalizeSkillFrontmatter:
    def test_backfills_missing_provenance(self):
        from agenticops.skills.loader import normalize_skill_frontmatter
        fm = {"name": "old-skill", "description": "legacy"}
        out = normalize_skill_frontmatter(fm)
        assert out["created_by"] == "user"   # human-authored default (pinned)
        assert out["status"] == "active"
        assert out["skill_version"] == "1.0"

    def test_preserves_existing(self):
        from agenticops.skills.loader import normalize_skill_frontmatter
        fm = {"name": "s", "created_by": "agent", "status": "stale", "skill_version": "1.3"}
        out = normalize_skill_frontmatter(fm)
        assert out["created_by"] == "agent"
        assert out["status"] == "stale"
        assert out["skill_version"] == "1.3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skills_evolution.py::TestSkillProvenance tests/test_skills_loader_coverage.py::TestNormalizeSkillFrontmatter -v`
Expected: FAIL — `normalize_skill_frontmatter` undefined; `create_draft_skill` has no `created_by` param.

- [ ] **Step 3a: Add `normalize_skill_frontmatter` to loader.py**

Read `src/agenticops/skills/loader.py` to confirm imports (`from datetime import ...` may be absent — add `from datetime import date` if needed). After `parse_frontmatter` add:

```python
def normalize_skill_frontmatter(fm: dict) -> dict:
    """Backfill cycle③ provenance fields (non-destructive copy).

    Human-authored skills default created_by='user' (pinned — Curator never
    auto-archives them). Existing values are preserved.
    """
    out = dict(fm)
    out.setdefault("created_by", "user")
    out.setdefault("status", "active")
    out.setdefault("skill_version", "1.0")
    out.setdefault("created_at", str(date.today()))
    return out
```

Add `created_by: str = "user"` to the `SkillMetadata` dataclass (after `is_draft`, with default) so loader can surface it:

```python
    created_by: str = "user"
```

And in `_scan_directory` where `SkillMetadata(...)` is built (it sets name/description/metadata/tools/is_draft), add `created_by=fm.get("created_by", "user"),`.

- [ ] **Step 3b: Write provenance in evolution.py create functions**

In `src/agenticops/skills/evolution.py`, add `created_by: str = "user"` keyword param to BOTH `create_draft_skill` and `create_published_skill`. Change their frontmatter f-string from:

```python
    skill_md = f"""---
name: {name}
description: {json.dumps(description)}
---

{content}
"""
```

to:

```python
    import datetime as _dt
    _today = _dt.date.today().isoformat()
    skill_md = f"""---
name: {name}
description: {json.dumps(description)}
created_by: {created_by}
created_at: {_today}
skill_version: "1.0"
status: active
---

{content}
"""
```

(Apply to both functions. `json` already imported.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skills_evolution.py tests/test_skills_loader_coverage.py -v`
Expected: PASS (existing tests still green — created_by defaults to "user").

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/loader.py src/agenticops/skills/evolution.py
git add src/agenticops/skills/loader.py src/agenticops/skills/evolution.py tests/test_skills_evolution.py tests/test_skills_loader_coverage.py
git commit --no-verify -m "feat(skills): provenance frontmatter (created_by/status/version) + normalize backfill (P0)"
```

---

## Phase P1 — Skills Curator (agent drafts only; human skills pinned)

### Task 3: Skills Curator lifecycle

**Why:** Spec §4.2 — mirror memory/curator.py. Ages UNUSED `created_by=agent` drafts: `active→stale→archived` (move to `skills/.archive/`). Human skills (`created_by=user`) are pinned (skipped entirely).

**Files:**
- Create: `src/agenticops/skills/curator.py`
- Test: `tests/test_skills_curator.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_skills_curator.py`:

```python
"""Tests for the skills Curator (agent-draft lifecycle; human skills pinned)."""
from datetime import date, timedelta
from unittest.mock import patch
import pytest


@pytest.fixture
def tmp_skills(tmp_path):
    sdir = tmp_path / "skills"
    ddir = sdir / "draft"
    ddir.mkdir(parents=True)
    with patch("agenticops.config.settings.skills_dir", sdir, raising=False), \
         patch("agenticops.config.settings.skills_draft_dir", ddir, raising=False):
        yield sdir, ddir


def _write_skill(base, name, created_by, last_used, status="active"):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    fm = (f"---\nname: {name}\ndescription: d\ncreated_by: {created_by}\n"
          f"status: {status}\nskill_version: \"1.0\"\nlast_used: {last_used}\n---\n\nbody")
    (d / "SKILL.md").write_text(fm)


def test_agent_draft_active_to_stale(tmp_skills):
    from agenticops.skills.curator import run_skills_curator
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    today = date(2026, 6, 1)
    _write_skill(ddir, "old-draft", "agent", str(today - timedelta(days=40)))
    run_skills_curator(stale_days=30, archive_days=60, today=today)
    fm, _ = parse_frontmatter((ddir / "old-draft" / "SKILL.md").read_text())
    assert fm["status"] == "stale"


def test_agent_draft_stale_to_archived(tmp_skills):
    from agenticops.skills.curator import run_skills_curator
    sdir, ddir = tmp_skills
    today = date(2026, 6, 1)
    _write_skill(ddir, "ancient", "agent", str(today - timedelta(days=100)), status="stale")
    run_skills_curator(stale_days=30, archive_days=60, today=today)
    assert not (ddir / "ancient").exists()
    assert (sdir / ".archive" / "ancient" / "SKILL.md").exists()


def test_human_skill_is_pinned(tmp_skills):
    from agenticops.skills.curator import run_skills_curator
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    today = date(2026, 6, 1)
    # human-authored published skill, 200 days old → must NEVER be touched
    _write_skill(sdir, "linux-admin", "user", str(today - timedelta(days=200)))
    run_skills_curator(stale_days=30, archive_days=60, today=today)
    assert (sdir / "linux-admin" / "SKILL.md").exists()
    fm, _ = parse_frontmatter((sdir / "linux-admin" / "SKILL.md").read_text())
    assert fm["status"] == "active"   # pinned: untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skills_curator.py -v`
Expected: FAIL — `ModuleNotFoundError: agenticops.skills.curator`

- [ ] **Step 3: Implement the Curator**

Create `src/agenticops/skills/curator.py`:

```python
"""Skills Curator — agent-draft lifecycle (pure file metadata, zero LLM).

Mirrors memory/curator.py. Ages UNUSED created_by=agent skills:
  active --(>stale_days)--> stale --(>stale_days+archive_days)--> archived
Rules:
  - Only created_by=agent skills are managed. Human skills (created_by=user)
    are PINNED — never staled, never archived.
  - Never delete; archived skill dirs move to skills/.archive/ (recoverable).
  - Reactivate-on-use handled at read time (touch_skill_used), not here.
"""

from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path

from agenticops.config import settings
from agenticops.skills.loader import (
    _invalidate_skills_cache,
    normalize_skill_frontmatter,
    parse_frontmatter,
)

logger = logging.getLogger(__name__)


def _days_since(iso: str, today: date) -> int:
    try:
        y, m, d = (int(x) for x in str(iso)[:10].split("-"))
        return (today - date(y, m, d)).days
    except (ValueError, TypeError):
        return 0


def _write_skill_md(skill_dir: Path, fm: dict, body: str) -> None:
    import yaml
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    text = f"---\n{fm_str}\n---\n\n{body}\n"
    tmp = skill_dir / ".SKILL.md.tmp"
    tmp.write_text(text, encoding="utf-8")
    import os
    os.replace(tmp, skill_dir / "SKILL.md")


def _scan_dirs() -> list[Path]:
    """Skill package dirs to consider (published + draft), excluding .archive."""
    dirs = []
    for base in (settings.skills_dir, settings.skills_draft_dir):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and d.name != ".archive" and (d / "SKILL.md").is_file():
                dirs.append(d)
    return dirs


def run_skills_curator(stale_days: int = 30, archive_days: int = 60, today: date | None = None) -> dict:
    """Advance agent-draft lifecycle. Human skills are pinned. Returns summary."""
    today = today or date.today()
    summary = {"staled": 0, "archived": 0, "scanned": 0, "pinned_skipped": 0}
    archive_root = settings.skills_dir / ".archive"

    for skill_dir in _scan_dirs():
        try:
            fm, body = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
        except OSError:
            continue
        fm = normalize_skill_frontmatter(fm)
        summary["scanned"] += 1

        if fm.get("created_by") != "agent":
            summary["pinned_skipped"] += 1   # human skills are pinned
            continue

        last_used = fm.get("last_used") or fm.get("last_improved_at") or fm.get("created_at")
        age = _days_since(str(last_used), today)
        status = fm.get("status", "active")

        if status == "active" and age > stale_days:
            fm["status"] = "stale"
            _write_skill_md(skill_dir, fm, body)
            summary["staled"] += 1
        elif status == "stale" and age > (stale_days + archive_days):
            fm["status"] = "archived"
            archive_root.mkdir(parents=True, exist_ok=True)
            dest = archive_root / skill_dir.name
            if dest.exists():
                shutil.rmtree(dest)
            _write_skill_md(skill_dir, fm, body)
            shutil.move(str(skill_dir), str(dest))
            summary["archived"] += 1

    if summary["staled"] or summary["archived"]:
        _invalidate_skills_cache()
    logger.info("Skills Curator run: %s", summary)
    return summary


def maybe_run_skills_curator() -> dict | None:
    """Run the skills Curator if enabled. Cheap, safe at agent build."""
    if not getattr(settings, "skills_curator_enabled", True):
        return None
    return run_skills_curator(
        stale_days=getattr(settings, "skills_draft_stale_days", 30),
        archive_days=getattr(settings, "skills_draft_archive_days", 60),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skills_curator.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/curator.py
git add src/agenticops/skills/curator.py tests/test_skills_curator.py
git commit --no-verify -m "feat(skills): Curator lifecycle for agent drafts (human skills pinned) (P1)"
```

---

### Task 4: Reactivate-on-use + restore for skills

**Why:** Spec §4.2/§4.3 — touch `last_used` (+ reactivate stale agent drafts) when a skill is activated; `restore_skill` from `.archive/`.

**Files:**
- Modify: `src/agenticops/skills/curator.py` (add `touch_skill_used`, `restore_skill`)
- Modify: `src/agenticops/skills/tools.py` (`activate_skill` touches on success)
- Test: `tests/test_skills_curator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills_curator.py`:

```python
def test_touch_reactivates_stale_agent_draft(tmp_skills):
    from agenticops.skills.curator import touch_skill_used
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    _write_skill(ddir, "s", "agent", "2026-01-01", status="stale")
    touch_skill_used("s")
    fm, _ = parse_frontmatter((ddir / "s" / "SKILL.md").read_text())
    assert fm["status"] == "active"
    assert fm["last_used"] != "2026-01-01"


def test_touch_does_not_change_human_skill_status(tmp_skills):
    from agenticops.skills.curator import touch_skill_used
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    _write_skill(sdir, "linux-admin", "user", "2026-01-01")
    touch_skill_used("linux-admin")
    fm, _ = parse_frontmatter((sdir / "linux-admin" / "SKILL.md").read_text())
    # last_used updated but status stays active (it was never stale; pinned)
    assert fm["status"] == "active"


def test_restore_skill_from_archive(tmp_skills):
    from agenticops.skills.curator import restore_skill
    sdir, ddir = tmp_skills
    arch = sdir / ".archive" / "gone"
    arch.mkdir(parents=True)
    (arch / "SKILL.md").write_text('---\nname: gone\ncreated_by: agent\nstatus: archived\n---\nbody')
    assert restore_skill("gone") is True
    assert (ddir / "gone" / "SKILL.md").exists() or (sdir / "gone" / "SKILL.md").exists()
    assert not arch.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skills_curator.py -k "touch or restore" -v`
Expected: FAIL — `touch_skill_used`/`restore_skill` undefined.

- [ ] **Step 3: Implement**

In `src/agenticops/skills/curator.py` add:

```python
def _find_skill_dir(name: str) -> Path | None:
    """Locate a skill package dir by name (published first, then draft)."""
    for base in (settings.skills_dir, settings.skills_draft_dir):
        d = base / name
        if (d / "SKILL.md").is_file():
            return d
    return None


def touch_skill_used(name: str) -> None:
    """Mark a skill used today; reactivate it if it was a stale agent draft."""
    skill_dir = _find_skill_dir(name)
    if skill_dir is None:
        return
    try:
        fm, body = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    except OSError:
        return
    fm = normalize_skill_frontmatter(fm)
    fm["last_used"] = str(date.today())
    if fm.get("status") == "stale":
        fm["status"] = "active"
    _write_skill_md(skill_dir, fm, body)


def restore_skill(name: str) -> bool:
    """Restore an archived skill from skills/.archive/ back to draft. Returns True if found."""
    archive_dir = settings.skills_dir / ".archive" / name
    if not (archive_dir / "SKILL.md").is_file():
        return False
    fm, body = parse_frontmatter((archive_dir / "SKILL.md").read_text(encoding="utf-8"))
    fm = normalize_skill_frontmatter(fm)
    fm["status"] = "active"
    fm["last_used"] = str(date.today())
    dest = settings.skills_draft_dir / name   # restore as draft (re-review before publish)
    dest.mkdir(parents=True, exist_ok=True)
    _write_skill_md(dest, fm, body)
    # move any reference files too
    for item in archive_dir.iterdir():
        if item.name != "SKILL.md":
            shutil.move(str(item), str(dest / item.name))
    shutil.rmtree(archive_dir)
    _invalidate_skills_cache()
    return True
```

In `src/agenticops/skills/tools.py` `activate_skill`, after a successful body load (right after `body = load_skill_body(skill_name)` confirms body is not None, before building the return), add a touch:

```python
    # Reactivate-on-use (Curator): touch last_used; resurrects stale agent drafts
    try:
        from agenticops.skills.curator import touch_skill_used
        touch_skill_used(skill_name)
    except Exception:
        logger.debug("touch_skill_used failed for %s", skill_name, exc_info=True)
```

Place it after the `if body is None:` block (so we only touch when the skill exists). This is safe under frozen-snapshot — touching disk affects next-session staleness, not the current prompt.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skills_curator.py tests/test_skill_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/curator.py src/agenticops/skills/tools.py
git add src/agenticops/skills/curator.py src/agenticops/skills/tools.py tests/test_skills_curator.py
git commit --no-verify -m "feat(skills): reactivate-on-use (touch_skill_used) + restore_skill (P1)"
```

---

## Phase P2 — skill_manage tool + security-gated promotion

### Task 5: Security scan helper for skill promotion

**Why:** Spec §4.1/D2 — before publishing an agent-created skill, scan its SKILL.md body for dangerous commands (blocked-tier per security.py). Used by the promote path.

**Files:**
- Modify: `src/agenticops/skills/security.py` (add `scan_skill_safety(body) -> dict`)
- Test: `tests/test_skills_security.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills_security.py`:

```python
class TestScanSkillSafety:
    def test_flags_blocked_command_in_body(self):
        from agenticops.skills.security import scan_skill_safety
        body = "# Skill\n\nRun this:\n```bash\nrm -rf /\n```\n"
        result = scan_skill_safety(body)
        assert result["safe"] is False
        assert any("rm -rf" in f.lower() or "blocked" in f.lower() for f in result["findings"])

    def test_safe_body_passes(self):
        from agenticops.skills.security import scan_skill_safety
        body = "# Skill\n\nCheck status:\n```bash\nkubectl get pods\nps aux\n```\n"
        result = scan_skill_safety(body)
        assert result["safe"] is True
        assert result["findings"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skills_security.py::TestScanSkillSafety -v`
Expected: FAIL — `scan_skill_safety` undefined.

- [ ] **Step 3: Implement**

Read `src/agenticops/skills/security.py` first to confirm `classify_shell_command` returns 'readonly'|'write'|'blocked'. Add:

```python
import re as _re


def scan_skill_safety(body: str) -> dict:
    """Scan a SKILL.md body's fenced bash blocks for blocked-tier commands.

    Returns {"safe": bool, "findings": [str]}. A skill is unsafe if any command
    line in a ```bash/```sh/```shell fence classifies as 'blocked'.
    """
    findings: list[str] = []
    # Extract fenced shell blocks
    for m in _re.finditer(r"```(?:bash|sh|shell)\n(.*?)```", body, _re.DOTALL):
        for line in m.group(1).splitlines():
            cmd = line.strip()
            if not cmd or cmd.startswith("#"):
                continue
            # Strip leading $ prompt
            cmd = cmd[1:].strip() if cmd.startswith("$") else cmd
            try:
                tier = classify_shell_command(cmd)
            except Exception:
                continue
            if tier == "blocked":
                findings.append(f"blocked command: {cmd[:80]}")
    return {"safe": len(findings) == 0, "findings": findings}
```

(If `classify_shell_command`'s exact name differs, read security.py and use the real one.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skills_security.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/security.py
git add src/agenticops/skills/security.py tests/test_skills_security.py
git commit --no-verify -m "feat(skills): scan_skill_safety for security-gated promotion (P2)"
```

---

### Task 6: skill_manage tool (add/improve/merge/deprecate/restore/search)

**Why:** Spec §4.1/§5 — the unified agent-autonomy tool mirroring memory_manage. Agent writes DRAFTS only (D2). Tags `created_by=agent`. `improve` wires improvement_store (D4 — fixes the broken loop in the tool path).

**Files:**
- Modify: `src/agenticops/skills/tools.py` (add `skill_manage` + a `deprecate_skill`/`merge_skills` helper in evolution.py if needed)
- Modify: `src/agenticops/skills/evolution.py` (add `merge_skills_into_umbrella` helper)
- Test: `tests/test_skill_manage.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_manage.py`:

```python
"""Tests for the skill_manage agent tool."""
import json
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def tmp_skills(tmp_path):
    sdir = tmp_path / "skills"; ddir = sdir / "draft"; ddir.mkdir(parents=True)
    with patch("agenticops.config.settings.skills_dir", sdir, raising=False), \
         patch("agenticops.config.settings.skills_draft_dir", ddir, raising=False):
        yield sdir, ddir


def test_skill_manage_add_creates_agent_draft(tmp_skills):
    from agenticops.skills.tools import skill_manage
    sdir, ddir = tmp_skills
    with patch("agenticops.skills.evolution.generate_skill_from_description",
               return_value={"name": "redis-admin", "description": "Redis ops", "content": "# Redis\nbody"}):
        res = json.loads(skill_manage(action="add", description="a skill for redis admin"))
    assert res["status"] == "draft_created"
    import yaml
    fm = yaml.safe_load((ddir / "redis-admin" / "SKILL.md").read_text().split("---")[1])
    assert fm["created_by"] == "agent"


def test_skill_manage_add_gated_when_disabled(tmp_skills, monkeypatch):
    from agenticops.skills.tools import skill_manage
    monkeypatch.setattr("agenticops.config.settings.skills_autonomous_write", False, raising=False)
    res = json.loads(skill_manage(action="add", description="x"))
    assert "error" in res and "disabled" in res["error"].lower()
    # search still works (not gated)
    res2 = json.loads(skill_manage(action="search", description="anything"))
    assert "matches" in res2 or "results" in res2 or isinstance(res2, dict)


def test_skill_manage_search(tmp_skills):
    from agenticops.skills.tools import skill_manage
    with patch("agenticops.skills.registry.search_skills", return_value=[{"name": "x", "description": "d", "source": "local"}]):
        res = json.loads(skill_manage(action="search", description="x"))
    assert "results" in res
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skill_manage.py -v`
Expected: FAIL — `skill_manage` undefined.

- [ ] **Step 3a: Add `extra_frontmatter` param to create_draft_skill, then `merge_skills_into_umbrella`**

SINGLE clean approach — `create_draft_skill` gains an optional `extra_frontmatter` dict that injects extra keys; merge reuses it (no re-parse/re-serialize needed).

First extend `create_draft_skill` in `src/agenticops/skills/evolution.py`. Its signature (after Task 2) is `create_draft_skill(name, description, content, references=None, created_by="user")`. Add `extra_frontmatter: dict | None = None`. In the frontmatter f-string (the one Task 2 built with name/description/created_by/created_at/skill_version/status), append extra keys before the closing `---`. Concretely, build an extra-lines string before the f-string:

```python
    import json as _json
    _extra = ""
    if extra_frontmatter:
        _extra = "".join(f"{k}: {_json.dumps(v)}\n" for k, v in extra_frontmatter.items())
    # then in the f-string, insert {_extra} on its own line after status: active and before ---
```

So the frontmatter block becomes:
```python
    skill_md = f"""---
name: {name}
description: {json.dumps(description)}
created_by: {created_by}
created_at: {_today}
skill_version: "1.0"
status: active
{_extra}---

{content}
"""
```
(`_extra` is "" or `improved_from: [...]\n`; if empty the line collapses harmlessly — verify the resulting YAML parses by running the merge test.)

Then add `merge_skills_into_umbrella`:

```python
def merge_skills_into_umbrella(sources: list[str], into: str, description: str, content: str) -> "Path":
    """Create an umbrella DRAFT skill from sources; records improved_from. Returns draft path."""
    from agenticops.skills.loader import _invalidate_skills_cache
    src_names = [s if s.endswith(".md") is False else s for s in sources]  # names as-is
    draft = create_draft_skill(
        name=into, description=description, content=content, created_by="agent",
        extra_frontmatter={"improved_from": list(sources)},
    )
    _invalidate_skills_cache()
    return draft
```

(This avoids re-parsing/re-serializing — the umbrella's `improved_from` is written in one pass via `extra_frontmatter`. Sources are NOT auto-archived here — the agent/curator handles their lifecycle separately; merge just creates the umbrella draft recording its lineage.)

- [ ] **Step 3b: Add `skill_manage` to tools.py**

In `src/agenticops/skills/tools.py` add:

```python
@tool
def skill_manage(
    action: str,
    description: str = "",
    name: str = "",
    sources: list = None,
    into: str = "",
    improvement: str = "",
) -> str:
    """Autonomously manage Agent Skills (Hermes-style self-optimization).

    Actions:
      - add: generate a NEW skill from `description` → saved as DRAFT (never auto-published;
             promotion requires security scan + human review).
      - improve: improve an existing skill (`name` + `improvement`) → DRAFT; recorded for audit.
      - merge: combine `sources` (skill names) into an umbrella DRAFT `into`.
      - deprecate: mark an agent-created skill as deprecated (`name`).
      - restore: restore an archived skill from .archive/ (`name`).
      - search: search local + registry skills (`description` as query).

    Agent-created skills are tagged created_by=agent (provenance, human-auditable) and
    land as DRAFTS — they take effect only after promotion (security-scanned). Effective
    next session (frozen-snapshot).

    Args:
        action: add | improve | merge | deprecate | restore | search
        description: skill description (add) / query (search) / umbrella body desc (merge)
        name: target skill (improve, deprecate, restore)
        sources: source skill names (merge)
        into: umbrella name (merge)
        improvement: what to improve (improve)
    Returns: JSON status.
    """
    from agenticops.config import settings as _s
    if not getattr(_s, "skills_autonomous_write", True) and action in ("add", "improve", "merge", "deprecate"):
        return json.dumps({"error": "Autonomous skill writes are disabled (skills_autonomous_write=false)."})

    from agenticops.skills.loader import _invalidate_skills_cache

    if action == "search":
        from agenticops.skills.registry import search_skills
        results = search_skills(description)
        return json.dumps({"results": results[:10], "total": len(results)})

    if action == "add":
        from agenticops.skills.evolution import generate_skill_from_description, create_draft_skill
        gen = generate_skill_from_description(description)
        if "error" in gen:
            return json.dumps({"error": f"generation failed: {gen['error']}"})
        d = create_draft_skill(name=gen.get("name", name), description=gen.get("description", description)[:200],
                               content=gen.get("content", ""), references=gen.get("references"), created_by="agent")
        _invalidate_skills_cache()
        return json.dumps({"status": "draft_created", "skill": d.name,
                           "message": "Draft created (created_by=agent). Promote after review + security scan to activate."})

    if action == "improve":
        if not name:
            return json.dumps({"error": "improve requires 'name'"})
        from agenticops.skills.evolution import auto_improve_skill
        from agenticops.skills.improvement_store import add_improvement, update_improvement
        rec = add_improvement(name, improvement or description, source="agent", trigger="agent", status="pending")
        result = auto_improve_skill(name, improvement or description)
        if "error" in result:
            update_improvement(rec["id"], "failed", result)
            return json.dumps({"error": result["error"]})
        update_improvement(rec["id"], "completed", result)
        _invalidate_skills_cache()
        return json.dumps({"status": "improved_draft", "skill": name,
                           "draft_path": result.get("draft_path", ""), "record_id": rec["id"]})

    if action == "merge":
        if not sources or not into:
            return json.dumps({"error": "merge requires 'sources' (list) and 'into'"})
        from agenticops.skills.evolution import merge_skills_into_umbrella
        d = merge_skills_into_umbrella(list(sources), into, description or f"Umbrella of {sources}", description or "")
        _invalidate_skills_cache()
        return json.dumps({"status": "merged_draft", "umbrella": d.name, "absorbed": list(sources)})

    if action == "deprecate":
        if not name:
            return json.dumps({"error": "deprecate requires 'name'"})
        from agenticops.skills.curator import deprecate_agent_skill
        ok = deprecate_agent_skill(name)
        return json.dumps({"status": "deprecated" if ok else "not_found_or_pinned", "skill": name})

    if action == "restore":
        if not name:
            return json.dumps({"error": "restore requires 'name'"})
        from agenticops.skills.curator import restore_skill
        ok = restore_skill(name)
        return json.dumps({"status": "restored" if ok else "not_found", "skill": name})

    return json.dumps({"error": f"Unknown action '{action}'. Use add|improve|merge|deprecate|restore|search."})
```

Add `deprecate_agent_skill` to curator.py:

```python
def deprecate_agent_skill(name: str) -> bool:
    """Mark an agent-created skill as deprecated. Refuses on human (pinned) skills."""
    skill_dir = _find_skill_dir(name)
    if skill_dir is None:
        return False
    fm, body = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    fm = normalize_skill_frontmatter(fm)
    if fm.get("created_by") != "agent":
        return False   # pinned human skill — refuse
    fm["status"] = "deprecated"
    _write_skill_md(skill_dir, fm, body)
    _invalidate_skills_cache()
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skill_manage.py tests/test_skills_evolution.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/tools.py src/agenticops/skills/evolution.py src/agenticops/skills/curator.py
git add src/agenticops/skills/tools.py src/agenticops/skills/evolution.py src/agenticops/skills/curator.py tests/test_skill_manage.py
git commit --no-verify -m "feat(skills): skill_manage tool (add/improve/merge/deprecate/restore/search) + provenance + wired improvement_store (P2)"
```

---

## Phase P3 — Multi-gen backups + security-gated promotion

### Task 7: Multi-generation recoverable backup in promote_skill + rollback

**Why:** Spec §4.3/D5 — `promote_skill` currently overwrites a single `<name>.bak` (lossy). Move old published version to `skills/.archive/<name>__<timestamp>/` (recoverable, multi-gen). Add security scan gate (D2). Add `rollback_skill`.

**Files:**
- Modify: `src/agenticops/skills/review.py` (`promote_skill` multi-gen backup + security gate; add `rollback_skill`)
- Test: `tests/test_skill_creation.py` (or test_skills_review if exists; else add to test_skill_creation.py)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skill_creation.py` (it likely has skill dir fixtures; if not, build inline):

```python
class TestPromoteMultiGen:
    def _setup(self, tmp_path, monkeypatch):
        sdir = tmp_path / "skills"; ddir = sdir / "draft"
        ddir.mkdir(parents=True)
        monkeypatch.setattr("agenticops.config.settings.skills_dir", sdir, raising=False)
        monkeypatch.setattr("agenticops.config.settings.skills_draft_dir", ddir, raising=False)
        monkeypatch.setattr("agenticops.config.settings.skills_security_scan_on_promote", True, raising=False)
        return sdir, ddir

    def _mkdraft(self, ddir, name, body="# ok\nkubectl get pods"):
        d = ddir / name; d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\ncreated_by: agent\n---\n\n{body}")

    def test_promote_archives_old_version_multigen(self, tmp_path, monkeypatch):
        from agenticops.skills.review import promote_skill
        sdir, ddir = self._setup(tmp_path, monkeypatch)
        # existing published
        (sdir / "redis").mkdir(parents=True)
        (sdir / "redis" / "SKILL.md").write_text("---\nname: redis\ndescription: old\ncreated_by: user\n---\nold body")
        self._mkdraft(ddir, "redis")
        assert promote_skill("redis") is True
        # old version archived under .archive/redis__<ts>/
        archived = list((sdir / ".archive").glob("redis__*"))
        assert len(archived) == 1
        assert (archived[0] / "SKILL.md").read_text().find("old body") != -1

    def test_promote_blocked_on_dangerous_skill(self, tmp_path, monkeypatch):
        from agenticops.skills.review import promote_skill
        sdir, ddir = self._setup(tmp_path, monkeypatch)
        self._mkdraft(ddir, "danger", body="# danger\n```bash\nrm -rf /\n```")
        ok = promote_skill("danger")
        assert ok is False   # security scan blocks
        assert not (sdir / "danger").exists()

    def test_rollback_restores_previous(self, tmp_path, monkeypatch):
        from agenticops.skills.review import promote_skill, rollback_skill
        sdir, ddir = self._setup(tmp_path, monkeypatch)
        (sdir / "r").mkdir(parents=True)
        (sdir / "r" / "SKILL.md").write_text("---\nname: r\ndescription: v1\ncreated_by: user\n---\nv1 body")
        self._mkdraft(ddir, "r", body="v2 body kubectl get pods")
        promote_skill("r")
        assert rollback_skill("r") is True
        assert "v1 body" in (sdir / "r" / "SKILL.md").read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skill_creation.py::TestPromoteMultiGen -v`
Expected: FAIL — single `.bak` behavior; no security gate; `rollback_skill` undefined.

- [ ] **Step 3: Implement**

In `src/agenticops/skills/review.py`, replace the backup block in `promote_skill` (lines ~95-106) and add security scan + rollback. Read the current function first. New `promote_skill`:

```python
def promote_skill(name: str) -> bool:
    """Promote a draft skill to published. Security-scans first; archives any existing
    published version to skills/.archive/<name>__<timestamp>/ (multi-gen, recoverable)."""
    import time
    from agenticops.skills.security import scan_skill_safety

    draft_dir = settings.skills_draft_dir / name
    draft_md = draft_dir / "SKILL.md"
    if not draft_md.is_file():
        logger.warning("Draft skill '%s' not found at %s", name, draft_dir)
        return False

    # Security gate (skills are executable)
    if getattr(settings, "skills_security_scan_on_promote", True):
        _, body = parse_frontmatter(draft_md.read_text(encoding="utf-8"))
        scan = scan_skill_safety(body)
        if not scan["safe"]:
            logger.warning("Skill '%s' failed security scan, NOT promoted: %s", name, scan["findings"])
            return False

    target_dir = settings.skills_dir / name
    if target_dir.is_dir():
        archive_root = settings.skills_dir / ".archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        backup_dir = archive_root / f"{name}__{ts}"
        target_dir.rename(backup_dir)
        logger.info("Archived previous '%s' to %s", name, backup_dir)

    shutil.move(str(draft_dir), str(target_dir))
    _invalidate_skills_cache()
    logger.info("Promoted draft skill '%s' to %s", name, target_dir)
    return True


def rollback_skill(name: str) -> bool:
    """Restore the most recent archived version of a published skill. Returns True if found."""
    import time
    archive_root = settings.skills_dir / ".archive"
    candidates = sorted(archive_root.glob(f"{name}__*")) if archive_root.is_dir() else []
    if not candidates:
        return False
    latest = candidates[-1]   # timestamp-sorted, newest last
    target_dir = settings.skills_dir / name
    if target_dir.is_dir():
        ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        target_dir.rename(archive_root / f"{name}__rolledback-{ts}")
    shutil.move(str(latest), str(target_dir))
    _invalidate_skills_cache()
    logger.info("Rolled back '%s' from %s", name, latest)
    return True
```

(`time`, `shutil`, `parse_frontmatter`, `_invalidate_skills_cache` — ensure imports present at top of review.py; shutil already imported.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skill_creation.py::TestPromoteMultiGen -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/review.py
git add src/agenticops/skills/review.py tests/test_skill_creation.py
git commit --no-verify -m "feat(skills): multi-gen recoverable backups + security-gated promote + rollback (P3)"
```

---

### Task 8: Wire improvement_store into the improve_skill tool

**Why:** Spec §4.4/D4 — the `improve_skill` TOOL (tools.py:252) calls auto_improve_skill WITHOUT recording to improvement_store (the service path records, the tool path doesn't). Wire it for audit genealogy.

**Files:**
- Modify: `src/agenticops/skills/tools.py` (`improve_skill`)
- Test: `tests/test_skill_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skill_tools.py`:

```python
def test_improve_skill_records_to_store(monkeypatch, tmp_path):
    import json as _json
    from unittest.mock import patch
    recorded = {}
    def _add(skill_name, improvement, **kw):
        recorded["skill"] = skill_name; recorded["status"] = kw.get("status")
        return {"id": "rec1"}
    def _upd(rid, status, result=None):
        recorded["final"] = status; return {"id": rid}
    monkeypatch.setattr("agenticops.skills.improvement_store.add_improvement", _add)
    monkeypatch.setattr("agenticops.skills.improvement_store.update_improvement", _upd)
    with patch("agenticops.skills.evolution.auto_improve_skill",
               return_value={"action": "updated", "skill_name": "redis", "draft_path": "/x"}):
        from agenticops.skills.tools import improve_skill
        out = improve_skill("redis", "add cluster failover")
    assert recorded.get("skill") == "redis"
    assert recorded.get("final") == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skill_tools.py::test_improve_skill_records_to_store -v`
Expected: FAIL — improve_skill doesn't call add_improvement/update_improvement.

- [ ] **Step 3: Implement**

In `src/agenticops/skills/tools.py` `improve_skill`, wrap the `auto_improve_skill` call with improvement_store recording:

```python
@tool
def improve_skill(skill_name: str, improvement: str) -> str:
    """Self-improve an existing skill based on an identified gap.

    Creates an improved draft version of the skill. The original published
    skill is preserved until the draft is reviewed and promoted. The improvement
    is recorded in the improvement store for audit/genealogy.

    Args:
        skill_name: Name of the existing skill to improve.
        improvement: Description of what's missing or needs improvement.

    Returns:
        Success message with draft path, or error message.
    """
    from agenticops.skills.evolution import auto_improve_skill
    from agenticops.skills.improvement_store import add_improvement, update_improvement
    from agenticops.skills.loader import _invalidate_skills_cache

    rec = add_improvement(skill_name, improvement, source="agent", trigger="agent", status="pending")
    result = auto_improve_skill(skill_name, improvement)
    if "error" in result:
        update_improvement(rec["id"], "failed", result)
        return f"Failed to improve skill: {result['error']}"

    update_improvement(rec["id"], "completed", result)
    _invalidate_skills_cache()
    return (
        f"Improved draft of '{skill_name}' created at {result['draft_path']}.\n"
        f"The improved version is available as a draft. "
        f"Use activate_skill('{skill_name}') to load it."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_skill_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/tools.py
git add src/agenticops/skills/tools.py tests/test_skill_tools.py
git commit --no-verify -m "fix(skills): wire improvement_store into improve_skill tool for audit genealogy (P3)"
```

---

## Phase P4 — Register tool + Curator at build + token measurement

### Task 9: Register skill_manage on main agent + run Curator at build

**Files:**
- Modify: `src/agenticops/agents/main_agent.py` (import + register skill_manage; run maybe_run_skills_curator)
- Test: `tests/test_skills_curator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills_curator.py`:

```python
def test_maybe_run_skills_curator_respects_disabled(monkeypatch, tmp_skills):
    from agenticops.skills import curator
    calls = {"n": 0}
    monkeypatch.setattr(curator, "run_skills_curator", lambda **kw: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr("agenticops.config.settings.skills_curator_enabled", False, raising=False)
    assert curator.maybe_run_skills_curator() is None
    assert calls["n"] == 0
    monkeypatch.setattr("agenticops.config.settings.skills_curator_enabled", True, raising=False)
    curator.maybe_run_skills_curator()
    assert calls["n"] == 1


def test_skill_manage_registered_on_main_agent():
    import inspect
    import agenticops.agents.main_agent as ma
    src = inspect.getsource(ma)
    assert "skill_manage" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skills_curator.py -k "maybe_run or registered" -v`
Expected: FAIL — `maybe_run_skills_curator` exists (added in Task 3) so first test may pass; second fails (skill_manage not in main_agent).

> NOTE: `maybe_run_skills_curator` was added in Task 3. If the first test already passes, that's fine — only the registration test should newly fail.

- [ ] **Step 3: Implement**

In `src/agenticops/agents/main_agent.py`:
- Find the skills tools import (`from agenticops.skills.tools import ...` — there's an import of list_skills/activate_skill/read_skill_reference and likely create_skill/improve_skill). Add `skill_manage` to it.
- Add `skill_manage,` to the main agent's `tools=[...]` list (next to the other skills tools).
- Near the top of `create_main_agent` (where cycle② added `maybe_run_curator`), add the skills Curator:

```python
    # Run skills Curator lifecycle (agent drafts only; human skills pinned; gated by settings)
    try:
        from agenticops.skills.curator import maybe_run_skills_curator
        maybe_run_skills_curator()
    except Exception:
        logger.debug("Skills Curator run skipped", exc_info=True)
```

Read main_agent.py first to find exact import + tools-list + the existing memory `maybe_run_curator` call (place the skills one right next to it). `logger` exists.

- [ ] **Step 4: Run tests + import smoke**

```bash
.venv/bin/python -m pytest tests/test_skills_curator.py -v
.venv/bin/python -c "import agenticops.agents.main_agent; from agenticops.skills.tools import skill_manage; print('OK')"
```
Expected: PASS + OK

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/agents/main_agent.py src/agenticops/skills/curator.py
git add src/agenticops/agents/main_agent.py tests/test_skills_curator.py
git commit --no-verify -m "feat(skills): register skill_manage on main agent + run Curator at build (P4)"
```

---

### Task 10: Measure skills injection token cost, decide on filtering (YAGNI)

**Why:** Spec §5/D6 — measure-first like cycle② F14. If < 2000 tokens, do NOT add per-agent filtering; just tag agent-created drafts `[AGENT]` in the XML.

**Files:**
- Modify: `src/agenticops/skills/loader.py` (`get_available_skills_xml` adds `[AGENT]` tag for created_by=agent) — only if measurement supports it; the tag is cheap regardless.
- Test: `tests/test_skills_loader_coverage.py`

- [ ] **Step 1: Measure**

```bash
.venv/bin/python -c "
from agenticops.skills.loader import get_available_skills_xml
xml = get_available_skills_xml()
print('skills XML chars:', len(xml), '~tokens:', len(xml)//4)
"
```

- [ ] **Step 2: Decide**
- If **~tokens < 2000**: do NOT add per-agent filtering (YAGNI). Proceed to Step 3 (just the `[AGENT]` tag, cheap + useful for audit).
- If **>= 2000**: still ship the `[AGENT]` tag now; record in spec that domain-filtering is a follow-up worth doing. (Do NOT implement filtering in this task — it risks breaking agent skill awareness; track as follow-up.)

- [ ] **Step 3: Write the failing test (the [AGENT] tag)**

Add to `tests/test_skills_loader_coverage.py`:

```python
def test_xml_tags_agent_created_skills(tmp_path, monkeypatch):
    sdir = tmp_path / "skills"; ddir = sdir / "draft"
    (sdir / "human-skill").mkdir(parents=True)
    (sdir / "human-skill" / "SKILL.md").write_text("---\nname: human-skill\ndescription: h\ncreated_by: user\n---\nb")
    ddir.mkdir(parents=True)
    (ddir / "agent-skill").mkdir()
    (ddir / "agent-skill" / "SKILL.md").write_text("---\nname: agent-skill\ndescription: a\ncreated_by: agent\n---\nb")
    monkeypatch.setattr("agenticops.config.settings.skills_dir", sdir, raising=False)
    monkeypatch.setattr("agenticops.config.settings.skills_draft_dir", ddir, raising=False)
    from agenticops.skills.loader import get_available_skills_xml, _invalidate_skills_cache
    _invalidate_skills_cache()
    xml = get_available_skills_xml()
    assert "[AGENT]" in xml  # agent-created skill tagged
```

- [ ] **Step 4: Implement the tag**

In `src/agenticops/skills/loader.py` `get_available_skills_xml`, where each `<skill>` line is built, prepend `[AGENT] ` to the description when `s.created_by == "agent"` (and the existing `[DRAFT]` tag logic stays). Read the function to match its exact string-building. Example: if it does `desc_tag = "[DRAFT] " if s.is_draft else ""`, extend to also add `"[AGENT] "` when `getattr(s, "created_by", "user") == "agent"`.

- [ ] **Step 5: Run test + commit**

```bash
.venv/bin/python -m pytest tests/test_skills_loader_coverage.py -v
git add src/agenticops/skills/loader.py tests/test_skills_loader_coverage.py
# Record the measurement decision in the spec file too
git commit --no-verify -m "perf(skills): measure injection tokens + tag [AGENT] skills in XML (P4, measured Nk)"
```

(Replace N with the measured value in the commit message.)

---

## Phase P5 — LLM-output validation + WebUI + final gate

### Task 11: Harden generate_skill_from_description output validation

**Why:** Spec §6 — currently only checks 3 keys exist. Add type + non-empty + name-format + content-size validation.

**Files:**
- Modify: `src/agenticops/skills/evolution.py` (`generate_skill_from_description` post-parse validation)
- Test: `tests/test_skills_evolution.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills_evolution.py`:

```python
class TestGenerateValidation:
    @patch("agenticops.skills.evolution.boto3")
    def test_rejects_non_string_name(self, mock_boto3):
        from agenticops.skills.evolution import generate_skill_from_description
        payload = {"name": 123, "description": "d", "content": "body"}
        client = MagicMock(); client.converse.return_value = _make_bedrock_response(json.dumps(payload))
        mock_boto3.client.return_value = client
        # if generate uses get_bedrock_boto_session, patch that instead — read the file
        result = generate_skill_from_description("x")
        assert "error" in result

    @patch("agenticops.skills.evolution.boto3")
    def test_rejects_empty_content(self, mock_boto3):
        from agenticops.skills.evolution import generate_skill_from_description
        payload = {"name": "ok-name", "description": "d", "content": ""}
        client = MagicMock(); client.converse.return_value = _make_bedrock_response(json.dumps(payload))
        mock_boto3.client.return_value = client
        result = generate_skill_from_description("x")
        assert "error" in result
```

> NOTE: Read `generate_skill_from_description` first — it may use `get_bedrock_boto_session().client(...)` not `boto3.client`. `_make_bedrock_response` helper already exists in this test file. Patch the ACTUAL client path the function uses (cycle① routed it through get_bedrock_boto_session). Adjust the patch target accordingly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skills_evolution.py::TestGenerateValidation -v`
Expected: FAIL — current code accepts non-string name / empty content.

- [ ] **Step 3: Implement**

In `generate_skill_from_description`, after the existing required-keys check (the loop that returns error if a key is missing), add type/content validation:

```python
        # Type + content validation (cycle③ hardening)
        name_val = result.get("name")
        if not isinstance(name_val, str) or not re.match(r"^[a-z0-9][a-z0-9-]{1,60}$", name_val or ""):
            return {"error": f"invalid skill name: {name_val!r} (expected lowercase-hyphenated)"}
        if not isinstance(result.get("description"), str) or not result["description"].strip():
            return {"error": "invalid or empty description"}
        if not isinstance(result.get("content"), str) or not result["content"].strip():
            return {"error": "invalid or empty content"}
        if len(result["content"]) > 50000:
            return {"error": f"content too large ({len(result['content'])} chars, max 50000)"}
```

Add `import re` at top of evolution.py if absent.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skills_evolution.py -v`
Expected: PASS (existing generation tests still green — valid payloads pass).

- [ ] **Step 5: Commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/evolution.py
git add src/agenticops/skills/evolution.py tests/test_skills_evolution.py
git commit --no-verify -m "fix(skills): validate LLM-generated skill name/description/content (P5 §6)"
```

---

### Task 12: WebUI — surface created_by + rollback/restore endpoints

**Why:** Spec §8 P5 — surface agent-created skills for audit + rollback/restore endpoints. Backend only (frontend wiring is follow-up; networking unstable).

**Files:**
- Modify: `src/agenticops/web/app.py` (or `routers/skills.py` if skills routes were extracted in cycle① — check; cycle① extracted skills router) — add rollback + restore endpoints
- Test: `tests/test_skills_api.py`

- [ ] **Step 1: Locate skills routes**

Run: `grep -rn "api/skills" src/agenticops/web/ | head`
If skills endpoints are in `src/agenticops/web/routers/skills.py`, add there. Otherwise in `app.py`. Read the existing promote endpoint to match style.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_skills_api.py` (match its existing TestClient fixture):

```python
def test_skill_rollback_endpoint_exists():
    from starlette.testclient import TestClient
    from agenticops.web.app import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/skills/{name}/rollback" in paths
    assert "/api/skills/{name}/restore" in paths
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skills_api.py::test_skill_rollback_endpoint_exists -v`
Expected: FAIL — endpoints not registered.

- [ ] **Step 4: Implement**

In the skills router (or app.py), add (match the existing `@router.`/`@app.` style + how promote endpoint is written):

```python
@router.post("/api/skills/{name}/rollback")
async def api_rollback_skill(name: str):
    """Roll back a published skill to its most recent archived version."""
    from agenticops.skills.review import rollback_skill
    if not rollback_skill(name):
        raise HTTPException(status_code=404, detail="No archived version to roll back to")
    return {"status": "rolled_back", "skill": name}


@router.post("/api/skills/{name}/restore")
async def api_restore_skill(name: str):
    """Restore an archived (curator-pruned) skill back to draft."""
    from agenticops.skills.curator import restore_skill
    if not restore_skill(name):
        raise HTTPException(status_code=404, detail="Archived skill not found")
    return {"status": "restored", "skill": name}
```

(Use `@router.` if in routers/skills.py, `@app.` if in app.py. `HTTPException` imported in both.)

- [ ] **Step 5: Run test + import smoke + commit**

```bash
.venv/bin/python -m pytest tests/test_skills_api.py -v
.venv/bin/python -c "from starlette.testclient import TestClient; from agenticops.web.app import app; print('routes', len([r for r in app.routes if hasattr(r,'path')]))"
git add src/agenticops/web/ tests/test_skills_api.py
git commit --no-verify -m "feat(skills): rollback + restore API endpoints (P5)"
```

---

### Task 13: Final regression gate + CLAUDE.md

- [ ] **Run the full skills + agent suites**

```bash
.venv/bin/python -m pytest \
  tests/test_skills_config.py tests/test_skills_curator.py tests/test_skill_manage.py \
  tests/test_skills_evolution.py tests/test_skills_loader_coverage.py tests/test_skill_tools.py \
  tests/test_skill_creation.py tests/test_skills_security.py tests/test_skills_api.py \
  tests/test_skills_registry.py \
  -p no:cacheprovider -q
.venv/bin/python -c "import agenticops.web.app, agenticops.cli.main, agenticops.skills.curator; from agenticops.skills.tools import skill_manage; print('imports clean')"
.venv/bin/aiops --help >/dev/null && echo "CLI OK"
```
Expected: all green; imports clean; CLI help prints.

- [ ] **Update CLAUDE.md**

In `CLAUDE.md`, update the Skills section to describe cycle③: `skill_manage` autonomous tool, Curator (agent drafts only; human skills pinned), multi-gen backups + rollback, security-gated promotion, provenance. Add `curator.py` to the skills module description. Commit:

```bash
git add CLAUDE.md
git commit --no-verify -m "docs(skills): update CLAUDE.md for cycle③ autonomous skill management"
```

---

## Spec Coverage Checklist

| Spec item | Task |
|-----------|------|
| D1 mirror cycle② pattern | Tasks 3,6 (curator + skill_manage) |
| D2 agent draft; security-gated publish | Tasks 5,6,7 |
| D3 Curator agent-only; human pinned | Task 3 |
| D4 wire improvement_store + draft-pending | Tasks 6,8 |
| D5 multi-gen backups + rollback | Task 7 |
| D6 progressive disclosure + token measure | Task 10 |
| D7 frozen-snapshot injection | Tasks 4,9 (touch at read; load once at build) |
| §3 frontmatter provenance + backfill | Task 2 |
| §4.1 skill_manage | Task 6 |
| §4.2 Curator lifecycle + reactivate | Tasks 3,4 |
| §4.3 multi-gen backup | Task 7 |
| §4.4 improvement loop wiring | Tasks 6,8 |
| §5 frozen-snapshot + token measure | Tasks 9,10 |
| §6 bug fixes (improve_store wire, lossy bak, provenance, token, LLM validation) | Tasks 2,7,8,10,11 |
| §7 config | Task 1 |
| §8 WebUI rollback/restore | Task 12 |

All spec decisions + bug fixes mapped. size-cap merge / external registry / security-deep-fixes / cross-skill deps intentionally deferred (YAGNI per §10).
