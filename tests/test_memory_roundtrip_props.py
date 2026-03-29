"""Property-based tests for memory serialization roundtrip consistency.

Feature: chat-session-persistence, Property 12: 记忆序列化往返一致性（MemoryFact, AgentMemory, SessionSummary）

Uses hypothesis to generate random AgentMemoryFact, AgentMemory, and
SessionSummary objects, write them to an in-memory SQLite database, read
them back, and verify all fields match.

**Validates: Requirements 10.1, 10.2, 10.3**
"""

import uuid
from contextlib import contextmanager

from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.models import AgentMemoryFact, AgentMemory, ChatSession, SessionSummary, Base


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_category_st = st.sampled_from(["user_preference", "infra_context", "team_info"])

_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
)

_value_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
)

_confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

_session_id_st = st.uuids().map(str)


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


# ---------------------------------------------------------------------------
# Property 12: 记忆序列化往返一致性（MemoryFact）
# ---------------------------------------------------------------------------

class TestMemoryFactRoundtrip:
    """Property 12: 记忆序列化往返一致性（MemoryFact）

    For any valid AgentMemoryFact object, serializing it to the database
    and then deserializing it back should produce an equivalent object
    with all fields matching.

    Feature: chat-session-persistence, Property 12: 记忆序列化往返一致性（MemoryFact）
    **Validates: Requirements 10.1**
    """

    @given(
        category=_category_st,
        key=_key_st,
        value=_value_st,
        confidence_score=_confidence_st,
        source_session_id=_session_id_st,
    )
    @h_settings(
        max_examples=150,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_memoryfact_roundtrip_all_fields_match(
        self, category, key, value, confidence_score, source_session_id
    ):
        """Write an AgentMemoryFact to DB, read it back, verify all fields."""
        engine = _create_test_engine()
        Session = sessionmaker(bind=engine)

        # Write
        with Session() as session:
            fact = AgentMemoryFact(
                category=category,
                key=key,
                value=value,
                confidence_score=confidence_score,
                source_session_id=source_session_id,
            )
            session.add(fact)
            session.commit()
            fact_id = fact.id

        # Read back
        with Session() as session:
            loaded = session.query(AgentMemoryFact).filter_by(id=fact_id).one()

            assert loaded.category == category, (
                f"category mismatch: expected {category!r}, got {loaded.category!r}"
            )
            assert loaded.key == key, (
                f"key mismatch: expected {key!r}, got {loaded.key!r}"
            )
            assert loaded.value == value, (
                f"value mismatch: expected {value!r}, got {loaded.value!r}"
            )
            assert abs(loaded.confidence_score - confidence_score) < 1e-6, (
                f"confidence_score mismatch: expected {confidence_score}, "
                f"got {loaded.confidence_score}"
            )
            assert loaded.source_session_id == source_session_id, (
                f"source_session_id mismatch: expected {source_session_id!r}, "
                f"got {loaded.source_session_id!r}"
            )
            assert loaded.created_at is not None, "created_at should not be None"
            assert loaded.updated_at is not None, "updated_at should not be None"

        engine.dispose()

    @given(
        category=_category_st,
        key=_key_st,
        value=_value_st,
        confidence_score=_confidence_st,
        source_session_id=_session_id_st,
    )
    @h_settings(
        max_examples=150,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_memoryfact_roundtrip_unique_constraint_preserved(
        self, category, key, value, confidence_score, source_session_id
    ):
        """Writing two facts with the same (category, key) respects the unique constraint."""
        engine = _create_test_engine()
        Session = sessionmaker(bind=engine)

        # Write first fact
        with Session() as session:
            fact1 = AgentMemoryFact(
                category=category,
                key=key,
                value=value,
                confidence_score=confidence_score,
                source_session_id=source_session_id,
            )
            session.add(fact1)
            session.commit()

        # Attempt to write a second fact with the same (category, key)
        # should raise IntegrityError due to unique constraint
        from sqlalchemy.exc import IntegrityError

        with Session() as session:
            fact2 = AgentMemoryFact(
                category=category,
                key=key,
                value="different_value",
                confidence_score=0.5,
                source_session_id=str(uuid.uuid4()),
            )
            session.add(fact2)
            try:
                session.commit()
                # If we get here, the constraint wasn't enforced — fail
                assert False, (
                    f"Expected IntegrityError for duplicate (category={category!r}, key={key!r})"
                )
            except IntegrityError:
                session.rollback()

        # Verify only one record exists
        with Session() as session:
            count = (
                session.query(AgentMemoryFact)
                .filter_by(category=category, key=key)
                .count()
            )
            assert count == 1, (
                f"Expected 1 record for ({category!r}, {key!r}), got {count}"
            )

        engine.dispose()


# ---------------------------------------------------------------------------
# AgentMemory Strategies
# ---------------------------------------------------------------------------

_memory_type_st = st.sampled_from(["problem", "root_cause", "solution"])

_content_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=300,
)

_memory_session_id_st = st.uuids().map(str)


# ---------------------------------------------------------------------------
# Property 12: 记忆序列化往返一致性（AgentMemory）
# ---------------------------------------------------------------------------

class TestAgentMemoryRoundtrip:
    """Property 12: 记忆序列化往返一致性（AgentMemory）

    For any valid AgentMemory object (without embedding_vector),
    serializing it to the database and then deserializing it back should
    produce an equivalent object with content_text, session_id, and
    memory_type matching.

    Feature: chat-session-persistence, Property 12: 记忆序列化往返一致性（AgentMemory）
    **Validates: Requirements 10.2**
    """

    @given(
        session_id=_memory_session_id_st,
        memory_type=_memory_type_st,
        content_text=_content_text_st,
    )
    @h_settings(
        max_examples=150,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_agent_memory_roundtrip_all_fields_match(
        self, session_id, memory_type, content_text
    ):
        """Write an AgentMemory to DB (no embedding_vector), read it back, verify fields."""
        engine = _create_test_engine()
        Session = sessionmaker(bind=engine)

        # Write
        with Session() as session:
            memory = AgentMemory(
                session_id=session_id,
                memory_type=memory_type,
                content_text=content_text,
                embedding_vector=None,
            )
            session.add(memory)
            session.commit()
            memory_id = memory.id

        # Read back
        with Session() as session:
            loaded = session.query(AgentMemory).filter_by(id=memory_id).one()

            assert loaded.session_id == session_id, (
                f"session_id mismatch: expected {session_id!r}, got {loaded.session_id!r}"
            )
            assert loaded.memory_type == memory_type, (
                f"memory_type mismatch: expected {memory_type!r}, got {loaded.memory_type!r}"
            )
            assert loaded.content_text == content_text, (
                f"content_text mismatch: expected {content_text!r}, got {loaded.content_text!r}"
            )
            assert loaded.embedding_vector is None, (
                "embedding_vector should be None for this test"
            )
            assert loaded.created_at is not None, "created_at should not be None"

        engine.dispose()


# ---------------------------------------------------------------------------
# SessionSummary Strategies
# ---------------------------------------------------------------------------

_summary_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=500,
)

_message_range_st = st.integers(min_value=1, max_value=10_000)


# ---------------------------------------------------------------------------
# Property 12: 记忆序列化往返一致性（SessionSummary）
# ---------------------------------------------------------------------------

class TestSessionSummaryRoundtrip:
    """Property 12: 记忆序列化往返一致性（SessionSummary）

    For any valid SessionSummary object, serializing it to the database
    and then deserializing it back should produce an equivalent object
    with summary_text, message_range_start, and message_range_end matching.

    Feature: chat-session-persistence, Property 12: 记忆序列化往返一致性（SessionSummary）
    **Validates: Requirements 10.3**
    """

    @given(
        summary_text=_summary_text_st,
        range_start=_message_range_st,
        range_end=_message_range_st,
    )
    @h_settings(
        max_examples=150,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_session_summary_roundtrip_all_fields_match(
        self, summary_text, range_start, range_end
    ):
        """Write a SessionSummary to DB, read it back, verify summary_text roundtrips."""
        engine = _create_test_engine()
        Session = sessionmaker(bind=engine)

        # SessionSummary has FK to chat_sessions.id, so create a ChatSession first
        with Session() as session:
            chat_session = ChatSession(
                session_id=str(uuid.uuid4()),
                name="test-session",
            )
            session.add(chat_session)
            session.commit()
            chat_session_id = chat_session.id

        # Write SessionSummary
        with Session() as session:
            summary = SessionSummary(
                session_id=chat_session_id,
                summary_text=summary_text,
                message_range_start=range_start,
                message_range_end=range_end,
            )
            session.add(summary)
            session.commit()
            summary_id = summary.id

        # Read back
        with Session() as session:
            loaded = session.query(SessionSummary).filter_by(id=summary_id).one()

            assert loaded.summary_text == summary_text, (
                f"summary_text mismatch: expected {summary_text!r}, got {loaded.summary_text!r}"
            )
            assert loaded.session_id == chat_session_id, (
                f"session_id mismatch: expected {chat_session_id}, got {loaded.session_id}"
            )
            assert loaded.message_range_start == range_start, (
                f"message_range_start mismatch: expected {range_start}, got {loaded.message_range_start}"
            )
            assert loaded.message_range_end == range_end, (
                f"message_range_end mismatch: expected {range_end}, got {loaded.message_range_end}"
            )
            assert loaded.created_at is not None, "created_at should not be None"

        engine.dispose()
