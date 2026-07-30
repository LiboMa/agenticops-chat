"""Skills Curator — agent-draft lifecycle (pure file metadata, zero LLM).

Mirrors memory/curator.py. Ages UNUSED created_by=agent skills:
  active --(>stale_days)--> stale --(>stale_days+archive_days)--> archived
Rules:
  - Only created_by=agent skills are managed. Human skills (created_by=user)
    are PINNED — never staled, never archived.
  - Never delete; archived skill dirs move to skills/.archive/ (recoverable).
  - Reactivate-on-use handled at read time (touch_skill_used), not here.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import date
from pathlib import Path

import yaml

from agenticops.config import settings
from agenticops.skills.loader import (
    _invalidate_skills_cache,
    normalize_skill_frontmatter,
    parse_frontmatter,
)

logger = logging.getLogger(__name__)


def _days_since(iso: str, today: date) -> int:
    try:
        y, m, d = (int(x) for x in str(iso)[:10].split("-"))
        return (today - date(y, m, d)).days
    except (ValueError, TypeError):
        return 0


def _write_skill_md(skill_dir: Path, fm: dict, body: str) -> None:
    # rstrip the body: parse_frontmatter returns it with its trailing newlines
    # intact, so appending "\n" here grew the file by one blank line on EVERY
    # touch_skill_used (linux-admin had accumulated 276). Unlike the memory
    # module's parser, the skills parser does not strip — so we must.
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    text = f"---\n{fm_str}\n---\n\n{body.rstrip()}\n"
    tmp = skill_dir / ".SKILL.md.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, skill_dir / "SKILL.md")


def _scan_dirs() -> list[Path]:
    """Skill package dirs to consider (published + draft), excluding .archive."""
    dirs = []
    for base in (settings.skills_dir, settings.skills_draft_dir):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and d.name != ".archive" and (d / "SKILL.md").is_file():
                dirs.append(d)
    return dirs


def _find_skill_dir(name: str) -> Path | None:
    """Locate a skill package dir by name (published first, then draft)."""
    for base in (settings.skills_dir, settings.skills_draft_dir):
        d = base / name
        if (d / "SKILL.md").is_file():
            return d
    return None


def touch_skill_used(name: str) -> None:
    """Mark a skill used today; reactivate it if it was a stale agent draft."""
    skill_dir = _find_skill_dir(name)
    if skill_dir is None:
        return
    try:
        fm, body = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    except OSError:
        return
    fm = normalize_skill_frontmatter(fm)
    fm["last_used"] = str(date.today())
    if fm.get("status") == "stale":
        fm["status"] = "active"
    _write_skill_md(skill_dir, fm, body)


def restore_skill(name: str) -> bool:
    """Restore an archived skill from skills/.archive/ back to draft. Returns True if found."""
    archive_dir = settings.skills_dir / ".archive" / name
    if not (archive_dir / "SKILL.md").is_file():
        return False
    fm, body = parse_frontmatter((archive_dir / "SKILL.md").read_text(encoding="utf-8"))
    fm = normalize_skill_frontmatter(fm)
    fm["status"] = "active"
    fm["last_used"] = str(date.today())
    dest = settings.skills_draft_dir / name
    dest.mkdir(parents=True, exist_ok=True)
    _write_skill_md(dest, fm, body)
    for item in archive_dir.iterdir():
        if item.name != "SKILL.md":
            shutil.move(str(item), str(dest / item.name))
    shutil.rmtree(archive_dir)
    _invalidate_skills_cache()
    return True


def run_skills_curator(stale_days: int = 30, archive_days: int = 60, today: date | None = None) -> dict:
    """Advance agent-draft lifecycle. Human skills are pinned. Returns summary."""
    today = today or date.today()
    summary = {"staled": 0, "archived": 0, "scanned": 0, "pinned_skipped": 0}
    archive_root = settings.skills_dir / ".archive"

    for skill_dir in _scan_dirs():
        try:
            fm, body = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
        except OSError:
            continue
        fm = normalize_skill_frontmatter(fm)
        summary["scanned"] += 1

        if fm.get("created_by") != "agent":
            summary["pinned_skipped"] += 1
            continue

        last_used = fm.get("last_used") or fm.get("last_improved_at") or fm.get("created_at")
        age = _days_since(str(last_used), today)
        status = fm.get("status", "active")

        if status == "active" and age > stale_days:
            fm["status"] = "stale"
            _write_skill_md(skill_dir, fm, body)
            summary["staled"] += 1
        elif status == "stale" and age > (stale_days + archive_days):
            fm["status"] = "archived"
            archive_root.mkdir(parents=True, exist_ok=True)
            dest = archive_root / skill_dir.name
            if dest.exists():
                shutil.rmtree(dest)
            _write_skill_md(skill_dir, fm, body)
            shutil.move(str(skill_dir), str(dest))
            summary["archived"] += 1

    if summary["staled"] or summary["archived"]:
        _invalidate_skills_cache()
    logger.info("Skills Curator run: %s", summary)
    return summary


def maybe_run_skills_curator() -> dict | None:
    """Run the skills Curator if enabled. Cheap, safe at agent build."""
    if not getattr(settings, "skills_curator_enabled", True):
        return None
    return run_skills_curator(
        stale_days=getattr(settings, "skills_draft_stale_days", 30),
        archive_days=getattr(settings, "skills_draft_archive_days", 60),
    )


def deprecate_agent_skill(name: str) -> bool:
    """Mark an agent-created skill as deprecated. Refuses on human (pinned) skills."""
    skill_dir = _find_skill_dir(name)
    if skill_dir is None:
        return False
    fm, body = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    fm = normalize_skill_frontmatter(fm)
    if fm.get("created_by") != "agent":
        return False   # pinned human skill — refuse
    fm["status"] = "deprecated"
    _write_skill_md(skill_dir, fm, body)
    _invalidate_skills_cache()
    return True
