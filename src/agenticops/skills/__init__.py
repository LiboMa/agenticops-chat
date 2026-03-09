"""Agent Skills integration — portable SKILL.md packages for ops domain knowledge.

Bridges the Agent Skills open standard (agentskills.io) to the Strands SDK
(@tool functions + system prompts). Skills are discovered from the skills/
directory and activated on demand via progressive disclosure.
"""

from agenticops.skills.loader import (
    discover_skills,
    get_available_skills_xml,
    build_prompt_with_skills,
    resolve_skill_tools,
    _invalidate_skills_cache,
)
from agenticops.skills.tools import activate_skill, read_skill_reference, list_skills
from agenticops.skills.execution import run_on_host, run_kubectl
from agenticops.skills.evolution import (
    create_draft_skill,
    update_draft_skill,
    generate_skill_from_description,
    auto_improve_skill,
)
from agenticops.skills.registry import search_skills, install_from_registry
from agenticops.skills.review import (
    list_draft_skills,
    review_draft_skill,
    promote_skill,
    reject_draft_skill,
)

__all__ = [
    "discover_skills",
    "get_available_skills_xml",
    "build_prompt_with_skills",
    "resolve_skill_tools",
    "_invalidate_skills_cache",
    "activate_skill",
    "read_skill_reference",
    "list_skills",
    "run_on_host",
    "run_kubectl",
    "create_draft_skill",
    "update_draft_skill",
    "generate_skill_from_description",
    "auto_improve_skill",
    "search_skills",
    "install_from_registry",
    "list_draft_skills",
    "review_draft_skill",
    "promote_skill",
    "reject_draft_skill",
]
