"""Tests for Skills Management API endpoints and skill loader functions.

Run:
    pytest tests/test_skills_api.py -v
"""

import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# ── Loader / Review unit tests (no server needed) ────────────────────


@pytest.fixture
def tmp_skills_dir(tmp_path):
    """Create a temporary skills directory with a published and draft skill."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    draft_dir = tmp_path / "skills" / "draft"
    draft_dir.mkdir()

    # Published skill: linux-admin
    linux_dir = skills_dir / "linux-admin"
    linux_dir.mkdir()
    (linux_dir / "SKILL.md").write_text(
        """---
name: linux-admin
description: "Linux system administration"
metadata:
  domain: infra
tools:
  - agenticops.tools.file_tools.read_local_file
---

# Linux Admin

## Quick Decision Trees
- IF high CPU -> check `top`
""",
        encoding="utf-8",
    )
    refs_dir = linux_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "process-management.md").write_text("# Process Management\n...", encoding="utf-8")
    (refs_dir / "networking.md").write_text("# Networking\n...", encoding="utf-8")

    # Draft skill: redis-admin
    redis_dir = draft_dir / "redis-admin"
    redis_dir.mkdir()
    (redis_dir / "SKILL.md").write_text(
        """---
name: redis-admin
description: "Redis cluster troubleshooting"
metadata:
  domain: data
---

# Redis Admin

## Diagnostics
- Check replication lag
""",
        encoding="utf-8",
    )

    return tmp_path


class TestSkillLoader:
    """Test skill discovery and loading with temp directories."""

    def test_discover_finds_published_and_draft(self, tmp_skills_dir):
        from agenticops.skills.loader import _scan_directory

        skills_dir = tmp_skills_dir / "skills"
        draft_dir = skills_dir / "draft"

        published = _scan_directory(skills_dir, is_draft=False)
        drafts = _scan_directory(draft_dir, is_draft=True)

        pub_names = [s.name for s in published]
        assert "linux-admin" in pub_names

        draft_names = [s.name for s in drafts]
        assert "redis-admin" in draft_names

    def test_scan_returns_metadata(self, tmp_skills_dir):
        from agenticops.skills.loader import _scan_directory

        skills_dir = tmp_skills_dir / "skills"
        published = _scan_directory(skills_dir, is_draft=False)
        linux = next(s for s in published if s.name == "linux-admin")
        assert linux.description == "Linux system administration"
        assert linux.metadata.get("domain") == "infra"
        assert "agenticops.tools.file_tools.read_local_file" in linux.tools
        assert linux.is_draft is False

    def test_parse_frontmatter(self):
        from agenticops.skills.loader import parse_frontmatter

        content = """---
name: test-skill
description: "A test"
metadata:
  domain: testing
---

