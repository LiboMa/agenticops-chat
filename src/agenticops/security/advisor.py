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


from agenticops.models import SecurityRecommendation, get_db_session

_VALID_SEVERITY = {"low", "medium", "high", "critical"}
_VALID_VERDICTS = {"supported", "weak", "refuted"}


def _critic(rec: dict, evidence: str, model: str) -> str | None:
    """One adversarial cheap-model pass. Returns a valid verdict or None."""
    from agenticops.services.signal_gate import _call_bedrock, _parse_verdict
    prompt = (
        "You are an adversarial reviewer. Given the evidence and a proposed security "
        "recommendation, judge whether the evidence actually supports it.\n"
        f"Evidence:\n{evidence}\n\nRecommendation:\n{json.dumps(rec)}\n\n"
        'Respond with ONLY JSON: {"verdict": "supported" | "weak" | "refuted", "notes": "..."}'
    )
    text, _ = _call_bedrock(prompt, model, max_tokens=300)
    parsed = _parse_verdict(text) or {}
    verdict = str(parsed.get("verdict", "")).lower()
    return verdict if verdict in _VALID_VERDICTS else None


def recommend(snapshot_id, account: str, score_result, findings: list) -> int:
    """Generate + persist grounded recommendations. Fail-closed: 0 rows on any error."""
    from agenticops.config import settings

    if not settings.security_advisor_enabled:
        return 0
    try:
        low = [c for c, s in score_result.category_scores.items() if s < 100.0]
        if not low or not findings:
            return 0
        model = settings.security_model_id or settings.bedrock_model_id_cheap
        from agenticops.services.signal_gate import _call_bedrock
        text, _ = _call_bedrock(_build_prompt(account, score_result.category_scores, findings),
                                model, max_tokens=1500)
        resource_ids = {f.resource_id for f in findings}
        recs = _grounded(_parse_recommendations(text), resource_ids)
        evidence = "\n".join(f"- {f.resource_id} — {f.raw_check} ({f.control_id})"
                             for f in findings)
        surviving: list[tuple[dict, str]] = []
        for r in recs:
            verdict = "supported"
            if settings.security_advisor_critic_enabled:
                verdict = _critic(r, evidence, model)
                if verdict is None or verdict == "refuted":
                    logger.info("advisor: critic dropped %r (verdict=%s)",
                                r.get("title"), verdict)
                    continue
            surviving.append((r, verdict))
        if not surviving:
            return 0
        with get_db_session() as session:
            for r, verdict in surviving:
                sev = str(r.get("severity", "medium")).lower()
                try:
                    conf = max(0.0, min(1.0, float(r.get("confidence", 0.5))))
                except (TypeError, ValueError):
                    conf = 0.5
                session.add(SecurityRecommendation(
                    snapshot_id=snapshot_id, account_id=account,
                    category=str(r.get("category", "other"))[:32],
                    title=str(r.get("title", ""))[:256],
                    detail=str(r.get("detail", "")),
                    evidence_refs=[str(x) for x in (r.get("evidence_refs") or [])],
                    severity=sev if sev in _VALID_SEVERITY else "medium",
                    critic_verdict=verdict, confidence=conf, status="open",
                ))
        return len(surviving)
    except Exception as e:
        logger.warning("advisor failed for %s (fail-closed, no rows): %s", account, e)
        return 0
