"""Metadata (SQLAlchemy) tools for Strands agents.

Wraps database read/write operations on the metadata layer.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from strands import tool

from agenticops.config import settings
from agenticops.models import (
    CloudAccount,
    CloudResource,
    FixExecution,
    FixPlan,
    HealthIssue,
    IMAlias,
    InvalidStatusTransition,
    RCAResult,
    get_session,
    validate_status_transition,
)
from agenticops.notify.im_config import load_channels as _load_yaml_channels

logger = logging.getLogger(__name__)

# ── Pre-compiled exclude patterns (avoids re-compiling per issue) ──────
_exclude_cache: tuple[list[str], list[re.Pattern]] | None = None


def _compiled_exclude_patterns() -> list[re.Pattern]:
    """Return compiled exclude patterns, recompiling only when config changes."""
    global _exclude_cache
    raw = settings.issue_exclude_patterns
    if _exclude_cache is None or _exclude_cache[0] != raw:
        compiled = []
        for p in raw:
            try:
                compiled.append(re.compile(p))
            except re.error:
                logger.warning("Invalid exclude pattern: %s", p)
        _exclude_cache = (raw, compiled)
    return _exclude_cache[1]


# ── Output size limits (prevents context window overflow) ──────────────
# Matches pattern in aws_cli_tool.py and skills/execution.py.
# Tool results accumulate in the agent conversation; unbounded JSON from
# DB queries was the root cause of "内容过大被截断" errors.
MAX_RESULT_CHARS = 4000
MAX_LIST_RESULT_CHARS = 6000  # lists may need slightly more room


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    """Truncate tool output to *limit* characters."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (output truncated, use get_* with specific ID for full details)"


@tool
def get_enabled_accounts() -> str:
    """Get all enabled cloud accounts for scanning and operations.

    Returns JSON array of accounts with id, name, provider, regions, labels.
    Returns JSON array of accounts with id, name, provider, regions, labels.
    """
    session = get_session()
    try:
        accounts = session.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()  # noqa: E712
        if not accounts:
            return json.dumps({"error": "No enabled accounts found. Add accounts via CLI or Web UI."})
        result = []
        for acct in accounts:
            result.append({
                "id": acct.id,
                "name": acct.name,
                "provider": acct.provider,
                "regions": acct.regions,
                "labels": acct.labels,
                "last_scanned_at": acct.last_scanned_at.isoformat() if acct.last_scanned_at else None,
            })
        return _truncate(json.dumps(result))
    except Exception as e:
        return json.dumps({"error": str(e)})
    finally:
        session.close()


@tool
def get_active_account() -> str:
    """Get all enabled cloud accounts for operations.

    Returns JSON array of enabled accounts (same as get_enabled_accounts).
    Agents should operate on ALL returned accounts unless the user specifies one.
    """
    return get_enabled_accounts()


@tool
def get_managed_resources(resource_type: str = "", region: str = "") -> str:
    """List resources from the inventory, optionally filtered.

    Args:
        resource_type: Filter by type (EC2, RDS, Lambda, etc.) or empty for all
        region: Filter by region or empty for all

    Returns:
        JSON list of resources with id, resource_id, type, name, region, status.
    """
    session = get_session()
    try:
        cloud_accounts = session.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()  # noqa: E712
        if cloud_accounts:
            account_ids = [a.id for a in cloud_accounts]
            query = session.query(CloudResource).filter(
                CloudResource.account_id.in_(account_ids),
                CloudResource.managed == True,  # noqa: E712
            )
            if resource_type:
                query = query.filter_by(resource_type=resource_type)
            if region:
                query = query.filter_by(region=region)

            resources = query.limit(50).all()
            if not resources:
                filters = []
                if resource_type:
                    filters.append(f"type={resource_type}")
                if region:
                    filters.append(f"region={region}")
                filter_str = f" (filters: {', '.join(filters)})" if filters else ""
                return f"No resources found{filter_str}."

            result = []
            for r in resources:
                result.append({
                    "id": r.id,
                    "resource_id": r.resource_id,
                    "resource_type": r.resource_type,
                    "name": r.name,
                    "provider": r.provider,
                    "region": r.region,
                    "status": r.status,
                    "managed": r.managed,
                })
            return _truncate(json.dumps(result, default=str), MAX_LIST_RESULT_CHARS)

        return json.dumps({"error": "No enabled accounts found. Add accounts via CLI or Web UI."})
    finally:
        session.close()


