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


class TestPromoteMultiGen:
    def _setup(self, tmp_path, monkeypatch):
        sdir = tmp_path / "skills"; ddir = sdir / "draft"
        ddir.mkdir(parents=True)
        monkeypatch.setattr("agenticops.config.settings.skills_dir", sdir, raising=False)
        monkeypatch.setattr("agenticops.config.settings.skills_draft_dir", ddir, raising=False)
        monkeypatch.setattr("agenticops.config.settings.skills_security_scan_on_promote", True, raising=False)
        return sdir, ddir

    def _mkdraft(self, ddir, name, body="# ok\nkubectl get pods"):
        d = ddir / name; d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\ncreated_by: agent\n---\n\n{body}")

    def test_promote_archives_old_version_multigen(self, tmp_path, monkeypatch):
        from agenticops.skills.review import promote_skill
        sdir, ddir = self._setup(tmp_path, monkeypatch)
        (sdir / "redis").mkdir(parents=True)
        (sdir / "redis" / "SKILL.md").write_text("---\nname: redis\ndescription: old\ncreated_by: user\n---\nold body")
        self._mkdraft(ddir, "redis")
        assert promote_skill("redis") is True
        archived = list((sdir / ".archive").glob("redis__*"))
        assert len(archived) == 1
        assert (archived[0] / "SKILL.md").read_text().find("old body") != -1

    def test_promote_blocked_on_dangerous_skill(self, tmp_path, monkeypatch):
        from agenticops.skills.review import promote_skill
        sdir, ddir = self._setup(tmp_path, monkeypatch)
        self._mkdraft(ddir, "danger", body="# danger\n```bash\nrm -rf /\n```")
        ok = promote_skill("danger")
        assert ok is False
        assert not (sdir / "danger").exists()

    def test_rollback_restores_previous(self, tmp_path, monkeypatch):
        from agenticops.skills.review import promote_skill, rollback_skill
        sdir, ddir = self._setup(tmp_path, monkeypatch)
        (sdir / "r").mkdir(parents=True)
        (sdir / "r" / "SKILL.md").write_text("---\nname: r\ndescription: v1\ncreated_by: user\n---\nv1 body")
        self._mkdraft(ddir, "r", body="v2 body kubectl get pods")
        promote_skill("r")
        assert rollback_skill("r") is True
        assert "v1 body" in (sdir / "r" / "SKILL.md").read_text()
