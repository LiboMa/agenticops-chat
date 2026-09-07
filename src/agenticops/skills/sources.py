"""Skill ingestion from wide sources — URL / git repo / zip archive.

Human-driven only: agents get no import tool. Every imported package lands as
a DRAFT (never published, never injected into a prompt, never executed), so the
existing draft -> review -> promote -> .archive chain stays the single approval
path. Nothing inside an imported package is ever run during import.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories never treated as (or searched for) skill packages.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".archive", ".staging", "draft"}


def discover_packages(root: Path) -> list[Path]:
    """Recursively find every directory holding a SKILL.md.

    A directory that has SKILL.md IS a package and is not descended into (so a
    skill's own references/SKILL.md never becomes a second package). Skips VCS,
    vendor and dot directories. Deterministic (sorted) output.
    """
    found: list[Path] = []

    def walk(d: Path) -> None:
        if (d / "SKILL.md").is_file():
            found.append(d)
            return
        try:
            children = sorted(d.iterdir())
        except OSError as e:
            logger.warning("Cannot list %s during skill discovery: %s", d, e)
            return
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if child.name in _SKIP_DIRS or child.name.startswith("."):
                continue
            walk(child)

    if root.is_dir():
        walk(root)
    return sorted(found)