@tool
def save_resources(resources_json: str, account_id: int = 0, provider: str = "") -> str:
    """Save or update discovered resources in metadata.

    Upserts resources into CloudResource table. If account_id and provider are
    given, uses them directly. Otherwise falls back to the first enabled
    CloudAccount.

    Args:
        resources_json: JSON array of resource objects. Each must have:
            resource_id, resource_type, region. Optional: name, status, tags, raw_data.
        account_id: CloudAccount ID to save resources under (0 = auto-detect).
        provider: Cloud provider (aws, azure, gcp, alicloud). Empty = auto-detect.

    Returns:
        Summary of saved/updated resources.
    """
    try:
        resources = json.loads(resources_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    if not isinstance(resources, list):
        return "Expected a JSON array of resource objects."

    session = get_session()
    created = 0
    updated = 0

    try:
        # Resolve account
        cloud_acct = None
        if account_id > 0:
            cloud_acct = session.query(CloudAccount).filter_by(id=account_id).first()
        if not cloud_acct:
            enabled = session.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()  # noqa: E712
            if len(enabled) == 1:
                cloud_acct = enabled[0]
            elif len(enabled) > 1:
                return json.dumps({"error": "Multiple accounts enabled. Specify account_id.", "accounts": [{"id": a.id, "name": a.name} for a in enabled]})

        if cloud_acct:
            acct_id = cloud_acct.id
            acct_provider = provider or cloud_acct.provider

            for res_data in resources:
                resource_id = res_data.get("resource_id")
                region = res_data.get("region")
                if not resource_id or not region:
                    continue

                existing = (
                    session.query(CloudResource)
                    .filter_by(
                        account_id=acct_id,
                        provider=acct_provider,
                        resource_id=resource_id,
                    )
                    .first()
                )

                if existing:
                    existing.name = res_data.get("name", existing.name)
                    existing.status = res_data.get("status", existing.status)
                    existing.raw_data = res_data.get("raw_data", existing.raw_data)
                    existing.tags = res_data.get("tags", existing.tags)
                    existing.region = region
                    existing.scanned_at = datetime.now(timezone.utc)
                    updated += 1
                else:
                    resource = CloudResource(
                        account_id=acct_id,
                        provider=acct_provider,
                        resource_id=resource_id,
                        resource_type=res_data.get("resource_type", "unknown"),
                        name=res_data.get("name", ""),
                        region=region,
                        status=res_data.get("status", "unknown"),
                        raw_data=res_data.get("raw_data", {}),
                        tags=res_data.get("tags", {}),
                        managed=res_data.get("managed", True),
                        scanned_at=datetime.now(timezone.utc),
                    )
                    session.add(resource)
                    created += 1

            cloud_acct.last_scanned_at = datetime.now(timezone.utc)
            session.commit()
            return f"Saved {created} new resources, updated {updated} existing (account={cloud_acct.name}, provider={acct_provider})."

        return "No enabled accounts found. Add accounts via CLI or Web UI."
    except Exception as e:
        session.rollback()
        return f"Error saving resources: {e}"
    finally:
        session.close()


_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# All states where an issue is still "active" — should NOT create duplicates
_ACTIVE_ISSUE_STATUSES = (
    "open", "investigating", "acknowledged",
    "root_cause_identified", "fix_planned",
    "fix_approved", "fix_executing", "fix_executed",
    "dismissed",
)

RESOURCE_DEDUP_STATUSES = ("open", "investigating", "acknowledged", "root_cause_identified")
_MERGED_ALERTS_CAP = 50


def _merge_into_existing_issue(
    session, existing, source, title, description, severity, fingerprint, metric_data_parsed, changes_parsed,
):
    """Merge a new alert into an existing HealthIssue for the same resource.

    Appends a snapshot to metric_data["merged_alerts"], escalates severity,
    updates description, bumps occurrence_count, and merges related_changes.
    """
    now = datetime.now(timezone.utc)

    # Build alert snapshot
    snapshot = {
        "timestamp": now.isoformat(),
        "source": source,
        "title": title,
        "description": (description or "")[:500],
        "severity": severity.lower(),
        "fingerprint": fingerprint,
    }

    # Append to merged_alerts (capped)
    md = existing.metric_data if isinstance(existing.metric_data, dict) else {}
    merged = md.get("merged_alerts", [])
    merged.append(snapshot)
    if len(merged) > _MERGED_ALERTS_CAP:
        merged = merged[-_MERGED_ALERTS_CAP:]
    md["merged_alerts"] = merged
    existing.metric_data = md

    # Update description to latest
    existing.description = description

    # Escalate severity
    if _SEVERITY_RANK.get(severity.lower(), 0) > _SEVERITY_RANK.get(existing.severity, 0):
        existing.severity = severity.lower()

    # Bump occurrence_count and last_seen
    existing.occurrence_count = (existing.occurrence_count or 1) + 1
    existing.last_seen = now

    # Merge related_changes
    if changes_parsed:
        existing_changes = existing.related_changes if isinstance(existing.related_changes, list) else []
        existing.related_changes = existing_changes + changes_parsed

    session.commit()

    # Log pipeline event
    try:
        from agenticops.services.pipeline_events import log_event
        log_event(existing.id, "issue_resource_merged", "detection", "completed",
                  detail={"source": source, "title": title, "severity": severity,
                          "merged_count": len(merged)})
    except Exception:
        pass

    return (
        f"Resource-merged: updated existing HealthIssue #{existing.id} "
        f"(resource={existing.resource_id}, merged_count={len(merged)}): "
        f"[{existing.severity.upper()}] {existing.title}"
    )


def _compute_fingerprint(source: str, resource_id: str, title: str) -> str:
    """Compute a SHA-256 fingerprint for HealthIssue deduplication.

    Normalises the title (lowercase, collapse whitespace, strip numbers/timestamps)
    so that semantically identical alerts produce the same fingerprint.
    """
    title_key = re.sub(r"\d+", "", title.lower())  # strip numbers
    title_key = re.sub(r"\s+", " ", title_key).strip()
    raw = f"{source}:{resource_id}:{title_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _create_health_issue_impl(
    resource_id: str,
    severity: str,
    source: str,
    title: str,
    description: str,
    alarm_name: str = "",
    metric_data: str = "{}",
    related_changes: str = "[]",
    auto_rca: bool = True,
) -> str:
    """Create a health issue with fingerprint dedup. Plain function (no @tool).

    auto_rca=False skips the auto-RCA trigger — used by structural risk sources
    (e.g. graph patrol SPOF/capacity findings) where a CloudTrail-style forensic
    RCA is not meaningful.
    """
    session = get_session()
    try:
        # Parse JSON fields
        try:
            metric_data_parsed = json.loads(metric_data) if isinstance(metric_data, str) else metric_data
        except json.JSONDecodeError:
            metric_data_parsed = {}

        try:
            changes_parsed = json.loads(related_changes) if isinstance(related_changes, str) else related_changes
        except json.JSONDecodeError:
            changes_parsed = []

        # Check exclude patterns
        for compiled in _compiled_exclude_patterns():
            if compiled.search(title):
                logger.info("Suppressed issue: title '%s' matched exclude pattern", title)
                return f"Suppressed: issue title matched exclude pattern"

        now = datetime.now(timezone.utc)
        fingerprint = _compute_fingerprint(source, resource_id, title)

        # Fingerprint-based deduplication: match any active (non-resolved) issue
        existing = (
            session.query(HealthIssue)
            .filter(
                HealthIssue.fingerprint == fingerprint,
                HealthIssue.status.in_(_ACTIVE_ISSUE_STATUSES),
            )
            .order_by(HealthIssue.detected_at.desc())
            .first()
        )

        if existing:
            existing.occurrence_count += 1
            existing.last_seen = now
            # Only update description/metrics for early-stage issues
            if existing.status in ("open", "investigating"):
                existing.description = description
                existing.metric_data = metric_data_parsed
                existing.related_changes = changes_parsed
            # Always escalate severity
            if _SEVERITY_RANK.get(severity.lower(), 0) > _SEVERITY_RANK.get(existing.severity, 0):
                existing.severity = severity.lower()
            session.commit()

            try:
                from agenticops.services.pipeline_events import log_event
                log_event(existing.id, "issue_deduplicated", "detection", "skipped",
                          detail={"existing_id": existing.id, "count": existing.occurrence_count})
            except Exception:
                pass

            return (
                f"Deduplicated: updated existing HealthIssue #{existing.id} "
                f"(status={existing.status}, count={existing.occurrence_count}): "
                f"[{existing.severity.upper()}] {existing.title}"
            )

        # Resolved cooldown: avoid flapping re-detection
        cooldown = settings.dedup_resolved_cooldown_minutes
        if cooldown > 0:
            recently_resolved = (
                session.query(HealthIssue)
                .filter(
                    HealthIssue.fingerprint == fingerprint,
                    HealthIssue.status == "resolved",
                    HealthIssue.resolved_at >= now - timedelta(minutes=cooldown),
                )
                .order_by(HealthIssue.resolved_at.desc())
                .first()
            )
            if recently_resolved:
                recently_resolved.occurrence_count += 1
                recently_resolved.last_seen = now
                session.commit()
                return (
                    f"Suppressed: HealthIssue #{recently_resolved.id} was resolved "
                    f"{int((now - recently_resolved.resolved_at).total_seconds() // 60)}min ago "
                    f"(cooldown={cooldown}min). Bumped count to {recently_resolved.occurrence_count}."
                )

        # Resource-based dedup: merge into existing open issue for the same resource
        if settings.resource_dedup_enabled and resource_id and resource_id != "unknown":
            resource_match = (
                session.query(HealthIssue)
                .filter(
                    HealthIssue.resource_id == resource_id,
                    HealthIssue.status.in_(RESOURCE_DEDUP_STATUSES),
                )
                .order_by(HealthIssue.detected_at.desc())
                .first()
            )
            if resource_match:
                return _merge_into_existing_issue(
                    session, resource_match, source, title, description,
                    severity, fingerprint, metric_data_parsed, changes_parsed,
                )

        # Inject trace_id from ContextVar
        from agenticops.config import get_im_origin, get_trace_id
        trace_id = get_trace_id()

        # Inject IM origin if called from an IM agent context
        im_origin = get_im_origin()
        if im_origin and isinstance(metric_data_parsed, dict):
            metric_data_parsed["im_origin"] = im_origin
        elif im_origin and not metric_data_parsed:
            metric_data_parsed = {"im_origin": im_origin}

        # Auto-resolve account_id and provider from resource inventory
        account_id = None
        provider = None
        if resource_id and resource_id != "unknown":
            res = session.query(CloudResource).filter_by(resource_id=resource_id).first()
            if res:
                account_id = res.account_id
                provider = res.provider
        # Fallback: use single enabled account, or skip if ambiguous
        if not account_id:
            enabled = session.query(CloudAccount).filter_by(is_enabled=True).all()
            if len(enabled) == 1:
                account_id = enabled[0].id
                provider = provider or enabled[0].provider

        issue = HealthIssue(
            resource_id=resource_id,
            provider=provider or "aws",
            severity=severity.lower(),
            source=source,
            title=title,
            description=description,
            alarm_name=alarm_name or None,
            metric_data=metric_data_parsed,
            related_changes=changes_parsed,
            status="open",
            detected_by="detect_agent",
            fingerprint=fingerprint,
            occurrence_count=1,
            first_seen=now,
            last_seen=now,
            trace_id=trace_id,
            account_id=account_id,
        )
        session.add(issue)
        session.commit()

        # Log pipeline event
        try:
            from agenticops.services.pipeline_events import log_event
            log_event(issue.id, "issue_created", "detection",
                      detail={"severity": severity, "fingerprint": fingerprint, "source": source})
        except Exception:
            pass

        # Auto-trigger RCA for newly created issues
        if auto_rca:
            from agenticops.services.rca_service import trigger_auto_rca
            trigger_auto_rca(issue.id, trace_id=trace_id)

        # Auto-notify
        try:
            from agenticops.services.notification_service import notify_issue_created
            notify_issue_created(issue.id, severity, title, resource_id)
        except Exception:
            logger.debug("Notification trigger failed", exc_info=True)

        return f"Created HealthIssue #{issue.id}: [{severity.upper()}] {title}"
    except Exception as e:
        session.rollback()
        return f"Error creating health issue: {e}"
    finally:
        session.close()


