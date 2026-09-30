"""Connector CLI + Web API (MVP-2.6.1 spec §2 surfaces, §3.B.6): `aiops connectors list|run`,
GET /api/connectors and POST /api/connectors/{name}/run. A disabled connector says so on both surfaces."""
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

import agenticops.connectors.runner as runner
from agenticops.config import settings
from agenticops.models import Base, CloudAccount, ConnectorRun, get_session


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.scheduler.scheduler  # noqa: F401 — register schedules / schedule_executions

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/connectors.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(id=1, name="global", provider="aws", is_enabled=True,
                       credentials={"account_id": "111111111111"}))
    s.commit()
    monkeypatch.setattr(settings, "k8s_connector_enabled", True)
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _run_row(session, i, status="complete", error=None, account_id=1):
    at = datetime(2026, 9, 29, 8, i, tzinfo=timezone.utc)
    session.add(ConnectorRun(id=i, connector="k8s", account_id=account_id, scope="lab", trigger="schedule",
                             started_at=at, finished_at=at, status=status, error=error,
                             counts={"created": i, "updated": 0, "absent": 0, "returned": 0}, per_kind={}))
    session.commit()


@pytest.fixture
def client():
    from agenticops.web.app import app
    return TestClient(app)


@pytest.fixture
def cli():
    from agenticops.cli.main import app
    return lambda *args: CliRunner().invoke(app, list(args))


def _result(status, error=""):
    target = runner.TargetRun(account="global", scope="lab", run_id=7, status=status, changed=status != "failed",
                              counts={"created": 1, "updated": 0, "absent": 0, "returned": 0}, error=error)
    return runner.ConnectorRunResult(connector="k8s", status=status, targets=[target],
                                     changed=status != "failed", graph_build_id=None)


# ── status (shared by CLI + API) ──────────────────────────────────────────────


def test_status_lists_newest_runs_first_with_the_account_name_and_the_schedule(db):
    from agenticops.scheduler.scheduler import Schedule

    for i in (1, 2, 3):
        _run_row(db, i, status="failed" if i == 3 else "complete",
                 error="cluster lab not collected — no kubeconfig" if i == 3 else None)
    _run_row(db, 4, account_id=None)                        # account row since deleted
    db.add(Schedule(name="k8s-discovery", pipeline_name="K8sDiscovery", cron_expression="*/10 * * * *", config={}))
    db.commit()

    st = runner.connector_status("k8s", limit=3)

    assert (st["name"], st["enabled"], st["running"]) == ("k8s", True, False)
    assert st["schedule"] == {"name": "k8s-discovery", "cron_expression": "*/10 * * * *", "is_enabled": True}
    assert [(r["id"], r["account"], r["status"]) for r in st["recent_runs"]] == [
        (4, None, "complete"), (3, "global", "failed"), (2, "global", "complete")]
    run = st["recent_runs"][1]
    assert run == {"id": 3, "account": "global", "scope": "lab", "trigger": "schedule", "status": "failed",
                   "started_at": "2026-09-29T08:03:00+00:00", "finished_at": "2026-09-29T08:03:00+00:00",
                   "counts": {"created": 3, "updated": 0, "absent": 0, "returned": 0},
                   "error": "cluster lab not collected — no kubeconfig"}


def test_status_of_a_disabled_connector_with_no_schedule_and_no_runs(db, monkeypatch):
    monkeypatch.setattr(settings, "k8s_connector_enabled", False)
    assert runner.connector_status("k8s") == {"name": "k8s", "enabled": False, "running": False,
                                              "schedule": None, "recent_runs": []}
    with pytest.raises(runner.UnknownConnector):
        runner.connector_status("cmdb")


def test_running_reflects_a_run_in_progress(db):
    with runner._LOCKS["k8s"]:
        assert runner.connector_status("k8s")["running"] is True
        assert runner.is_running("k8s") is True
    assert runner.is_running("k8s") is False


# ── Web API ───────────────────────────────────────────────────────────────────


def test_api_lists_connectors(db, client):
    _run_row(db, 1)
    body = client.get("/api/connectors").json()
    assert [c["name"] for c in body["connectors"]] == ["k8s"]
    assert [r["id"] for r in body["connectors"][0]["recent_runs"]] == [1]
    assert client.get("/api/connectors?limit=0").status_code == 422


