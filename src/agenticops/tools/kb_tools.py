"""Knowledge Base tools for Strands agents.

Local Markdown + JSON index for SOPs, cases, and patterns.
Supports hybrid search (vector + keyword) and case study distillation.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from strands import tool

from agenticops.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Frontmatter parser (shared with kb.search)
# ---------------------------------------------------------------------------


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML-style frontmatter from markdown content.

    Returns (metadata_dict, body_text).
    """
    metadata = {}
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            body = parts[2].strip()

            for line in frontmatter.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    # Handle list values like [a, b, c]
                    if value.startswith("[") and value.endswith("]"):
                        value = [
                            v.strip().strip("'\"")
                            for v in value[1:-1].split(",")
                        ]
                    metadata[key] = value

    return metadata, body


# ---------------------------------------------------------------------------
# Keyword search helpers (used as fallback by hybrid search)
# ---------------------------------------------------------------------------


def _keyword_search_cases(
    resource_type: str, issue_pattern: str, limit: int = 3
) -> list[dict]:
    """Keyword-based case search (original logic, extracted for reuse)."""
    cases_dir = settings.cases_dir
    matches = []
    keywords = issue_pattern.lower().split()

    for case_file in cases_dir.glob("*.md"):
        try:
            content = case_file.read_text()
            metadata, body = _parse_frontmatter(content)

            case_type = str(metadata.get("resource_type", "")).upper()
            file_text = content.lower()

            score = sum(1 for kw in keywords if kw in file_text)
            if resource_type.upper() in case_type:
                score += 2

            if score > 0:
                matches.append({
                    "file": case_file.name,
                    "score": score,
                    "content": content,
                })
        except Exception as e:
            logger.warning("Error reading case %s: %s", case_file, e)

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:limit]


def _keyword_search_sops(resource_type: str, issue_pattern: str) -> list[dict]:
    """Keyword-based SOP search (original logic, extracted for reuse)."""
    sops_dir = settings.sops_dir
    matches = []
    keywords = issue_pattern.lower().split()

    for sop_file in sops_dir.glob("*.md"):
        try:
            content = sop_file.read_text()
            metadata, body = _parse_frontmatter(content)

            sop_type = str(metadata.get("resource_type", "")).upper()
            if resource_type.upper() != sop_type and sop_type != "":
                if resource_type.upper() not in sop_type:
                    continue

            sop_keywords = metadata.get("keywords", [])
            if isinstance(sop_keywords, str):
                sop_keywords = [sop_keywords]
            sop_pattern = str(metadata.get("issue_pattern", "")).lower()

            all_sop_text = " ".join(
                str(k).lower() for k in sop_keywords
            ) + " " + sop_pattern + " " + sop_file.stem.lower()

            if any(kw in all_sop_text for kw in keywords):
                matches.append({
                    "file": sop_file.name,
                    "metadata": metadata,
                    "content": content,
                })
        except Exception as e:
            logger.warning("Error reading SOP %s: %s", sop_file, e)

    return matches


# ---------------------------------------------------------------------------
# Tools: Search
# ---------------------------------------------------------------------------


@tool
def search_sops(resource_type: str, issue_pattern: str) -> str:
    """Search Knowledge Base for matching Standard Operating Procedures.

    Tries vector search first for semantic matching, falls back to keyword
    search if vectors are unavailable.

    Args:
        resource_type: AWS resource type (EC2, RDS, Lambda, etc.)
        issue_pattern: Issue pattern keywords (e.g., 'cpu high', 'connection timeout')

    Returns:
        Matching SOP content or 'No SOP found' message.
    """
    settings.ensure_dirs()

    # Try hybrid vector search for SOPs
    try:
        from agenticops.kb.search import hybrid_search

        results = hybrid_search(
            query_text=issue_pattern,
            resource_type=resource_type,
            search_dir=settings.sops_dir,
            field_name="symptom",
            top_k=3,
        )
        if results:
            output = []
            for r in results:
                if r.content:
                    output.append(f"=== SOP: {Path(r.file_path).name if r.file_path else r.case_id} (score: {r.score:.2f}) ===\n{r.content}")
                elif r.file_path:
                    content = Path(r.file_path).read_text()
                    output.append(f"=== SOP: {Path(r.file_path).name} (score: {r.score:.2f}) ===\n{content}")
            if output:
                return "\n\n".join(output)
    except Exception as e:
        logger.debug("Hybrid SOP search unavailable, falling back to keyword: %s", e)

    # Keyword fallback
    matches = _keyword_search_sops(resource_type, issue_pattern)
    if not matches:
        return f"No SOP found for resource_type={resource_type}, pattern='{issue_pattern}'."

    result = []
    for match in matches[:3]:
        result.append(f"=== SOP: {match['file']} ===\n{match['content']}")
    return "\n\n".join(result)


