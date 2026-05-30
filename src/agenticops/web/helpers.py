"""Cross-router helper functions for the AgenticOps Web API.

Mechanically extracted from app.py (no logic change) so multiple routers can
share these without importing app.py (which would create an import cycle).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from agenticops.config import settings
from agenticops.models import CloudAccount, HealthIssue, Report
from agenticops.web.schemas import AnomalyResponse, ReportResponse

logger = logging.getLogger(__name__)


def _infra_ref_key(resource_type: str) -> Optional[str]:
    return {"VPC": "vpc_id", "Subnet": "subnet_id", "SecurityGroup": "security_group_id"}.get(resource_type)


def _guess_type(resource_id: str) -> str:
    for prefix, rtype in {"vpc-": "VPC", "subnet-": "Subnet", "sg-": "SecurityGroup",
                           "igw-": "IGW", "nat-": "NAT", "rtb-": "RouteTable"}.items():
        if resource_id.startswith(prefix):
            return rtype
    return "Unknown"


def _build_account_name_map(session, issues) -> dict[int, str]:
    """Batch-load account names for a list of HealthIssues to avoid N+1 queries."""
    account_ids = {i.account_id for i in issues if i.account_id}
    if not account_ids:
        return {}
    rows = session.query(CloudAccount.id, CloudAccount.name).filter(CloudAccount.id.in_(account_ids)).all()
    return {aid: aname for aid, aname in rows}


def _health_issue_to_anomaly_response(issue: HealthIssue, account_name: Optional[str] = None) -> AnomalyResponse:
    """Map a HealthIssue to the legacy AnomalyResponse format."""
    metric_data = issue.metric_data or {}
    return AnomalyResponse(
        id=issue.id,
        resource_id=issue.resource_id,
        resource_type=metric_data.get("resource_type", "unknown"),
        region=metric_data.get("region", "unknown"),
        anomaly_type=issue.source,
        severity=issue.severity,
        title=issue.title,
        description=issue.description,
        metric_name=metric_data.get("metric_name"),
        expected_value=metric_data.get("expected_value"),
        actual_value=metric_data.get("actual_value"),
        deviation_percent=metric_data.get("deviation_percent"),
        status=issue.status,
        detected_at=issue.detected_at,
        resolved_at=issue.resolved_at,
        account_id=issue.account_id,
        account_name=account_name,
    )


def _auto_learn_dismissed(issue_id: int, resource_id: str, title: str, description: str) -> None:
    """Auto-create detect agent memory when an issue is dismissed (best-effort)."""
    try:
        from agenticops.memory.agent_memory import save_memory_file

        parts = resource_id.split("/") if resource_id else []
        resource_pattern = f"{parts[0]}/*" if parts else ""
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower().strip())[:50].strip("_")
        filename = f"auto_{slug}.md" if slug else f"auto_issue_{issue_id}.md"

        body = (
            f"{title}\n\n{description}\n\n"
            f"Auto-learned: issue I#{issue_id} was dismissed by user."
        )
        save_memory_file(
            agent_name="detect",
            filename=filename,
            memory_type="feedback",
            confidence=2,
            source="auto",
            body=body,
            resource_pattern=resource_pattern,
            related_issue_id=issue_id,
        )
    except Exception:
        logger.debug("Auto-learn failed for dismissed issue #%d", issue_id, exc_info=True)


def _enrich_report(report: Report) -> dict:
    """Build ReportResponse dict with download_url when S3 is configured."""
    data = ReportResponse.model_validate(report).model_dump()
    if report.file_path and settings.report_storage == "s3" and settings.report_s3_bucket:
        try:
            from agenticops.storage.backend import get_storage_backend
            backend = get_storage_backend()
            data["download_url"] = backend.presigned_url(
                report.file_path, expiry=settings.report_presigned_url_expiry
            )
        except Exception:
            pass
    return data
