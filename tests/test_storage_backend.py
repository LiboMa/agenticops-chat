"""Tests for agenticops.storage.backend — LocalBackend, S3Backend, factories.

Targets the 57% → 85%+ coverage gap for storage/backend.py.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from agenticops.storage.backend import (
    LocalBackend,
    S3Backend,
    get_storage_backend,
    get_kb_backend,
    StorageBackend,
)
import agenticops.storage.backend as backend_mod


# ── LocalBackend ──────────────────────────────────────────────────────


class TestLocalBackend:
    def test_write_and_read(self, tmp_path):
        backend = LocalBackend(tmp_path)
        uri = backend.write("reports/r1.txt", b"hello world")
        assert Path(uri).exists()
        assert backend.read(uri) == b"hello world"

    def test_write_creates_subdirectories(self, tmp_path):
        backend = LocalBackend(tmp_path)
        uri = backend.write("deep/nested/dir/file.bin", b"\x00\x01")
        assert Path(uri).exists()
        assert backend.read(uri) == b"\x00\x01"

    def test_exists_true(self, tmp_path):
        backend = LocalBackend(tmp_path)
        uri = backend.write("test.txt", b"data")
        assert backend.exists(uri) is True

    def test_exists_false(self, tmp_path):
        backend = LocalBackend(tmp_path)
        assert backend.exists(str(tmp_path / "nonexistent.txt")) is False

    def test_delete_existing(self, tmp_path):
        backend = LocalBackend(tmp_path)
        uri = backend.write("to_delete.txt", b"bye")
        assert backend.delete(uri) is True
        assert not Path(uri).exists()

    def test_delete_nonexistent(self, tmp_path):
        backend = LocalBackend(tmp_path)
        assert backend.delete(str(tmp_path / "nope.txt")) is False

    def test_presigned_url_returns_none(self, tmp_path):
        backend = LocalBackend(tmp_path)
        assert backend.presigned_url("anything") is None

    def test_content_type_ignored(self, tmp_path):
        """LocalBackend ignores content_type but shouldn't error."""
        backend = LocalBackend(tmp_path)
        uri = backend.write("ct.txt", b"data", content_type="text/plain")
        assert backend.read(uri) == b"data"


# ── S3Backend ─────────────────────────────────────────────────────────


class TestS3Backend:
    def _make_backend(self):
        backend = S3Backend(bucket="test-bucket", prefix="reports/", region="us-west-2")
        backend._client = MagicMock()
        return backend

    def test_full_key(self):
        backend = self._make_backend()
        assert backend._full_key("file.txt") == "reports/file.txt"

    def test_full_key_empty_prefix(self):
        backend = S3Backend(bucket="b", prefix="", region="us-east-1")
        assert backend._full_key("k") == "k"

    def test_parse_uri(self):
        bucket, key = S3Backend._parse_uri("s3://my-bucket/some/key.txt")
        assert bucket == "my-bucket"
        assert key == "some/key.txt"

    def test_write(self):
        backend = self._make_backend()
        uri = backend.write("test.json", b'{"a":1}', content_type="application/json")
        assert uri == "s3://test-bucket/reports/test.json"
        backend._client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="reports/test.json",
            Body=b'{"a":1}',
            ContentType="application/json",
        )

    def test_write_no_content_type(self):
        backend = self._make_backend()
        backend.write("plain.txt", b"data")
        call_kwargs = backend._client.put_object.call_args[1]
        assert "ContentType" not in call_kwargs

    def test_read(self):
        backend = self._make_backend()
        body_mock = MagicMock()
        body_mock.read.return_value = b"file contents"
        backend._client.get_object.return_value = {"Body": body_mock}

        data = backend.read("s3://test-bucket/reports/test.txt")
        assert data == b"file contents"
        backend._client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="reports/test.txt"
        )

    def test_exists_true(self):
        backend = self._make_backend()
        backend._client.head_object.return_value = {}
        assert backend.exists("s3://test-bucket/reports/x.txt") is True

    def test_exists_false(self):
        from botocore.exceptions import ClientError
        backend = self._make_backend()
        backend._client.exceptions.ClientError = ClientError
        backend._client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )
        assert backend.exists("s3://test-bucket/reports/missing.txt") is False

    def test_delete_success(self):
        backend = self._make_backend()
        assert backend.delete("s3://test-bucket/reports/del.txt") is True
        backend._client.delete_object.assert_called_once()

    def test_delete_failure(self):
        backend = self._make_backend()
        backend._client.delete_object.side_effect = RuntimeError("boom")
        assert backend.delete("s3://test-bucket/reports/del.txt") is False

    def test_presigned_url_success(self):
        backend = self._make_backend()
        backend._client.generate_presigned_url.return_value = "https://signed.url"
        url = backend.presigned_url("s3://test-bucket/reports/f.txt", expiry=600)
        assert url == "https://signed.url"

    def test_presigned_url_failure(self):
        backend = self._make_backend()
        backend._client.generate_presigned_url.side_effect = Exception("fail")
        assert backend.presigned_url("s3://test-bucket/reports/f.txt") is None

    def test_lazy_client_creation(self):
        """_s3 property lazily creates boto3 client."""
        with patch("boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            backend = S3Backend(bucket="b", prefix="p/", region="eu-west-1")
            _ = backend._s3
            mock_boto.assert_called_once_with("s3", region_name="eu-west-1")
            # Second access should not re-create
            _ = backend._s3
            assert mock_boto.call_count == 1


# ── Factory functions ─────────────────────────────────────────────────


class TestGetStorageBackend:
    def setup_method(self):
        backend_mod._backend = None  # reset singleton

    def teardown_method(self):
        backend_mod._backend = None

    def test_local_backend(self, tmp_path):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.report_storage = "local"
            mock_settings.reports_dir = tmp_path
            backend = get_storage_backend()
            assert isinstance(backend, LocalBackend)

    def test_s3_backend(self):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.report_storage = "s3"
            mock_settings.report_s3_bucket = "my-bucket"
            mock_settings.report_s3_prefix = "reports/"
            mock_settings.report_s3_region = "us-east-1"
            backend = get_storage_backend()
            assert isinstance(backend, S3Backend)

    def test_singleton(self, tmp_path):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.report_storage = "local"
            mock_settings.reports_dir = tmp_path
            b1 = get_storage_backend()
            b2 = get_storage_backend()
            assert b1 is b2


class TestGetKbBackend:
    def setup_method(self):
        backend_mod._kb_backend = None

    def teardown_method(self):
        backend_mod._kb_backend = None

    def test_local_kb_backend(self, tmp_path):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.kb_storage = "local"
            mock_settings.knowledge_base_dir = tmp_path
            backend = get_kb_backend()
            assert isinstance(backend, LocalBackend)

    def test_s3_kb_backend(self):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.kb_storage = "s3"
            mock_settings.kb_s3_bucket = "kb-bucket"
            mock_settings.kb_s3_prefix = "kb/"
            mock_settings.kb_s3_region = "us-west-2"
            backend = get_kb_backend()
            assert isinstance(backend, S3Backend)
