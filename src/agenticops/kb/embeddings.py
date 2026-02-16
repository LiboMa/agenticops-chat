"""Embedding client abstraction for KB vector search.

Provides BedrockTitanEmbedding (Titan V2, 1024 dims) with NullEmbeddingClient
fallback when Bedrock is unavailable.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingClient(ABC):
    """Abstract embedding client interface."""

    @abstractmethod
    def embed(self, text: str) -> Optional[np.ndarray]:
        """Embed text into a vector. Returns None on failure."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...


class NullEmbeddingClient(EmbeddingClient):
    """No-op client used when Bedrock is unavailable (graceful degradation)."""

    def embed(self, text: str) -> Optional[np.ndarray]:
        return None

    @property
    def dimension(self) -> int:
        return 0


class BedrockTitanEmbedding(EmbeddingClient):
    """AWS Bedrock Titan Text Embeddings V2 client.

    Model: amazon.titan-embed-text-v2:0 — 1024 dimensions, float32.
    Truncates input to 8000 chars to stay within Titan limits.
    """

    MAX_INPUT_CHARS = 8000

    def __init__(self, model_id: str, region: str, dim: int = 1024):
        self._model_id = model_id
        self._region = region
        self._dim = dim
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "bedrock-runtime", region_name=self._region
            )
        return self._client

    def embed(self, text: str) -> Optional[np.ndarray]:
        if not text or not text.strip():
            return None
        text = text[: self.MAX_INPUT_CHARS]
        try:
            client = self._get_client()
            body = json.dumps({
                "inputText": text,
                "dimensions": self._dim,
                "normalize": True,
            })
            resp = client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            result = json.loads(resp["body"].read())
            embedding = result.get("embedding")
            if embedding:
                return np.array(embedding, dtype=np.float32)
            return None
        except Exception as e:
            logger.warning("Bedrock embedding failed: %s", e)
            return None

    @property
    def dimension(self) -> int:
        return self._dim


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_embedding_client: Optional[EmbeddingClient] = None
_client_initialized = False


def get_embedding_client() -> EmbeddingClient:
    """Return a singleton EmbeddingClient.

    On first call, tests Bedrock connectivity. Falls back to NullEmbeddingClient
    if Bedrock is unreachable or embedding is disabled.
    """
    global _embedding_client, _client_initialized
    if _client_initialized:
        return _embedding_client  # type: ignore[return-value]

    from agenticops.config import settings

    if not getattr(settings, "embedding_enabled", True):
        logger.info("Embedding disabled via config — using NullEmbeddingClient")
        _embedding_client = NullEmbeddingClient()
        _client_initialized = True
        return _embedding_client

    model_id = getattr(settings, "embedding_model_id", "amazon.titan-embed-text-v2:0")
    dim = getattr(settings, "embedding_dimension", 1024)
    region = settings.bedrock_region

    candidate = BedrockTitanEmbedding(model_id=model_id, region=region, dim=dim)

    # Connectivity test with a short string
    try:
        test_vec = candidate.embed("connectivity test")
        if test_vec is not None:
            logger.info("Bedrock Titan embedding available (%s, %d dims)", model_id, dim)
            _embedding_client = candidate
        else:
            logger.warning("Bedrock Titan returned None — falling back to NullEmbeddingClient")
            _embedding_client = NullEmbeddingClient()
    except Exception as e:
        logger.warning("Bedrock Titan unavailable (%s) — falling back to NullEmbeddingClient", e)
        _embedding_client = NullEmbeddingClient()

    _client_initialized = True
    return _embedding_client


def reset_embedding_client() -> None:
    """Reset the singleton (for testing)."""
    global _embedding_client, _client_initialized
    _embedding_client = None
    _client_initialized = False
