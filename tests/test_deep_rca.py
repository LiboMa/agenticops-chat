"""Tests for Deep RCA Engine — memory-augmented, graph-aware analysis."""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticops.analyze.deep_rca import DeepRCAEngine, DeepRCAResult
from agenticops.analyze.evidence import EvidenceItem
from agenticops.analyze.rca import RCAAnalysis, RCAEngine
from agenticops.memory import AgentMemory, MemoryType
from agenticops.memory.agent_memory import _NullEmbeddingClient


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_rca.db")


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
        "root_cause": "Memory limit exceeded due to memory leak in container",
        "confidence_score": 0.85,
        "contributing_factors": ["No memory limits set", "Memory leak in app"],
        "recommendations": ["Set memory limits", "Fix memory leak", "Add monitoring"],
        "related_resources": ["pod/my-app", "node/worker-1"],
    })
    return llm


@pytest.fixture
def engine(memory, mock_llm):
    from agenticops.analyze.rca import RCAEngine

    base = RCAEngine()
    base.llm = mock_llm
    eng = DeepRCAEngine(base_engine=base, memory=memory)
    return eng


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestDeepRCAEngine:
    """Test the 6-step Deep RCA flow."""

    def test_basic_analysis(self, engine):
        """Step 4: LLM analysis works with no memory/graph/KB."""
        result = run(engine.analyze(
            anomaly_title="Pod OOM Kill",
            anomaly_description="Pod my-app killed by OOM",
            resource_id="pod/my-app",
            resource_type="kubernetes_pod",
            severity="high",
        ))
        assert result.analysis.root_cause
        assert result.analysis.confidence_score > 0
        assert result.memory_id is not None  # Step 5: WAL write
        assert not result.is_known_pattern

    def test_memory_recall_enriches_prompt(self, engine, memory):
        """Step 1: Past memories are included in analysis."""
        # Seed a memory
        run(memory.remember(
            "EKS pod OOM: always check memory limits first",
            memory_type=MemoryType.EPISODIC,
            source="past_rca:42",
        ))

        result = run(engine.analyze(
            anomaly_title="Pod OOM Kill",
            anomaly_description="Pod my-app killed by OOM",
        ))
        assert len(result.memory_hits) >= 1
        assert "OOM" in result.memory_hits[0]["content"]

    def test_known_pattern_skips_llm(self, engine, memory, mock_llm):
        """Known pattern (confidence >= 0.85) skips LLM call."""
        # Seed high-confidence memory
        run(memory.remember(
            "RCA: Pod OOM always caused by missing memory limits",
            memory_type=MemoryType.EPISODIC,
            source="deep_rca:pod/old-app",
            confidence=0.9,
        ))

        result = run(engine.analyze(
            anomaly_title="Pod OOM Kill",
            anomaly_description="Pod killed by OOM",
        ))

        assert result.is_known_pattern
        assert "[Known Pattern]" in result.analysis.root_cause
        # LLM should NOT be called
        mock_llm.invoke.assert_not_called()

    def test_graph_context_enrichment(self, engine):
        """Step 2: Graph context is added when available."""
        mock_ctx = {
            "resource": {"id": "i-abc123", "label": "web-server"},
            "neighbors": [{"id": "vpc-1", "node_type": "vpc"}],
            "blast_radius": {"total_affected": 5, "by_type": {"ec2": 3, "rds": 2}},
            "dependencies": {"upstream": [], "downstream": [{"id": "rds-1"}]},
            "topology_summary": "EC2 'web-server' in VPC vpc-1, 5 blast radius",
        }

        # Direct test via internal method — ensure prompt includes topology
        prompt = engine._build_deep_prompt(
            title="High CPU",
            description="CPU at 95%",
            resource_id="i-abc123",
            resource_type="ec2",
            severity="high",
            context={
                "topology": "EC2 'web-server' in VPC vpc-1",
                "blast_radius": {"total_affected": 5},
                "dependencies": {"upstream": [{"id": "elb-1"}], "downstream": []},
            },
            memory_hints=[],
        )
        assert "Topology" in prompt
        assert "web-server" in prompt
        assert "Blast Radius" in prompt
        assert "1 upstream" in prompt

    def test_kb_matches_in_result(self, engine):
        """Step 3: KB search results are captured."""
        mock_kb = [
            {"title": "Past OOM incident", "score": 0.9, "root_cause": "Memory leak"},
        ]

        with patch("agenticops.kb.search.hybrid_search", return_value=mock_kb):
            result = run(engine.analyze(
                anomaly_title="Pod OOM",
                anomaly_description="OOM killed",
            ))
        assert len(result.kb_matches) == 1
        assert result.kb_matches[0]["title"] == "Past OOM incident"

    def test_wal_write_before_respond(self, engine):
        """Step 5: Memory is written for every analysis."""
        result = run(engine.analyze(
            anomaly_title="High Latency",
            anomaly_description="API latency > 5s",
            resource_id="api-gw-1",
        ))
        assert result.memory_id is not None

        # Verify it's in memory
        memories = run(engine.memory.recall_recent(limit=5))
        found = any("High Latency" in m.content for m in memories)
        assert found

    def test_case_study_capture(self, engine):
        """Step 6: High-confidence RCA auto-generates CaseStudy."""
        result = run(engine.analyze(
            anomaly_title="RDS Connection Exhaustion",
            anomaly_description="RDS max connections reached",
            resource_type="rds",
            severity="critical",
            save_to_kb=True,
        ))

        # Should have stored procedural memory from case study
        memories = run(engine.memory.recall(
            "Resolution for RDS",
            memory_type=MemoryType.PROCEDURAL,
        ))
        assert len(memories) >= 1

    def test_llm_failure_fallback_to_memory(self, engine, memory, mock_llm):
        """When LLM fails, falls back to memory if available."""
        # Seed memory
        run(memory.remember(
            "Lambda timeout: increase timeout and check cold start",
            source="past_rca:lambda",
            confidence=0.7,
        ))

        # Make LLM fail
        mock_llm.invoke.side_effect = Exception("Bedrock timeout")

        result = run(engine.analyze(
            anomaly_title="Lambda Timeout",
            anomaly_description="Lambda function timing out",
        ))

        assert "[Memory Fallback]" in result.analysis.root_cause
        assert result.analysis.confidence_score > 0

    def test_llm_failure_no_memory(self, engine, mock_llm):
        """When LLM fails and no memory, returns error."""
        mock_llm.invoke.side_effect = Exception("Bedrock down")

        result = run(engine.analyze(
            anomaly_title="Unknown Issue",
            anomaly_description="Something broke",
        ))

        assert "failed" in result.analysis.root_cause.lower()
        assert result.analysis.confidence_score == 0.0

    def test_confidence_boost_from_memory(self, engine, memory, mock_llm):
        """Memory hits boost LLM confidence score."""
        # Seed memories
        run(memory.remember("Related issue A", confidence=0.5))
        run(memory.remember("Related issue B", confidence=0.6))

        result = run(engine.analyze(
            anomaly_title="Similar Issue",
            anomaly_description="Something similar",
        ))

        assert result.confidence_boost > 0
        # Base confidence was 0.85, should be boosted
        assert result.analysis.confidence_score > 0.85

    def test_low_confidence_no_case_study(self, engine, mock_llm):
        """Low confidence RCA does not generate CaseStudy."""
        mock_llm.invoke.return_value = json.dumps({
            "root_cause": "Unclear",
            "confidence_score": 0.3,
            "contributing_factors": [],
            "recommendations": [],
            "related_resources": [],
        })

        result = run(engine.analyze(
            anomaly_title="Mysterious Error",
            anomaly_description="Unknown cause",
            save_to_kb=True,
        ))

        # Only 1 episodic memory (WAL), no procedural (CaseStudy)
        memories = run(engine.memory.recall(
            "Resolution for Mysterious",
            memory_type=MemoryType.PROCEDURAL,
        ))
        assert len(memories) == 0

    def test_multiple_analyses_build_memory(self, engine):
        """Successive analyses accumulate agent memory."""
        for i in range(3):
            run(engine.analyze(
                anomaly_title=f"Issue {i}",
                anomaly_description=f"Description {i}",
            ))

        stats = engine.memory.get_stats()
        # At least 3 episodic + some procedural from case studies
        assert stats["total_memories"] >= 3