@tool
def create_health_issue(
    resource_id: str,
    severity: str,
    source: str,
    title: str,
    description: str,
    alarm_name: str = "",
    metric_data: str = "{}",
    related_changes: str = "[]",
) -> str:
    """Create a new health issue record in the metadata database.

    Uses fingerprint-based deduplication: if an open/investigating issue with the
    same fingerprint (source + resource_id + normalised title) exists and was last
    seen within 5 minutes, the existing issue is updated instead of creating a
    duplicate.

    Args:
        resource_id: AWS resource ID (e.g., i-1234567890abcdef0)
        severity: Issue severity: critical, high, medium, or low
        source: Detection source: cloudwatch_alarm, metric_anomaly, log_pattern, or manual
        title: Brief issue title
        description: Detailed description of the issue
        alarm_name: CloudWatch alarm name if source is cloudwatch_alarm
        metric_data: JSON object with relevant metric data
        related_changes: JSON array of related CloudTrail events

    Returns:
        Confirmation with the new HealthIssue ID.
    """
    return _create_health_issue_impl(
        resource_id=resource_id,
        severity=severity,
        source=source,
        title=title,
        description=description,
        alarm_name=alarm_name,
        metric_data=metric_data,
        related_changes=related_changes,
        auto_rca=True,
    )


