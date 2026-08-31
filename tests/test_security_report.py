# tests/test_security_report.py
"""Stage 6: security-review report generation."""
from contextlib import contextmanager
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


class TestSecurityReviewReport:
    def test_markdown_contains_scores_and_paths(self, sess_factory):
        with sess_factory() as s:
            s.add(models.SecuritySnapshot(
                account_id="acct-a", provider="aws", overall_score=62.5,
                category_scores={"iam": 33.3, "network": 50.0},
                cis_results={"cis-1.10": "fail", "cis-4.1": "fail"},
                exposure_paths=[{"resource_id": "sg-1", "port": 22,
                                 "path": ["internet", "sn-1", "i-1:22"],
                                 "reachability": "reachable"}]))
            s.add(models.SecurityRecommendation(
                account_id="acct-a", category="network", title="Restrict SSH",
                detail="close 0.0.0.0/0:22", evidence_refs=["sg-1"], severity="high",
                critic_verdict="supported", confidence=0.9, status="open"))
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        with patch("agenticops.report.generator.get_db_session", sess_factory, create=True):
            md = gen.generate_security_review_report(save=False)
        assert "# Security Review Report" in md
        assert "62.5" in md
        assert "cis-4.1" in md
        assert "sg-1" in md
        assert "Restrict SSH" in md

    def test_no_snapshot_graceful(self, sess_factory):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        with patch("agenticops.report.generator.get_db_session", sess_factory, create=True):
            md = gen.generate_security_review_report(save=False)
        assert "No security snapshot available" in md

    def test_schema_accepts_type(self):
        from agenticops.web.schemas import ReportGenerateRequest
        req = ReportGenerateRequest(report_type="security-review")
        assert req.report_type == "security-review"

    def test_report_tools_accept_type(self):
        import inspect
        from agenticops.tools import report_tools
        src = inspect.getsource(report_tools)
        assert "security-review" in src
