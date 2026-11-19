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

    def test_an_account_nobody_could_read_is_not_given_a_score(self, sess_factory):
        """MVP-2.9.0 N20: the report formatted `None` as a number (TypeError) — and before that such a snapshot
        read «100.0 / 100»."""
        with sess_factory() as s:
            s.add(models.SecuritySnapshot(
                account_id="acct-a", provider="aws", overall_score=None,
                category_scores={"iam": None, "network": None},
                cis_results={"cis-1.10": "undetermined", "cis-4.1": "undetermined"}, exposure_paths=[],
                collection_health={"status": "failed", "sources": {
                    "iam": {"ok": False, "error": "AccessDenied (GetCredentialReport)"},
                    "network": {"ok": False, "error": "us-east-1: UnauthorizedOperation (DescribeSecurityGroups)"}}}))
            s.add(models.SecuritySnapshot(
                account_id="acct-b", provider="aws", overall_score=62.5,
                category_scores={"iam": None, "network": 100.0},
                cis_results={"cis-1.10": "undetermined", "cis-4.1": "pass"}, exposure_paths=[],
                collection_health={"status": "partial", "sources": {
                    "iam": {"ok": False, "error": "AccessDenied (GetCredentialReport)"},
                    "network": {"ok": True, "error": ""}}}))
        from agenticops.report.generator import ReportGenerator
        with patch("agenticops.report.generator.get_db_session", sess_factory, create=True):
            md = ReportGenerator().generate_security_review_report(save=False)
        a, b = md.split("## Account: acct-b")
        assert "**Overall score**: not scored — no collection source could be read" in a and "/ 100" not in a
        assert "- iam: AccessDenied (GetCredentialReport)" in a
        assert "| iam | not collected |" in a and "| cis-4.1 | undetermined |" in a
        assert "**Overall score**: 62.5 / 100 (partial collection: a control that could not be read counts as not passed)" in b
        assert "| iam | not collected |" in b and "| network | 100.0 |" in b
        assert "- iam: AccessDenied (GetCredentialReport)" in b and "- network" not in b

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
