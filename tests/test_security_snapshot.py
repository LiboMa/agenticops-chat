import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops.models import Base, SecuritySnapshot, SecurityRecommendation


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


class TestSecurityModels:
    def test_snapshot_roundtrip(self, session):
        snap = SecuritySnapshot(
            account_id="533267047935", provider="aws", overall_score=72.5,
            category_scores={"iam": 66.6, "network": 50.0},
            metrics={"no_mfa": 3, "open_sg": 2},
            exposure_paths=[{"resource_id": "i-1", "port": 22, "reachability": "reachable"}],
            cis_results={"cis-1.3": "fail", "cis-4.1": "pass"},
        )
        session.add(snap)
        session.commit()
        got = session.query(SecuritySnapshot).one()
        assert got.overall_score == 72.5
        assert got.category_scores["iam"] == 66.6
        assert got.cis_results["cis-1.3"] == "fail"
        assert got.created_at is not None

    def test_recommendation_fk_nullable(self, session):
        rec = SecurityRecommendation(
            account_id="533267047935", category="network",
            title="Restrict SSH", detail="close 0.0.0.0/0:22",
            evidence_refs=["sg-abc"], severity="high",
            critic_verdict="supported", confidence=0.8, status="open",
        )
        session.add(rec)
        session.commit()
        got = session.query(SecurityRecommendation).one()
        assert got.snapshot_id is None
        assert got.evidence_refs == ["sg-abc"]
        assert got.status == "open"
