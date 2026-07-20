"""Signal Gate — unified noise/dedup judgment for ALL HealthIssue creation paths.

Every inbound event (webhook alert, agent detection, REST create, resolution
notice) becomes one Signal row (``alert_events``) with an auditable
disposition:

    promoted  → a genuinely new problem; HealthIssue created (+auto-RCA/notify)
    merged    → same problem as an existing issue; occurrence bumped, silent
    noise     → deterministic noise (flapping / excluded); NO issue, recoverable

Design rules (spec 2026-07-10-mvp-2.2.0):
- L1 deterministic rules first ($0, explainable) handle the bulk;
- L2 LLM runs ONLY in the gray zone and may only choose merge-vs-new —
  it can NEVER declare noise; uncertainty promotes (fail-open);
- every decision records rule/evidence into ``gate_evidence``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from agenticops.config import settings

logger = logging.getLogger(__name__)

# Canonical status sets (signal_gate is the single owner; metadata_tools aliases these)
ACTIVE_ISSUE_STATUSES = (
    "open", "investigating", "acknowledged",
    "root_cause_identified", "fix_planned",
    "fix_approved", "fix_executing", "fix_executed",
    "dismissed",
)
RESOURCE_DEDUP_STATUSES = ("open", "investigating", "acknowledged", "root_cause_identified")

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_MERGED_ALERTS_CAP = 50

ISSUE_TYPES: tuple[str, ...] = (
    "cpu_spike", "memory_pressure", "disk_full", "network_flap", "connectivity",
    "security_exposure", "security_finding", "iam_risk", "cert_expiry",
    "availability", "capacity_risk", "spof", "cost_anomaly", "config_drift",
    "performance_degradation", "other",
)

# Keyword table for deterministic classification — first hit wins.
# Order matters: specific families (exposure, flap) before generic ones.
_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cert_expiry", ("certificate", "cert expir", "acm", "tls expir", "ssl expir")),
    ("security_exposure", ("security group", "0.0.0.0/0", "open to the world",
                           "publicly accessible", "public access", "exposed", "port 22", "port 3389")),
    ("iam_risk", ("iam", "root account", "access key", "mfa", "credential")),
    ("security_finding", ("guardduty", "security hub", "securityhub", "inspector",
                          "cve", "vulnerabilit", "malware", "threat", "finding")),
    ("network_flap", ("flap", "link down", "link up", "bond", "intermittent")),
    ("connectivity", ("unreachable", "connection refused", "connection timeout", "timeout",
                      "no route", "nat gateway", "dns fail", "cannot connect", "connectivity")),
    ("disk_full", ("disk", "volume full", "filesystem", "no space", "storage full")),
    ("memory_pressure", ("memory", "oom", "out of memory", "swap")),
    ("cpu_spike", ("cpu", "load average")),
    ("capacity_risk", ("capacity", "quota", "limit reached", "throttl")),
    ("spof", ("single point of failure", "spof", "no redundancy")),
    ("cost_anomaly", ("cost", "billing", "spend")),
    ("config_drift", ("drift", "config change", "configuration change", "tag compliance", "noncompliant")),
    ("availability", ("5xx", "unhealthy target", "health check fail", "unavailable",
                      "downtime", "service down", "pod crash", "crashloop")),
    ("performance_degradation", ("latency", "slow quer", "p99", "response time", "degrad")),
)


def classify_issue_type(title: str, source: str = "", namespace: str = "",
                        metric: str = "", alertname: str = "") -> str:
    """Deterministic issue-type classification from alert text/metadata."""
    haystack = " ".join((title or "", namespace or "", metric or "", alertname or "")).lower()
    if not haystack.strip():
        return "other"
    for issue_type, keywords in _TYPE_KEYWORDS:
        if any(k in haystack for k in keywords):
            return issue_type
    return "other"


def _strip_digits(text: str) -> str:
    out = re.sub(r"\d+", "", (text or "").lower())
    return re.sub(r"\s+", " ", out).strip()


def compute_fingerprint_v2(account_id: str, provider: str, resource_id: str,
                           issue_type: str, upstream_key: str, title: str = "") -> str:
    """Structured identity: account|provider|resource|type|upstream-key.

    Falls back to the digit-stripped title as the last component ONLY when
    there is neither a usable resource_id nor an upstream key (today's
    behavior as the floor).
    """
    resource_norm = (resource_id or "").strip()
    if resource_norm.lower() == "unknown":
        resource_norm = ""
    key = (upstream_key or "").strip()
    if not resource_norm and not key:
        key = _strip_digits(title)
    raw = f"{account_id or ''}|{provider or ''}|{resource_norm}|{issue_type or 'other'}|{key}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class SignalInput:
    """One inbound event, normalized for the gate."""

    source: str
    title: str
    description: str
    severity: str
    resource_id: str = ""
    account_id: str = ""
    provider: str = "aws"
    issue_type: str = "other"
    upstream_key: str = ""
    kind: str = "alert"  # alert | detection | resolution | manual
    metric_data: dict = field(default_factory=dict)
    related_changes: list = field(default_factory=list)
    alarm_name: str = ""
    raw: dict = field(default_factory=dict)
    trace_id: Optional[str] = None
    im_origin: Optional[dict] = None
    auto_rca: bool = True
    detected_by: str = "detect_agent"


@dataclass
class GateDecision:
    """Gate outcome. ``created`` is True only when a new HealthIssue row was inserted."""

    disposition: str  # promoted | merged | noise
    reason: str
    issue_id: Optional[int] = None
    signal_id: Optional[int] = None
    created: bool = False
    issue_status: str = ""
    occurrence_count: int = 0


_gate_lock = threading.Lock()
_last_prune_date: Optional[date] = None


# ── Merge helper (single implementation for all paths) ────────────────


def merge_into_issue(session, existing, source, title, description, severity,
                     fingerprint, metric_data, related_changes) -> None:
    """Merge a signal into an existing HealthIssue (no commit).

    Appends a snapshot to metric_data["merged_alerts"], escalates severity,
    bumps occurrence_count/last_seen; refreshes description/metrics only for
    early-stage issues (open/investigating).
    """
    now = datetime.now(timezone.utc)
    snapshot = {
        "timestamp": now.isoformat(),
        "source": source,
        "title": title,
        "description": (description or "")[:500],
        "severity": (severity or "").lower(),
        "fingerprint": fingerprint or "",
    }
    md = dict(existing.metric_data) if isinstance(existing.metric_data, dict) else {}
    merged = list(md.get("merged_alerts", []))
    merged.append(snapshot)
    if len(merged) > _MERGED_ALERTS_CAP:
        merged = merged[-_MERGED_ALERTS_CAP:]
    md["merged_alerts"] = merged
    existing.metric_data = md

    if existing.status in ("open", "investigating"):
        existing.description = description
        if metric_data:
            md.update({k: v for k, v in metric_data.items() if k != "merged_alerts"})
            existing.metric_data = md
        if related_changes:
            prior = existing.related_changes if isinstance(existing.related_changes, list) else []
            existing.related_changes = prior + list(related_changes)

    if _SEVERITY_RANK.get((severity or "").lower(), 0) > _SEVERITY_RANK.get(existing.severity, 0):
        existing.severity = (severity or "").lower()

    existing.occurrence_count = (existing.occurrence_count or 1) + 1
    existing.last_seen = now


# ── L2 gray-zone LLM judgment ─────────────────────────────────────────


def _call_bedrock(prompt: str, model_id: str, max_tokens: int = 500) -> tuple:
    """One Bedrock converse call, temp=0. Returns (text, usage-dict)."""
    from agenticops.config import get_bedrock_boto_session

    client = get_bedrock_boto_session().client("bedrock-runtime")
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    usage = resp.get("usage", {})
    return text, {"input": int(usage.get("inputTokens", 0)), "output": int(usage.get("outputTokens", 0))}


def _parse_verdict(text: str) -> Optional[dict]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return v if isinstance(v, dict) else None


def _jaccard(a: str, b: str) -> float:
    sa = set(re.findall(r"[a-z0-9]+", (a or "").lower()))
    sb = set(re.findall(r"[a-z0-9]+", (b or "").lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _gray_zone_candidates(session, sig: SignalInput, now: datetime) -> list:
    """Active issues that make this signal ambiguous (L2 triggers, spec §2.4)."""
    from agenticops.models import HealthIssue

    window_start = now - timedelta(minutes=settings.noise_flap_window_minutes)
    active = (
        session.query(HealthIssue)
        .filter(HealthIssue.status.in_(ACTIVE_ISSUE_STATUSES))
        .order_by(HealthIssue.detected_at.desc())
        .limit(50)
        .all()
    )
    candidates: dict[int, object] = {}
    resource = (sig.resource_id or "").strip()
    for issue in active:
        # ① same resource, different wording/type
        if resource and resource.lower() != "unknown" and issue.resource_id == resource:
            candidates[issue.id] = issue
            continue
        # ② same issue_type recently active (cross-resource same-root-cause suspicion)
        recent = (issue.last_seen or issue.detected_at)
        if recent is not None and recent.tzinfo is None:
            recent = recent.replace(tzinfo=timezone.utc)
        if getattr(issue, "issue_type", "other") == sig.issue_type and recent and recent >= window_start:
            candidates[issue.id] = issue
            continue
        # ③ title similarity
        if _jaccard(issue.title, sig.title) >= 0.5:
            candidates[issue.id] = issue
    return list(candidates.values())[: settings.signal_gate_candidate_cap]


def _llm_judge(sig: SignalInput, candidates: list) -> Optional[dict]:
    """Ask the cheap tier: merge into one candidate, or new? Fail → None (promote)."""
    model_id = settings.signal_gate_llm_model or settings.bedrock_model_id_cheap
    cand_lines = [
        {
            "issue_id": c.id,
            "issue_type": getattr(c, "issue_type", "other"),
            "resource_id": c.resource_id,
            "severity": c.severity,
            "status": c.status,
            "title": c.title,
            "occurrence_count": c.occurrence_count or 1,
        }
        for c in candidates
    ]
    prompt = (
        "You are the Signal Gate merge judge for an AIOps platform.\n"
        "Decide if the NEW SIGNAL is the same underlying problem as ONE of the "
        "candidate active issues (action=merge) or a genuinely new problem (action=new).\n"
        "Respond with ONLY this JSON, nothing else:\n"
        '{"action": "merge" | "new", "target_issue_id": <int or null>, '
        '"confidence": <0.0-1.0>, "reason": "<short>"}\n'
        "If unsure, choose \"new\".\n\n"
        f"NEW SIGNAL: {json.dumps({'source': sig.source, 'issue_type': sig.issue_type, 'resource_id': sig.resource_id, 'severity': sig.severity, 'title': sig.title, 'description': (sig.description or '')[:300]})}\n\n"
        f"CANDIDATE ISSUES: {json.dumps(cand_lines)}"
    )
    try:
        text, usage = _call_bedrock(prompt, model_id)
    except Exception as e:
        logger.warning("signal-gate L2 LLM call failed (fail-open promote): %s", e)
        return None
    verdict = _parse_verdict(text)
    if verdict is not None:
        verdict["_usage"] = usage
        verdict["_model_id"] = model_id
    return verdict


# ── Signal ledger write ──────────────────────────────────────────────


def _write_signal(session, sig: SignalInput, fingerprint: str, disposition: str,
                  reason: str, issue_id: Optional[int], gate_evidence: dict,
                  trace_id: Optional[str]) -> int:
    from agenticops.models import AlertEvent

    row = AlertEvent(
        source=sig.source,
        external_id=(sig.upstream_key or "")[:200],
        severity=(sig.severity or "").lower(),
        title=(sig.title or "")[:500],
        description=sig.description or "",
        resource_hint=(sig.resource_id or "")[:500],
        raw_payload=sig.raw or {},
        health_issue_id=issue_id,
        status="ignored" if disposition == "noise" else "processed",
        trace_id=trace_id,
        kind=sig.kind,
        fingerprint=fingerprint,
        resource_id=(sig.resource_id or "")[:500],
        account_id=(sig.account_id or "")[:100],
        issue_type=sig.issue_type or "other",
        disposition=disposition,
        disposition_reason=reason[:200],
        gate_evidence=gate_evidence,
    )
    session.add(row)
    session.flush()
    return row.id


def _prune_old_signals(session) -> None:
    """Once per process-day, delete Signal rows past retention."""
    global _last_prune_date
    today = datetime.now(timezone.utc).date()
    if _last_prune_date == today or settings.signal_retention_days <= 0:
        return
    _last_prune_date = today
    try:
        from agenticops.models import AlertEvent

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.signal_retention_days)
        deleted = (
            session.query(AlertEvent)
            .filter(AlertEvent.received_at < cutoff)
            .delete(synchronize_session=False)
        )
        if deleted:
            logger.info("signal-gate: pruned %d signals older than %dd", deleted, settings.signal_retention_days)
    except Exception:
        logger.debug("signal prune failed", exc_info=True)


def _log_gated(issue_id: int, disposition: str, reason: str, signal_id: int) -> None:
    try:
        from agenticops.services.pipeline_events import log_event

        log_event(issue_id, "signal_gated", "detection", "completed",
                  detail={"disposition": disposition, "reason": reason, "signal_id": signal_id})
    except Exception:
        pass


# ── Promote: create the HealthIssue (moved from _create_health_issue_impl) ──


def _promote(session, sig: SignalInput, fingerprint: str, trace_id: Optional[str],
             im_origin: Optional[dict]):
    from agenticops.models import CloudAccount, CloudResource, HealthIssue

    now = datetime.now(timezone.utc)
    metric_data = dict(sig.metric_data or {})
    if im_origin:
        metric_data.setdefault("im_origin", im_origin)

    # Resolve account/provider from resource inventory; fallback: single enabled account
    account_id = None
    provider = None
    resource = (sig.resource_id or "").strip()
    if resource and resource.lower() != "unknown":
        res = session.query(CloudResource).filter_by(resource_id=resource).first()
        if res:
            account_id = res.account_id
            provider = res.provider
    if not account_id:
        enabled = session.query(CloudAccount).filter_by(is_enabled=True).all()
        if len(enabled) == 1:
            account_id = enabled[0].id
            provider = provider or enabled[0].provider

    issue = HealthIssue(
        resource_id=resource or "unknown",
        provider=provider or sig.provider or "aws",
        severity=(sig.severity or "medium").lower(),
        source=sig.source,
        title=(sig.title or "")[:300],
        description=sig.description or "",
        alarm_name=(sig.alarm_name or None),
        metric_data=metric_data,
        related_changes=list(sig.related_changes or []),
        status="open",
        detected_by=sig.detected_by,
        issue_type=sig.issue_type or "other",
        fingerprint=fingerprint,
        occurrence_count=1,
        first_seen=now,
        last_seen=now,
        trace_id=trace_id,
        account_id=account_id,
    )
    session.add(issue)
    session.flush()
    return issue


# ── The gate ──────────────────────────────────────────────────────────


def process_signal(sig: SignalInput) -> GateDecision:
    """Run one signal through L1 deterministic rules, then (gray zone only) L2.

    Serialized under a process-wide lock: decide+write is atomic per signal.
    """
    from agenticops.models import HealthIssue, get_session

    # Context fallbacks (agent-tool path relies on ContextVars)
    trace_id = sig.trace_id
    im_origin = sig.im_origin
    try:
        from agenticops.config import get_im_origin, get_trace_id

        trace_id = trace_id or get_trace_id()
        im_origin = im_origin or get_im_origin()
    except Exception:
        pass

    sig.severity = (sig.severity or "medium").lower()
    if sig.issue_type not in ISSUE_TYPES:
        sig.issue_type = classify_issue_type(sig.title, source=sig.source)
    fingerprint = compute_fingerprint_v2(
        sig.account_id, sig.provider, sig.resource_id, sig.issue_type, sig.upstream_key, sig.title
    )

    gate_on = settings.signal_gate_enabled
    now = datetime.now(timezone.utc)
    evidence: dict = {"fingerprint": fingerprint, "gate_enabled": gate_on}

    with _gate_lock:
        session = get_session()
        try:
            _prune_old_signals(session)

            # ① exclude patterns (regex on title) → noise
            for compiled in _compiled_exclude_patterns():
                if compiled.search(sig.title or ""):
                    evidence["rule"] = "excluded_pattern"
                    sid = _write_signal(session, sig, fingerprint, "noise", "excluded_pattern",
                                        None, evidence, trace_id)
                    session.commit()
                    logger.info("signal-gate: noise/excluded_pattern '%s'", sig.title)
                    return GateDecision("noise", "excluded_pattern", None, sid)

            # ② resolution kind: update/annotate, never create (gate-on only)
            if gate_on and sig.kind == "resolution":
                target = (
                    session.query(HealthIssue)
                    .filter(HealthIssue.fingerprint == fingerprint,
                            HealthIssue.status.in_(ACTIVE_ISSUE_STATUSES))
                    .order_by(HealthIssue.detected_at.desc())
                    .first()
                )
                if target is None:
                    cutoff = now - timedelta(minutes=settings.noise_flap_window_minutes)
                    target = (
                        session.query(HealthIssue)
                        .filter(HealthIssue.fingerprint == fingerprint,
                                HealthIssue.status == "resolved",
                                HealthIssue.resolved_at >= cutoff)
                        .order_by(HealthIssue.resolved_at.desc())
                        .first()
                    )
                if target is not None:
                    md = dict(target.metric_data) if isinstance(target.metric_data, dict) else {}
                    merged = list(md.get("merged_alerts", []))
                    merged.append({"timestamp": now.isoformat(), "source": sig.source,
                                   "title": sig.title, "kind": "resolution"})
                    md["merged_alerts"] = merged[-_MERGED_ALERTS_CAP:]
                    target.metric_data = md
                    target.last_seen = now
                    sid = _write_signal(session, sig, fingerprint, "merged", "resolution_update",
                                        target.id, evidence, trace_id)
                    session.commit()
                    _log_gated(target.id, "merged", "resolution_update", sid)
                    return GateDecision("merged", "resolution_update", target.id, sid,
                                        issue_status=target.status,
                                        occurrence_count=target.occurrence_count or 1)
                sid = _write_signal(session, sig, fingerprint, "noise", "orphan_resolution",
                                    None, evidence, trace_id)
                session.commit()
                return GateDecision("noise", "orphan_resolution", None, sid)

            # ③ exact fingerprint match on an active issue → merge
            existing = (
                session.query(HealthIssue)
                .filter(HealthIssue.fingerprint == fingerprint,
                        HealthIssue.status.in_(ACTIVE_ISSUE_STATUSES))
                .order_by(HealthIssue.detected_at.desc())
                .first()
            )
            if existing is not None:
                merge_into_issue(session, existing, sig.source, sig.title, sig.description,
                                 sig.severity, fingerprint, sig.metric_data, sig.related_changes)
                evidence["rule"] = "exact_fingerprint"
                sid = _write_signal(session, sig, fingerprint, "merged", "exact_fingerprint",
                                    existing.id, evidence, trace_id)
                session.commit()
                _log_gated(existing.id, "merged", "exact_fingerprint", sid)
                return GateDecision("merged", "exact_fingerprint", existing.id, sid,
                                    issue_status=existing.status,
                                    occurrence_count=existing.occurrence_count or 1)

            # ④ resolved cooldown → merge into the recently-resolved issue
            cooldown = settings.dedup_resolved_cooldown_minutes
            if cooldown > 0:
                recently = (
                    session.query(HealthIssue)
                    .filter(HealthIssue.fingerprint == fingerprint,
                            HealthIssue.status == "resolved",
                            HealthIssue.resolved_at >= now - timedelta(minutes=cooldown))
                    .order_by(HealthIssue.resolved_at.desc())
                    .first()
                )
                if recently is not None:
                    recently.occurrence_count = (recently.occurrence_count or 1) + 1
                    recently.last_seen = now
                    evidence["rule"] = "resolved_cooldown"
                    sid = _write_signal(session, sig, fingerprint, "merged", "resolved_cooldown",
                                        recently.id, evidence, trace_id)
                    session.commit()
                    _log_gated(recently.id, "merged", "resolved_cooldown", sid)
                    return GateDecision("merged", "resolved_cooldown", recently.id, sid,
                                        issue_status="resolved",
                                        occurrence_count=recently.occurrence_count)

            # ⑤ flapping: same fingerprint seen repeatedly in window → noise (gate-on only)
            if gate_on and settings.noise_flap_threshold > 0:
                from agenticops.models import AlertEvent

                window_start = now - timedelta(minutes=settings.noise_flap_window_minutes)
                flap_count = (
                    session.query(AlertEvent)
                    .filter(AlertEvent.fingerprint == fingerprint,
                            AlertEvent.received_at >= window_start)
                    .count()
                )
                if flap_count + 1 >= settings.noise_flap_threshold:
                    evidence["rule"] = "flapping"
                    evidence["flap_count"] = flap_count + 1
                    evidence["window_minutes"] = settings.noise_flap_window_minutes
                    reason = "flapping"
                    sid = _write_signal(session, sig, fingerprint, "noise", reason,
                                        None, evidence, trace_id)
                    session.commit()
                    logger.info("signal-gate: noise/flapping fp=%s count=%d", fingerprint[:12], flap_count + 1)
                    return GateDecision("noise", reason, None, sid)

            # ⑥ same resource AND same issue_type → merge (gate-on tightens legacy resource merge)
            resource = (sig.resource_id or "").strip()
            if gate_on and settings.resource_dedup_enabled and resource and resource.lower() != "unknown":
                match = (
                    session.query(HealthIssue)
                    .filter(HealthIssue.resource_id == resource,
                            HealthIssue.issue_type == (sig.issue_type or "other"),
                            HealthIssue.status.in_(RESOURCE_DEDUP_STATUSES))
                    .order_by(HealthIssue.detected_at.desc())
                    .first()
                )
                if match is not None:
                    merge_into_issue(session, match, sig.source, sig.title, sig.description,
                                     sig.severity, fingerprint, sig.metric_data, sig.related_changes)
                    evidence["rule"] = "resource_type_merge"
                    sid = _write_signal(session, sig, fingerprint, "merged", "resource_type_merge",
                                        match.id, evidence, trace_id)
                    session.commit()
                    _log_gated(match.id, "merged", "resource_type_merge", sid)
                    return GateDecision("merged", "resource_type_merge", match.id, sid,
                                        issue_status=match.status,
                                        occurrence_count=match.occurrence_count or 1)

            # L2 gray zone (gate-on + LLM enabled + suspicious neighbors exist)
            if gate_on and settings.signal_gate_llm_enabled and sig.kind != "resolution":
                candidates = _gray_zone_candidates(session, sig, now)
                if candidates:
                    evidence["candidates"] = [c.id for c in candidates]
                    verdict = _llm_judge(sig, candidates)
                    if verdict is not None:
                        evidence["llm"] = {k: v for k, v in verdict.items() if not k.startswith("_")}
                        evidence["llm_model"] = verdict.get("_model_id", "")
                        action = verdict.get("action")
                        conf = float(verdict.get("confidence") or 0.0)
                        target_id = verdict.get("target_issue_id")
                        cand_ids = {c.id for c in candidates}
                        if (action == "merge" and conf >= settings.signal_gate_confidence_min
                                and target_id in cand_ids):
                            target = next(c for c in candidates if c.id == target_id)
                            merge_into_issue(session, target, sig.source, sig.title,
                                             sig.description, sig.severity, fingerprint,
                                             sig.metric_data, sig.related_changes)
                            sid = _write_signal(session, sig, fingerprint, "merged", "llm_merge",
                                                target.id, evidence, trace_id)
                            session.commit()
                            _log_gated(target.id, "merged", "llm_merge", sid)
                            return GateDecision("merged", "llm_merge", target.id, sid,
                                                issue_status=target.status,
                                                occurrence_count=target.occurrence_count or 1)
                        # Any non-merge / low-confidence / invalid verdict → promote (fail-open).
                        # The LLM is never allowed to declare noise.

            # Promote: genuinely new problem
            issue = _promote(session, sig, fingerprint, trace_id, im_origin)
            evidence["rule"] = evidence.get("rule", "new_issue")
            sid = _write_signal(session, sig, fingerprint, "promoted", "new_issue",
                                issue.id, evidence, trace_id)
            session.commit()
            issue_id = issue.id
            occurrence = issue.occurrence_count or 1
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Post-commit side effects (outside the lock/session)
    try:
        from agenticops.services.pipeline_events import log_event

        log_event(issue_id, "issue_created", "detection",
                  detail={"severity": sig.severity, "fingerprint": fingerprint,
                          "source": sig.source, "issue_type": sig.issue_type,
                          "signal_id": sid})
    except Exception:
        pass

    if sig.auto_rca:
        try:
            from agenticops.services.rca_service import trigger_auto_rca

            trigger_auto_rca(issue_id, trace_id=trace_id)
        except Exception:
            logger.warning("signal-gate: auto-RCA trigger failed for #%d", issue_id, exc_info=True)

    try:
        from agenticops.services.notification_service import notify_issue_created

        notify_issue_created(issue_id, sig.severity, sig.title, sig.resource_id or "unknown")
    except Exception:
        logger.debug("signal-gate: notification failed", exc_info=True)

    return GateDecision("promoted", "new_issue", issue_id, sid, created=True,
                        issue_status="open", occurrence_count=occurrence)


def _compiled_exclude_patterns() -> list:
    """Compiled settings.issue_exclude_patterns (invalid patterns skipped)."""
    out = []
    for pattern in settings.issue_exclude_patterns or []:
        try:
            out.append(re.compile(pattern))
        except re.error:
            logger.warning("signal-gate: invalid exclude pattern skipped: %s", pattern)
    return out