# Body here
"""
        fm, body = parse_frontmatter(content)
        assert fm["name"] == "test-skill"
        assert fm["description"] == "A test"
        assert fm["metadata"]["domain"] == "testing"
        assert "# Body here" in body

    def test_parse_frontmatter_no_frontmatter(self):
        from agenticops.skills.loader import parse_frontmatter

        content = "# Just markdown\nNo frontmatter."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content


class TestSkillReview:
    """Test draft skill review and lifecycle."""

    def test_create_draft_skill(self, tmp_skills_dir):
        from agenticops.skills.evolution import create_draft_skill
        from agenticops.config import settings

        original = settings.skills_draft_dir
        settings.skills_draft_dir = tmp_skills_dir / "skills" / "draft"
        try:
            path = create_draft_skill(
                name="test-new",
                description="A test skill",
                content="# Test\nSome content",
                references={"ref1.md": "# Reference 1\nContent"},
            )
            assert path.is_dir()
            assert (path / "SKILL.md").is_file()
            assert (path / "references" / "ref1.md").is_file()
            skill_content = (path / "SKILL.md").read_text()
            assert "test-new" in skill_content
            assert "A test skill" in skill_content
        finally:
            settings.skills_draft_dir = original

    def test_reject_draft_skill(self, tmp_skills_dir):
        from agenticops.skills.review import reject_draft_skill
        from agenticops.skills.loader import _invalidate_skills_cache
        from agenticops.config import settings

        draft_dir = tmp_skills_dir / "skills" / "draft" / "redis-admin"
        assert draft_dir.is_dir()

        original_draft = settings.skills_draft_dir
        settings.skills_draft_dir = tmp_skills_dir / "skills" / "draft"
        try:
            _invalidate_skills_cache()
            result = reject_draft_skill("redis-admin")
            assert result is True
            assert not draft_dir.exists()
        finally:
            settings.skills_draft_dir = original_draft
            _invalidate_skills_cache()

    def test_reject_nonexistent_skill(self, tmp_skills_dir):
        from agenticops.skills.review import reject_draft_skill
        from agenticops.config import settings

        original = settings.skills_draft_dir
        settings.skills_draft_dir = tmp_skills_dir / "skills" / "draft"
        try:
            result = reject_draft_skill("nonexistent")
            assert result is False
        finally:
            settings.skills_draft_dir = original


class TestListDraftSkills:
    """Tests for list_draft_skills function."""

    def test_returns_only_draft_skills(self, tmp_skills_dir):
        from agenticops.skills.review import list_draft_skills
        from agenticops.skills.loader import _invalidate_skills_cache
        from agenticops.config import settings

        original_skills = settings.skills_dir
        original_draft = settings.skills_draft_dir
        settings.skills_dir = tmp_skills_dir / "skills"
        settings.skills_draft_dir = tmp_skills_dir / "skills" / "draft"
        try:
            _invalidate_skills_cache()
            drafts = list_draft_skills()
            assert len(drafts) == 1
            assert drafts[0].name == "redis-admin"
            assert drafts[0].is_draft is True
        finally:
            settings.skills_dir = original_skills
            settings.skills_draft_dir = original_draft
            _invalidate_skills_cache()

    def test_empty_when_no_drafts(self, tmp_skills_dir):
        """When draft dir has no skills, returns empty list."""
        from agenticops.skills.review import list_draft_skills
        from agenticops.skills.loader import _invalidate_skills_cache
        from agenticops.config import settings

        empty_draft = tmp_skills_dir / "empty_draft"
        empty_draft.mkdir()
        original_skills = settings.skills_dir
        original_draft = settings.skills_draft_dir
        settings.skills_dir = tmp_skills_dir / "skills"
        settings.skills_draft_dir = empty_draft
        try:
            _invalidate_skills_cache()
            drafts = list_draft_skills()
            assert drafts == []
        finally:
            settings.skills_dir = original_skills
            settings.skills_draft_dir = original_draft
            _invalidate_skills_cache()


class TestReviewDraftSkill:
    """Tests for review_draft_skill function."""

    def test_review_existing_draft_with_published(self, tmp_skills_dir):
        """Review a draft that has a corresponding published version."""
        from agenticops.skills.review import review_draft_skill
        from agenticops.config import settings

        # Create a draft version of linux-admin (published already exists)
        draft_linux = tmp_skills_dir / "skills" / "draft" / "linux-admin"
        draft_linux.mkdir()
        (draft_linux / "SKILL.md").write_text(
            """---
name: linux-admin
description: "Updated Linux admin"
---

# Linux Admin v2