@tool
def search_similar_cases(
    resource_type: str, issue_pattern: str, limit: int = 3
) -> str:
    """Search Knowledge Base for similar historical cases.

    Uses hybrid search (vector + keyword) for semantic matching.
    Falls back to keyword-only if vectors are unavailable.

    Args:
        resource_type: AWS resource type (EC2, RDS, Lambda, etc.)
        issue_pattern: Issue description (use full symptom description for better vector matching)
        limit: Maximum number of cases to return

    Returns:
        Matching case studies or 'No cases found' message.
    """
    settings.ensure_dirs()

    # Try hybrid search first
    try:
        from agenticops.kb.search import hybrid_search

        results = hybrid_search(
            query_text=issue_pattern,
            resource_type=resource_type,
            search_dir=settings.cases_dir,
            field_name="symptom",
            top_k=limit,
        )
        if results:
            output = []
            for r in results:
                if r.content:
                    label = Path(r.file_path).name if r.file_path else r.case_id
                    output.append(f"=== Case: {label} (score: {r.score:.2f}, source: {r.source}) ===\n{r.content}")
                elif r.file_path:
                    content = Path(r.file_path).read_text()
                    output.append(f"=== Case: {Path(r.file_path).name} (score: {r.score:.2f}, source: {r.source}) ===\n{content}")
            if output:
                return "\n\n".join(output)
    except Exception as e:
        logger.debug("Hybrid case search unavailable, falling back to keyword: %s", e)

    # Keyword fallback
    matches = _keyword_search_cases(resource_type, issue_pattern, limit)
    if not matches:
        return f"No similar cases found for resource_type={resource_type}, pattern='{issue_pattern}'."

    result = []
    for match in matches[:limit]:
        result.append(f"=== Case: {match['file']} (score: {match['score']}) ===\n{match['content']}")
    return "\n\n".join(result)


# ---------------------------------------------------------------------------
# Tools: Read / List
# ---------------------------------------------------------------------------


@tool
def read_kb_sops() -> str:
    """List all available Standard Operating Procedures in the Knowledge Base.

    Returns:
        List of SOP files with their resource_type and issue_pattern metadata.
    """
    settings.ensure_dirs()
    sops_dir = settings.sops_dir
    sops = []

    for sop_file in sorted(sops_dir.glob("*.md")):
        try:
            content = sop_file.read_text()
            metadata, _ = _parse_frontmatter(content)
            sops.append({
                "file": sop_file.name,
                "resource_type": metadata.get("resource_type", "unknown"),
                "issue_pattern": metadata.get("issue_pattern", "unknown"),
                "severity": metadata.get("severity", "unknown"),
                "keywords": metadata.get("keywords", []),
            })
        except Exception as e:
            sops.append({"file": sop_file.name, "error": str(e)})

    if not sops:
        return "No SOPs found in Knowledge Base."

    return json.dumps(sops, indent=2)


# ---------------------------------------------------------------------------
# Tools: Write
# ---------------------------------------------------------------------------


@tool
def write_kb_case(filename: str, content: str) -> str:
    """Write a case study to the Knowledge Base.

    After saving the markdown file, attempts to parse it into a CaseStudy,
    embed the symptom and root cause text, and index vectors for future
    semantic search.

    Args:
        filename: Filename for the case (e.g., 'ec2-cpu-spike-2024-01.md')
        content: Full markdown content including frontmatter

    Returns:
        Confirmation with file path and embedding status.
    """
    settings.ensure_dirs()
    filepath = settings.cases_dir / filename

    try:
        filepath.write_text(content)
    except Exception as e:
        return f"Error writing case study: {e}"

    # Try to embed and index the case
    embed_status = _embed_and_index_from_markdown(content, filename)
    return f"Case study saved to {filepath}. {embed_status}"


