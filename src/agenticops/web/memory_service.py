"""Cross-session memory service for structured fact extraction and retrieval.

Uses a lightweight LLM (Haiku) to extract structured facts from conversation
history and stores them in the agent_memory_facts table with upsert semantics.
Also manages vectorized experience memories using Titan V2 embeddings.
"""

import json
import logging
from typing import Optional

import boto3
import numpy as np
from botocore.exceptions import ClientError

from agenticops.config import settings
from agenticops.models import AgentMemory, AgentMemoryFact, get_db_session

logger = logging.getLogger(__name__)


class MemoryService:
    """Cross-session memory service managing structured facts and vectorized experiences."""

    VALID_CATEGORIES = ("user_preference", "infra_context", "team_info")
    VALID_MEMORY_TYPES = ("problem", "root_cause", "solution")
    EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

    EXPERIENCE_EXTRACTION_PROMPT = (
        "You are an experience extractor for an operations support system. "
        "Analyze the following conversation and extract key experiences.\n\n"
        "For each experience, identify:\n"
        '- "memory_type": one of "problem" (problem description), '
        '"root_cause" (root cause analysis), "solution" (resolution steps)\n'
        '- "content_text": a concise description of the experience\n\n'
        "Return a JSON array of experiences. Each must have memory_type and content_text.\n"
        "Only extract experiences that are clearly described. "
        "Return an empty array [] if no experiences can be extracted.\n\n"
        "Conversation:\n{conversation}\n\n"
        "JSON array of experiences:"
    )

    FACT_EXTRACTION_PROMPT = (
        "You are a structured fact extractor. Analyze the following conversation "
        "and extract key facts about the user's preferences, infrastructure context, "
        "and team information.\n\n"
        "Return a JSON array of facts. Each fact must have:\n"
        '- "category": one of "user_preference", "infra_context", "team_info"\n'
        '- "key": a short descriptive key (e.g., "preferred_region", "naming_convention")\n'
        '- "value": the fact value\n'
        '- "confidence_score": float between 0.0 and 1.0 indicating confidence\n\n'
        "Only extract facts that are clearly stated or strongly implied. "
        "Return an empty array [] if no facts can be extracted.\n\n"
        "Conversation:\n{conversation}\n\n"
        "JSON array of facts:"
    )

    def __init__(self, region: str | None = None, model_id: str | None = None):
        self.region = region or settings.bedrock_region
        self.model_id = model_id or settings.bedrock_model_id_cheap
        self._client = None

    @property
    def client(self):
        """Lazy-init Bedrock runtime client."""
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
            )
        return self._client

    def _format_messages(self, messages: list[dict]) -> str:
        """Format Strands-format messages into a readable conversation string."""
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if "text" in block:
                            text_parts.append(block["text"])
                        elif "toolUse" in block:
                            tool = block["toolUse"]
                            text_parts.append(f"[Tool: {tool.get('name', '?')}]")
                        elif "toolResult" in block:
                            text_parts.append("[Tool Result]")
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = " ".join(text_parts)
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _parse_facts_response(self, response_text: str) -> list[dict]:
        """Parse LLM response into a list of fact dicts.

        Handles cases where the response contains markdown code fences or
        extra text around the JSON array.
        """
        text = response_text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            facts = json.loads(text)
        except json.JSONDecodeError:
            # Try to find a JSON array in the text
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    facts = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    logger.warning("Failed to parse facts JSON from LLM response")
                    return []
            else:
                logger.warning("No JSON array found in LLM response")
                return []

        if not isinstance(facts, list):
            return []

        # Validate and normalize each fact
        valid_facts = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            category = fact.get("category", "")
            key = fact.get("key", "")
            value = fact.get("value", "")
            confidence = fact.get("confidence_score", 0.8)

            if not category or not key or not value:
                continue
            if category not in self.VALID_CATEGORIES:
                continue

            try:
                confidence = float(confidence)
                confidence = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = 0.8

            valid_facts.append({
                "category": category,
                "key": str(key)[:200],
                "value": str(value),
                "confidence_score": confidence,
            })
        return valid_facts

    def extract_facts(
        self, session_id: str, messages: list[dict]
    ) -> list[AgentMemoryFact]:
        """Extract structured facts from conversation history using LLM.

        Args:
            session_id: The ChatSession.session_id (UUID string).
            messages: List of Strands-format message dicts.

        Returns:
            List of AgentMemoryFact objects that were upserted into the DB.
            Returns empty list on failure.
        """
        if not messages:
            return []

        try:
            conversation_text = self._format_messages(messages)
            prompt = self.FACT_EXTRACTION_PROMPT.format(conversation=conversation_text)

            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            })

            response = self.client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            response_text = response_body["content"][0]["text"]

            parsed_facts = self._parse_facts_response(response_text)
            if not parsed_facts:
                return []

            return self._upsert_facts(session_id, parsed_facts)

        except (ClientError, KeyError, IndexError, Exception) as exc:
            logger.error(
                "Failed to extract facts for session %s: %s", session_id, exc
            )
            return []

    def _upsert_facts(
        self, session_id: str, parsed_facts: list[dict]
    ) -> list[AgentMemoryFact]:
        """Upsert facts into the database.

        For each (category, key) pair:
        - If exists: update value and confidence_score
        - If not: insert new record

        Args:
            session_id: The ChatSession.session_id (UUID string).
            parsed_facts: List of validated fact dicts.

        Returns:
            List of AgentMemoryFact objects that were upserted.
        """
        results: list[AgentMemoryFact] = []
        try:
            with get_db_session() as db:
                for fact_data in parsed_facts:
                    existing = (
                        db.query(AgentMemoryFact)
                        .filter(
                            AgentMemoryFact.category == fact_data["category"],
                            AgentMemoryFact.key == fact_data["key"],
                        )
                        .first()
                    )

                    if existing:
                        existing.value = fact_data["value"]
                        existing.confidence_score = fact_data["confidence_score"]
                        existing.source_session_id = session_id
                        results.append(existing)
                    else:
                        new_fact = AgentMemoryFact(
                            category=fact_data["category"],
                            key=fact_data["key"],
                            value=fact_data["value"],
                            confidence_score=fact_data["confidence_score"],
                            source_session_id=session_id,
                        )
                        db.add(new_fact)
                        results.append(new_fact)

                # Flush to get IDs assigned before expunge
                db.flush()
                db.expunge_all()

            return results

        except Exception as exc:
            logger.error("Failed to upsert facts: %s", exc)
            return []

    def get_facts(
        self, min_confidence: float = 0.7
    ) -> list[AgentMemoryFact]:
        """Retrieve high-confidence facts from the database.

        Args:
            min_confidence: Minimum confidence_score threshold (default 0.7).

        Returns:
            List of AgentMemoryFact objects with confidence >= min_confidence.
        """
        try:
            with get_db_session() as db:
                facts = (
                    db.query(AgentMemoryFact)
                    .filter(AgentMemoryFact.confidence_score >= min_confidence)
                    .order_by(
                        AgentMemoryFact.category.asc(),
                        AgentMemoryFact.key.asc(),
                    )
                    .all()
                )
                db.expunge_all()
                return facts
        except Exception as exc:
            logger.error("Failed to retrieve facts: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Experience memory (vectorized)
    # ------------------------------------------------------------------

    def _generate_embedding(self, text: str) -> Optional[np.ndarray]:
        """Generate an embedding vector for the given text using Titan V2.

        Args:
            text: The text to embed.

        Returns:
            numpy array of the embedding, or None on failure.
        """
        try:
            body = json.dumps({"inputText": text})
            response = self.client.invoke_model(
                modelId=self.EMBEDDING_MODEL_ID,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            response_body = json.loads(response["body"].read())
            embedding = response_body.get("embedding")
            if embedding is None:
                logger.warning("No embedding returned from Titan V2")
                return None
            return np.array(embedding, dtype=np.float32)
        except Exception as exc:
            logger.error("Failed to generate embedding: %s", exc)
            return None

    def _parse_experiences_response(self, response_text: str) -> list[dict]:
        """Parse LLM response into a list of experience dicts.

        Handles markdown code fences and extra text around the JSON array.
        """
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            experiences = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    experiences = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    logger.warning("Failed to parse experiences JSON from LLM response")
                    return []
            else:
                logger.warning("No JSON array found in LLM experience response")
                return []

        if not isinstance(experiences, list):
            return []

        valid = []
        for exp in experiences:
            if not isinstance(exp, dict):
                continue
            memory_type = exp.get("memory_type", "")
            content_text = exp.get("content_text", "")
            if not memory_type or not content_text:
                continue
            if memory_type not in self.VALID_MEMORY_TYPES:
                continue
            valid.append({
                "memory_type": memory_type,
                "content_text": str(content_text),
            })
        return valid

    def extract_experiences(
        self, session_id: str, messages: list[dict]
    ) -> list[AgentMemory]:
        """Extract experience fragments from conversation and generate embeddings.

        Uses Haiku LLM to identify problem descriptions, root causes, and
        solutions, then generates Titan V2 embeddings for each and stores
        them in the agent_memories table.

        Args:
            session_id: The ChatSession.session_id (UUID string).
            messages: List of Strands-format message dicts.

        Returns:
            List of AgentMemory objects stored in the DB.
            Returns empty list on failure.
        """
        if not messages:
            return []

        try:
            conversation_text = self._format_messages(messages)
            prompt = self.EXPERIENCE_EXTRACTION_PROMPT.format(
                conversation=conversation_text
            )

            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            })

            response = self.client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            response_text = response_body["content"][0]["text"]

            parsed = self._parse_experiences_response(response_text)
            if not parsed:
                return []

            return self._store_experiences(session_id, parsed)

        except Exception as exc:
            logger.error(
                "Failed to extract experiences for session %s: %s",
                session_id,
                exc,
            )
            return []

    def _store_experiences(
        self, session_id: str, parsed_experiences: list[dict]
    ) -> list[AgentMemory]:
        """Store extracted experiences with embeddings in the database.

        Args:
            session_id: The ChatSession.session_id (UUID string).
            parsed_experiences: List of validated experience dicts.

        Returns:
            List of AgentMemory objects that were stored.
        """
        results: list[AgentMemory] = []
        try:
            with get_db_session() as db:
                for exp in parsed_experiences:
                    embedding = self._generate_embedding(exp["content_text"])
                    embedding_bytes = (
                        embedding.tobytes() if embedding is not None else None
                    )

                    memory = AgentMemory(
                        session_id=session_id,
                        memory_type=exp["memory_type"],
                        content_text=exp["content_text"],
                        embedding_vector=embedding_bytes,
                    )
                    db.add(memory)
                    results.append(memory)

                db.flush()
                db.expunge_all()

            return results

        except Exception as exc:
            logger.error("Failed to store experiences: %s", exc)
            return []

    def search_experiences(
        self,
        query_text: str,
        top_k: int = 3,
        min_score: float = 0.6,
    ) -> list[AgentMemory]:
        """Search historical experiences by vector similarity.

        Generates an embedding for the query text, loads all stored
        embeddings from the DB, computes cosine similarity, and returns
        the top_k results above min_score.

        Args:
            query_text: The text to search for similar experiences.
            top_k: Maximum number of results to return (default 3).
            min_score: Minimum cosine similarity threshold (default 0.6).

        Returns:
            List of AgentMemory objects sorted by similarity (descending).
            Returns empty list on failure.
        """
        if not query_text:
            return []

        try:
            query_embedding = self._generate_embedding(query_text)
            if query_embedding is None:
                return []

            with get_db_session() as db:
                all_memories = (
                    db.query(AgentMemory)
                    .filter(AgentMemory.embedding_vector.isnot(None))
                    .all()
                )
                db.expunge_all()

            if not all_memories:
                return []

            # Compute cosine similarity for each memory
            scored: list[tuple[float, AgentMemory]] = []
            query_norm = np.linalg.norm(query_embedding)
            if query_norm == 0:
                return []

            for memory in all_memories:
                try:
                    stored_vec = np.frombuffer(
                        memory.embedding_vector, dtype=np.float32
                    )
                    if stored_vec.shape != query_embedding.shape:
                        continue
                    stored_norm = np.linalg.norm(stored_vec)
                    if stored_norm == 0:
                        continue
                    similarity = float(
                        np.dot(query_embedding, stored_vec)
                        / (query_norm * stored_norm)
                    )
                    if similarity >= min_score:
                        scored.append((similarity, memory))
                except Exception:
                    continue

            # Sort by similarity descending, take top_k
            scored.sort(key=lambda x: x[0], reverse=True)
            return [memory for _, memory in scored[:top_k]]

        except Exception as exc:
            logger.error("Failed to search experiences: %s", exc)
            return []

    def build_memory_context(
        self, session_id: str, initial_context: str = ""
    ) -> str:
        """Build a memory context string for system prompt injection.

        Combines structured facts and relevant experiences into a formatted
        string. Uses initial_context as the query for experience search.

        Args:
            session_id: The current ChatSession.session_id (UUID string).
            initial_context: Optional context text (e.g., HealthIssue description)
                used as the query for experience similarity search.

        Returns:
            Formatted memory context string, or empty string if no memories.
        """
        sections: list[str] = []

        # 1. Structured facts
        try:
            facts = self.get_facts(min_confidence=0.7)
            if facts:
                lines = ["[Cross-session memory - Known facts]"]
                for fact in facts:
                    lines.append(
                        f"- {fact.category}/{fact.key}: {fact.value} "
                        f"(confidence: {fact.confidence_score:.2f})"
                    )
                sections.append("\n".join(lines))
        except Exception:
            logger.warning("Failed to load facts for memory context", exc_info=True)

        # 2. Vectorized experiences (search using initial_context)
        try:
            if initial_context:
                experiences = self.search_experiences(
                    query_text=initial_context, top_k=3, min_score=0.6
                )
                if experiences:
                    lines = ["[Cross-session memory - Related experiences]"]
                    for exp in experiences:
                        created_str = (
                            exp.created_at.strftime("%Y-%m-%d %H:%M:%S")
                            if exp.created_at
                            else "unknown"
                        )
                        lines.append(
                            f"- [{exp.memory_type}] {exp.content_text} "
                            f"(source: session {exp.session_id}, "
                            f"at: {created_str})"
                        )
                    sections.append("\n".join(lines))
        except Exception:
            logger.warning(
                "Failed to load experiences for memory context", exc_info=True
            )

        return "\n\n".join(sections)
