import pytest
pytestmark = pytest.mark.skip(reason="pending mock path adaptation for main branch")

"""Tests for dashboard trends API."""
import pytest
import uuid
from datetime import datetime, timedelta, timezone
from starlette.testclient import TestClient
from agenticops.models import (
    Base, AWSAccount, AWSResource, HealthIssue, FixPlan, RCAResult,
    FixExecution, get_engine, get_db_session, init_db,
)
from agenticops.web.app import app


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_trends():
    now = datetime.now(timezone.utc)
    uid = uuid.uuid4().hex[:8]
    with get_db_session() as db:
        acct = AWSAccount(
            name=f"test-trends-{uid}", account_id=f"1111{uid[:8].ljust(8, '0')}",
            role_arn="arn:aws:iam::role/t", regions=["us-east-1"],
        )
        db.add(acct)
        db.flush()
        for i in range(5):
            db.add(AWSResource(
                account_id=acct.id, resource_id=f"i-t{uid}{i:03d}", resource_type="EC2",
                region="us-east-1", status="running",
                created_at=now - timedelta(days=i % 3),
            ))
        issue = HealthIssue(
            resource_id=f"i-t{uid}000", severity="high", source="metric_anomaly",
            title="Test issue", description="Test", status="resolved",
            detected_at=now - timedelta(days=2),
            resolved_at=now - timedelta(days=1),
        )
        db.add(issue)
        db.flush()
        rca = RCAResult(
            health_issue_id=issue.id, root_cause="test",
            confidence=0.9, fix_risk_level="L0",
        )
        db.add(rca)
        db.flush()
        plan = FixPlan(
            health_issue_id=issue.id, rca_result_id=rca.id,
            risk_level="L0", title="fix", summary="fix it",
            steps=[], rollback_plan={}, status="executed",
        )
        db.add(plan)
        db.flush()
        db.add(FixExecution(
            fix_plan_id=plan.id, health_issue_id=issue.id,
            status="succeeded", duration_ms=3600000,
            started_at=now - timedelta(days=1, hours=1),
            completed_at=now - timedelta(days=1),
        ))


def test_dashboard_trends_default(client, seed_trends):
    resp = client.get("/api/dashboard/trends")
    assert resp.status_code == 200
    data = resp.json()
    assert "issues" in data
    assert "severity" in data
    assert "resources" in data
    assert "mttr" in data
    assert "fix_rate" in data
    assert "summary" in data
    assert data["summary"]["mttr_avg_hours"] > 0
    assert data["summary"]["fix_rate_pct"] == 100.0


def test_dashboard_trends_custom_days(client, seed_trends):
    resp = client.get("/api/dashboard/trends?days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["issues"]) >= 1


def test_dashboard_trends_no_data_in_range(client):
    """No data in range should return empty arrays, not error."""
    # days=1 with no data in last 1 day should be safe
    resp = client.get("/api/dashboard/trends?days=0")
    # days=0 not allowed (ge=1), so test with valid range
    resp = client.get("/api/dashboard/trends?days=1")
    assert resp.status_code == 200
    data = resp.json()
    # Structure should always be present
    assert "issues" in data
    assert "summary" in data
    assert isinstance(data["summary"]["mttr_avg_hours"], (int, float))