def test_api_run_is_accepted_and_runs_in_the_background_as_manual(db, client, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run_connector", lambda name, **kw: calls.append((name, kw)) or _result("complete"))
    r = client.post("/api/connectors/k8s/run")
    assert (r.status_code, r.json()) == (202, {"connector": "k8s", "status": "accepted"})
    assert calls == [("k8s", {"trigger": "manual"})]         # TestClient runs background tasks before returning


def test_api_run_refuses_unknown_disabled_and_busy(db, client, monkeypatch):
    monkeypatch.setattr(runner, "run_connector", lambda *a, **k: pytest.fail("must not run"))
    r = client.post("/api/connectors/cmdb/run")
    assert r.status_code == 404 and "known: k8s" in r.json()["detail"]

    with runner._LOCKS["k8s"]:
        r = client.post("/api/connectors/k8s/run")
    assert (r.status_code, r.json()["detail"]) == (409, "connector k8s is already running")

    monkeypatch.setattr(settings, "k8s_connector_enabled", False)
    r = client.post("/api/connectors/k8s/run")
    assert (r.status_code, r.json()["detail"]) == (
        409, "connector k8s is disabled — set k8s_connector_enabled: true in config/settings.yaml")


def test_a_failing_background_run_is_logged_not_raised(db, client, monkeypatch, caplog):
    monkeypatch.setattr(runner, "run_connector", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    assert client.post("/api/connectors/k8s/run").status_code == 202
    assert "connector k8s: manual run failed: db gone" in caplog.text


# ── CLI ───────────────────────────────────────────────────────────────────────


def test_cli_list_prints_state_schedule_and_runs(db, cli):
    _run_row(db, 1, status="partial", error="Secret not collected — kubectl exit 1: forbidden")
    res = cli("connectors", "list")
    assert res.exit_code == 0, res.output
    assert "k8s" in res.output and "enabled" in res.output and "no schedule" in res.output
    assert "partial" in res.output and "Secret not collected" in res.output


def test_cli_shows_kubectl_stderr_literally(db, cli, monkeypatch):
    stderr = "Secret not collected — kubectl exit 1: Error from server [/forbidden] [bold]x"
    _run_row(db, 1, status="partial", error=stderr)
    res = cli("connectors", "list")
    assert res.exit_code == 0, res.output
    assert "[/forbidden] [bold]x" in " ".join(res.output.split())       # shown, not parsed as markup

    monkeypatch.setattr(runner, "run_connector", lambda name, **kw: _result("partial", stderr))
    res = cli("connectors", "run", "k8s")
    assert res.exit_code == 0 and "[/forbidden] [bold]x" in " ".join(res.output.split())


def test_cli_list_json(db, cli):
    import json

    _run_row(db, 1)
    res = cli("connectors", "list", "--json")
    assert res.exit_code == 0, res.output
    assert [c["name"] for c in json.loads(res.output)] == ["k8s"]


@pytest.mark.parametrize("status,code", [("complete", 0), ("partial", 0), ("failed", 1)])
def test_cli_run_prints_each_target_and_exits_nonzero_only_on_failure(db, cli, monkeypatch, status, code):
    calls = []
    error = "cluster lab not collected — no kubeconfig" if status != "complete" else ""
    monkeypatch.setattr(runner, "run_connector", lambda name, **kw: calls.append((name, kw)) or _result(status, error))
    res = cli("connectors", "run", "k8s", "--account", "global")
    assert res.exit_code == code, res.output
    assert calls == [("k8s", {"account": "global", "trigger": "manual"})]
    assert "global" in res.output and "lab" in res.output and status in res.output
    assert (error in res.output) if error else True


@pytest.mark.parametrize("status,text", [
    ("disabled", "connector k8s is disabled — set k8s_connector_enabled: true in config/settings.yaml"),
    ("no_targets", "no targets for account 'global'"),
    ("busy", "connector k8s is already running")])
def test_cli_run_says_why_nothing_ran(db, cli, monkeypatch, status, text):
    monkeypatch.setattr(runner, "run_connector",
                        lambda name, **kw: runner.ConnectorRunResult(connector=name, status=status))
    res = cli("connectors", "run", "k8s", "--account", "global")
    assert res.exit_code == 1 and text in " ".join(res.output.split())


def test_cli_run_unknown_connector(db, cli):
    res = cli("connectors", "run", "cmdb")
    assert res.exit_code == 1 and "unknown connector 'cmdb'; known: k8s" in res.output
