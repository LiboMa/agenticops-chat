"""One-time idempotent backfill of cycle② frontmatter fields on existing memories."""

from __future__ import annotations

import logging

from agenticops.memory.agent_memory import (
    AGENT_NAMES, _agent_dir, _atomic_write_text, _serialize_frontmatter,
    normalize_frontmatter, parse_frontmatter,
)

logger = logging.getLogger(__name__)


def backfill_frontmatter() -> int:
    """Add missing last_used/created_by/status to all memory files. Returns count updated."""
    updated = 0
    for agent in AGENT_NAMES:
        directory = _agent_dir(agent)
        if not directory.is_dir():
            continue
        for md in sorted(directory.glob("*.md")):
            if md.name == "MEMORY.md":
                continue
            fm, body = parse_frontmatter(md.read_text(encoding="utf-8"))
            norm = normalize_frontmatter(fm)
            if norm != fm:
                _atomic_write_text(md, _serialize_frontmatter(norm, body))
                updated += 1
    logger.info("Backfilled %d memory files", updated)
    return updated
