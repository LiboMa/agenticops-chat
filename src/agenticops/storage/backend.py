"""Storage backend implementations for report persistence.

Provides a pluggable backend so reports can be stored on local disk (dev)
or S3 (production).  The active backend is chosen via ``settings.report_storage``
and instantiated lazily by :func:`get_storage_backend`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract report storage backend."""

    @abstractmethod
    def write(self, key: str, content: bytes, content_type: str = "") -> str:
        """Write *content* under *key* and return the storage URI."""

    @abstractmethod
    def read(self, uri: str) -> bytes:
        """Read content by its storage URI."""

    @abstractmethod
    def exists(self, uri: str) -> bool:
        """Return ``True`` if the object at *uri* exists."""

    @abstractmethod
    def delete(self, uri: str) -> bool:
        """Delete the object at *uri*.  Return ``True`` on success."""

    def presigned_url(self, uri: str, expiry: int = 3600) -> str | None:
        """Return a presigned URL if applicable (S3 only), else ``None``."""
        return None


# ── Local filesystem backend ──────────────────────────────────────────


class LocalBackend(StorageBackend):
    """Store reports as plain files under *base_dir*."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def write(self, key: str, content: bytes, content_type: str = "") -> str:
        dest = self.base_dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return str(dest)

    def read(self, uri: str) -> bytes:
        return Path(uri).read_bytes()

    def exists(self, uri: str) -> bool:
        return Path(uri).exists()

    def delete(self, uri: str) -> bool:
        p = Path(uri)
        if p.exists():
            p.unlink()
            return True
        return False


# ── S3 backend ────────────────────────────────────────────────────────


class S3Backend(StorageBackend):
    """Store reports in an S3 bucket."""

    def __init__(self, bucket: str, prefix: str = "reports/", region: str = "us-east-1") -> None:
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.region = region
        self._client = None

    @property
    def _s3(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    @staticmethod
    def _parse_uri(uri: str) -> tuple[str, str]:
        """Parse ``s3://bucket/key`` into (bucket, key)."""
        parsed = urlparse(uri)
        return parsed.netloc, parsed.path.lstrip("/")

    def write(self, key: str, content: bytes, content_type: str = "") -> str:
        full_key = self._full_key(key)
        kwargs: dict = {"Bucket": self.bucket, "Key": full_key, "Body": content}
        if content_type:
            kwargs["ContentType"] = content_type
        self._s3.put_object(**kwargs)
        return f"s3://{self.bucket}/{full_key}"

    def read(self, uri: str) -> bytes:
        bucket, key = self._parse_uri(uri)
        resp = self._s3.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()

    def exists(self, uri: str) -> bool:
        bucket, key = self._parse_uri(uri)
        try:
            self._s3.head_object(Bucket=bucket, Key=key)
            return True
        except self._s3.exceptions.ClientError:
            return False

    def delete(self, uri: str) -> bool:
        bucket, key = self._parse_uri(uri)
        try:
            self._s3.delete_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def presigned_url(self, uri: str, expiry: int = 3600) -> str | None:
        bucket, key = self._parse_uri(uri)
        try:
            return self._s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expiry,
            )
        except Exception:
            logger.warning("Failed to generate presigned URL for %s", uri, exc_info=True)
            return None


# ── Factory ───────────────────────────────────────────────────────────

_backend: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """Return the lazily-initialised storage backend singleton."""
    global _backend
    if _backend is None:
        from agenticops.config import settings

        if settings.report_storage == "s3":
            _backend = S3Backend(
                bucket=settings.report_s3_bucket,
                prefix=settings.report_s3_prefix,
                region=settings.report_s3_region,
            )
        else:
            _backend = LocalBackend(base_dir=settings.reports_dir)
    return _backend
