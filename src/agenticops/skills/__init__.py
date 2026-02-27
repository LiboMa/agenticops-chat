"""Agent Skills integration — portable SKILL.md packages for ops domain knowledge.

Bridges the Agent Skills open standard (agentskills.io) to the Strands SDK
(@tool functions + system prompts). Skills are discovered from the skills/
directory and activated on demand via progressive disclosure.
"""

from agenticops.skills.loader import (
    discover_skills,
    get_available_skills_xml,
    build_prompt_with_skills,
)
from agenticops.skills.tools import activate_skill, read_skill_reference, list_skills
from agenticops.skills.execution import run_on_host, run_kubectl

__all__ = [
    "discover_skills",
    "get_available_skills_xml",
    "build_prompt_with_skills",
    "activate_skill",
    "read_skill_reference",
    "list_skills",
    "run_on_host",
    "run_kubectl",
]