@tool
def get_health_issue(issue_id: int) -> str:
    """Get details of a specific health issue.

    Args:
        issue_id: The HealthIssue ID to retrieve.

    Returns:
        JSON object with full health issue details.
    """
    session = get_session()
    try:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            return f"HealthIssue #{issue_id} not found."

        return _truncate(json.dumps({
            "id": issue.id,
            "resource_id": issue.resource_id,
            "severity": issue.severity,
            "source": issue.source,
            "title": issue.title,
            "description": issue.description,
            "alarm_name": issue.alarm_name,
            "metric_data": issue.metric_data,
            "related_changes": issue.related_changes,
            "status": issue.status,
            "detected_at": str(issue.detected_at),
            "detected_by": issue.detected_by,
            "resolved_at": str(issue.resolved_at) if issue.resolved_at else None,
            "trace_id": issue.trace_id,
        }, default=str))
    finally:
        session.close()


@tool
def get_resource_by_id(resource_id: int) -> str:
    """Get details of a specific cloud resource by its database ID.

    Args:
        resource_id: The CloudResource database ID (integer PK).

    Returns:
        JSON object with resource details.
    """
    session = get_session()
    try:
        resource = session.query(CloudResource).filter_by(id=resource_id).first()
        if not resource:
            return f"Resource #{resource_id} not found."
        return _truncate(json.dumps({
            "id": resource.id,
            "resource_id": resource.resource_id,
            "provider": resource.provider,
            "resource_type": resource.resource_type,
            "name": resource.name,
            "region": resource.region,
            "status": resource.status,
            "managed": resource.managed,
            "tags": resource.tags,
        }, default=str))
    finally:
        session.close()


@tool
def list_health_issues(
    severity: str = "",
    status: str = "open",
    resource_type: str = "",
    limit: int = 20,
) -> str:
    """List health issues with optional filters.

    Args:
        severity: Filter by severity (critical, high, medium, low) or empty for all
        status: Filter by status (open, investigating, root_cause_identified, resolved) or empty for all
        resource_type: Filter by resource type prefix in resource_id (e.g., 'i-' for EC2) or empty for all
        limit: Maximum number of results (default 20)

    Returns:
        JSON array of health issues with id, resource_id, severity, source, title, status, detected_at.
    """
    session = get_session()
    try:
        query = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc())

        if severity:
            query = query.filter_by(severity=severity.lower())
        if status:
            query = query.filter_by(status=status.lower())
        if resource_type:
            query = query.filter(HealthIssue.resource_id.like(f"{resource_type}%"))

        issues = query.limit(limit).all()

        if not issues:
            return "No health issues found matching filters."

        result = []
        for i in issues:
            result.append({
                "id": i.id,
                "resource_id": i.resource_id,
                "severity": i.severity,
                "source": i.source,
                "title": i.title,
                "status": i.status,
                "detected_at": str(i.detected_at),
            })

        return _truncate(json.dumps(result, default=str), MAX_LIST_RESULT_CHARS)
    finally:
        session.close()


@tool
def update_health_issue_status(issue_id: int, new_status: str, note: str = "") -> str:
    """Update the status of a health issue with state machine enforcement.

    Valid transitions (see models.py _ISSUE_TRANSITIONS for full map):
    - open -> investigating | acknowledged | resolved
    - investigating -> acknowledged | root_cause_identified | fix_planned | resolved
    - acknowledged -> investigating | root_cause_identified | fix_planned | resolved
    - root_cause_identified -> fix_planned | resolved
    - fix_planned -> fix_approved | resolved
    - fix_approved -> fix_executing | resolved
    - fix_executing -> fix_executed | resolved
    - fix_executed -> resolved

    Args:
        issue_id: The HealthIssue ID to update
        new_status: New status value
        note: Optional note explaining the status change

    Returns:
        Confirmation of the status update, or error message if transition is invalid.
    """
    new_status = new_status.lower()

    session = get_session()
    try:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            return f"HealthIssue #{issue_id} not found."

        old_status = issue.status
        try:
            validate_status_transition(old_status, new_status)
        except (InvalidStatusTransition, ValueError) as e:
            return f"Status transition rejected: {e}"

        issue.status = new_status

        if new_status == "resolved":
            issue.resolved_at = datetime.now(timezone.utc)

        session.commit()

        msg = f"HealthIssue #{issue_id} status: {old_status} -> {new_status}"
        if note:
            msg += f" (note: {note})"
        return msg
    except Exception as e:
        session.rollback()
        return f"Error updating health issue: {e}"
    finally:
        session.close()


