"""Deterministic CIS scoring. No randomness, no time dependence, no LLM.

overall_score = passed_controls / total_controls * 100
category_score[c] = passed_in_c / total_in_c * 100
Reachability annotations DO NOT enter scoring — they only reorder display.

Collection health (MVP-2.9.0 N20): a control is decided by ONE collection source (CONTROL_SOURCE). When that source
could not be read the control is `undetermined` — not a pass — unless a violation was seen before it failed (a
violation that was seen is a fact). A score that no readable source stands behind is None, not a number: the overall
score when every source failed, a category's when every source of its controls failed. Otherwise the formulas above
hold with `undetermined` counted as not passed, so missing data can lower a score and never raise it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# P1 control subset (per spec §10: not the full CIS benchmark).
# {control_id: (category, human description)}
CIS_CONTROLS: dict[str, tuple[str, str]] = {
    "cis-1.3":  ("iam",     "No IAM access key older than 90 days"),
    "cis-1.4":  ("iam",     "No root account access key"),
    "cis-1.10": ("iam",     "MFA enabled for all console users"),
    "cis-4.1":  ("network", "No unrestricted ingress to port 22 (SSH)"),
    "cis-4.2":  ("network", "No unrestricted ingress to port 3389 (RDP)"),
    "cis-2.1":  ("data",    "S3 buckets block public access"),
    "cis-enc":  ("data",    "EBS volumes encrypted at rest"),
    "cis-3.1":  ("logging", "CloudTrail multi-region logging enabled"),
}


# The collection source that decides each control; security/collectors reports its health under these names.
CONTROL_SOURCE: dict[str, str] = {
    "cis-1.3": "iam", "cis-1.4": "iam", "cis-1.10": "iam",
    "cis-4.1": "network", "cis-4.2": "network",
    "cis-2.1": "s3", "cis-enc": "ebs",
    "cis-3.1": "logging",
}
SOURCES: frozenset[str] = frozenset(CONTROL_SOURCE.values())


@dataclass
class ScoreResult:
    overall_score: float | None                                 # None = every source failed: nothing to score
    category_scores: dict[str, float | None] = field(default_factory=dict)
    cis_results: dict[str, str] = field(default_factory=dict)  # control_id -> pass|fail|undetermined
    metrics: dict[str, int] = field(default_factory=dict)      # category -> raw finding count


def score(findings, failed_sources=()) -> ScoreResult:
    failed = frozenset(failed_sources)
    if failed - SOURCES:
        raise ValueError(f"unknown collection source(s): {sorted(failed - SOURCES)}")
    violated = {f.control_id for f in findings if f.control_id in CIS_CONTROLS}

    def result(cid: str) -> str:
        if cid in violated:
            return "fail"
        return "undetermined" if CONTROL_SOURCE[cid] in failed else "pass"

    cis_results = {cid: result(cid) for cid in CIS_CONTROLS}

    def rate(ctrls: list[str]) -> float | None:
        if not ctrls:
            return 100.0
        if all(CONTROL_SOURCE[cid] in failed for cid in ctrls):
            return None
        return sum(1 for cid in ctrls if cis_results[cid] == "pass") / len(ctrls) * 100.0

    categories = sorted({cat for cat, _ in CIS_CONTROLS.values()})
    category_scores = {cat: rate([cid for cid, (c, _) in CIS_CONTROLS.items() if c == cat]) for cat in categories}
    overall = rate(list(CIS_CONTROLS))

    metrics: dict[str, int] = {}
    for f in findings:
        metrics[f.category] = metrics.get(f.category, 0) + 1

    return ScoreResult(overall_score=overall, category_scores=category_scores,
                       cis_results=cis_results, metrics=metrics)
