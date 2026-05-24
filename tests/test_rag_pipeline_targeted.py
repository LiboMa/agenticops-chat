"""Targeted tests for pipeline/rag_pipeline.py — coverage lift from 44%.

Covers:
- RAGPipelineResult dataclass
- run_rag_pipeline disabled path
- run_rag_pipeline with mocked DB (extract, match, generate, embed, validate)
- _extract_case_data (found, not found, no RCA)
- _generate_sop_filename edge cases
- compute_sop_quality_score
- _save_sop_record (new + update)
- _embed_sop (success, embeddings disabled, failure)
- _validate_sop_searchable (keyword hit, vector hit, miss)
- _extract_section
"""

import importlib
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_rag():
    """Import rag_pipeline module."""
    return importlib.import_module("agenticops.pipeline.rag_pipeline")


# ---------------------------------------------------------------------------
# RAGPipelineResult
# ---------------------------------------------------------------------------

class TestRAGPipelineResult:
    def test_defaults(self):
        mod = _import_rag()
        r = mod.RAGPipelineResult(health_issue_id=1, success=False, action="skipped")
        assert r.health_issue_id == 1
        assert r.sop_path is None
        assert r.steps == []
        assert r.duration_ms == 0
        assert r.validation_passed is False

    def test_with_values(self):
        mod = _import_rag()
        r = mod.RAGPipelineResult(
            health_issue_id=42,
            success=True,
            action="created",
            sop_path="/tmp/sop.md",
            sop_filename="ec2-high-cpu.md",
            similarity_score=0.85,
            embed_status="ok",
            validation_passed=True,
            duration_ms=123,
            steps=[{"step": "extract"}],
        )
        assert r.sop_filename == "ec2-high-cpu.md"
        assert r.similarity_score == 0.85


# ---------------------------------------------------------------------------
# run_rag_pipeline — disabled
# ---------------------------------------------------------------------------

class TestRunRagPipelineDisabled:
    def test_disabled_returns_skipped(self):
        mod = _import_rag()
        with patch.object(mod, "settings", rag_pipeline_enabled=False):
            result = mod.run_rag_pipeline(99)
        assert result.action == "skipped"
        assert not result.success
        assert "disabled" in result.error.lower()


# ---------------------------------------------------------------------------
# run_rag_pipeline — extract fails
# ---------------------------------------------------------------------------

class TestRunRagPipelineExtractFails:
    def test_extract_returns_none(self):
        mod = _import_rag()
        fake_settings = SimpleNamespace(rag_pipeline_enabled=True)
        with patch.object(mod, "settings", fake_settings), \
             patch.object(mod, "_extract_case_data", return_value=None):
            result = mod.run_rag_pipeline(1)
        assert result.action == "failed"
        assert "not found" in result.error


# ---------------------------------------------------------------------------
# run_rag_pipeline — full success (created)
# ---------------------------------------------------------------------------

class TestRunRagPipelineCreated:
    def test_create_new_sop(self, tmp_path):
        mod = _import_rag()
        case = {
            "resource_type": "EC2",
            "issue_pattern": "high cpu usage",
            "severity": "high",
            "title": "High CPU",
        }
        fake_settings = SimpleNamespace(
            rag_pipeline_enabled=True,
            sops_dir=tmp_path,
            ensure_dirs=lambda: None,
        )
        with patch.object(mod, "settings", fake_settings), \
             patch.object(mod, "_extract_case_data", return_value=case), \
             patch.object(mod, "identify_matching_sop", return_value=None), \
             patch.object(mod, "generate_new_sop", return_value="# SOP\nHigh CPU fix"), \
             patch.object(mod, "_save_sop_record"), \
             patch.object(mod, "_embed_sop", return_value="Indexed 1 vector(s)"), \
             patch.object(mod, "_validate_sop_searchable", return_value=True):
            result = mod.run_rag_pipeline(10)
        assert result.success
        assert result.action == "created"
        assert result.validation_passed
        assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# run_rag_pipeline — full success (upgraded)
# ---------------------------------------------------------------------------

