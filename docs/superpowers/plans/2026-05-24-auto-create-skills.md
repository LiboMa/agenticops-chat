# Auto-Create Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When no matching skill exists, Agent asks user for confirmation then auto-generates, publishes, and activates the skill in one shot.

**Architecture:** Modify `create_skill` tool to support `publish=True` (writes to `skills/` not `skills/draft/`) and auto-activate after creation. Modify `activate_skill` to return guidance when skill not found. Add creation guidance to `SKILLS_USAGE_PROTOCOL`.

**Tech Stack:** Python (Strands SDK `@tool`), boto3 Bedrock, existing skill loader.

---

### Task 1: Add `create_published_skill` to evolution.py

**Files:**
- Modify: `src/agenticops/skills/evolution.py:22-60`
- Test: `tests/test_skill_creation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_creation.py
import shutil
from pathlib import Path
from unittest.mock import patch

from agenticops.skills.evolution import create_published_skill


def test_create_published_skill_writes_to_skills_dir(tmp_path):
    """Published skill lands in skills_dir, not draft_dir."""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()

    with patch("agenticops.skills.evolution.settings") as mock_settings:
        mock_settings.skills_dir = skill_dir

        path = create_published_skill(
            name="redis-admin",
            description="Redis troubleshooting skill",
            content="# Redis Admin\n\nDiagnostic procedures...",
            references={"troubleshooting.md": "## Steps\n..."},
        )

    assert path == skill_dir / "redis-admin"
    assert (path / "SKILL.md").is_file()
    assert "redis-admin" in (path / "SKILL.md").read_text()
    assert (path / "references" / "troubleshooting.md").is_file()

    # Cleanup
    shutil.rmtree(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_creation.py::test_create_published_skill_writes_to_skills_dir -v`
