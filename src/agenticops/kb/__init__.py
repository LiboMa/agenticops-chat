"""Knowledge Base package — vector search, case studies, and embeddings."""

from agenticops.kb.case_study import (
    CaseStudy,
    CaseStudyMeta,
    CaseStudyStatus,
    EmbeddingInputs,
    LessonsLearned,
    Resolution,
)
from agenticops.kb.embeddings import (
    EmbeddingClient,
    NullEmbeddingClient,
    BedrockTitanEmbedding,
    get_embedding_client,
)
from agenticops.kb.vector_store import (
    VectorStore,
    SQLiteVectorStore,
    VectorRecord,
    SearchResult,
    get_vector_store,
)
from agenticops.kb.search import hybrid_search, HybridResult

__all__ = [
    # Case study
    "CaseStudy",
    "CaseStudyMeta",
    "CaseStudyStatus",
    "EmbeddingInputs",
    "LessonsLearned",
    "Resolution",
    # Embeddings
    "EmbeddingClient",
    "NullEmbeddingClient",
    "BedrockTitanEmbedding",
    "get_embedding_client",
    # Vector store
    "VectorStore",
    "SQLiteVectorStore",
    "VectorRecord",
    "SearchResult",
    "get_vector_store",
    # Search
    "hybrid_search",
    "HybridResult",
]
