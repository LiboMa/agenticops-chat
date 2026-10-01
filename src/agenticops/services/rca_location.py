"""Root-cause location validation for save_rca_result (MVP-2.6.1 Plan C, spec §3.C.3).

The RCA agent may name up to three ranked candidate resources and a causal path from the root cause to
the symptom's anchor. Everything is checked against the database, fail-closed: a candidate that is not
an inventory row of the issue's own account is dropped; so is an evidence label that is not one of this
RCA's evidence items; one path edge that is not a rule/observed relation of the checked build, between two
inventory rows of the issue's account, drops the whole path; a given build that is not a published
graph build is replaced by the published one. The stored location keeps only what survived, with both ends' names inline, so it reads the
same after the build is pruned. It is observed only — the critic, the confidence gate and auto-fix never
read it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, func

from agenticops.galaxy.models import GalaxyBuild, ResourceRelation
from agenticops.graph import query_service as qs
from agenticops.models import CloudResource, HealthIssue, RCAResult
from agenticops.services import identity_resolver as ir

VALID, PARTIAL, INVALID, ABSENT = "valid", "partial", "invalid", "absent"
LOCATION_STATUSES = (VALID, PARTIAL, INVALID, ABSENT)
LOCATION_VERDICTS = ("correct", "partial", "incorrect")
MAX_CANDIDATES = 3
PATH_PROVENANCE = frozenset({"rule", "observed"})
_LABEL = re.compile(r"E(\d+)")
_INT64 = 2 ** 63


def _int(value) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool) and -_INT64 <= value < _INT64:
        return value
    return None  # a bool, a non-int, or an id no database column can hold


def _labels(value, evidence_count: int, where: str, dropped: list) -> list[str]:
    """The E<n> labels that name one of this RCA's evidence items (1-based); the rest are dropped."""
    if value is None:
        return []
    if not isinstance(value, list):
        dropped.append(f"{where}: not a list")
        return []
    out = []
    for item in value:
        m = _LABEL.fullmatch(str(item).strip().upper())
        if m and 1 <= int(m.group(1)) <= evidence_count:
            out.append(f"E{int(m.group(1))}")
        else:
            dropped.append(f"{where}: {item!r} is not an evidence item of this RCA")
    return out


def _candidates(session, issue: HealthIssue, raw, evidence_count: int, dropped: list) -> list[dict]:
    if not isinstance(raw, list):
        if raw is not None:
            dropped.append("candidates: not a list")
        return []
    out, ranks, refs = [], set(), set()
    for c in raw:
        if not isinstance(c, dict):
            dropped.append(f"candidate {c!r}: not an object")
            continue
        ref, rank = _int(c.get("ref")), _int(c.get("rank"))
        if ref is None:
            dropped.append(f"candidate {c.get('ref')!r}: ref is not a resource id")
            continue
        if rank is None or not 1 <= rank <= MAX_CANDIDATES or rank in ranks:
            dropped.append(f"candidate {ref}: rank {c.get('rank')!r} is not a free rank 1..{MAX_CANDIDATES}")
            continue
        if ref in refs:
            dropped.append(f"candidate {ref}: already a candidate")
            continue
        row = session.get(CloudResource, ref)
        if row is None:
            dropped.append(f"candidate {ref}: no such resource")
            continue
        if issue.account_id is None or row.account_id != issue.account_id:
            dropped.append(f"candidate {ref}: not in the issue's account")
            continue
        ranks.add(rank)
        refs.add(ref)
        out.append({"ref": ref, "rank": rank, "type": row.resource_type, "name": row.name or "",
                    "resource_id": row.resource_id,
                    "supporting": _labels(c.get("supporting"), evidence_count, f"candidate {ref} supporting",
                                          dropped),
                    "refuting": _labels(c.get("refuting"), evidence_count, f"candidate {ref} refuting", dropped)})
    return sorted(out, key=lambda c: c["rank"])


