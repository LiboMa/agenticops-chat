"""Per-agent Markdown memory: load, save, search, and prompt injection.

Agent Memory is a behavioral constraint & enhancement layer stored as
Markdown files with YAML frontmatter under ``agent-memory/``.  It is
separate from the DB-based MemoryService (case-level experience memory).

Directory layout::

    agent-memory/
      detect/MEMORY.md + *.md
      rca/MEMORY.md + *.md
      shared/MEMORY.md + *.md
      ...
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from agenticops.config import settings

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
AGENT_MEMORY_DIR = PROJECT_ROOT / "agent-memory"

AGENT_NAMES = ("detect", "rca", "sre", "executor", "reporter", "scan", "shared")

MEMORY_MARKER_START = "[Agent Memory - learned from past feedback]"
MEMORY_MARKER_END = "[End Agent Memory]"

DEFAULT_CONFIDENCE = 3


# ── Frontmatter parsing ────────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown string.

    Args:
        content: Raw Markdown file content.

    Returns:
        (frontmatter_dict, body_text).  If no frontmatter found,
        returns ({}, full_content).
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {}, content.strip()
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        logger.warning("Failed to parse YAML frontmatter")
        return {}, content.strip()
    return fm, match.group(2).strip()


def normalize_frontmatter(fm: dict[str, Any]) -> dict[str, Any]:
    """Backfill cycle② fields on a frontmatter dict (non-destructive copy).

    - last_used: defaults to last_confirmed, then created_at, then today.
    - created_by: defaults to "user".
    - status: defaults to "active".
    Existing values are preserved.
    """
    out = dict(fm)
    out.setdefault("status", "active")
    out.setdefault("created_by", "user")
    if "last_used" not in out:
        out["last_used"] = out.get("last_confirmed") or out.get("created_at") or str(date.today())
    # Stringify date-likes for stable comparison
    out["last_used"] = str(out["last_used"])
    return out


def _serialize_frontmatter(fm: dict[str, Any], body: str) -> str:
    """Serialize frontmatter dict + body into a Markdown string."""
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{fm_str}\n---\n\n{body}\n"


# ── Loading ─────────────────────────────────────────────────────────

def _agent_dir(agent_name: str) -> Path:
    """Return the memory directory for a given agent."""
    return AGENT_MEMORY_DIR / agent_name


def _load_memories_from_dir(directory: Path) -> list[dict[str, Any]]:
    """Load all active memory files from a directory.

    Returns list of dicts with keys: filename, frontmatter, body, confidence.
    """
    memories: list[dict[str, Any]] = []
    if not directory.is_dir():
        return memories

    for md_file in sorted(directory.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        try:
            raw = md_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Failed to read %s", md_file)
            continue

        fm, body = parse_frontmatter(raw)
        if fm.get("status") != "active":
            continue

        confidence = fm.get("confidence", DEFAULT_CONFIDENCE)
        try:
            confidence = int(confidence)
        except (TypeError, ValueError):
            confidence = DEFAULT_CONFIDENCE

        memories.append({
            "filename": md_file.name,
            "frontmatter": fm,
            "body": body,
            "confidence": confidence,
        })

    return memories


def load_agent_memory(agent_name: str, max_entries: int = 10) -> str:
    """Load per-agent + shared memories, return formatted prompt context.

    Memories are sorted by confidence (high first) and capped at
    *max_entries*.

    Args:
        agent_name: One of AGENT_NAMES (e.g. "detect").
        max_entries: Max number of memory entries to inject.

    Returns:
        Formatted string ready for system prompt injection, or empty
        string if no active memories.
    """
    memories: list[dict[str, Any]] = []

    # 1. Agent's own memories
    memories.extend(_load_memories_from_dir(_agent_dir(agent_name)))

    # 2. Shared memories (unless agent IS shared)
    if agent_name != "shared":
        memories.extend(_load_memories_from_dir(_agent_dir("shared")))

    if not memories:
        return ""

    # 3. Sort by confidence descending, cap
    memories.sort(key=lambda m: m["confidence"], reverse=True)
    memories = memories[:max_entries]

    # 4. Format
    lines = [MEMORY_MARKER_START]
    for m in memories:
        fm = m["frontmatter"]
        entry = (
            f"[{fm.get('type', 'unknown')}] "
            f"(confidence: {m['confidence']}/5) "
            f"{m['body']}"
        )
        lines.append(entry)
        lines.append("---")

    lines.append(MEMORY_MARKER_END)
    return "\n".join(lines)


# ── Saving ──────────────────────────────────────────────────────────

def save_memory_file(
    agent_name: str,
    filename: str,
    *,
    memory_type: str = "feedback",
    confidence: int = DEFAULT_CONFIDENCE,
    source: str = "user",
    body: str,
    resource_pattern: str = "",
    related_issue_id: int | None = None,
) -> Path:
    """Create or update a memory Markdown file.

    Args:
        agent_name: Target agent (e.g. "detect").
        filename: File name (e.g. "cpu_spike_normal.md").
        memory_type: feedback | pattern | preference | baseline.
        confidence: 1-5 user confidence score.
        source: user | chat | auto.
        body: Markdown body content.
        resource_pattern: Optional resource match pattern.
        related_issue_id: Optional associated HealthIssue ID.

    Returns:
        Path to the written file.
    """
    directory = _agent_dir(agent_name)
    directory.mkdir(parents=True, exist_ok=True)

    if not filename.endswith(".md"):
        filename = filename + ".md"

    filepath = directory / filename

    # If file exists, preserve created_at
    created_at = str(date.today())
    if filepath.exists():
        try:
            old_fm, _ = parse_frontmatter(filepath.read_text(encoding="utf-8"))
            if "created_at" in old_fm:
                created_at = str(old_fm["created_at"])
        except OSError:
            pass

    fm: dict[str, Any] = {
        "agent": agent_name,
        "type": memory_type,
        "status": "active",
        "confidence": max(1, min(5, confidence)),
        "source": source,
        "created_at": created_at,
        "last_confirmed": str(date.today()),
    }
    if resource_pattern:
        fm["resource_pattern"] = resource_pattern
    if related_issue_id is not None:
        fm["related_issue_id"] = related_issue_id

    filepath.write_text(_serialize_frontmatter(fm, body), encoding="utf-8")
    logger.info("Saved agent memory: %s/%s (confidence=%d)", agent_name, filename, confidence)

    # Update index
    update_memory_index(agent_name)
    return filepath


def archive_memory(agent_name: str, filename: str) -> bool:
    """Set a memory file's status to 'archived'.

    Returns True if the file was found and updated.
    """
    filepath = _agent_dir(agent_name) / filename
    if not filepath.exists():
        return False

    raw = filepath.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)
    fm["status"] = "archived"
    filepath.write_text(_serialize_frontmatter(fm, body), encoding="utf-8")
    update_memory_index(agent_name)
    logger.info("Archived agent memory: %s/%s", agent_name, filename)
    return True


def update_memory_index(agent_name: str) -> None:
    """Rebuild the MEMORY.md index for an agent from active memory files."""
    directory = _agent_dir(agent_name)
    if not directory.is_dir():
        return

    lines = [f"# {agent_name.title()} Agent Memory", ""]
    for md_file in sorted(directory.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        try:
            raw = md_file.read_text(encoding="utf-8")
        except OSError:
            continue

        fm, body = parse_frontmatter(raw)
        if fm.get("status") != "active":
            continue

        confidence = fm.get("confidence", DEFAULT_CONFIDENCE)
        # First line of body as summary
        summary = body.split("\n")[0][:80] if body else "(empty)"
        name_part = md_file.stem.replace("_", " ").title()
        lines.append(
            f"- [{name_part}]({md_file.name}) — {summary} [confidence: {confidence}]"
        )

    index_path = directory / "MEMORY.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Searching ───────────────────────────────────────────────────────

def search_memories(
    query: str,
    agent_name: str = "",
) -> list[dict[str, Any]]:
    """Search agent memories by keyword.

    Args:
        query: Search keywords (case-insensitive substring match on body + frontmatter).
        agent_name: Filter by agent, or empty for all agents + shared.

    Returns:
        List of matching memory dicts with filename, agent, body, confidence.
    """
    results: list[dict[str, Any]] = []
    query_lower = query.lower()

    dirs_to_search: list[tuple[str, Path]] = []
    if agent_name:
        dirs_to_search.append((agent_name, _agent_dir(agent_name)))
        if agent_name != "shared":
            dirs_to_search.append(("shared", _agent_dir("shared")))
    else:
        for name in AGENT_NAMES:
            dirs_to_search.append((name, _agent_dir(name)))

    for name, directory in dirs_to_search:
        for m in _load_memories_from_dir(directory):
            searchable = f"{m['body']} {m['frontmatter']}".lower()
            if query_lower in searchable:
                results.append({
                    "agent": name,
                    "filename": m["filename"],
                    "body": m["body"],
                    "confidence": m["confidence"],
                    "type": m["frontmatter"].get("type", ""),
                    "resource_pattern": m["frontmatter"].get("resource_pattern", ""),
                })

    # Sort by confidence descending
    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results


# ── System prompt hot-reload ────────────────────────────────────────

def rebuild_prompt_with_memory(current_prompt: str, memory_block: str) -> str:
    """Replace the memory section in a system prompt, or append if absent.

    Looks for MEMORY_MARKER_START..MEMORY_MARKER_END in *current_prompt*
    and replaces it with *memory_block*.  If markers are not found,
    appends the memory block before the Skills Protocol section (or at end).

    Args:
        current_prompt: The current system prompt string.
        memory_block: New memory block from load_agent_memory().

    Returns:
        Updated system prompt.
    """
    if MEMORY_MARKER_START in current_prompt:
        # Replace existing memory block
        pattern = re.escape(MEMORY_MARKER_START) + r".*?" + re.escape(MEMORY_MARKER_END)
        return re.sub(pattern, memory_block, current_prompt, flags=re.DOTALL)

    # No existing block — insert before Skills Protocol or append
    skills_marker = "AGENT SKILLS PROTOCOL:"
    if skills_marker in current_prompt:
        idx = current_prompt.index(skills_marker)
        return current_prompt[:idx] + memory_block + "\n\n" + current_prompt[idx:]

    return current_prompt + "\n\n" + memory_block


# ── List memories for API ───────────────────────────────────────────

def list_memories(
    agent_name: str = "",
    status_filter: str = "active",
) -> list[dict[str, Any]]:
    """List memories with metadata for API responses.

    Args:
        agent_name: Filter by agent, or empty for all.
        status_filter: "active", "archived", or "all".

    Returns:
        List of memory metadata dicts.
    """
    results: list[dict[str, Any]] = []

    dirs_to_search: list[tuple[str, Path]] = []
    if agent_name:
        dirs_to_search.append((agent_name, _agent_dir(agent_name)))
    else:
        for name in AGENT_NAMES:
            dirs_to_search.append((name, _agent_dir(name)))

    for name, directory in dirs_to_search:
        if not directory.is_dir():
            continue
        for md_file in sorted(directory.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            try:
                raw = md_file.read_text(encoding="utf-8")
            except OSError:
                continue

            fm, body = parse_frontmatter(raw)
            file_status = fm.get("status", "active")
            if status_filter != "all" and file_status != status_filter:
                continue

            summary = body.split("\n")[0][:120] if body else ""
            results.append({
                "agent": name,
                "filename": md_file.name,
                "type": fm.get("type", ""),
                "status": file_status,
                "confidence": fm.get("confidence", DEFAULT_CONFIDENCE),
                "source": fm.get("source", ""),
                "resource_pattern": fm.get("resource_pattern", ""),
                "related_issue_id": fm.get("related_issue_id"),
                "summary": summary,
                "created_at": str(fm.get("created_at", "")),
                "last_confirmed": str(fm.get("last_confirmed", "")),
            })

    return results
