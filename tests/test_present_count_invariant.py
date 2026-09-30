"""One "present" definition everywhere (MVP-2.6.1 Plan B Task 11): every resource count and list the user or an
agent sees counts only rows with absent_since IS NULL, so the numbers agree across the API, the Dashboard, the
CLI, reports and agent tools. Lookups by id still return an absent row, and it carries absent_since."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, get_session

A, B = 1, 2
T0 = datetime(2026, 9, 1, 12, 0)
GONE = datetime(2026, 9, 2, 12, 0)
PRESENT_IDS = {"i-1live", "sg-1live", "i-2live", "sg-2live"}


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401  (change_service writes audit rows)
    from agenticops.config import settings

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/present.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([
        CloudAccount(id=A, name="dev", provider="aws", is_enabled=True, credentials={"account_id": "111111111111"},
                     regions=["us-east-1"]),
        CloudAccount(id=B, name="cn", provider="aws", is_enabled=True, credentials={"account_id": "222222222222"},
                     regions=["us-east-1"]),
    ])
    # 2 accounts x 2 types x (live, gone): 8 rows, 4 present
    for acct in (A, B):
        for rtype, prefix in (("EC2", "i"), ("SecurityGroup", "sg")):
            for state in ("live", "gone"):
                rid = f"{prefix}-{acct}{state}"
                s.add(CloudResource(account_id=acct, provider="aws", region="us-east-1", resource_type=rtype,
                                    resource_id=rid, name=rid, tags={}, raw_data={}, status="running",
                                    scanned_at=T0, absent_since=GONE if state == "gone" else None))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _pk(s, rid):
    return s.query(CloudResource).filter_by(resource_id=rid).one().id


@pytest.fixture
def client(db):
    from agenticops.web.app import app

    return TestClient(app)


def test_stats_list_and_type_counts_agree(client):
    stats = client.get("/api/stats").json()
    listing = client.get("/api/resources").json()
    counts = client.get("/api/resources/type-counts").json()
    assert stats["total_resources"] == listing["total"] == sum(counts.values()) == 4
    assert counts == {"EC2": 2, "SecurityGroup": 2}
    assert {r["resource_id"] for r in listing["items"]} == PRESENT_IDS
    assert all(r["absent_since"] is None for r in listing["items"])


def test_include_absent_shows_every_row(client):
    listing = client.get("/api/resources", params={"include_absent": "true"}).json()
    counts = client.get("/api/resources/type-counts", params={"include_absent": "true"}).json()
    assert listing["total"] == sum(counts.values()) == 8
    assert {r["resource_id"] for r in listing["items"] if r["absent_since"]} == {
        "i-1gone", "sg-1gone", "i-2gone", "sg-2gone"}


def test_filters_still_apply_to_present_rows(client):
    listing = client.get("/api/resources", params={"account_id": A, "type": "EC2"}).json()
    assert [r["resource_id"] for r in listing["items"]] == ["i-1live"]


def test_detail_still_returns_an_absent_row(client, db):
    body = client.get(f"/api/resources/{_pk(db, 'i-1gone')}").json()
    assert body["resource_id"] == "i-1gone"
    assert body["absent_since"].startswith("2026-09-02")
    assert body["scanned_at"].startswith("2026-09-01")


def test_related_contains_skips_absent_rows(client, db):
    db.add(CloudResource(account_id=A, provider="aws", region="us-east-1", resource_type="VPC", resource_id="vpc-1",
                         name="vpc-1", tags={}, raw_data={}, status="available"))
    for rid, absent in (("subnet-live", None), ("subnet-gone", GONE)):
        db.add(CloudResource(account_id=A, provider="aws", region="us-east-1", resource_type="Subnet",
                             resource_id=rid, name=rid, tags={}, raw_data={"vpc_id": "vpc-1"}, status="available",
                             absent_since=absent))
    db.commit()
    body = client.get(f"/api/resources/{_pk(db, 'vpc-1')}/related").json()
    assert [c["resource_id"] for c in body["contains"]] == ["subnet-live"]


def test_global_search_skips_absent_rows(client):
    body = client.get("/api/search", params={"q": "i-1", "types": "resources"}).json()
    assert [r["title"] for r in body["results"]["resources"]] == ["i-1live"]


def test_cli_status_counts_present_rows(db):
    from agenticops.cli.main import _slash_status

    assert "Resources: 4 tracked" in _slash_status(MagicMock(), [])


def test_inventory_report_counts_present_rows(db):
    from agenticops.report.generator import ReportGenerator

    report = ReportGenerator().generate_inventory_report(save=False)
    assert "**Total Resources**: 4" in report
    assert "i-1gone" not in report


def test_agent_inventory_tools(db):
    import json

    from agenticops.tools.metadata_tools import get_managed_resources, get_resource_by_id

    listed = json.loads(get_managed_resources())
    assert {r["resource_id"] for r in listed} == PRESENT_IDS
    assert json.loads(get_resource_by_id(_pk(db, "i-1gone")))["absent_since"].startswith("2026-09-02")


def test_detect_all_skips_absent_rows(db):
    from agenticops.detect.detector import AnomalyDetector

    with patch("agenticops.detect.detector.CloudWatchMonitor"):
        detector = AnomalyDetector(db.get(CloudAccount, A))
    with patch.object(AnomalyDetector, "detect_for_resource", return_value=["finding"]):
        results = detector.detect_all(save=False)
    assert set(results) == {"i-1live", "sg-1live"}


def test_collect_for_service_skips_absent_rows(db):
    from agenticops.monitor.collector import MetricsCollector

    with patch("agenticops.monitor.collector.CloudWatchMonitor"):
        collector = MetricsCollector(db.get(CloudAccount, A))
    with patch.object(MetricsCollector, "collect_for_resource", return_value={}):
        results = collector.collect_for_service("EC2", save=False)
    assert set(results) == {"i-1live"}


def test_ground_targets_never_grounds_on_an_absent_row(db):
    from agenticops.auth.actor import cli_actor
    from agenticops.services import change_service as cs

    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="cli", actor=cli_actor(), title="tag", description="add Env=prod",
                                      account_name="dev", targets=["i-1live", "i-1gone"],
                                      requested_change_type="normal", start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    out = cs.ground_targets(cr["id"])
    assert [g["resource_id"] for g in out["grounded"]] == ["i-1live"]
    assert out["unresolved"] == ["i-1gone"]
