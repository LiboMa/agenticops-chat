"""Property-based tests for MemoryService — fact upsert idempotency.

Feature: chat-session-persistence, Property 8: 事实 Upsert 幂等性

Uses hypothesis to generate sequences of facts with potentially duplicate
(category, key) pairs, upserts them all via MemoryService._upsert_facts(),
then verifies that for each unique (category, key) only one record exists
in the DB and its value/confidence_score match the LAST upsert.

**Validates: Requirements 6.3**
"""

import uuid
from contextlib import contextmanager

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from agenticops.models import AgentMemory, AgentMemoryFact, Base, init_db
from agenticops.web.memory_service import MemoryService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Categories must be one of the valid MemoryService categories
_category_st = st.sampled_from(["user_preference", "infra_context", "team_info"])

# Keys: short non-empty strings (use a small alphabet to increase collision rate)
_key_st = st.text(
    alphabet="abcdefgh",
    min_size=1,
    max_size=5,
)

# Values: non-empty printable strings
_value_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
)

# Confidence score: float in [0.0, 1.0]
_confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# A single fact dict
_fact_st = st.fixed_dictionaries({
    "category": _category_st,
    "key": _key_st,
    "value": _value_st,
    "confidence_score": _confidence_st,
})

# A sequence of facts (2-20 items, likely to contain duplicate category+key)
_facts_sequence_st = st.lists(_fact_st, min_size=2, max_size=20)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_test_engine():
    """Create a fresh in-memory SQLite engine with all tables."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _make_service() -> MemoryService:
    """Create a MemoryService instance (LLM client not needed for upsert)."""
    svc = MemoryService.__new__(MemoryService)
    svc.region = "us-east-1"
    svc.model_id = "test"
    svc._client = None
    return svc


@contextmanager
def _patched_db_session(engine):
    """Context manager that yields a session bound to the given engine.

    Designed to be used as a replacement for get_db_session() in tests.
    """
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Property 8: 事实 Upsert 幂等性
# ---------------------------------------------------------------------------

class TestFactUpsertIdempotency:
    """Property 8: 事实 Upsert 幂等性

    For any sequence of facts (containing duplicate category+key pairs),
    after upserting all facts, the database should contain exactly one
    record per unique (category, key), with the value and confidence_score
    from the LAST upsert in the sequence.

    Feature: chat-session-persistence, Property 8: 事实 Upsert 幂等性
    **Validates: Requirements 6.3**
    """

    @given(facts_sequence=_facts_sequence_st)
    @h_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_upsert_keeps_one_record_per_category_key(self, facts_sequence):
        """DB contains exactly one record per unique (category, key)."""
        engine = _create_test_engine()
        svc = _make_service()
        session_id = f"test-{uuid.uuid4().hex[:8]}"

        # Patch get_db_session to use our in-memory engine
        import unittest.mock as mock

        with mock.patch(
            "agenticops.web.memory_service.get_db_session",
            lambda: _patched_db_session(engine),
        ):
            svc._upsert_facts(session_id, facts_sequence)

        # Compute expected: last occurrence of each (category, key)
        expected: dict[tuple[str, str], dict] = {}
        for fact in facts_sequence:
            ck = (fact["category"], fact["key"])
            expected[ck] = fact

        # Query all facts from DB
        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as db:
            all_facts = db.query(AgentMemoryFact).all()

            # One record per unique (category, key)
            assert len(all_facts) == len(expected), (
                f"Expected {len(expected)} unique facts, got {len(all_facts)}. "
                f"Sequence had {len(facts_sequence)} items."
            )

            # Each record matches the last upsert's value and confidence
            for fact_row in all_facts:
                ck = (fact_row.category, fact_row.key)
                assert ck in expected, (
                    f"Unexpected (category, key) in DB: {ck}"
                )
                exp = expected[ck]
                assert fact_row.value == exp["value"], (
                    f"Value mismatch for {ck}: "
                    f"expected {exp['value']!r}, got {fact_row.value!r}"
                )
                assert abs(fact_row.confidence_score - exp["confidence_score"]) < 1e-6, (
                    f"Confidence mismatch for {ck}: "
                    f"expected {exp['confidence_score']}, got {fact_row.confidence_score}"
                )

        engine.dispose()

    @given(facts_sequence=_facts_sequence_st)
    @h_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_last_value_wins_on_duplicate_keys(self, facts_sequence):
        """When the same (category, key) appears multiple times, the last value wins."""
        engine = _create_test_engine()
        svc = _make_service()
        session_id = f"test-{uuid.uuid4().hex[:8]}"

        import unittest.mock as mock

        with mock.patch(
            "agenticops.web.memory_service.get_db_session",
            lambda: _patched_db_session(engine),
        ):
            svc._upsert_facts(session_id, facts_sequence)

        # Build map of last occurrence
        last_seen: dict[tuple[str, str], dict] = {}
        for fact in facts_sequence:
            last_seen[(fact["category"], fact["key"])] = fact

        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as db:
            for ck, exp in last_seen.items():
                row = (
                    db.query(AgentMemoryFact)
                    .filter(
                        AgentMemoryFact.category == ck[0],
                        AgentMemoryFact.key == ck[1],
                    )
                    .one()
                )
                assert row.value == exp["value"], (
                    f"For {ck}, expected value {exp['value']!r} but got {row.value!r}"
                )
                assert abs(row.confidence_score - exp["confidence_score"]) < 1e-6, (
                    f"For {ck}, expected confidence {exp['confidence_score']} "
                    f"but got {row.confidence_score}"
                )
                assert row.source_session_id == session_id

        engine.dispose()


# ---------------------------------------------------------------------------
# Property 9: 高置信度事实过滤
# ---------------------------------------------------------------------------

# Additional strategies for Property 9

# A single fact with explicit confidence for direct DB insertion
_fact_with_confidence_st = st.fixed_dictionaries({
    "category": _category_st,
    "key": _key_st,
    "value": _value_st,
    "confidence_score": _confidence_st,
})

# A list of facts (1-20 items) for confidence filtering tests
_facts_for_filter_st = st.lists(_fact_with_confidence_st, min_size=1, max_size=20)

# Random min_confidence threshold in [0.0, 1.0]
_threshold_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


class TestHighConfidenceFactFiltering:
    """Property 9: 高置信度事实过滤

    For any set of facts with varying confidence_scores,
    get_facts(min_confidence=threshold) should return ONLY facts with
    confidence_score >= threshold, and should NOT omit any qualifying facts.

    Feature: chat-session-persistence, Property 9: 高置信度事实过滤
    **Validates: Requirements 6.4**
    """

    @given(facts_sequence=_facts_for_filter_st)
    @h_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_default_threshold_returns_only_high_confidence(self, facts_sequence):
        """get_facts() with default min_confidence=0.7 returns only facts with score >= 0.7."""
        engine = _create_test_engine()
        svc = _make_service()
        session_id = f"test-{uuid.uuid4().hex[:8]}"

        import unittest.mock as mock

        with mock.patch(
            "agenticops.web.memory_service.get_db_session",
            lambda: _patched_db_session(engine),
        ):
            svc._upsert_facts(session_id, facts_sequence)

        # Compute expected: last occurrence per (category, key), then filter >= 0.7
        last_seen: dict[tuple[str, str], dict] = {}
        for fact in facts_sequence:
            last_seen[(fact["category"], fact["key"])] = fact

        expected_high = {
            ck: f for ck, f in last_seen.items()
            if f["confidence_score"] >= 0.7
        }

        with mock.patch(
            "agenticops.web.memory_service.get_db_session",
            lambda: _patched_db_session(engine),
        ):
            result = svc.get_facts(min_confidence=0.7)

        # All returned facts must have confidence >= 0.7
        for fact_row in result:
            assert fact_row.confidence_score >= 0.7, (
                f"Returned fact ({fact_row.category}, {fact_row.key}) has "
                f"confidence {fact_row.confidence_score} < 0.7"
            )

        # No qualifying facts should be missing
        result_keys = {(f.category, f.key) for f in result}
        for ck in expected_high:
            assert ck in result_keys, (
                f"Expected fact {ck} with confidence "
                f"{expected_high[ck]['confidence_score']} >= 0.7 is missing from results"
            )

        # Count must match
        assert len(result) == len(expected_high), (
            f"Expected {len(expected_high)} high-confidence facts, got {len(result)}"
        )

        engine.dispose()

    @given(facts_sequence=_facts_for_filter_st, threshold=_threshold_st)
    @h_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_random_threshold_filters_correctly(self, facts_sequence, threshold):
        """get_facts(min_confidence=threshold) returns only facts with score >= threshold."""
        engine = _create_test_engine()
        svc = _make_service()
        session_id = f"test-{uuid.uuid4().hex[:8]}"

        import unittest.mock as mock

        with mock.patch(
            "agenticops.web.memory_service.get_db_session",
            lambda: _patched_db_session(engine),
        ):
            svc._upsert_facts(session_id, facts_sequence)

        # Compute expected: last occurrence per (category, key), then filter >= threshold
        last_seen: dict[tuple[str, str], dict] = {}
        for fact in facts_sequence:
            last_seen[(fact["category"], fact["key"])] = fact

        expected_filtered = {
            ck: f for ck, f in last_seen.items()
            if f["confidence_score"] >= threshold
        }

        with mock.patch(
            "agenticops.web.memory_service.get_db_session",
            lambda: _patched_db_session(engine),
        ):
            result = svc.get_facts(min_confidence=threshold)

        # All returned facts must have confidence >= threshold
        for fact_row in result:
            assert fact_row.confidence_score >= threshold, (
                f"Returned fact ({fact_row.category}, {fact_row.key}) has "
                f"confidence {fact_row.confidence_score} < threshold {threshold}"
            )

        # No qualifying facts should be missing
        result_keys = {(f.category, f.key) for f in result}
        for ck in expected_filtered:
            assert ck in result_keys, (
                f"Expected fact {ck} with confidence "
                f"{expected_filtered[ck]['confidence_score']} >= {threshold} "
                f"is missing from results"
            )

        # Count must match
        assert len(result) == len(expected_filtered), (
            f"Expected {len(expected_filtered)} facts with confidence >= {threshold}, "
            f"got {len(result)}"
        )

        engine.dispose()


# ---------------------------------------------------------------------------
# Property 10: 经验注入格式完整性
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta

# Strategy for memory_type (must be one of the valid types)
_memory_type_st = st.sampled_from(["problem", "root_cause", "solution"])

# Strategy for session_id (UUID-like strings)
_session_id_st = st.uuids().map(str)

# Strategy for content_text (non-empty printable strings)
_content_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
)

# Strategy for created_at (datetime within a reasonable range)
_created_at_st = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)


class _FakeAgentMemory:
    """Lightweight stand-in for AgentMemory (avoids SQLAlchemy instrumentation)."""

    def __init__(self, session_id: str, memory_type: str, content_text: str, created_at: datetime):
        self.id = 1
        self.session_id = session_id
        self.memory_type = memory_type
        self.content_text = content_text
        self.embedding_vector = None
        self.created_at = created_at


# Strategy for a single experience tuple
_experience_st = st.tuples(_session_id_st, _memory_type_st, _content_text_st, _created_at_st)

# Strategy for a non-empty list of experiences (1-10 items)
_experiences_list_st = st.lists(_experience_st, min_size=1, max_size=10)


class TestExperienceInjectionFormat:
    """Property 10: 经验注入格式完整性

    For any non-empty list of retrieved historical experiences,
    the text injected into the system prompt should contain each
    experience's source session_id and created_at timestamp
    (formatted as %Y-%m-%d %H:%M:%S).

    Feature: chat-session-persistence, Property 10: 经验注入格式完整性
    **Validates: Requirements 7.4**
    """

    @given(experiences=_experiences_list_st)
    @h_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_injected_text_contains_session_id_and_created_at(self, experiences):
        """build_memory_context() output contains each experience's session_id and created_at."""
        import unittest.mock as mock

        # Build AgentMemory objects from generated tuples
        memories = [
            _FakeAgentMemory(sid, mtype, ctext, cat)
            for sid, mtype, ctext, cat in experiences
        ]

        svc = _make_service()

        # Mock get_facts to return empty (focus on experience format)
        # Mock search_experiences to return our generated memories
        with mock.patch.object(svc, "get_facts", return_value=[]), \
             mock.patch.object(svc, "search_experiences", return_value=memories):
            result = svc.build_memory_context(
                session_id="test-session",
                initial_context="some query text",
            )

        # Verify the output contains each experience's session_id and created_at
        for sid, mtype, ctext, cat in experiences:
            expected_created_str = cat.strftime("%Y-%m-%d %H:%M:%S")
            assert sid in result, (
                f"session_id {sid!r} not found in memory context output"
            )
            assert expected_created_str in result, (
                f"created_at {expected_created_str!r} not found in memory context output"
            )