@tool
def save_rca_result(
    health_issue_id: int,
    root_cause: str,
    confidence: float,
    contributing_factors: str,
    recommendations: str,
    fix_plan: str = "{}",
    fix_risk_level: str = "unknown",
    sop_used: str = "",
    similar_cases: str = "[]",
    model_id: str = "",
) -> str:
    """Save RCA analysis result to metadata and update HealthIssue status.

    Creates an RCAResult record linked to the HealthIssue and sets the issue
    status to 'root_cause_identified'.

    Args:
        health_issue_id: The HealthIssue ID this analysis is for
        root_cause: Root cause description
        confidence: Confidence score 0.0-1.0
        contributing_factors: JSON array of contributing factors
        recommendations: JSON array of recommendations
        fix_plan: JSON object with step-by-step remediation plan
        fix_risk_level: Risk level: unknown, low, medium, high, critical
        sop_used: SOP filename used during analysis, if any
        similar_cases: JSON array of similar case references
        model_id: LLM model ID used for analysis

    Returns:
        Confirmation with the new RCAResult ID.
    """
    # Parse JSON string parameters
    try:
        factors_parsed = json.loads(contributing_factors) if isinstance(contributing_factors, str) else contributing_factors
    except json.JSONDecodeError:
        factors_parsed = [contributing_factors]

    try:
        recs_parsed = json.loads(recommendations) if isinstance(recommendations, str) else recommendations
    except json.JSONDecodeError:
        recs_parsed = [recommendations]

    try:
        plan_parsed = json.loads(fix_plan) if isinstance(fix_plan, str) else fix_plan
    except json.JSONDecodeError:
        plan_parsed = {}

    try:
        cases_parsed = json.loads(similar_cases) if isinstance(similar_cases, str) else similar_cases
    except json.JSONDecodeError:
        cases_parsed = []

    session = get_session()
    try:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            return f"HealthIssue #{health_issue_id} not found."

        rca = RCAResult(
            health_issue_id=health_issue_id,
            root_cause=root_cause,
            confidence=max(0.0, min(1.0, confidence)),
            contributing_factors=factors_parsed,
            recommendations=recs_parsed,
            fix_plan=plan_parsed,
            fix_risk_level=fix_risk_level,
            sop_used=sop_used or None,
            similar_cases=cases_parsed,
            model_id=model_id,
        )
        session.add(rca)

        issue.status = "root_cause_identified"
        session.commit()

        # Log pipeline event
        try:
            from agenticops.services.pipeline_events import log_event
            log_event(health_issue_id, "rca_completed", "rca",
                      detail={"rca_id": rca.id, "confidence": rca.confidence, "root_cause": root_cause[:200]})
        except Exception:
            pass

        # Auto-trigger SRE fix plan generation
        try:
            from agenticops.services.pipeline_service import trigger_auto_sre
            trigger_auto_sre(health_issue_id, trace_id=issue.trace_id)
        except Exception as e:
            logger.warning("Failed to trigger auto-SRE: %s", e)

        # Auto-notify + IM origin update
        try:
            from agenticops.services.notification_service import notify_rca_completed, notify_im_origin
            notify_rca_completed(health_issue_id, root_cause, rca.confidence)
            notify_im_origin(
                health_issue_id, "rca_completed",
                f"RCA completed for Issue #{health_issue_id}: {root_cause[:200]}. Confidence: {rca.confidence:.0%}",
            )
        except Exception:
            logger.debug("Notification trigger failed", exc_info=True)

        return (
            f"RCAResult #{rca.id} saved for HealthIssue #{health_issue_id}. "
            f"Root cause: {root_cause[:100]}... Confidence: {rca.confidence:.0%}. "
            f"Issue status updated to 'root_cause_identified'."
        )
    except Exception as e:
        session.rollback()
        return f"Error saving RCA result: {e}"
    finally:
        session.close()


