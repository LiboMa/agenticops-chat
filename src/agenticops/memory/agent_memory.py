"""Per-agent persistent memory with episodic + semantic storage.

Uses SQLite directly (not SQLAlchemy) to avoid session conflicts with the
main application. Reuses existing KB embedding infrastructure.
"""

import json
import logging
import math
import sqlite3
import struct
from datetime import datetime
from pathlib import Path
from typing import Optional

from agenticops.memory.types import MemoryEntry, MemoryType, decayed_confidence

logger = logging.getLogger(__name__)


class AgentMemory:
    """Per-agent persistent memory with episodic + semantic storage."""

    MAX_MEMORIES_PER_AGENT = 1000   # Hard limit, oldest pruned
    CONSOLIDATION_THRESHOLD = 50     # Trigger consolidation after N new entries/day

    def __init__(self, agent_name: str, db_path: str | Path = ""):
        self.agent_name = agent_name
        self._db_path = str(db_path) if db_path else self._default_db_path()
        self._memory_md_path = Path(f"data/memory/{agent_name}_MEMORY.md")
        self._embedding_client = None  # Lazy init
        self._ensure_table()

    def _default_db_path(self) -> str:
        """Get default DB path from settings."""
        try:
            from agenticops.config import settings
            url = settings.database_url
            if url.startswith("sqlite:///"):
                return url.replace("sqlite:///", "")
        except Exception:
            pass
        return "data/agenticops.db"

    def _get_embedding_client(self):
        """Lazy-init embedding client."""
        if self._embedding_client is None:
            try:
                from agenticops.kb.embeddings import get_embedding_client
                self._embedding_client = get_embedding_client()
            except Exception:
                logger.warning("Embedding client unavailable, using null embeddings")
                self._embedding_client = _NullEmbeddingClient()
        return self._embedding_client

    def _get_conn(self) -> sqlite3.Connection:
        """Get a SQLite connection."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create agent_memories table if not exists."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    context_json TEXT DEFAULT '{}',
                    source TEXT DEFAULT '',
                    confidence REAL DEFAULT 1.0,
                    recall_count INTEGER DEFAULT 0,
                    vector BLOB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_am_agent ON agent_memories(agent_name);
                CREATE INDEX IF NOT EXISTS idx_am_type ON agent_memories(agent_name, memory_type);
                CREATE INDEX IF NOT EXISTS idx_am_created ON agent_memories(created_at DESC);
            """)
            conn.commit()
        finally:
            conn.close()

    # ── Write ──────────────────────────────────────────────────

    async def remember(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.EPISODIC,
        context: dict | None = None,
        source: str = "",
        confidence: float = 1.0,
    ) -> MemoryEntry:
        """Store a new memory entry.

        1. Create MemoryEntry
        2. Embed content → vector
        3. Insert into SQLite
        4. Append to MEMORY.md
        5. Check if consolidation needed
        """
        entry = MemoryEntry(
            agent_name=self.agent_name,
            memory_type=memory_type,
            content=content,
            context=context or {},
            source=source,
            confidence=max(0.0, min(1.0, confidence)),
        )

        # Embed
        vector = await self._embed(content)

        # Insert to SQLite
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT INTO agent_memories
                   (agent_name, memory_type, content, context_json, source, confidence, vector, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.agent_name,
                    memory_type.value,
                    content,
                    json.dumps(entry.context),
                    source,
                    entry.confidence,
                    _encode_vector(vector) if vector else None,
                    entry.timestamp.isoformat(),
                ),
            )
            conn.commit()
            entry.id = cursor.lastrowid
        finally:
            conn.close()

        # Append to MEMORY.md
        self._append_to_md(entry)

        logger.info(
            "Memory stored: agent=%s type=%s id=%d",
            self.agent_name, memory_type.value, entry.id,
        )
        return entry

    # ── Read ───────────────────────────────────────────────────

    async def recall(
        self,
        query: str,
        memory_type: MemoryType | None = None,
        top_k: int = 5,
        min_confidence: float = 0.3,
    ) -> list[MemoryEntry]:
        """Semantic search across agent's memories."""
        query_vector = await self._embed(query)

        conn = self._get_conn()
        try:
            # Build query
            sql = "SELECT * FROM agent_memories WHERE agent_name = ?"
            params: list = [self.agent_name]

            if memory_type is not None:
                sql += " AND memory_type = ?"
                params.append(memory_type.value)

            sql += " AND confidence >= ?"
            params.append(min_confidence)

            rows = conn.execute(sql, params).fetchall()

            # Score by semantic similarity + confidence
            scored = []
            now = datetime.utcnow()
            for row in rows:
                entry = self._row_to_entry(row)
                if query_vector and row["vector"]:
                    stored_vector = _decode_vector(row["vector"])
                    sim = _cosine_similarity(query_vector, stored_vector)
                else:
                    # Fallback: recency-based scoring
                    age_hours = max(1, (now - entry.timestamp).total_seconds() / 3600)
                    sim = 1.0 / math.log2(age_hours + 1)

                score = sim * decayed_confidence(entry, now)
                scored.append((score, entry))

            # Sort by score descending
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [entry for _, entry in scored[:top_k]]

            # Increment recall_count
            if results:
                ids = [e.id for e in results if e.id is not None]
                if ids:
                    placeholders = ",".join("?" * len(ids))
                    conn.execute(
                        f"UPDATE agent_memories SET recall_count = recall_count + 1, "
                        f"updated_at = ? WHERE id IN ({placeholders})",
                        [datetime.utcnow().isoformat()] + ids,
                    )
                    conn.commit()
                    for entry in results:
                        entry.recall_count += 1

            return results
        finally:
            conn.close()

    async def recall_recent(
        self,
        limit: int = 10,
        memory_type: MemoryType | None = None,
    ) -> list[MemoryEntry]:
        """Retrieve most recent memories (chronological)."""
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM agent_memories WHERE agent_name = ?"
            params: list = [self.agent_name]

            if memory_type is not None:
                sql += " AND memory_type = ?"
                params.append(memory_type.value)

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_entry(row) for row in rows]
        finally:
            conn.close()

    # ── Reflect ────────────────────────────────────────────────

    async def reflect(self) -> str:
        """End-of-day consolidation and summary.

        1. Gather today's memories
        2. Generate summary (patterns, lessons)
        3. Store as REFLECTION type
        4. Prune low-value entries
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM agent_memories
                   WHERE agent_name = ? AND date(created_at) = ?
                   AND memory_type != 'reflection'
                   ORDER BY created_at""",
                (self.agent_name, today),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return "No memories to reflect on today."

        entries = [self._row_to_entry(row) for row in rows]

        # Generate summary
        summary_parts = [f"Today ({today}) I processed {len(entries)} memories:"]
        by_type: dict[str, list[str]] = {}
        for e in entries:
            by_type.setdefault(e.memory_type.value, []).append(e.content[:100])

        for mtype, contents in by_type.items():
            summary_parts.append(f"- {mtype}: {len(contents)} entries")
            for c in contents[:3]:
                summary_parts.append(f"  • {c}")

        summary = "\n".join(summary_parts)

        # Store reflection
        await self.remember(
            content=summary,
            memory_type=MemoryType.REFLECTION,
            source="daily_reflect",
            confidence=1.0,
        )

        # Prune
        pruned = await self.prune()
        if pruned > 0:
            summary += f"\n\nPruned {pruned} low-value memories."

        return summary

    # ── Maintenance ────────────────────────────────────────────

    async def prune(self, keep: int | None = None) -> int:
        """Remove oldest/lowest-confidence memories beyond limit.

        Strategy:
        1. Never prune REFLECTION entries
        2. Score = confidence * (1 + log(recall_count + 1)) * recency_factor
        3. Keep top `keep` by score
        4. Delete the rest
        """
        max_keep = keep or self.MAX_MEMORIES_PER_AGENT
        conn = self._get_conn()
        try:
            # Get all non-reflection entries
            rows = conn.execute(
                """SELECT * FROM agent_memories
                   WHERE agent_name = ? AND memory_type != 'reflection'""",
                (self.agent_name,),
            ).fetchall()

            if len(rows) <= max_keep:
                return 0

            # Score entries
            now = datetime.utcnow()
            scored = []
            for row in rows:
                entry = self._row_to_entry(row)
                score = decayed_confidence(entry, now) * (
                    1 + math.log(entry.recall_count + 1)
                )
                scored.append((score, row["id"]))

            # Sort by score descending, keep top N
            scored.sort(key=lambda x: x[0], reverse=True)
            to_delete = [row_id for _, row_id in scored[max_keep:]]

            if to_delete:
                placeholders = ",".join("?" * len(to_delete))
                conn.execute(
                    f"DELETE FROM agent_memories WHERE id IN ({placeholders})",
                    to_delete,
                )
                conn.commit()

            logger.info("Pruned %d memories for agent %s", len(to_delete), self.agent_name)
            return len(to_delete)
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """Get memory statistics for this agent."""
        conn = self._get_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM agent_memories WHERE agent_name = ?",
                (self.agent_name,),
            ).fetchone()[0]

            by_type = {}
            for row in conn.execute(
                "SELECT memory_type, COUNT(*) as cnt FROM agent_memories "
                "WHERE agent_name = ? GROUP BY memory_type",
                (self.agent_name,),
            ).fetchall():
                by_type[row["memory_type"]] = row["cnt"]

            return {
                "agent_name": self.agent_name,
                "total_memories": total,
                "by_type": by_type,
            }
        finally:
            conn.close()

    # ── Private helpers ────────────────────────────────────────

    async def _embed(self, text: str) -> list[float] | None:
        """Embed text using the KB embedding client."""
        try:
            client = self._get_embedding_client()
            if isinstance(client, _NullEmbeddingClient):
                return None
            # The KB embedding client may be sync or async
            if hasattr(client, "embed_text"):
                result = client.embed_text(text)
                return result if isinstance(result, list) else None
            if hasattr(client, "embed_query"):
                result = client.embed_query(text)
                return result if isinstance(result, list) else None
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
        return None

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        """Convert a SQLite row to MemoryEntry."""
        try:
            context = json.loads(row["context_json"]) if row["context_json"] else {}
        except (json.JSONDecodeError, TypeError):
            context = {}

        try:
            ts = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            ts = datetime.utcnow()

        return MemoryEntry(
            id=row["id"],
            agent_name=row["agent_name"],
            memory_type=MemoryType(row["memory_type"]),
            content=row["content"],
            context=context,
            timestamp=ts,
            source=row["source"] or "",
            confidence=row["confidence"],
            recall_count=row["recall_count"],
        )

    def _append_to_md(self, entry: MemoryEntry) -> None:
        """Append entry to the agent's MEMORY.md file."""
        self._memory_md_path.parent.mkdir(parents=True, exist_ok=True)

        date_str = entry.timestamp.strftime("%Y-%m-%d")
        time_str = entry.timestamp.strftime("%H:%M")

        line = f"- [{time_str}] {entry.content[:200]}"
        if entry.source:
            line += f" (source: {entry.source})"
        if entry.confidence < 1.0:
            line += f" [confidence: {entry.confidence:.2f}]"

        # Read existing content to check if date header exists
        existing = ""
        if self._memory_md_path.exists():
            existing = self._memory_md_path.read_text()

        with open(self._memory_md_path, "a") as f:
            if not existing:
                f.write(f"# {self.agent_name} Memory\n\n")

            if f"## {date_str}" not in existing:
                f.write(f"\n## {date_str}\n\n")

            type_header = f"### {entry.memory_type.value.capitalize()}"
            if type_header not in existing:
                f.write(f"{type_header}\n")

            f.write(f"{line}\n")


class _NullEmbeddingClient:
    """Fallback when no embedding service is available."""

    def embed_text(self, text: str) -> None:
        return None

    def embed_query(self, text: str) -> None:
        return None


# ── Vector encoding/decoding helpers ──────────────────────────


def _encode_vector(vector: list[float]) -> bytes:
    """Encode float list to compact binary (struct pack)."""
    return struct.pack(f"{len(vector)}f", *vector)


def _decode_vector(blob: bytes) -> list[float]:
    """Decode binary blob back to float list."""
    n = len(blob) // 4  # 4 bytes per float32
    return list(struct.unpack(f"{n}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
