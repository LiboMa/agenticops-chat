"""Tests for the skill_manage agent tool."""
import json
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def tmp_skills(tmp_path):
    sdir = tmp_path / "skills"; ddir = sdir / "draft"; ddir.mkdir(parents=True)
    with patch("agenticops.config.settings.skills_dir", sdir), \
         patch("agenticops.config.settings.skills_draft_dir", ddir):
        yield sdir, ddir


def test_skill_manage_add_creates_agent_draft(tmp_skills):
    from agenticops.skills.tools import skill_manage
    sdir, ddir = tmp_skills
    with patch("agenticops.skills.evolution.generate_skill_from_description",
               return_value={"name": "redis-admin", "description": "Redis ops", "content": "# Redis\nbody"}):
        res = json.loads(skill_manage(action="add", description="a skill for redis admin"))
    assert res["status"] == "draft_created"
    import yaml
    fm = yaml.safe_load((ddir / "redis-admin" / "SKILL.md").read_text().split("---")[1])
    assert fm["created_by"] == "agent"


def test_skill_manage_add_gated_when_disabled(tmp_skills, monkeypatch):
    from agenticops.skills.tools import skill_manage
    monkeypatch.setattr("agenticops.config.settings.skills_autonomous_write", False)
    res = json.loads(skill_manage(action="add", description="x"))
    assert "error" in res and "disabled" in res["error"].lower()
    # search still works (not gated)
    with patch("agenticops.skills.registry.search_skills", return_value=[]):
        res2 = json.loads(skill_manage(action="search", description="anything"))
    assert "results" in res2


def test_skill_manage_search(tmp_skills):
    from agenticops.skills.tools import skill_manage
    with patch("agenticops.skills.registry.search_skills", return_value=[{"name": "x", "description": "d", "source": "local"}]):
        res = json.loads(skill_manage(action="search", description="x"))
    assert "results" in res


def test_skill_manage_merge_creates_umbrella_draft(tmp_skills):
    from agenticops.skills.tools import skill_manage
    sdir, ddir = tmp_skills
    res = json.loads(skill_manage(action="merge", sources=["a", "b"], into="combo",
                                  description="combined skill"))
    assert res["status"] == "merged_draft"
    import yaml
    fm = yaml.safe_load((ddir / "combo" / "SKILL.md").read_text().split("---")[1])
    assert fm["created_by"] == "agent"
    assert fm["improved_from"] == ["a", "b"]


def test_skill_manage_deprecate_refuses_human_skill(tmp_skills):
    from agenticops.skills.tools import skill_manage
    sdir, ddir = tmp_skills
    (sdir / "linux-admin").mkdir(parents=True)
    (sdir / "linux-admin" / "SKILL.md").write_text(
        "---\nname: linux-admin\ndescription: d\ncreated_by: user\nstatus: active\n---\nbody")
    res = json.loads(skill_manage(action="deprecate", name="linux-admin"))
    assert res["status"] == "not_found_or_pinned"


def test_skill_manage_add_rejects_unsafe_name(tmp_skills):
    from agenticops.skills.tools import skill_manage
    with patch("agenticops.skills.evolution.generate_skill_from_description",
               return_value={"name": "../../evil", "description": "d", "content": "body"}):
        res = json.loads(skill_manage(action="add", description="x"))
    assert "error" in res and "invalid skill name" in res["error"].lower()
    sdir, ddir = tmp_skills
    assert not (ddir.parent.parent / "evil").exists()


def test_skill_manage_add_handles_none_description(tmp_skills):
    from agenticops.skills.tools import skill_manage
    with patch("agenticops.skills.evolution.generate_skill_from_description",
               return_value={"name": "ok-skill", "description": None, "content": "body"}):
        res = json.loads(skill_manage(action="add", description="fallback desc"))
    assert res["status"] == "draft_created"