## New Section
- Added new diagnostics
""",
            encoding="utf-8",
        )

        original = settings.skills_draft_dir
        settings.skills_draft_dir = tmp_skills_dir / "skills" / "draft"
        try:
            result = review_draft_skill("linux-admin")
            assert result is not None
            assert result["name"] == "linux-admin"
            assert result["is_new"] is False
            assert result["published_content"] is not None
            assert "lines added" in result["diff_summary"]
            assert "lines removed" in result["diff_summary"]
        finally:
            settings.skills_draft_dir = original

    def test_review_new_draft_no_published(self, tmp_skills_dir):
        """Review a draft with no published counterpart."""
        from agenticops.skills.review import review_draft_skill
        from agenticops.config import settings

        original_draft = settings.skills_draft_dir
        original_skills = settings.skills_dir
        settings.skills_draft_dir = tmp_skills_dir / "skills" / "draft"
        settings.skills_dir = tmp_skills_dir / "skills"
        try:
            result = review_draft_skill("redis-admin")
            assert result is not None
            assert result["name"] == "redis-admin"
            assert result["is_new"] is True
            assert result["published_content"] is None
            assert "New skill" in result["diff_summary"]
        finally:
            settings.skills_draft_dir = original_draft
            settings.skills_dir = original_skills

    def test_review_nonexistent_draft(self, tmp_skills_dir):
        """Returns None for a draft that doesn't exist."""
        from agenticops.skills.review import review_draft_skill
        from agenticops.config import settings

        original = settings.skills_draft_dir
        settings.skills_draft_dir = tmp_skills_dir / "skills" / "draft"
        try:
            result = review_draft_skill("nonexistent")
            assert result is None
        finally:
            settings.skills_draft_dir = original


# ── API endpoint tests (FastAPI TestClient) ──────────────────────────

# We patch the skills functions at the endpoint level to avoid
# needing to manipulate settings or file system for API tests.


@pytest.fixture
def client():
    from agenticops.web.app import app
    return TestClient(app)


def _make_skill_meta(name, description, is_draft=False, domain="general", tools=None, path=None):
    """Create a SkillMetadata-like object for mocking."""
    from agenticops.skills.loader import SkillMetadata

    if path is None:
        # Use a real tmp dir so path / "references" works
        import tempfile
        path = Path(tempfile.mkdtemp()) / name
        path.mkdir(parents=True, exist_ok=True)

    return SkillMetadata(
        name=name,
        description=description,
        path=path,
        metadata={"domain": domain},
        tools=tools or [],
        is_draft=is_draft,
    )


@pytest.fixture
def mock_skills(tmp_path):
    """Provide mock skill data with real filesystem paths for ref counting."""
    # linux-admin (published, with refs)
    linux_dir = tmp_path / "linux-admin"
    linux_dir.mkdir()
    refs = linux_dir / "references"
    refs.mkdir()
    (refs / "process-management.md").write_text("# PM", encoding="utf-8")
    (refs / "networking.md").write_text("# Net", encoding="utf-8")
    (linux_dir / "SKILL.md").write_text("---\nname: linux-admin\ndescription: Linux\n---\n# Linux", encoding="utf-8")

    linux = _make_skill_meta(
        "linux-admin", "Linux system administration",
        domain="infra", tools=["agenticops.tools.file_tools.read_local_file"],
        path=linux_dir,
    )

    # redis-admin (draft, no refs)
    redis_dir = tmp_path / "redis-admin"
    redis_dir.mkdir()
    (redis_dir / "SKILL.md").write_text("---\nname: redis-admin\ndescription: Redis\n---\n# Redis", encoding="utf-8")

    redis = _make_skill_meta(
        "redis-admin", "Redis cluster troubleshooting",
        is_draft=True, domain="data", path=redis_dir,
    )

    return [linux, redis]


class TestListSkillsAPI:
    def test_list_returns_all_skills(self, client, mock_skills):
        with patch("agenticops.skills.loader.discover_skills", return_value=mock_skills):
            resp = client.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        names = [s["name"] for s in data]
        assert "linux-admin" in names
        assert "redis-admin" in names

    def test_list_includes_rich_fields(self, client, mock_skills):
        with patch("agenticops.skills.loader.discover_skills", return_value=mock_skills):
            resp = client.get("/api/skills")
        data = resp.json()
        linux = next(s for s in data if s["name"] == "linux-admin")
        assert linux["is_draft"] is False
        assert linux["domain"] == "infra"
        assert linux["tools"] == ["agenticops.tools.file_tools.read_local_file"]
        assert linux["ref_count"] == 2

    def test_draft_skill_marked(self, client, mock_skills):
        with patch("agenticops.skills.loader.discover_skills", return_value=mock_skills):
            resp = client.get("/api/skills")
        data = resp.json()
        redis = next(s for s in data if s["name"] == "redis-admin")
        assert redis["is_draft"] is True
        assert redis["domain"] == "data"
        assert redis["ref_count"] == 0


