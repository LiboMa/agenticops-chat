"""Tests for agenticops.skills.evolution module.

Covers create_draft_skill, update_draft_skill, generate_skill_from_description,
and auto_improve_skill with mocked LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agenticops.skills.evolution import (
    auto_improve_skill,
    create_draft_skill,
    generate_skill_from_description,
    update_draft_skill,
)


# ---------------------------------------------------------------------------
# create_draft_skill
# ---------------------------------------------------------------------------


class TestCreateDraftSkill:
    def test_creates_skill_md(self, tmp_path):
        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = tmp_path
            result = create_draft_skill(
                name="test-skill",
                description="A test skill",
                content="## Steps\n1. Do something",
            )
            assert result == tmp_path / "test-skill"
            skill_md = (result / "SKILL.md").read_text(encoding="utf-8")
            assert "name: test-skill" in skill_md
            assert 'description: "A test skill"' in skill_md
            assert "## Steps" in skill_md

    def test_creates_reference_files(self, tmp_path):
        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = tmp_path
            refs = {"guide.md": "# Guide\nDetails", "commands.txt": "ls -la"}
            result = create_draft_skill(
                name="ref-skill",
                description="Skill with refs",
                content="Body",
                references=refs,
            )
            refs_dir = result / "references"
            assert refs_dir.is_dir()
            assert (refs_dir / "guide.md").read_text(encoding="utf-8") == "# Guide\nDetails"
            assert (refs_dir / "commands.txt").read_text(encoding="utf-8") == "ls -la"

    def test_no_references_skips_refs_dir(self, tmp_path):
        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = tmp_path
            result = create_draft_skill(
                name="no-refs", description="No refs", content="Body"
            )
            assert not (result / "references").exists()

    def test_idempotent_overwrite(self, tmp_path):
        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = tmp_path
            create_draft_skill(name="dup", description="v1", content="first")
            path = create_draft_skill(name="dup", description="v2", content="second")
            assert "second" in (path / "SKILL.md").read_text(encoding="utf-8")

    def test_create_draft_skill_handles_quotes_in_description(self, tmp_path):
        import yaml
        from unittest.mock import patch
        from agenticops.skills.evolution import create_draft_skill

        nasty = 'A "quoted" skill\nwith newline'
        with patch("agenticops.skills.evolution.settings") as ms:
            ms.skills_draft_dir = tmp_path
            d = create_draft_skill(name="q-skill", description=nasty, content="body")
        text = (d / "SKILL.md").read_text()
        # Frontmatter must parse and round-trip the description faithfully
        fm = text.split("---")[1]
        loaded = yaml.safe_load(fm)
        assert loaded["description"] == nasty
        assert loaded["name"] == "q-skill"


class TestAtomicWrite:
    def test_atomic_write_helper_replaces_in_place(self, tmp_path):
        from agenticops.skills.evolution import _atomic_write_text

        target = tmp_path / "SKILL.md"
        _atomic_write_text(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"
        # Overwrite is atomic and leaves no temp residue
        _atomic_write_text(target, "world")
        assert target.read_text(encoding="utf-8") == "world"
        assert list(tmp_path.glob(".*tmp*")) == []

    def test_create_draft_skill_leaves_no_temp_file(self, tmp_path):
        from unittest.mock import patch
        from agenticops.skills.evolution import create_draft_skill

        with patch("agenticops.skills.evolution.settings") as ms:
            ms.skills_draft_dir = tmp_path
            d = create_draft_skill(name="atomic-skill", description="d", content="body")
        assert (d / "SKILL.md").read_text(encoding="utf-8").startswith("---")
        assert list(d.glob(".*tmp*")) == []


# ---------------------------------------------------------------------------
# update_draft_skill
# ---------------------------------------------------------------------------


class TestUpdateDraftSkill:
    def test_updates_existing_skill(self, tmp_path):
        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = tmp_path
            # Create first
            skill_dir = tmp_path / "my-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("old content", encoding="utf-8")

            result = update_draft_skill("my-skill", "new content")
            assert result == skill_dir
            assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "new content"

    def test_returns_none_if_not_found(self, tmp_path):
        with patch("agenticops.skills.evolution.settings") as mock_settings:
            mock_settings.skills_draft_dir = tmp_path
            result = update_draft_skill("nonexistent", "content")
            assert result is None


# ---------------------------------------------------------------------------
# generate_skill_from_description
# ---------------------------------------------------------------------------


def _make_bedrock_response(text: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}}}


class TestGenerateSkillFromDescription:
    @patch("agenticops.skills.evolution.boto3")
    def test_success(self, mock_boto3):
        payload = {
            "name": "redis-admin",
            "description": "Redis troubleshooting skill",
            "content": "## Decision Tree\n...",
            "references": {"tips.md": "some tips"},
        }
        client = MagicMock()
        client.converse.return_value = _make_bedrock_response(json.dumps(payload))
        mock_boto3.client.return_value = client

        result = generate_skill_from_description("a skill for Redis admin")
        assert result["name"] == "redis-admin"
        assert result["references"] == {"tips.md": "some tips"}

    @patch("agenticops.skills.evolution.boto3")
    def test_strips_markdown_fences(self, mock_boto3):
        payload = {"name": "k8s", "description": "K8s skill", "content": "body"}
        fenced = f"```json\n{json.dumps(payload)}\n```"
        client = MagicMock()
        client.converse.return_value = _make_bedrock_response(fenced)
        mock_boto3.client.return_value = client

        result = generate_skill_from_description("kubernetes skill")
        assert result["name"] == "k8s"
        assert result.get("references") == {}

    @patch("agenticops.skills.evolution.boto3")
    def test_missing_required_key(self, mock_boto3):
        payload = {"name": "bad", "content": "no description key"}
        client = MagicMock()
        client.converse.return_value = _make_bedrock_response(json.dumps(payload))
        mock_boto3.client.return_value = client

        result = generate_skill_from_description("bad skill")
        assert "error" in result
        assert "missing required key" in result["error"]

    @patch("agenticops.skills.evolution.boto3")
    def test_invalid_json(self, mock_boto3):
        client = MagicMock()
        client.converse.return_value = _make_bedrock_response("not json at all")
        mock_boto3.client.return_value = client

        result = generate_skill_from_description("broken")
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    @patch("agenticops.skills.evolution.boto3")
    def test_boto3_exception(self, mock_boto3):
        client = MagicMock()
        client.converse.side_effect = RuntimeError("connection timeout")
        mock_boto3.client.return_value = client

        result = generate_skill_from_description("fail")
        assert "error" in result
        assert "connection timeout" in result["error"]

    @patch("agenticops.skills.evolution.boto3")
    def test_defaults_references_to_empty(self, mock_boto3):
        payload = {"name": "minimal", "description": "Minimal", "content": "body"}
        client = MagicMock()
        client.converse.return_value = _make_bedrock_response(json.dumps(payload))
        mock_boto3.client.return_value = client

        result = generate_skill_from_description("minimal skill")
        assert result["references"] == {}


# ---------------------------------------------------------------------------
# auto_improve_skill
# ---------------------------------------------------------------------------


class TestAutoImproveSkill:
    def _make_skill(self, tmp_path, name="my-skill"):
        skill_dir = tmp_path / name
        skill_dir.mkdir(parents=True)
        content = '---\nname: my-skill\ndescription: "Original"\n---\n\n## Original body'
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        skill = SimpleNamespace(name=name, path=skill_dir, description="Original")
        return skill

    @patch("agenticops.skills.evolution.boto3")
    @patch("agenticops.skills.evolution.settings")
    def test_success(self, mock_settings, mock_boto3, tmp_path):
        draft_dir = tmp_path / "drafts"
        mock_settings.skills_draft_dir = draft_dir
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_model_id = "test-model"

        skill = self._make_skill(tmp_path)

        client = MagicMock()
        client.converse.return_value = _make_bedrock_response("## Improved body\nNew content")
        mock_boto3.client.return_value = client

        with patch(
            "agenticops.skills.loader.discover_skills", return_value=[skill]
        ), patch(
            "agenticops.skills.loader.parse_frontmatter",
            return_value=({"description": "Original"}, "## Original body"),
        ):
            result = auto_improve_skill("my-skill", "needs more examples")

        assert result["action"] == "updated"
        assert result["skill_name"] == "my-skill"
        assert "draft_path" in result
        # Verify draft was actually created
        draft_skill_md = Path(result["draft_path"]) / "SKILL.md"
        assert draft_skill_md.is_file()
        assert "Improved body" in draft_skill_md.read_text(encoding="utf-8")

    def test_skill_not_found(self):
        with patch(
            "agenticops.skills.loader.discover_skills", return_value=[]
        ):
            result = auto_improve_skill("nonexistent", "gap")
        assert "error" in result
        assert "not found" in result["error"]

    @patch("agenticops.skills.evolution.boto3")
    @patch("agenticops.skills.evolution.settings")
    def test_llm_error(self, mock_settings, mock_boto3, tmp_path):
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_model_id = "test-model"

        skill = self._make_skill(tmp_path)

        client = MagicMock()
        client.converse.side_effect = RuntimeError("LLM down")
        mock_boto3.client.return_value = client

        with patch(
            "agenticops.skills.loader.discover_skills", return_value=[skill]
        ), patch(
            "agenticops.skills.loader.parse_frontmatter",
            return_value=({"description": "Orig"}, "body"),
        ):
            result = auto_improve_skill("my-skill", "gap")

        assert "error" in result
        assert "LLM down" in result["error"]

    @patch("agenticops.skills.evolution.boto3")
    @patch("agenticops.skills.evolution.settings")
    def test_with_agent_context(self, mock_settings, mock_boto3, tmp_path):
        draft_dir = tmp_path / "drafts"
        mock_settings.skills_draft_dir = draft_dir
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_model_id = "test-model"

        skill = self._make_skill(tmp_path)

        client = MagicMock()
        client.converse.return_value = _make_bedrock_response("improved")
        mock_boto3.client.return_value = client

        with patch(
            "agenticops.skills.loader.discover_skills", return_value=[skill]
        ), patch(
            "agenticops.skills.loader.parse_frontmatter",
            return_value=({"description": "Orig"}, "body"),
        ):
            result = auto_improve_skill(
                "my-skill", "gap", agent_context="Redis was OOMing"
            )

        assert result["action"] == "updated"
        # Verify agent_context was included in the prompt
        call_args = client.converse.call_args
        prompt_text = call_args[1]["messages"][0]["content"][0]["text"]
        assert "Redis was OOMing" in prompt_text
