"""Agent Memory tools — @tool functions for recording and searching memories.

These tools are registered on agents to enable:
- ``record_agent_feedback``: Chat-driven feedback → memory file creation
  (registered on main_agent only)
- ``search_agent_memory``: Cross-agent memory search
  (registered on all agents)
"""

from __future__ import annotations

import json
import logging
import re

from strands import tool

from agenticops.memory.agent_memory import (
    load_agent_memory,
    rebuild_prompt_with_memory,
    save_memory_file,
    search_memories,
)

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug for filenames."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:60] if slug else "memory"


@tool
def record_agent_feedback(
    agent_name: str,
    description: str,
    confidence: int = 3,
    resource_pattern: str = "",
    memory_type: str = "feedback",
    related_issue_id: int = 0,
) -> str:
    """Record operational feedback as a persistent agent memory.

    Creates or updates a Markdown memory file so the specified agent
    will remember this feedback in future sessions.

    Args:
        agent_name: Target agent (detect, rca, sre, executor, reporter, scan, shared).
        description: What the agent should remember (e.g., "CPU 50-70% on t3.medium is normal fluctuation").
        confidence: User confidence score 1-5 (5=certain, 3=default, 1=uncertain).
        resource_pattern: Optional resource match pattern (e.g., "EC2/t3.*").
        memory_type: Memory type: feedback, pattern, preference, or baseline.
        related_issue_id: Optional associated HealthIssue ID (0 = none).

    Returns:
        Confirmation message with the saved memory details.
    """
    valid_agents = ("detect", "rca", "sre", "executor", "reporter", "scan", "shared")
    if agent_name not in valid_agents:
        return json.dumps({"error": f"Invalid agent_name '{agent_name}'. Must be one of: {valid_agents}"})

    valid_types = ("feedback", "pattern", "preference", "baseline")
    if memory_type not in valid_types:
        return json.dumps({"error": f"Invalid memory_type '{memory_type}'. Must be one of: {valid_types}"})

    filename = _slugify(description[:50]) + ".md"
    issue_id = related_issue_id if related_issue_id > 0 else None

    filepath = save_memory_file(
        agent_name=agent_name,
        filename=filename,
        memory_type=memory_type,
        confidence=confidence,
        source="chat",
        body=description,
        resource_pattern=resource_pattern,
        related_issue_id=issue_id,
    )

    result = {
        "status": "saved",
        "agent": agent_name,
        "file": str(filepath.name),
        "confidence": confidence,
        "message": f"Memory recorded for {agent_name} agent (confidence: {confidence}/5). "
                   f"This will take effect on the next agent invocation.",
    }
    return json.dumps(result)


@tool
def search_agent_memory(query: str, agent_name: str = "") -> str:
    """Search agent memories by keyword across agents.

    Finds memories whose content matches the query keywords.
    Results are sorted by confidence (highest first).

    Args:
        query: Search keywords (e.g., "CPU spike", "RDS connection", "security group").
        agent_name: Filter by specific agent name, or empty string to search all agents.

    Returns:
        JSON array of matching memories with agent, filename, body, confidence.
    """
    results = search_memories(query=query, agent_name=agent_name)
    if not results:
        return json.dumps({"matches": [], "message": f"No memories found matching '{query}'"})
    return json.dumps({"matches": results[:10], "total": len(results)})
