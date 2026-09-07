"""Skill ingestion tests — hermetic: no network, no real AWS, no cloning from the internet."""

import os
import zipfile
from pathlib import Path

import pytest


SKILL_MD = """---
name: {name}
description: {name} test skill for ingestion
---

# {name}

Read-only helper.
"""


def _make_pkg(root: Path, name: str, extra: dict[str, str] | None = None) -> Path:
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "SKILL.md").write_text(SKILL_MD.format(name=name), encoding="utf-8")
    for rel, content in (extra or {}).items():
        target = pkg / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return pkg


class TestDiscoverPackages:
    def test_finds_every_skill_md_dir_sorted(self, tmp_path):
        from agenticops.skills.sources import discover_packages

        root = tmp_path / "repo"
        _make_pkg(root, "alpha-skill")
        _make_pkg(root / "nested", "beta-skill")
        _make_pkg(root / "nested" / "deeper", "gamma-skill")

        pkgs = discover_packages(root)
        assert [p.name for p in pkgs] == ["alpha-skill", "beta-skill", "gamma-skill"]

    def test_root_itself_can_be_a_package(self, tmp_path):
        from agenticops.skills.sources import discover_packages

        root = tmp_path / "single-skill"
        _make_pkg(tmp_path, "single-skill")
        assert discover_packages(root) == [root]

    def test_does_not_descend_into_a_hit(self, tmp_path):
        """技能内部的 references/SKILL.md 不得被当成第二个包（spec 测试 4）。"""
        from agenticops.skills.sources import discover_packages

        root = tmp_path / "repo"
        pkg = _make_pkg(root, "alpha-skill")
        (pkg / "references").mkdir()
        (pkg / "references" / "SKILL.md").write_text(SKILL_MD.format(name="nope"), encoding="utf-8")

        assert discover_packages(root) == [pkg]

    def test_skips_vcs_and_dot_dirs(self, tmp_path):
        from agenticops.skills.sources import discover_packages

        root = tmp_path / "repo"
        _make_pkg(root, "alpha-skill")
        _make_pkg(root / ".git", "ghost-skill")
        _make_pkg(root / "node_modules", "vendor-skill")
        _make_pkg(root / ".hidden", "hidden-skill")

        assert [p.name for p in discover_packages(root)] == ["alpha-skill"]

    def test_missing_root_returns_empty(self, tmp_path):
        from agenticops.skills.sources import discover_packages
        assert discover_packages(tmp_path / "nope") == []


@pytest.fixture
def skill_dirs(tmp_path, monkeypatch):
    """Point settings at throwaway published/draft dirs (pattern from tests/test_skills_curator.py)."""
    from agenticops.skills.loader import _invalidate_skills_cache

    sdir = tmp_path / "skills"
    ddir = sdir / "draft"
    ddir.mkdir(parents=True)
    monkeypatch.setattr("agenticops.config.settings.skills_dir", sdir, raising=False)
    monkeypatch.setattr("agenticops.config.settings.skills_draft_dir", ddir, raising=False)
    _invalidate_skills_cache()
    yield sdir, ddir
    _invalidate_skills_cache()


