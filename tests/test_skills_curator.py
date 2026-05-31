"""Tests for the skills Curator (agent-draft lifecycle; human skills pinned)."""
from datetime import date, timedelta
from unittest.mock import patch
import pytest


@pytest.fixture
def tmp_skills(tmp_path):
    sdir = tmp_path / "skills"
    ddir = sdir / "draft"
    ddir.mkdir(parents=True)
    with patch("agenticops.config.settings.skills_dir", sdir), \
         patch("agenticops.config.settings.skills_draft_dir", ddir):
        yield sdir, ddir


def _write_skill(base, name, created_by, last_used, status="active"):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    fm = (f"---\nname: {name}\ndescription: d\ncreated_by: {created_by}\n"
          f"status: {status}\nskill_version: \"1.0\"\nlast_used: {last_used}\n---\n\nbody")
    (d / "SKILL.md").write_text(fm)


def test_agent_draft_active_to_stale(tmp_skills):
    from agenticops.skills.curator import run_skills_curator
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    today = date(2026, 6, 1)
    _write_skill(ddir, "old-draft", "agent", str(today - timedelta(days=40)))
    run_skills_curator(stale_days=30, archive_days=60, today=today)
    fm, _ = parse_frontmatter((ddir / "old-draft" / "SKILL.md").read_text())
    assert fm["status"] == "stale"


def test_agent_draft_stale_to_archived(tmp_skills):
    from agenticops.skills.curator import run_skills_curator
    sdir, ddir = tmp_skills
    today = date(2026, 6, 1)
    _write_skill(ddir, "ancient", "agent", str(today - timedelta(days=100)), status="stale")
    run_skills_curator(stale_days=30, archive_days=60, today=today)
    assert not (ddir / "ancient").exists()
    assert (sdir / ".archive" / "ancient" / "SKILL.md").exists()


def test_human_skill_is_pinned(tmp_skills):
    from agenticops.skills.curator import run_skills_curator
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    today = date(2026, 6, 1)
    _write_skill(sdir, "linux-admin", "user", str(today - timedelta(days=200)))
    run_skills_curator(stale_days=30, archive_days=60, today=today)
    assert (sdir / "linux-admin" / "SKILL.md").exists()
    fm, _ = parse_frontmatter((sdir / "linux-admin" / "SKILL.md").read_text())
    assert fm["status"] == "active"   # pinned: untouched
