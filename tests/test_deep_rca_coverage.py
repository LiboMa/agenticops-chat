"""Additional tests for deep_rca.py — targeting uncovered lines.

Covers: confidence_threshold param (L77), timeout break (L192-193),
graph context success path (L152-161), evidence gap iteration (L243-249),
re-iteration exception (L308-309), CaseStudy exception (L324-325),
JSON parse fallback (L439-441).
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticops.analyze.deep_rca import DeepRCAEngine, DeepRCAResult
from agenticops.analyze.evidence import EvidenceItem
from agenticops.analyze.rca import RCAAnalysis, RCAEngine
from agenticops.memory import AgentMemory, MemoryType
from agenticops.memory.agent_memory import _NullEmbeddingClient


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_rca_cov.db")


@pytest.fixture
def memory(tmp_db, tmp_path):
    mem = AgentMemory("rca_agent", db_path=tmp_db)
    mem._memory_md_path = tmp_path / "rca_agent_MEMORY.md"
    mem._embedding_client = _NullEmbeddingClient()
    return mem


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.invoke.return_value = json.dumps({
        "root_cause": "Memory limit exceeded",
        "confidence_score": 0.85,
        "contributing_factors": ["No memory limits"],
        "recommendations": ["Set limits"],
        "related_resources": ["pod/app"],
    })
    return llm


@pytest.fixture
def engine(memory, mock_llm):
    base = RCAEngine()
    base.llm = mock_llm
    return DeepRCAEngine(base_engine=base, memory=memory)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestConfidenceThresholdParam:
    """Cover L77: confidence_threshold constructor param."""

    def test_custom_confidence_threshold(self, memory, mock_llm):
        """When confidence_threshold is passed, it overrides the default."""
        base = RCAEngine()
        base.llm = mock_llm
        eng = DeepRCAEngine(
            base_engine=base,
            memory=memory,
            confidence_threshold=0.5,
        )
        assert eng.CONFIDENCE_THRESHOLD == 0.5

    def test_default_confidence_threshold(self, engine):
        """Default confidence threshold is 0.7."""
        assert engine.CONFIDENCE_THRESHOLD == 0.7


class TestTimeoutBreak:
    """Cover L192-193: timeout during iteration."""

    def test_analysis_timeout(self, memory):
        """Engine breaks out of iteration loop on timeout."""
        mock_llm = MagicMock()
        # Return low confidence so it wants to iterate
        mock_llm.invoke.return_value = json.dumps({
            "root_cause": "Unclear",
            "confidence_score": 0.3,
            "contributing_factors": [],
            "recommendations": [],
            "related_resources": [],
        })

        base = RCAEngine()
        base.llm = mock_llm
        eng = DeepRCAEngine(
            base_engine=base,
            memory=memory,
            max_iterations=10,
        )
        # Set timeout to -1 so it's always exceeded
        eng.TIMEOUT_SECONDS = -1

        result = run(eng.analyze(
            anomaly_title="Timeout Test",
            anomaly_description="Should timeout",
        ))

        # Should have stopped at iteration 1 due to timeout
        assert result.iterations <= 1
        assert result.duration_ms >= 0


class TestGraphContextSuccessPath:
    """Cover L152-161: graph context enrichment success path."""

    def test_graph_context_full_integration(self, engine):
        """Graph context is fetched and injected into analysis context."""
        mock_ctx = {
            "resource": {"id": "i-abc123"},
            "neighbors": [{"id": "vpc-1", "node_type": "vpc"}],
            "blast_radius": {"total_affected": 5},
            "dependencies": {"upstream": ["elb-1"], "downstream": ["rds-1"]},
            "topology_summary": "EC2 in VPC vpc-1",
        }

        with patch(
            "agenticops.graph.context.get_alert_context",
            return_value=mock_ctx,
        ):
            result = run(engine.analyze(
                anomaly_title="High CPU",
                anomaly_description="CPU 95%",
                resource_id="i-abc123",
                resource_type="ec2",
            ))

        assert result.graph_context == mock_ctx
        assert result.analysis.root_cause  # Analysis still runs


class TestEvidenceGapIteration:
    """Cover L243-249: evidence gap detection and collection within iteration."""

    def test_evidence_gaps_collected(self, memory):
        """When LLM returns low confidence, evidence gaps are detected and gathered."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            # Iteration 1: low confidence analysis
            json.dumps({
                "root_cause": "Maybe network",
                "confidence_score": 0.4,
                "contributing_factors": [],
                "recommendations": [],
                "related_resources": [],
            }),
            # Evidence gap detection returns gaps
            json.dumps([{"source": "cloudtrail", "query": "network changes"}]),
            # Iteration 2: higher confidence
            json.dumps({
                "root_cause": "SG rule change",
                "confidence_score": 0.85,
                "contributing_factors": ["SG modified"],
                "recommendations": ["Revert SG"],
                "related_resources": [],
            }),
            # Self-verification
            json.dumps({"valid": True, "adjusted_confidence": 0.85}),
        ]

        base = RCAEngine()
        base.llm = mock_llm
        eng = DeepRCAEngine(base_engine=base, memory=memory, max_iterations=3)

        # Mock evidence gathering
        mock_evidence = EvidenceItem(
            source="cloudtrail",
            content="ModifySecurityGroup at 14:00",
            confidence_delta=0.15,
        )
        with patch(
            "agenticops.analyze.deep_rca.gather_evidence",
            new_callable=AsyncMock,
            return_value=mock_evidence,
        ):
            result = run(eng.analyze(
                anomaly_title="Network Issue",
                anomaly_description="Connectivity lost",
                resource_id="vpc-123",
            ))

        assert result.iterations >= 2
        # Evidence should have been collected
        ct_evidence = [e for e in result.evidence_chain if e.source == "cloudtrail"]
        assert len(ct_evidence) >= 1


