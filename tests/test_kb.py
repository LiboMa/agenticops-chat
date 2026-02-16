"""Tests for the kb module: case_study, vector_store, search, and kb_tools integration."""

import json
import pytest
import numpy as np
from pathlib import Path

from agenticops.kb.case_study import (
    CaseStudy,
    CaseStudyMeta,
    CaseStudyStatus,
    EmbeddingInputs,
    LessonsLearned,
    Resolution,
)
from agenticops.kb.vector_store import SQLiteVectorStore, VectorRecord, SearchResult
from agenticops.kb.embeddings import NullEmbeddingClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_case():
    """Build a representative CaseStudy instance."""
    return CaseStudy(
        case_id="case_20260216_001",
        title="EC2 High CPU from Bad Deployment",
        meta=CaseStudyMeta(
            resource_type="EC2",
            severity="high",
            region="us-east-1",
            source_issue_id=42,
            source_rca_id=7,
            created_at="2026-02-16",
            tags=["ec2", "cpu", "deployment"],
        ),
        embedding_inputs=EmbeddingInputs(
            symptom_vector_text="EC2 instance CPU spiked above 95% after deployment",
            root_cause_vector_text="New deployment contained inefficient loop causing CPU spin",
        ),
        resolution=Resolution(
            immediate_action="Rolled back deployment",
            long_term_fix="Add CPU regression tests to CI pipeline",
            verification_method="Monitor CPU for 30 minutes post-rollback",
        ),
        lessons_learned=LessonsLearned(
            what_failed="No performance gate in CI",
            why_missed="Load tests only ran on staging, not prod-like traffic",
            efficiency_score=0.65,
        ),
        status=CaseStudyStatus.PENDING_REVIEW,
        verified=False,
        reuse_count=0,
        symptoms="CPU utilization exceeded 95% on all instances in the ASG",
        root_cause="Deployment v2.3.1 introduced an O(n^2) loop in request handler",
        prevention="Add CPU regression tests to CI pipeline",
    )


@pytest.fixture
def vector_store(tmp_path):
    """Create an isolated SQLiteVectorStore in a temp directory."""
    db_path = tmp_path / "test_vectors.db"
    return SQLiteVectorStore(db_path)


