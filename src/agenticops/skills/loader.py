"""Skill discovery, YAML parsing, XML generation, and prompt helper.

Scans the skills/ directory (and skills/draft/) for valid SKILL.md packages,
parses YAML frontmatter, and generates XML summaries for agent system prompts.
Supports dynamic tool registration via the ``tools`` frontmatter field.
Uses mtime-based cache invalidation (same pattern as notify/im_config.py).
"""

from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

from agenticops.config import settings

logger = logging.getLogger(__name__)

# ── Module-level mtime cache ────────────────────────────────────────

_cached_skills: list[SkillMetadata] | None = None
_cached_skills_by_name: dict[str, SkillMetadata] | None = None
_cached_mtime: float = 0.0
_cached_xml: str | None = None


def _get_max_mtime(*directories: Path) -> float:
    """Return the max mtime of SKILL.md files across given directories.

    Also considers directory mtime itself (detects skill additions/removals).
    """
    max_mt = 0.0
    for directory in directories:
        if not directory.is_dir():
            continue
        # Directory mtime changes when children are added/removed
        max_mt = max(max_mt, directory.stat().st_mtime)
        for skill_dir in directory.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.is_file():
                max_mt = max(max_mt, skill_md.stat().st_mtime)
    return max_mt


def _invalidate_skills_cache() -> None:
    """Force cache invalidation."""
    global _cached_skills, _cached_skills_by_name, _cached_mtime, _cached_xml
    _cached_skills = None
    _cached_skills_by_name = None
    _cached_mtime = 0.0
    _cached_xml = None


def _get_skill_by_name(name: str) -> SkillMetadata | None:
    """O(1) lookup of a skill by name."""
    global _cached_skills_by_name
    skills = discover_skills()
    if _cached_skills_by_name is None:
        _cached_skills_by_name = {s.name: s for s in skills}
    return _cached_skills_by_name.get(name)


@dataclass
class SkillMetadata:
    """Parsed metadata from a SKILL.md frontmatter."""

    name: str
    description: str
    path: Path
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)  # dotted paths to @tool functions
    is_draft: bool = False
    created_by: str = "user"


# ── YAML Frontmatter Parsing ────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md content.

    Args:
        content: Raw SKILL.md file content.

    Returns:
        Tuple of (frontmatter dict, body text after frontmatter).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse YAML frontmatter: %s", e)
        return {}, content

    body = content[match.end():]
    return fm, body


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


# ── Skill Discovery ─────────────────────────────────────────────────


def _scan_directory(directory: Path, is_draft: bool = False) -> list[SkillMetadata]:
    """Scan a single directory for valid skill packages."""
    skills: list[SkillMetadata] = []
    if not directory.is_dir():
        return skills

    for skill_dir in sorted(directory.iterdir()):
        if not skill_dir.is_dir():
            continue

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue

        try:
            content = skill_md.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(content)

            name = fm.get("name", skill_dir.name)
            description = fm.get("description", "")
            if not description:
                logger.warning("Skill '%s' has no description, skipping", name)
                continue

            # Skip deprecated/archived skills (missing status => kept, treated active)
            if fm.get("status") in ("deprecated", "archived"):
                continue

            skills.append(
                SkillMetadata(
                    name=name,
                    description=description[:1024],
                    path=skill_dir,
                    license=fm.get("license"),
                    compatibility=fm.get("compatibility"),
                    metadata=fm.get("metadata", {}),
                    tools=fm.get("tools", []),
                    is_draft=is_draft,
                    created_by=fm.get("created_by", "user"),
                )
            )
        except Exception as e:
            logger.warning("Failed to load skill from %s: %s", skill_dir, e)

    return skills


def discover_skills(skills_dir: Path | None = None) -> list[SkillMetadata]:
    """Scan for valid skill directories containing SKILL.md.

    Checks both the main skills/ directory and the draft/ subdirectory.
    Uses mtime-based cache invalidation — reloads when any SKILL.md changes.

    Args:
        skills_dir: Override skills directory (defaults to settings.skills_dir).

    Returns:
        List of SkillMetadata for each valid skill found.
    """
    global _cached_skills, _cached_skills_by_name, _cached_mtime, _cached_xml

    if not settings.skills_enabled:
        if _cached_skills is None:
            _cached_skills = []
        return _cached_skills

    directory = skills_dir or settings.skills_dir
    draft_dir = settings.skills_draft_dir

    # Check mtime for cache invalidation
    current_mtime = _get_max_mtime(directory, draft_dir)
    if _cached_skills is not None and current_mtime == _cached_mtime:
        return _cached_skills

    # Cache miss or stale — reload
    # Also invalidate XML and name-lookup caches since skills changed
    _cached_xml = None
    _cached_skills_by_name = None

    skills = _scan_directory(directory, is_draft=False)
    draft_skills = _scan_directory(draft_dir, is_draft=True)

    # Merge: draft skills with same name as published are skipped
    published_names = {s.name for s in skills}
    for ds in draft_skills:
        if ds.name not in published_names:
            skills.append(ds)
        else:
            logger.debug(
                "Draft skill '%s' shadowed by published skill", ds.name
            )

    _cached_skills = skills
    _cached_mtime = current_mtime
    logger.info(
        "Discovered %d skills (%d draft)",
        len(skills),
        sum(1 for s in skills if s.is_draft),
    )
    return _cached_skills


