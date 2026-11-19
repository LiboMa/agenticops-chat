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


A, B = 1, 2      # cloud_accounts ids; snapshots and recommendations name an account by its NAME


def _day(days_ago: int, hour: int = 12) -> datetime:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days_ago) + timedelta(hours=hour)


def _snap(account="acct-a", score=75.0, at=None, health=None, paths=(), categories=None):
    return models.SecuritySnapshot(
        account_id=account, provider="aws", overall_score=score, created_at=at or _day(0),
        category_scores={"iam": 66.6} if categories is None else categories, exposure_paths=list(paths),
        collection_health=health)


def _finding(account_id=A, severity="high", status="open", title="[cis-4.1] open ssh", resource_id="sg-1",
             detected_by="security_posture", reach="reachable", last_seen=None, resource_ref=None):
    return models.HealthIssue(
        resource_id=resource_id, severity=severity, source=detected_by, title=title, description="", status=status,
        detected_by=detected_by, issue_type="security_exposure", account_id=account_id, resource_ref=resource_ref,
        metric_data={} if reach is None else {"reachability": reach}, last_seen=last_seen or _day(0))


def _seed(sess_factory):
    with sess_factory() as s:
        s.add_all([
            models.CloudAccount(id=A, name="acct-a", provider="aws", regions=["us-east-1"],
                                credentials={"role_arn": "arn:aws:iam::111111111111:role/x"}),
            models.CloudAccount(id=B, name="acct-cn", provider="aws", regions=["cn-north-1"], credentials={}),
        ])
        s.add(_snap(score=60.0, at=_day(0, 1), categories={"iam": 50.0}))
        s.add(_snap(score=75.0, at=_day(0, 3), paths=[{"resource_id": "sg-1", "port": 22,
                                                       "path": ["internet", "sn-1", "i-1:22"],
                                                       "reachability": "reachable"}]))
        s.add(_finding())
        s.add(models.SecurityRecommendation(
            account_id="acct-a", category="network", title="Restrict SSH",
            detail="close it", evidence_refs=["sg-1"], severity="high",
            critic_verdict="supported", confidence=0.9, status="open"))


@pytest.fixture
def svc(sess_factory, monkeypatch):
    from agenticops.services import security_service
    monkeypatch.setattr(security_service, "get_db_session", sess_factory)
    return security_service


class TestSummary:
    def test_latest_snapshot_and_its_account(self, svc, sess_factory):
        _seed(sess_factory)
        out = svc.security_summary()
        assert len(out["accounts"]) == 1
        acct = out["accounts"][0]
        assert acct["overall_score"] == 75.0  # latest, not the 60.0 one
        assert (acct["account_id"], acct["account_name"], acct["partition"]) == (A, "acct-a", "aws")
        assert acct["reachable_paths"] == 1 and acct["open_findings"] == 1
        assert acct["created_at"].endswith("Z")                 # a time is said in UTC
        assert (acct["collection"], acct["collection_errors"]) == (None, [])   # written before N20: as it was

    def test_each_account_counts_its_own_open_findings(self, svc, sess_factory):
        """The defect: the global count was copied onto every account's card."""
        _seed(sess_factory)
        with sess_factory() as s:
            s.add(_snap(account="acct-cn", score=50.0))
            s.add_all([_finding(account_id=B), _finding(account_id=B, severity="low"),
                       _finding(account_id=B, status="resolved"),            # closed: not counted
                       _finding(account_id=B, detected_by="detect_agent"),   # not a security finding
                       _finding(account_id=None)])                           # nobody's: said apart
        out = svc.security_summary()
        assert {a["account_name"]: a["open_findings"] for a in out["accounts"]} == {"acct-a": 1, "acct-cn": 2}
        assert out["unassigned_open_findings"] == 1
        assert [a["account_name"] for a in out["accounts"]] == ["acct-a", "acct-cn"]      # by name
        assert out["accounts"][1]["partition"] == "aws-cn"
        for a in out["accounts"]:            # the acceptance rule: the card's number is the list's total
            assert svc.security_findings(account_id=a["account_id"])["total"] == a["open_findings"]

    def test_one_account(self, svc, sess_factory):
        _seed(sess_factory)
        with sess_factory() as s:
            s.add(_snap(account="acct-cn", score=50.0))
        assert [a["account_name"] for a in svc.security_summary(account_id=B)["accounts"]] == ["acct-cn"]
        assert svc.security_summary(account_id=999)["accounts"] == []

    def test_an_account_nobody_could_read_has_no_score(self, svc, sess_factory):
        _seed(sess_factory)
        failed = {"status": "failed", "sources": {"iam": {"ok": False, "error": "AccessDenied (GetCredentialReport)"},
                                                  "network": {"ok": False, "error": "us-east-1: Timeout"}}}
        with sess_factory() as s:
            s.add(_snap(score=None, at=_day(0, 5), health=failed, categories={"iam": None}))
        acct = svc.security_summary()["accounts"][0]
        assert acct["overall_score"] is None and acct["collection"] == "failed"
        assert acct["collection_errors"] == [{"source": "iam", "error": "AccessDenied (GetCredentialReport)"},
                                             {"source": "network", "error": "us-east-1: Timeout"}]
        assert acct["category_scores"] == {"iam": None}

    def test_a_snapshot_of_an_account_that_is_gone_is_listed_by_its_name(self, svc, sess_factory):
        with sess_factory() as s:
            s.add(_snap(account="removed"))
        acct = svc.security_summary()["accounts"][0]
        assert (acct["account_id"], acct["account_name"], acct["partition"], acct["open_findings"]) == (None, "removed", None, 0)

    @pytest.mark.parametrize("regions, creds, want", [
        (["us-east-1"], {}, "aws"), (["cn-northwest-1"], {}, "aws-cn"),
        ([], {"role_arn": "arn:aws-cn:iam::1:role/x"}, "aws-cn"),
        (["us-gov-west-1"], {}, "aws-us-gov"), ([], {"role_arn": "arn:aws-us-gov:iam::1:role/x"}, "aws-us-gov"),
        (None, None, "aws"),
    ])
    def test_partition(self, svc, regions, creds, want):
        assert svc.partition_of(regions, creds) == want