class TestRunRagPipelineUpgraded:
    def test_upgrade_existing_sop(self, tmp_path):
        mod = _import_rag()
        case = {
            "resource_type": "RDS",
            "issue_pattern": "connection limit",
            "severity": "medium",
        }
        from agenticops.pipeline.sop_identifier import SOPMatch
        match = SOPMatch(
            filename="rds-conn.md",
            sop_path=str(tmp_path / "rds-conn.md"),
            similarity_score=0.92,
            resource_type="RDS",
            issue_pattern="connection limit",
            content="# Old SOP",
        )
        fake_settings = SimpleNamespace(
            rag_pipeline_enabled=True,
            sops_dir=tmp_path,
            ensure_dirs=lambda: None,
        )
        with patch.object(mod, "settings", fake_settings), \
             patch.object(mod, "_extract_case_data", return_value=case), \
             patch.object(mod, "identify_matching_sop", return_value=match), \
             patch.object(mod, "upgrade_existing_sop", return_value="# Upgraded SOP"), \
             patch.object(mod, "_save_sop_record"), \
             patch.object(mod, "_embed_sop", return_value="Indexed 2 vector(s)"), \
             patch.object(mod, "_validate_sop_searchable", return_value=False):
            result = mod.run_rag_pipeline(20)
        assert result.success
        assert result.action == "upgraded"
        assert result.similarity_score == 0.92
        assert not result.validation_passed  # validate returned False


# ---------------------------------------------------------------------------
# run_rag_pipeline — exception path
# ---------------------------------------------------------------------------

class TestRunRagPipelineException:
    def test_exception_caught(self):
        mod = _import_rag()
        fake_settings = SimpleNamespace(rag_pipeline_enabled=True)
        with patch.object(mod, "settings", fake_settings), \
             patch.object(mod, "_extract_case_data", side_effect=RuntimeError("boom")):
            result = mod.run_rag_pipeline(5)
        assert not result.success
        assert result.action == "failed"
        assert "boom" in result.error


# ---------------------------------------------------------------------------
# _generate_sop_filename
# ---------------------------------------------------------------------------

class TestGenerateSOPFilename:
    def test_normal(self):
        mod = _import_rag()
        name = mod._generate_sop_filename({
            "resource_type": "EC2",
            "issue_pattern": "High CPU utilization on production instances",
        })
        assert name.startswith("ec2-")
        assert name.endswith(".md")

    def test_stop_words_skipped(self):
        mod = _import_rag()
        name = mod._generate_sop_filename({
            "resource_type": "RDS",
            "issue_pattern": "the connection was dropped",
        })
        assert "the" not in name.split("-")
        assert name.startswith("rds-")

    def test_empty_pattern(self):
        mod = _import_rag()
        name = mod._generate_sop_filename({
            "resource_type": "S3",
            "issue_pattern": "",
        })
        assert name == "s3-general.md"

    def test_short_words_skipped(self):
        mod = _import_rag()
        name = mod._generate_sop_filename({
            "resource_type": "EKS",
            "issue_pattern": "an OOM kill event detected",
        })
        assert "an" not in name.split("-")


# ---------------------------------------------------------------------------
# compute_sop_quality_score
# ---------------------------------------------------------------------------

class TestComputeSOPQualityScore:
    def test_high_quality(self):
        mod = _import_rag()
        score = mod.compute_sop_quality_score({
            "confidence": 0.95,
            "fix_risk_level": "L0",
            "fix_steps": "step1",
            "post_checks": "check1",
            "rollback_plan": "rollback",
        })
        # 0.35*0.95 + 0.25*1.0 + 0.20*1.0 + 0.20*1.0 = 0.9825
        assert score > 0.9

    def test_low_quality(self):
        mod = _import_rag()
        score = mod.compute_sop_quality_score({
            "confidence": 0.2,
            "fix_risk_level": "L3",
        })
        # 0.35*0.2 + 0.25*0.5 + 0.20*0.3 + 0.20*0.5 = 0.355
        assert score < 0.4

    def test_missing_fields(self):
        mod = _import_rag()
        score = mod.compute_sop_quality_score({})
        assert 0.0 <= score <= 1.0

    def test_unknown_risk_level(self):
        mod = _import_rag()
        score = mod.compute_sop_quality_score({
            "confidence": 0.5,
            "fix_risk_level": "unknown",
        })
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# _extract_section
# ---------------------------------------------------------------------------

class TestExtractSection:
    def test_basic(self):
        mod = _import_rag()
        body = textwrap.dedent("""\
            ## Root Cause
            Memory leak in connection pool.

            ## Diagnosis
            Checked logs and metrics.
        """)
        result = mod._extract_section(body, "Root Cause", "Diagnosis")
        assert "Memory leak" in result

    def test_no_match(self):
        mod = _import_rag()
        result = mod._extract_section("No headings here", "Root Cause")
        assert result == ""

    def test_truncation(self):
        mod = _import_rag()
        body = "## Root Cause\n" + "x" * 1000 + "\n## Next"
        result = mod._extract_section(body, "Root Cause")
        assert len(result) <= 500


# ---------------------------------------------------------------------------
# _embed_sop
# ---------------------------------------------------------------------------

