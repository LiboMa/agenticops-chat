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


class PostgresVectorStore(VectorStore):
    """PostgreSQL + pgvector backend for production deployments.

    Requires: ``pip install pgvector psycopg2-binary``
    Table: case_vectors (id SERIAL, case_id TEXT, field_name TEXT, vector vector(N),
           resource_type TEXT, metadata_json TEXT, UNIQUE(case_id, field_name))
    """

    def __init__(self, connection_url: str, dimension: int = 1024) -> None:
        self._connection_url = connection_url
        self._dimension = dimension
        self._conn = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            import psycopg2
            self._conn = psycopg2.connect(self._connection_url)
            self._conn.autocommit = False
            with self._conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS case_vectors (
                        id SERIAL PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        field_name TEXT NOT NULL,
                        vector vector({self._dimension}) NOT NULL,
                        resource_type TEXT DEFAULT '',
                        metadata_json TEXT DEFAULT '{{}}',
                        UNIQUE(case_id, field_name)
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cv_field_resource
                    ON case_vectors(field_name, resource_type)
                """)
            self._conn.commit()
        return self._conn

    def upsert(self, record: VectorRecord) -> None:
        vec_list = record.vector.astype(np.float32).tolist()
        meta_json = json.dumps(record.metadata or {})
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO case_vectors (case_id, field_name, vector, resource_type, metadata_json)
                   VALUES (%s, %s, %s::vector, %s, %s)
                   ON CONFLICT (case_id, field_name)
                   DO UPDATE SET vector = EXCLUDED.vector,
                                 resource_type = EXCLUDED.resource_type,
                                 metadata_json = EXCLUDED.metadata_json""",
                (record.case_id, record.field_name, str(vec_list), record.resource_type, meta_json),
            )
        conn.commit()

    def search(
        self,
        query_vector: np.ndarray,
        field_name: str = "symptom",
        resource_type: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        vec_str = str(query_vector.astype(np.float32).tolist())
        conn = self._get_conn()
        with conn.cursor() as cur:
            sql = (
                "SELECT case_id, field_name, 1 - (vector <=> %s::vector) AS score, "
                "resource_type, metadata_json FROM case_vectors WHERE field_name = %s"
            )
            params: list = [vec_str, field_name]
            if resource_type:
                sql += " AND resource_type = %s"
                params.append(resource_type)
            sql += " ORDER BY vector <=> %s::vector LIMIT %s"
            params.extend([vec_str, top_k])
            cur.execute(sql, params)
            rows = cur.fetchall()

        results: list[SearchResult] = []
        for case_id, fname, score, rtype, meta_json in rows:
            meta = {}
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(SearchResult(case_id=case_id, field_name=fname, score=float(score),
                                        resource_type=rtype, metadata=meta))
        return results

    def delete(self, case_id: str) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM case_vectors WHERE case_id = %s", (case_id,))
            count = cur.rowcount
        conn.commit()
        return count

    def count(self) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM case_vectors")
            row = cur.fetchone()
        return row[0] if row else 0


class S3VectorStore(VectorStore):
    """S3-backed vector store using numpy blobs.

    Layout:
      {prefix}{case_id}/{field_name}.npy  — individual vector blobs
      {prefix}_index.json                 — lightweight index of all records
    """

    def __init__(self, bucket: str, prefix: str = "vectors/", region: str = "us-east-1",
                 dimension: int = 1024) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._region = region
        self._dimension = dimension
        self._client = None

    @property
    def _s3(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    def _vector_key(self, case_id: str, field_name: str) -> str:
        return f"{self._prefix}{case_id}/{field_name}.npy"

    @property
    def _index_key(self) -> str:
        return f"{self._prefix}_index.json"

    def _load_index(self) -> dict:
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=self._index_key)
            return json.loads(resp["Body"].read())
        except Exception:
            return {"records": {}}

    def _save_index(self, index: dict) -> None:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=self._index_key,
            Body=json.dumps(index).encode(),
            ContentType="application/json",
        )

    def upsert(self, record: VectorRecord) -> None:
        blob = record.vector.astype(np.float32).tobytes()
        key = self._vector_key(record.case_id, record.field_name)
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=blob)

        index = self._load_index()
        rec_key = f"{record.case_id}/{record.field_name}"
        index["records"][rec_key] = {
            "case_id": record.case_id,
            "field_name": record.field_name,
            "resource_type": record.resource_type,
            "metadata": record.metadata or {},
            "s3_key": key,
        }
        self._save_index(index)

    def search(
        self,
        query_vector: np.ndarray,
        field_name: str = "symptom",
        resource_type: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        index = self._load_index()
        qv = query_vector.astype(np.float32)
        q_norm = np.linalg.norm(qv)
        if q_norm == 0:
            return []
        qv_normed = qv / q_norm

        candidates = [
            r for r in index.get("records", {}).values()
            if r["field_name"] == field_name
            and (resource_type is None or r.get("resource_type") == resource_type)
        ]

        results: list[SearchResult] = []
        for rec in candidates:
            try:
                resp = self._s3.get_object(Bucket=self._bucket, Key=rec["s3_key"])
                vec = np.frombuffer(resp["Body"].read(), dtype=np.float32)
                v_norm = np.linalg.norm(vec)
                if v_norm == 0:
                    continue
                cos_sim = float(np.dot(qv_normed, vec / v_norm))
                results.append(SearchResult(
                    case_id=rec["case_id"],
                    field_name=rec["field_name"],
                    score=cos_sim,
                    resource_type=rec.get("resource_type", ""),
                    metadata=rec.get("metadata"),
                ))
            except Exception:
                logger.warning("Failed to load vector %s", rec["s3_key"], exc_info=True)
                continue

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def delete(self, case_id: str) -> int:
        index = self._load_index()
        to_delete = [k for k, v in index["records"].items() if v["case_id"] == case_id]
        for rec_key in to_delete:
            rec = index["records"].pop(rec_key)
            try:
                self._s3.delete_object(Bucket=self._bucket, Key=rec["s3_key"])
            except Exception:
                logger.warning("Failed to delete S3 vector %s", rec["s3_key"], exc_info=True)
        if to_delete:
            self._save_index(index)
        return len(to_delete)

    def count(self) -> int:
        index = self._load_index()
        return len(index.get("records", {}))


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Vector store factory — routes by settings.vector_storage."""
    global _vector_store
    if _vector_store is None:
        from agenticops.config import settings
        if settings.vector_storage == "rds":
            _vector_store = PostgresVectorStore(
                connection_url=settings.vector_rds_url,
                dimension=settings.embedding_dimension,
            )
        elif settings.vector_storage == "s3":
            _vector_store = S3VectorStore(
                bucket=settings.vector_s3_bucket,
                prefix=settings.vector_s3_prefix,
                region=settings.vector_s3_region,
                dimension=settings.embedding_dimension,
            )
        else:
            db_path = settings.database_url.replace("sqlite:///", "")
            _vector_store = SQLiteVectorStore(db_path)
    return _vector_store


def reset_vector_store() -> None:
    """Reset the singleton (for testing)."""
    global _vector_store
    _vector_store = None
