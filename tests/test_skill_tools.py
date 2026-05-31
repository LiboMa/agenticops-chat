"""Tests for agenticops.skills.tools — targeting uncovered lines."""

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helper SkillMetadata ─────────────────────────────────────────────

@dataclass
class _FakeSkill:
    name: str
    description: str
    path: Path
    tools: list = field(default_factory=list)
    is_draft: bool = False


# ── list_skills ──────────────────────────────────────────────────────

class TestListSkills:
    """Cover list_skills lines 40-63."""

    @patch("agenticops.skills.tools.discover_skills")
    def test_no_skills(self, mock_discover):
        from agenticops.skills.tools import list_skills

        mock_discover.return_value = []
        result = list_skills()
        assert "No skills installed" in result

    @patch("agenticops.skills.tools.discover_skills")
    def test_skills_with_refs_and_tools(self, mock_discover):
        from agenticops.skills.tools import list_skills
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "linux-admin"
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(parents=True)
            (refs_dir / "proc.md").write_text("# Proc")
            (refs_dir / "net.md").write_text("# Net")

            mock_discover.return_value = [
                _FakeSkill(
                    name="linux-admin",
                    description="Linux administration skill",
                    path=skill_dir,
                    tools=["my_tool"],
                    is_draft=False,
                )
            ]
            result = list_skills()
            assert "linux-admin" in result
            assert "References: 2" in result
            assert "Dynamic tools: 1" in result

    @patch("agenticops.skills.tools.discover_skills")
    def test_draft_skills(self, mock_discover):
        from agenticops.skills.tools import list_skills
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_discover.return_value = [
                _FakeSkill(
                    name="draft-skill",
                    description="WIP",
                    path=Path(tmpdir),
                    is_draft=True,
                )
            ]
            result = list_skills()
            assert "[DRAFT]" in result
            assert "1 draft" in result


# ── activate_skill ───────────────────────────────────────────────────

class TestActivateSkill:
    """Cover activate_skill lines 84-130."""

    @patch("agenticops.skills.tools.discover_skills")
    @patch("agenticops.skills.tools.load_skill_body", return_value=None)
    def test_skill_not_found(self, mock_load, mock_discover):
        from agenticops.skills.tools import activate_skill

        mock_discover.return_value = [
            _FakeSkill(name="linux-admin", description="LA", path=Path("/tmp"))
        ]
        result = activate_skill(skill_name="nonexistent")
        assert "not found" in result
        assert "linux-admin" in result

    @patch("agenticops.skills.tools.discover_skills")
    @patch("agenticops.skills.tools.load_skill_body", return_value="# Decision Tree\n- Check CPU")
    def test_activate_success_no_agent(self, mock_load, mock_discover):
        from agenticops.skills.tools import activate_skill
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir)
            refs_dir = skill_dir / "references"
            refs_dir.mkdir()
            (refs_dir / "net.md").write_text("# Net")

            mock_discover.return_value = [
                _FakeSkill(name="linux-admin", description="LA", path=skill_dir)
            ]
            result = activate_skill(skill_name="linux-admin")
            assert "Decision Tree" in result
            assert "references/net.md" in result
            assert "decision trees above" in result

    @patch("agenticops.skills.tools.resolve_skill_tools")
    @patch("agenticops.skills.tools.discover_skills")
    @patch("agenticops.skills.tools.load_skill_body", return_value="# Skill Body")
    def test_activate_with_agent_tools(self, mock_load, mock_discover, mock_resolve):
        from agenticops.skills.tools import activate_skill
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_discover.return_value = [
                _FakeSkill(name="os-op", description="OS", path=Path(tmpdir))
            ]

            mock_tool = MagicMock()
            mock_tool.tool_name = "read_file"
            mock_resolve.return_value = [mock_tool]

            agent = MagicMock()
            agent.tool_registry.registry = {}  # not yet registered

            result = activate_skill(skill_name="os-op", agent=agent)
            assert "read_file" in result
            assert "Dynamically registered" in result
            agent.tool_registry.process_tools.assert_called_once()

    @patch("agenticops.skills.tools.resolve_skill_tools")
    @patch("agenticops.skills.tools.discover_skills")
    @patch("agenticops.skills.tools.load_skill_body", return_value="# Skill Body")
    def test_activate_tool_already_registered(self, mock_load, mock_discover, mock_resolve):
        from agenticops.skills.tools import activate_skill
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_discover.return_value = [
                _FakeSkill(name="os-op", description="OS", path=Path(tmpdir))
            ]

            mock_tool = MagicMock()
            mock_tool.tool_name = "read_file"
            mock_resolve.return_value = [mock_tool]

            agent = MagicMock()
            agent.tool_registry.registry = {"read_file": mock_tool}

            result = activate_skill(skill_name="os-op", agent=agent)
            assert "read_file" in result
            # Should NOT call process_tools since tool already registered
            agent.tool_registry.process_tools.assert_not_called()

    @patch("agenticops.skills.tools.resolve_skill_tools")
    @patch("agenticops.skills.tools.discover_skills")
    @patch("agenticops.skills.tools.load_skill_body", return_value="# Skill Body")
    def test_activate_tool_registration_fails(self, mock_load, mock_discover, mock_resolve):
        from agenticops.skills.tools import activate_skill
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_discover.return_value = [
                _FakeSkill(name="os-op", description="OS", path=Path(tmpdir))
            ]

            mock_tool = MagicMock()
            mock_tool.tool_name = "bad_tool"
            mock_resolve.return_value = [mock_tool]

            agent = MagicMock()
            agent.tool_registry.registry = {}
            agent.tool_registry.process_tools.side_effect = Exception("bad tool")

            result = activate_skill(skill_name="os-op", agent=agent)
            # Should still return the skill body, just no tools_info
            assert "Skill Body" in result


