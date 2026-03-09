"""Skill registry — local and remote skill search and installation.

Provides a unified interface for discovering skills locally and from
ClawHub (remote registry). ClawHub integration is a placeholder that
wraps the ``clawhub`` CLI tool via subprocess.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agenticops.config import settings
from agenticops.skills.loader import discover_skills, _invalidate_skills_cache

logger = logging.getLogger(__name__)


class SkillRegistry(ABC):
    """Abstract base for skill registries."""

    @abstractmethod
    def search(self, query: str) -> list[dict[str, Any]]:
        """Search for skills matching a query."""
        ...

    @abstractmethod
    def install(self, slug: str) -> Path | None:
        """Install a skill by its identifier."""
        ...

    @abstractmethod
    def inspect(self, slug: str) -> dict[str, Any] | None:
        """Get detailed info about a skill."""
        ...


class LocalRegistry(SkillRegistry):
    """Searches local skills/ and draft/ directories."""

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search local skills by name or description substring."""
        query_lower = query.lower()
        results = []
        for s in discover_skills():
            if query_lower in s.name.lower() or query_lower in s.description.lower():
                results.append({
                    "name": s.name,
                    "description": s.description,
                    "source": "draft" if s.is_draft else "local",
                    "path": str(s.path),
                    "has_tools": bool(s.tools),
                })
        return results

    def install(self, slug: str) -> Path | None:
        """Local skills are already installed — returns path if found."""
        for s in discover_skills():
            if s.name == slug:
                return s.path
        return None

    def inspect(self, slug: str) -> dict[str, Any] | None:
        """Get detailed info about a local skill."""
        for s in discover_skills():
            if s.name == slug:
                refs_dir = s.path / "references"
                ref_files = (
                    [f.name for f in sorted(refs_dir.glob("*.md"))]
                    if refs_dir.is_dir()
                    else []
                )
                return {
                    "name": s.name,
                    "description": s.description,
                    "source": "draft" if s.is_draft else "local",
                    "path": str(s.path),
                    "license": s.license,
                    "compatibility": s.compatibility,
                    "tools": s.tools,
                    "references": ref_files,
                    "is_draft": s.is_draft,
                }
        return None


class ClawHubRegistry(SkillRegistry):
    """Wraps the ``clawhub`` CLI for remote skill registry access.

    This is a placeholder implementation. Requires ``clawhub`` CLI
    to be installed and AIOPS_CLAWHUB_TOKEN to be set.
    """

    def _run_clawhub(self, *args: str) -> dict[str, Any] | None:
        """Run a clawhub CLI command and parse JSON output."""
        if not settings.clawhub_enabled:
            return None

        cmd = ["clawhub", *args, "--format", "json"]
        env = None
        if settings.clawhub_token:
            import os
            env = {**os.environ, "CLAWHUB_TOKEN": settings.clawhub_token}

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            if result.returncode != 0:
                logger.warning("clawhub command failed: %s", result.stderr.strip())
                return None
            return json.loads(result.stdout)
        except FileNotFoundError:
            logger.warning("clawhub CLI not found — install it or disable AIOPS_CLAWHUB_ENABLED")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("clawhub command timed out")
            return None
        except json.JSONDecodeError:
            logger.warning("clawhub returned invalid JSON")
            return None

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search ClawHub registry for skills."""
        data = self._run_clawhub("search", query)
        if not data or "results" not in data:
            return []
        results = []
        for item in data["results"]:
            results.append({
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "source": "clawhub",
                "slug": item.get("slug", ""),
                "author": item.get("author", ""),
                "version": item.get("version", ""),
            })
        return results

    def install(self, slug: str) -> Path | None:
        """Install a skill from ClawHub into the skills directory."""
        target_dir = settings.skills_dir
        data = self._run_clawhub("install", slug, "--dir", str(target_dir))
        if not data or "path" not in data:
            return None
        installed_path = Path(data["path"])
        _invalidate_skills_cache()
        logger.info("Installed skill '%s' from ClawHub to %s", slug, installed_path)
        return installed_path

    def inspect(self, slug: str) -> dict[str, Any] | None:
        """Get detailed info about a ClawHub skill."""
        data = self._run_clawhub("inspect", slug)
        if not data:
            return None
        return {
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "source": "clawhub",
            "slug": data.get("slug", ""),
            "author": data.get("author", ""),
            "version": data.get("version", ""),
            "license": data.get("license", ""),
            "readme": data.get("readme", ""),
        }


# ── Unified search ──────────────────────────────────────────────────

_local_registry = LocalRegistry()
_clawhub_registry = ClawHubRegistry()


def search_skills(query: str, include_remote: bool = True) -> list[dict[str, Any]]:
    """Unified skill search across local and remote registries.

    Args:
        query: Search query string.
        include_remote: Whether to include ClawHub results (default: True).

    Returns:
        List of skill dicts with 'source' indicating origin.
    """
    results = _local_registry.search(query)

    if include_remote and settings.clawhub_enabled:
        remote = _clawhub_registry.search(query)
        # Deduplicate: skip remote skills that match a local name
        local_names = {r["name"] for r in results}
        for r in remote:
            if r["name"] not in local_names:
                results.append(r)

    return results


def install_from_registry(slug: str) -> Path | None:
    """Install a skill from ClawHub registry.

    Args:
        slug: ClawHub skill slug (e.g., 'author/skill-name').

    Returns:
        Path to installed skill directory, or None on failure.
    """
    if not settings.clawhub_enabled:
        logger.warning("ClawHub is disabled — set AIOPS_CLAWHUB_ENABLED=true")
        return None
    return _clawhub_registry.install(slug)
