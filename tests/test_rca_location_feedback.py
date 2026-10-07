"""Location verdict + location stats (MVP-2.6.1 Plan C Task 5, spec §3.C.4)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.models import Base, HealthIssue, RCAResult, get_session
from agenticops.services import rca_location as rl
from agenticops.web.app import app
from agenticops.web.deps import current_actor

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
LOCATION = {"candidates": [{"ref": 3, "rank": 1, "type": "EC2", "name": "i-1", "resource_id": "i-1",
                            "supporting": ["E1"], "refuting": []}], "path": [], "dropped": []}


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/feedback.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    app.dependency_overrides.pop(current_actor, None)
    models_mod._engine = None


def _issue(s, *, resource_id="i-1", ref=3, anchor_status="anchored", detected_at=None):
    issue = HealthIssue(resource_id=resource_id, resource_ref=ref, anchor_status=anchor_status, account_id=1,
                        severity="high", status="root_cause_identified", source="test", title="t",
                        description="d", issue_type="cpu_spike", detected_at=detected_at or NOW)
    s.add(issue)
    s.flush()
    return issue.id


def _rca(s, issue_id, status="valid", verdict=None, created_at=None):
    rca = RCAResult(health_issue_id=issue_id, root_cause="sg change", confidence=0.8,
                    location=LOCATION if status in ("valid", "partial") else None, location_status=status,
                    location_verdict=verdict, created_at=created_at or NOW)
    s.add(rca)
    s.commit()
    return rca.id


def _post(issue_id, **body):
    return TestClient(app).post(f"/api/health-issues/{issue_id}/rca-feedback", json=body)


# ── the verdict ───────────────────────────────────────────────────────


def test_location_verdict_alone_names_the_anonymous_judge(db):
    iid = _issue(db)
    rid = _rca(db, iid)
    resp = _post(iid, location_verdict="correct", location_verdict_by="user:someone-else")
    assert resp.status_code == 201
    assert resp.json() == {"rca_id": rid, "verdict": None, "location_verdict": "correct",
                           "message": f"Human location verdict 'correct' recorded on RCA #{rid}"}
    db.expire_all()
    rca = db.get(RCAResult, rid)
    assert (rca.location_verdict, rca.location_verdict_by) == ("correct", "web:anonymous")
    assert rca.location_verdict_at is not None
    assert (rca.human_verdict, rca.verified_at) == (None, None)


def test_the_judge_is_the_session_actor(db):
    iid = _issue(db)
    rid = _rca(db, iid, status="partial")
    app.dependency_overrides[current_actor] = lambda: Actor("user", "ops@example.com")
    resp = _post(iid, verdict="correct", location_verdict="partial")
    assert resp.status_code == 201
    assert resp.json()["message"] == f"Human verdict 'correct' and location verdict 'partial' recorded on RCA #{rid}"
    db.expire_all()
    rca = db.get(RCAResult, rid)
    assert (rca.human_verdict, rca.location_verdict, rca.location_verdict_by) == (
        "correct", "partial", "user:ops@example.com")


def test_the_verdict_alone_leaves_the_location_untouched(db):
    iid = _issue(db)
    rid = _rca(db, iid, status="absent")
    assert _post(iid, verdict="correct").status_code == 201
    db.expire_all()
    rca = db.get(RCAResult, rid)
    assert (rca.human_verdict, rca.location_verdict, rca.location_verdict_by) == ("correct", None, None)


@pytest.mark.parametrize("body", [{}, {"note": "x"}, {"location_verdict": "maybe"}, {"verdict": "partial"}])
def test_a_body_without_a_legal_verdict_is_rejected(db, body):
    iid = _issue(db)
    _rca(db, iid)
    assert _post(iid, **body).status_code == 422


@pytest.mark.parametrize("status", ["absent", "invalid"])
def test_a_location_with_no_candidate_cannot_be_judged(db, status):
    iid = _issue(db)
    rid = _rca(db, iid, status=status)
    resp = _post(iid, verdict="correct", location_verdict="correct")
    assert resp.status_code == 409 and f"RCA #{rid} has no root-cause location to judge" in resp.json()["detail"]
    db.expire_all()
    assert db.get(RCAResult, rid).human_verdict is None  # nothing is written


# ── the stats ─────────────────────────────────────────────────────────


def test_stats_with_nothing_to_divide_by(db):
    out = rl.location_stats(db, 30)
    assert out == {"days": 30, "top1": None, "judged": 0, "anchoring_rate": None, "issues_with_resource_id": 0,
                   "anchor_status_counts": {"anchored": 0, "account_level": 0, "ambiguous": 0, "unanchored": 0},
                   "location_status_counts": {"valid": 0, "partial": 0, "invalid": 0, "absent": 0}}


def test_stats_count_the_window_only(db):
    a = _issue(db)
    _issue(db, anchor_status=None)                                  # legacy with a ref → anchored
    _issue(db, ref=None, anchor_status="account_level")
    _issue(db, ref=None, anchor_status="ambiguous")
    _issue(db, ref=None, anchor_status=None)                        # legacy without a ref → unanchored
    _issue(db, resource_id="", ref=None, anchor_status="unanchored")  # names no resource: not in the rate
    old = _issue(db, detected_at=NOW - timedelta(days=40))
    _rca(db, a, "valid", "correct")
    _rca(db, a, "valid", "correct")
    _rca(db, a, "partial", "partial")
    _rca(db, a, "partial", "incorrect")
    _rca(db, a, "invalid")
    _rca(db, a, "absent")
    _rca(db, old, "valid", "incorrect", created_at=NOW - timedelta(days=40))
    out = rl.location_stats(db, 30)
    assert (out["judged"], out["top1"]) == (4, 0.5)
    assert out["location_status_counts"] == {"valid": 2, "partial": 2, "invalid": 1, "absent": 1}
    assert out["anchor_status_counts"] == {"anchored": 2, "account_level": 1, "ambiguous": 1, "unanchored": 2}
    assert (out["issues_with_resource_id"], out["anchoring_rate"]) == (5, 0.6)
    wide = rl.location_stats(db, 60)
    assert (wide["judged"], wide["top1"], wide["anchor_status_counts"]["anchored"]) == (5, 0.4, 3)


def test_stats_endpoint(db):
    _rca(db, _issue(db), "valid", "correct")
    resp = TestClient(app).get("/api/rca/location-stats", params={"days": 7})
    assert resp.status_code == 200 and resp.json() == rl.location_stats(db, 7)
    assert resp.json()["top1"] == 1.0
    assert TestClient(app).get("/api/rca/location-stats").json()["days"] == 30
    for bad in (0, 366):
        assert TestClient(app).get("/api/rca/location-stats", params={"days": bad}).status_code == 422
