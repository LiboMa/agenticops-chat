"""Tests for resource detail API endpoints."""
import pytest
import uuid
from datetime import datetime, timedelta
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
def seed_data():
    """Seed a resource with related issues and fix plans."""
    uid = uuid.uuid4().hex[:8]
    with get_db_session() as db:
        acct = AWSAccount(
            name=f"test-rd-{uid}", account_id=f"1234{uid[:8].ljust(8, '0')}",
            role_arn="arn:aws:iam::role/test", regions=["us-east-1"],
        )
        db.add(acct)
        db.flush()
        res_id = f"i-{uid}"
        res = AWSResource(
            account_id=acct.id, resource_id=res_id, resource_type="EC2",
            resource_name="web-prod", region="us-east-1", status="running",
            resource_metadata={"instance_type": "t3.large", "vpc_id": f"vpc-{uid}"},
            tags={"env": "prod"},
        )
        db.add(res)
        db.flush()
        issue1 = HealthIssue(
            resource_id=res_id, severity="high", source="metric_anomaly",
            title="CPU spike", description="CPU at 95%", status="open",
            detected_at=datetime.utcnow(),
        )
        issue2 = HealthIssue(
            resource_id=res_id, severity="medium", source="log_pattern",
            title="Disk full", description="Disk 90%", status="resolved",
            detected_at=datetime.utcnow() - timedelta(days=3),
            resolved_at=datetime.utcnow() - timedelta(days=2),
        )
        db.add_all([issue1, issue2])
        db.flush()
        rca = RCAResult(
            health_issue_id=issue2.id, root_cause="Disk full",
            confidence=0.9, fix_risk_level="L0",
        )
        db.add(rca)
        db.flush()
        plan = FixPlan(
            health_issue_id=issue2.id, rca_result_id=rca.id,
            risk_level="L0", title="Cleanup disk", summary="rm old logs",
            steps=[{"cmd": "rm /tmp/*.log"}], rollback_plan={},
            status="executed",
        )
        db.add(plan)
        db.flush()
        execution = FixExecution(
            fix_plan_id=plan.id, health_issue_id=issue2.id,
            status="succeeded", duration_ms=1200,
        )
        db.add(execution)
        return {"resource_id": res.id, "issue1_id": issue1.id, "issue2_id": issue2.id}


def test_resource_issues(client, seed_data):
    resp = client.get(f"/api/resources/{seed_data['resource_id']}/issues")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["title"] == "CPU spike"  # most recent first


def test_resource_fix_plans(client, seed_data):
    resp = client.get(f"/api/resources/{seed_data['resource_id']}/fix-plans")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Cleanup disk"
    assert data[0]["executions"][0]["status"] == "succeeded"


def test_resource_issues_404(client):
    resp = client.get("/api/resources/99999/issues")
    assert resp.status_code == 404


def test_resource_related_compute(client, seed_data):
    """Compute resources show network context from metadata."""
    resp = client.get(f"/api/resources/{seed_data['resource_id']}/related")
    assert resp.status_code == 200
    data = resp.json()
    assert "network" in data
    assert "contains" in data
    # vpc_id from metadata should appear (unlinked, since no VPC resource exists)
    assert len(data["network"]) > 0
    assert data["network"][0]["resource_type"] == "VPC"


def test_resource_related_infra(client):
    """Infrastructure resources get 'contains' populated."""
    uid = uuid.uuid4().hex[:8]
    with get_db_session() as db:
        acct = AWSAccount(
            name=f"test-rd-infra-{uid}", account_id=f"2222{uid[:8].ljust(8, '0')}",
            role_arn="arn:aws:iam::role/t2", regions=["us-east-1"],
        )
        db.add(acct)
        db.flush()
        vpc = AWSResource(
            account_id=acct.id, resource_id="vpc-222", resource_type="VPC",
            resource_name="prod-vpc", region="us-east-1", status="available",
            resource_metadata={"cidr_block": "10.0.0.0/16"}, tags={},
        )
        ec2 = AWSResource(
            account_id=acct.id, resource_id="i-in-vpc", resource_type="EC2",
            resource_name="server", region="us-east-1", status="running",
            resource_metadata={"vpc_id": "vpc-222"}, tags={},
        )
        db.add_all([vpc, ec2])
        db.flush()
        vpc_db_id = vpc.id

    resp = client.get(f"/api/resources/{vpc_db_id}/related")
    assert resp.status_code == 200
    data = resp.json()
    assert any(r["resource_id"] == "i-in-vpc" for r in data["contains"])


def test_search_includes_resources(client, seed_data):
    """Global search should return matching resources."""
    resp = client.get("/api/search?q=web-prod&types=resources")
    assert resp.status_code == 200
    data = resp.json()
    assert "resources" in data["results"]
    assert len(data["results"]["resources"]) >= 1
    item = data["results"]["resources"][0]
    assert item["entity_type"] == "resource"
    assert "web-prod" in item["title"]


def test_search_resources_by_id(client, seed_data):
    """Search by resource_id prefix should find resources."""
    resp = client.get("/api/search?q=i-&types=resources")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"].get("resources", [])) >= 1
