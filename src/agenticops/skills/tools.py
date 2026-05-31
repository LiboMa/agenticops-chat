"""Skill tools — progressive disclosure of domain knowledge + dynamic tool loading.

Seven @tool functions that agents use to discover, load, and evolve skill content:
- list_skills: See what's available
- activate_skill: Load full SKILL.md decision trees and procedures;
  if the skill declares tools, dynamically register them on the calling agent
- read_skill_reference: Load detailed reference material
- create_skill: Generate and create a new draft skill from description
- improve_skill: Self-improve an existing skill based on identified gaps
- search_skill_registry: Search local and remote skill registries
- skill_manage: Unified agent tool for autonomous skill management (add/improve/merge/deprecate/restore/search)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from strands import tool

from agenticops.skills.loader import (
    discover_skills,
    list_skill_resources,
    load_skill_body,
    load_skill_reference as _load_ref,
    resolve_skill_tools,
)

logger = logging.getLogger(__name__)


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

    draft_count = sum(1 for s in skills if s.is_draft)
    header = f"Available Skills ({len(skills)})"
    if draft_count:
        header += f" — {draft_count} draft"
    lines = [f"{header}:"]
    for s in skills:
        refs_dir = s.path / "references"
        ref_count = len(list(refs_dir.glob("*.md"))) if refs_dir.is_dir() else 0
        has_tools = bool(s.tools)
        draft_tag = " [DRAFT]" if s.is_draft else ""
        lines.append(f"\n  {s.name}{draft_tag}")
        lines.append(f"    {s.description[:200]}")
        if ref_count:
            lines.append(f"    References: {ref_count} files")
        if has_tools:
            lines.append(f"    Dynamic tools: {len(s.tools)} (registered on activation)")
    lines.append(
        "\nUse activate_skill(skill_name) to load full decision trees and procedures."
    )
    return "\n".join(lines)


@tool
def activate_skill(skill_name: str, agent: Any = None) -> str:
    """Activate a skill by loading its full SKILL.md content.

    Loads the skill's decision trees, command references, diagnostic
    procedures, and troubleshooting workflows. Call this BEFORE starting
    investigation when the domain is clear.

    If the skill declares tools (e.g., local-os-operator provides file
    reading tools), they are dynamically registered on the agent so you
    can call them immediately after activation.

    Args:
        skill_name: Name of the skill to activate (e.g., 'linux-admin', 'local-os-operator').

    Returns:
        Full skill content with decision trees and procedures, or error message.
    """
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

    # Reactivate-on-use (Curator): touch last_used; resurrects stale agent drafts
    try:
        from agenticops.skills.curator import touch_skill_used
        touch_skill_used(skill_name)
    except Exception:
        logger.debug("touch_skill_used failed for %s", skill_name, exc_info=True)

    # List available resources (scripts/, references/, assets/)
    refs_info = ""
    resources = list_skill_resources(skill_name)
    if resources:
        refs_info = "\n\nAvailable resources (use read_skill_reference to load):\n"
        for rel in resources:
            refs_info += f"  - {rel}\n"

    # Dynamic tool registration — if the skill declares tools AND we have an agent
    tools_info = ""
    if agent is not None:
        skill_tools = resolve_skill_tools(skill_name)
        if skill_tools:
            registered = []
            for tool_fn in skill_tools:
                tool_name = getattr(tool_fn, "tool_name", getattr(tool_fn, "__name__", str(tool_fn)))
                # Skip if already registered (idempotent activation)
                if tool_name in agent.tool_registry.registry:
                    registered.append(tool_name)
                    continue
                try:
                    agent.tool_registry.process_tools([tool_fn])
                    registered.append(tool_name)
                except Exception as e:
                    logger.warning(
                        "Failed to register tool '%s' from skill '%s': %s",
                        tool_name, skill_name, e,
                    )
            if registered:
                tools_info = (
                    f"\n\nDynamically registered tools: {', '.join(registered)}\n"
                    "You can now call these tools directly."
                )

    return (
        f'<activated_skill name="{skill_name}">\n{body}{refs_info}</activated_skill>'
        f"{tools_info}"
        "\n\nNote: Use the decision trees above to GUIDE your investigation. "
        "Do NOT echo this content back to the user — summarize relevant findings only."
    )


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
    from agenticops.skills.loader import _invalidate_skills_cache

    result = generate_skill_from_description(description)
    if "error" in result:
        return f"Failed to generate skill: {result['error']}"

    skill_name = result.get("name", name)
    skill_desc = (result.get("description") or description)[:200]
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


@tool
def improve_skill(skill_name: str, improvement: str) -> str:
    """Self-improve an existing skill based on an identified gap.

    Creates an improved draft version of the skill. The original published
    skill is preserved until the draft is reviewed and promoted.
    The improvement is recorded in the improvement store for audit/genealogy.

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


@tool
def search_skill_registry(query: str) -> str:
    """Search for skills across local installation and remote registry.

    Searches both installed skills (published + draft) and ClawHub
    remote registry (if enabled).

    Args:
        query: Search query (matches skill names and descriptions).

    Returns:
        Formatted list of matching skills with source information.
    """
    from agenticops.skills.registry import search_skills

    results = search_skills(query)
    if not results:
        return f"No skills found matching '{query}'."

    lines = [f"Search results for '{query}' ({len(results)} found):"]
    for r in results:
        source = r.get("source", "local")
        lines.append(f"  {r['name']} [{source}] — {r.get('description', '')[:120]}")
    return "\n".join(lines)


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
      - add: generate a NEW skill from `description` -> saved as DRAFT (never auto-published;
             promotion requires security scan + human review).
      - improve: improve an existing skill (`name` + `improvement`) -> DRAFT; recorded for audit.
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
        try:
            d = create_draft_skill(name=gen.get("name", name), description=(gen.get("description") or description)[:200],
                                   content=gen.get("content", ""), references=gen.get("references"), created_by="agent")
        except ValueError as e:
            return json.dumps({"error": f"invalid skill name: {e}"})
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
        try:
            d = merge_skills_into_umbrella(list(sources), into, description or f"Umbrella of {sources}", description or "")
        except ValueError as e:
            return json.dumps({"error": f"invalid skill name: {e}"})
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
