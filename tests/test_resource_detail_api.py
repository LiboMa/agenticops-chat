"""Tests for resource detail API endpoints."""
import pytest
import uuid
from datetime import datetime, timedelta, timezone
from starlette.testclient import TestClient
from agenticops.models import (
    Base, CloudAccount, CloudResource, HealthIssue, FixPlan, RCAResult,
    FixExecution, get_engine, get_db_session, init_db,
)
from agenticops.web.app import app
import agenticops.models as models_mod


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    """Use a fresh temp DB to avoid index conflicts with legacy tables."""
    from agenticops.config import settings
    orig_url = settings.database_url
    orig_engine = models_mod._engine

    settings.database_url = f"sqlite:///{tmp_path}/test_resource.db"
    models_mod._engine = None
    init_db()
    yield
    models_mod._engine = None
    settings.database_url = orig_url
    models_mod._engine = orig_engine


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_data():
    """Seed a resource with related issues and fix plans."""
    uid = uuid.uuid4().hex[:8]
    with get_db_session() as db:
        acct = CloudAccount(
            name=f"test-rd-{uid}", provider="aws",
            credentials={"account_id": f"1234{uid[:8].ljust(8, '0')}", "role_arn": "arn:aws:iam::role/test"},
            regions=["us-east-1"],
        )
        db.add(acct)
        db.flush()
        res_id = f"i-{uid}"
        res = CloudResource(
            account_id=acct.id, provider="aws", resource_id=res_id, resource_type="EC2",
            name="web-prod", region="us-east-1", status="running",
            raw_data={"instance_type": "t3.large", "vpc_id": f"vpc-{uid}"},
            tags={"env": "prod"},
        )
        db.add(res)
        db.flush()
        issue1 = HealthIssue(
            resource_id=res_id, severity="high", source="metric_anomaly",
            title="CPU spike", description="CPU at 95%", status="open",
            detected_at=datetime.now(timezone.utc),
        )
        issue2 = HealthIssue(
            resource_id=res_id, severity="medium", source="log_pattern",
            title="Disk full", description="Disk 90%", status="resolved",
            detected_at=datetime.now(timezone.utc) - timedelta(days=3),
            resolved_at=datetime.now(timezone.utc) - timedelta(days=2),
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
        return {"resource_id": res.id, "aws_resource_id": res_id, "issue1_id": issue1.id, "issue2_id": issue2.id}


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


def _anchored(seed_data, raw_id, *, account_matches=True, plan=False):
    """An issue whose alarm carried `raw_id` (an ARN, an alarm name — not the row's own id) and whose anchor
    resolved to the seeded resource."""
    with get_db_session() as db:
        res = db.query(CloudResource).filter_by(id=seed_data["resource_id"]).one()
        issue = HealthIssue(resource_id=raw_id, severity="critical", source="cloudwatch_alarm", title="Anchored by the resolver",
                            description="d", status="open", detected_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                            resource_ref=res.id, anchor_status="anchored",
                            account_id=res.account_id if account_matches else res.account_id + 100)
        db.add(issue)
        db.flush()
        if plan:
            rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
            db.add(rca); db.flush()
            db.add(FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="Plan of the anchored issue",
                           summary="s", steps=[], rollback_plan={}, status="draft", created_at=datetime.now(timezone.utc) + timedelta(minutes=2)))
        return issue.id


def test_resource_issues_include_the_ones_anchored_to_it(client, seed_data):
    """MVP-2.9.0: an issue is tied to its resource by its anchor (`resource_ref`, MVP-2.6.1) — the alarm's own
    resource id is often an ARN or an alarm name and matches no row. The resource's list missed every such issue
    while the map and the resource table (the health overlay, by `resource_ref`) counted it."""
    iid = _anchored(seed_data, f"arn:aws:ec2:us-east-1:123456789012:instance/{seed_data['aws_resource_id']}")
    data = client.get(f"/api/resources/{seed_data['resource_id']}/issues").json()
    assert [i["id"] for i in data] == [iid, seed_data["issue1_id"], seed_data["issue2_id"]]      # newest first; the legacy matches stay