class TestReIterationException:
    """Cover L308-309: exception during re-iteration after verify."""

    def test_re_iteration_failure_handled(self, memory):
        """When re-iteration fails, analysis still completes."""
        mock_llm = MagicMock()
        call_count = 0

        def mock_invoke(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Initial analysis - high enough to verify
                return json.dumps({
                    "root_cause": "Network issue",
                    "confidence_score": 0.8,
                    "contributing_factors": [],
                    "recommendations": ["Check SG"],
                    "related_resources": [],
                })
            elif call_count == 2:
                # Self-verification: challenge it (triggers re-iteration)
                return json.dumps({
                    "valid": False,
                    "critique": "Not enough evidence",
                    "adjusted_confidence": 0.5,
                })
            else:
                # Re-iteration: throw exception
                raise Exception("LLM timeout during re-iteration")

        mock_llm.invoke.side_effect = mock_invoke

        base = RCAEngine()
        base.llm = mock_llm
        eng = DeepRCAEngine(base_engine=base, memory=memory, max_iterations=2)

        result = run(eng.analyze(
            anomaly_title="Test Re-iter Exception",
            anomaly_description="Should handle gracefully",
        ))

        # Should complete without raising
        assert result.analysis.root_cause
        assert result.duration_ms > 0


class TestCaseStudyException:
    """Cover L324-325: CaseStudy save failure."""

    def test_case_study_save_failure_handled(self, engine):
        """When CaseStudy save fails, analysis still returns."""
        with patch.object(
            engine,
            "_save_case_study",
            new_callable=AsyncMock,
            side_effect=Exception("KB write failed"),
        ):
            result = run(engine.analyze(
                anomaly_title="CaseStudy Fail Test",
                anomaly_description="KB should fail gracefully",
                save_to_kb=True,
            ))

        # Analysis should still succeed
        assert result.analysis.root_cause
        assert result.analysis.confidence_score > 0
        assert result.memory_id is not None


class TestJSONParseFallback:
    """Cover L439-441: JSON parse failure fallback."""

    def test_malformed_json_response(self, memory):
        """When LLM returns non-JSON, falls back to raw text."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            # Return non-JSON text
            "The root cause appears to be a memory leak in the application container. "
            "This is causing OOM kills. I recommend setting resource limits.",
            # Self-verification (won't be called if confidence < threshold)
        ]

        base = RCAEngine()
        base.llm = mock_llm
        eng = DeepRCAEngine(base_engine=base, memory=memory, max_iterations=1)

        result = run(eng.analyze(
            anomaly_title="OOM Test",
            anomaly_description="Pod OOM killed",
        ))

        # Should fall back to raw text as root_cause
        assert "memory leak" in result.analysis.root_cause.lower()
        # Fallback confidence is 0.5
        assert result.analysis.confidence_score == 0.5