Expected: FAIL with `ImportError` or `AttributeError` (function doesn't exist yet)

- [ ] **Step 3: Write minimal implementation**

Add to `src/agenticops/skills/evolution.py` after `create_draft_skill`:

```python
def create_published_skill(
    name: str,
    description: str,
    content: str,
    references: Optional[dict[str, str]] = None,
) -> Path:
    """Write a new SKILL.md directly to the published skills directory.

    Same as create_draft_skill but targets skills_dir (production).
    Used when user has confirmed skill creation.

    Args:
        name: Skill name (used as directory name).
        description: Short description for YAML frontmatter.
        content: Full SKILL.md body content (after frontmatter).
        references: Optional dict of {filename: content} for references/ files.

    Returns:
        Path to the created skill directory.
    """
    pub_dir = settings.skills_dir / name
    pub_dir.mkdir(parents=True, exist_ok=True)

    skill_md = f"""---
name: {name}
description: "{description}"
---

{content}
"""
    (pub_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    if references:
        refs_dir = pub_dir / "references"
        refs_dir.mkdir(exist_ok=True)
        for filename, ref_content in references.items():
            (refs_dir / filename).write_text(ref_content, encoding="utf-8")

    logger.info("Created published skill '%s' at %s", name, pub_dir)
    return pub_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_creation.py::test_create_published_skill_writes_to_skills_dir -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/skills/evolution.py tests/test_skill_creation.py
git commit -m "feat(skills): add create_published_skill for confirmed auto-creation"
```

---

### Task 2: Modify `create_skill` tool to support publish + auto-activate

**Files:**
- Modify: `src/agenticops/skills/tools.py:162-194`
- Test: `tests/test_skill_creation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_creation.py (append)
from unittest.mock import patch, MagicMock


def test_create_skill_tool_with_publish_true(tmp_path):
    """create_skill with publish=True writes to skills_dir and returns activated content."""
    from agenticops.skills.tools import create_skill

    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()

    mock_generate_result = {
        "name": "redis-admin",
        "description": "Redis troubleshooting",
        "content": "# Redis\n\n## Decision Tree\n...",
        "references": {},
    }

    with patch("agenticops.skills.evolution.generate_skill_from_description", return_value=mock_generate_result), \
         patch("agenticops.skills.evolution.settings") as mock_settings, \
         patch("agenticops.skills.loader._invalidate_skills_cache"):
        mock_settings.skills_dir = skill_dir
        mock_settings.skills_draft_dir = tmp_path / "draft"

        result = create_skill.tool_function(
            name="redis-admin",
            description="Redis cluster troubleshooting",
            publish=True,
        )

    assert "redis-admin" in result
    assert "<activated_skill" in result
    assert "Decision Tree" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_creation.py::test_create_skill_tool_with_publish_true -v`
Expected: FAIL — `create_skill` doesn't accept `publish` parameter yet

- [ ] **Step 3: Update create_skill tool**

Replace the `create_skill` function in `src/agenticops/skills/tools.py`:

```python
@tool
def create_skill(name: str, description: str, publish: bool = False) -> str:
    """Create a new skill by generating content from a description.

    Uses LLM to generate a complete SKILL.md with decision trees, diagnostic
    procedures, and command references.

    When publish=True (user confirmed), the skill is saved directly to the
    published skills directory and immediately activated. When publish=False,
    it is saved as a draft.

    IMPORTANT: Always ask the user for confirmation before calling with publish=True.

    Args:
        name: Skill name (lowercase, hyphenated, e.g., 'redis-admin').
        description: Natural language description of what the skill should cover.
        publish: If True, save as published and auto-activate. Default False (draft).

    Returns:
        Success message with activated skill content (if publish=True), or draft path.
    """
    from agenticops.skills.evolution import (
        generate_skill_from_description,
        create_draft_skill,
        create_published_skill,
    )
    from agenticops.skills.loader import _invalidate_skills_cache, load_skill_body

    result = generate_skill_from_description(description)
    if "error" in result:
        return f"Failed to generate skill: {result['error']}"

    skill_name = result.get("name", name)
    skill_desc = result.get("description", description)[:200]
    skill_content = result.get("content", "")
    skill_refs = result.get("references")

    if publish:
        create_published_skill(
            name=skill_name,
            description=skill_desc,
            content=skill_content,
            references=skill_refs,
        )
    else:
        create_draft_skill(
            name=skill_name,
            description=skill_desc,
            content=skill_content,
            references=skill_refs,
        )

    _invalidate_skills_cache()

    if publish:
        # Auto-activate: return skill body directly
        body = load_skill_body(skill_name)
        if body:
            return (
                f"Skill '{skill_name}' created and published.\n\n"
                f'<activated_skill name="{skill_name}">\n{body}\n</activated_skill>\n\n'
                f"Skill is now active and ready to use."
            )

    return (
        f"Draft skill '{skill_name}' created.\n"
        f"It is now available — use activate_skill('{skill_name}') to load it."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_creation.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/skills/tools.py tests/test_skill_creation.py
git commit -m "feat(skills): create_skill supports publish=True with auto-activate"
```

---

### Task 3: Modify `activate_skill` to guide creation when not found

**Files:**
- Modify: `src/agenticops/skills/tools.py:66-135`
- Test: `tests/test_skill_creation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_creation.py (append)
def test_activate_skill_not_found_suggests_creation():
    """activate_skill returns guidance to create when skill not found."""
    from agenticops.skills.tools import activate_skill

    with patch("agenticops.skills.tools.load_skill_body", return_value=None), \
         patch("agenticops.skills.tools.discover_skills", return_value=[]):
        result = activate_skill.tool_function(skill_name="redis-admin")

    assert "not found" in result.lower()
    assert "create_skill" in result
    assert "redis-admin" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_creation.py::test_activate_skill_not_found_suggests_creation -v`
Expected: FAIL — current message says "not found" but doesn't mention `create_skill`

- [ ] **Step 3: Update activate_skill not-found response**

In `src/agenticops/skills/tools.py`, replace the not-found block inside `activate_skill`:

```python
    body = load_skill_body(skill_name)
    if body is None:
        skills = discover_skills()
        available = ", ".join(s.name for s in skills)
        return (
            f"Skill '{skill_name}' not found.\n"
            f"Available skills: {available or '(none)'}\n\n"
            f"If no existing skill covers this domain, you can create one:\n"
            f"1. Ask the user: \"I don't have a skill for '{skill_name}'. Should I create one?\"\n"
            f"2. If confirmed, call: create_skill(name=\"{skill_name}\", "
            f"description=\"<what it should cover>\", publish=True)"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_creation.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/skills/tools.py tests/test_skill_creation.py
git commit -m "feat(skills): activate_skill guides Agent to create missing skills"
```

---

### Task 4: Update SKILLS_USAGE_PROTOCOL in preamble.py

**Files:**
- Modify: `src/agenticops/agents/preamble.py:27-36`
- Test: `tests/test_skill_creation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_creation.py (append)
def test_skills_protocol_mentions_creation():
    """SKILLS_USAGE_PROTOCOL includes guidance about creating new skills."""
    from agenticops.agents.preamble import SKILLS_USAGE_PROTOCOL

    assert "create_skill" in SKILLS_USAGE_PROTOCOL
    assert "confirm" in SKILLS_USAGE_PROTOCOL.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_creation.py::test_skills_protocol_mentions_creation -v`
Expected: FAIL — current protocol doesn't mention creation

- [ ] **Step 3: Update SKILLS_USAGE_PROTOCOL**

In `src/agenticops/agents/preamble.py`, replace `SKILLS_USAGE_PROTOCOL`:

```python
SKILLS_USAGE_PROTOCOL = """
AGENT SKILLS PROTOCOL:
- You have access to domain knowledge skills. Use list_skills to see them, or check <available_skills> above.
- When you need deep domain knowledge for troubleshooting, call activate_skill(skill_name) to load the skill's
  decision trees, command references, and diagnostic procedures.
- For detailed reference material, call read_skill_reference(skill_name, reference_path).
- Skills are READ-ONLY knowledge — they guide your tool usage but don't replace your tools.
- Activate skills BEFORE starting investigation when the domain is clear (e.g., activate 'linux-admin'
  before running host diagnostics, activate 'kubernetes-admin' before debugging pods).
- SKILL CREATION: If no existing skill covers the current problem domain, ask the user for confirmation,
  then call create_skill(name, description, publish=True) to generate and immediately activate a new skill.
  Never create a skill without user confirmation.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_creation.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/agents/preamble.py tests/test_skill_creation.py
git commit -m "feat(skills): add creation guidance to SKILLS_USAGE_PROTOCOL"
```

---

### Task 5: Update feature documentation

**Files:**
- Modify: `docs/MVP-1.0.0-RELEASE.md` (add feature entry)
- Modify: `docs/WORKFLOW.md` (if skill workflow section exists)

- [ ] **Step 1: Add auto-create skills feature to docs**

Add a section to the features documentation describing:
- Trigger: Agent detects no matching skill for current problem domain
- Flow: Agent asks user → user confirms → skill generated via LLM → published → activated
- Configuration: Requires `skills_enabled=true` (default)
- Behavior: `publish=True` saves to production `skills/` directory, immediately usable

- [ ] **Step 2: Commit docs**

```bash
git add docs/
git commit -m "docs: add auto-create skills feature description"
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `src/agenticops/skills/evolution.py` | Add `create_published_skill()` |
| `src/agenticops/skills/tools.py` | `create_skill` adds `publish` param + auto-activate; `activate_skill` guides creation |
| `src/agenticops/agents/preamble.py` | `SKILLS_USAGE_PROTOCOL` adds creation guidance |
| `tests/test_skill_creation.py` | 4 unit tests |
| `docs/` | Feature documentation |

Total: 3 source files modified, 1 test file created, docs updated.