class TestTrend:
    def test_one_point_a_day_per_account_the_days_last_score(self, svc, sess_factory):
        _seed(sess_factory)                                  # acct-a today: 60.0 at 01:00, 75.0 at 03:00
        partial = {"status": "partial", "sources": {}}
        with sess_factory() as s:
            s.add_all([_snap(score=40.0, at=_day(2, 9)), _snap(score=45.0, at=_day(2, 23), health=partial),
                       _snap(account="acct-cn", score=90.0, at=_day(1))])
        out = svc.security_trend(days=7)
        assert out["days"] == 7
        by = {a["account_name"]: a for a in out["accounts"]}
        assert list(by) == ["acct-a", "acct-cn"] and by["acct-cn"]["account_id"] == B
        day = lambda n: _day(n).strftime("%Y-%m-%d")                                    # noqa: E731
        assert by["acct-a"]["points"] == [{"day": day(2), "score": 45.0, "partial": True},
                                          {"day": day(0), "score": 75.0, "partial": False}]   # no point for day 1
        assert by["acct-cn"]["points"] == [{"day": day(1), "score": 90.0, "partial": False}]

    def test_a_snapshot_without_a_score_draws_no_point(self, svc, sess_factory):
        failed = {"status": "failed", "sources": {}}
        with sess_factory() as s:
            s.add_all([models.CloudAccount(id=A, name="acct-a", provider="aws"),
                       _snap(score=80.0, at=_day(1, 6)), _snap(score=None, at=_day(1, 20), health=failed),
                       _snap(score=None, at=_day(0, 6), health=failed)])
        points = svc.security_trend(days=7)["accounts"][0]["points"]
        assert points == [{"day": _day(1).strftime("%Y-%m-%d"), "score": 80.0, "partial": False}]   # that day's last SCORE

    def test_an_account_with_snapshots_and_no_score_is_listed_with_no_points(self, svc, sess_factory):
        with sess_factory() as s:
            s.add(_snap(score=None, health={"status": "failed", "sources": {}}))
        assert svc.security_trend(days=7)["accounts"] == [{"account_id": None, "account_name": "acct-a", "points": []}]

    def test_the_window_is_whole_utc_days(self, svc, sess_factory):
        with sess_factory() as s:
            s.add_all([_snap(score=10.0, at=_day(6, 0)), _snap(score=20.0, at=_day(7, 23))])
        points = svc.security_trend(days=7)["accounts"][0]["points"]
        assert [p["score"] for p in points] == [10.0]                # today and the six days before it: 7 at most

    def test_one_account_and_the_three_ranges(self, svc, sess_factory):
        _seed(sess_factory)
        with sess_factory() as s:
            s.add(_snap(account="acct-cn", score=90.0))
        assert [a["account_name"] for a in svc.security_trend(days=30, account_id=B)["accounts"]] == ["acct-cn"]
        assert svc.security_trend(days=90)["days"] == 90
        with pytest.raises(ValueError):
            svc.security_trend(days=14)