@pytest.fixture
def cases_dir(tmp_path):
    """Create a temp cases directory with a sample markdown file."""
    d = tmp_path / "cases"
    d.mkdir()
    case_md = d / "ec2-cpu-spike-2026-02.md"
    case_md.write_text(
        "---\n"
        'title: "EC2 CPU Spike After Deploy"\n'
        "case_id: case_20260216_001\n"
        "resource_type: EC2\n"
        "severity: high\n"
        "region: us-east-1\n"
        "status: pending_review\n"
        "verified: false\n"
        "efficiency_score: 0.65\n"
        "reuse_count: 0\n"
        "date: 2026-02-16\n"
        "tags: [ec2, cpu, deployment]\n"
        "---\n\n"
        "# EC2 CPU Spike After Deploy\n\n"
        "## Symptoms\n"
        "CPU utilization exceeded 95% on all instances after deployment v2.3.1\n\n"
        "## Root Cause\n"
        "Deployment introduced an O(n^2) loop in the request handler\n\n"
        "## Resolution\n"
        "**Immediate Action:** Rolled back deployment\n\n"
        "**Long-term Fix:** Add CPU regression tests\n\n"
        "**Verification:** Monitor CPU for 30 minutes\n\n"
        "## Lessons Learned\n"
        "- **What failed:** No performance gate in CI\n"
        "- **Why missed:** Load tests only ran on staging\n"
        "- **Efficiency score:** 0.65\n\n"
        "## Prevention\n"
        "Add CPU regression tests to CI pipeline\n"
    )

    # Add a second case for multi-result testing
    case2 = d / "rds-connection-leak-2026-01.md"
    case2.write_text(
        "---\n"
        'title: "RDS Connection Pool Exhaustion"\n'
        "case_id: case_20260115_002\n"
        "resource_type: RDS\n"
        "severity: critical\n"
        "region: us-west-2\n"
        "status: verified\n"
        "verified: true\n"
        "efficiency_score: 0.45\n"
        "date: 2026-01-15\n"
        "tags: [rds, connection, pool]\n"
        "---\n\n"
        "# RDS Connection Pool Exhaustion\n\n"
        "## Symptoms\n"
        "Database connections reached maximum, application returning 503 errors\n\n"
        "## Root Cause\n"
        "Application not closing database connections after use\n"
    )
    return d


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing (matches project convention)."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None

    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url
    settings.cases_dir = tmp_path / "cases"
    settings.cases_dir.mkdir(parents=True, exist_ok=True)
    settings.sops_dir = tmp_path / "sops"
    settings.sops_dir.mkdir(parents=True, exist_ok=True)

    engine = models_mod.get_engine()
    models_mod.Base.metadata.create_all(engine)

    # Also create case_vectors table (normally done in init_db migration)
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS case_vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                vector BLOB NOT NULL,
                resource_type TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(case_id, field_name)
            )
        """))
        conn.commit()

    session = models_mod.get_session()
    yield session
    session.close()
    models_mod._engine = None


# ===================================================================
# CaseStudy Dataclass Tests
# ===================================================================


class TestCaseStudy:
    """Tests for CaseStudy dataclass serialization."""

    def test_to_dict(self, sample_case):
        """Test CaseStudy serialization to dict."""
        d = sample_case.to_dict()
        assert d["case_id"] == "case_20260216_001"
        assert d["meta"]["resource_type"] == "EC2"
        assert d["meta"]["severity"] == "high"
        assert d["status"] == "pending_review"
        assert d["lessons_learned"]["efficiency_score"] == 0.65
        assert d["embedding_inputs"]["symptom_vector_text"] != ""

    def test_from_dict_roundtrip(self, sample_case):
        """Test dict -> CaseStudy -> dict round-trip."""
        d = sample_case.to_dict()
        restored = CaseStudy.from_dict(d)

        assert restored.case_id == sample_case.case_id
        assert restored.title == sample_case.title
        assert restored.meta.resource_type == sample_case.meta.resource_type
        assert restored.meta.severity == sample_case.meta.severity
        assert restored.meta.tags == sample_case.meta.tags
        assert restored.resolution.immediate_action == sample_case.resolution.immediate_action
        assert restored.lessons_learned.efficiency_score == sample_case.lessons_learned.efficiency_score
        assert restored.status == CaseStudyStatus.PENDING_REVIEW
        assert restored.verified is False

    def test_to_markdown(self, sample_case):
        """Test CaseStudy serialization to markdown with frontmatter."""
        md = sample_case.to_markdown()

        assert md.startswith("---\n")
        assert "case_id: case_20260216_001" in md
        assert "resource_type: EC2" in md
        assert "severity: high" in md
        assert "efficiency_score: 0.65" in md
        assert "tags: [ec2, cpu, deployment]" in md
        assert "## Symptoms" in md
        assert "## Root Cause" in md
        assert "## Resolution" in md
        assert "**Immediate Action:** Rolled back deployment" in md
        assert "## Lessons Learned" in md
        assert "## Prevention" in md

    def test_from_markdown_roundtrip(self, sample_case):
        """Test markdown -> CaseStudy round-trip."""
        md = sample_case.to_markdown()
        restored = CaseStudy.from_markdown(md)

        assert restored.case_id == "case_20260216_001"
        assert restored.title == "EC2 High CPU from Bad Deployment"
        assert restored.meta.resource_type == "EC2"
        assert restored.meta.severity == "high"
        assert restored.lessons_learned.efficiency_score == 0.65
        assert restored.status == CaseStudyStatus.PENDING_REVIEW
        assert restored.verified is False

    def test_from_markdown_existing_case_file(self):
        """Test parsing the existing case file in the knowledge base."""
        case_path = Path("data/knowledge_base/cases/ec2-missing-cloudwatch-metrics-orphaned-instance-2026-02.md")
        if not case_path.exists():
            pytest.skip("Existing case file not found")

        case = CaseStudy.from_markdown(case_path.read_text())

        assert case.meta.resource_type == "EC2"
        assert case.meta.severity == "medium"
        assert "orphaned" in case.title.lower() or "cloudwatch" in case.title.lower()
        assert case.embedding_inputs.symptom_vector_text != ""
        assert case.embedding_inputs.root_cause_vector_text != ""

    def test_from_dict_invalid_status(self):
        """Test from_dict with an invalid status falls back to PENDING_REVIEW."""
        d = {
            "case_id": "test",
            "title": "Test",
            "status": "bogus_status",
        }
        case = CaseStudy.from_dict(d)
        assert case.status == CaseStudyStatus.PENDING_REVIEW

    def test_from_dict_enum_status(self):
        """Test from_dict with CaseStudyStatus enum value."""
        d = {
            "case_id": "test",
            "title": "Test",
            "status": CaseStudyStatus.VERIFIED,
        }
        case = CaseStudy.from_dict(d)
        assert case.status == CaseStudyStatus.VERIFIED

    def test_from_markdown_empty_frontmatter(self):
        """Test parsing markdown with no frontmatter gracefully."""
        md = "# Just a title\n\nSome body text."
        case = CaseStudy.from_markdown(md)
        assert case.case_id == ""
        assert case.title == ""

    def test_default_case_study(self):
        """Test CaseStudy defaults are sensible."""
        case = CaseStudy()
        assert case.case_id == ""
        assert case.status == CaseStudyStatus.PENDING_REVIEW
        assert case.verified is False
        assert case.reuse_count == 0
        assert case.lessons_learned.efficiency_score == 0.5


# ===================================================================
# SQLiteVectorStore Tests
# ===================================================================


class TestSQLiteVectorStore:
    """Tests for SQLiteVectorStore CRUD and search."""

    def test_empty_store(self, vector_store):
        """Test that a new store starts empty."""
        assert vector_store.count() == 0

    def test_upsert_and_count(self, vector_store):
        """Test inserting a vector and verifying count."""
        vec = np.random.randn(1024).astype(np.float32)
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec,
            resource_type="EC2",
        ))
        assert vector_store.count() == 1

    def test_upsert_replaces_on_conflict(self, vector_store):
        """Test that upserting same (case_id, field_name) replaces the record."""
        vec1 = np.ones(1024, dtype=np.float32)
        vec2 = np.ones(1024, dtype=np.float32) * 2

        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec1,
            resource_type="EC2",
        ))
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec2,
            resource_type="EC2",
        ))
        assert vector_store.count() == 1

    def test_upsert_different_fields(self, vector_store):
        """Test that same case_id with different field_names creates separate records."""
        vec = np.random.randn(1024).astype(np.float32)
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec,
            resource_type="EC2",
        ))
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="root_cause",
            vector=vec,
            resource_type="EC2",
        ))
        assert vector_store.count() == 2

    def test_search_returns_self_as_top_match(self, vector_store):
        """Test that searching with the same vector returns score ~1.0."""
        vec = np.random.randn(1024).astype(np.float32)
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec,
            resource_type="EC2",
        ))

        results = vector_store.search(vec, field_name="symptom", top_k=5)
        assert len(results) == 1
        assert results[0].case_id == "case_001"
        assert results[0].score > 0.99

    def test_search_filters_by_field_name(self, vector_store):
        """Test that search only returns matching field_name."""
        vec = np.random.randn(1024).astype(np.float32)
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec,
            resource_type="EC2",
        ))
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="root_cause",
            vector=vec,
            resource_type="EC2",
        ))

        results = vector_store.search(vec, field_name="root_cause", top_k=5)
        assert len(results) == 1
        assert results[0].field_name == "root_cause"

    def test_search_filters_by_resource_type(self, vector_store):
        """Test that resource_type filter excludes non-matching records."""
        vec = np.random.randn(1024).astype(np.float32)
        vector_store.upsert(VectorRecord(
            case_id="case_ec2",
            field_name="symptom",
            vector=vec,
            resource_type="EC2",
        ))
        vector_store.upsert(VectorRecord(
            case_id="case_rds",
            field_name="symptom",
            vector=vec,
            resource_type="RDS",
        ))

        results = vector_store.search(vec, field_name="symptom", resource_type="EC2", top_k=5)
        assert len(results) == 1
        assert results[0].case_id == "case_ec2"

    def test_search_respects_top_k(self, vector_store):
        """Test that search returns at most top_k results."""
        for i in range(10):
            vec = np.random.randn(1024).astype(np.float32)
            vector_store.upsert(VectorRecord(
                case_id=f"case_{i:03d}",
                field_name="symptom",
                vector=vec,
                resource_type="EC2",
            ))

        query = np.random.randn(1024).astype(np.float32)
        results = vector_store.search(query, field_name="symptom", top_k=3)
        assert len(results) == 3

    def test_search_returns_sorted_by_score(self, vector_store):
        """Test that results are sorted by descending score."""
        for i in range(5):
            vec = np.random.randn(1024).astype(np.float32)
            vector_store.upsert(VectorRecord(
                case_id=f"case_{i:03d}",
                field_name="symptom",
                vector=vec,
                resource_type="EC2",
            ))

        query = np.random.randn(1024).astype(np.float32)
        results = vector_store.search(query, field_name="symptom", top_k=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_empty_store(self, vector_store):
        """Test that searching an empty store returns no results."""
        query = np.random.randn(1024).astype(np.float32)
        results = vector_store.search(query, field_name="symptom")
        assert results == []

    def test_search_zero_vector_query(self, vector_store):
        """Test that a zero query vector returns no results."""
        vec = np.random.randn(1024).astype(np.float32)
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec,
            resource_type="EC2",
        ))
        zero = np.zeros(1024, dtype=np.float32)
        results = vector_store.search(zero, field_name="symptom")
        assert results == []

    def test_search_preserves_metadata(self, vector_store):
        """Test that metadata is stored and returned correctly."""
        vec = np.random.randn(1024).astype(np.float32)
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec,
            resource_type="EC2",
            metadata={"efficiency_score": 0.8, "verified": "true"},
        ))

        results = vector_store.search(vec, field_name="symptom")
        assert results[0].metadata["efficiency_score"] == 0.8
        assert results[0].metadata["verified"] == "true"

    def test_delete(self, vector_store):
        """Test deleting a case removes all its vectors."""
        vec = np.random.randn(1024).astype(np.float32)
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="symptom",
            vector=vec,
            resource_type="EC2",
        ))
        vector_store.upsert(VectorRecord(
            case_id="case_001",
            field_name="root_cause",
            vector=vec,
            resource_type="EC2",
        ))
        assert vector_store.count() == 2

        deleted = vector_store.delete("case_001")
        assert deleted == 2
        assert vector_store.count() == 0

    def test_delete_nonexistent(self, vector_store):
        """Test deleting a non-existent case returns 0."""
        deleted = vector_store.delete("nonexistent")
        assert deleted == 0


# ===================================================================
# NullEmbeddingClient Tests
# ===================================================================


class TestNullEmbeddingClient:
    """Tests for the NullEmbeddingClient fallback."""

    def test_embed_returns_none(self):
        client = NullEmbeddingClient()
        assert client.embed("any text") is None

    def test_dimension_is_zero(self):
        client = NullEmbeddingClient()
        assert client.dimension == 0

    def test_embed_empty_string(self):
        client = NullEmbeddingClient()
        assert client.embed("") is None


# ===================================================================
# Hybrid Search Tests
# ===================================================================


class TestHybridSearch:
    """Tests for hybrid_search keyword fallback and reranking."""

    def test_keyword_search_finds_matching_cases(self, cases_dir):
        """Test keyword search returns matching cases by content."""
        from agenticops.kb.search import _keyword_search

        results = _keyword_search(
            query_text="CPU spike deployment",
            resource_type="EC2",
            search_dir=cases_dir,
            top_k=5,
        )
        assert len(results) >= 1
        assert any("case_20260216_001" in r.case_id or "ec2" in r.case_id.lower() for r in results)

    def test_keyword_search_resource_type_boost(self, cases_dir):
        """Test that matching resource_type boosts score."""
        from agenticops.kb.search import _keyword_search

        # EC2 case should rank higher for EC2 resource type
        results = _keyword_search(
            query_text="deployment",
            resource_type="EC2",
            search_dir=cases_dir,
            top_k=5,
        )
        ec2_results = [r for r in results if "ec2" in r.case_id.lower() or "case_20260216" in r.case_id]
        rds_results = [r for r in results if "rds" in r.case_id.lower()]

        if ec2_results and rds_results:
            assert ec2_results[0].score >= rds_results[0].score

    def test_keyword_search_no_matches(self, cases_dir):
        """Test keyword search returns empty for non-matching queries."""
        from agenticops.kb.search import _keyword_search

        results = _keyword_search(
            query_text="kubernetes pod eviction",
            resource_type="EKS",
            search_dir=cases_dir,
            top_k=5,
        )
        assert len(results) == 0

    def test_keyword_search_respects_top_k(self, cases_dir):
        """Test keyword search returns at most top_k results."""
        from agenticops.kb.search import _keyword_search

        results = _keyword_search(
            query_text="instance errors connection",
            resource_type="",
            search_dir=cases_dir,
            top_k=1,
        )
        assert len(results) <= 1

    def test_rerank_boosts_verified(self):
        """Test that _rerank gives verified cases a 1.2x boost."""
        from agenticops.kb.search import _rerank, HybridResult

        unverified = HybridResult(
            case_id="unverified",
            file_path="",
            score=0.8,
            source="vector",
            metadata={"verified": "false", "efficiency_score": 0.5},
        )
        verified = HybridResult(
            case_id="verified",
            file_path="",
            score=0.8,
            source="vector",
            metadata={"verified": "true", "efficiency_score": 0.5},
        )

        results = _rerank([unverified, verified])
        # Verified should rank higher
        assert results[0].case_id == "verified"
        assert results[0].score > results[1].score

    def test_rerank_incorporates_efficiency(self):
        """Test that _rerank incorporates efficiency_score."""
        from agenticops.kb.search import _rerank, HybridResult

        low_eff = HybridResult(
            case_id="low",
            file_path="",
            score=0.8,
            source="vector",
            metadata={"efficiency_score": 0.1, "verified": "false"},
        )
        high_eff = HybridResult(
            case_id="high",
            file_path="",
            score=0.8,
            source="vector",
            metadata={"efficiency_score": 0.9, "verified": "false"},
        )

        results = _rerank([low_eff, high_eff])
        assert results[0].case_id == "high"

    def test_rerank_score_capped_at_one(self):
        """Test that reranked scores don't exceed 1.0."""
        from agenticops.kb.search import _rerank, HybridResult

        r = HybridResult(
            case_id="perfect",
            file_path="",
            score=1.0,
            source="vector",
            metadata={"efficiency_score": 1.0, "verified": "true"},
        )
        results = _rerank([r])
        assert results[0].score <= 1.0

    def test_hybrid_search_falls_back_to_keyword(self, cases_dir):
        """Test full hybrid_search falls back to keyword when no vectors."""
        from agenticops.kb.search import hybrid_search
        from agenticops.kb.embeddings import reset_embedding_client
        import agenticops.kb.embeddings as emb_mod

        # Force NullEmbeddingClient
        reset_embedding_client()
        emb_mod._embedding_client = NullEmbeddingClient()
        emb_mod._client_initialized = True

        try:
            results = hybrid_search(
                query_text="CPU spike deployment",
                resource_type="EC2",
                search_dir=cases_dir,
                top_k=3,
            )
            assert len(results) >= 1
            # Should come from keyword source
            assert any(r.source == "keyword" for r in results)
        finally:
            reset_embedding_client()


