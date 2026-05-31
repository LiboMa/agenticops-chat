"""Skill evolution — create, update, and auto-improve draft skills.

Provides functions for agents to generate new skills from natural language
descriptions and self-improve existing skills based on identified gaps.
Uses Bedrock LLM directly (no Agent instance) for skill generation.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import boto3

from agenticops.config import settings

logger = logging.getLogger(__name__)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically: temp file in the same dir + os.replace.

    Prevents a crash mid-write from leaving a corrupt/half-written file.
    """
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


import re as _re

def _safe_skill_name(name: str) -> str:
    """Validate a skill name is a safe single-segment slug (no path traversal).

    Raises ValueError on names that aren't lowercase-hyphenated single segments
    (rejects '/', '..', absolute paths, etc.). Skills are executable, and skill
    names can originate from an LLM / autonomous tool, so this is a hard gate.
    """
    if not isinstance(name, str) or not _re.match(r"^[a-z0-9][a-z0-9._-]{0,62}$", name):
        raise ValueError(f"unsafe skill name: {name!r} (expected lowercase single-segment slug)")
    if name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"unsafe skill name: {name!r}")
    return name


def create_draft_skill(
    name: str,
    description: str,
    content: str,
    references: Optional[dict[str, str]] = None,
    created_by: str = "user",
    extra_frontmatter: dict | None = None,
) -> Path:
    """Write a new SKILL.md to the draft directory.

    Args:
        name: Skill name (used as directory name).
        description: Short description for YAML frontmatter.
        content: Full SKILL.md body content (after frontmatter).
        references: Optional dict of {filename: content} for references/ files.
        created_by: Provenance — "user" (human, pinned) or "agent" (auto).
        extra_frontmatter: Additional frontmatter fields (e.g., improved_from).

    Returns:
        Path to the created draft skill directory.
    """
    name = _safe_skill_name(name)
    draft_dir = settings.skills_draft_dir / name
    draft_dir.mkdir(parents=True, exist_ok=True)

    # Build SKILL.md with YAML frontmatter
    import datetime as _dt
    _today = _dt.date.today().isoformat()
    _extra = ""
    if extra_frontmatter:
        _extra = "".join(f"{k}: {json.dumps(v)}\n" for k, v in extra_frontmatter.items())
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
    _atomic_write_text(draft_dir / "SKILL.md", skill_md)

    # Write reference files if provided
    if references:
        refs_dir = draft_dir / "references"
        refs_dir.mkdir(exist_ok=True)
        for filename, ref_content in references.items():
            (refs_dir / filename).write_text(ref_content, encoding="utf-8")

    logger.info("Created draft skill '%s' at %s", name, draft_dir)
    return draft_dir


def create_published_skill(
    name: str,
    description: str,
    content: str,
    references: Optional[dict[str, str]] = None,
    created_by: str = "user",
) -> Path:
    """Write a new SKILL.md directly to the published skills directory.

    Same as create_draft_skill but targets skills_dir (production).
    Used when user has confirmed skill creation.

    Args:
        name: Skill name (used as directory name).
        description: Short description for YAML frontmatter.
        content: Full SKILL.md body content (after frontmatter).
        references: Optional dict of {filename: content} for references/ files.
        created_by: Provenance — "user" (human, pinned) or "agent" (auto).

    Returns:
        Path to the created skill directory.
    """
    name = _safe_skill_name(name)
    pub_dir = settings.skills_dir / name
    pub_dir.mkdir(parents=True, exist_ok=True)

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
    _atomic_write_text(pub_dir / "SKILL.md", skill_md)

    if references:
        refs_dir = pub_dir / "references"
        refs_dir.mkdir(exist_ok=True)
        for filename, ref_content in references.items():
            (refs_dir / filename).write_text(ref_content, encoding="utf-8")

    logger.info("Created published skill '%s' at %s", name, pub_dir)
    return pub_dir


def merge_skills_into_umbrella(sources: list, into: str, description: str, content: str) -> Path:
    """Create an umbrella DRAFT skill from sources; records improved_from. Returns draft path.

    Sources are NOT auto-archived — merge just creates the umbrella draft recording
    its lineage. The agent/curator handles source lifecycle separately.
    """
    from agenticops.skills.loader import _invalidate_skills_cache
    draft = create_draft_skill(
        name=into, description=description, content=content, created_by="agent",
        extra_frontmatter={"improved_from": list(sources)},
    )
    _invalidate_skills_cache()
    return draft


