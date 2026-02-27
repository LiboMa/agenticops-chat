"""Skill tools — progressive disclosure of domain knowledge.

Three @tool functions that agents use to discover and load skill content:
- list_skills: See what's available
- activate_skill: Load full SKILL.md decision trees and procedures
- read_skill_reference: Load detailed reference material
"""

from __future__ import annotations

from strands import tool

from agenticops.skills.loader import (
    discover_skills,
    load_skill_body,
    load_skill_reference as _load_ref,
)


@tool
def list_skills() -> str:
    """List all available Agent Skills with their descriptions.

    Returns a summary of installed skills that can be activated for
    domain-specific troubleshooting knowledge.

    Returns:
        Formatted list of available skills with names and descriptions.
    """
    skills = discover_skills()
    if not skills:
        return "No skills installed. Add skill packages to the skills/ directory."

    lines = [f"Available Skills ({len(skills)}):"]
    for s in skills:
        refs_dir = s.path / "references"
        ref_count = len(list(refs_dir.glob("*.md"))) if refs_dir.is_dir() else 0
        lines.append(f"\n  {s.name}")
        lines.append(f"    {s.description[:200]}")
        if ref_count:
            lines.append(f"    References: {ref_count} files")
    lines.append(
        "\nUse activate_skill(skill_name) to load full decision trees and procedures."
    )
    return "\n".join(lines)


@tool
def activate_skill(skill_name: str) -> str:
    """Activate a skill by loading its full SKILL.md content.

    Loads the skill's decision trees, command references, diagnostic
    procedures, and troubleshooting workflows. Call this BEFORE starting
    investigation when the domain is clear.

    Args:
        skill_name: Name of the skill to activate (e.g., 'linux-admin', 'kubernetes-admin').

    Returns:
        Full skill content with decision trees and procedures, or error message.
    """
    body = load_skill_body(skill_name)
    if body is None:
        skills = discover_skills()
        available = ", ".join(s.name for s in skills)
        return f"Skill '{skill_name}' not found. Available: {available}"

    # List available references
    skills = discover_skills()
    refs_info = ""
    for s in skills:
        if s.name == skill_name:
            refs_dir = s.path / "references"
            if refs_dir.is_dir():
                ref_files = sorted(refs_dir.glob("*.md"))
                if ref_files:
                    refs_info = "\n\nAvailable references (use read_skill_reference to load):\n"
                    for rf in ref_files:
                        refs_info += f"  - references/{rf.name}\n"
            break

    return f"<activated_skill name=\"{skill_name}\">\n{body}{refs_info}</activated_skill>"


@tool
def read_skill_reference(skill_name: str, reference_path: str) -> str:
    """Load a reference file from a skill package.

    Reference files contain detailed procedures, command examples, and
    deep-dive material for specific topics within a skill domain.

    Args:
        skill_name: Name of the skill (e.g., 'linux-admin').
        reference_path: Relative path to the reference file (e.g., 'references/process-management.md').

    Returns:
        Reference file content, or error message.
    """
    content = _load_ref(skill_name, reference_path)
    if content is None:
        return (
            f"Reference '{reference_path}' not found in skill '{skill_name}'. "
            f"Use activate_skill('{skill_name}') to see available references."
        )

    return f"<skill_reference skill=\"{skill_name}\" path=\"{reference_path}\">\n{content}\n</skill_reference>"
