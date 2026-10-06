"""GET /api/fix-plans for the Plans hub and PlanDetail (MVP-2.7.0 S3): issue context, target, actions, multi-status
and search in a bounded number of queries; PUT content edits name the hash they were made against."""
import pytest
from starlette.testclient import TestClient
from sqlalchemy import event

from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_session


@pytest.fixture
def client(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/reads.db"
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    models_mod._engine = None


def _seed(status="pending_approval", title="restart nginx", resource="i-0abc123", issue_title="nginx down"):
    s = get_session()
    try:
        issue = HealthIssue(title=issue_title, description="d", severity="high", source="test", status="fix_planned",
                            resource_id=resource, metric_data={"resource_type": "EC2", "region": "us-east-1"})
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title=title, summary="s",
                       status=status, steps=[{"command": "systemctl restart nginx"}])
        s.add(plan); s.flush()
        from agenticops.services.plan_content import stamp_content
        stamp_content(s, plan); s.commit()
        return plan.id, issue.id
    finally:
        s.close()


def test_rows_carry_issue_context_target_and_actions(client):
    pid, iid = _seed()
    row = client.get("/api/fix-plans?kind=fix").json()[0]
    assert row["id"] == pid and row["issue_title"] == "nginx down" and row["issue_status"] == "fix_planned"
    assert row["target"] == {"resource_id": "i-0abc123", "resource_ref": None, "anchor_status": None,
                             "resource_type": "EC2", "region": "us-east-1"}
    assert {a["action"] for a in row["available_actions"]} == {"approve", "reject"}
    assert client.get(f"/api/fix-plans/{pid}").json()["available_actions"] == row["available_actions"]


def test_status_accepts_a_list_and_refuses_a_typo(client):
    a, _ = _seed("draft"); b, _ = _seed("pending_approval"); _seed("rejected")
    ids = {r["id"] for r in client.get("/api/fix-plans?status=draft,pending_approval").json()}
    assert ids == {a, b}
    assert client.get("/api/fix-plans?status=draft,pendng").status_code == 422


def test_q_matches_title_resource_and_ids(client):
    pid, iid = _seed(title="rotate keys", resource="arn:aws:iam::1:user/bob")
    _seed(title="other", resource="i-zzz")
    assert [r["id"] for r in client.get("/api/fix-plans?q=rotate").json()] == [pid]
    assert [r["id"] for r in client.get("/api/fix-plans?q=user/bob").json()] == [pid]
    assert pid in [r["id"] for r in client.get(f"/api/fix-plans?q=I%23{iid}").json()]
    assert client.get("/api/fix-plans?q=100%25_").status_code == 200   # LIKE wildcards are escaped


def test_the_list_is_a_bounded_number_of_queries(client):
    for _ in range(12):
        _seed()
    import agenticops.models as models_mod
    count = {"n": 0}
    def on_exec(*_a, **_k):
        count["n"] += 1
    event.listen(models_mod.get_engine(), "before_cursor_execute", on_exec)
    try:
        assert len(client.get("/api/fix-plans").json()) == 12
    finally:
        event.remove(models_mod.get_engine(), "before_cursor_execute", on_exec)
    assert count["n"] <= 6, count


def test_a_content_edit_needs_the_hash_it_was_made_against(client):
    pid, _ = _seed()
    h = client.get(f"/api/fix-plans/{pid}").json()["content_hash"]
    assert client.put(f"/api/fix-plans/{pid}", json={"steps": [{"command": "true"}]}).status_code == 422
    assert client.put(f"/api/fix-plans/{pid}", json={"steps": [{"command": "true"}], "content_hash": "stale"}).status_code == 409
    r = client.put(f"/api/fix-plans/{pid}", json={"steps": [{"command": "true"}], "content_hash": h})
    assert r.status_code == 200 and r.json()["content_hash"] != h
    assert client.put(f"/api/fix-plans/{pid}", json={"status": "rejected"}).status_code == 200  # alias needs no hash


def test_q_prefix_names_what_the_number_is(client):
    """Deferred minor M4: I#n is an issue, P#n / #n a plan, a bare number either."""
    s = get_session()
    s.add(HealthIssue(title="no plan", description="d", severity="low", source="test", status="open", resource_id="r"))
    s.commit(); s.close()                      # issue ids now run one ahead of plan ids
    a, a_issue = _seed(title="first")
    b, b_issue = _seed(title="second")
    assert a_issue == b and a != a_issue       # plan b's id is plan a's issue id: the prefix must tell them apart
    assert [r["id"] for r in client.get(f"/api/fix-plans?q=I%23{a_issue}").json()] == [a]
    assert [r["id"] for r in client.get(f"/api/fix-plans?q=P%23{b}").json()] == [b]
    assert [r["id"] for r in client.get(f"/api/fix-plans?q=%23{b}").json()] == [b]
    assert sorted(r["id"] for r in client.get(f"/api/fix-plans?q={b}").json()) == sorted({a, b})


def test_q_escapes_like_wildcards(client):
    """Deferred minor M4: `_` and `%` are literal, not any character."""
    _seed(title="restart nginx")
    assert client.get("/api/fix-plans?q=restart_nginx").json() == []
    assert client.get("/api/fix-plans?q=rest%25art").json() == []
    assert len(client.get("/api/fix-plans?q=restart nginx").json()) == 1


def test_a_plan_stored_without_a_hash_can_still_be_edited_after_a_reload(client):
    """Deferred minor M5: like approve, the first refused edit stamps the missing hash so the reload has one to send."""
    pid, _ = _seed()
    s = get_session(); s.query(FixPlan).filter_by(id=pid).update({"content_hash": None}); s.commit(); s.close()
    assert client.get(f"/api/fix-plans/{pid}").json()["content_hash"] is None
    r = client.put(f"/api/fix-plans/{pid}", json={"steps": [{"command": "true"}], "content_hash": "anything"})
    assert r.status_code == 409
    h = client.get(f"/api/fix-plans/{pid}").json()["content_hash"]
    assert h
    assert client.put(f"/api/fix-plans/{pid}", json={"steps": [{"command": "true"}], "content_hash": h}).status_code == 200


def test_an_issue_with_non_dict_metric_data_still_lists(client):
    """Deferred minor M6: legacy metric_data that is not an object never breaks the list."""
    pid, iid = _seed()
    s = get_session(); s.query(HealthIssue).filter_by(id=iid).update({"metric_data": ["legacy"]}); s.commit(); s.close()
    r = client.get("/api/fix-plans")
    assert r.status_code == 200 and r.json()[0]["target"]["resource_type"] is None
