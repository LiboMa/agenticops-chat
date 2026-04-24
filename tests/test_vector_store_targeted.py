"""Targeted tests for kb/vector_store.py — boosting coverage from 55%.

Covers: SQLiteVectorStore (delete, count, zero-vector edge cases, metadata
parsing, resource_type filtering, upsert-replace), PostgresVectorStore and
S3VectorStore construction, and the singleton factory/reset helpers.
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agenticops.kb.vector_store import (
    SQLiteVectorStore,
    SearchResult,
    VectorRecord,
    VectorStore,
    get_vector_store,
    reset_vector_store,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rand_vec(dim: int = 16) -> np.ndarray:
    v = np.random.randn(dim).astype(np.float32)
    return v


@pytest.fixture
def store(tmp_path):
    """Fresh SQLiteVectorStore in a temp directory."""
    return SQLiteVectorStore(tmp_path / "test_vectors.db")


# ---------------------------------------------------------------------------
# SQLiteVectorStore — core CRUD
# ---------------------------------------------------------------------------


class TestSQLiteVectorStoreCRUD:
    def test_upsert_and_count(self, store):
        assert store.count() == 0
        rec = VectorRecord(case_id="c1", field_name="symptom", vector=_rand_vec())
        store.upsert(rec)
        assert store.count() == 1

    def test_upsert_replaces_same_key(self, store):
        v1 = _rand_vec()
        v2 = _rand_vec()
        store.upsert(VectorRecord(case_id="c1", field_name="symptom", vector=v1))
        store.upsert(VectorRecord(case_id="c1", field_name="symptom", vector=v2))
        assert store.count() == 1  # replaced, not duplicated

    def test_delete_returns_count(self, store):
        store.upsert(VectorRecord(case_id="c1", field_name="symptom", vector=_rand_vec()))
        store.upsert(VectorRecord(case_id="c1", field_name="root_cause", vector=_rand_vec()))
        deleted = store.delete("c1")
        assert deleted == 2
        assert store.count() == 0

    def test_delete_nonexistent(self, store):
        assert store.delete("no-such-case") == 0

    def test_count_empty(self, store):
        assert store.count() == 0


# ---------------------------------------------------------------------------
# SQLiteVectorStore — search edge cases
# ---------------------------------------------------------------------------


class TestSQLiteSearch:
    def test_search_empty_store(self, store):
        results = store.search(_rand_vec(), field_name="symptom")
        assert results == []

    def test_search_zero_query_vector(self, store):
        store.upsert(VectorRecord(case_id="c1", field_name="symptom", vector=_rand_vec()))
        zero_vec = np.zeros(16, dtype=np.float32)
        results = store.search(zero_vec, field_name="symptom")
        assert results == []

    def test_search_with_resource_type_filter(self, store):
        store.upsert(VectorRecord(case_id="c1", field_name="symptom", vector=_rand_vec(), resource_type="ec2"))
        store.upsert(VectorRecord(case_id="c2", field_name="symptom", vector=_rand_vec(), resource_type="rds"))
        results = store.search(_rand_vec(), field_name="symptom", resource_type="ec2")
        case_ids = {r.case_id for r in results}
        assert "c2" not in case_ids

    def test_search_returns_top_k(self, store):
        for i in range(10):
            store.upsert(VectorRecord(case_id=f"c{i}", field_name="symptom", vector=_rand_vec()))
        results = store.search(_rand_vec(), field_name="symptom", top_k=3)
        assert len(results) <= 3

    def test_search_results_sorted_descending(self, store):
        for i in range(5):
            store.upsert(VectorRecord(case_id=f"c{i}", field_name="symptom", vector=_rand_vec()))
        results = store.search(_rand_vec(), field_name="symptom", top_k=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_with_metadata(self, store):
        meta = {"service": "api-gw", "region": "us-east-1"}
        store.upsert(VectorRecord(case_id="c1", field_name="symptom", vector=_rand_vec(), metadata=meta))
        results = store.search(_rand_vec(), field_name="symptom")
        assert len(results) >= 1
        assert results[0].metadata == meta

    def test_search_with_invalid_metadata_json(self, store):
        """Corrupt metadata_json should not crash search."""
        rec = VectorRecord(case_id="c1", field_name="symptom", vector=_rand_vec())
        store.upsert(rec)
        # Manually corrupt metadata_json
        import sqlite3
        conn = sqlite3.connect(store._db_path)
        conn.execute("UPDATE case_vectors SET metadata_json = 'NOT-JSON' WHERE case_id = 'c1'")
        conn.commit()
        conn.close()
        results = store.search(_rand_vec(), field_name="symptom")
        assert len(results) == 1
        assert results[0].metadata == {}

    def test_search_skips_zero_norm_stored_vectors(self, store):
        """Stored zero-vectors should be skipped in results."""
        zero = np.zeros(16, dtype=np.float32)
        store.upsert(VectorRecord(case_id="c_zero", field_name="symptom", vector=zero))
        store.upsert(VectorRecord(case_id="c_good", field_name="symptom", vector=_rand_vec()))
        results = store.search(_rand_vec(), field_name="symptom")
        case_ids = {r.case_id for r in results}
        assert "c_zero" not in case_ids

    def test_search_field_name_filters(self, store):
        store.upsert(VectorRecord(case_id="c1", field_name="symptom", vector=_rand_vec()))
        store.upsert(VectorRecord(case_id="c2", field_name="root_cause", vector=_rand_vec()))
        results = store.search(_rand_vec(), field_name="root_cause")
        case_ids = {r.case_id for r in results}
        assert "c1" not in case_ids


# ---------------------------------------------------------------------------
# PostgresVectorStore — construction (no live DB needed)
# ---------------------------------------------------------------------------


class TestPostgresVectorStoreInit:
    def test_construction(self):
        from agenticops.kb.vector_store import PostgresVectorStore
        pg = PostgresVectorStore("postgresql://user:pass@localhost/test", dimension=512)
        assert pg._dimension == 512
        assert pg._conn is None


# ---------------------------------------------------------------------------
# S3VectorStore — construction and helper methods
# ---------------------------------------------------------------------------


class TestS3VectorStoreInit:
    def test_construction(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="my-bucket", prefix="vecs/", region="eu-west-1", dimension=768)
        assert s3._bucket == "my-bucket"
        assert s3._prefix == "vecs/"
        assert s3._region == "eu-west-1"
        assert s3._dimension == 768

    def test_vector_key(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        assert s3._vector_key("case-1", "symptom") == "v/case-1/symptom.npy"

    def test_index_key(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="vectors/")
        assert s3._index_key == "vectors/_index.json"

    def test_prefix_normalization(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="no-trailing-slash")
        assert s3._prefix.endswith("/")

    def test_load_index_returns_empty_on_error(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("NoSuchKey")
        s3._client = mock_client
        idx = s3._load_index()
        assert idx == {"records": {}}

    def test_count_uses_index(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        mock_client = MagicMock()
        body_mock = MagicMock()
        body_mock.read.return_value = json.dumps({"records": {"a/symptom": {}, "b/symptom": {}}}).encode()
        mock_client.get_object.return_value = {"Body": body_mock}
        s3._client = mock_client
        assert s3.count() == 2

    def test_search_zero_vector(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        mock_client = MagicMock()
        body_mock = MagicMock()
        body_mock.read.return_value = json.dumps({"records": {}}).encode()
        mock_client.get_object.return_value = {"Body": body_mock}
        s3._client = mock_client
        results = s3.search(np.zeros(16, dtype=np.float32))
        assert results == []

    def test_delete_nonexistent(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        mock_client = MagicMock()
        body_mock = MagicMock()
        body_mock.read.return_value = json.dumps({"records": {}}).encode()
        mock_client.get_object.return_value = {"Body": body_mock}
        s3._client = mock_client
        assert s3.delete("no-case") == 0

    def test_upsert_stores_to_s3(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        mock_client = MagicMock()
        body_mock = MagicMock()
        body_mock.read.return_value = json.dumps({"records": {}}).encode()
        mock_client.get_object.return_value = {"Body": body_mock}
        s3._client = mock_client
        rec = VectorRecord(case_id="c1", field_name="symptom", vector=_rand_vec(), resource_type="ec2")
        s3.upsert(rec)
        mock_client.put_object.assert_called()

    def test_search_with_records(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        mock_client = MagicMock()
        vec = _rand_vec()
        records = {
            "c1/symptom": {
                "case_id": "c1",
                "field_name": "symptom",
                "resource_type": "ec2",
                "metadata": {"k": "v"},
                "s3_key": "v/c1/symptom.npy",
            }
        }
        index_body = MagicMock()
        index_body.read.return_value = json.dumps({"records": records}).encode()

        vec_body = MagicMock()
        vec_body.read.return_value = vec.tobytes()

        def get_object_side_effect(**kwargs):
            if kwargs["Key"] == "v/_index.json":
                return {"Body": index_body}
            return {"Body": vec_body}

        mock_client.get_object.side_effect = get_object_side_effect
        s3._client = mock_client
        results = s3.search(vec, field_name="symptom")
        assert len(results) == 1
        assert results[0].case_id == "c1"

    def test_search_handles_s3_error_gracefully(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        mock_client = MagicMock()
        records = {
            "c1/symptom": {
                "case_id": "c1",
                "field_name": "symptom",
                "resource_type": "",
                "metadata": {},
                "s3_key": "v/c1/symptom.npy",
            }
        }
        index_body = MagicMock()
        index_body.read.return_value = json.dumps({"records": records}).encode()

        def get_object_side_effect(**kwargs):
            if kwargs["Key"] == "v/_index.json":
                return {"Body": index_body}
            raise Exception("S3 error")

        mock_client.get_object.side_effect = get_object_side_effect
        s3._client = mock_client
        results = s3.search(_rand_vec(), field_name="symptom")
        assert results == []

    def test_delete_removes_from_index_and_s3(self):
        from agenticops.kb.vector_store import S3VectorStore
        s3 = S3VectorStore(bucket="b", prefix="v/")
        mock_client = MagicMock()
        records = {
            "c1/symptom": {
                "case_id": "c1",
                "field_name": "symptom",
                "resource_type": "",
                "metadata": {},
                "s3_key": "v/c1/symptom.npy",
            }
        }
        index_body = MagicMock()
        index_body.read.return_value = json.dumps({"records": records}).encode()
        mock_client.get_object.return_value = {"Body": index_body}
        s3._client = mock_client
        deleted = s3.delete("c1")
        assert deleted == 1
        mock_client.delete_object.assert_called_once()
        mock_client.put_object.assert_called()  # saves updated index


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------


class TestVectorStoreFactory:
    def setup_method(self):
        reset_vector_store()

    def teardown_method(self):
        reset_vector_store()

    def test_reset_clears_singleton(self):
        from agenticops.kb import vector_store as vs_mod
        vs_mod._vector_store = MagicMock()
        reset_vector_store()
        assert vs_mod._vector_store is None

    @patch("agenticops.kb.vector_store.SQLiteVectorStore")
    @patch("agenticops.config.settings")
    def test_factory_default_sqlite(self, mock_settings, mock_sqlite_cls):
        mock_settings.vector_storage = "sqlite"
        mock_settings.database_url = "sqlite:///test.db"
        mock_sqlite_cls.return_value = MagicMock()
        store = get_vector_store()
        mock_sqlite_cls.assert_called_once_with("test.db")
        assert store is not None

    @patch("agenticops.kb.vector_store.PostgresVectorStore")
    @patch("agenticops.config.settings")
    def test_factory_rds(self, mock_settings, mock_pg_cls):
        mock_settings.vector_storage = "rds"
        mock_settings.vector_rds_url = "postgresql://localhost/test"
        mock_settings.embedding_dimension = 1024
        mock_pg_cls.return_value = MagicMock()
        store = get_vector_store()
        mock_pg_cls.assert_called_once_with(
            connection_url="postgresql://localhost/test",
            dimension=1024,
        )

    @patch("agenticops.kb.vector_store.S3VectorStore")
    @patch("agenticops.config.settings")
    def test_factory_s3(self, mock_settings, mock_s3_cls):
        mock_settings.vector_storage = "s3"
        mock_settings.vector_s3_bucket = "my-bucket"
        mock_settings.vector_s3_prefix = "vecs/"
        mock_settings.vector_s3_region = "us-west-2"
        mock_settings.embedding_dimension = 768
        mock_s3_cls.return_value = MagicMock()
        store = get_vector_store()
        mock_s3_cls.assert_called_once_with(
            bucket="my-bucket",
            prefix="vecs/",
            region="us-west-2",
            dimension=768,
        )
