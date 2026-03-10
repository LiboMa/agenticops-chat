"""Tests for SOPAutoWriter — auto-generate SOPs from RCA results."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from agenticops.pipeline.sop_auto_writer import (
    SOPAutoWriter,
    SOPDeduplicator,
    SOPDraft,
)

run = asyncio.get_event_loop().run_until_complete


class TestSOPDraft:
    def test_creation(self):
        sop = SOPDraft(title="Test SOP", service="api-server")
        assert sop.title == "Test SOP"
        assert sop.status == "draft"

    def test_to_markdown(self):
        sop = SOPDraft(
            title="OOM Recovery",
            service="frontend",
            root_cause="Memory leak",
            diagnostic_steps=["Check memory", "Review logs"],
            remediation_steps=["Restart pod", "Scale up"],
            evidence_summary=["Memory at 95%"],
        )
        md = sop.to_markdown()
        assert "# OOM Recovery" in md
        assert "Memory leak" in md
        assert "1. Check memory" in md
        assert "1. Restart pod" in md
        assert "- Memory at 95%" in md

    def test_to_markdown_frontmatter(self):
        sop = SOPDraft(title="Test", service="svc", trigger="better_fix")
        md = sop.to_markdown()
        assert "trigger: better_fix" in md
        assert "status: draft" in md


class TestSOPDeduplicator:
    def test_no_kb_returns_none(self):
        dedup = SOPDeduplicator(kb_search=None)
        result = run(dedup.find_similar("oom", "frontend"))
        assert result is None

    def test_high_similarity_returns_match(self):
        mock_result = MagicMock()
        mock_result.score = 0.9
        mock_result.content = "Existing SOP content"
        mock_result.metadata = {"sop_id": "SOP-001"}

        mock_kb = AsyncMock()
        mock_kb.hybrid_search.return_value = [mock_result]

        dedup = SOPDeduplicator(kb_search=mock_kb)
        result = run(dedup.find_similar("oom", "frontend"))
        assert result is not None
        assert result["action"] == "update"
        assert result["similarity"] == 0.9

    def test_low_similarity_returns_none(self):
        mock_result = MagicMock()
        mock_result.score = 0.3

        mock_kb = AsyncMock()
        mock_kb.hybrid_search.return_value = [mock_result]

        dedup = SOPDeduplicator(kb_search=mock_kb)
        result = run(dedup.find_similar("oom", "frontend"))
        assert result is None

    def test_kb_error_returns_none(self):
        mock_kb = AsyncMock()
        mock_kb.hybrid_search.side_effect = RuntimeError("KB down")

        dedup = SOPDeduplicator(kb_search=mock_kb)
        result = run(dedup.find_similar("oom", "frontend"))
        assert result is None


class TestSOPAutoWriter:
    @pytest.fixture
    def writer(self):
        return SOPAutoWriter()

    def test_evaluate_trigger_new_pattern(self, writer):
        trigger = writer.evaluate_trigger(None, {}, [])
        assert trigger == "new_pattern"

    def test_evaluate_trigger_better_fix(self, writer):
        existing = {"content": "one\ntwo"}
        trigger = writer.evaluate_trigger(existing, {}, ["a", "b", "c", "d"])
        assert trigger == "better_fix"

    def test_evaluate_trigger_escalation(self, writer):
        existing = {"content": "many\n" * 100}
        trigger = writer.evaluate_trigger(existing, {}, ["paged on-call engineer"])
        assert trigger == "escalation_path"

    def test_evaluate_trigger_none(self, writer):
        existing = {"content": "many\n" * 100}
        trigger = writer.evaluate_trigger(existing, {}, ["simple fix"])
        assert trigger is None

    def test_build_sop_from_rca(self, writer):
        rca = {
            "root_cause": "Memory leak in v2.3",
            "affected_service": "checkout",
            "alert_type": "oom",
            "symptoms": ["OOM kill", "High memory"],
            "recommendations": ["Set limits", "Fix leak"],
        }
        sop = writer.build_sop_from_rca(rca, ["restart pod"], incident_id="INC-001")
        assert sop.service == "checkout"
        assert sop.root_cause == "Memory leak in v2.3"
        assert len(sop.diagnostic_steps) >= 2
        assert len(sop.remediation_steps) >= 2
        assert sop.created_from_incident == "INC-001"

    def test_build_sop_with_evidence(self, writer):
        ev = MagicMock()
        ev.content = "Memory usage at 95% for pod/checkout"
        sop = writer.build_sop_from_rca(
            {"root_cause": "OOM", "service": "api"},
            ["restart"],
            evidence_chain=[ev],
        )
        assert len(sop.evidence_summary) == 1

    def test_build_sop_empty_recommendations(self, writer):
        sop = writer.build_sop_from_rca(
            {"root_cause": "Unknown"},
            [],
        )
        assert len(sop.remediation_steps) >= 1  # Falls back to default

    def test_evaluate_and_write_new_pattern(self, writer):
        rca = {"root_cause": "Disk full", "service": "db"}
        sop = run(writer.evaluate_and_write(rca, ["expand volume"]))
        assert sop is not None
        assert sop.trigger == "new_pattern"

    def test_evaluate_and_write_no_trigger(self):
        mock_dedup = MagicMock()
        mock_dedup.find_similar = AsyncMock(return_value={"content": "x\n" * 100})

        writer = SOPAutoWriter(deduplicator=mock_dedup)
        sop = run(writer.evaluate_and_write(
            {"root_cause": "test", "service": "svc"},
            ["simple"],
        ))
        assert sop is None

    def test_store_local(self, tmp_path, writer):
        writer.sop_dir = str(tmp_path)
        sop = SOPDraft(title="Test", service="api", alert_type="oom", trigger="new_pattern")
        writer._store_local(sop)
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1
        assert "api_oom_new_pattern.md" in files[0].name

    def test_evaluate_and_write_with_store(self, tmp_path):
        writer = SOPAutoWriter(sop_dir=str(tmp_path))
        rca = {"root_cause": "OOM", "service": "web", "alert_type": "oom"}
        sop = run(writer.evaluate_and_write(rca, ["restart pod"], incident_id="INC-X"))
        assert sop is not None
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1
