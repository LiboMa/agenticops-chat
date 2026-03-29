"""Unit tests for MemoryService — extract_facts, get_facts, upsert logic,
and experience memory (extract_experiences, search_experiences, build_memory_context).
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agenticops.models import AgentMemory, AgentMemoryFact, Base, ChatSession
from agenticops.web.memory_service import MemoryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def service():
    """Return a MemoryService with a mocked Bedrock client."""
    svc = MemoryService.__new__(MemoryService)
    svc.region = "us-east-1"
    svc.model_id = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    svc._client = MagicMock()
    return svc


def _mock_bedrock_response(mock_client, text: str):
    body_bytes = json.dumps({"content": [{"text": text}]}).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_bytes
    mock_client.invoke_model.return_value = {"body": mock_body}


# ---------------------------------------------------------------------------
# _format_messages
# ---------------------------------------------------------------------------

class TestFormatMessages:
    def test_simple_text_messages(self, service):
        msgs = [
            {"role": "user", "content": "I prefer us-west-2"},
            {"role": "assistant", "content": "Noted, us-west-2."},
        ]
        result = service._format_messages(msgs)
        assert "user: I prefer us-west-2" in result
        assert "assistant: Noted, us-west-2." in result

    def test_strands_content_blocks(self, service):
        msgs = [
            {"role": "assistant", "content": [
                {"text": "Checking..."},
                {"toolUse": {"name": "describe_instances", "input": {}}},
            ]},
        ]
        result = service._format_messages(msgs)
        assert "Checking..." in result
        assert "[Tool: describe_instances]" in result

    def test_empty_messages(self, service):
        assert service._format_messages([]) == ""


# ---------------------------------------------------------------------------
# _parse_facts_response
# ---------------------------------------------------------------------------

class TestParseFactsResponse:
    def test_valid_json_array(self, service):
        text = json.dumps([
            {"category": "user_preference", "key": "region", "value": "us-west-2", "confidence_score": 0.9},
        ])
        result = service._parse_facts_response(text)
        assert len(result) == 1
        assert result[0]["category"] == "user_preference"
        assert result[0]["key"] == "region"
        assert result[0]["confidence_score"] == 0.9

    def test_markdown_code_fences(self, service):
        text = '```json\n[{"category": "infra_context", "key": "vpc", "value": "vpc-123", "confidence_score": 0.8}]\n```'
        result = service._parse_facts_response(text)
        assert len(result) == 1
        assert result[0]["category"] == "infra_context"

    def test_invalid_json_returns_empty(self, service):
        result = service._parse_facts_response("not json at all")
        assert result == []

    def test_invalid_category_filtered(self, service):
        text = json.dumps([
            {"category": "invalid_cat", "key": "k", "value": "v", "confidence_score": 0.9},
        ])
        result = service._parse_facts_response(text)
        assert result == []

    def test_missing_fields_filtered(self, service):
        text = json.dumps([
            {"category": "user_preference", "key": "", "value": "v"},
            {"category": "user_preference", "key": "k", "value": ""},
        ])
        result = service._parse_facts_response(text)
        assert result == []

    def test_confidence_clamped(self, service):
        text = json.dumps([
            {"category": "team_info", "key": "lead", "value": "Alice", "confidence_score": 1.5},
            {"category": "team_info", "key": "size", "value": "5", "confidence_score": -0.3},
        ])
        result = service._parse_facts_response(text)
        assert result[0]["confidence_score"] == 1.0
        assert result[1]["confidence_score"] == 0.0

    def test_key_truncated_to_200(self, service):
        long_key = "k" * 300
        text = json.dumps([
            {"category": "user_preference", "key": long_key, "value": "v", "confidence_score": 0.8},
        ])
        result = service._parse_facts_response(text)
        assert len(result[0]["key"]) == 200

    def test_json_embedded_in_text(self, service):
        text = 'Here are the facts:\n[{"category": "user_preference", "key": "region", "value": "eu-west-1", "confidence_score": 0.85}]\nDone.'
        result = service._parse_facts_response(text)
        assert len(result) == 1
        assert result[0]["value"] == "eu-west-1"


# ---------------------------------------------------------------------------
# extract_facts
# ---------------------------------------------------------------------------

class TestExtractFacts:
    @patch("agenticops.web.memory_service.get_db_session")
    def test_extracts_and_upserts_facts(self, mock_get_db, service):
        facts_json = json.dumps([
            {"category": "user_preference", "key": "region", "value": "us-west-2", "confidence_score": 0.9},
        ])
        _mock_bedrock_response(service._client, facts_json)

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None  # No existing fact
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        messages = [{"role": "user", "content": "I prefer us-west-2"}]
        result = service.extract_facts("sess-uuid-1", messages)

        service._client.invoke_model.assert_called_once()
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, AgentMemoryFact)
        assert added.category == "user_preference"
        assert added.key == "region"
        assert added.value == "us-west-2"

    def test_returns_empty_for_empty_messages(self, service):
        result = service.extract_facts("sess-uuid-1", [])
        assert result == []
        service._client.invoke_model.assert_not_called()

    @patch("agenticops.web.memory_service.get_db_session")
    def test_returns_empty_on_bedrock_error(self, mock_get_db, service):
        from botocore.exceptions import ClientError

        service._client.invoke_model.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "InvokeModel",
        )
        messages = [{"role": "user", "content": "test"}]
        result = service.extract_facts("sess-uuid-1", messages)
        assert result == []

    @patch("agenticops.web.memory_service.get_db_session")
    def test_upsert_updates_existing_fact(self, mock_get_db, service):
        facts_json = json.dumps([
            {"category": "user_preference", "key": "region", "value": "eu-west-1", "confidence_score": 0.95},
        ])
        _mock_bedrock_response(service._client, facts_json)

        existing_fact = AgentMemoryFact(
            id=1,
            category="user_preference",
            key="region",
            value="us-west-2",
            confidence_score=0.9,
            source_session_id="old-sess",
        )

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = existing_fact
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        messages = [{"role": "user", "content": "Switch to eu-west-1"}]
        result = service.extract_facts("sess-uuid-2", messages)

        # Should NOT add a new record — should update existing
        mock_db.add.assert_not_called()
        assert existing_fact.value == "eu-west-1"
        assert existing_fact.confidence_score == 0.95
        assert existing_fact.source_session_id == "sess-uuid-2"


# ---------------------------------------------------------------------------
# get_facts
# ---------------------------------------------------------------------------

class TestGetFacts:
    @patch("agenticops.web.memory_service.get_db_session")
    def test_returns_high_confidence_facts(self, mock_get_db, service):
        f1 = AgentMemoryFact(
            id=1, category="user_preference", key="region",
            value="us-west-2", confidence_score=0.9,
            source_session_id="s1",
        )
        f2 = AgentMemoryFact(
            id=2, category="infra_context", key="vpc",
            value="vpc-abc", confidence_score=0.8,
            source_session_id="s1",
        )

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order = MagicMock()
        mock_order2 = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.order_by.return_value = mock_order
        mock_order.all.return_value = [f2, f1]  # ordered by category, key

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = service.get_facts(min_confidence=0.7)
        assert len(result) == 2

    @patch("agenticops.web.memory_service.get_db_session")
    def test_returns_empty_on_db_error(self, mock_get_db, service):
        mock_get_db.return_value.__enter__ = MagicMock(side_effect=Exception("DB down"))

        result = service.get_facts()
        assert result == []

    @patch("agenticops.web.memory_service.get_db_session")
    def test_custom_min_confidence(self, mock_get_db, service):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.order_by.return_value = mock_order
        mock_order.all.return_value = []

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        service.get_facts(min_confidence=0.5)
        # Verify filter was called (the actual filter expression is checked by the query)
        mock_query.filter.assert_called_once()


# ---------------------------------------------------------------------------
# _parse_experiences_response
# ---------------------------------------------------------------------------

class TestParseExperiencesResponse:
    def test_valid_json_array(self, service):
        text = json.dumps([
            {"memory_type": "problem", "content_text": "EC2 instance unreachable"},
            {"memory_type": "root_cause", "content_text": "Security group blocked port 443"},
            {"memory_type": "solution", "content_text": "Added inbound rule for port 443"},
        ])
        result = service._parse_experiences_response(text)
        assert len(result) == 3
        assert result[0]["memory_type"] == "problem"
        assert result[1]["memory_type"] == "root_cause"
        assert result[2]["memory_type"] == "solution"

    def test_markdown_code_fences(self, service):
        text = '```json\n[{"memory_type": "problem", "content_text": "High CPU usage"}]\n```'
        result = service._parse_experiences_response(text)
        assert len(result) == 1
        assert result[0]["content_text"] == "High CPU usage"

    def test_invalid_json_returns_empty(self, service):
        result = service._parse_experiences_response("not json")
        assert result == []

    def test_invalid_memory_type_filtered(self, service):
        text = json.dumps([
            {"memory_type": "invalid_type", "content_text": "something"},
        ])
        result = service._parse_experiences_response(text)
        assert result == []

    def test_missing_fields_filtered(self, service):
        text = json.dumps([
            {"memory_type": "problem", "content_text": ""},
            {"memory_type": "", "content_text": "something"},
        ])
        result = service._parse_experiences_response(text)
        assert result == []

    def test_json_embedded_in_text(self, service):
        text = 'Here are experiences:\n[{"memory_type": "solution", "content_text": "Restart the service"}]\nDone.'
        result = service._parse_experiences_response(text)
        assert len(result) == 1
        assert result[0]["content_text"] == "Restart the service"


# ---------------------------------------------------------------------------
# extract_experiences
# ---------------------------------------------------------------------------

class TestExtractExperiences:
    @patch("agenticops.web.memory_service.get_db_session")
    def test_extracts_and_stores_experiences(self, mock_get_db, service):
        exp_json = json.dumps([
            {"memory_type": "problem", "content_text": "RDS connection timeout"},
        ])
        # First call: LLM extraction; second call: embedding generation
        call_count = [0]
        def mock_invoke(modelId, body, **kwargs):
            call_count[0] += 1
            if "anthropic_version" in body:
                # LLM call
                body_bytes = json.dumps({"content": [{"text": exp_json}]}).encode()
            else:
                # Embedding call
                embedding = [0.1] * 256
                body_bytes = json.dumps({"embedding": embedding}).encode()
            mock_body = MagicMock()
            mock_body.read.return_value = body_bytes
            return {"body": mock_body}

        service._client.invoke_model.side_effect = mock_invoke

        mock_db = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        messages = [{"role": "user", "content": "RDS connection is timing out"}]
        result = service.extract_experiences("sess-uuid-1", messages)

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, AgentMemory)
        assert added.memory_type == "problem"
        assert added.content_text == "RDS connection timeout"
        assert added.session_id == "sess-uuid-1"

    def test_returns_empty_for_empty_messages(self, service):
        result = service.extract_experiences("sess-uuid-1", [])
        assert result == []

    def test_returns_empty_on_bedrock_error(self, service):
        from botocore.exceptions import ClientError
        service._client.invoke_model.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "InvokeModel",
        )
        messages = [{"role": "user", "content": "test"}]
        result = service.extract_experiences("sess-uuid-1", messages)
        assert result == []


# ---------------------------------------------------------------------------
# _generate_embedding
# ---------------------------------------------------------------------------

class TestGenerateEmbedding:
    def test_returns_numpy_array(self, service):
        embedding = [0.1, 0.2, 0.3]
        body_bytes = json.dumps({"embedding": embedding}).encode()
        mock_body = MagicMock()
        mock_body.read.return_value = body_bytes
        service._client.invoke_model.return_value = {"body": mock_body}

        result = service._generate_embedding("test text")
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        np.testing.assert_allclose(result, [0.1, 0.2, 0.3], atol=1e-6)

    def test_returns_none_on_error(self, service):
        service._client.invoke_model.side_effect = Exception("API error")
        result = service._generate_embedding("test text")
        assert result is None

    def test_returns_none_when_no_embedding_key(self, service):
        body_bytes = json.dumps({"other": "data"}).encode()
        mock_body = MagicMock()
        mock_body.read.return_value = body_bytes
        service._client.invoke_model.return_value = {"body": mock_body}

        result = service._generate_embedding("test text")
        assert result is None


# ---------------------------------------------------------------------------
# search_experiences
# ---------------------------------------------------------------------------

class TestSearchExperiences:
    def _make_memory(self, memory_type, content, embedding_vec, session_id="s1"):
        """Helper to create an AgentMemory with a serialized embedding."""
        m = AgentMemory(
            id=1,
            session_id=session_id,
            memory_type=memory_type,
            content_text=content,
            embedding_vector=np.array(embedding_vec, dtype=np.float32).tobytes(),
            created_at=datetime(2025, 1, 1),
        )
        return m

    @patch("agenticops.web.memory_service.get_db_session")
    def test_returns_similar_experiences(self, mock_get_db, service):
        # Query embedding: [1, 0, 0]
        query_emb = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        body_bytes = json.dumps({"embedding": [1.0, 0.0, 0.0]}).encode()
        mock_body = MagicMock()
        mock_body.read.return_value = body_bytes
        service._client.invoke_model.return_value = {"body": mock_body}

        # Stored memories: one similar, one orthogonal
        m1 = self._make_memory("problem", "similar issue", [0.9, 0.1, 0.0])
        m2 = self._make_memory("solution", "unrelated", [0.0, 0.0, 1.0])

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all.return_value = [m1, m2]
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = service.search_experiences("similar query", top_k=3, min_score=0.6)
        assert len(result) == 1
        assert result[0].content_text == "similar issue"

    @patch("agenticops.web.memory_service.get_db_session")
    def test_respects_min_score(self, mock_get_db, service):
        body_bytes = json.dumps({"embedding": [1.0, 0.0, 0.0]}).encode()
        mock_body = MagicMock()
        mock_body.read.return_value = body_bytes
        service._client.invoke_model.return_value = {"body": mock_body}

        # All memories have low similarity
        m1 = self._make_memory("problem", "low sim", [0.0, 1.0, 0.0])

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all.return_value = [m1]
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = service.search_experiences("query", min_score=0.9)
        assert result == []

    @patch("agenticops.web.memory_service.get_db_session")
    def test_respects_top_k(self, mock_get_db, service):
        body_bytes = json.dumps({"embedding": [1.0, 0.0, 0.0]}).encode()
        mock_body = MagicMock()
        mock_body.read.return_value = body_bytes
        service._client.invoke_model.return_value = {"body": mock_body}

        # 3 similar memories, but top_k=1
        memories = [
            self._make_memory("problem", f"issue {i}", [0.9, 0.1, 0.0])
            for i in range(3)
        ]

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all.return_value = memories
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = service.search_experiences("query", top_k=1, min_score=0.0)
        assert len(result) == 1

    def test_returns_empty_for_empty_query(self, service):
        result = service.search_experiences("")
        assert result == []

    def test_returns_empty_on_embedding_error(self, service):
        service._client.invoke_model.side_effect = Exception("API error")
        result = service.search_experiences("query text")
        assert result == []


# ---------------------------------------------------------------------------
# build_memory_context
# ---------------------------------------------------------------------------

class TestBuildMemoryContext:
    @patch.object(MemoryService, "search_experiences")
    @patch.object(MemoryService, "get_facts")
    def test_combines_facts_and_experiences(self, mock_get_facts, mock_search, service):
        mock_get_facts.return_value = [
            AgentMemoryFact(
                id=1, category="user_preference", key="region",
                value="us-west-2", confidence_score=0.9,
                source_session_id="s1",
            ),
        ]
        mock_search.return_value = [
            AgentMemory(
                id=1, session_id="s-abc", memory_type="problem",
                content_text="EC2 unreachable",
                created_at=datetime(2025, 6, 15, 10, 30, 0),
            ),
        ]

        result = service.build_memory_context("current-sess", initial_context="EC2 issue")

        assert "[Cross-session memory - Known facts]" in result
        assert "user_preference/region: us-west-2" in result
        assert "[Cross-session memory - Related experiences]" in result
        assert "[problem] EC2 unreachable" in result
        assert "session s-abc" in result
        assert "2025-06-15 10:30:00" in result

    @patch.object(MemoryService, "search_experiences")
    @patch.object(MemoryService, "get_facts")
    def test_facts_only_when_no_initial_context(self, mock_get_facts, mock_search, service):
        mock_get_facts.return_value = [
            AgentMemoryFact(
                id=1, category="infra_context", key="vpc",
                value="vpc-123", confidence_score=0.85,
                source_session_id="s1",
            ),
        ]

        result = service.build_memory_context("current-sess", initial_context="")

        assert "[Cross-session memory - Known facts]" in result
        assert "Related experiences" not in result
        mock_search.assert_not_called()

    @patch.object(MemoryService, "search_experiences")
    @patch.object(MemoryService, "get_facts")
    def test_empty_when_no_memories(self, mock_get_facts, mock_search, service):
        mock_get_facts.return_value = []
        mock_search.return_value = []

        result = service.build_memory_context("current-sess", initial_context="query")
        assert result == ""

    @patch.object(MemoryService, "search_experiences")
    @patch.object(MemoryService, "get_facts")
    def test_graceful_on_facts_error(self, mock_get_facts, mock_search, service):
        mock_get_facts.side_effect = Exception("DB error")
        mock_search.return_value = [
            AgentMemory(
                id=1, session_id="s-abc", memory_type="solution",
                content_text="Restart service",
                created_at=datetime(2025, 1, 1),
            ),
        ]

        result = service.build_memory_context("current-sess", initial_context="issue")
        # Should still include experiences even if facts fail
        assert "Restart service" in result

    @patch.object(MemoryService, "search_experiences")
    @patch.object(MemoryService, "get_facts")
    def test_graceful_on_search_error(self, mock_get_facts, mock_search, service):
        mock_get_facts.return_value = [
            AgentMemoryFact(
                id=1, category="team_info", key="lead",
                value="Alice", confidence_score=0.9,
                source_session_id="s1",
            ),
        ]
        mock_search.side_effect = Exception("Vector search error")

        result = service.build_memory_context("current-sess", initial_context="query")
        # Should still include facts even if search fails
        assert "team_info/lead: Alice" in result
