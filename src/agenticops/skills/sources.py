"""Skill ingestion from wide sources — URL / git repo / zip archive.

Human-driven only: agents get no import tool. Every imported package lands as
a DRAFT (never published, never injected into a prompt, never executed), so the
existing draft -> review -> promote -> .archive chain stays the single approval
path. Nothing inside an imported package is ever run during import.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agenticops.config import settings
from agenticops.skills.curator import _write_skill_md
from agenticops.skills.loader import (
    _invalidate_skills_cache,
    _validate_skill_name,
    normalize_skill_frontmatter,
    parse_frontmatter,
)

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


@dataclass
class ImportedSkill:
    name: str
    path: Path
    files: int
    bytes: int


@dataclass
class ImportResult:
    source_uri: str
    source_ref: str
    installed: list[ImportedSkill] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)


class _Reject(Exception):
    """A package failed validation — record it and move to the next one."""


def _package_files(pkg_dir: Path) -> list[Path]:
    """Every regular file in the package. Rejects symlinks, specials, escapes."""
    root = pkg_dir.resolve()
    out: list[Path] = []
    for p in sorted(pkg_dir.rglob("*")):
        rel = p.relative_to(pkg_dir)
        if p.is_symlink():
            raise _Reject(f"symlink not allowed: {rel}")
        if p.is_dir():
            continue
        if not p.is_file():
            raise _Reject(f"not a regular file: {rel}")
        if not str(p.resolve()).startswith(str(root) + os.sep):
            raise _Reject(f"path escapes package root: {rel}")
        out.append(p)
    return out


def _validate_package(pkg_dir: Path) -> list[Path]:
    files = _package_files(pkg_dir)
    max_files = settings.skills_import_max_files
    if len(files) > max_files:
        raise _Reject(f"too many files: {len(files)} > {max_files}")
    cap = settings.skills_import_max_package_bytes
    total = sum(f.stat().st_size for f in files)
    if total > cap:
        raise _Reject(f"package too large: {total} > {cap} bytes")
    allowed = {e.lower() for e in settings.skills_import_allowed_extensions}
    for f in files:
        if f.suffix.lower() not in allowed:
            raise _Reject(f"file type not allowed: {f.relative_to(pkg_dir)}")
    return files


def _stamp_provenance(pkg_dir: Path, name: str, source_uri: str, source_ref: str) -> None:
    """Rewrite SKILL.md frontmatter with import provenance (created_by=imported)."""
    fm, body = parse_frontmatter((pkg_dir / "SKILL.md").read_text(encoding="utf-8"))
    fm = normalize_skill_frontmatter(fm)
    fm["name"] = name
    fm["created_by"] = "imported"
    fm["status"] = "active"
    fm["source_uri"] = source_uri
    fm["source_ref"] = source_ref
    fm["imported_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_skill_md(pkg_dir, fm, body)


def _install_one(pkg_dir: Path, name: str, source_uri: str, source_ref: str) -> ImportedSkill:
    """Copy a validated package into skills_draft_dir/<name> atomically."""
    files = _validate_package(pkg_dir)
    staging_root = settings.skills_draft_dir / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = staging_root / f"{name}-{uuid.uuid4().hex[:8]}"
    try:
        total = 0
        for f in files:
            dst = staging / f.relative_to(pkg_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = f.read_bytes()
            dst.write_bytes(data)
            os.chmod(dst, 0o644)          # never executable — the sandbox names the interpreter
            total += len(data)
        _stamp_provenance(staging, name, source_uri, source_ref)
        target = settings.skills_draft_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)       # atomic — no half-installed state
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return ImportedSkill(name=name, path=target, files=len(files), bytes=total)


def install_packages(
    pkgs: list[Path],
    source_uri: str,
    source_ref: str,
    names: list[str] | None = None,
) -> ImportResult:
    """Install discovered packages as DRAFTS. Per-package fail-soft, security fail-closed."""
    result = ImportResult(source_uri=source_uri, source_ref=source_ref)
    wanted = set(names) if names else None

    for pkg in pkgs:
        try:
            fm, _ = parse_frontmatter((pkg / "SKILL.md").read_text(encoding="utf-8"))
        except Exception as e:
            result.rejected.append((str(pkg), f"unreadable SKILL.md: {e}"))
            continue

        raw_name = (fm.get("name") if isinstance(fm, dict) else None) or pkg.name
        name = str(raw_name).strip()
        # R2: validate against the DESTINATION dir — the archive's own dir name is not ours
        if not _validate_skill_name(name, settings.skills_draft_dir / name):
            result.rejected.append((name[:64] or str(pkg), "invalid skill name"))
            continue

        if wanted is not None and name not in wanted:
            result.skipped.append((name, "not in requested names"))
            continue
        if (settings.skills_draft_dir / name).exists():
            result.skipped.append((name, "draft already exists — reject the old draft first"))
            continue
        if (settings.skills_dir / name).exists():
            result.skipped.append((name, "already published — use improve_skill, or rollback first"))
            continue

        try:
            result.installed.append(_install_one(pkg, name, source_uri, source_ref))
        except _Reject as e:
            result.rejected.append((name, str(e)))
        except Exception as e:
            logger.warning("Import of skill '%s' failed: %s", name, e)
            result.rejected.append((name, f"install failed: {e}"))

    if result.installed:
        _invalidate_skills_cache()
    return result
