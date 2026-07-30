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


def test_touch_reactivates_stale_agent_draft(tmp_skills):
    from agenticops.skills.curator import touch_skill_used
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    _write_skill(ddir, "s", "agent", "2026-01-01", status="stale")
    touch_skill_used("s")
    fm, _ = parse_frontmatter((ddir / "s" / "SKILL.md").read_text())
    assert fm["status"] == "active"
    assert fm["last_used"] != "2026-01-01"


def test_touch_keeps_human_skill_active(tmp_skills):
    from agenticops.skills.curator import touch_skill_used
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    _write_skill(sdir, "linux-admin", "user", "2026-01-01")
    touch_skill_used("linux-admin")
    fm, _ = parse_frontmatter((sdir / "linux-admin" / "SKILL.md").read_text())
    assert fm["status"] == "active"


def test_repeated_touch_does_not_grow_the_file(tmp_skills):
    """Each touch used to append a blank line (linux-admin reached 276)."""
    from agenticops.skills.curator import touch_skill_used
    sdir, ddir = tmp_skills
    path = sdir / "linux-admin" / "SKILL.md"
    _write_skill(sdir, "linux-admin", "user", "2026-01-01")
    touch_skill_used("linux-admin")          # settles the last_used value
    baseline = path.stat().st_size
    for _ in range(5):
        touch_skill_used("linux-admin")
    assert path.stat().st_size == baseline
    text = path.read_text()
    assert not text.endswith("\n\n"), "body accumulated trailing blank lines"


def test_touch_preserves_body_content(tmp_skills):
    """rstrip must not eat real body text."""
    from agenticops.skills.curator import touch_skill_used
    from agenticops.skills.loader import parse_frontmatter
    sdir, ddir = tmp_skills
    d = sdir / "s"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: s\ndescription: d\ncreated_by: user\nstatus: active\n---\n\n"
        "# Heading\n\nline one\n\n| a | b |\n"
    )
    touch_skill_used("s")
    _, body = parse_frontmatter((d / "SKILL.md").read_text())
    assert "# Heading" in body and "line one" in body and "| a | b |" in body


def test_restore_skill_from_archive(tmp_skills):
    from agenticops.skills.curator import restore_skill
    sdir, ddir = tmp_skills
    arch = sdir / ".archive" / "gone"
    arch.mkdir(parents=True)
    (arch / "SKILL.md").write_text('---\nname: gone\ncreated_by: agent\nstatus: archived\n---\nbody')
    assert restore_skill("gone") is True
    assert (ddir / "gone" / "SKILL.md").exists()
    assert not arch.exists()


def test_deprecated_skill_excluded_from_discovery(tmp_path, monkeypatch):
    sdir = tmp_path / "skills"; ddir = sdir / "draft"
    (sdir / "live").mkdir(parents=True)
    (sdir / "live" / "SKILL.md").write_text("---\nname: live\ndescription: d\ncreated_by: user\nstatus: active\n---\nb")
    (sdir / "dead").mkdir(parents=True)
    (sdir / "dead" / "SKILL.md").write_text("---\nname: dead\ndescription: d\ncreated_by: agent\nstatus: deprecated\n---\nb")
    ddir.mkdir(parents=True)
    monkeypatch.setattr("agenticops.config.settings.skills_dir", sdir, raising=False)
    monkeypatch.setattr("agenticops.config.settings.skills_draft_dir", ddir, raising=False)
    from agenticops.skills.loader import discover_skills, _invalidate_skills_cache
    _invalidate_skills_cache()
    names = {s.name for s in discover_skills()}
    assert "live" in names
    assert "dead" not in names


def test_maybe_run_skills_curator_respects_disabled(monkeypatch, tmp_skills):
    from agenticops.skills import curator
    calls = {"n": 0}
    monkeypatch.setattr(curator, "run_skills_curator", lambda **kw: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr("agenticops.config.settings.skills_curator_enabled", False, raising=False)
    assert curator.maybe_run_skills_curator() is None
    assert calls["n"] == 0
    monkeypatch.setattr("agenticops.config.settings.skills_curator_enabled", True, raising=False)
    curator.maybe_run_skills_curator()
    assert calls["n"] == 1


def test_skill_manage_registered_on_main_agent():
    import inspect
    import agenticops.agents.main_agent as ma
    src = inspect.getsource(ma)
    assert "skill_manage" in src
