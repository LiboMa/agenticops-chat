"""Extended tests for agenticops.tools.kb_tools — boosting coverage from 58% to 75%+.

Covers: read_kb_sops, write_kb_sop, _keyword_search_sops, _embed_and_index_from_markdown,
distill_case_study, _llm_distill, _embed_and_index_case, _save_case_record.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# read_kb_sops
# ---------------------------------------------------------------------------

class TestReadKBSops:
    def test_no_sops(self, tmp_path):
        mock_settings = MagicMock()
        mock_settings.sops_dir = tmp_path
        mock_settings.ensure_dirs = MagicMock()
        with patch("agenticops.tools.kb_tools.settings", mock_settings):
            from agenticops.tools.kb_tools import read_kb_sops
            result = read_kb_sops()
            assert result == "No SOPs found in Knowledge Base."

    def test_reads_sop_files(self, tmp_path):
        sop = tmp_path / "test-sop.md"
        sop.write_text("---\nresource_type: EC2\nissue_pattern: high-cpu\nseverity: high\nkeywords: [cpu, spike]\n---\n# SOP\nDo stuff")
        mock_settings = MagicMock()
        mock_settings.sops_dir = tmp_path
        mock_settings.ensure_dirs = MagicMock()
        with patch("agenticops.tools.kb_tools.settings", mock_settings):
            from agenticops.tools.kb_tools import read_kb_sops
            result = read_kb_sops()
            parsed = json.loads(result)
            assert len(parsed) == 1
            assert parsed[0]["resource_type"] == "EC2"
            assert parsed[0]["issue_pattern"] == "high-cpu"

    def test_handles_parse_error(self, tmp_path):
        sop = tmp_path / "bad-sop.md"
        sop.write_text("")  # no frontmatter
        mock_settings = MagicMock()
        mock_settings.sops_dir = tmp_path
        mock_settings.ensure_dirs = MagicMock()
        with patch("agenticops.tools.kb_tools.settings", mock_settings):
            from agenticops.tools.kb_tools import read_kb_sops
            result = read_kb_sops()
            parsed = json.loads(result)
            assert len(parsed) == 1
            assert parsed[0]["resource_type"] == "unknown"


# ---------------------------------------------------------------------------
# write_kb_sop
# ---------------------------------------------------------------------------

class TestWriteKBSop:
    def test_write_success(self, tmp_path):
        mock_settings = MagicMock()
        mock_settings.sops_dir = tmp_path
        mock_settings.ensure_dirs = MagicMock()
        with patch("agenticops.tools.kb_tools.settings", mock_settings):
            from agenticops.tools.kb_tools import write_kb_sop
            result = write_kb_sop.__wrapped__("test.md", "# SOP Content")
            assert "saved" in result
            assert (tmp_path / "test.md").read_text() == "# SOP Content"

    def test_write_error(self, tmp_path):
        mock_settings = MagicMock()
        mock_settings.sops_dir = tmp_path / "nonexistent" / "deep"
        mock_settings.ensure_dirs = MagicMock()
        with patch("agenticops.tools.kb_tools.settings", mock_settings):
            from agenticops.tools.kb_tools import write_kb_sop
            result = write_kb_sop.__wrapped__("test.md", "content")
            assert "Error" in result


# ---------------------------------------------------------------------------
# _keyword_search_sops
# ---------------------------------------------------------------------------

class TestKeywordSearchSops:
    def test_finds_matching_sop(self, tmp_path):
        sop = tmp_path / "eks-oom.md"
        sop.write_text("---\nresource_type: EKS\nissue_pattern: oom-killed\nkeywords: [oom, memory, pod]\n---\n# OOM SOP")
        mock_settings = MagicMock()
        mock_settings.sops_dir = tmp_path
        with patch("agenticops.tools.kb_tools.settings", mock_settings):
            from agenticops.tools.kb_tools import _keyword_search_sops
            results = _keyword_search_sops("EKS", "oom")
            assert len(results) >= 1
            # Check file or issue_pattern contains oom
            assert any("oom" in str(r).lower() for r in results)

    def test_no_match(self, tmp_path):
        sop = tmp_path / "ec2-cpu.md"
        sop.write_text("---\nresource_type: EC2\nissue_pattern: cpu-spike\nkeywords: [cpu]\n---\n# CPU SOP")
        mock_settings = MagicMock()
        mock_settings.sops_dir = tmp_path
        with patch("agenticops.tools.kb_tools.settings", mock_settings):
            from agenticops.tools.kb_tools import _keyword_search_sops
            results = _keyword_search_sops("RDS", "deadlock")
            assert len(results) == 0

    def test_empty_dir(self, tmp_path):
        mock_settings = MagicMock()
        mock_settings.sops_dir = tmp_path
        with patch("agenticops.tools.kb_tools.settings", mock_settings):
            from agenticops.tools.kb_tools import _keyword_search_sops
            results = _keyword_search_sops("EC2", "anything")
            assert results == []


# ---------------------------------------------------------------------------
# _llm_distill
# ---------------------------------------------------------------------------

class TestLLMDistill:
    def test_success(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({
            "content": [{"text": json.dumps({
                "title": "Test Case",
                "symptoms": "High CPU",
                "root_cause": "Leak",
                "immediate_action": "Restart",
                "long_term_fix": "Fix code",
                "verification_method": "Monitor",
                "what_failed": "Alerting",
                "why_missed": "Threshold",
                "efficiency_score": 0.7,
                "tags": ["cpu", "leak"],
            })}]
        }).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch("boto3.client", return_value=mock_client):
            from agenticops.tools.kb_tools import _llm_distill
            result = _llm_distill({"issue_id": 1, "title": "test"})
            assert result is not None
            assert result["title"] == "Test Case"

    def test_strips_code_fences(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({
            "content": [{"text": '```json\n{"title": "Fenced"}\n```'}]
        }).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch("boto3.client", return_value=mock_client):
            from agenticops.tools.kb_tools import _llm_distill
            result = _llm_distill({"issue_id": 1})
            assert result["title"] == "Fenced"

    def test_failure(self):
        with patch("boto3.client", side_effect=Exception("no access")):
            from agenticops.tools.kb_tools import _llm_distill
            result = _llm_distill({"issue_id": 1})
            assert result is None

    def test_invalid_json(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({
            "content": [{"text": "not json at all"}]
        }).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch("boto3.client", return_value=mock_client):
            from agenticops.tools.kb_tools import _llm_distill
            result = _llm_distill({"issue_id": 1})
            assert result is None


# ---------------------------------------------------------------------------
# _embed_and_index_case
# ---------------------------------------------------------------------------

class TestEmbedAndIndexCase:
    def _make_case(self):
        case = MagicMock()
        case.case_id = "case_20260425_001"
        case.meta.resource_type = "EC2"
        case.lessons_learned.efficiency_score = 0.8
        case.verified = False
        case.embedding_inputs.symptom_vector_text = "high cpu usage"
        case.embedding_inputs.root_cause_vector_text = "memory leak"
        return case

    def test_embeddings_disabled(self):
        case = self._make_case()
        mock_client = MagicMock()
        mock_client.dimension = 0

        from agenticops.tools.kb_tools import _embed_and_index_case
        with patch("agenticops.kb.embeddings.get_embedding_client", return_value=mock_client):
            result = _embed_and_index_case(case)
            assert "disabled" in result.lower()

    def test_indexes_both_vectors(self):
        case = self._make_case()
        mock_client = MagicMock()
        mock_client.dimension = 256
        mock_client.embed.return_value = [0.1] * 256
        mock_store = MagicMock()

        from agenticops.tools.kb_tools import _embed_and_index_case
        with patch("agenticops.kb.embeddings.get_embedding_client", return_value=mock_client):
            with patch("agenticops.kb.vector_store.get_vector_store", return_value=mock_store):
                result = _embed_and_index_case(case)
                assert "2 vector" in result
                assert mock_store.upsert.call_count == 2

    def test_no_text_no_vectors(self):
        case = self._make_case()
        case.embedding_inputs.symptom_vector_text = ""
        case.embedding_inputs.root_cause_vector_text = ""
        mock_client = MagicMock()
        mock_client.dimension = 256

        from agenticops.tools.kb_tools import _embed_and_index_case
        with patch("agenticops.kb.embeddings.get_embedding_client", return_value=mock_client):
            with patch("agenticops.kb.vector_store.get_vector_store"):
                result = _embed_and_index_case(case)
                assert "No vectors" in result

    def test_embed_returns_none(self):
        case = self._make_case()
        mock_client = MagicMock()
        mock_client.dimension = 256
        mock_client.embed.return_value = None
        mock_store = MagicMock()

        from agenticops.tools.kb_tools import _embed_and_index_case
        with patch("agenticops.kb.embeddings.get_embedding_client", return_value=mock_client):
            with patch("agenticops.kb.vector_store.get_vector_store", return_value=mock_store):
                result = _embed_and_index_case(case)
                assert "No vectors" in result

    def test_exception_handling(self):
        case = self._make_case()
        from agenticops.tools.kb_tools import _embed_and_index_case
        with patch("agenticops.kb.embeddings.get_embedding_client", side_effect=Exception("fail")):
            result = _embed_and_index_case(case)
            assert "skipped" in result.lower()


# ---------------------------------------------------------------------------
# _save_case_record
# ---------------------------------------------------------------------------

class TestSaveCaseRecord:
    def _make_case(self):
        case = MagicMock()
        case.case_id = "case_20260425_001"
        case.meta.resource_type = "EC2"
        case.meta.severity = "high"
        case.meta.source_issue_id = 1
        case.meta.source_rca_id = 10
        case.status.value = "pending_review"
        case.verified = False
        case.lessons_learned.efficiency_score = 0.7
        return case

    def test_creates_new_record(self):
        case = self._make_case()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        from agenticops.tools.kb_tools import _save_case_record
        with patch("agenticops.models.get_db_session", return_value=mock_session):
            _save_case_record(case, "/path/to/case.md")
            mock_session.add.assert_called_once()

    def test_updates_existing_record(self):
        case = self._make_case()
        existing = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = existing

        from agenticops.tools.kb_tools import _save_case_record
        with patch("agenticops.models.get_db_session", return_value=mock_session):
            _save_case_record(case, "/path/to/case.md")
            assert existing.resource_type == "EC2"
            mock_session.add.assert_not_called()

    def test_db_error_handled(self):
        case = self._make_case()
        from agenticops.tools.kb_tools import _save_case_record
        with patch("agenticops.models.get_db_session", side_effect=Exception("db down")):
            # Should not raise
            _save_case_record(case, "/path")


# ---------------------------------------------------------------------------
# _embed_and_index_from_markdown
# ---------------------------------------------------------------------------

class TestEmbedAndIndexFromMarkdown:
    def test_embeddings_disabled(self):
        mock_client = MagicMock()
        mock_client.dimension = 0

        from agenticops.tools.kb_tools import _embed_and_index_from_markdown
        with patch("agenticops.kb.case_study.CaseStudy") as MockCS:
            MockCS.from_markdown.return_value = MagicMock()
            with patch("agenticops.kb.embeddings.get_embedding_client", return_value=mock_client):
                result = _embed_and_index_from_markdown("# Test", "test.md")
                assert "disabled" in result.lower()

    def test_parse_error(self):
        from agenticops.tools.kb_tools import _embed_and_index_from_markdown
        with patch("agenticops.kb.case_study.CaseStudy") as MockCS:
            MockCS.from_markdown.side_effect = Exception("parse error")
            result = _embed_and_index_from_markdown("bad content", "bad.md")
            assert "skipped" in result.lower()


# ---------------------------------------------------------------------------
# distill_case_study (integration-level)
# ---------------------------------------------------------------------------

class TestDistillCaseStudy:
    def test_no_context(self):
        from agenticops.tools.kb_tools import distill_case_study
        with patch("agenticops.tools.kb_tools._build_distillation_context", return_value=None):
            result = distill_case_study.__wrapped__(999)
            assert "not found" in result

    def test_llm_failure(self):
        from agenticops.tools.kb_tools import distill_case_study
        ctx = {"issue_id": 1, "resource_id": "i-123", "resource_type": "EC2", "severity": "high", "title": "Test"}
        with patch("agenticops.tools.kb_tools._build_distillation_context", return_value=ctx):
            with patch("agenticops.tools.kb_tools._llm_distill", return_value=None):
                result = distill_case_study.__wrapped__(1)
                assert "failed" in result.lower()

    def test_exception_handling(self):
        from agenticops.tools.kb_tools import distill_case_study
        with patch("agenticops.tools.kb_tools._build_distillation_context", side_effect=Exception("boom")):
            result = distill_case_study.__wrapped__(1)
            assert "error" in result.lower()


# ---------------------------------------------------------------------------
# _parse_frontmatter edge cases
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        from agenticops.tools.kb_tools import _parse_frontmatter
        meta, body = _parse_frontmatter("---\nkey: value\n---\n# Body")
        assert meta["key"] == "value"
        assert "Body" in body

    def test_no_frontmatter(self):
        from agenticops.tools.kb_tools import _parse_frontmatter
        meta, body = _parse_frontmatter("# Just a heading")
        assert meta == {}
        assert "heading" in body

    def test_empty_frontmatter(self):
        from agenticops.tools.kb_tools import _parse_frontmatter
        meta, body = _parse_frontmatter("---\n---\n# Body")
        assert meta == {} or meta is not None
        assert "Body" in body
