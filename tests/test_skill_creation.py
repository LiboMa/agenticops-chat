"""Tests for auto-create skills feature (publish + auto-activate)."""

import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from agenticops.skills.evolution import create_published_skill


def test_create_published_skill_writes_to_skills_dir(tmp_path):
    """Published skill lands in skills_dir, not draft_dir."""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()

    with patch("agenticops.skills.evolution.settings") as mock_settings:
        mock_settings.skills_dir = skill_dir

        path = create_published_skill(
            name="redis-admin",
            description="Redis troubleshooting skill",
            content="# Redis Admin\n\nDiagnostic procedures...",
            references={"troubleshooting.md": "## Steps\n..."},
        )

    assert path == skill_dir / "redis-admin"
    assert (path / "SKILL.md").is_file()
    assert "redis-admin" in (path / "SKILL.md").read_text()
    assert (path / "references" / "troubleshooting.md").is_file()

    shutil.rmtree(path)


def test_create_skill_tool_publish_true_activates(tmp_path):
    """create_skill with publish=True writes to skills_dir and returns activated content."""
    from agenticops.skills.tools import create_skill

    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()

    mock_generate_result = {
        "name": "redis-admin",
        "description": "Redis troubleshooting",
        "content": "# Redis\n\n## Decision Tree\n\nCheck connectivity first.",
        "references": {},
    }

    with patch("agenticops.skills.evolution.generate_skill_from_description", return_value=mock_generate_result), \
         patch("agenticops.skills.evolution.settings") as mock_ev_settings, \
         patch("agenticops.skills.loader.settings") as mock_ld_settings, \
         patch("agenticops.skills.loader._invalidate_skills_cache"):
        mock_ev_settings.skills_dir = skill_dir
        mock_ev_settings.skills_draft_dir = tmp_path / "draft"
        mock_ld_settings.skills_enabled = True
        mock_ld_settings.skills_dir = skill_dir
        mock_ld_settings.skills_draft_dir = tmp_path / "draft"
        mock_ld_settings.skills_max_body_chars = 10000

        # Call the underlying function (bypass @tool decorator)
        result = create_skill._tool_func(
            name="redis-admin",
            description="Redis cluster troubleshooting",
            publish=True,
        )

    assert "redis-admin" in result
    assert "<activated_skill" in result
    assert "Decision Tree" in result


def test_activate_skill_not_found_suggests_creation():
    """activate_skill returns guidance to create when skill not found."""
    from agenticops.skills.tools import activate_skill

    with patch("agenticops.skills.tools.load_skill_body", return_value=None), \
         patch("agenticops.skills.tools.discover_skills", return_value=[]):
        result = activate_skill._tool_func(skill_name="redis-admin")

    assert "not found" in result.lower()
    assert "create_skill" in result
    assert "redis-admin" in result


def test_skills_protocol_mentions_creation():
    """SKILLS_USAGE_PROTOCOL includes guidance about creating new skills."""
    from agenticops.agents.preamble import SKILLS_USAGE_PROTOCOL

    assert "create_skill" in SKILLS_USAGE_PROTOCOL
    assert "confirm" in SKILLS_USAGE_PROTOCOL.lower()
