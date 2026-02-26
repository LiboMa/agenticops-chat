"""Metadata (SQLAlchemy) tools for Strands agents.

Wraps database read/write operations on the metadata layer.
"""

import json
import logging
from datetime import datetime

from strands import tool

from agenticops.config import settings
from agenticops.models import (
    AWSAccount,
    AWSResource,
    FixExecution,
    FixPlan,
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
def get_resource_by_id(resource_id: int) -> str:
    """Get details of a specific AWS resource by its database ID.

    Args:
        resource_id: The AWSResource database ID (integer PK).

    Returns:
        JSON object with resource details.
    """
    session = get_session()
    try:
        resource = session.query(AWSResource).filter_by(id=resource_id).first()
        if not resource:
            return f"Resource #{resource_id} not found."
        return json.dumps({
            "id": resource.id,
            "resource_id": resource.resource_id,
            "resource_arn": resource.resource_arn,
            "resource_type": resource.resource_type,
            "resource_name": resource.resource_name,
            "region": resource.region,
            "status": resource.status,
            "managed": resource.managed,
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
        Confirmation with the new FixPlan ID and risk level.
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

        issue.status = "fix_planned"
        session.commit()

        return (
            f"FixPlan #{plan.id} saved for HealthIssue #{health_issue_id}. "
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

        return json.dumps({
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
        }, default=str)
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
        plan.approved_at = datetime.utcnow()
        session.commit()

        # Update health issue status
        issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first()
        if issue:
            issue.status = "fix_approved"
            session.commit()

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

        return json.dumps({
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
        }, default=str)
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
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
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
                issue.resolved_at = datetime.utcnow()
                auto_resolved = True

        session.commit()

        # Trigger post-resolution pipeline (RAG + case distillation) in background
        if auto_resolved:
            try:
                from agenticops.services.resolution_service import trigger_post_resolution
                trigger_post_resolution(health_issue_id)
            except Exception as e:
                logger.warning("Failed to trigger post-resolution pipeline: %s", e)

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