def update_draft_skill(name: str, updated_content: str) -> Path | None:
    """Update an existing draft skill's SKILL.md content.

    Args:
        name: Name of the draft skill.
        updated_content: New full file content (including frontmatter).

    Returns:
        Path to the updated skill directory, or None if not found.
    """
    draft_dir = settings.skills_draft_dir / name
    skill_md = draft_dir / "SKILL.md"

    if not skill_md.is_file():
        logger.warning("Draft skill '%s' not found at %s", name, draft_dir)
        return None

    _atomic_write_text(skill_md, updated_content)
    logger.info("Updated draft skill '%s'", name)
    return draft_dir


def generate_skill_from_description(description: str) -> dict[str, Any]:
    """Use LLM to generate a SKILL.md from a natural language description.

    Calls Bedrock directly (no Agent instance) using settings.bedrock_model_id.

    Args:
        description: Natural language description of the desired skill
            (e.g., "a skill for troubleshooting Redis cluster issues").

    Returns:
        Dict with keys: name, description, content, references (dict).
        On error, returns dict with 'error' key.
    """
    prompt = f"""You are an expert at creating Agent Skills (SKILL.md packages) for an AIOps platform.

Given this description, generate a complete skill package:

DESCRIPTION: {description}

Respond with a JSON object containing:
- "name": skill directory name (lowercase, hyphenated, e.g., "redis-admin")
- "description": one-line description for YAML frontmatter (max 200 chars)
- "content": the full SKILL.md body content (decision trees, diagnostic procedures, command references)
- "references": an object mapping filename to content for reference files (e.g., {{"troubleshooting.md": "..."}})

Requirements for the content:
- Include decision trees with clear IF/THEN branching
- Include diagnostic commands with expected output patterns
- Include remediation steps with rollback procedures
- Follow the Agent Skills open standard format

Return ONLY valid JSON, no markdown fences or extra text."""

    try:
        from agenticops.config import get_bedrock_boto_session
        client = get_bedrock_boto_session().client("bedrock-runtime")
        response = client.converse(
            modelId=settings.bedrock_model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 8192},
        )
        raw_text = response["output"]["message"]["content"][0]["text"]

        # Strip markdown fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        result = json.loads(text)

        # Validate required keys
        for key in ("name", "description", "content"):
            if key not in result:
                return {"error": f"LLM response missing required key: {key}"}

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

        result.setdefault("references", {})
        return result

    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM response as JSON: %s", e)
        return {"error": f"Invalid JSON from LLM: {e}"}
    except Exception as e:
        logger.error("Skill generation failed: %s", e)
        return {"error": str(e)}


def auto_improve_skill(
    skill_name: str,
    gap_description: str,
    agent_context: str = "",
) -> dict[str, Any]:
    """Agent self-improves a skill by generating an updated draft.

    Reads the current skill content, sends it to the LLM with the gap
    description, and creates an updated draft.

    Args:
        skill_name: Name of the existing skill to improve.
        gap_description: What's missing or needs improvement.
        agent_context: Optional context from the agent's investigation.

    Returns:
        Dict with keys: action ('created'|'updated'), skill_name, draft_path.
        On error, returns dict with 'error' key.
    """
    from agenticops.skills.loader import discover_skills, parse_frontmatter

    # Find existing skill
    skills = discover_skills()
    existing = None
    for s in skills:
        if s.name == skill_name:
            existing = s
            break

    if existing is None:
        return {"error": f"Skill '{skill_name}' not found"}

    # Read current content
    current_content = (existing.path / "SKILL.md").read_text(encoding="utf-8")
    fm, body = parse_frontmatter(current_content)

    prompt = f"""You are improving an existing Agent Skill for an AIOps platform.

CURRENT SKILL ({skill_name}):
{body[:4000]}

GAP/IMPROVEMENT NEEDED:
{gap_description}

{"AGENT CONTEXT:" + chr(10) + agent_context[:2000] if agent_context else ""}

Generate an IMPROVED version of the SKILL.md body content that addresses the gap.
Keep all existing good content and ADD the missing parts.

Return ONLY the improved SKILL.md body content (no frontmatter, no JSON wrapper).
Include decision trees, diagnostic commands, and remediation steps."""

    try:
        from agenticops.config import get_bedrock_boto_session
        client = get_bedrock_boto_session().client("bedrock-runtime")
        response = client.converse(
            modelId=settings.bedrock_model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 8192},
        )
        improved_body = response["output"]["message"]["content"][0]["text"].strip()

        # Create as draft (preserves original)
        draft_path = create_draft_skill(
            name=skill_name,
            description=fm.get("description", existing.description),
            content=improved_body,
            created_by="agent",
        )

        return {
            "action": "updated",
            "skill_name": skill_name,
            "draft_path": str(draft_path),
        }

    except Exception as e:
        logger.error("Auto-improve failed for skill '%s': %s", skill_name, e)
        return {"error": str(e)}
