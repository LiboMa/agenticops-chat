"""Evidence-grounded security recommendation advisor — the ONLY LLM component
in the security engine. Fail-closed end to end: ungrounded refs, critic
refutation, or any exception -> the recommendation is dropped, never guessed.
Recommendations never touch scoring (principle 4)."""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parse_recommendations(text: str) -> list[dict]:
    """First JSON array in the text (code fences tolerated); invalid -> []."""
    cleaned = re.sub(r"```(?:json)?", "", text or "")
    m = _ARRAY_RE.search(cleaned)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _grounded(recs: list[dict], resource_ids: set[str]) -> list[dict]:
    """Keep only recommendations whose every evidence ref is a resource we
    actually collected this round. Empty evidence -> dropped (must cite)."""
    out = []
    for r in recs:
        refs = r.get("evidence_refs") or []
        if refs and all(str(ref) in resource_ids for ref in refs):
            out.append(r)
        else:
            logger.info("advisor: dropped ungrounded recommendation %r", r.get("title"))
    return out


def _build_prompt(account: str, category_scores: dict, findings: list) -> str:
    low = sorted(c for c, s in category_scores.items() if s < 100.0)
    evidence = "\n".join(
        f"- {f.resource_id} — {f.raw_check} ({f.control_id}, {f.category})"
        for f in findings
    )
    return (
        "You are a cloud security advisor. Based ONLY on the evidence below, "
        f"produce prioritized remediation recommendations for account {account}.\n"
        f"Low-scoring categories: {', '.join(low)}\n"
        f"Evidence (the only resources you may cite):\n{evidence}\n\n"
        "Rules: every recommendation MUST cite resource ids from the evidence in "
        "evidence_refs, verbatim. Do not invent resources. Respond with ONLY a JSON "
        "array: [{\"category\": str, \"title\": str, \"detail\": str, "
        "\"evidence_refs\": [str], \"severity\": \"low|medium|high|critical\", "
        "\"confidence\": 0.0-1.0}]"
    )
