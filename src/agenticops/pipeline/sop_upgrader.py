"""SOP Upgrader — generate new SOPs or merge learnings into existing ones.

Uses Bedrock LLM to produce structured markdown SOPs with YAML frontmatter.
"""

import json
import logging
from datetime import datetime

from agenticops.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

NEW_SOP_PROMPT = """You are an SRE documentation engineer. Generate a Standard Operating Procedure (SOP) for the following issue pattern.

CASE DATA:
{case_data}

Generate a markdown SOP with YAML frontmatter. Format:

---
resource_type: {resource_type}
issue_pattern: {issue_pattern}
severity: {severity}
keywords: [{keywords}]
created: {date}
updated: {date}
---

# {title}

## Symptoms
(Observable indicators that this issue is occurring)

## Diagnosis Steps
(Step-by-step commands/checks to confirm the issue)

## Fix Procedure
(Ordered steps to resolve, with specific AWS CLI commands where applicable)

## Rollback
(How to undo the fix if something goes wrong)

## Post-Verification
(How to confirm the fix worked)

## Prevention
(Monitoring/alerts/config changes to prevent recurrence)

## Related
(Links to related SOPs, AWS docs, or internal resources)

RULES:
- Be specific with AWS CLI commands (include --query for concise output)
- Use generic placeholders like <instance-id>, <cluster-name> instead of specific IDs
- Focus on the repeatable pattern, not the specific incident
- Include estimated time for each step
- Return ONLY the markdown (with frontmatter), no extra commentary"""


UPGRADE_SOP_PROMPT = """You are an SRE documentation engineer. An existing SOP needs to be updated with learnings from a new incident.

EXISTING SOP:
{existing_sop}

NEW CASE LEARNINGS:
{case_data}

Merge the new learnings into the existing SOP. Specifically:
1. Add any NEW symptoms not already covered
2. Update diagnosis steps if the new case revealed a faster/better approach
3. Update fix procedure if the new case found improvements
4. Add new rollback steps if needed
5. Update prevention section with any new monitoring recommendations
6. Keep ALL existing content that is still valid — do NOT remove information
7. Update the "updated" date in frontmatter to {date}

Return ONLY the complete updated markdown SOP (with frontmatter), no extra commentary.
The output must start with --- (frontmatter delimiter)."""


def generate_new_sop(case_data: dict) -> str:
    """Generate a new SOP from a resolved case using Bedrock LLM.

    Args:
        case_data: Dict with keys: resource_type, issue_pattern, severity,
                   title, symptoms, root_cause, fix_steps, verification_steps,
                   rollback_plan, prevention.

    Returns:
        Complete SOP markdown string with frontmatter.
    """
    resource_type = case_data.get("resource_type", "Unknown")
    issue_pattern = case_data.get("issue_pattern", "unknown issue")
    severity = case_data.get("severity", "medium")
    title = case_data.get("title", "Untitled SOP")
    now = datetime.utcnow().strftime("%Y-%m-%d")

    # Build keywords from available data
    keywords = _extract_keywords(case_data)

    prompt = NEW_SOP_PROMPT.format(
        case_data=json.dumps(case_data, indent=2, default=str),
        resource_type=resource_type,
        issue_pattern=issue_pattern,
        severity=severity,
        keywords=", ".join(keywords),
        date=now,
        title=title,
    )

    result = _call_llm(prompt)
    if result is None:
        # Fallback: generate a minimal SOP without LLM
        return _generate_fallback_sop(case_data, now)

    return result


def upgrade_existing_sop(existing_sop_content: str, case_data: dict) -> str:
    """Merge new case learnings into an existing SOP using Bedrock LLM.

    Args:
        existing_sop_content: Full markdown content of the existing SOP.
        case_data: Dict with new case learnings (same schema as generate_new_sop).

    Returns:
        Updated SOP markdown string with frontmatter.
    """
    now = datetime.utcnow().strftime("%Y-%m-%d")

    prompt = UPGRADE_SOP_PROMPT.format(
        existing_sop=existing_sop_content,
        case_data=json.dumps(case_data, indent=2, default=str),
        date=now,
    )

    result = _call_llm(prompt)
    if result is None:
        # On failure, return the original unchanged
        logger.warning("SOP upgrade LLM call failed, returning original SOP")
        return existing_sop_content

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call_llm(prompt: str) -> str | None:
    """Call Bedrock LLM with the given prompt. Returns text or None."""
    try:
        import boto3

        client = boto3.client(
            "bedrock-runtime", region_name=settings.bedrock_region
        )
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
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

        return text.strip()
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


def _extract_keywords(case_data: dict) -> list[str]:
    """Extract keywords from case data for SOP frontmatter."""
    keywords = set()
    rt = case_data.get("resource_type", "")
    if rt:
        keywords.add(rt.lower())

    # Extract from issue pattern and root cause
    for field in ("issue_pattern", "root_cause", "title"):
        text = case_data.get(field, "")
        if text:
            for word in text.lower().split():
                word = word.strip(".,;:!?()[]{}\"'")
                if len(word) > 3 and word not in ("the", "and", "for", "was", "with", "that", "this"):
                    keywords.add(word)
                if len(keywords) >= 8:
                    break

    return sorted(keywords)[:8]


def _generate_fallback_sop(case_data: dict, date: str) -> str:
    """Generate a minimal SOP without LLM (fallback)."""
    resource_type = case_data.get("resource_type", "Unknown")
    issue_pattern = case_data.get("issue_pattern", "unknown issue")
    severity = case_data.get("severity", "medium")
    title = case_data.get("title", f"{resource_type} - {issue_pattern}")

    return f"""---
resource_type: {resource_type}
issue_pattern: {issue_pattern}
severity: {severity}
keywords: [{resource_type.lower()}, {issue_pattern.replace(' ', ', ')}]
created: {date}
updated: {date}
---

# {title}

## Symptoms
{case_data.get("symptoms", "See case data for symptom details.")}

## Diagnosis Steps
1. Check CloudWatch alarms and metrics for the affected resource.
2. Review CloudTrail events for recent changes.
3. Inspect resource configuration and status.

## Fix Procedure
{case_data.get("fix_steps", "See case data for fix steps.")}

## Rollback
{case_data.get("rollback_plan", "Reverse the fix steps in reverse order.")}

## Post-Verification
{case_data.get("verification_steps", "Verify the resource is healthy and metrics are normal.")}

## Prevention
{case_data.get("prevention", "Add appropriate CloudWatch alarms and monitoring.")}
"""
