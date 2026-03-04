"""Report storage backend abstraction (local filesystem or S3)."""

from agenticops.storage.backend import StorageBackend, get_storage_backend

__all__ = ["StorageBackend", "get_storage_backend"]
