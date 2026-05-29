"""Tests for src/agenticops/skills/tools.py — targeting uncovered lines."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


# ---------------------------------------------------------------------------
# list_skills
# ---------------------------------------------------------------------------

class TestListSkills:
    """Cover list_skills tool function."""

    @patch("agenticops.skills.tools.discover_skills")
    def test_list_skills_empty(self, mock_discover):
        from agenticops.skills.tools import list_skills
        mock_discover.return_value = []
        result = list_skills()
        assert "No skills installed" in result

    @patch("agenticops.skills.tools.discover_skills")
    def test_list_skills_with_skills(self, mock_discover):
        from agenticops.skills.tools import list_skills

        skill = MagicMock()
        skill.name = "linux-admin"
        skill.description = "Linux administration diagnostics"
        skill.is_draft = False
        skill.path = Path("/tmp/skills/linux-admin")
        skill.tools = []

        refs_dir = skill.path / "references"
        # Simulate no references dir
        with patch.object(Path, "is_dir", return_value=False):
            mock_discover.return_value = [skill]
            result = list_skills()
            assert "linux-admin" in result
            assert "Available Skills" in result

    @patch("agenticops.skills.tools.discover_skills")
    def test_list_skills_with_drafts_and_tools(self, mock_discover):
        from agenticops.skills.tools import list_skills

        skill = MagicMock()
        skill.name = "redis-admin"
        skill.description = "Redis troubleshooting"
        skill.is_draft = True
        skill.tools = ["tool_a", "tool_b"]
        skill.path = MagicMock()
        refs_dir = MagicMock()
        refs_dir.is_dir.return_value = True
        refs_dir.glob.return_value = [Path("a.md"), Path("b.md")]
        skill.path.__truediv__ = MagicMock(return_value=refs_dir)

        mock_discover.return_value = [skill]
        result = list_skills()
        assert "[DRAFT]" in result
        assert "Dynamic tools: 2" in result
        assert "References: 2" in result


# ---------------------------------------------------------------------------
# activate_skill
# ---------------------------------------------------------------------------

class TestActivateSkill:
    """Cover activate_skill tool function."""

    @patch("agenticops.skills.tools.discover_skills")
    @patch("agenticops.skills.tools.load_skill_body")
    def test_skill_not_found(self, mock_load, mock_discover):
        from agenticops.skills.tools import activate_skill

        mock_load.return_value = None
        skill = MagicMock()
        skill.name = "linux-admin"
        mock_discover.return_value = [skill]

        result = activate_skill(skill_name="nonexistent")
        assert "not found" in result
        assert "linux-admin" in result

    @patch("agenticops.skills.tools.resolve_skill_tools")
    @patch("agenticops.skills.tools.discover_skills")
    @patch("agenticops.skills.tools.load_skill_body")
    def test_activate_with_agent_and_tools(self, mock_load, mock_discover, mock_resolve):
        from agenticops.skills.tools import activate_skill

        mock_load.return_value = "# Skill content\nDecision tree here"

        skill = MagicMock()
        skill.name = "linux-admin"
        skill.path = MagicMock()
        refs_dir = MagicMock()
        refs_dir.is_dir.return_value = True
        refs_dir.glob.return_value = [Path("proc.md")]
        skill.path.__truediv__ = MagicMock(return_value=refs_dir)
        mock_discover.return_value = [skill]

        # Mock agent with tool_registry
        agent = MagicMock()
        agent.tool_registry.registry = {}

        tool_fn = MagicMock()
        tool_fn.tool_name = "check_process"
        mock_resolve.return_value = [tool_fn]

        result = activate_skill(skill_name="linux-admin", agent=agent)
        assert "activated_skill" in result
        assert "Dynamically registered tools" in result
        assert "check_process" in result
        agent.tool_registry.process_tools.assert_called_once_with([tool_fn])

    @patch("agenticops.skills.tools.resolve_skill_tools")
    @patch("agenticops.skills.tools.discover_skills")
    @patch("agenticops.skills.tools.load_skill_body")
    def test_activate_tool_registration_failure(self, mock_load, mock_discover, mock_resolve):
        from agenticops.skills.tools import activate_skill

        mock_load.return_value = "# Skill content"
        skill = MagicMock()
        skill.name = "test-skill"
        skill.path = MagicMock()
        refs_dir = MagicMock()
        refs_dir.is_dir.return_value = False
        skill.path.__truediv__ = MagicMock(return_value=refs_dir)
        mock_discover.return_value = [skill]

        agent = MagicMock()
        agent.tool_registry.registry = {}
        agent.tool_registry.process_tools.side_effect = RuntimeError("fail")

        tool_fn = MagicMock()
        tool_fn.tool_name = "bad_tool"
        mock_resolve.return_value = [tool_fn]

        # Should not crash even if tool registration fails
        result = activate_skill(skill_name="test-skill", agent=agent)
        assert "activated_skill" in result


# ---------------------------------------------------------------------------
# read_skill_reference
# ---------------------------------------------------------------------------

class TestReadSkillReference:
    """Cover read_skill_reference tool function."""

    @patch("agenticops.skills.tools._load_ref")
    def test_reference_not_found(self, mock_load):
        from agenticops.skills.tools import read_skill_reference
        mock_load.return_value = None
        result = read_skill_reference(skill_name="linux-admin", reference_path="references/missing.md")
        assert "not found" in result

    @patch("agenticops.skills.tools._load_ref")
    def test_reference_found(self, mock_load):
        from agenticops.skills.tools import read_skill_reference
        mock_load.return_value = "# Process Management\nDetails here..."
        result = read_skill_reference(skill_name="linux-admin", reference_path="references/proc.md")
        assert "skill_reference" in result
        assert "Process Management" in result


# ---------------------------------------------------------------------------
# create_skill
# ---------------------------------------------------------------------------

class TestCreateSkill:
    """Cover create_skill tool function."""

    @patch("agenticops.skills.tools.discover_skills")
    def test_create_skill_success(self, mock_discover):
        from agenticops.skills.tools import create_skill

        with patch("agenticops.skills.evolution.generate_skill_from_description") as mock_gen, \
             patch("agenticops.skills.evolution.create_draft_skill") as mock_create, \
             patch("agenticops.skills.loader._invalidate_skills_cache"):

            mock_gen.return_value = {
                "name": "redis-admin",
                "description": "Redis troubleshooting skill",
                "content": "# Redis Admin\nDecision tree",
                "references": {"redis-cli.md": "# CLI usage"},
            }
            mock_create.return_value = Path("/tmp/skills/redis-admin")

            result = create_skill(name="redis-admin", description="Redis troubleshooting")
            assert "redis-admin" in result
            assert "created" in result

    @patch("agenticops.skills.tools.discover_skills")
    def test_create_skill_error(self, mock_discover):
        from agenticops.skills.tools import create_skill

        with patch("agenticops.skills.evolution.generate_skill_from_description") as mock_gen:
            mock_gen.return_value = {"error": "LLM unavailable"}
            result = create_skill(name="test", description="test skill")
            assert "Failed" in result


# ---------------------------------------------------------------------------
# improve_skill
# ---------------------------------------------------------------------------

class TestImproveSkill:
    """Cover improve_skill tool function."""

    def test_improve_skill_success(self):
        from agenticops.skills.tools import improve_skill

        with patch("agenticops.skills.evolution.auto_improve_skill") as mock_improve, \
             patch("agenticops.skills.loader._invalidate_skills_cache"):
            mock_improve.return_value = {"draft_path": "/tmp/skills/linux-admin-draft"}
            result = improve_skill(skill_name="linux-admin", improvement="Add systemd section")
            assert "Improved draft" in result

    def test_improve_skill_error(self):
        from agenticops.skills.tools import improve_skill

        with patch("agenticops.skills.evolution.auto_improve_skill") as mock_improve:
            mock_improve.return_value = {"error": "Skill not found"}
            result = improve_skill(skill_name="missing", improvement="anything")
            assert "Failed" in result


# ---------------------------------------------------------------------------
# search_skill_registry
# ---------------------------------------------------------------------------

class TestSearchSkillRegistry:
    """Cover search_skill_registry tool function."""

    def test_search_no_results(self):
        from agenticops.skills.tools import search_skill_registry

        with patch("agenticops.skills.registry.search_skills") as mock_search:
            mock_search.return_value = []
            result = search_skill_registry(query="nonexistent")
            assert "No skills found" in result

    def test_search_with_results(self):
        from agenticops.skills.tools import search_skill_registry

        with patch("agenticops.skills.registry.search_skills") as mock_search:
            mock_search.return_value = [
                {"name": "redis-admin", "source": "local", "description": "Redis troubleshooting"},
                {"name": "k8s-ops", "source": "clawhub", "description": "Kubernetes operations"},
            ]
            result = search_skill_registry(query="redis")
            assert "redis-admin" in result
            assert "[local]" in result
            assert "[clawhub]" in result