@tool
def get_rca_result(health_issue_id: int) -> str:
    """Get the latest RCA result for a health issue.

    Args:
        health_issue_id: The HealthIssue ID to look up.

    Returns:
        JSON object with the latest RCA result, or a message if none found.
    """
    session = get_session()
    try:
        rca = (
            session.query(RCAResult)
            .filter_by(health_issue_id=health_issue_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )
        if not rca:
            return f"No RCA result found for HealthIssue #{health_issue_id}."

        return _truncate(json.dumps({
            "id": rca.id,
            "health_issue_id": rca.health_issue_id,
            "root_cause": rca.root_cause,
            "confidence": rca.confidence,
            "contributing_factors": rca.contributing_factors,
            "recommendations": rca.recommendations,
            "fix_plan": rca.fix_plan,
            "fix_risk_level": rca.fix_risk_level,
            "sop_used": rca.sop_used,
            "similar_cases": rca.similar_cases,
            "model_id": rca.model_id,
            "created_at": str(rca.created_at),
        }, default=str))
    finally:
        session.close()


# ============================================================================
# Fix Plan tools (SRE Agent)
# ============================================================================


@tool
def save_fix_plan(
    health_issue_id: int,
    rca_result_id: int,
    risk_level: str,
    title: str,
    summary: str,
    steps: str = "[]",
    rollback_plan: str = "{}",
    estimated_impact: str = "",
    pre_checks: str = "[]",
    post_checks: str = "[]",
) -> str:
    """Save a structured fix plan for a health issue.

    Args:
        health_issue_id: The HealthIssue ID this plan addresses
        rca_result_id: The RCAResult ID this plan is based on
        risk_level: Risk classification: L0 (read-only), L1 (low-risk), L2 (service-affecting), L3 (high-risk)
        title: Brief title for the fix plan
        summary: Summary of what the fix plan does
        steps: JSON array of ordered fix steps (each step is a dict with 'action' and 'command' keys)
        rollback_plan: JSON object describing how to undo the fix
        estimated_impact: Description of expected downtime or performance impact
        pre_checks: JSON array of pre-conditions to verify before starting
        post_checks: JSON array of checks to verify after completion

    Returns:
        - Created: confirmation with new FixPlan ID and risk level
        - Updated: confirmation that existing draft plan was updated in place
        - Rejected: error message if a locked plan (approved/executing) already exists
    """
    valid_levels = {"L0", "L1", "L2", "L3"}
    risk_level = risk_level.upper()
    if risk_level not in valid_levels:
        return f"Invalid risk_level '{risk_level}'. Must be one of: {', '.join(sorted(valid_levels))}"

    # Parse JSON parameters
    try:
        steps_parsed = json.loads(steps) if isinstance(steps, str) else steps
    except json.JSONDecodeError:
        steps_parsed = [steps]

    try:
        rollback_parsed = json.loads(rollback_plan) if isinstance(rollback_plan, str) else rollback_plan
    except json.JSONDecodeError:
        rollback_parsed = {"description": rollback_plan}

    try:
        pre_parsed = json.loads(pre_checks) if isinstance(pre_checks, str) else pre_checks
    except json.JSONDecodeError:
        pre_parsed = [pre_checks]

    try:
        post_parsed = json.loads(post_checks) if isinstance(post_checks, str) else post_checks
    except json.JSONDecodeError:
        post_parsed = [post_checks]

    session = get_session()
    try:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            return f"HealthIssue #{health_issue_id} not found."

        rca = session.query(RCAResult).filter_by(id=rca_result_id).first()
        if not rca:
            return f"RCAResult #{rca_result_id} not found."

        # --- Dedup: one issue → one fix plan (replace mode) ---
        # NOTE: This check-then-act is not atomic. For SQLite (single-writer)
        # this is safe. For PostgreSQL, a partial unique index on
        # (health_issue_id) WHERE status NOT IN terminal would be ideal.
        # The trigger_auto_sre() guard prevents most concurrent scenarios.
        from agenticops.models import (
            FIXPLAN_TERMINAL_STATUSES,
            FIXPLAN_REPLACEABLE_STATUSES,
            FIXPLAN_LOCKED_STATUSES,
        )

        existing = (
            session.query(FixPlan)
            .filter_by(health_issue_id=health_issue_id)
            .filter(FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES))
            .order_by(FixPlan.created_at.desc())
            .first()
        )

        if existing and existing.status in FIXPLAN_LOCKED_STATUSES:
            return (
                f"HealthIssue #{health_issue_id} already has FixPlan #{existing.id} "
                f"in '{existing.status}' state. Cannot create a new plan while one is "
                f"in progress. Wait for it to complete or reject it first."
            )

        is_update = existing and existing.status in FIXPLAN_REPLACEABLE_STATUSES

        if is_update:
            # Update existing draft plan in place
            plan = existing
            plan.rca_result_id = rca_result_id
            plan.risk_level = risk_level
            plan.title = title
            plan.summary = summary
            plan.steps = steps_parsed
            plan.rollback_plan = rollback_parsed
            plan.estimated_impact = estimated_impact
            plan.pre_checks = pre_parsed
            plan.post_checks = post_parsed
            event_type = "fix_plan_updated"
        else:
            # Create new plan (no existing, or all existing are terminal)
            plan = FixPlan(
                health_issue_id=health_issue_id,
                rca_result_id=rca_result_id,
                risk_level=risk_level,
                title=title,
                summary=summary,
                steps=steps_parsed,
                rollback_plan=rollback_parsed,
                estimated_impact=estimated_impact,
                pre_checks=pre_parsed,
                post_checks=post_parsed,
                status="draft",
            )
            session.add(plan)
            event_type = "fix_plan_created"

        issue.status = "fix_planned"
        session.commit()

        # Log pipeline event
        try:
            from agenticops.services.pipeline_events import log_event
            log_event(health_issue_id, event_type, "planning",
                      detail={"plan_id": plan.id, "risk_level": risk_level})
        except Exception:
            pass

        # Auto-approve L0/L1 plans
        try:
            from agenticops.services.pipeline_service import trigger_auto_approve
            trigger_auto_approve(plan.id, trace_id=issue.trace_id)
        except Exception as e:
            logger.warning("Failed to trigger auto-approve: %s", e)

        # Auto-notify
        try:
            from agenticops.services.notification_service import notify_fix_planned
            notify_fix_planned(health_issue_id, plan.id, risk_level, title)
        except Exception:
            logger.debug("Notification trigger failed", exc_info=True)

        action = "UPDATED" if is_update else "saved"
        return (
            f"FixPlan #{plan.id} {action} for HealthIssue #{health_issue_id}. "
            f"Risk: {risk_level}. Title: {title}. "
            f"Issue status updated to 'fix_planned'."
        )
    except Exception as e:
        session.rollback()
        return f"Error saving fix plan: {e}"
    finally:
        session.close()


@tool
def get_fix_plan(health_issue_id: int) -> str:
    """Get the latest fix plan for a health issue.

    Args:
        health_issue_id: The HealthIssue ID to look up.

    Returns:
        JSON object with the latest FixPlan, or a message if none found.
    """
    session = get_session()
    try:
        plan = (
            session.query(FixPlan)
            .filter_by(health_issue_id=health_issue_id)
            .order_by(FixPlan.created_at.desc())
            .first()
        )
        if not plan:
            return f"No fix plan found for HealthIssue #{health_issue_id}."

        return _truncate(json.dumps({
            "id": plan.id,
            "health_issue_id": plan.health_issue_id,
            "rca_result_id": plan.rca_result_id,
            "risk_level": plan.risk_level,
            "title": plan.title,
            "summary": plan.summary,
            "steps": plan.steps,
            "rollback_plan": plan.rollback_plan,
            "estimated_impact": plan.estimated_impact,
            "pre_checks": plan.pre_checks,
            "post_checks": plan.post_checks,
            "status": plan.status,
            "approved_by": plan.approved_by,
            "approved_at": str(plan.approved_at) if plan.approved_at else None,
            "created_at": str(plan.created_at),
        }, default=str))
    finally:
        session.close()


