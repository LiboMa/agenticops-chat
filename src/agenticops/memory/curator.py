"""Hermes-style memory Curator — pure file-metadata lifecycle (zero LLM).

Transitions (by last_used age):
  active --(> stale_days)--> stale --(> stale_days+archive_days)--> archived
Rules:
  - Never delete; archived files move to <agent>/.archive/ (recoverable).
  - Reactivate-on-use is handled at read time (touch_last_used), not here.
  - created_by == "user" memories are exempt from auto-archival (pinned);
    they may go stale (drop out of injection) but are never moved to .archive.
"""

from __future__ import annotations

import logging
from datetime import date

from agenticops.memory.agent_memory import (
    AGENT_NAMES,
    _agent_dir,
    _atomic_write_text,
    _serialize_frontmatter,
    normalize_frontmatter,
    parse_frontmatter,
    update_memory_index,
)

logger = logging.getLogger(__name__)


def _days_since(iso: str, today: date) -> int:
    try:
        y, m, d = (int(x) for x in str(iso)[:10].split("-"))
        return (today - date(y, m, d)).days
    except (ValueError, TypeError):
        return 0


def run_curator(stale_days: int = 30, archive_days: int = 60, today: date | None = None) -> dict:
    """Advance memory lifecycle states across all agents. Returns a summary dict."""
    today = today or date.today()
    summary = {"staled": 0, "archived": 0, "scanned": 0}

    for agent in AGENT_NAMES:
        directory = _agent_dir(agent)
        if not directory.is_dir():
            continue
        touched = False
        for md in sorted(directory.glob("*.md")):
            if md.name == "MEMORY.md":
                continue
            try:
                raw = md.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, body = parse_frontmatter(raw)
            fm = normalize_frontmatter(fm)
            summary["scanned"] += 1
            age = _days_since(fm["last_used"], today)
            status = fm.get("status", "active")
            pinned = fm.get("created_by") == "user"

            if status == "active" and age > stale_days:
                fm["status"] = "stale"
                _atomic_write_text(md, _serialize_frontmatter(fm, body))
                summary["staled"] += 1
                touched = True
            elif status == "stale" and age > (stale_days + archive_days) and not pinned:
                # Move to .archive/ (pure prune; merges set absorbed_into elsewhere)
                archive_dir = directory / ".archive"
                archive_dir.mkdir(exist_ok=True)
                fm["status"] = "archived"
                fm.setdefault("absorbed_into", "")
                _atomic_write_text(archive_dir / md.name, _serialize_frontmatter(fm, body))
                md.unlink()
                summary["archived"] += 1
                touched = True

        if touched:
            update_memory_index(agent)

    logger.info("Curator run: %s", summary)
    return summary


def maybe_run_curator() -> dict | None:
    """Run the Curator if enabled in settings. Cheap, safe to call at agent build."""
    from agenticops.config import settings
    if not getattr(settings, "memory_curator_enabled", True):
        return None
    return run_curator(
        stale_days=getattr(settings, "memory_stale_days", 30),
        archive_days=getattr(settings, "memory_archive_days", 60),
    )