def _path(session, issue: HealthIssue, raw, build_id: Optional[int], dropped: list) -> list[dict]:
    """The whole path, or [] when any edge fails (spec: one bad edge drops the path)."""
    if not raw:
        return []
    if not isinstance(raw, list):
        dropped.append("path: not a list")
        return []
    # A legacy issue with a ref but no anchor_status counts as anchored, as in the topology evidence.
    if (issue.anchor_status or (ir.ANCHORED if issue.resource_ref else ir.UNANCHORED)) != ir.ANCHORED \
            or not issue.resource_ref:
        dropped.append("path: the issue is not anchored, so it has no path")
        return []
    if issue.account_id is None:
        dropped.append("path: the issue has no account, so it has no path")
        return []
    if build_id is None:
        dropped.append("path: no published graph build to check it against")
        return []
    out = []
    for e in raw:
        src, dst = (_int(e.get("src_ref")), _int(e.get("dst_ref"))) if isinstance(e, dict) else (None, None)
        rtype = e.get("relation_type") if isinstance(e, dict) else None
        rel, ends = None, {}
        if src is not None and dst is not None and isinstance(rtype, str):
            rel = session.query(ResourceRelation).filter_by(build_id=build_id, src_ref=src, dst_ref=dst,
                                                            relation_type=rtype).first()
            # Relation endpoints carry no foreign key: both ends must still be the issue's own inventory rows.
            ends = {r.id: (r.name or "", r.account_id)
                    for r in session.query(CloudResource).filter(CloudResource.id.in_([src, dst]))}
        if rel is None or rel.provenance not in PATH_PROVENANCE or rel.account_id != issue.account_id \
                or any(ends.get(ref, (None, None))[1] != issue.account_id for ref in (src, dst)):
            dropped.append(f"path: edge {e!r} is not a rule/observed relation of build {build_id} in the "
                           "issue's account")
            return []
        out.append({"src_ref": src, "src_name": ends[src][0], "dst_ref": dst, "dst_name": ends[dst][0],
                    "relation_type": rtype, "provenance": rel.provenance})
    return out


def validate_location(session, issue: HealthIssue, location, evidence_count: int) -> tuple[Optional[dict], str,
                                                                                            Optional[int]]:
    """(stored location, location_status, location_build_id) for one save_rca_result call.

    `location` is the tool argument: a JSON string or an already-parsed object. Nothing given → absent.
    """
    if isinstance(location, str):
        if not location.strip():
            return None, ABSENT, None
        try:
            location = json.loads(location)
        except json.JSONDecodeError:
            return {"candidates": [], "path": [], "dropped": ["location: not valid JSON"]}, INVALID, None
    if location is None or location == {}:
        return None, ABSENT, None
    if not isinstance(location, dict):
        return {"candidates": [], "path": [], "dropped": ["location: not an object"]}, INVALID, None
    dropped: list[str] = []
    build_id = _int(location.get("build_id"))
    if build_id is not None and session.query(GalaxyBuild.id).filter(
            GalaxyBuild.id == build_id, GalaxyBuild.rules_published_at.isnot(None)).first() is None:
        dropped.append(f"build_id {build_id}: not a published graph build")
        build_id = None
    if build_id is None:
        build_id = qs.published_build_id(session)
    candidates = _candidates(session, issue, location.get("candidates"), evidence_count, dropped)
    path = _path(session, issue, location.get("path"), build_id, dropped)
    status = INVALID if not candidates else PARTIAL if dropped else VALID
    return {"candidates": candidates, "path": path, "dropped": dropped}, status, build_id


def location_stats(session, days: int) -> dict:
    """GET /api/rca/location-stats (spec §3.C.4): the RCAs created in the last `days` days — their location
    status and the human verdicts on their location — and how the issues detected in that window were
    anchored. top1 = correct / judged (a "partial" verdict is not a top-1 hit); anchoring_rate = (anchored +
    account_level) / issues that name a resource_id. Both are None when there is nothing to divide by.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    location_counts = dict.fromkeys(LOCATION_STATUSES, 0)
    verdicts = dict.fromkeys(LOCATION_VERDICTS, 0)
    for status, verdict, n in (session.query(RCAResult.location_status, RCAResult.location_verdict,
                                             func.count(RCAResult.id))
                               .filter(RCAResult.created_at >= since)
                               .group_by(RCAResult.location_status, RCAResult.location_verdict)):
        location_counts[status if status in location_counts else ABSENT] += n
        if verdict in verdicts:
            verdicts[verdict] += n

    anchor_counts = dict.fromkeys((ir.ANCHORED, ir.ACCOUNT_LEVEL, ir.AMBIGUOUS, ir.UNANCHORED), 0)
    named, anchored_named = 0, 0
    has_ref = HealthIssue.resource_ref.isnot(None)
    has_id = case((func.coalesce(HealthIssue.resource_id, "") != "", 1), else_=0)
    for status, ref, with_id, n in (session.query(HealthIssue.anchor_status, has_ref, has_id,
                                                  func.count(HealthIssue.id))
                                    .filter(HealthIssue.detected_at >= since)
                                    .group_by(HealthIssue.anchor_status, has_ref, has_id)):
        # A legacy issue without anchor_status counts as anchored when it has a ref, as in the topology evidence.
        status = status or (ir.ANCHORED if ref else ir.UNANCHORED)
        anchor_counts[status] = anchor_counts.get(status, 0) + n
        if with_id:
            named += n
            anchored_named += n if status in (ir.ANCHORED, ir.ACCOUNT_LEVEL) else 0

    judged = sum(verdicts.values())
    return {"days": days,
            "top1": round(verdicts["correct"] / judged, 4) if judged else None,
            "judged": judged,
            "anchoring_rate": round(anchored_named / named, 4) if named else None,
            "issues_with_resource_id": named,
            "anchor_status_counts": anchor_counts,
            "location_status_counts": location_counts}