@tool
def approve_fix_plan(fix_plan_id: int, approved_by: str) -> str:
    """Approve a fix plan. L0/L1 can be auto-approved; L2/L3 require human approval.

    Args:
        fix_plan_id: The FixPlan ID to approve
        approved_by: Name/identifier of the approver

    Returns:
        Confirmation of approval or rejection reason.
    """
    session = get_session()
    try:
        plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
        if not plan:
            return f"FixPlan #{fix_plan_id} not found."

        if plan.status == "approved":
            return f"FixPlan #{fix_plan_id} is already approved."

        if plan.status == "rejected":
            return f"FixPlan #{fix_plan_id} was rejected. Create a new plan instead."

        # L2/L3 require human approval — flag it but still record
        if plan.risk_level in ("L2", "L3") and approved_by.startswith("agent:"):
            plan.status = "pending_approval"
            session.commit()
            return (
                f"FixPlan #{fix_plan_id} (risk {plan.risk_level}) requires human approval. "
                f"Status set to 'pending_approval'. A human operator must approve L2/L3 plans."
            )

        plan.status = "approved"
        plan.approved_by = approved_by
        plan.approved_at = datetime.now(timezone.utc)
        session.commit()

        # Update health issue status
        issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first()
        if issue:
            issue.status = "fix_approved"
            session.commit()

        # Auto-trigger execution for approved plans
        try:
            from agenticops.services.pipeline_service import trigger_auto_execute
            trigger_auto_execute(fix_plan_id, trace_id=issue.trace_id if issue else None)
        except Exception as e:
            logger.warning("Failed to trigger auto-execute: %s", e)

        # Auto-notify
        try:
            from agenticops.services.notification_service import notify_fix_approved
            notify_fix_approved(fix_plan_id, approved_by, plan.risk_level)
        except Exception:
            logger.debug("Notification trigger failed", exc_info=True)

        return (
            f"FixPlan #{fix_plan_id} approved by {approved_by}. "
            f"Risk: {plan.risk_level}. HealthIssue status updated to 'fix_approved'."
        )
    except Exception as e:
        session.rollback()
        return f"Error approving fix plan: {e}"
    finally:
        session.close()


# ============================================================================
# Executor tools (L4 Auto Operation)
# ============================================================================


@tool
def get_approved_fix_plan(fix_plan_id: int) -> str:
    """Safety gate: retrieve a fix plan ONLY if its status is 'approved'.

    This is the mandatory first step before execution. Returns full plan
    details needed for execution, or rejects with an explanation.

    Args:
        fix_plan_id: The FixPlan ID to retrieve.

    Returns:
        JSON object with full plan details if approved, or rejection message.
    """
    session = get_session()
    try:
        plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
        if not plan:
            return f"REJECTED: FixPlan #{fix_plan_id} not found."

        if plan.status != "approved":
            return (
                f"REJECTED: FixPlan #{fix_plan_id} status is '{plan.status}', not 'approved'. "
                f"Only approved plans can be executed."
            )

        return _truncate(json.dumps({
            "id": plan.id,
            "health_issue_id": plan.health_issue_id,
            "rca_result_id": plan.rca_result_id,
            "risk_level": plan.risk_level,
            "title": plan.title,
            "summary": plan.summary,
            "steps": plan.steps,
            "rollback_plan": plan.rollback_plan,
            "estimated_impact": plan.estimated_impact,
            "pre_checks": plan.pre_checks,
            "post_checks": plan.post_checks,
            "status": plan.status,
            "approved_by": plan.approved_by,
            "approved_at": str(plan.approved_at) if plan.approved_at else None,
            "created_at": str(plan.created_at),
        }, default=str))
    finally:
        session.close()