# ── read_skill_reference ─────────────────────────────────────────────

class TestReadSkillReference:
    """Cover read_skill_reference lines 152-159."""

    @patch("agenticops.skills.tools._load_ref", return_value=None)
    def test_reference_not_found(self, mock_ref):
        from agenticops.skills.tools import read_skill_reference

        result = read_skill_reference(
            skill_name="linux-admin", reference_path="references/nonexistent.md"
        )
        assert "not found" in result

    @patch("agenticops.skills.tools._load_ref", return_value="# Process Management\nUse ps aux")
    def test_reference_found(self, mock_ref):
        from agenticops.skills.tools import read_skill_reference

        result = read_skill_reference(
            skill_name="linux-admin", reference_path="references/proc.md"
        )
        assert "Process Management" in result
        assert '<skill_reference skill="linux-admin"' in result


# ── create_skill ─────────────────────────────────────────────────────

class TestCreateSkill:
    """Cover create_skill lines 177-191."""

    @patch("agenticops.skills.tools.discover_skills", return_value=[])
    def test_create_skill_success(self, mock_discover):
        from agenticops.skills.tools import create_skill

        with patch("agenticops.skills.evolution.generate_skill_from_description") as mock_gen, \
             patch("agenticops.skills.evolution.create_draft_skill") as mock_create, \
             patch("agenticops.skills.loader._invalidate_skills_cache"):
            mock_gen.return_value = {
                "name": "redis-admin",
                "description": "Redis admin skill",
                "content": "# Redis\n- Check memory",
                "references": None,
            }
            mock_create.return_value = Path("/tmp/skills/redis-admin")

            result = create_skill(name="redis-admin", description="Redis admin skill")
            assert "redis-admin" in result
            assert "created" in result

    @patch("agenticops.skills.tools.discover_skills", return_value=[])
    def test_create_skill_generation_error(self, mock_discover):
        from agenticops.skills.tools import create_skill

        with patch("agenticops.skills.evolution.generate_skill_from_description") as mock_gen:
            mock_gen.return_value = {"error": "LLM unavailable"}
            result = create_skill(name="x", description="x")
            assert "Failed" in result


# ── improve_skill ────────────────────────────────────────────────────

class TestImproveSkill:
    """Cover improve_skill lines 211-219."""

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
            mock_improve.return_value = {"error": "skill not found"}
            result = improve_skill(skill_name="bad", improvement="x")
            assert "Failed" in result


# ── search_skill_registry ────────────────────────────────────────────

class TestSearchSkillRegistry:
    """Cover search_skill_registry lines 239-249."""

    def test_search_no_results(self):
        from agenticops.skills.tools import search_skill_registry

        with patch("agenticops.skills.registry.search_skills", return_value=[]):
            result = search_skill_registry(query="unicorn")
            assert "No skills found" in result

    def test_search_with_results(self):
        from agenticops.skills.tools import search_skill_registry

        with patch("agenticops.skills.registry.search_skills") as mock_search:
            mock_search.return_value = [
                {"name": "linux-admin", "source": "local", "description": "Linux admin skill"},
                {"name": "k8s-admin", "source": "clawhub", "description": "K8s management"},
            ]
            result = search_skill_registry(query="admin")
            assert "2 found" in result
            assert "linux-admin [local]" in result
            assert "k8s-admin [clawhub]" in result


# ── improve_skill ────────────────────────────────────────────────────


class TestImproveSkill:
    """Cover improve_skill improvement_store wiring."""

    def test_improve_skill_records_to_store(self, monkeypatch):
        recorded = {}
        def _add(skill_name, improvement, **kw):
            recorded["skill"] = skill_name
            recorded["status"] = kw.get("status")
            recorded["source"] = kw.get("source")
            return {"id": "rec1"}
        def _upd(rid, status, result=None):
            recorded["final"] = status
            recorded["rid"] = rid
            return {"id": rid}
        monkeypatch.setattr("agenticops.skills.improvement_store.add_improvement", _add)
        monkeypatch.setattr("agenticops.skills.improvement_store.update_improvement", _upd)
        with patch("agenticops.skills.evolution.auto_improve_skill",
                   return_value={"action": "updated", "skill_name": "redis", "draft_path": "/x"}):
            from agenticops.skills.tools import improve_skill
            out = improve_skill("redis", "add cluster failover")
        assert recorded.get("skill") == "redis"
        assert recorded.get("final") == "completed"
        assert recorded.get("rid") == "rec1"

    def test_improve_skill_records_failure(self, monkeypatch):
        recorded = {}
        monkeypatch.setattr("agenticops.skills.improvement_store.add_improvement",
                            lambda skill_name, improvement, **kw: {"id": "rec2"})
        def _upd(rid, status, result=None):
            recorded["final"] = status
        monkeypatch.setattr("agenticops.skills.improvement_store.update_improvement", _upd)
        with patch("agenticops.skills.evolution.auto_improve_skill",
                   return_value={"error": "skill not found"}):
            from agenticops.skills.tools import improve_skill
            out = improve_skill("ghost", "x")
        assert "Failed to improve" in out
        assert recorded.get("final") == "failed"