class TestDeepPromptBuilding:
    """Test the prompt enrichment logic."""

    def test_empty_context(self, engine):
        """Prompt builds correctly with minimal inputs."""
        prompt = engine._build_deep_prompt(
            title="Test",
            description="Test desc",
            resource_id="",
            resource_type="",
            severity="low",
            context={},
            memory_hints=[],
        )
        assert "Test" in prompt
        assert "Instructions" in prompt

    def test_memory_hints_included(self, engine):
        """Memory hints appear in prompt."""
        hints = [
            {"content": "Past fix: restart pod", "type": "procedural",
             "confidence": 0.8, "source": "rca:1", "recall_count": 3},
        ]
        prompt = engine._build_deep_prompt(
            title="Pod Crash",
            description="CrashLoopBackOff",
            resource_id="pod/x",
            resource_type="k8s_pod",
            severity="high",
            context={},
            memory_hints=hints,
        )
        assert "Past Experience" in prompt
        assert "restart pod" in prompt

    def test_past_incidents_included(self, engine):
        """KB incidents appear in prompt."""
        prompt = engine._build_deep_prompt(
            title="DB Slow",
            description="RDS slow queries",
            resource_id="rds-1",
            resource_type="rds",
            severity="medium",
            context={
                "past_incidents": [
                    "- RDS slow query: missing index on users table",
                ]
            },
            memory_hints=[],
        )
        assert "Similar Past Incidents" in prompt
        assert "missing index" in prompt

    def test_evidence_chain_in_prompt(self, engine):
        """Evidence chain from previous iterations appears in prompt."""
        evidence = [
            EvidenceItem(source="cloudtrail", content="ModifyDBInstance at 14:00", confidence_delta=0.1),
        ]
        prompt = engine._build_deep_prompt(
            title="DB Slow",
            description="Slow",
            resource_id="rds-1",
            resource_type="rds",
            severity="medium",
            context={},
            memory_hints=[],
            evidence_chain=evidence,
            iteration=2,
        )
        assert "Collected Evidence" in prompt
        assert "ModifyDBInstance" in prompt
        assert "iteration 2" in prompt


