"""Skill discovery, YAML parsing, XML generation, and prompt helper.

Scans the skills/ directory for valid SKILL.md packages, parses YAML
frontmatter, and generates XML summaries for agent system prompts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from agenticops.config import get_detail_level, settings

logger = logging.getLogger(__name__)

# ── Module-level cache ───────────────────────────────────────────────

_cached_skills: list[SkillMetadata] | None = None
_cached_xml: str | None = None


@dataclass
class SkillMetadata:
    """Parsed metadata from a SKILL.md frontmatter."""

    name: str
    description: str
    path: Path
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: dict = field(default_factory=dict)


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


# ── Skill Discovery ─────────────────────────────────────────────────


def discover_skills(skills_dir: Path | None = None) -> list[SkillMetadata]:
    """Scan for valid skill directories containing SKILL.md.

    Args:
        skills_dir: Override skills directory (defaults to settings.skills_dir).

    Returns:
        List of SkillMetadata for each valid skill found.
    """
    global _cached_skills
    if _cached_skills is not None:
        return _cached_skills

    if not settings.skills_enabled:
        _cached_skills = []
        return _cached_skills

    directory = skills_dir or settings.skills_dir
    if not directory.is_dir():
        logger.debug("Skills directory does not exist: %s", directory)
        _cached_skills = []
        return _cached_skills

    skills: list[SkillMetadata] = []
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

            skills.append(
                SkillMetadata(
                    name=name,
                    description=description[:1024],
                    path=skill_dir,
                    license=fm.get("license"),
                    compatibility=fm.get("compatibility"),
                    metadata=fm.get("metadata", {}),
                )
            )
        except Exception as e:
            logger.warning("Failed to load skill from %s: %s", skill_dir, e)

    _cached_skills = skills
    logger.info("Discovered %d skills", len(skills))
    return _cached_skills


# ── XML Generation ───────────────────────────────────────────────────


def build_available_skills_xml(skills: list[SkillMetadata]) -> str:
    """Generate <available_skills> XML block for agent system prompts.

    Args:
        skills: List of discovered skill metadata.

    Returns:
        XML string listing all available skills.
    """
    if not skills:
        return ""

    lines = ["<available_skills>"]
    for s in skills:
        lines.append(f'  <skill name="{s.name}">{s.description}</skill>')
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
    skills = discover_skills()
    for s in skills:
        if s.name == skill_name:
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
    return None


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
    skills = discover_skills()
    for s in skills:
        if s.name == skill_name:
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
    return None


# ── Prompt Helper ────────────────────────────────────────────────────

_SKILLS_USAGE_PROTOCOL = """
AGENT SKILLS PROTOCOL:
- You have access to domain knowledge skills. Use list_skills to see them, or check <available_skills> above.
- When you need deep domain knowledge for troubleshooting, call activate_skill(skill_name) to load the skill's
  decision trees, command references, and diagnostic procedures.
- For detailed reference material, call read_skill_reference(skill_name, reference_path).
- Skills are READ-ONLY knowledge — they guide your tool usage but don't replace your tools.
- Activate skills BEFORE starting investigation when the domain is clear (e.g., activate 'linux-admin'
  before running host diagnostics, activate 'kubernetes-admin' before debugging pods).
"""


# ── Output Format Rule Templates ────────────────────────────────────

_OUTPUT_RULES: dict[str, str] = {
    "concise": """\
OUTPUT FORMAT RULES (concise mode — target ~500 tokens):
- Lead with root cause / answer in 1-2 sentences.
- Bullet points only — no tables, no headings, no paragraphs.
- Do NOT echo back skill content, tool results, or protocol steps.
- Do NOT repeat the user's question.
- Cite resource IDs inline (e.g., "i-0abc123 is running").
- Omit recommendations and fix plans unless explicitly requested.""",

    "medium": """\
OUTPUT FORMAT RULES (medium mode — target ~1500 tokens):
- Keep responses CONCISE. Aim for 500-1500 tokens of output text.
- Use bullet points and short sentences — not paragraphs.
- Lead with a 2-3 sentence summary, then key findings as bullets.
- Include brief recommendations section when relevant.
- Do NOT echo back full skill content or tool results verbatim. Summarize key findings.
- Do NOT repeat the user's question or restate the protocol steps.
- When citing resource IDs, use inline format (e.g., "i-0abc123 is running") not tables.""",

    "detailed": """\
OUTPUT FORMAT RULES (detailed mode — target ~4000 tokens):
- Provide a thorough narrative with full evidence chain.
- Use headings (##) to organize: Summary → Evidence → Analysis → Recommendations.
- Include resource details with IDs, states, and relevant attributes.
- Tables are allowed for comparing resources or metrics.
- Include complete recommendations with specific CLI commands.
- Still do NOT echo raw tool output or repeat the protocol — synthesize and explain.""",
}

_RCA_ADDENDA: dict[str, str] = {
    "concise": """\
- Structure: Root Cause (1 sentence) → top 3 evidence bullets → confidence score.""",
    "medium": """\
- Structure: Root Cause → Evidence → Contributing Factors → Recommendations → Fix Plan (if applicable).""",
    "detailed": """\
- Structure: Root Cause → Full Evidence Chain (with timestamps) → Contributing Factors → Detailed Recommendations → Fix Plan → Risk Assessment.
- Include CloudTrail event names, metric data points, and KB matches when available.""",
}

_SRE_ADDENDA: dict[str, str] = {
    "concise": """\
- For Mode A (fix plans): numbered steps, one line per step, no prose.
- For Mode B (investigation): 1-sentence answer + key findings bullets.""",
    "medium": """\
- For Mode A (fix plans): use numbered steps, one line per step.
- For Mode B (investigation): lead with a 2-3 sentence summary, then key findings as bullets.""",
    "detailed": """\
- For Mode A (fix plans): numbered steps with full CLI commands, pre/post checks, rollback plan, and estimated impact.
- For Mode B (investigation): comprehensive findings organized by resource, with topology context and capacity data.""",
}


def get_output_rules(agent_type: str = "generic") -> str:
    """Return the OUTPUT FORMAT RULES block for the current detail level.

    Reads the detail level from the ContextVar set by config.get_detail_level().

    Args:
        agent_type: One of 'rca', 'sre', or 'generic'.

    Returns:
        Formatted rules string ready to inject into a system prompt.
    """
    level = get_detail_level()
    rules = _OUTPUT_RULES.get(level, _OUTPUT_RULES["medium"])

    addenda = ""
    if agent_type == "rca":
        addenda = _RCA_ADDENDA.get(level, "")
    elif agent_type == "sre":
        addenda = _SRE_ADDENDA.get(level, "")

    if addenda:
        return f"{rules}\n{addenda}"
    return rules


def build_prompt_with_skills(base_prompt: str, agent_type: str = "generic") -> str:
    """Append output rules + skills XML + usage protocol to an agent system prompt.

    Args:
        base_prompt: The agent's base system prompt.
        agent_type: Agent type for output rule selection ('rca', 'sre', or 'generic').

    Returns:
        Enhanced prompt with output rules and skills information appended.
    """
    # Always inject output rules (even if skills are disabled)
    output_rules = get_output_rules(agent_type)
    prompt = f"{base_prompt}\n\n{output_rules}"

    if not settings.skills_enabled:
        return prompt

    xml = get_available_skills_xml()
    if not xml:
        return prompt

    return f"{prompt}\n\n{xml}\n{_SKILLS_USAGE_PROTOCOL}"
