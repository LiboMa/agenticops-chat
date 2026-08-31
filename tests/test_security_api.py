# tests/test_security_api.py
"""Stage 6: security service queries + /api/security/* contract."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops import models


@pytest.fixture
def sess_factory():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def _sess():
        s = Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return _sess


def _seed(sess_factory):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    with sess_factory() as s:
        s.add(models.SecuritySnapshot(
            account_id="acct-a", provider="aws", overall_score=60.0,
            created_at=old, category_scores={"iam": 50.0}, exposure_paths=[]))
        s.add(models.SecuritySnapshot(
            account_id="acct-a", provider="aws", overall_score=75.0,
            category_scores={"iam": 66.6},
            exposure_paths=[{"resource_id": "sg-1", "port": 22,
                             "path": ["internet", "sn-1", "i-1:22"],
                             "reachability": "reachable"}]))
        s.add(models.HealthIssue(
            resource_id="sg-1", severity="high", source="security_posture",
            title="[cis-4.1] open ssh", description="", status="open",
            detected_by="security_posture", issue_type="security_exposure",
            metric_data={"reachability": "reachable"}))
        s.add(models.SecurityRecommendation(
            account_id="acct-a", category="network", title="Restrict SSH",
            detail="close it", evidence_refs=["sg-1"], severity="high",
            critic_verdict="supported", confidence=0.9, status="open"))


class TestSecurityService:
    def test_summary_latest_snapshot_and_counts(self, sess_factory, monkeypatch):
        from agenticops.services import security_service as svc
        monkeypatch.setattr(svc, "get_db_session", sess_factory)
        _seed(sess_factory)
        out = svc.security_summary()
        assert len(out["accounts"]) == 1
        acct = out["accounts"][0]
        assert acct["overall_score"] == 75.0  # latest, not the 60.0 one
        assert acct["reachable_paths"] == 1
        assert acct["open_findings"] == 1

    def test_trend_ascending(self, sess_factory, monkeypatch):
        from agenticops.services import security_service as svc
        monkeypatch.setattr(svc, "get_db_session", sess_factory)
        _seed(sess_factory)
        pts = svc.security_trend(days=30, account="acct-a")
        assert [p["overall_score"] for p in pts] == [60.0, 75.0]

    def test_findings_carry_reachability(self, sess_factory, monkeypatch):
        from agenticops.services import security_service as svc
        monkeypatch.setattr(svc, "get_db_session", sess_factory)
        _seed(sess_factory)
        rows = svc.security_findings()
        assert rows[0]["reachability"] == "reachable"
        assert rows[0]["detected_by"] == "security_posture"

    def test_recommendations_filter_by_status(self, sess_factory, monkeypatch):
        from agenticops.services import security_service as svc
        monkeypatch.setattr(svc, "get_db_session", sess_factory)
        _seed(sess_factory)
        assert len(svc.security_recommendations(status="open")) == 1
        assert svc.security_recommendations(status="dismissed") == []

    def test_attack_paths_flattened_with_account(self, sess_factory, monkeypatch):
        from agenticops.services import security_service as svc
        monkeypatch.setattr(svc, "get_db_session", sess_factory)
        _seed(sess_factory)
        paths = svc.attack_paths()
        assert paths == [{"account_id": "acct-a", "resource_id": "sg-1", "port": 22,
                          "path": ["internet", "sn-1", "i-1:22"],
                          "reachability": "reachable"}]