# ---------------------------------------------------------------------------
# Property 11: 相似度阈值过滤
# ---------------------------------------------------------------------------

import numpy as np

# Strategy for embedding dimension (keep small for speed)
_embedding_dim_st = st.integers(min_value=4, max_value=32)

# Strategy for a non-zero float vector component
_vector_component_st = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def _make_embedding(components: list[float]) -> np.ndarray:
    """Create a float32 numpy array from a list of floats."""
    return np.array(components, dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# Strategy: generate a list of non-zero embedding vectors of the same dimension
@st.composite
def _memories_with_embeddings(draw):
    """Generate a query vector and a list of memory embeddings with known similarities.

    Returns (dim, query_vec, memories_data) where memories_data is a list of
    (session_id, memory_type, content_text, embedding_vec) tuples.
    """
    dim = draw(st.integers(min_value=4, max_value=32))
    n_memories = draw(st.integers(min_value=1, max_value=15))

    # Generate a non-zero query vector
    query_components = draw(
        st.lists(
            _vector_component_st,
            min_size=dim,
            max_size=dim,
        ).filter(lambda cs: any(abs(c) > 1e-7 for c in cs))
    )
    query_vec = _make_embedding(query_components)

    memories_data = []
    for i in range(n_memories):
        # Generate a non-zero memory vector
        mem_components = draw(
            st.lists(
                _vector_component_st,
                min_size=dim,
                max_size=dim,
            ).filter(lambda cs: any(abs(c) > 1e-7 for c in cs))
        )
        mem_vec = _make_embedding(mem_components)
        sid = f"session-{i}"
        mtype = draw(_memory_type_st)
        ctext = f"experience-{i}"
        memories_data.append((sid, mtype, ctext, mem_vec))

    return (dim, query_vec, memories_data)


# Strategy for min_score threshold in [0.0, 1.0]
_min_score_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


class _FakeAgentMemoryWithEmbedding:
    """Lightweight stand-in for AgentMemory with embedding_vector bytes."""

    def __init__(self, id: int, session_id: str, memory_type: str,
                 content_text: str, embedding_vector: bytes, created_at: datetime):
        self.id = id
        self.session_id = session_id
        self.memory_type = memory_type
        self.content_text = content_text
        self.embedding_vector = embedding_vector
        self.created_at = created_at


class TestSimilarityThresholdFiltering:
    """Property 11: 相似度阈值过滤

    For any vector search result set, search_experiences(min_score=threshold)
    should return ONLY results with cosine similarity >= threshold.

    Feature: chat-session-persistence, Property 11: 相似度阈值过滤
    **Validates: Requirements 7.5**
    """

    @given(data=_memories_with_embeddings(), min_score=_min_score_st)
    @h_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
    def test_search_returns_only_above_threshold(self, data, min_score):
        """search_experiences(min_score=X) returns only memories with similarity >= X."""
        dim, query_vec, memories_data = data

        import unittest.mock as mock

        svc = _make_service()

        # Build fake AgentMemory objects with embedding_vector as bytes
        db_memories = []
        for i, (sid, mtype, ctext, mem_vec) in enumerate(memories_data):
            mem = _FakeAgentMemoryWithEmbedding(
                id=i + 1,
                session_id=sid,
                memory_type=mtype,
                content_text=ctext,
                embedding_vector=mem_vec.tobytes(),
                created_at=datetime(2025, 1, 1),
            )
            db_memories.append(mem)

        # Compute expected similarities
        expected_above = []
        for sid, mtype, ctext, mem_vec in memories_data:
            sim = _cosine_similarity(query_vec, mem_vec)
            if sim >= min_score:
                expected_above.append((sim, sid))

        # Mock _generate_embedding to return our query vector
        with mock.patch.object(svc, "_generate_embedding", return_value=query_vec):
            mock_session = mock.MagicMock()
            mock_session.query.return_value.filter.return_value.all.return_value = db_memories
            mock_session.expunge_all = mock.MagicMock()

            @contextmanager
            def _mock_db():
                yield mock_session

            with mock.patch(
                "agenticops.web.memory_service.get_db_session",
                _mock_db,
            ):
                results = svc.search_experiences(
                    query_text="test query",
                    top_k=100,  # large top_k to not limit results
                    min_score=min_score,
                )

        # All returned results must have similarity >= min_score
        for mem in results:
            mem_vec = np.frombuffer(mem.embedding_vector, dtype=np.float32)
            sim = _cosine_similarity(query_vec, mem_vec)
            assert sim >= min_score, (
                f"Returned memory {mem.session_id} has similarity {sim:.6f} "
                f"< min_score {min_score}"
            )

        # No qualifying memories should be missing (accounting for top_k)
        returned_sids = {m.session_id for m in results}
        for sim, sid in expected_above:
            assert sid in returned_sids, (
                f"Memory {sid} with similarity {sim:.6f} >= {min_score} "
                f"is missing from results"
            )

    @given(data=_memories_with_embeddings())
    @h_settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
    def test_default_threshold_filters_below_0_6(self, data):
        """search_experiences() with default min_score=0.6 excludes results below 0.6."""
        dim, query_vec, memories_data = data

        import unittest.mock as mock

        svc = _make_service()

        db_memories = []
        for i, (sid, mtype, ctext, mem_vec) in enumerate(memories_data):
            mem = _FakeAgentMemoryWithEmbedding(
                id=i + 1,
                session_id=sid,
                memory_type=mtype,
                content_text=ctext,
                embedding_vector=mem_vec.tobytes(),
                created_at=datetime(2025, 1, 1),
            )
            db_memories.append(mem)

        with mock.patch.object(svc, "_generate_embedding", return_value=query_vec):
            mock_session = mock.MagicMock()
            mock_session.query.return_value.filter.return_value.all.return_value = db_memories
            mock_session.expunge_all = mock.MagicMock()

            @contextmanager
            def _mock_db():
                yield mock_session

            with mock.patch(
                "agenticops.web.memory_service.get_db_session",
                _mock_db,
            ):
                results = svc.search_experiences(
                    query_text="test query",
                    top_k=100,
                )

        # All returned results must have similarity >= 0.6 (default)
        for mem in results:
            mem_vec = np.frombuffer(mem.embedding_vector, dtype=np.float32)
            sim = _cosine_similarity(query_vec, mem_vec)
            assert sim >= 0.6, (
                f"Returned memory {mem.session_id} has similarity {sim:.6f} "
                f"< default min_score 0.6"
            )

        # Verify no qualifying memories are missing
        expected_above = []
        for sid, mtype, ctext, mem_vec in memories_data:
            sim = _cosine_similarity(query_vec, mem_vec)
            if sim >= 0.6:
                expected_above.append(sid)

        returned_sids = {m.session_id for m in results}
        for sid in expected_above:
            assert sid in returned_sids, (
                f"Memory {sid} with similarity >= 0.6 is missing from results"
            )