class TestInstallPackages:
    def test_installs_as_draft_with_provenance(self, tmp_path, skill_dirs):
        from agenticops.skills.loader import parse_frontmatter
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill", {"references/deep.md": "# deep"})

        res = install_packages(discover_packages(src), "file://src", "deadbeef")

        assert [s.name for s in res.installed] == ["alpha-skill"]
        assert res.skipped == [] and res.rejected == []
        landed = ddir / "alpha-skill"
        assert (landed / "SKILL.md").is_file()
        assert (landed / "references" / "deep.md").is_file()

        fm, _ = parse_frontmatter((landed / "SKILL.md").read_text(encoding="utf-8"))
        assert fm["created_by"] == "imported"
        assert fm["status"] == "active"
        assert fm["source_uri"] == "file://src"
        assert fm["source_ref"] == "deadbeef"
        assert fm["imported_at"]
        assert res.installed[0].files == 2
        assert res.installed[0].bytes > 0

    def test_multi_skill_repo_all_land(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        for n in ("alpha-skill", "beta-skill", "gamma-skill"):
            _make_pkg(src, n)

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert sorted(s.name for s in res.installed) == ["alpha-skill", "beta-skill", "gamma-skill"]
        for n in ("alpha-skill", "beta-skill", "gamma-skill"):
            assert (ddir / n / "SKILL.md").is_file()

    def test_names_filter_skips_the_rest(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        for n in ("alpha-skill", "beta-skill"):
            _make_pkg(src, n)

        res = install_packages(discover_packages(src), "file://src", "ref", names=["beta-skill"])
        assert [s.name for s in res.installed] == ["beta-skill"]
        assert res.skipped == [("alpha-skill", "not in requested names")]
        assert not (ddir / "alpha-skill").exists()

    def test_existing_draft_is_skipped_not_overwritten(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        (ddir / "alpha-skill").mkdir()
        (ddir / "alpha-skill" / "SKILL.md").write_text("ORIGINAL", encoding="utf-8")

        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert len(res.skipped) == 1 and res.skipped[0][0] == "alpha-skill"
        assert (ddir / "alpha-skill" / "SKILL.md").read_text(encoding="utf-8") == "ORIGINAL"

    def test_published_same_name_is_skipped(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        sdir, ddir = skill_dirs
        (sdir / "alpha-skill").mkdir(parents=True)
        (sdir / "alpha-skill" / "SKILL.md").write_text("PUBLISHED", encoding="utf-8")

        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert res.skipped[0][0] == "alpha-skill"
        assert not (ddir / "alpha-skill").exists()

    @pytest.mark.parametrize("bad_name", ["Foo Bar", "../evil", "UPPER", "double--hyphen", "x" * 200])
    def test_bad_skill_names_rejected(self, tmp_path, skill_dirs, bad_name):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "SKILL.md").write_text(
            f'---\nname: "{bad_name}"\ndescription: bad name probe\n---\n\nbody\n', encoding="utf-8"
        )

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert len(res.rejected) == 1
        assert list(ddir.iterdir()) == []

    def test_disallowed_extension_rejects_whole_package(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        (pkg / "payload.so").write_bytes(b"\x00binary")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert res.rejected[0][0] == "alpha-skill"
        assert "not allowed" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_too_many_files_rejected(self, tmp_path, skill_dirs, monkeypatch):
        from agenticops.skills.sources import discover_packages, install_packages

        monkeypatch.setattr("agenticops.config.settings.skills_import_max_files", 3, raising=False)
        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        for i in range(5):
            (pkg / f"note{i}.md").write_text("x", encoding="utf-8")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert "too many files" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_too_large_rejected(self, tmp_path, skill_dirs, monkeypatch):
        from agenticops.skills.sources import discover_packages, install_packages

        monkeypatch.setattr("agenticops.config.settings.skills_import_max_package_bytes", 512, raising=False)
        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        (pkg / "big.txt").write_text("x" * 4096, encoding="utf-8")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert "too large" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_symlink_in_package_rejected(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        secret = tmp_path / "outside.txt"
        secret.write_text("outside", encoding="utf-8")
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        os.symlink(secret, pkg / "link.txt")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert "symlink" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_scripts_land_without_exec_bit(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill", {"tool.sh": "#!/bin/sh\necho hi\n"})
        os.chmod(pkg / "tool.sh", 0o755)

        install_packages(discover_packages(src), "file://src", "ref")
        mode = (ddir / "alpha-skill" / "tool.sh").stat().st_mode
        assert not (mode & 0o111), "imported scripts must not be executable"

    def test_one_bad_package_does_not_block_the_others(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "good-skill")
        bad = _make_pkg(src, "bad-skill")
        (bad / "payload.so").write_bytes(b"\x00")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert [s.name for s in res.installed] == ["good-skill"]
        assert res.rejected[0][0] == "bad-skill"
        assert (ddir / "good-skill").is_dir()

    def test_no_staging_leftovers(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")
        install_packages(discover_packages(src), "file://src", "ref")
        staging = ddir / ".staging"
        assert not staging.exists() or list(staging.iterdir()) == []