def _embed_and_index_from_markdown(content: str, filename: str) -> str:
    """Parse markdown case, embed, and index vectors. Returns status string."""
    try:
        from agenticops.kb.case_study import CaseStudy
        from agenticops.kb.embeddings import get_embedding_client
        from agenticops.kb.vector_store import VectorRecord, get_vector_store

        case = CaseStudy.from_markdown(content)
        client = get_embedding_client()

        if client.dimension == 0:
            return "Embeddings disabled."

        indexed = 0
        store = get_vector_store()
        case_id = case.case_id or Path(filename).stem
        resource_type = case.meta.resource_type.upper()

        # Embed symptom text
        symptom_text = case.embedding_inputs.symptom_vector_text
        if symptom_text:
            vec = client.embed(symptom_text)
            if vec is not None:
                store.upsert(VectorRecord(
                    case_id=case_id,
                    field_name="symptom",
                    vector=vec,
                    resource_type=resource_type,
                    metadata={"efficiency_score": case.lessons_learned.efficiency_score,
                              "verified": str(case.verified).lower()},
                ))
                indexed += 1

        # Embed root cause text
        rc_text = case.embedding_inputs.root_cause_vector_text
        if rc_text:
            vec = client.embed(rc_text)
            if vec is not None:
                store.upsert(VectorRecord(
                    case_id=case_id,
                    field_name="root_cause",
                    vector=vec,
                    resource_type=resource_type,
                    metadata={"efficiency_score": case.lessons_learned.efficiency_score,
                              "verified": str(case.verified).lower()},
                ))
                indexed += 1

        return f"Indexed {indexed} vector(s)." if indexed else "No vectors indexed."
    except Exception as e:
        logger.warning("Embed+index failed for %s: %s", filename, e)
        return f"Embedding skipped: {e}"


@tool
def write_kb_sop(filename: str, content: str) -> str:
    """Write a Standard Operating Procedure to the Knowledge Base.

    Args:
        filename: Filename for the SOP (e.g., 'eks-oom-killed.md')
        content: Full markdown content including frontmatter

    Returns:
        Confirmation with file path.
    """
    settings.ensure_dirs()
    filepath = settings.sops_dir / filename

    try:
        filepath.write_text(content)
        return f"SOP saved to {filepath}"
    except Exception as e:
        return f"Error writing SOP: {e}"


# ---------------------------------------------------------------------------
# Tools: Distillation pipeline
# ---------------------------------------------------------------------------


@tool
def distill_case_study(health_issue_id: int) -> str:
    """Distill a resolved HealthIssue + RCA into a structured Case Study.

    Pipeline: Capture (load issue + RCA) -> Distill (LLM) -> Embed -> Index.

    1. Load HealthIssue + RCAResult from DB
    2. Build raw context (symptoms, hypothesis, actions, results)
    3. Call Bedrock LLM with distillation prompt
    4. Parse LLM JSON into CaseStudy dataclass
    5. Write markdown to data/knowledge_base/cases/
    6. Embed symptom + root_cause text via Titan
    7. Store vectors in case_vectors table
    8. Save CaseStudyRecord metadata

    Args:
        health_issue_id: The HealthIssue ID to distill.

    Returns:
        Confirmation with case_id, file path, and embedding status.
    """
    try:
        # 1. Load issue + RCA
        context = _build_distillation_context(health_issue_id)
        if context is None:
            return f"Cannot distill: HealthIssue #{health_issue_id} not found or has no RCA."

        # 2-3. LLM distillation
        distilled = _llm_distill(context)
        if distilled is None:
            return f"Distillation failed for HealthIssue #{health_issue_id}."

        # 4. Parse into CaseStudy
        case = _parse_distilled_case(distilled, context)

        # 5. Write markdown
        filename = f"{case.case_id}.md"
        filepath = settings.cases_dir / filename
        settings.ensure_dirs()
        filepath.write_text(case.to_markdown())

        # 6-7. Embed and index
        embed_status = _embed_and_index_case(case)

        # 8. Save DB record
        _save_case_record(case, str(filepath))

        return (
            f"Case study distilled: {case.case_id}\n"
            f"File: {filepath}\n"
            f"Severity: {case.meta.severity}\n"
            f"Efficiency: {case.lessons_learned.efficiency_score}\n"
            f"{embed_status}"
        )
    except Exception as e:
        logger.exception("Distillation failed for HealthIssue #%d", health_issue_id)
        return f"Distillation error: {e}"