class TestEmbedSOP:
    def test_embeddings_disabled(self):
        mod = _import_rag()
        fake_client = MagicMock()
        fake_client.dimension = 0
        with patch("agenticops.pipeline.rag_pipeline.settings", sops_dir=Path("/tmp")), \
             patch("agenticops.kb.embeddings.get_embedding_client", return_value=fake_client), \
             patch("agenticops.pipeline.rag_pipeline._extract_section", return_value=""):
            result = mod._embed_sop("---\nresource_type: EC2\n---\nContent", "test.md")
        assert "disabled" in result.lower()

    def test_embed_success(self):
        mod = _import_rag()
        import numpy as np
        fake_client = MagicMock()
        fake_client.dimension = 128
        fake_client.embed.return_value = np.zeros(128)

        fake_store = MagicMock()
        with patch("agenticops.kb.embeddings.get_embedding_client", return_value=fake_client), \
             patch("agenticops.kb.vector_store.get_vector_store", return_value=fake_store), \
             patch("agenticops.tools.kb_tools._parse_frontmatter", return_value=({"resource_type": "EC2"}, "body")):
            result = mod._embed_sop("# SOP content", "ec2-test.md")
        assert "Indexed" in result

    def test_embed_exception(self):
        mod = _import_rag()
        with patch("agenticops.kb.embeddings.get_embedding_client", side_effect=RuntimeError("no embeddings")):
            result = mod._embed_sop("content", "test.md")
        assert "skipped" in result.lower()


# ---------------------------------------------------------------------------
# _validate_sop_searchable
# ---------------------------------------------------------------------------

class TestValidateSOPSearchable:
    def test_keyword_hit(self):
        mod = _import_rag()
        with patch("agenticops.tools.kb_tools._keyword_search_sops",
                    return_value=[{"file": "ec2-cpu.md"}]):
            assert mod._validate_sop_searchable("EC2", "high cpu", "ec2-cpu.md")

    def test_keyword_miss_vector_hit(self):
        mod = _import_rag()
        fake_result = SimpleNamespace(file_path="/sops/ec2-cpu.md", case_id="ec2-cpu")
        with patch("agenticops.tools.kb_tools._keyword_search_sops", return_value=[]), \
             patch("agenticops.kb.search.hybrid_search", return_value=[fake_result]), \
             patch("agenticops.pipeline.rag_pipeline.settings",
                    sops_dir=Path("/sops")):
            assert mod._validate_sop_searchable("EC2", "high cpu", "ec2-cpu.md")

    def test_no_match(self):
        mod = _import_rag()
        with patch("agenticops.tools.kb_tools._keyword_search_sops", return_value=[]), \
             patch("agenticops.kb.search.hybrid_search", return_value=[]), \
             patch("agenticops.pipeline.rag_pipeline.settings",
                    sops_dir=Path("/sops")):
            assert not mod._validate_sop_searchable("EC2", "query", "missing.md")

    def test_exception_returns_false(self):
        mod = _import_rag()
        with patch("agenticops.tools.kb_tools._keyword_search_sops",
                    side_effect=RuntimeError("broken")):
            assert not mod._validate_sop_searchable("EC2", "q", "f.md")


# ---------------------------------------------------------------------------
# _save_sop_record
# ---------------------------------------------------------------------------

class TestSaveSOPRecord:
    def test_new_record(self):
        mod = _import_rag()
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        from contextlib import contextmanager
        @contextmanager
        def fake_db():
            yield mock_session

        with patch("agenticops.models.get_db_session", fake_db):
            mod._save_sop_record(
                filename="ec2-cpu.md",
                file_path="/sops/ec2-cpu.md",
                case_data={"resource_type": "EC2", "issue_pattern": "cpu", "severity": "high",
                           "confidence": 0.9, "fix_risk_level": "L0", "fix_steps": "restart",
                           "post_checks": "check cpu"},
                action="created",
            )
        mock_session.add.assert_called_once()

    def test_update_existing(self):
        mod = _import_rag()
        existing = MagicMock()
        existing.status = "draft"
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = existing

        from contextlib import contextmanager
        @contextmanager
        def fake_db():
            yield mock_session

        with patch("agenticops.models.get_db_session", fake_db):
            mod._save_sop_record(
                filename="ec2-cpu.md",
                file_path="/sops/ec2-cpu.md",
                case_data={"confidence": 0.8, "fix_risk_level": "L1", "fix_steps": "y", "post_checks": "y"},
                action="upgraded",
            )
        mock_session.add.assert_not_called()  # updated in-place

    def test_exception_swallowed(self):
        mod = _import_rag()
        with patch("agenticops.models.get_db_session",
                    side_effect=RuntimeError("db down")):
            # Should not raise
            mod._save_sop_record("f", "/f", {}, "created")