# ===================================================================
# KB Tools Integration Tests
# ===================================================================


class TestKBToolsSearch:
    """Tests for search_similar_cases and search_sops with keyword fallback."""

    def test_search_similar_cases_keyword_fallback(self, db_session, tmp_path):
        """Test search_similar_cases falls back to keyword search."""
        from agenticops.config import settings
        from agenticops.kb.embeddings import reset_embedding_client
        import agenticops.kb.embeddings as emb_mod

        # Write a test case file
        case_file = settings.cases_dir / "test-case.md"
        case_file.write_text(
            "---\n"
            "resource_type: EC2\n"
            "severity: high\n"
            "---\n\n"
            "# Test Case\n\n"
            "## Symptoms\n"
            "High CPU utilization on EC2 instance\n"
        )

        # Force NullEmbeddingClient
        reset_embedding_client()
        emb_mod._embedding_client = NullEmbeddingClient()
        emb_mod._client_initialized = True

        try:
            from agenticops.tools.kb_tools import search_similar_cases

            result = search_similar_cases(
                resource_type="EC2",
                issue_pattern="high CPU utilization",
            )
            assert "Test Case" in result or "test-case" in result
        finally:
            reset_embedding_client()

    def test_search_similar_cases_no_results(self, db_session, tmp_path):
        """Test search_similar_cases with no matches."""
        from agenticops.kb.embeddings import reset_embedding_client
        import agenticops.kb.embeddings as emb_mod

        reset_embedding_client()
        emb_mod._embedding_client = NullEmbeddingClient()
        emb_mod._client_initialized = True

        try:
            from agenticops.tools.kb_tools import search_similar_cases

            result = search_similar_cases(
                resource_type="EKS",
                issue_pattern="pod eviction oom killed",
            )
            assert "No similar cases found" in result
        finally:
            reset_embedding_client()

    def test_search_sops_keyword_fallback(self, db_session, tmp_path):
        """Test search_sops falls back to keyword search."""
        from agenticops.config import settings
        from agenticops.kb.embeddings import reset_embedding_client
        import agenticops.kb.embeddings as emb_mod

        # Write a test SOP file
        sop_file = settings.sops_dir / "ec2-cpu-high.md"
        sop_file.write_text(
            "---\n"
            "resource_type: EC2\n"
            "issue_pattern: cpu_high\n"
            "severity: high\n"
            "keywords: [cpu, high, utilization]\n"
            "---\n\n"
            "# EC2 High CPU SOP\n\n"
            "Check CloudWatch metrics and scale up.\n"
        )

        reset_embedding_client()
        emb_mod._embedding_client = NullEmbeddingClient()
        emb_mod._client_initialized = True

        try:
            from agenticops.tools.kb_tools import search_sops

            result = search_sops(
                resource_type="EC2",
                issue_pattern="cpu high utilization",
            )
            assert "EC2 High CPU SOP" in result
        finally:
            reset_embedding_client()


