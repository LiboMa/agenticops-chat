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
    MemoryFullError,
    archive_memory,
    load_agent_memory,
    merge_memories,
    patch_memory,
    rebuild_prompt_with_memory,
    save_memory_file,
    search_memories,
)
from agenticops.config import settings
from agenticops.security import redact_secrets

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug for filenames.

    Secrets are scrubbed BEFORE lowercasing: an AWS key ID lowercased no longer
    matches the (uppercase) key-ID shape, so a raw key could otherwise survive
    into a filename — and content-redaction can't fix a filename. This is the
    single choke point for memory slugs, so scrubbing here covers every caller.
    """
    slug = redact_secrets(text).lower().strip()
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

    filename = _slugify(description) + ".md"
    issue_id = related_issue_id if related_issue_id > 0 else None

    try:
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
    except MemoryFullError as e:
        # Consistent with memory_manage: return actionable merge guidance, not a traceback
        return json.dumps({
            "status": "memory_full",
            "agent": agent_name,
            "active_count": e.active_count,
            "current": e.current,
            "message": f"Memory full for {agent_name}. Use memory_manage(action='merge') "
                       f"to consolidate related entries, then record again.",
        })

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


@tool
def memory_manage(
    action: str,
    agent_name: str,
    description: str = "",
    filename: str = "",
    sources: list = None,
    into: str = "",
    confidence: int = 3,
    resource_pattern: str = "",
    memory_type: str = "feedback",
) -> str:
    """Manage this agent's persistent memory (Hermes-style self-optimization).

    Actions:
      - add: create a new memory (returns memory_full + current list if size cap reached).
      - patch: append to / re-confirm an existing memory (filename required).
      - merge: combine `sources` (filenames) into an umbrella `into` (frees space).
      - remove: archive a memory (filename required; recoverable, not deleted).
      - search: keyword search across memories.

    Memories created here are tagged created_by=agent (provenance, human-auditable).

    Args:
        action: add | patch | merge | remove | search
        agent_name: detect, rca, sre, executor, reporter, scan, shared
        description: memory content (add) / query (search) / merged body (merge) / appended text (patch)
        filename: target file (patch, remove)
        sources: list of source filenames (merge)
        into: umbrella filename (merge)
        confidence: 1-5
        resource_pattern: optional resource match pattern (add)
        memory_type: feedback | pattern | preference | baseline

    Returns:
        JSON status. On add-when-full: {"status":"memory_full","current":[...]} —
        merge related entries (action='merge') first, then add again.
    """
    valid_agents = ("detect", "rca", "sre", "executor", "reporter", "scan", "shared")
    if agent_name not in valid_agents:
        return json.dumps({"error": f"Invalid agent_name '{agent_name}'. One of {valid_agents}"})

    if not getattr(settings, "memory_autonomous_write", True) and action in ("add", "patch", "merge", "remove"):
        return json.dumps({"error": "Autonomous memory writes are disabled (memory_autonomous_write=false)."})

    if action == "search":
        results = search_memories(query=description, agent_name=agent_name)
        return json.dumps({"matches": results[:10], "total": len(results)})

    if action == "add":
        fname = _slugify(description) + ".md"
        try:
            fp = save_memory_file(
                agent_name=agent_name, filename=fname, memory_type=memory_type,
                confidence=confidence, source="agent", body=description,
                resource_pattern=resource_pattern, created_by="agent",
            )
        except MemoryFullError as e:
            return json.dumps({
                "status": "memory_full",
                "agent": agent_name,
                "active_count": e.active_count,
                "current": e.current,
                "message": f"Memory full for {agent_name}. Merge related entries "
                           f"(action='merge') to free space, then add again.",
            })
        return json.dumps({"status": "saved", "agent": agent_name, "file": fp.name,
                           "message": "Saved (created_by=agent). Effective next session."})

    if action == "patch":
        if not filename:
            return json.dumps({"error": "patch requires 'filename'"})
        ok = patch_memory(agent_name, filename,
                          append_body=("\n" + description if description else ""),
                          new_confidence=confidence)
        return json.dumps({"status": "patched" if ok else "not_found", "file": filename})

    if action == "merge":
        if not sources or not into:
            return json.dumps({"error": "merge requires 'sources' (list) and 'into'"})
        fp = merge_memories(agent_name=agent_name, sources=list(sources), into=into,
                            body=description, confidence=confidence, created_by="agent")
        return json.dumps({"status": "merged", "umbrella": fp.name, "absorbed": list(sources)})

    if action == "remove":
        if not filename:
            return json.dumps({"error": "remove requires 'filename'"})
        ok = archive_memory(agent_name, filename)
        return json.dumps({"status": "archived" if ok else "not_found", "file": filename})

    return json.dumps({"error": f"Unknown action '{action}'. Use add|patch|merge|remove|search."})