# ── XML Generation ───────────────────────────────────────────────────


def build_available_skills_xml(skills: list[SkillMetadata]) -> str:
    """Generate <available_skills> XML block for agent system prompts.

    Descriptions are truncated to the first sentence (max 80 chars) to
    reduce prompt token usage. Full descriptions are available via
    activate_skill().

    Args:
        skills: List of discovered skill metadata.

    Returns:
        XML string listing all available skills.
    """
    if not skills:
        return ""

    lines = ["<available_skills>"]
    for s in skills:
        # Truncate to first sentence, max 80 chars
        short_desc = s.description.split(".")[0][:80]
        tag = "[DRAFT] " if s.is_draft else ""
        lines.append(f'  <skill name="{s.name}">{tag}{short_desc}</skill>')
    lines.append("</available_skills>")
    return "\n".join(lines)


def get_available_skills_xml() -> str:
    """Cached getter for the available skills XML block."""
    global _cached_xml
    if _cached_xml is not None:
        return _cached_xml

    skills = discover_skills()
    _cached_xml = build_available_skills_xml(skills)
    return _cached_xml


# ── Skill Content Loading ────────────────────────────────────────────


def load_skill_body(skill_name: str) -> str | None:
    """Load the full SKILL.md body for activation.

    Args:
        skill_name: Name of the skill to load.

    Returns:
        SKILL.md body content (after frontmatter), or None if not found.
    """
    s = _get_skill_by_name(skill_name)
    if s is None:
        return None
    content = (s.path / "SKILL.md").read_text(encoding="utf-8")
    _, body = parse_frontmatter(content)
    body = body.strip()
    max_chars = settings.skills_max_body_chars
    if len(body) > max_chars:
        body = body[:max_chars] + (
            "\n\n[... truncated — use read_skill_reference() "
            "for detailed sections]"
        )
    return body


def load_skill_reference(skill_name: str, ref_path: str) -> str | None:
    """Load a reference file from a skill package.

    Includes path traversal protection — ref_path must resolve within
    the skill directory.

    Args:
        skill_name: Name of the skill.
        ref_path: Relative path to the reference file (e.g., 'references/process-management.md').

    Returns:
        Reference file content, or None if not found or path traversal detected.
    """
    s = _get_skill_by_name(skill_name)
    if s is None:
        return None
    target = (s.path / ref_path).resolve()
    # Path traversal protection
    if not str(target).startswith(str(s.path.resolve())):
        logger.warning(
            "Path traversal attempt blocked: %s -> %s", ref_path, target
        )
        return None
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8")


# ── Dynamic Tool Resolution ──────────────────────────────────────────


def resolve_skill_tools(skill_name: str) -> list[Any]:
    """Import and return @tool functions declared in a skill's YAML frontmatter.

    Each entry in the ``tools`` field is a dotted path like
    ``agenticops.tools.file_tools.read_local_file``.

    Args:
        skill_name: Name of the skill whose tools to resolve.

    Returns:
        List of @tool decorated function objects, or empty list if skill
        has no tools declared or skill not found.
    """
    s = _get_skill_by_name(skill_name)
    if s is None:
        return []
    if not s.tools:
        return []
    resolved = []
    for dotted_path in s.tools:
        try:
            module_path, func_name = dotted_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            resolved.append(func)
        except Exception as e:
            logger.warning(
                "Failed to resolve tool '%s' for skill '%s': %s",
                dotted_path, skill_name, e,
            )
    return resolved


# ── Prompt Helper ────────────────────────────────────────────────────
# Constants and helpers are now canonical in agents/preamble.py.
# Re-export for backward compatibility (callers that import from loader).

from agenticops.agents.preamble import (  # noqa: E402, F401
    SKILLS_USAGE_PROTOCOL as _SKILLS_USAGE_PROTOCOL,
    OUTPUT_RULES as _OUTPUT_RULES,
    RCA_ADDENDA as _RCA_ADDENDA,
    SRE_ADDENDA as _SRE_ADDENDA,
    get_output_rules,
    build_system_prompt,
)


def build_prompt_with_skills(base_prompt: str, agent_type: str = "generic") -> str:
    """Append output rules + skills XML + usage protocol to an agent system prompt.

    Thin wrapper around build_system_prompt() for backward compatibility.

    Args:
        base_prompt: The agent's base system prompt.
        agent_type: Agent type for output rule selection ('rca', 'sre', or 'generic').

    Returns:
        Enhanced prompt with output rules and skills information appended.
    """
    return build_system_prompt(
        base_prompt, include_account=False, include_skills=True, agent_type=agent_type,
    )