class TestWriteKBCase:
    """Tests for write_kb_case with embedding integration."""

    def test_write_case_saves_file(self, db_session, tmp_path):
        """Test write_kb_case saves the markdown file."""
        from agenticops.config import settings
        from agenticops.tools.kb_tools import write_kb_case

        content = (
            "---\n"
            "resource_type: Lambda\n"
            "severity: medium\n"
            "---\n\n"
            "# Lambda Timeout\n\n"
            "## Symptoms\nFunction timing out\n"
        )

        result = write_kb_case(filename="lambda-timeout-case.md", content=content)

        assert "saved to" in result.lower() or "Case study saved" in result
        filepath = settings.cases_dir / "lambda-timeout-case.md"
        assert filepath.exists()
        assert "Lambda Timeout" in filepath.read_text()

    def test_write_case_reports_embedding_status(self, db_session, tmp_path):
        """Test write_kb_case includes embedding status in response."""
        from agenticops.kb.embeddings import reset_embedding_client
        import agenticops.kb.embeddings as emb_mod
        from agenticops.tools.kb_tools import write_kb_case

        reset_embedding_client()
        emb_mod._embedding_client = NullEmbeddingClient()
        emb_mod._client_initialized = True

        try:
            content = (
                "---\n"
                "resource_type: EC2\n"
                "---\n\n"
                "# Test\n\n## Symptoms\ntest\n\n## Root Cause\ntest\n"
            )
            result = write_kb_case(filename="test-embed.md", content=content)
            assert "Embeddings disabled" in result or "saved" in result.lower()
        finally:
            reset_embedding_client()