class TestIteration:
    """Test the iteration loop behavior."""

    def test_iterates_on_low_confidence(self, tmp_db, tmp_path):
        """Engine iterates when confidence < threshold."""
        mem = AgentMemory("rca_agent", db_path=tmp_db)
        mem._memory_md_path = tmp_path / "rca_MEMORY.md"
        mem._embedding_client = _NullEmbeddingClient()

        mock_llm = MagicMock()
        # First call returns low confidence, second returns high
        mock_llm.invoke.side_effect = [
            # Iteration 1: analysis
            json.dumps({"root_cause": "Maybe memory leak", "confidence_score": 0.4,
                        "contributing_factors": [], "recommendations": [], "related_resources": []}),
            # Iteration 1: evidence gap detection
            '[]',
            # Iteration 2: analysis
            json.dumps({"root_cause": "Confirmed memory leak in pod", "confidence_score": 0.8,
                        "contributing_factors": ["No limits"], "recommendations": ["Set limits"],
                        "related_resources": []}),
            # Self-verification
            json.dumps({"valid": True, "adjusted_confidence": 0.8}),
        ]

        base = RCAEngine()
        base.llm = mock_llm
        eng = DeepRCAEngine(base_engine=base, memory=mem, max_iterations=3)

        result = run(eng.analyze(
            anomaly_title="Pod OOM",
            anomaly_description="Pod killed",
        ))

        assert result.iterations >= 2
        assert result.analysis.confidence_score >= 0.7
        assert len(result.iteration_history) >= 2

    def test_stops_at_max_iterations(self, tmp_db, tmp_path):
        """Engine stops after max_iterations even with low confidence."""
        mem = AgentMemory("rca_agent", db_path=tmp_db)
        mem._memory_md_path = tmp_path / "rca_MEMORY.md"
        mem._embedding_client = _NullEmbeddingClient()

        mock_llm = MagicMock()
        # Always return low confidence
        mock_llm.invoke.return_value = json.dumps({
            "root_cause": "Unclear", "confidence_score": 0.3,
            "contributing_factors": [], "recommendations": [], "related_resources": [],
        })

        base = RCAEngine()
        base.llm = mock_llm
        eng = DeepRCAEngine(base_engine=base, memory=mem, max_iterations=2)

        result = run(eng.analyze(
            anomaly_title="Mystery",
            anomaly_description="Unknown issue",
        ))

        assert result.iterations == 2  # Hit max
        assert result.analysis.confidence_score < 0.7

    def test_duration_tracked(self, engine):
        """duration_ms is recorded."""
        result = run(engine.analyze(
            anomaly_title="Test",
            anomaly_description="Test",
        ))
        assert result.duration_ms > 0


