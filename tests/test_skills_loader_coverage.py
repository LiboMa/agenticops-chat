"""Tests for skills/loader.py uncovered paths — P2 tech-debt coverage push."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenticops.skills.loader import (
    SkillMetadata,
    _get_max_mtime,
    _invalidate_skills_cache,
    _scan_directory,
    build_available_skills_xml,
    discover_skills,
    get_available_skills_xml,
    load_skill_body,
    load_skill_reference,
    parse_frontmatter,
    resolve_skill_tools,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset module-level caches between tests."""
    _invalidate_skills_cache()
    yield
    _invalidate_skills_cache()


def _make_skill_dir(base: Path, name: str, fm: str, body: str = "# Body") -> Path:
    """Create a minimal skill directory with SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\n{fm}\n---\n{body}")
    return skill_dir


# ── normalize_skill_frontmatter ─────────────────────────────────────


class TestNormalizeSkillFrontmatter:
    def test_backfills_missing_provenance(self):
        from agenticops.skills.loader import normalize_skill_frontmatter
        fm = {"name": "old-skill", "description": "legacy"}
        out = normalize_skill_frontmatter(fm)
        assert out["created_by"] == "user"
        assert out["status"] == "active"
        assert out["skill_version"] == "1.0"

    def test_preserves_existing(self):
        from agenticops.skills.loader import normalize_skill_frontmatter
        fm = {"name": "s", "created_by": "agent", "status": "stale", "skill_version": "1.3"}
        out = normalize_skill_frontmatter(fm)
        assert out["created_by"] == "agent"
        assert out["status"] == "stale"
        assert out["skill_version"] == "1.3"


# ── parse_frontmatter: YAML error ───────────────────────────────────


class TestParseFrontmatterErrors:
    def test_yaml_error_returns_empty(self):
        """Bad YAML in frontmatter → returns empty dict and full content."""
        content = "---\n: :\n  bad: [unclosed\n---\nBody"
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content


# ── _scan_directory edge cases ──────────────────────────────────────


class TestScanDirectory:
    def test_nonexistent_dir_returns_empty(self, tmp_path):
        assert _scan_directory(tmp_path / "nope") == []

    def test_skill_without_description_skipped(self, tmp_path):
        _make_skill_dir(tmp_path, "no-desc", "name: no-desc\n")
        skills = _scan_directory(tmp_path)
        assert len(skills) == 0

    def test_exception_during_load_skipped(self, tmp_path):
        skill_dir = tmp_path / "broken"
        skill_dir.mkdir()
        # Create unreadable SKILL.md by making it a directory
        (skill_dir / "SKILL.md").mkdir()
        skills = _scan_directory(tmp_path)
        assert len(skills) == 0


# ── discover_skills: skills_enabled=False ───────────────────────────


class TestDiscoverSkillsDisabled:
    def test_returns_empty_when_disabled(self):
        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = False
            result = discover_skills()
            assert result == []

    def test_cache_hit_returns_same_list(self, tmp_path):
        """Second call with same mtime returns cached result."""
        _make_skill_dir(tmp_path, "alpha", "name: alpha\ndescription: test skill")
        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"
            first = discover_skills(tmp_path)
            second = discover_skills(tmp_path)
            assert first is second  # Same object → cache hit


# ── load_skill_reference ─────────────────────────────────────────────


class TestLoadSkillReference:
    def test_load_existing_reference(self, tmp_path):
        _make_skill_dir(tmp_path, "ref-skill", "name: ref-skill\ndescription: has refs")
        ref_dir = tmp_path / "ref-skill" / "references"
        ref_dir.mkdir()
        (ref_dir / "guide.md").write_text("# Guide content")

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            result = load_skill_reference("ref-skill", "references/guide.md")
            assert result == "# Guide content"

    def test_path_traversal_blocked(self, tmp_path):
        _make_skill_dir(tmp_path, "safe", "name: safe\ndescription: safe skill")
        (tmp_path / "secret.txt").write_text("secret")

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            result = load_skill_reference("safe", "../secret.txt")
            assert result is None

    def test_nonexistent_reference(self, tmp_path):
        _make_skill_dir(tmp_path, "noref", "name: noref\ndescription: no refs")

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            result = load_skill_reference("noref", "missing.md")
            assert result is None

    def test_unknown_skill_returns_none(self, tmp_path):
        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            result = load_skill_reference("nonexistent", "anything.md")
            assert result is None


# ── resolve_skill_tools ──────────────────────────────────────────────


class TestResolveSkillTools:
    def test_no_tools_declared(self, tmp_path):
        _make_skill_dir(tmp_path, "notool", "name: notool\ndescription: no tools")

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            result = resolve_skill_tools("notool")
            assert result == []

    def test_resolve_valid_tool(self, tmp_path):
        fm = "name: toolskill\ndescription: has tools\ntools:\n  - os.path.join"
        _make_skill_dir(tmp_path, "toolskill", fm)

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            result = resolve_skill_tools("toolskill")
            assert len(result) == 1
            import os.path
            assert result[0] is os.path.join

    def test_resolve_bad_tool_path_skipped(self, tmp_path):
        fm = "name: badtool\ndescription: broken tool\ntools:\n  - nonexistent.module.func"
        _make_skill_dir(tmp_path, "badtool", fm)

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            result = resolve_skill_tools("badtool")
            assert result == []

    def test_unknown_skill_returns_empty(self, tmp_path):
        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            result = resolve_skill_tools("ghost")
            assert result == []


# ── get_available_skills_xml cache ───────────────────────────────────


class TestGetAvailableSkillsXmlCache:
    def test_cached_xml_returned(self, tmp_path):
        _make_skill_dir(tmp_path, "xmlskill", "name: xmlskill\ndescription: XML test skill")

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"

            first = get_available_skills_xml()
            assert "xmlskill" in first
            # Second call should use XML cache
            second = get_available_skills_xml()
            assert first == second
