"""resource-scan: the W2 scan on a timer (Plan B Task 13)."""

import json
from unittest.mock import MagicMock, patch

import pytest

import agenticops.scanner.scheduled as scheduled
from agenticops.config import settings
from agenticops.models import Base, CloudAccount, CloudResource, get_session
from agenticops.scanner.engine import AccountScanResult, ScanResult


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.scheduler.scheduler  # noqa: F401 — register schedules / schedule_executions

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/scan-schedule.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=1, name="global", provider="aws", is_enabled=True, regions=["us-east-1"],
                            credentials={"account_id": "111111111111"}),
               CloudAccount(id=2, name="cn", provider="aws", is_enabled=True, regions=["cn-north-1"],
                            credentials={"account_id": "222222222222"}),
               CloudAccount(id=3, name="old", provider="aws", is_enabled=False, regions=["us-east-1"],
                            credentials={"account_id": "333333333333"})])
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _fake_scan(monkeypatch, scanned):
    """scanned: (pk, name, resources_absent, errors) per account the engine managed to scan."""
    calls = []

    async def fake(account_ids=None, focus="all", regions=None):
        calls.append(account_ids)
        accts = [AccountScanResult(account_id=pk, account_name=name, provider="aws", resources_found=5,
                                   resources_updated=4, resources_absent=absent, errors=list(errors))
                 for pk, name, absent, errors in scanned]
        return ScanResult(accounts=accts, total_found=5 * len(accts), total_updated=4 * len(accts))
    monkeypatch.setattr(scheduled, "scan_accounts_parallel", fake)
    return calls


# ── seed ──────────────────────────────────────────────────────────────────────


def test_the_interval_defaults_to_an_hour():
    assert settings.resource_scan_interval_minutes == 60


def test_scan_schedule_is_seeded_once_and_a_user_edit_survives(db, monkeypatch):
    from agenticops.scheduler.scheduler import Schedule

    monkeypatch.setattr(settings, "resource_scan_interval_minutes", 60)
    assert scheduled.seed_scan_schedule() is True
    row = db.query(Schedule).filter_by(name="resource-scan").one()
    assert (row.pipeline_name, row.cron_expression, row.config) == ("ResourceScan", "0 */1 * * *", {})

    row.cron_expression, row.is_enabled = "0 */6 * * *", False
    db.commit()
    assert scheduled.seed_scan_schedule() is False
    db.expire_all()
    row = db.query(Schedule).filter_by(name="resource-scan").one()
    assert (row.cron_expression, row.is_enabled) == ("0 */6 * * *", False)


def test_the_seed_follows_the_interval(db, monkeypatch):
    from agenticops.scheduler.scheduler import Schedule

    monkeypatch.setattr(settings, "resource_scan_interval_minutes", 30)
    scheduled.seed_scan_schedule()
    assert db.query(Schedule).filter_by(name="resource-scan").one().cron_expression == "*/30 * * * *"


# ── run_scheduled_scan ────────────────────────────────────────────────────────


def test_every_enabled_account_is_scanned(db, monkeypatch):
    calls = _fake_scan(monkeypatch, [(1, "global", 3, ["iam_users: boom"]), (2, "cn", 0, [])])
    assert scheduled.run_scheduled_scan() == {
        "pipeline": "ResourceScan", "accounts": 2, "total_found": 10, "total_updated": 8,
        "resources_absent": 3, "errors": 1, "skipped_accounts": []}
    assert calls == [[1, 2]]


def test_an_account_whose_credentials_failed_is_named(db, monkeypatch):
    _fake_scan(monkeypatch, [(1, "global", 0, [])])
    assert scheduled.run_scheduled_scan()["skipped_accounts"] == ["cn"]


def test_the_schedule_account_limits_the_scan(db, monkeypatch):
    calls = _fake_scan(monkeypatch, [(2, "cn", 0, [])])
    assert scheduled.run_scheduled_scan("cn")["accounts"] == 1
    assert calls == [[2]]


@pytest.mark.parametrize("name", ["old", "nope"])
def test_a_disabled_or_unknown_schedule_account_is_an_error(db, monkeypatch, name):
    calls = _fake_scan(monkeypatch, [])
    with pytest.raises(ValueError, match=name):
        scheduled.run_scheduled_scan(name)
    assert calls == []


def test_no_enabled_account_scans_nothing(db, monkeypatch):
    db.query(CloudAccount).update({"is_enabled": False})
    db.commit()
    calls = _fake_scan(monkeypatch, [])
    assert scheduled.run_scheduled_scan()["accounts"] == 0
    assert calls == []


# ── scheduler ─────────────────────────────────────────────────────────────────


def _dispatch(db):
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution, Scheduler

    db.add(Schedule(id=9, name="resource-scan", pipeline_name="ResourceScan", cron_expression="0 */1 * * *",
                    config={}))
    db.commit()
    Scheduler()._execute_schedule_by_info({"id": 9, "name": "resource-scan", "pipeline_name": "ResourceScan",
                                           "account_name": None, "config": {}})
    db.expire_all()
    return db.query(ScheduleExecution).filter_by(schedule_id=9).one()


@pytest.mark.parametrize("skipped,status,error", [([], "completed", None),
                                                  (["cn"], "failed", "credentials failed: cn")])
def test_scheduler_dispatches_resource_scan(db, monkeypatch, skipped, status, error):
    res = {"pipeline": "ResourceScan", "accounts": 1, "total_found": 5, "total_updated": 4,
           "resources_absent": 2, "errors": 0, "skipped_accounts": skipped}
    monkeypatch.setattr(scheduled, "run_scheduled_scan", lambda account_name=None: res)
    execution = _dispatch(db)
    assert (execution.status, execution.result, execution.error) == (status, res, error)
    assert execution.completed_at is not None


def test_a_raising_scan_is_a_failed_execution(db, monkeypatch):
    def boom(account_name=None):
        raise ValueError("account 'x' not found or disabled")
    monkeypatch.setattr(scheduled, "run_scheduled_scan", boom)
    execution = _dispatch(db)
    assert (execution.status, execution.error) == ("failed", "account 'x' not found or disabled")


def test_a_scheduled_run_marks_a_vanished_resource_absent(db):
    """End to end through the real engine: the schedule is what keeps an old row from being counted forever."""
    db.query(CloudAccount).filter_by(id=2).update({"is_enabled": False})
    db.add_all([CloudResource(account_id=1, provider="aws", region="us-east-1", resource_type="EC2",
                              resource_id=rid, name=rid, tags={}, raw_data={}, status="running")
                for rid in ("i-live", "i-gone")])
    db.commit()

    def cli(command):
        if command.split()[1:3] == ["ec2", "describe-instances"]:
            return json.dumps({"Reservations": [{"Instances": [{"InstanceId": "i-live"}]}]})
        return "Error (exit 254): not mocked"

    with patch("agenticops.scanner.engine._get_provider_and_tool",
               return_value=(MagicMock(), MagicMock(side_effect=cli))):
        execution = _dispatch(db)

    assert execution.status == "completed" and execution.result["resources_absent"] == 1
    gone = {r.resource_id: r.absent_since for r in db.query(CloudResource).all()}
    assert gone["i-live"] is None and gone["i-gone"] is not None


def test_pipeline_options_include_resource_scan(db):
    from starlette.testclient import TestClient
    from agenticops.web.app import app

    assert "ResourceScan" in TestClient(app).get("/api/schedules/pipeline-options").json()["pipelines"]
