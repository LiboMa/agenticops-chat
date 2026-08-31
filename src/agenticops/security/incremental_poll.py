"""Fast-frequency security incremental poll job (SecurityIncrementalPoll).

Cursor-based GuardDuty / SecurityHub / CloudTrail high-risk-event polling.
Every source is fail-soft: on error the source is skipped for this round and
its cursor is NOT advanced (retry next round, no data loss). All AWS calls go
through the provider layer for the target account — never ambient.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_BACKFILL_HOURS = 24  # first run: bounded backfill window


def _get_client(service: str, region: str, account: str = ""):
    """Provider-layer client for the target account (never ambient)."""
    from agenticops.security.collectors import _get_client as _c
    return _c(service, region, account)


@dataclass
class SecurityEvent:
    """One normalized fast-path security event from an official source."""
    source: str          # guardduty | securityhub | cloudtrail
    event_id: str        # upstream unique id -> SignalInput.upstream_key
    title: str
    description: str
    severity: str        # critical | high | medium | low
    resource_id: str
    resource_type: str
    occurred_at: str     # upstream ISO8601 timestamp
    raw: dict = field(default_factory=dict)


def _get_cursor(session, account: str, source: str, region: str) -> str:
    """Stored cursor, or now-24h ISO on first run (bounded backfill)."""
    from agenticops.models import SecurityPollCursor
    row = (session.query(SecurityPollCursor)
           .filter_by(account_id=account, source=source, region=region).first())
    if row and row.cursor:
        return row.cursor
    return (datetime.now(timezone.utc) - timedelta(hours=_BACKFILL_HOURS)).isoformat()


def _set_cursor(session, account: str, source: str, region: str, value: str) -> None:
    from agenticops.models import SecurityPollCursor
    row = (session.query(SecurityPollCursor)
           .filter_by(account_id=account, source=source, region=region).first())
    if row:
        row.cursor = value
    else:
        session.add(SecurityPollCursor(
            account_id=account, source=source, region=region, cursor=value))


def _gd_severity(sev: float) -> str:
    """AWS GuardDuty numeric severity bands."""
    if sev >= 9.0:
        return "critical"
    if sev >= 7.0:
        return "high"
    if sev >= 4.0:
        return "medium"
    return "low"


def _gd_resource(finding: dict) -> tuple[str, str]:
    res = finding.get("Resource", {}) or {}
    inst = (res.get("InstanceDetails") or {}).get("InstanceId")
    if inst:
        return inst, "Instance"
    key = (res.get("AccessKeyDetails") or {}).get("UserName")
    if key:
        return key, "IAMUser"
    return "unknown", res.get("ResourceType", "unknown")


def poll_guardduty(account: str, region: str, since_iso: str) -> list[SecurityEvent]:
    """GuardDuty findings updated since the cursor. Raises on API error."""
    gd = _get_client("guardduty", region, account)
    out: list[SecurityEvent] = []
    since_ms = int(datetime.fromisoformat(since_iso.replace("Z", "+00:00")).timestamp() * 1000)
    for det in gd.list_detectors().get("DetectorIds", []):
        ids: list[str] = []
        paginator = gd.get_paginator("list_findings")
        for page in paginator.paginate(
            DetectorId=det,
            FindingCriteria={"Criterion": {"updatedAt": {"Gte": since_ms}}},
        ):
            ids.extend(page.get("FindingIds", []))
        for i in range(0, len(ids), 50):
            for f in gd.get_findings(DetectorId=det, FindingIds=ids[i:i + 50]).get("Findings", []):
                rid, rtype = _gd_resource(f)
                out.append(SecurityEvent(
                    source="guardduty", event_id=f.get("Id", ""),
                    title=f.get("Title", "GuardDuty finding"),
                    description=f.get("Description", ""),
                    severity=_gd_severity(float(f.get("Severity", 0))),
                    resource_id=rid, resource_type=rtype,
                    occurred_at=f.get("UpdatedAt", since_iso),
                    raw={"type": f.get("Type", "")},
                ))
    return out


def poll_securityhub(account: str, region: str, since_iso: str) -> list[SecurityEvent]:
    """SecurityHub ACTIVE+NEW findings updated since the cursor. Raises on API error."""
    sh = _get_client("securityhub", region, account)
    now_iso = datetime.now(timezone.utc).isoformat()
    out: list[SecurityEvent] = []
    paginator = sh.get_paginator("get_findings")
    for page in paginator.paginate(Filters={
        "UpdatedAt": [{"Start": since_iso, "End": now_iso}],
        "RecordState": [{"Value": "ACTIVE", "Comparison": "EQUALS"}],
        "WorkflowStatus": [{"Value": "NEW", "Comparison": "EQUALS"}],
    }):
        for f in page.get("Findings", []):
            res = (f.get("Resources") or [{}])[0]
            label = str((f.get("Severity") or {}).get("Label", "MEDIUM")).lower()
            out.append(SecurityEvent(
                source="securityhub", event_id=f.get("Id", ""),
                title=f.get("Title", "Security Hub finding"),
                description=f.get("Description", ""),
                severity="low" if label == "informational" else label,
                resource_id=res.get("Id", "unknown"),
                resource_type=res.get("Type", "unknown"),
                occurred_at=f.get("UpdatedAt", since_iso),
            ))
    return out


HIGH_RISK_EVENTS = frozenset({
    # logging tampering
    "DeleteTrail", "StopLogging", "UpdateTrail", "PutEventSelectors", "DeleteFlowLogs",
    # network exposure
    "AuthorizeSecurityGroupIngress",
    # identity escalation
    "CreateUser", "CreateAccessKey", "CreateLoginProfile", "AttachUserPolicy",
    "PutUserPolicy", "DeactivateMFADevice",
    # data exposure
    "PutBucketAcl", "PutBucketPolicy", "DeleteBucketPolicy",
    # encryption tampering
    "DisableKey", "ScheduleKeyDeletion",
})


def poll_cloudtrail(account: str, region: str, since_iso: str) -> list[SecurityEvent]:
    """High-risk CloudTrail management events since the cursor. Raises on API error.

    lookup_events supports only one LookupAttribute per call, so we pull the
    window and filter client-side against HIGH_RISK_EVENTS."""
    ct = _get_client("cloudtrail", region, account)
    start = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
    out: list[SecurityEvent] = []
    paginator = ct.get_paginator("lookup_events")
    for page in paginator.paginate(StartTime=start):
        for e in page.get("Events", []):
            name = e.get("EventName", "")
            if name not in HIGH_RISK_EVENTS:
                continue
            res = (e.get("Resources") or [{}])[0]
            user = e.get("Username", "unknown")
            when = e.get("EventTime")
            out.append(SecurityEvent(
                source="cloudtrail", event_id=e.get("EventId", ""),
                title=f"High-risk API call: {name}",
                description=f"{name} invoked by {user}",
                severity="high",
                resource_id=res.get("ResourceName") or user,
                resource_type=res.get("ResourceType", "unknown"),
                occurred_at=when.isoformat() if hasattr(when, "isoformat") else str(when or since_iso),
            ))
    return out


def run_incremental_poll() -> int:
    """Return the number of new findings emitted. Filled in by Task 4.5."""
    return 0
