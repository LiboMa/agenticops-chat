"""Metadata (SQLAlchemy) tools for Strands agents.

Wraps database read/write operations on the metadata layer.
"""

import json
import logging
from datetime import datetime

from strands import tool

from agenticops.models import (
    AWSAccount,
    AWSResource,
    HealthIssue,
    RCAResult,
    get_session,
)

logger = logging.getLogger(__name__)


@tool
def get_active_account() -> str:
    """Get the currently active AWS account configuration.

    Returns:
        JSON object with account details: name, account_id, role_arn, regions, last_scanned_at.
        Returns error message if no active account is configured.
    """
    session = get_session()
    try:
        account = session.query(AWSAccount).filter_by(is_active=True).first()
        if not account:
            return "No active AWS account configured. Use 'aiops create account' to add one."

        return json.dumps({
            "id": account.id,
            "name": account.name,
            "account_id": account.account_id,
            "role_arn": account.role_arn,
            "external_id": account.external_id or "",
            "regions": account.regions,
            "last_scanned_at": str(account.last_scanned_at) if account.last_scanned_at else "never",
        })
    finally:
        session.close()


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
        # Get active account
        account = session.query(AWSAccount).filter_by(is_active=True).first()
        if not account:
            return "No active AWS account configured."

        query = session.query(AWSResource).filter_by(account_id=account.id, managed=True)

        if resource_type:
            query = query.filter_by(resource_type=resource_type)
        if region:
            query = query.filter_by(region=region)

        resources = query.limit(200).all()

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
                "resource_name": r.resource_name,
                "region": r.region,
                "status": r.status,
                "managed": r.managed,
            })

        return json.dumps(result, default=str)
    finally:
        session.close()


@tool
def save_resources(resources_json: str) -> str:
    """Save or update discovered resources in metadata.

    Upserts resources: creates new or updates existing based on resource_id + region.

    Args:
        resources_json: JSON array of resource objects. Each must have:
            resource_id, resource_type, region. Optional: resource_name, resource_arn,
            status, metadata, tags.

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
        # Get active account
        account = session.query(AWSAccount).filter_by(is_active=True).first()
        if not account:
            return "No active AWS account configured."

        for res_data in resources:
            resource_id = res_data.get("resource_id")
            region = res_data.get("region")
            if not resource_id or not region:
                continue

            existing = (
                session.query(AWSResource)
                .filter_by(
                    account_id=account.id,
                    resource_id=resource_id,
                    region=region,
                )
                .first()
            )

            if existing:
                existing.resource_name = res_data.get("resource_name", existing.resource_name)
                existing.resource_arn = res_data.get("resource_arn", existing.resource_arn)
                existing.status = res_data.get("status", existing.status)
                existing.resource_metadata = res_data.get("metadata", existing.resource_metadata)
                existing.tags = res_data.get("tags", existing.tags)
                updated += 1
            else:
                resource = AWSResource(
                    account_id=account.id,
                    resource_id=resource_id,
                    resource_arn=res_data.get("resource_arn"),
                    resource_type=res_data.get("resource_type", "unknown"),
                    resource_name=res_data.get("resource_name"),
                    region=region,
                    status=res_data.get("status", "unknown"),
                    resource_metadata=res_data.get("metadata", {}),
                    tags=res_data.get("tags", {}),
                )
                session.add(resource)
                created += 1

        # Update last_scanned_at
        account.last_scanned_at = datetime.utcnow()
        session.commit()

        return f"Saved {created} new resources, updated {updated} existing."
    except Exception as e:
        session.rollback()
        return f"Error saving resources: {e}"
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

        # Deduplication: check for existing open issue with same resource + source + alarm
        dedup_query = session.query(HealthIssue).filter(
            HealthIssue.resource_id == resource_id,
            HealthIssue.source == source,
            HealthIssue.status.in_(["open", "investigating"]),
        )
        if alarm_name:
            dedup_query = dedup_query.filter(HealthIssue.alarm_name == alarm_name)

        existing = dedup_query.first()
        if existing:
            # Update existing issue instead of creating duplicate
            existing.description = description
            existing.metric_data = metric_data_parsed
            existing.related_changes = changes_parsed
            if severity.lower() in ("critical", "high") and existing.severity in ("medium", "low"):
                existing.severity = severity.lower()
            session.commit()
            return (
                f"Updated existing HealthIssue #{existing.id} (dedup): "
                f"[{existing.severity.upper()}] {existing.title}"
            )

        issue = HealthIssue(
            resource_id=resource_id,
            severity=severity.lower(),
            source=source,
            title=title,
            description=description,
            alarm_name=alarm_name or None,
            metric_data=metric_data_parsed,
            related_changes=changes_parsed,
            status="open",
            detected_by="detect_agent",
        )
        session.add(issue)
        session.commit()

        return f"Created HealthIssue #{issue.id}: [{severity.upper()}] {title}"
    except Exception as e:
        session.rollback()
        return f"Error creating health issue: {e}"
    finally:
        session.close()


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

        return json.dumps({
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
        }, default=str)
    finally:
        session.close()


@tool
def list_health_issues(
    severity: str = "",
    status: str = "open",
    resource_type: str = "",
    limit: int = 50,
) -> str:
    """List health issues with optional filters.

    Args:
        severity: Filter by severity (critical, high, medium, low) or empty for all
        status: Filter by status (open, investigating, root_cause_identified, resolved) or empty for all
        resource_type: Filter by resource type prefix in resource_id (e.g., 'i-' for EC2) or empty for all
        limit: Maximum number of results (default 50)

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

        return json.dumps(result, default=str)
    finally:
        session.close()


@tool
def update_health_issue_status(issue_id: int, new_status: str, note: str = "") -> str:
    """Update the status of a health issue.

    Valid status transitions:
    - open -> investigating
    - investigating -> root_cause_identified
    - root_cause_identified -> fix_planned -> fix_approved -> fix_executed -> resolved
    - Any status -> resolved (force close)

    Args:
        issue_id: The HealthIssue ID to update
        new_status: New status value
        note: Optional note explaining the status change

    Returns:
        Confirmation of the status update.
    """
    valid_statuses = {
        "open", "investigating", "root_cause_identified",
        "fix_planned", "fix_approved", "fix_executed", "resolved",
    }
    if new_status.lower() not in valid_statuses:
        return f"Invalid status '{new_status}'. Valid: {', '.join(sorted(valid_statuses))}"

    session = get_session()
    try:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            return f"HealthIssue #{issue_id} not found."

        old_status = issue.status
        issue.status = new_status.lower()

        if new_status.lower() == "resolved":
            issue.resolved_at = datetime.utcnow()

        session.commit()

        msg = f"HealthIssue #{issue_id} status: {old_status} -> {new_status.lower()}"
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

        return json.dumps({
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
        }, default=str)
    finally:
        session.close()