class TestSelfVerification:
    """Test the Voyager CriticAgent pattern."""

    def test_verification_adjusts_confidence(self, tmp_db, tmp_path):
        """Self-verification can lower confidence."""
        mem = AgentMemory("rca_agent", db_path=tmp_db)
        mem._memory_md_path = tmp_path / "rca_MEMORY.md"
        mem._embedding_client = _NullEmbeddingClient()

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            # Analysis
            json.dumps({"root_cause": "Network issue", "confidence_score": 0.8,
                        "contributing_factors": [], "recommendations": ["Check SG"],
                        "related_resources": []}),
            # Self-verification: challenge it
            json.dumps({"valid": False, "critique": "Correlation not causation",
                        "adjusted_confidence": 0.6}),
            # Re-iteration with critique
            json.dumps({"root_cause": "SG misconfiguration confirmed", "confidence_score": 0.85,
                        "contributing_factors": ["SG rule"], "recommendations": ["Fix SG"],
                        "related_resources": []}),
            # Re-verify: accept
            json.dumps({"valid": True, "adjusted_confidence": 0.85}),
        ]

        base = RCAEngine()
        base.llm = mock_llm
        eng = DeepRCAEngine(base_engine=base, memory=mem)

        result = run(eng.analyze(
            anomaly_title="Latency Spike",
            anomaly_description="P99 latency > 5s",
        ))

        # Should have re-iterated and now be verified
        assert result.verified
        assert result.iterations >= 2  # Original + re-iteration
        # Check iteration history has re-iteration entry
        re_iters = [h for h in result.iteration_history if h.get("trigger") == "self_verify_re_iteration"]
        assert len(re_iters) >= 1


class TestEvidenceModel:
    """Test evidence data model."""

    def test_evidence_item_summary(self):
        ev = EvidenceItem(
            source="cloudtrail",
            content="ModifyDBInstance called at 14:00",
            confidence_delta=0.15,
        )
        s = ev.summary()
        assert "[cloudtrail]" in s
        assert "+0.15" in s

    def test_negative_confidence_delta(self):
        ev = EvidenceItem(
            source="cloudwatch",
            content="No anomaly in metrics",
            confidence_delta=-0.1,
        )
        s = ev.summary()
        assert "-0.10" in s
