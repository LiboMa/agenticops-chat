"""Deterministic CIS scoring. No randomness, no time dependence, no LLM.

overall_score = passed_controls / total_controls * 100
category_score[c] = passed_in_c / total_in_c * 100
Reachability annotations DO NOT enter scoring — they only reorder display.
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


@dataclass
class ScoreResult:
    overall_score: float
    category_scores: dict[str, float] = field(default_factory=dict)
    cis_results: dict[str, str] = field(default_factory=dict)  # control_id -> pass|fail
    metrics: dict[str, int] = field(default_factory=dict)      # category -> raw finding count


def score(findings) -> ScoreResult:
    failed_controls = {f.control_id for f in findings if f.control_id in CIS_CONTROLS}

    cis_results = {cid: ("fail" if cid in failed_controls else "pass") for cid in CIS_CONTROLS}

    categories = sorted({cat for cat, _ in CIS_CONTROLS.values()})
    category_scores: dict[str, float] = {}
    for cat in categories:
        ctrls = [cid for cid, (c, _) in CIS_CONTROLS.items() if c == cat]
        passed = sum(1 for cid in ctrls if cis_results[cid] == "pass")
        category_scores[cat] = passed / len(ctrls) * 100.0 if ctrls else 100.0

    total = len(CIS_CONTROLS)
    passed_total = sum(1 for v in cis_results.values() if v == "pass")
    overall = passed_total / total * 100.0 if total else 100.0

    metrics: dict[str, int] = {}
    for f in findings:
        metrics[f.category] = metrics.get(f.category, 0) + 1

    return ScoreResult(overall_score=overall, category_scores=category_scores,
                       cis_results=cis_results, metrics=metrics)
