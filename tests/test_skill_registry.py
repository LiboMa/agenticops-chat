"""Tests for agenticops.skills.registry module.

Covers LocalRegistry, ClawHubRegistry, and unified search/install functions.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenticops.skills.registry import (
    ClawHubRegistry,
    LocalRegistry,
    install_from_registry,
    search_skills,
)


# ── LocalRegistry ───────────────────────────────────────────────────


class TestLocalRegistry:
    """Tests for LocalRegistry."""

    def setup_method(self):
        self.registry = LocalRegistry()

    @patch("agenticops.skills.registry.discover_skills")
    def test_search_matches_name(self, mock_discover):
        skill = MagicMock()
        skill.name = "network-scan"
        skill.description = "Scan network resources"
        skill.is_draft = False
        skill.path = Path("/skills/network-scan")
        skill.tools = ["scan_tool"]
        mock_discover.return_value = [skill]

        results = self.registry.search("network")
        assert len(results) == 1
        assert results[0]["name"] == "network-scan"
        assert results[0]["source"] == "local"
        assert results[0]["has_tools"] is True

    @patch("agenticops.skills.registry.discover_skills")
    def test_search_matches_description(self, mock_discover):
        skill = MagicMock()
        skill.name = "foo"
        skill.description = "A kubernetes deployment helper"
        skill.is_draft = True
        skill.path = Path("/skills/draft/foo")
        skill.tools = []
        mock_discover.return_value = [skill]

        results = self.registry.search("kubernetes")
        assert len(results) == 1
        assert results[0]["source"] == "draft"
        assert results[0]["has_tools"] is False

    @patch("agenticops.skills.registry.discover_skills")
    def test_search_no_match(self, mock_discover):
        skill = MagicMock()
        skill.name = "something"
        skill.description = "unrelated"
        skill.is_draft = False
        skill.path = Path("/skills/something")
        skill.tools = []
        mock_discover.return_value = [skill]

        results = self.registry.search("zzzzz")
        assert results == []

    @patch("agenticops.skills.registry.discover_skills")
    def test_install_found(self, mock_discover):
        skill = MagicMock()
        skill.name = "my-skill"
        skill.path = Path("/skills/my-skill")
        mock_discover.return_value = [skill]

        result = self.registry.install("my-skill")
        assert result == Path("/skills/my-skill")

    @patch("agenticops.skills.registry.discover_skills")
    def test_install_not_found(self, mock_discover):
        mock_discover.return_value = []
        result = self.registry.install("nonexistent")
        assert result is None

    @patch("agenticops.skills.registry.discover_skills")
    def test_inspect_found(self, mock_discover):
        skill = MagicMock()
        skill.name = "test-skill"
        skill.description = "Test"
        skill.is_draft = False
        skill.path = MagicMock(spec=Path)
        skill.path.__truediv__ = lambda self, other: Path("/fake/references")
        skill.license = "MIT"
        skill.compatibility = ">=0.5"
        skill.tools = ["tool_a"]

        # Mock the references directory
        refs_path = MagicMock()
        skill.path.__truediv__ = MagicMock(return_value=refs_path)
        refs_path.is_dir.return_value = True
        ref_file = MagicMock()
        ref_file.name = "ref1.md"
        refs_path.glob.return_value = [ref_file]

        mock_discover.return_value = [skill]

        result = self.registry.inspect("test-skill")
        assert result is not None
        assert result["name"] == "test-skill"
        assert result["license"] == "MIT"
        assert result["references"] == ["ref1.md"]

    @patch("agenticops.skills.registry.discover_skills")
    def test_inspect_not_found(self, mock_discover):
        mock_discover.return_value = []
        result = self.registry.inspect("missing")
        assert result is None

    @patch("agenticops.skills.registry.discover_skills")
    def test_inspect_no_references_dir(self, mock_discover):
        skill = MagicMock()
        skill.name = "bare-skill"
        skill.description = "No refs"
        skill.is_draft = True
        skill.license = ""
        skill.compatibility = ""
        skill.tools = []

        refs_path = MagicMock()
        skill.path.__truediv__ = MagicMock(return_value=refs_path)
        refs_path.is_dir.return_value = False

        mock_discover.return_value = [skill]

        result = self.registry.inspect("bare-skill")
        assert result is not None
        assert result["references"] == []
        assert result["is_draft"] is True


# ── ClawHubRegistry ─────────────────────────────────────────────────


class TestClawHubRegistry:
    """Tests for ClawHubRegistry."""

    def setup_method(self):
        self.registry = ClawHubRegistry()

    @patch("agenticops.skills.registry.settings")
    def test_run_clawhub_disabled(self, mock_settings):
        mock_settings.clawhub_enabled = False
        result = self.registry._run_clawhub("search", "foo")
        assert result is None

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run")
    def test_run_clawhub_success(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = "tok123"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"results": []}),
        )

        result = self.registry._run_clawhub("search", "test")
        assert result == {"results": []}
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert "clawhub" in call_kwargs[0][0]

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run")
    def test_run_clawhub_no_token(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = ""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"ok": True}),
        )

        result = self.registry._run_clawhub("inspect", "x")
        assert result == {"ok": True}

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run")
    def test_run_clawhub_nonzero_exit(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = ""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="error message",
        )

        result = self.registry._run_clawhub("install", "bad")
        assert result is None

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_run_clawhub_not_installed(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = ""

        result = self.registry._run_clawhub("search", "x")
        assert result is None

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30))
    def test_run_clawhub_timeout(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = ""

        result = self.registry._run_clawhub("search", "x")
        assert result is None

    @patch("agenticops.skills.registry.settings")
    @patch("subprocess.run")
    def test_run_clawhub_invalid_json(self, mock_run, mock_settings):
        mock_settings.clawhub_enabled = True
        mock_settings.clawhub_token = ""
        mock_run.return_value = MagicMock(returncode=0, stdout="not json{")

        result = self.registry._run_clawhub("search", "x")
        assert result is None

    @patch.object(ClawHubRegistry, "_run_clawhub")
    def test_search_with_results(self, mock_run):
        mock_run.return_value = {
            "results": [
                {
                    "name": "aws-rca",
                    "description": "Root cause analysis",
                    "slug": "author/aws-rca",
                    "author": "author",
                    "version": "1.0.0",
                }
            ]
        }

        results = self.registry.search("aws")
        assert len(results) == 1
        assert results[0]["source"] == "clawhub"
        assert results[0]["slug"] == "author/aws-rca"

    @patch.object(ClawHubRegistry, "_run_clawhub")
    def test_search_no_results(self, mock_run):
        mock_run.return_value = None
        results = self.registry.search("nothing")
        assert results == []

    @patch.object(ClawHubRegistry, "_run_clawhub")
    def test_search_missing_results_key(self, mock_run):
        mock_run.return_value = {"other": "data"}
        results = self.registry.search("x")
        assert results == []

    @patch("agenticops.skills.registry._invalidate_skills_cache")
    @patch.object(ClawHubRegistry, "_run_clawhub")
    @patch("agenticops.skills.registry.settings")
    def test_install_success(self, mock_settings, mock_run, mock_invalidate):
        mock_settings.skills_dir = Path("/skills")
        mock_run.return_value = {"path": "/skills/new-skill"}

        result = self.registry.install("author/new-skill")
        assert result == Path("/skills/new-skill")
        mock_invalidate.assert_called_once()

    @patch.object(ClawHubRegistry, "_run_clawhub")
    @patch("agenticops.skills.registry.settings")
    def test_install_failure(self, mock_settings, mock_run):
        mock_settings.skills_dir = Path("/skills")
        mock_run.return_value = None

        result = self.registry.install("bad/skill")
        assert result is None

    @patch.object(ClawHubRegistry, "_run_clawhub")
    @patch("agenticops.skills.registry.settings")
    def test_install_no_path_in_response(self, mock_settings, mock_run):
        mock_settings.skills_dir = Path("/skills")
        mock_run.return_value = {"status": "ok"}

        result = self.registry.install("partial/response")
        assert result is None

    @patch.object(ClawHubRegistry, "_run_clawhub")
    def test_inspect_success(self, mock_run):
        mock_run.return_value = {
            "name": "cool-skill",
            "description": "Cool",
            "slug": "author/cool-skill",
            "author": "author",
            "version": "2.0",
            "license": "Apache-2.0",
            "readme": "# Cool Skill",
        }

        result = self.registry.inspect("author/cool-skill")
        assert result is not None
        assert result["source"] == "clawhub"
        assert result["license"] == "Apache-2.0"

    @patch.object(ClawHubRegistry, "_run_clawhub")
    def test_inspect_not_found(self, mock_run):
        mock_run.return_value = None
        result = self.registry.inspect("unknown/skill")
        assert result is None


# ── Unified functions ───────────────────────────────────────────────


class TestUnifiedFunctions:
    """Tests for search_skills and install_from_registry."""

    @patch("agenticops.skills.registry._clawhub_registry")
    @patch("agenticops.skills.registry._local_registry")
    @patch("agenticops.skills.registry.settings")
    def test_search_skills_local_only(self, mock_settings, mock_local, mock_clawhub):
        mock_settings.clawhub_enabled = False
        mock_local.search.return_value = [{"name": "local-skill", "source": "local"}]

        results = search_skills("local", include_remote=False)
        assert len(results) == 1
        mock_clawhub.search.assert_not_called()

    @patch("agenticops.skills.registry._clawhub_registry")
    @patch("agenticops.skills.registry._local_registry")
    @patch("agenticops.skills.registry.settings")
    def test_search_skills_with_remote_dedup(self, mock_settings, mock_local, mock_clawhub):
        mock_settings.clawhub_enabled = True
        mock_local.search.return_value = [{"name": "shared", "source": "local"}]
        mock_clawhub.search.return_value = [
            {"name": "shared", "source": "clawhub"},
            {"name": "remote-only", "source": "clawhub"},
        ]

        results = search_skills("shared", include_remote=True)
        # Should have local 'shared' + remote 'remote-only' (deduped)
        assert len(results) == 2
        names = [r["name"] for r in results]
        assert "shared" in names
        assert "remote-only" in names

    @patch("agenticops.skills.registry.settings")
    def test_install_from_registry_disabled(self, mock_settings):
        mock_settings.clawhub_enabled = False
        result = install_from_registry("author/skill")
        assert result is None

    @patch("agenticops.skills.registry._clawhub_registry")
    @patch("agenticops.skills.registry.settings")
    def test_install_from_registry_enabled(self, mock_settings, mock_clawhub):
        mock_settings.clawhub_enabled = True
        mock_clawhub.install.return_value = Path("/skills/installed")

        result = install_from_registry("author/skill")
        assert result == Path("/skills/installed")