def test_resource_issues_leave_out_a_stale_anchor_of_another_account(client, seed_data):
    """SQLite does not enforce ON DELETE SET NULL: a stale resource_ref may point at an id another account's row now
    uses (health_overlay has the same guard)."""
    _anchored(seed_data, "arn:aws:ec2:us-east-1:999:instance/i-else", account_matches=False)
    data = client.get(f"/api/resources/{seed_data['resource_id']}/issues").json()
    assert [i["title"] for i in data] == ["CPU spike", "Disk full"]


def test_resource_fix_plans_include_the_plans_of_anchored_issues(client, seed_data):
    _anchored(seed_data, "alarm:cpu-high-web-prod", plan=True)
    data = client.get(f"/api/resources/{seed_data['resource_id']}/fix-plans").json()
    assert [p["title"] for p in data] == ["Plan of the anchored issue", "Cleanup disk"]


def test_resource_issues_leave_out_another_accounts_resource_of_the_same_id(client, seed_data):
    """Final review: the older tie — the alarm's id equals the row's own id — had no account condition. A service-
    linked role has the same name in every account, so account B's issue was listed (with its plans) on account A's
    role, while A's ring — by the anchor — showed none."""
    with get_db_session() as db:
        res = db.query(CloudResource).filter_by(id=seed_data["resource_id"]).one()
        other = CloudAccount(name=f"other-{uuid.uuid4().hex[:8]}", provider="aws", credentials={}, regions=["us-east-1"])
        db.add(other); db.flush()
        db.add(HealthIssue(resource_id=res.resource_id, severity="critical", source="test", title="Another account's",
                           description="d", status="open", account_id=other.id,
                           detected_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
        db.add(HealthIssue(resource_id=res.resource_id, severity="low", source="test", title="This account's, by id",
                           description="d", status="open", account_id=res.account_id,
                           detected_at=datetime.now(timezone.utc) + timedelta(minutes=4)))
    data = client.get(f"/api/resources/{seed_data['resource_id']}/issues").json()
    assert [i["title"] for i in data] == ["This account's, by id", "CPU spike", "Disk full"]       # an issue with no account stays


def test_resource_issues_can_be_asked_for_open_ones_only(client, seed_data):
    """A card that says «N open issues» lists the open ones: the newest 20 of any status could leave the one open
    issue out behind twenty closed ones."""
    iid = _anchored(seed_data, "alarm:cpu-high-web-prod")
    data = client.get(f"/api/resources/{seed_data['resource_id']}/issues", params={"open": "true"}).json()
    assert [i["id"] for i in data] == [iid, seed_data["issue1_id"]]                              # the resolved one is left out
    assert [i["resource_ref"] == seed_data["resource_id"] for i in data] == [True, False]        # which tie each one has
    assert len(client.get(f"/api/resources/{seed_data['resource_id']}/issues").json()) == 3      # the default is unchanged


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
    # vpc_id from raw_data should appear (unlinked, since no VPC resource exists)
    assert len(data["network"]) > 0
    assert data["network"][0]["resource_type"] == "VPC"


def test_resource_related_infra(client):
    """Infrastructure resources get 'contains' populated."""
    uid = uuid.uuid4().hex[:8]
    with get_db_session() as db:
        acct = CloudAccount(
            name=f"test-rd-infra-{uid}", provider="aws",
            credentials={"account_id": f"2222{uid[:8].ljust(8, '0')}", "role_arn": "arn:aws:iam::role/t2"},
            regions=["us-east-1"],
        )
        db.add(acct)
        db.flush()
        vpc = CloudResource(
            account_id=acct.id, provider="aws", resource_id="vpc-222", resource_type="VPC",
            name="prod-vpc", region="us-east-1", status="available",
            raw_data={"cidr_block": "10.0.0.0/16"}, tags={},
        )
        ec2 = CloudResource(
            account_id=acct.id, provider="aws", resource_id="i-in-vpc", resource_type="EC2",
            name="server", region="us-east-1", status="running",
            raw_data={"vpc_id": "vpc-222"}, tags={},
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
