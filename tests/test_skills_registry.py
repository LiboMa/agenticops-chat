"""Tests for agenticops.skills.registry — covering LocalRegistry, ClawHubRegistry,
search_skills, and install_from_registry (37% → higher)."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ─────────────────────────────────────────────────────────

def _make_skill(name="my-skill", description="A test skill", is_draft=False,
                tools=None, license_="MIT", compatibility=">=0.5",
                path=None):
    s = SimpleNamespace(
        name=name,
        description=description,
        is_draft=is_draft,
        tools=tools or [],
        license=license_,
        compatibility=compatibility,
        path=path or Path(f"/skills/{name}"),
    )
    return s


# ── LocalRegistry ──────────────────────────────────────────────────

class TestLocalRegistry:
    def _cls(self):
        from agenticops.skills.registry import LocalRegistry
        return LocalRegistry()

    @patch("agenticops.skills.registry.discover_skills")
    def test_search_matches_name(self, mock_discover):
        mock_discover.return_value = [
            _make_skill("aws-scanner", "Scan AWS"),
            _make_skill("k8s-debug", "Debug k8s"),
        ]
        reg = self._cls()
        results = reg.search("aws")
        assert len(results) == 1
        assert results[0]["name"] == "aws-scanner"
        assert results[0]["source"] == "local"

    @patch("agenticops.skills.registry.discover_skills")
    def test_search_matches_description(self, mock_discover):
        mock_discover.return_value = [
            _make_skill("tool-a", "Helps with debugging"),
        ]
        reg = self._cls()
        results = reg.search("debug")
        assert len(results) == 1

    @patch("agenticops.skills.registry.discover_skills")
    def test_search_draft_source(self, mock_discover):
        mock_discover.return_value = [
            _make_skill("draft-skill", "WIP", is_draft=True),
        ]
        results = self._cls().search("draft")
        assert results[0]["source"] == "draft"

    @patch("agenticops.skills.registry.discover_skills")
    def test_search_has_tools(self, mock_discover):
        mock_discover.return_value = [
            _make_skill("with-tools", "Has tools", tools=["tool_a"]),
        ]
        results = self._cls().search("with")
        assert results[0]["has_tools"] is True

    @patch("agenticops.skills.registry.discover_skills")
    def test_search_no_match(self, mock_discover):
        mock_discover.return_value = [_make_skill("abc", "xyz")]
        assert self._cls().search("zzz") == []

    @patch("agenticops.skills.registry.discover_skills")
    def test_install_found(self, mock_discover):
        sk = _make_skill("target")
        mock_discover.return_value = [sk]
        assert self._cls().install("target") == sk.path

    @patch("agenticops.skills.registry.discover_skills")
    def test_install_not_found(self, mock_discover):
        mock_discover.return_value = []
        assert self._cls().install("nope") is None

    @patch("agenticops.skills.registry.discover_skills")
    def test_inspect_found(self, mock_discover):
        p = Path("/tmp/test-skill")
        sk = _make_skill("my-skill", path=p)
        mock_discover.return_value = [sk]
        info = self._cls().inspect("my-skill")
        assert info is not None
        assert info["name"] == "my-skill"
        assert info["license"] == "MIT"
        assert info["references"] == []  # no refs dir

    @patch("agenticops.skills.registry.discover_skills")
    def test_inspect_with_references(self, mock_discover, tmp_path):
        skill_dir = tmp_path / "my-skill"
        refs_dir = skill_dir / "references"
        refs_dir.mkdir(parents=True)
        (refs_dir / "ref1.md").write_text("# Ref 1")
        (refs_dir / "ref2.md").write_text("# Ref 2")
        sk = _make_skill("my-skill", path=skill_dir)
        mock_discover.return_value = [sk]
        info = self._cls().inspect("my-skill")
        assert set(info["references"]) == {"ref1.md", "ref2.md"}

    @patch("agenticops.skills.registry.discover_skills")
    def test_inspect_not_found(self, mock_discover):
        mock_discover.return_value = []
        assert self._cls().inspect("nope") is None


# ── ClawHubRegistry ────────────────────────────────────────────────

class TestClawHubRegistry:
    def _cls(self):
        from agenticops.skills.registry import ClawHubRegistry
        return ClawHubRegistry()

    @patch("agenticops.skills.registry.settings")
    def test_run_clawhub_disabled(self, mock_settings):
        mock_settings.clawhub_enabled = False
        reg = self._cls()
        assert reg._run_clawhub("search", "test") is None

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run")
    def test_run_clawhub_success(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = "tok-123"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"ok": True}),
        )
        reg = self._cls()
        result = reg._run_clawhub("search", "aws")
        assert result == {"ok": True}
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert "clawhub" in args[0][0]

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run")
    def test_run_clawhub_no_token(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = None
        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok":true}')
        reg = self._cls()
        result = reg._run_clawhub("search", "test")
        assert result == {"ok": True}

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run")
    def test_run_clawhub_nonzero_exit(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = None
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        assert self._cls()._run_clawhub("search", "x") is None

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_run_clawhub_not_found(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = None
        assert self._cls()._run_clawhub("search", "x") is None

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("clawhub", 30))
    def test_run_clawhub_timeout(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = None
        assert self._cls()._run_clawhub("search", "x") is None

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run")
    def test_run_clawhub_bad_json(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = None
        mock_run.return_value = MagicMock(returncode=0, stdout="not json")
        assert self._cls()._run_clawhub("search", "x") is None

    def test_search_returns_formatted(self):
        reg = self._cls()
        data = {"results": [
            {"name": "aws-skill", "description": "AWS", "slug": "author/aws",
             "author": "alice", "version": "1.0"},
        ]}
        with patch.object(reg, "_run_clawhub", return_value=data):
            results = reg.search("aws")
        assert len(results) == 1
        assert results[0]["source"] == "clawhub"
        assert results[0]["slug"] == "author/aws"

    def test_search_empty(self):
        reg = self._cls()
        with patch.object(reg, "_run_clawhub", return_value=None):
            assert reg.search("nothing") == []

    def test_search_no_results_key(self):
        reg = self._cls()
        with patch.object(reg, "_run_clawhub", return_value={}):
            assert reg.search("nothing") == []

    def test_install_success(self):
        reg = self._cls()
        with patch.object(reg, "_run_clawhub", return_value={"path": "/skills/new"}):
            with patch("agenticops.skills.registry._invalidate_skills_cache"):
                with patch("agenticops.skills.registry.settings") as ms:
                    ms.skills_dir = Path("/skills")
                    result = reg.install("author/new")
        assert result == Path("/skills/new")

    def test_install_failure(self):
        reg = self._cls()
        with patch.object(reg, "_run_clawhub", return_value=None):
            with patch("agenticops.skills.registry.settings") as ms:
                ms.skills_dir = Path("/skills")
                assert reg.install("author/bad") is None

    def test_inspect_success(self):
        reg = self._cls()
        data = {"name": "cool", "description": "Cool skill", "slug": "a/cool",
                "author": "bob", "version": "2.0", "license": "Apache",
                "readme": "# Cool"}
        with patch.object(reg, "_run_clawhub", return_value=data):
            info = reg.inspect("a/cool")
        assert info["name"] == "cool"
        assert info["license"] == "Apache"

    def test_inspect_not_found(self):
        reg = self._cls()
        with patch.object(reg, "_run_clawhub", return_value=None):
            assert reg.inspect("nope") is None


# ── Unified functions ──────────────────────────────────────────────

class TestSearchSkills:
    @patch("agenticops.skills.registry._clawhub_registry")
    @patch("agenticops.skills.registry._local_registry")
    @patch("agenticops.skills.registry.settings")
    def test_local_only(self, mock_settings, mock_local, mock_remote):
        mock_settings.clawhub_enabled = False
        mock_local.search.return_value = [{"name": "local-1", "source": "local"}]
        from agenticops.skills.registry import search_skills
        results = search_skills("test", include_remote=False)
        assert len(results) == 1
        mock_remote.search.assert_not_called()

    @patch("agenticops.skills.registry._clawhub_registry")
    @patch("agenticops.skills.registry._local_registry")
    @patch("agenticops.skills.registry.settings")
    def test_with_remote_dedup(self, mock_settings, mock_local, mock_remote):
        mock_settings.clawhub_enabled = True
        mock_local.search.return_value = [{"name": "shared", "source": "local"}]
        mock_remote.search.return_value = [
            {"name": "shared", "source": "clawhub"},
            {"name": "remote-only", "source": "clawhub"},
        ]
        from agenticops.skills.registry import search_skills
        results = search_skills("test")
        names = [r["name"] for r in results]
        assert names.count("shared") == 1  # dedup'd
        assert "remote-only" in names


class TestInstallFromRegistry:
    @patch("agenticops.skills.registry.settings")
    def test_disabled(self, mock_settings):
        mock_settings.clawhub_enabled = False
        from agenticops.skills.registry import install_from_registry
        assert install_from_registry("author/skill") is None

    @patch("agenticops.skills.registry._clawhub_registry")
    @patch("agenticops.skills.registry.settings")
    def test_enabled(self, mock_settings, mock_remote):
        mock_settings.clawhub_enabled = True
        mock_remote.install.return_value = Path("/skills/new")
        from agenticops.skills.registry import install_from_registry
        assert install_from_registry("author/skill") == Path("/skills/new")