class TestFindings:
    def _many(self, sess_factory):
        with sess_factory() as s:
            s.add_all([
                models.CloudAccount(id=A, name="acct-a", provider="aws"),
                models.CloudAccount(id=B, name="acct-cn", provider="aws", regions=["cn-north-1"]),
                models.CloudResource(id=31, account_id=A, provider="aws", region="us-west-2", resource_type="SecurityGroup",
                                     resource_id="sg-1", name="sg-1", tags={}, raw_data={}),
            ])
            s.add_all([
                _finding(severity="low", title="old low", last_seen=_day(3)),
                _finding(severity="critical", title="crit older", last_seen=_day(2)),
                _finding(severity="critical", title="crit newer", last_seen=_day(1), resource_ref=31),
                _finding(severity="high", title="cn 100% open", account_id=B, reach="undetermined", resource_id="sg-cn"),
                _finding(severity="medium", title="closed one", status="resolved", reach=None),
                _finding(severity="high", title="evidence object", reach={"verdict": "?"}, account_id=None,
                         last_seen=_day(1)),
                _finding(severity="high", title="not security", detected_by="detect_agent"),
            ])

    def test_open_by_default_most_severe_first_then_newest(self, svc, sess_factory):
        self._many(sess_factory)
        out = svc.security_findings()
        assert out["total"] == 5
        assert [i["title"] for i in out["items"]] == ["crit newer", "crit older", "cn 100% open", "evidence object", "old low"]

    def test_a_row_says_where_it_is_and_which_issue_it_is(self, svc, sess_factory):
        self._many(sess_factory)
        first = svc.security_findings()["items"][0]
        assert first["issue_ref"] == f"I#{first['id']}"
        assert (first["account_id"], first["account_name"], first["region"], first["resource_type"]) == (A, "acct-a", "us-west-2", "SecurityGroup")
        assert first["last_seen"].endswith("Z") and first["reachability"] == "reachable"
        nobody = next(i for i in svc.security_findings()["items"] if i["title"] == "evidence object")
        assert (nobody["account_id"], nobody["account_name"], nobody["region"], nobody["resource_type"]) == (None, None, None, None)
        assert nobody["reachability"] == "undetermined"       # an evidence object reads as undetermined, as on the page

    def test_filters(self, svc, sess_factory):
        self._many(sess_factory)
        titles = lambda **kw: [i["title"] for i in svc.security_findings(**kw)["items"]]      # noqa: E731
        assert titles(account_id=B) == ["cn 100% open"]
        assert titles(severity=["critical", "low"]) == ["crit newer", "crit older", "old low"]
        assert titles(status="all", severity=["medium"]) == ["closed one"]
        assert titles(reachability="undetermined") == ["cn 100% open", "evidence object"]
        assert titles(reachability="reachable", severity=["critical"]) == ["crit newer", "crit older"]
        assert titles(q="100%") == ["cn 100% open"]           # % is a character, not a wildcard
        assert titles(q="SG-CN") == ["cn 100% open"]          # the resource id too, any case
        assert titles(q="_") == []
        crit = svc.security_findings()["items"][0]["id"]
        assert titles(q=f"I#{crit}") == ["crit newer"] and titles(q=str(crit)) == ["crit newer"]

    def test_the_total_is_of_the_filter_not_of_the_page(self, svc, sess_factory):
        self._many(sess_factory)
        page = svc.security_findings(limit=2, offset=2)
        assert page["total"] == 5 and [i["title"] for i in page["items"]] == ["cn 100% open", "evidence object"]
        page = svc.security_findings(reachability="reachable", limit=1, offset=1)      # the filter done in Python pages too
        assert page["total"] == 3 and [i["title"] for i in page["items"]] == ["crit older"]

    @pytest.mark.parametrize("kw", [{"status": "closed"}, {"severity": ["urgent"]}, {"reachability": "maybe"}])
    def test_an_unknown_filter_value_is_refused(self, svc, sess_factory, kw):
        with pytest.raises(ValueError):
            svc.security_findings(**kw)


