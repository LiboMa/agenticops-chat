"""Knowledge Base tools for Strands agents.

Local Markdown + JSON index for SOPs, cases, and patterns.
"""

import json
import logging
from pathlib import Path

from strands import tool

from agenticops.config import settings

logger = logging.getLogger(__name__)


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


@tool
def search_sops(resource_type: str, issue_pattern: str) -> str:
    """Search Knowledge Base for matching Standard Operating Procedures.

    Searches SOP markdown files by resource_type and issue_pattern keywords
    in the frontmatter metadata.

    Args:
        resource_type: AWS resource type (EC2, RDS, Lambda, etc.)
        issue_pattern: Issue pattern keywords (e.g., 'cpu high', 'connection timeout')

    Returns:
        Matching SOP content or 'No SOP found' message.
    """
    settings.ensure_dirs()
    sops_dir = settings.sops_dir
    matches = []
    keywords = issue_pattern.lower().split()

    for sop_file in sops_dir.glob("*.md"):
        try:
            content = sop_file.read_text()
            metadata, body = _parse_frontmatter(content)

            # Match by resource_type
            sop_type = str(metadata.get("resource_type", "")).upper()
            if resource_type.upper() != sop_type and sop_type != "":
                if resource_type.upper() not in sop_type:
                    continue

            # Match by keywords in frontmatter keywords or issue_pattern
            sop_keywords = metadata.get("keywords", [])
            if isinstance(sop_keywords, str):
                sop_keywords = [sop_keywords]
            sop_pattern = str(metadata.get("issue_pattern", "")).lower()

            # Check keyword overlap
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
            logger.warning(f"Error reading SOP {sop_file}: {e}")

    if not matches:
        return f"No SOP found for resource_type={resource_type}, pattern='{issue_pattern}'."

    # Return the best match (first) with full content
    result = []
    for match in matches[:3]:
        result.append(
            f"=== SOP: {match['file']} ===\n{match['content']}"
        )

    return "\n\n".join(result)


@tool
def search_similar_cases(
    resource_type: str, issue_pattern: str, limit: int = 3
) -> str:
    """Search Knowledge Base for similar historical cases.

    Args:
        resource_type: AWS resource type (EC2, RDS, Lambda, etc.)
        issue_pattern: Issue pattern keywords
        limit: Maximum number of cases to return

    Returns:
        Matching case studies or 'No cases found' message.
    """
    settings.ensure_dirs()
    cases_dir = settings.cases_dir
    matches = []
    keywords = issue_pattern.lower().split()

    for case_file in cases_dir.glob("*.md"):
        try:
            content = case_file.read_text()
            metadata, body = _parse_frontmatter(content)

            case_type = str(metadata.get("resource_type", "")).upper()
            file_text = content.lower()

            # Simple keyword matching
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
            logger.warning(f"Error reading case {case_file}: {e}")

    if not matches:
        return f"No similar cases found for resource_type={resource_type}, pattern='{issue_pattern}'."

    # Sort by relevance score
    matches.sort(key=lambda x: x["score"], reverse=True)

    result = []
    for match in matches[:limit]:
        result.append(f"=== Case: {match['file']} (score: {match['score']}) ===\n{match['content']}")

    return "\n\n".join(result)


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


@tool
def write_kb_case(filename: str, content: str) -> str:
    """Write a case study to the Knowledge Base.

    Args:
        filename: Filename for the case (e.g., 'ec2-cpu-spike-2024-01.md')
        content: Full markdown content including frontmatter

    Returns:
        Confirmation with file path.
    """
    settings.ensure_dirs()
    filepath = settings.cases_dir / filename

    try:
        filepath.write_text(content)
        return f"Case study saved to {filepath}"
    except Exception as e:
        return f"Error writing case study: {e}"


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