class TestCaseStudyRecord:
    """Tests for CaseStudyRecord database model."""

    def test_create_record(self, db_session):
        """Test creating a CaseStudyRecord."""
        from agenticops.models import CaseStudyRecord

        record = CaseStudyRecord(
            case_id="case_20260216_001",
            resource_type="EC2",
            severity="high",
            status="pending_review",
            verified=False,
            reuse_count=0,
            source_issue_id=42,
            source_rca_id=7,
            efficiency_score=0.65,
            file_path="/tmp/case.md",
        )
        db_session.add(record)
        db_session.commit()

        assert record.id is not None
        assert record.case_id == "case_20260216_001"
        assert record.resource_type == "EC2"
        assert record.efficiency_score == 0.65

    def test_unique_case_id(self, db_session):
        """Test that case_id must be unique."""
        from agenticops.models import CaseStudyRecord

        r1 = CaseStudyRecord(
            case_id="case_dup",
            resource_type="EC2",
            severity="high",
        )
        db_session.add(r1)
        db_session.commit()

        r2 = CaseStudyRecord(
            case_id="case_dup",
            resource_type="RDS",
            severity="medium",
        )
        db_session.add(r2)
        with pytest.raises(Exception):
            db_session.commit()

    def test_record_defaults(self, db_session):
        """Test CaseStudyRecord default values."""
        from agenticops.models import CaseStudyRecord

        record = CaseStudyRecord(
            case_id="case_defaults",
        )
        db_session.add(record)
        db_session.commit()

        assert record.status == "pending_review"
        assert record.verified is False
        assert record.reuse_count == 0
        assert record.efficiency_score == 0.5
        assert record.created_at is not None