class TestRecommendationsAndPaths:
    def test_recommendations_filter_by_status_and_account(self, svc, sess_factory):
        _seed(sess_factory)
        assert len(svc.security_recommendations(status="open")) == 1
        assert svc.security_recommendations(status="dismissed") == []
        assert len(svc.security_recommendations(status="open", account_id=A)) == 1
        assert svc.security_recommendations(status="open", account_id=B) == []
        row = svc.security_recommendations()[0]
        assert (row["account_id"], row["account_name"]) == (A, "acct-a")

    def test_attack_paths_flattened_with_account(self, svc, sess_factory):
        _seed(sess_factory)
        paths = svc.attack_paths()
        assert paths == [{"account_id": A, "account_name": "acct-a", "resource_id": "sg-1", "port": 22,
                          "path": ["internet", "sn-1", "i-1:22"],
                          "reachability": "reachable"}]
        assert svc.attack_paths(account_id=B) == [] and len(svc.attack_paths(account_id=A)) == 1


from fastapi.testclient import TestClient

from agenticops.web.app import app

client = TestClient(app)


class TestSecurityApiContract:
    def test_summary_endpoint(self):
        fake = {"accounts": [], "generated_at": "2026-08-31T00:00:00+00:00"}
        with patch("agenticops.services.security_service.security_summary", return_value=fake) as m:
            r = client.get("/api/security/summary?account_id=2")
        assert r.status_code == 200
        assert r.json() == fake and m.call_args.kwargs == {"account_id": 2}

    def test_trend_params_forwarded(self):
        with patch("agenticops.services.security_service.security_trend",
                   return_value={"days": 7, "accounts": []}) as m:
            r = client.get("/api/security/trend?days=7&account_id=2")
        assert r.status_code == 200
        assert m.call_args.kwargs == {"days": 7, "account_id": 2}

    def test_trend_takes_three_ranges(self):
        assert client.get("/api/security/trend?days=14").status_code == 422
        with patch("agenticops.services.security_service.security_trend", return_value={"days": 30, "accounts": []}) as m:
            assert client.get("/api/security/trend").status_code == 200
        assert m.call_args.kwargs == {"days": 30, "account_id": None}

    def test_findings_params_forwarded(self):
        with patch("agenticops.services.security_service.security_findings",
                   return_value={"items": [], "total": 0}) as m:
            r = client.get("/api/security/findings?account_id=2&severity=critical,high&status=all"
                           "&reachability=reachable&q=ssh&limit=20&offset=40")
        assert r.status_code == 200 and r.json() == {"items": [], "total": 0}
        assert m.call_args.kwargs == {"account_id": 2, "severity": ["critical", "high"], "status": "all",
                                      "reachability": "reachable", "q": "ssh", "limit": 20, "offset": 40}

    def test_findings_defaults(self):
        with patch("agenticops.services.security_service.security_findings",
                   return_value={"items": [], "total": 0}) as m:
            assert client.get("/api/security/findings").status_code == 200
        assert m.call_args.kwargs == {"account_id": None, "severity": None, "status": "open", "reachability": None,
                                      "q": None, "limit": 50, "offset": 0}

    @pytest.mark.parametrize("query", ["severity=urgent", "status=closed", "reachability=maybe", "limit=0", "limit=201",
                                       "offset=-1", "account_id=x", "q=" + "x" * 201])
    def test_findings_refuse_what_they_cannot_read(self, query):
        r = client.get(f"/api/security/findings?{query}")
        assert r.status_code == 422, r.text

    def test_recommendations_and_attack_paths_take_the_account(self):
        with patch("agenticops.services.security_service.security_recommendations", return_value=[]) as recs, \
             patch("agenticops.services.security_service.attack_paths", return_value=[]) as paths:
            assert client.get("/api/security/recommendations?status=open&account_id=2").status_code == 200
            assert client.get("/api/security/attack-paths?account_id=2").status_code == 200
        assert recs.call_args.kwargs == {"status": "open", "limit": 100, "account_id": 2}
        assert paths.call_args.kwargs == {"account_id": 2}

    def test_the_handlers_are_plain_functions(self):
        """One process: a blocking database read never runs inside an `async def` handler (MVP-2.7.0 S1)."""
        import inspect

        from agenticops.web.routers import security
        handlers = [r.endpoint for r in security.router.routes]
        assert len(handlers) == 5 and not any(inspect.iscoroutinefunction(h) for h in handlers)

    def test_pipeline_options_include_security_jobs(self):
        r = client.get("/api/schedules/pipeline-options")
        assert r.status_code == 200
        pipes = r.json()["pipelines"]
        assert "SecurityPostureSnapshot" in pipes
        assert "SecurityIncrementalPoll" in pipes
