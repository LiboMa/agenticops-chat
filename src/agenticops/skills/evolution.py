"""Skill evolution — create, update, and auto-improve draft skills.

Provides functions for agents to generate new skills from natural language
descriptions and self-improve existing skills based on identified gaps.
Uses Bedrock LLM directly (no Agent instance) for skill generation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import boto3

from agenticops.config import settings

logger = logging.getLogger(__name__)


def create_draft_skill(
    name: str,
    description: str,
    content: str,
    references: Optional[dict[str, str]] = None,
) -> Path:
    """Write a new SKILL.md to the draft directory.

    Args:
        name: Skill name (used as directory name).
        description: Short description for YAML frontmatter.
        content: Full SKILL.md body content (after frontmatter).
        references: Optional dict of {filename: content} for references/ files.

    Returns:
        Path to the created draft skill directory.
    """
    draft_dir = settings.skills_draft_dir / name
    draft_dir.mkdir(parents=True, exist_ok=True)

    # Build SKILL.md with YAML frontmatter
    skill_md = f"""---
name: {name}
description: "{description}"
---

{content}
"""
    (draft_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

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

    skill_md.write_text(updated_content, encoding="utf-8")
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
        )

        return {
            "action": "updated",
            "skill_name": skill_name,
            "draft_path": str(draft_path),
        }

    except Exception as e:
        logger.error("Auto-improve failed for skill '%s': %s", skill_name, e)
        return {"error": str(e)}