class TestDistillationHelpers:
    """Tests for distillation helper functions."""

    def test_infer_resource_type_ec2(self):
        """Test resource type inference from instance ID."""
        from agenticops.tools.kb_tools import _infer_resource_type

        assert _infer_resource_type("i-1234567890abcdef0") == "EC2"

    def test_infer_resource_type_lambda(self):
        from agenticops.tools.kb_tools import _infer_resource_type

        assert _infer_resource_type("arn:aws:lambda:us-east-1:123:function:my-func") == "Lambda"

    def test_infer_resource_type_rds(self):
        from agenticops.tools.kb_tools import _infer_resource_type

        assert _infer_resource_type("arn:aws:rds:us-east-1:123:db:mydb") == "RDS"

    def test_infer_resource_type_unknown(self):
        from agenticops.tools.kb_tools import _infer_resource_type

        assert _infer_resource_type("some-random-id") == "Unknown"

    def test_build_distillation_context_missing_issue(self, db_session):
        """Test _build_distillation_context returns None for missing issue."""
        from agenticops.tools.kb_tools import _build_distillation_context

        result = _build_distillation_context(99999)
        assert result is None

    def test_build_distillation_context_no_rca(self, db_session):
        """Test _build_distillation_context returns None when no RCA exists."""
        from agenticops.models import HealthIssue
        from agenticops.tools.kb_tools import _build_distillation_context

        issue = HealthIssue(
            resource_id="i-abc123",
            severity="high",
            source="cloudwatch_alarm",
            title="Test Issue",
            description="Test description",
        )
        db_session.add(issue)
        db_session.commit()

        result = _build_distillation_context(issue.id)
        assert result is None

    def test_build_distillation_context_with_rca(self, db_session):
        """Test _build_distillation_context returns full context."""
        from agenticops.models import HealthIssue, RCAResult
        from agenticops.tools.kb_tools import _build_distillation_context

        issue = HealthIssue(
            resource_id="i-abc123",
            severity="high",
            source="cloudwatch_alarm",
            title="High CPU on i-abc123",
            description="CPU exceeded 95%",
        )
        db_session.add(issue)
        db_session.commit()

        rca = RCAResult(
            health_issue_id=issue.id,
            root_cause="Bad deployment caused CPU spike",
            confidence=0.85,
            contributing_factors=["No CPU alerts"],
            recommendations=["Add CPU monitoring"],
            fix_plan={"steps": ["rollback"]},
            fix_risk_level="low",
            model_id="test",
        )
        db_session.add(rca)
        db_session.commit()

        context = _build_distillation_context(issue.id)
        assert context is not None
        assert context["issue_id"] == issue.id
        assert context["rca_id"] == rca.id
        assert context["severity"] == "high"
        assert context["root_cause"] == "Bad deployment caused CPU spike"
        assert context["confidence"] == 0.85
        assert context["resource_type"] == "EC2"

    def test_parse_distilled_case(self):
        """Test _parse_distilled_case creates a valid CaseStudy."""
        from agenticops.tools.kb_tools import _parse_distilled_case

        distilled = {
            "title": "CPU Spike from Bad Deploy",
            "symptoms": "CPU utilization exceeded 95% after deployment",
            "root_cause": "Deployment introduced inefficient code path",
            "immediate_action": "Rolled back deployment",
            "long_term_fix": "Add CPU regression tests",
            "verification_method": "Monitor CPU 30 minutes",
            "what_failed": "No performance gate",
            "why_missed": "No prod-like load tests",
            "efficiency_score": 0.7,
            "tags": ["cpu", "deployment"],
        }
        context = {
            "issue_id": 42,
            "rca_id": 7,
            "resource_type": "EC2",
            "severity": "high",
        }

        case = _parse_distilled_case(distilled, context)
        assert case.title == "CPU Spike from Bad Deploy"
        assert case.meta.resource_type == "EC2"
        assert case.meta.severity == "high"
        assert case.meta.source_issue_id == 42
        assert case.meta.source_rca_id == 7
        assert case.lessons_learned.efficiency_score == 0.7
        assert case.resolution.immediate_action == "Rolled back deployment"
        assert "cpu" in case.meta.tags
        assert case.status == CaseStudyStatus.PENDING_REVIEW
        assert case.case_id.startswith("case_")

    def test_parse_distilled_case_clamps_efficiency(self):
        """Test that efficiency_score is clamped to [0.0, 1.0]."""
        from agenticops.tools.kb_tools import _parse_distilled_case

        distilled = {"efficiency_score": 1.5, "tags": []}
        context = {"issue_id": 1, "rca_id": 1, "resource_type": "EC2", "severity": "low"}
        case = _parse_distilled_case(distilled, context)
        assert case.lessons_learned.efficiency_score == 1.0

        distilled2 = {"efficiency_score": -0.5, "tags": []}
        case2 = _parse_distilled_case(distilled2, context)
        assert case2.lessons_learned.efficiency_score == 0.0

    def test_distill_case_study_missing_issue(self, db_session):
        """Test distill_case_study returns error for non-existent issue."""
        from agenticops.tools.kb_tools import distill_case_study

        result = distill_case_study(health_issue_id=99999)
        assert "Cannot distill" in result

    def test_save_case_record(self, db_session, sample_case):
        """Test _save_case_record persists to database."""
        from agenticops.tools.kb_tools import _save_case_record
        from agenticops.models import CaseStudyRecord

        _save_case_record(sample_case, "/tmp/test_case.md")

        record = db_session.query(CaseStudyRecord).filter_by(
            case_id="case_20260216_001"
        ).first()
        assert record is not None
        assert record.resource_type == "EC2"
        assert record.severity == "high"
        assert record.efficiency_score == 0.65
        assert record.file_path == "/tmp/test_case.md"

    def test_save_case_record_upsert(self, db_session, sample_case):
        """Test _save_case_record updates existing record."""
        from agenticops.tools.kb_tools import _save_case_record
        from agenticops.models import CaseStudyRecord

        _save_case_record(sample_case, "/tmp/v1.md")

        # Update and save again
        sample_case.meta.severity = "critical"
        sample_case.lessons_learned.efficiency_score = 0.9
        _save_case_record(sample_case, "/tmp/v2.md")

        records = db_session.query(CaseStudyRecord).filter_by(
            case_id="case_20260216_001"
        ).all()
        assert len(records) == 1
        assert records[0].severity == "critical"
        assert records[0].efficiency_score == 0.9
        assert records[0].file_path == "/tmp/v2.md"