@tool
def save_execution_result(
    fix_plan_id: int,
    health_issue_id: int,
    status: str,
    step_results: str = "[]",
    pre_check_results: str = "[]",
    post_check_results: str = "[]",
    rollback_results: str = "[]",
    error_message: str = "",
    duration_ms: int = 0,
    executed_by: str = "executor_agent",
) -> str:
    """Create a FixExecution record and update FixPlan status.

    Args:
        fix_plan_id: The FixPlan ID that was executed.
        health_issue_id: The HealthIssue ID associated with the plan.
        status: Execution outcome: succeeded, failed, rolled_back, or aborted.
        step_results: JSON array of per-step results [{step_index, command, status, output, duration_ms}].
        pre_check_results: JSON array of pre-check outcomes.
        post_check_results: JSON array of post-check outcomes.
        rollback_results: JSON array of rollback step outcomes (if applicable).
        error_message: Error description if execution failed.
        duration_ms: Total execution time in milliseconds.
        executed_by: Identifier of who/what executed the plan.

    Returns:
        Confirmation with the new FixExecution ID.
    """
    valid_statuses = {"succeeded", "failed", "rolled_back", "aborted"}
    if status not in valid_statuses:
        return f"Invalid execution status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}"

    def _parse_json(val, fallback):
        try:
            return json.loads(val) if isinstance(val, str) else val
        except json.JSONDecodeError:
            return fallback

    session = get_session()
    try:
        plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
        if not plan:
            return f"FixPlan #{fix_plan_id} not found."

        execution = FixExecution(
            fix_plan_id=fix_plan_id,
            health_issue_id=health_issue_id,
            status=status,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            executed_by=executed_by,
            pre_check_results=_parse_json(pre_check_results, []),
            step_results=_parse_json(step_results, []),
            post_check_results=_parse_json(post_check_results, []),
            rollback_results=_parse_json(rollback_results, []),
            error_message=error_message or None,
            duration_ms=duration_ms,
        )
        session.add(execution)

        # Update FixPlan status
        if status == "succeeded":
            plan.status = "executed"
        elif status in ("failed", "rolled_back"):
            plan.status = "failed"
        # aborted -> keep approved (allow retry)

        # Auto-resolve HealthIssue on success and trigger post-resolution pipeline.
        # DESIGN NOTE: Successful execution transitions directly from fix_approved → resolved,
        # intentionally skipping fix_executed. The FixExecution table tracks execution detail,
        # while HealthIssue.status tracks the lifecycle. Controlled by executor_auto_resolve flag.
        auto_resolved = False
        if status == "succeeded" and settings.executor_auto_resolve:
            issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
            if issue and issue.status in ("fix_approved", "fix_executed"):
                issue.status = "resolved"
                issue.resolved_at = datetime.now(timezone.utc)
                auto_resolved = True

        session.commit()

        # Log pipeline event
        try:
            from agenticops.services.pipeline_events import log_event
            log_event(health_issue_id, "execution_completed", "execution", status,
                      detail={"plan_id": fix_plan_id, "duration_ms": duration_ms, "auto_resolved": auto_resolved},
                      duration_ms=duration_ms)
        except Exception:
            pass

        # Trigger post-resolution pipeline (RAG + case distillation) in background
        if auto_resolved:
            try:
                from agenticops.services.resolution_service import trigger_post_resolution
                trigger_post_resolution(health_issue_id)
            except Exception as e:
                logger.warning("Failed to trigger post-resolution pipeline: %s", e)

        # Auto-notify + IM origin update
        try:
            from agenticops.services.notification_service import notify_execution_result, notify_im_origin
            notify_execution_result(fix_plan_id, health_issue_id, status, error_message)
            notify_im_origin(
                health_issue_id, "execution_completed",
                f"Execution {'SUCCEEDED' if status == 'succeeded' else 'FAILED'} for Issue #{health_issue_id} (Plan #{fix_plan_id})"
                + (f": {error_message[:200]}" if error_message else ""),
            )
        except Exception:
            logger.debug("Notification trigger failed", exc_info=True)

        msg = (
            f"FixExecution #{execution.id} saved for FixPlan #{fix_plan_id}. "
            f"Status: {status}. FixPlan status updated to '{plan.status}'."
        )
        if auto_resolved:
            msg += f" HealthIssue #{health_issue_id} auto-resolved. Post-resolution pipeline triggered."
        return msg
    except Exception as e:
        session.rollback()
        return f"Error saving execution result: {e}"
    finally:
        session.close()


@tool
def mark_fix_executed(health_issue_id: int, execution_id: int) -> str:
    """Mark a HealthIssue as fix_executed after successful execution.

    Transitions HealthIssue status to 'fix_executed' and records the execution reference.

    Args:
        health_issue_id: The HealthIssue ID to update.
        execution_id: The FixExecution ID that completed successfully.

    Returns:
        Confirmation of the status update.
    """
    session = get_session()
    try:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            return f"HealthIssue #{health_issue_id} not found."

        execution = session.query(FixExecution).filter_by(id=execution_id).first()
        if not execution:
            return f"FixExecution #{execution_id} not found."

        old_status = issue.status

        # If already auto-resolved by save_execution_result(), don't overwrite
        if old_status == "resolved":
            return (
                f"HealthIssue #{health_issue_id} already auto-resolved. "
                f"Execution #{execution_id} recorded. No status change needed."
            )

        issue.status = "fix_executed"
        session.commit()

        return (
            f"HealthIssue #{health_issue_id} status: {old_status} -> fix_executed. "
            f"Execution #{execution_id} recorded."
        )
    except Exception as e:
        session.rollback()
        return f"Error marking fix executed: {e}"
    finally:
        session.close()


@tool
def mark_fix_failed(health_issue_id: int, execution_id: int, reason: str = "") -> str:
    """Record that a fix execution failed. Keeps HealthIssue in fix_approved state to allow retry.

    Args:
        health_issue_id: The HealthIssue ID.
        execution_id: The FixExecution ID that failed.
        reason: Brief description of why execution failed.

    Returns:
        Confirmation message.
    """
    session = get_session()
    try:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            return f"HealthIssue #{health_issue_id} not found."

        execution = session.query(FixExecution).filter_by(id=execution_id).first()
        if not execution:
            return f"FixExecution #{execution_id} not found."

        # Keep status at fix_approved so a retry or new plan is possible
        if issue.status != "fix_approved":
            issue.status = "fix_approved"
            session.commit()

        msg = (
            f"HealthIssue #{health_issue_id} remains in 'fix_approved' (retry allowed). "
            f"Execution #{execution_id} failed"
        )
        if reason:
            msg += f": {reason}"
        return msg
    except Exception as e:
        session.rollback()
        return f"Error marking fix failed: {e}"
    finally:
        session.close()


@tool
def list_send_targets(target_type: str = "") -> str:
    """List available /send_to targets (notification channels and IM aliases).

    Args:
        target_type: Filter by type: "channel", "im", or "" for all.

    Returns:
        JSON with channels and im_aliases arrays, plus usage hint.
    """
    result: dict = {}

    if target_type in ("", "channel"):
        yaml_channels = _load_yaml_channels()
        result["channels"] = [
            {
                "name": ch.name,
                "channel_type": ch.channel_type,
                "is_enabled": ch.is_enabled,
                "severity_filter": ch.severity_filter or [],
            }
            for ch in yaml_channels
            if ch.is_enabled
        ]

    if target_type in ("", "im"):
        session = get_session()
        try:
            aliases = session.query(IMAlias).all()
            result["im_aliases"] = [
                {
                    "id": a.id,
                    "name": a.name,
                    "platform": a.platform,
                    "app_name": a.app_name,
                    "description": a.description or "",
                }
                for a in aliases
            ]
        finally:
            session.close()

    result["hint"] = 'Use /send_to <name> #R<id> or /send_to <name> "message" to send.'
    return _truncate(json.dumps(result, default=str), MAX_LIST_RESULT_CHARS)
