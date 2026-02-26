"""SOP Identifier — match incoming issues against existing SOPs.

Uses hybrid search (vector + keyword) from the KB infrastructure.
Returns the best-matching SOP with a similarity score, or None.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agenticops.config import settings
from agenticops.tools.kb_tools import (
    _keyword_search_sops,
    _parse_frontmatter,
)

logger = logging.getLogger(__name__)


@dataclass
class SOPMatch:
    """Result of an SOP search."""

    sop_path: str
    filename: str
    similarity_score: float
    resource_type: str
    issue_pattern: str
    content: str


def identify_matching_sop(
    resource_type: str,
    issue_pattern: str,
    severity: str = "",
) -> Optional[SOPMatch]:
    """Find the best-matching SOP for a given issue pattern.

    Tries vector search first for semantic matching, falls back to keyword.
    Returns the highest-scoring match above the configured threshold,
    or None if no match is found.

    Args:
        resource_type: AWS resource type (EC2, RDS, EKS, etc.)
        issue_pattern: Symptom or issue description text.
        severity: Optional severity filter.

    Returns:
        SOPMatch with path and score, or None.
    """
    settings.ensure_dirs()
    threshold = settings.sop_similarity_threshold

    # --- Try vector search first ---
    try:
        from agenticops.kb.search import hybrid_search

        results = hybrid_search(
            query_text=issue_pattern,
            resource_type=resource_type,
            search_dir=settings.sops_dir,
            field_name="symptom",
            top_k=1,
        )
        if results and results[0].score >= threshold:
            r = results[0]
            file_path = r.file_path or str(settings.sops_dir / f"{r.case_id}.md")
            content = r.content or ""
            if not content and Path(file_path).exists():
                content = Path(file_path).read_text()
            metadata, _ = _parse_frontmatter(content) if content else ({}, "")
            return SOPMatch(
                sop_path=file_path,
                filename=Path(file_path).name,
                similarity_score=r.score,
                resource_type=metadata.get("resource_type", resource_type),
                issue_pattern=metadata.get("issue_pattern", ""),
                content=content,
            )
    except Exception as e:
        logger.debug("Vector SOP search unavailable: %s", e)

    # --- Keyword fallback ---
    matches = _keyword_search_sops(resource_type, issue_pattern)
    if not matches:
        return None

    best = matches[0]
    metadata = best.get("metadata", {})
    # Normalize keyword score to 0..1 range (heuristic: max meaningful score ~10)
    normalized_score = min(1.0, best.get("score", 0) / 10.0) if "score" in best else 0.5

    if normalized_score < threshold:
        return None

    sop_path = str(settings.sops_dir / best["file"])
    return SOPMatch(
        sop_path=sop_path,
        filename=best["file"],
        similarity_score=normalized_score,
        resource_type=metadata.get("resource_type", resource_type),
        issue_pattern=metadata.get("issue_pattern", ""),
        content=best.get("content", ""),
    )
