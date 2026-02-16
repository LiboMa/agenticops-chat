"""Vector storage abstraction for KB embeddings.

SQLiteVectorStore stores vectors as BLOBs and uses numpy cosine similarity
for search. Designed for easy swap to OpenSearch via the VectorStore interface.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VectorRecord:
    case_id: str
    field_name: str  # "symptom" or "root_cause"
    vector: np.ndarray
    resource_type: str = ""
    metadata: dict | None = None


@dataclass
class SearchResult:
    case_id: str
    field_name: str
    score: float
    resource_type: str = ""
    metadata: dict | None = None


class VectorStore(ABC):
    """Abstract vector store interface (swappable to OpenSearch)."""

    @abstractmethod
    def upsert(self, record: VectorRecord) -> None:
        ...

    @abstractmethod
    def search(
        self,
        query_vector: np.ndarray,
        field_name: str = "symptom",
        resource_type: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        ...

    @abstractmethod
    def delete(self, case_id: str) -> int:
        ...

    @abstractmethod
    def count(self) -> int:
        ...


class SQLiteVectorStore(VectorStore):
    """SQLite-backed vector store with numpy cosine similarity.

    Table: case_vectors (case_id, field_name, vector BLOB, resource_type, metadata_json)
    UNIQUE(case_id, field_name)
    """

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._ensure_table()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _ensure_table(self) -> None:
        conn = self._get_conn()
        try:
            conn.execute("""
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
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cv_field_resource
                ON case_vectors(field_name, resource_type)
            """)
            conn.commit()
        finally:
            conn.close()

    def upsert(self, record: VectorRecord) -> None:
        blob = record.vector.astype(np.float32).tobytes()
        meta_json = json.dumps(record.metadata or {})
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO case_vectors
                   (case_id, field_name, vector, resource_type, metadata_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    record.case_id,
                    record.field_name,
                    blob,
                    record.resource_type,
                    meta_json,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def search(
        self,
        query_vector: np.ndarray,
        field_name: str = "symptom",
        resource_type: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        conn = self._get_conn()
        try:
            sql = "SELECT case_id, field_name, vector, resource_type, metadata_json FROM case_vectors WHERE field_name = ?"
            params: list = [field_name]
            if resource_type:
                sql += " AND resource_type = ?"
                params.append(resource_type)

            rows = conn.execute(sql, params).fetchall()
            if not rows:
                return []

            # Batch cosine similarity
            qv = query_vector.astype(np.float32)
            q_norm = np.linalg.norm(qv)
            if q_norm == 0:
                return []
            qv_normed = qv / q_norm

            results: list[SearchResult] = []
            for case_id, fname, blob, rtype, meta_json in rows:
                vec = np.frombuffer(blob, dtype=np.float32)
                v_norm = np.linalg.norm(vec)
                if v_norm == 0:
                    continue
                cos_sim = float(np.dot(qv_normed, vec / v_norm))
                meta = {}
                try:
                    meta = json.loads(meta_json) if meta_json else {}
                except (json.JSONDecodeError, TypeError):
                    pass
                results.append(
                    SearchResult(
                        case_id=case_id,
                        field_name=fname,
                        score=cos_sim,
                        resource_type=rtype,
                        metadata=meta,
                    )
                )

            results.sort(key=lambda r: r.score, reverse=True)
            return results[:top_k]
        finally:
            conn.close()

    def delete(self, case_id: str) -> int:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "DELETE FROM case_vectors WHERE case_id = ?", (case_id,)
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) FROM case_vectors").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_vector_store: Optional[VectorStore] = None


def get_vector_store() -> SQLiteVectorStore:
    """Return a singleton SQLiteVectorStore using the project database."""
    global _vector_store
    if _vector_store is None:
        from agenticops.config import settings

        db_path = settings.database_url.replace("sqlite:///", "")
        _vector_store = SQLiteVectorStore(db_path)
    return _vector_store  # type: ignore[return-value]


def reset_vector_store() -> None:
    """Reset the singleton (for testing)."""
    global _vector_store
    _vector_store = None