class TestGetSkillAPI:
    def test_get_existing_skill(self, client, mock_skills):
        with patch("agenticops.skills.loader.discover_skills", return_value=mock_skills), \
             patch("agenticops.skills.loader.load_skill_body", return_value="# Linux Admin\nContent"):
            resp = client.get("/api/skills/linux-admin")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "linux-admin"
        assert data["is_draft"] is False
        assert "body_markdown" in data
        assert "Linux Admin" in data["body_markdown"]
        assert "references" in data
        assert "process-management.md" in data["references"]
        assert data["ref_count"] == 2

    def test_get_nonexistent_skill_404(self, client):
        with patch("agenticops.skills.loader.discover_skills", return_value=[]):
            resp = client.get("/api/skills/nonexistent")
        assert resp.status_code == 404


class TestSaveDraftAPI:
    def test_save_draft(self, client, tmp_path):
        with patch("agenticops.skills.evolution.create_draft_skill", return_value=tmp_path / "new") as mock_create, \
             patch("agenticops.skills.loader._invalidate_skills_cache"):
            resp = client.post(
                "/api/skills/draft",
                json={
                    "name": "new-test-skill",
                    "description": "A brand new skill",
                    "content": "# New Skill\nContent here",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "new-test-skill"
        mock_create.assert_called_once()

    def test_save_draft_with_references(self, client, tmp_path):
        refs = {"guide.md": "# Guide\nContent"}
        with patch("agenticops.skills.evolution.create_draft_skill", return_value=tmp_path / "ref") as mock_create, \
             patch("agenticops.skills.loader._invalidate_skills_cache"):
            resp = client.post(
                "/api/skills/draft",
                json={
                    "name": "ref-skill",
                    "description": "Skill with refs",
                    "content": "# Content",
                    "references": refs,
                },
            )
        assert resp.status_code == 200
        call_args = mock_create.call_args
        assert call_args[1].get("references") == refs or call_args[0][3] == refs

    def test_save_draft_missing_fields(self, client):
        resp = client.post("/api/skills/draft", json={"name": "x"})
        assert resp.status_code == 400


class TestDeleteSkillAPI:
    def test_delete_draft(self, client, mock_skills):
        with patch("agenticops.skills.loader.discover_skills", return_value=mock_skills), \
             patch("agenticops.skills.review.reject_draft_skill", return_value=True):
            resp = client.delete("/api/skills/redis-admin")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True

    def test_delete_published_returns_403(self, client, mock_skills):
        with patch("agenticops.skills.loader.discover_skills", return_value=mock_skills):
            resp = client.delete("/api/skills/linux-admin")
        assert resp.status_code == 403

    def test_delete_nonexistent_returns_404(self, client):
        with patch("agenticops.skills.loader.discover_skills", return_value=[]):
            resp = client.delete("/api/skills/nonexistent")
        assert resp.status_code == 404


class TestImportSkillAPI:
    def test_import_md_file(self, client, tmp_path):
        md_content = """---
name: imported-skill
description: "An imported skill"
---

# Imported Skill
Some content here.
"""
        with patch("agenticops.skills.evolution.create_draft_skill", return_value=tmp_path / "imported") as mock_create, \
             patch("agenticops.skills.loader._invalidate_skills_cache"), \
             patch("agenticops.skills.loader.parse_frontmatter") as mock_parse:
            mock_parse.return_value = (
                {"name": "imported-skill", "description": "An imported skill"},
                "# Imported Skill\nSome content here.\n",
            )
            resp = client.post(
                "/api/skills/import",
                files={"file": ("SKILL.md", md_content.encode(), "text/markdown")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "imported-skill"

    def test_import_zip_file(self, client, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            skill_md = """---
name: zip-skill
description: "A skill from zip"
---

# Zip Skill
Content.
"""
            zf.writestr("zip-skill/SKILL.md", skill_md)
            zf.writestr("zip-skill/references/guide.md", "# Guide\nContent.")
        buf.seek(0)

        with patch("agenticops.skills.evolution.create_draft_skill", return_value=tmp_path / "zip") as mock_create, \
             patch("agenticops.skills.loader._invalidate_skills_cache"):
            resp = client.post(
                "/api/skills/import",
                files={"file": ("skill.zip", buf.read(), "application/zip")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "zip-skill"

    def test_import_zip_path_traversal_blocked(self, client):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil/SKILL.md", "evil content")
        buf.seek(0)

        resp = client.post(
            "/api/skills/import",
            files={"file": ("evil.zip", buf.read(), "application/zip")},
        )
        assert resp.status_code == 400
        assert "Invalid path" in resp.json()["detail"]

    def test_import_zip_non_md_blocked(self, client):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("skill/SKILL.md", "---\nname: x\ndescription: y\n---\n# X")
            zf.writestr("skill/evil.py", "import os")
        buf.seek(0)

        resp = client.post(
            "/api/skills/import",
            files={"file": ("bad.zip", buf.read(), "application/zip")},
        )
        assert resp.status_code == 400
        assert "Only .md files" in resp.json()["detail"]

    def test_import_unsupported_format(self, client):
        resp = client.post(
            "/api/skills/import",
            files={"file": ("skill.txt", b"some text", "text/plain")},
        )
        assert resp.status_code == 400


class TestGenerateSkillAPI:
    def test_generate_missing_description(self, client):
        resp = client.post("/api/skills/generate", json={"description": ""})
        assert resp.status_code == 400

    def test_generate_calls_llm(self, client):
        mock_result = {
            "name": "test-gen",
            "description": "Generated skill",
            "content": "# Generated\nSome content here",
            "references": {"ref.md": "# Ref"},
        }
        with patch(
            "agenticops.skills.evolution.generate_skill_from_description",
            return_value=mock_result,
        ):
            resp = client.post(
                "/api/skills/generate",
                json={"description": "a skill for testing"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-gen"
        assert data["description"] == "Generated skill"
        assert "body_preview" in data
        assert "full_content" in data
        assert data["references"] == {"ref.md": "# Ref"}

    def test_generate_llm_error(self, client):
        with patch(
            "agenticops.skills.evolution.generate_skill_from_description",
            return_value={"error": "LLM failed"},
        ):
            resp = client.post(
                "/api/skills/generate",
                json={"description": "something"},
            )
        assert resp.status_code == 500
        assert "LLM failed" in resp.json()["detail"]


# ── Rollback + Restore endpoints (cycle③ P5) ─────────────────────────


class TestRollbackRestoreEndpoints:
    def test_endpoints_registered(self):
        from agenticops.web.app import app
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/skills/{name}/rollback" in paths
        assert "/api/skills/{name}/restore" in paths

    def test_rollback_success(self, client):
        with patch("agenticops.skills.review.rollback_skill", return_value=True):
            resp = client.post("/api/skills/redis/rollback")
        assert resp.status_code == 200
        assert resp.json() == {"rolled_back": True, "name": "redis"}

    def test_rollback_404_when_no_archive(self, client):
        with patch("agenticops.skills.review.rollback_skill", return_value=False):
            resp = client.post("/api/skills/ghost/rollback")
        assert resp.status_code == 404

    def test_restore_success(self, client):
        with patch("agenticops.skills.curator.restore_skill", return_value=True):
            resp = client.post("/api/skills/old-skill/restore")
        assert resp.status_code == 200
        assert resp.json() == {"restored": True, "name": "old-skill"}

    def test_restore_404_when_missing(self, client):
        with patch("agenticops.skills.curator.restore_skill", return_value=False):
            resp = client.post("/api/skills/nope/restore")
        assert resp.status_code == 404
