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
    _validate_skill_name,
    build_available_skills_xml,
    discover_skills,
    get_available_skills_xml,
    list_skill_resources,
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

    def test_non_dict_frontmatter_coerced(self):
        """Malformed (non-mapping) frontmatter must not raise — coerce to defaults."""
        from agenticops.skills.loader import normalize_skill_frontmatter
        for bad in ([1, 2, 3], "scalar", 42, None):
            out = normalize_skill_frontmatter(bad)
            assert out["created_by"] == "user"   # pinned default
            assert out["status"] == "active"


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


# ── [AGENT] provenance tag in XML (cycle③ P4) ────────────────────────


class TestAgentTagInXml:
    def test_agent_created_skill_tagged(self):
        human = SkillMetadata(name="human-skill", description="h", path=Path("/tmp/human-skill"),
                              created_by="user")
        agent = SkillMetadata(name="agent-skill", description="a", path=Path("/tmp/agent-skill"),
                             created_by="agent")
        xml = build_available_skills_xml([human, agent])
        assert "[AGENT]" in xml
        # the tag attaches to the agent-created skill line, not the human one
        for line in xml.splitlines():
            if 'name="human-skill"' in line:
                assert "[AGENT]" not in line
            if 'name="agent-skill"' in line:
                assert "[AGENT]" in line

    def test_draft_and_agent_tags_compose(self):
        s = SkillMetadata(name="ag-draft", description="d", path=Path("/tmp/ag-draft"),
                          is_draft=True, created_by="agent")
        xml = build_available_skills_xml([s])
        assert "[DRAFT]" in xml and "[AGENT]" in xml


# ── P0.5 — Strands AgentSkills 借鉴 tests ─────────────────────────────


class TestXmlEscape:
    """A1: XML escape in build_available_skills_xml."""

    def test_description_with_special_chars_escaped(self, tmp_path):
        skill = SkillMetadata(name="alpha", description="Use when foo & bar <baz>", path=tmp_path / "alpha")
        xml = build_available_skills_xml([skill])
        assert "&amp;" in xml
        assert "&lt;baz&gt;" in xml
        assert "<baz>" not in xml

    def test_safe_description_unchanged(self, tmp_path):
        skill = SkillMetadata(name="plain", description="plain description", path=tmp_path / "plain")
        xml = build_available_skills_xml([skill])
        assert "plain description" in xml


class TestYamlColonFallback:
    """A2: parse_frontmatter recovers from values containing colons."""

    def test_value_with_colon_recovers(self):
        content = "---\nname: pdf-skill\ndescription: Use when: the user asks about PDFs\n---\nBody"
        fm, body = parse_frontmatter(content)
        assert fm.get("name") == "pdf-skill"
        assert "Use when" in fm.get("description", "")
        assert body.strip() == "Body"

    def test_truly_broken_yaml_still_returns_empty(self):
        content = "---\n: :\n  bad: [unclosed\n---\nBody"
        fm, body = parse_frontmatter(content)
        assert fm == {}


class TestNameValidation:
    """A3: _validate_skill_name enforces kebab-case + dir match."""

    def test_valid_name(self, tmp_path):
        d = tmp_path / "redis-admin"
        d.mkdir()
        assert _validate_skill_name("redis-admin", d) is True

    def test_uppercase_rejected(self, tmp_path):
        d = tmp_path / "BadName"
        d.mkdir()
        assert _validate_skill_name("BadName", d) is False

    def test_dir_mismatch_rejected(self, tmp_path):
        d = tmp_path / "aaa"
        d.mkdir()
        assert _validate_skill_name("bbb", d) is False

    def test_too_long_rejected(self, tmp_path):
        long = "a" * 65
        d = tmp_path / long
        d.mkdir()
        assert _validate_skill_name(long, d) is False

    def test_consecutive_hyphens_rejected(self, tmp_path):
        d = tmp_path / "a--b"
        d.mkdir()
        assert _validate_skill_name("a--b", d) is False

    def test_scan_skips_invalid_name(self, tmp_path):
        skill_dir = tmp_path / "right"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: wrong\ndescription: x\n---\nBody")
        skills = _scan_directory(tmp_path)
        assert skills == []


class TestListSkillResources:
    """B1: list_skill_resources enumerates scripts/references/assets."""

    def test_lists_references_and_scripts(self, tmp_path):
        _make_skill_dir(tmp_path, "ops", "name: ops\ndescription: ops skill")
        (tmp_path / "ops" / "references").mkdir()
        (tmp_path / "ops" / "references" / "api.md").write_text("# API")
        (tmp_path / "ops" / "scripts").mkdir()
        (tmp_path / "ops" / "scripts" / "run.sh").write_text("#!/bin/sh")

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"
            resources = list_skill_resources("ops")
            assert "references/api.md" in resources
            assert "scripts/run.sh" in resources

    def test_unknown_skill_returns_empty(self, tmp_path):
        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"
            assert list_skill_resources("ghost") == []

    def test_truncates_at_cap(self, tmp_path):
        _make_skill_dir(tmp_path, "many", "name: many\ndescription: many refs")
        refs = tmp_path / "many" / "references"
        refs.mkdir()
        for i in range(25):
            (refs / f"r{i:02d}.md").write_text("x")

        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = True
            mock_settings.skills_dir = tmp_path
            mock_settings.skills_draft_dir = tmp_path / "draft"
            resources = list_skill_resources("many")
            assert len(resources) == 21
            assert resources[-1].startswith("... (truncated")


class TestDescriptionWidening:
    """B2: XML cap raised from 80 → 200 chars; first-sentence split removed."""

    def test_long_description_not_cut_at_80(self, tmp_path):
        skill = SkillMetadata(name="long", description="X" * 150 + " end.", path=tmp_path / "long")
        xml = build_available_skills_xml([skill])
        assert "X" * 150 in xml

    def test_truncated_at_200(self, tmp_path):
        skill = SkillMetadata(name="huge", description="Y" * 300, path=tmp_path / "huge")
        xml = build_available_skills_xml([skill])
        assert "Y" * 200 in xml
        assert "Y" * 201 not in xml

    def test_period_no_longer_truncates(self, tmp_path):
        skill = SkillMetadata(name="multi", description="First. Second.", path=tmp_path / "multi")
        xml = build_available_skills_xml([skill])
        assert "Second" in xml
