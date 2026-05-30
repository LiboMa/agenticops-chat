"""Shared HealthIssue / CloudResource reference resolution.

Single source of truth for both the chat preprocessor (I#/R# inline refs) and
the /send_to command. Returns plain dicts so each caller can format as needed.
"""

from __future__ import annotations

from typing import Optional

from agenticops.models import get_db_session


def fetch_issue(issue_id: int) -> Optional[dict]:
    """Return a HealthIssue as a dict, or None if not found."""
    from agenticops.models import HealthIssue
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            return None
        return {
            "id": issue.id, "title": issue.title, "severity": issue.severity,
            "status": issue.status, "resource_id": issue.resource_id,
            "source": issue.source, "description": issue.description,
            "detected_at": issue.detected_at,
        }


def fetch_resource(resource_pk: int) -> Optional[dict]:
    """Return a CloudResource as a dict, or None if not found."""
    from agenticops.models import CloudResource
    with get_db_session() as session:
        r = session.query(CloudResource).filter_by(id=resource_pk).first()
        if not r:
            return None
        return {
            "id": r.id, "resource_id": r.resource_id, "provider": r.provider,
            "resource_type": r.resource_type, "name": r.name, "region": r.region,
            "status": r.status,
        }