# ---------------------------------------------------------------------------
# Distillation helpers
# ---------------------------------------------------------------------------


def _build_distillation_context(health_issue_id: int) -> Optional[dict]:
    """Load HealthIssue + RCAResult and build raw context for distillation."""
    from agenticops.models import HealthIssue, RCAResult, get_db_session

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            return None

        rca = (
            session.query(RCAResult)
            .filter_by(health_issue_id=health_issue_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )
        if not rca:
            return None

        return {
            "issue_id": issue.id,
            "resource_id": issue.resource_id,
            "resource_type": _infer_resource_type(issue.resource_id),
            "severity": issue.severity,
            "title": issue.title,
            "description": issue.description,
            "source": issue.source,
            "status": issue.status,
            "detected_at": issue.detected_at.isoformat() if issue.detected_at else "",
            "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else "",
            "metric_data": issue.metric_data,
            "related_changes": issue.related_changes,
            "rca_id": rca.id,
            "root_cause": rca.root_cause,
            "confidence": rca.confidence,
            "contributing_factors": rca.contributing_factors,
            "recommendations": rca.recommendations,
            "fix_plan": rca.fix_plan,
            "fix_risk_level": rca.fix_risk_level,
            "sop_used": rca.sop_used,
            "similar_cases": rca.similar_cases,
        }


def _infer_resource_type(resource_id: str) -> str:
    """Infer AWS resource type from resource ID prefix."""
    prefixes = {
        "i-": "EC2",
        "arn:aws:lambda": "Lambda",
        "arn:aws:rds": "RDS",
        "arn:aws:ecs": "ECS",
        "arn:aws:eks": "EKS",
        "arn:aws:s3": "S3",
        "arn:aws:dynamodb": "DynamoDB",
        "arn:aws:sqs": "SQS",
        "arn:aws:sns": "SNS",
    }
    for prefix, rtype in prefixes.items():
        if resource_id.startswith(prefix):
            return rtype
    return "Unknown"


DISTILLATION_PROMPT = """You are an SRE knowledge engineer. Distill the following incident data into a structured case study.

INPUT:
{context}

OUTPUT a JSON object with exactly these fields:
{{
  "title": "concise title describing the incident pattern (no specific resource IDs)",
  "symptoms": "generalized symptom description (replace specific IDs with <resource_id>, dates with <date>)",
  "root_cause": "abstracted root cause explanation",
  "immediate_action": "what was done to fix it immediately",
  "long_term_fix": "preventive measures for the future",
  "verification_method": "how to verify the fix worked",
  "what_failed": "what process/monitoring failed to catch this earlier",
  "why_missed": "why existing monitoring/alerts missed this",
  "efficiency_score": <float 0.0-1.0 based on: 0.9+ = detected and fixed automatically, 0.7-0.8 = quick manual fix, 0.5-0.6 = took investigation, 0.3-0.4 = prolonged incident, <0.3 = significant impact>,
  "tags": ["tag1", "tag2", "tag3"]
}}

RULES:
- De-noise: remove account IDs, specific timestamps, instance IDs
- Abstract: replace specific values with generic descriptions
- Summarize: focus on the pattern, not the specific incident
- Score honestly based on the investigation efficiency
- Return ONLY valid JSON, no markdown code fences"""


def _llm_distill(context: dict) -> Optional[dict]:
    """Call Bedrock LLM to distill context into structured case study fields."""
    try:
        import boto3

        client = boto3.client(
            "bedrock-runtime", region_name=settings.bedrock_region
        )
        prompt = DISTILLATION_PROMPT.format(context=json.dumps(context, indent=2, default=str))

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp = client.invoke_model(
            modelId=settings.bedrock_model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        result = json.loads(resp["body"].read())
        text = result.get("content", [{}])[0].get("text", "")

        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        return json.loads(text)
    except Exception as e:
        logger.warning("LLM distillation failed: %s", e)
        return None


def _parse_distilled_case(distilled: dict, context: dict) -> "CaseStudy":
    """Convert LLM-distilled dict + original context into a CaseStudy."""
    from agenticops.kb.case_study import (
        CaseStudy,
        CaseStudyMeta,
        CaseStudyStatus,
        EmbeddingInputs,
        LessonsLearned,
        Resolution,
    )

    now = datetime.utcnow()
    case_id = f"case_{now.strftime('%Y%m%d')}_{context['issue_id']:03d}"

    tags = distilled.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    meta = CaseStudyMeta(
        resource_type=context.get("resource_type", "Unknown"),
        severity=context.get("severity", "medium"),
        region="",
        source_issue_id=context.get("issue_id"),
        source_rca_id=context.get("rca_id"),
        created_at=now.strftime("%Y-%m-%d"),
        tags=tags,
    )

    embedding_inputs = EmbeddingInputs(
        symptom_vector_text=distilled.get("symptoms", ""),
        root_cause_vector_text=distilled.get("root_cause", ""),
    )

    resolution = Resolution(
        immediate_action=distilled.get("immediate_action", ""),
        long_term_fix=distilled.get("long_term_fix", ""),
        verification_method=distilled.get("verification_method", ""),
    )

    efficiency = 0.5
    try:
        efficiency = float(distilled.get("efficiency_score", 0.5))
        efficiency = max(0.0, min(1.0, efficiency))
    except (ValueError, TypeError):
        pass

    lessons = LessonsLearned(
        what_failed=distilled.get("what_failed", ""),
        why_missed=distilled.get("why_missed", ""),
        efficiency_score=efficiency,
    )

    return CaseStudy(
        case_id=case_id,
        title=distilled.get("title", context.get("title", "Untitled Case")),
        meta=meta,
        embedding_inputs=embedding_inputs,
        resolution=resolution,
        lessons_learned=lessons,
        status=CaseStudyStatus.PENDING_REVIEW,
        verified=False,
        reuse_count=0,
        symptoms=distilled.get("symptoms", ""),
        root_cause=distilled.get("root_cause", ""),
        prevention=distilled.get("long_term_fix", ""),
    )


def _embed_and_index_case(case: "CaseStudy") -> str:
    """Embed symptom + root_cause vectors and store in vector store."""
    try:
        from agenticops.kb.embeddings import get_embedding_client
        from agenticops.kb.vector_store import VectorRecord, get_vector_store

        client = get_embedding_client()
        if client.dimension == 0:
            return "Embeddings disabled."

        store = get_vector_store()
        resource_type = case.meta.resource_type.upper()
        meta = {
            "efficiency_score": case.lessons_learned.efficiency_score,
            "verified": str(case.verified).lower(),
        }
        indexed = 0

        for field_name, text in [
            ("symptom", case.embedding_inputs.symptom_vector_text),
            ("root_cause", case.embedding_inputs.root_cause_vector_text),
        ]:
            if not text:
                continue
            vec = client.embed(text)
            if vec is not None:
                store.upsert(VectorRecord(
                    case_id=case.case_id,
                    field_name=field_name,
                    vector=vec,
                    resource_type=resource_type,
                    metadata=meta,
                ))
                indexed += 1

        return f"Indexed {indexed} vector(s)." if indexed else "No vectors indexed."
    except Exception as e:
        logger.warning("Embed+index failed for %s: %s", case.case_id, e)
        return f"Embedding skipped: {e}"


def _save_case_record(case: "CaseStudy", file_path: str) -> None:
    """Persist CaseStudyRecord to the database."""
    try:
        from agenticops.models import CaseStudyRecord, get_db_session

        with get_db_session() as session:
            existing = (
                session.query(CaseStudyRecord)
                .filter_by(case_id=case.case_id)
                .first()
            )
            if existing:
                existing.resource_type = case.meta.resource_type
                existing.severity = case.meta.severity
                existing.status = case.status.value
                existing.verified = case.verified
                existing.efficiency_score = case.lessons_learned.efficiency_score
                existing.file_path = file_path
            else:
                record = CaseStudyRecord(
                    case_id=case.case_id,
                    resource_type=case.meta.resource_type,
                    severity=case.meta.severity,
                    status=case.status.value,
                    verified=case.verified,
                    reuse_count=0,
                    source_issue_id=case.meta.source_issue_id,
                    source_rca_id=case.meta.source_rca_id,
                    efficiency_score=case.lessons_learned.efficiency_score,
                    file_path=file_path,
                )
                session.add(record)
    except Exception as e:
        logger.warning("Failed to save CaseStudyRecord for %s: %s", case.case_id, e)
