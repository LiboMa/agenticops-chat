"""Hybrid search: vector similarity + keyword fallback with reranking.

Single entry point for all KB searches. Used by kb_tools.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HybridResult:
    case_id: str
    file_path: str
    score: float
    source: str  # "vector", "keyword", "both"
    content: str = ""
    metadata: dict | None = None


def hybrid_search(
    query_text: str,
    resource_type: str = "",
    search_dir: Optional[Path] = None,
    field_name: str = "symptom",
    top_k: int = 5,
) -> list[HybridResult]:
    """Perform hybrid search: vector → keyword fallback → rerank.

    1. Filter by resource_type (SQL WHERE)
    2. Vector search via embedding + cosine similarity
    3. Keyword fallback if vector returns < top_k or embeddings unavailable
    4. Rerank: final_score = cosine_sim * 0.6 + efficiency_score * 0.2 + 0.2
       Verified cases get 1.2x boost.

    Args:
        query_text: Natural language query (symptoms, description).
        resource_type: AWS resource type filter (e.g. "EC2"). Empty = all.
        search_dir: Directory containing markdown case files.
        field_name: Vector field to search ("symptom" or "root_cause").
        top_k: Maximum results to return.

    Returns:
        Sorted list of HybridResult.
    """
    from agenticops.config import settings

    if search_dir is None:
        search_dir = settings.cases_dir

    vector_results = _vector_search(query_text, resource_type, field_name, top_k)
    vector_ids = {r.case_id for r in vector_results}

    # Keyword fallback to fill remaining slots
    needed = max(0, top_k - len(vector_results))
    keyword_results: list[HybridResult] = []
    if needed > 0 or not vector_results:
        keyword_results = _keyword_search(
            query_text, resource_type, search_dir, top_k
        )

    # Merge: prefer vector results, supplement with keyword
    merged: dict[str, HybridResult] = {}
    for vr in vector_results:
        merged[vr.case_id] = vr
    for kr in keyword_results:
        key = kr.case_id or kr.file_path
        if key not in merged and kr.file_path not in {m.file_path for m in merged.values()}:
            merged[key] = kr

    # Rerank
    reranked = _rerank(list(merged.values()))
    return reranked[:top_k]


def _vector_search(
    query_text: str,
    resource_type: str,
    field_name: str,
    top_k: int,
) -> list[HybridResult]:
    """Embed query and search vector store."""
    try:
        from agenticops.kb.embeddings import get_embedding_client
        from agenticops.kb.vector_store import get_vector_store

        client = get_embedding_client()
        query_vec = client.embed(query_text)
        if query_vec is None:
            return []

        store = get_vector_store()
        results = store.search(
            query_vector=query_vec,
            field_name=field_name,
            resource_type=resource_type.upper() if resource_type else None,
            top_k=top_k,
        )
        return [
            HybridResult(
                case_id=r.case_id,
                file_path="",
                score=r.score,
                source="vector",
                metadata=r.metadata,
            )
            for r in results
        ]
    except Exception as e:
        logger.warning("Vector search failed: %s", e)
        return []


def _keyword_search(
    query_text: str,
    resource_type: str,
    search_dir: Path,
    top_k: int,
) -> list[HybridResult]:
    """Keyword-based search over markdown files (extracted from original kb_tools logic)."""
    from agenticops.tools.kb_tools import _parse_frontmatter

    keywords = query_text.lower().split()
    results: list[HybridResult] = []

    for md_file in search_dir.glob("*.md"):
        try:
            content = md_file.read_text()
            metadata, body = _parse_frontmatter(content)
            file_text = content.lower()

            score = sum(1 for kw in keywords if kw in file_text)
            case_type = str(metadata.get("resource_type", "")).upper()
            if resource_type and resource_type.upper() in case_type:
                score += 2

            if score > 0:
                # Normalize keyword score to 0-1 range (rough heuristic)
                norm_score = min(score / max(len(keywords) + 2, 1), 1.0)
                results.append(
                    HybridResult(
                        case_id=str(metadata.get("case_id", md_file.stem)),
                        file_path=str(md_file),
                        score=norm_score,
                        source="keyword",
                        content=content,
                        metadata=metadata,
                    )
                )
        except Exception as e:
            logger.warning("Error reading %s: %s", md_file, e)

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def _rerank(results: list[HybridResult]) -> list[HybridResult]:
    """Rerank results: final_score = cosine_sim * 0.6 + efficiency_score * 0.2 + 0.2.

    Verified cases get a 1.2x boost.
    """
    for r in results:
        efficiency = 0.5
        verified = False
        if r.metadata:
            try:
                efficiency = float(r.metadata.get("efficiency_score", 0.5))
            except (ValueError, TypeError):
                pass
            verified = str(r.metadata.get("verified", "false")).lower() == "true"

        base_score = r.score * 0.6 + efficiency * 0.2 + 0.2
        if verified:
            base_score *= 1.2
        r.score = min(base_score, 1.0)

    results.sort(key=lambda r: r.score, reverse=True)
    return results
