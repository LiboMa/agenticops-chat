"""The health-issue endpoints carry the issue's anchor (MVP-2.6.1 Plan E, spec §3.E.2).

IssueDetail reads GET /api/health-issues/{id} for its anchor badge: a resource link, or unanchored / ambiguous
(N candidates) / account level."""
from datetime import datetime

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, CloudAccount, CloudResource, HealthIssue, get_session

OBSERVED = datetime(2026, 9, 28, 1, 2, 3)
CANDIDATES = {"rule": "short_id", "candidates": [{"ref": 1, "account_id": 1, "reason": "short_id"},
                                                 {"ref": 2, "account_id": 1, "reason": "short_id"}]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/detail.db")
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(id=1, name="dev", provider="aws", credentials={}))
    s.add(CloudResource(id=1, account_id=1, provider="aws", region="us-east-1", resource_type="EC2",
                        resource_id="i-1", name="web-1", tags={}, raw_data={}))
    s.add_all([
        HealthIssue(id=1, resource_id="i-1", resource_ref=1, anchor_status="anchored", account_id=1,
                    anchor_candidates={"rule": "resource_id", "candidates": []}, observed_at=OBSERVED,
                    severity="high", source="test", title="anchored", description="d", status="open"),
        HealthIssue(id=2, resource_id="web", anchor_status="ambiguous", anchor_candidates=CANDIDATES,
                    severity="high", source="test", title="ambiguous", description="d", status="open"),
        HealthIssue(id=3, resource_id="r", severity="low", source="test", title="legacy", description="d",
                    status="open"),
    ])
    s.commit()
    s.close()
    from agenticops.web.app import app
    return TestClient(app)  # bare — no `with`, so the lifespan never starts


def _anchor(body):
    return {k: body[k] for k in ("resource_ref", "anchor_status", "anchor_candidates", "observed_at")}


def test_an_anchored_issue_carries_its_resource(client):
    resp = client.get("/api/health-issues/1")
    assert resp.status_code == 200, resp.text
    assert _anchor(resp.json()) == {"resource_ref": 1, "anchor_status": "anchored",
                                    "anchor_candidates": {"rule": "resource_id", "candidates": []},
                                    "observed_at": OBSERVED.isoformat()}


def test_an_ambiguous_issue_carries_its_candidates(client):
    body = client.get("/api/health-issues/2").json()
    assert (body["resource_ref"], body["anchor_status"]) == (None, "ambiguous")
    assert len(body["anchor_candidates"]["candidates"]) == 2


def test_an_issue_never_anchored_reads_as_nulls(client):
    """An issue the resolver has not reached yet (before the backfill): no anchor fields, not a 500."""
    assert _anchor(client.get("/api/health-issues/3").json()) == {
        "resource_ref": None, "anchor_status": None, "anchor_candidates": None, "observed_at": None}


def test_the_list_carries_the_anchor_too(client):
    rows = {r["id"]: r for r in client.get("/api/health-issues").json()}
    assert _anchor(rows[1])["anchor_status"] == "anchored" and rows[2]["anchor_status"] == "ambiguous"
