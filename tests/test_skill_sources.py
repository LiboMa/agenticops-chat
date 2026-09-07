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
