"""Skill review — list, review, promote, and reject draft skills.

Provides functions for reviewing draft skills before promoting them
to the main skills directory. Promotion moves the skill directory
from draft/ to skills/ with optional backup of existing skills.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from agenticops.config import settings
from agenticops.skills.loader import (
    SkillMetadata,
    discover_skills,
    parse_frontmatter,
    _invalidate_skills_cache,
)

logger = logging.getLogger(__name__)


def list_draft_skills() -> list[SkillMetadata]:
    """Return only draft skills from the discovered skill list."""
    return [s for s in discover_skills() if s.is_draft]


def review_draft_skill(name: str) -> dict | None:
    """Review a draft skill by comparing it to any existing published version.

    Args:
        name: Name of the draft skill to review.

    Returns:
        Dict with draft_content, published_content (if exists), and diff_summary.
        None if draft not found.
    """
    draft_dir = settings.skills_draft_dir / name
    draft_md = draft_dir / "SKILL.md"
    if not draft_md.is_file():
        return None

    draft_content = draft_md.read_text(encoding="utf-8")
    _, draft_body = parse_frontmatter(draft_content)

    # Check for existing published version
    published_dir = settings.skills_dir / name
    published_md = published_dir / "SKILL.md"
    published_content = None
    published_body = None
    if published_md.is_file():
        published_content = published_md.read_text(encoding="utf-8")
        _, published_body = parse_frontmatter(published_content)

    # Build diff summary
    if published_body is not None:
        draft_lines = set(draft_body.strip().splitlines())
        pub_lines = set(published_body.strip().splitlines())
        added = len(draft_lines - pub_lines)
        removed = len(pub_lines - draft_lines)
        diff_summary = f"+{added} lines added, -{removed} lines removed vs published"
    else:
        line_count = len(draft_body.strip().splitlines())
        diff_summary = f"New skill — {line_count} lines (no published version)"

    return {
        "name": name,
        "draft_content": draft_content,
        "published_content": published_content,
        "diff_summary": diff_summary,
        "is_new": published_content is None,
    }


def promote_skill(name: str) -> bool:
    """Promote a draft skill to published.

    Security-scans the draft first (skills are executable); a blocked-tier
    command in its body aborts promotion. Any existing published version is
    archived to skills/.archive/<name>__<timestamp>/ (multi-generation,
    recoverable via rollback_skill) instead of a single lossy .bak.

    Args:
        name: Name of the draft skill to promote.

    Returns:
        True if promoted, False if draft not found or it failed the security scan.
    """
    draft_dir = settings.skills_draft_dir / name
    draft_md = draft_dir / "SKILL.md"
    if not draft_md.is_file():
        logger.warning("Draft skill '%s' not found at %s", name, draft_dir)
        return False

    # Security gate — skills are executable (run_on_host/run_kubectl)
    if getattr(settings, "skills_security_scan_on_promote", True):
        from agenticops.skills.security import scan_skill_safety
        _, body = parse_frontmatter(draft_md.read_text(encoding="utf-8"))
        scan = scan_skill_safety(body)
        if not scan["safe"]:
            logger.warning("Skill '%s' failed security scan, NOT promoted: %s", name, scan["findings"])
            return False

    target_dir = settings.skills_dir / name

    # Archive existing published version (multi-generation, recoverable)
    if target_dir.is_dir():
        archive_root = settings.skills_dir / ".archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        backup_dir = archive_root / f"{name}__{ts}"
        target_dir.rename(backup_dir)
        logger.info("Archived previous '%s' to %s", name, backup_dir)

    shutil.move(str(draft_dir), str(target_dir))
    _invalidate_skills_cache()
    logger.info("Promoted draft skill '%s' to %s", name, target_dir)
    return True


def rollback_skill(name: str) -> bool:
    """Restore the most recent archived version of a published skill.

    Moves the newest skills/.archive/<name>__<timestamp>/ back to published.
    Any current published version is itself archived first (so rollback is
    reversible). Returns True if an archived version was found.
    """
    archive_root = settings.skills_dir / ".archive"
    candidates = sorted(archive_root.glob(f"{name}__*")) if archive_root.is_dir() else []
    # exclude any rolledback-marked dirs from being treated as the source to restore
    candidates = [c for c in candidates if "__rolledback-" not in c.name]
    if not candidates:
        return False
    latest = candidates[-1]   # timestamp-sorted, newest last
    target_dir = settings.skills_dir / name
    if target_dir.is_dir():
        ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        target_dir.rename(archive_root / f"{name}__rolledback-{ts}")
    shutil.move(str(latest), str(target_dir))
    _invalidate_skills_cache()
    logger.info("Rolled back '%s' from %s", name, latest)
    return True


def reject_draft_skill(name: str) -> bool:
    """Delete a draft skill.

    Args:
        name: Name of the draft skill to reject/delete.

    Returns:
        True if deleted, False if not found.
    """
    draft_dir = settings.skills_draft_dir / name
    if not draft_dir.is_dir():
        logger.warning("Draft skill '%s' not found at %s", name, draft_dir)
        return False

    shutil.rmtree(draft_dir)
    _invalidate_skills_cache()
    logger.info("Rejected and deleted draft skill '%s'", name)
    return True
