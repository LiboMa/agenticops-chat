"""connectors.runner (MVP-2.6.1 spec §3.B.6): targets → collect → ingest per target, one connector_runs row
each; a structure change on a schedule / manual run refreshes the graph rule-only; the k8s-discovery schedule is
seeded once and dispatched by the scheduler; a disabled connector says so instead of running."""
import threading
from types import SimpleNamespace

import pytest

import agenticops.connectors.runner as runner
from agenticops.config import settings
from agenticops.connectors.base import CollectResult, EntityObservation, Target
from agenticops.models import Base, CloudAccount, CloudResource, ConnectorRun, get_session


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.scheduler.scheduler  # noqa: F401 — register schedules / schedule_executions

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/runner.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=1, name="global", provider="aws", is_enabled=True,
                            credentials={"account_id": "111111111111"}),
               CloudAccount(id=2, name="cn", provider="aws", is_enabled=True,
                            credentials={"account_id": "222222222222"})])
    s.commit()
    monkeypatch.setattr(settings, "k8s_connector_enabled", True)
    monkeypatch.setattr(settings, "galaxy_enabled", True)
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _acct(pk, name, aws_id):
    return SimpleNamespace(id=pk, name=name, provider="aws", credentials={"account_id": aws_id}, regions=[],
                           labels={}, credential_source_type="")


GLOBAL, CN = _acct(1, "global", "111111111111"), _acct(2, "cn", "222222222222")


def _deployment(scope, name="web"):
    return EntityObservation(provider="kubernetes", resource_type="K8s_Deployment",
                             resource_id=f"{scope}/Deployment/default/{name}", name=name, region="us-east-1",
                             raw_data={"cluster": scope, "namespace": "default"}, tags={}, status="active")


class _Fake:
    """A scripted connector: results[scope] is a CollectResult or an exception to raise."""

    name, provider = "k8s", "kubernetes"

    def __init__(self, targets, results):
        self._targets, self.results, self.budgets = targets, results, []

    def targets(self, session):
        return list(self._targets)

    def collect(self, target, *, timeout_seconds=None):
        self.budgets.append(timeout_seconds)
        outcome = self.results[target.scope]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _complete(scope):
    return CollectResult(entities=[_deployment(scope)], completeness={(scope, "K8s_Deployment"): True})


def _install(monkeypatch, fake):
    monkeypatch.setattr(runner, "CONNECTORS", {"k8s": lambda: fake})


@pytest.fixture
def builds(monkeypatch):
    calls = []

    def fake_build(trigger="manual", full=False, llm=True):
        calls.append((trigger, llm))
        return 41
    monkeypatch.setattr("agenticops.galaxy.builder.build_graph", fake_build)
    return calls


def test_every_target_gets_its_own_run_row_and_a_change_refreshes_the_graph_once(db, monkeypatch, builds):
    fake = _Fake([Target(GLOBAL, "lab", "us-east-1"), Target(CN, "prod", "cn-north-1")],
                 {"lab": _complete("lab"), "prod": _complete("prod")})
    _install(monkeypatch, fake)

    res = runner.run_connector("k8s", trigger="schedule")

    assert (res.connector, res.status, res.changed, res.graph_build_id) == ("k8s", "complete", True, 41)
    assert [(t.account, t.scope, t.status, t.changed) for t in res.targets] == [
        ("global", "lab", "complete", True), ("cn", "prod", "complete", True)]
    assert builds == [("k8s-discovery", False)]
    rows = db.query(ConnectorRun).order_by(ConnectorRun.id).all()
    assert [(r.connector, r.account_id, r.scope, r.trigger, r.status) for r in rows] == [
        ("k8s", 1, "lab", "schedule", "complete"), ("k8s", 2, "prod", "schedule", "complete")]
    assert [t.run_id for t in res.targets] == [r.id for r in rows]

    res = runner.run_connector("k8s", trigger="manual")          # nothing moved: no second refresh
    assert res.changed is False and res.graph_build_id is None and builds == [("k8s-discovery", False)]


def test_an_rca_run_leaves_the_graph_refresh_to_its_caller(db, monkeypatch, builds):
    _install(monkeypatch, _Fake([Target(GLOBAL, "lab", "us-east-1")], {"lab": _complete("lab")}))
    res = runner.run_connector("k8s", account="global", scope="lab", trigger="rca", timeout_seconds=30)
    assert res.changed is True and res.graph_build_id is None and builds == []


def test_no_graph_refresh_while_galaxy_is_off_and_a_failed_refresh_does_not_lose_the_runs(db, monkeypatch):
    fake = _Fake([Target(GLOBAL, "lab", "us-east-1")], {"lab": _complete("lab")})
    _install(monkeypatch, fake)
    monkeypatch.setattr("agenticops.galaxy.builder.build_graph",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("graph down")))
    res = runner.run_connector("k8s")
    assert res.status == "complete" and res.changed is True and res.graph_build_id is None
    assert db.query(ConnectorRun).count() == 1

    monkeypatch.setattr(settings, "galaxy_enabled", False)
    monkeypatch.setattr("agenticops.galaxy.builder.build_graph", lambda *a, **k: pytest.fail("galaxy is off"))
    fake.results["lab"] = CollectResult(entities=[_deployment("lab", "api")],
                                        completeness={("lab", "K8s_Deployment"): True})
    res = runner.run_connector("k8s")
    assert res.changed is True and res.graph_build_id is None


def test_account_and_scope_select_targets_by_name_or_cloud_account_id(db, monkeypatch, builds):
    fake = _Fake([Target(GLOBAL, "lab", "us-east-1"), Target(GLOBAL, "edge", "us-east-1"),
                  Target(CN, "lab", "cn-north-1")],
                 {"lab": _complete("lab"), "edge": _complete("edge")})
    _install(monkeypatch, fake)
    assert [(t.account, t.scope) for t in runner.run_connector("k8s", account="global", scope="lab").targets] == [
        ("global", "lab")]
    assert [(t.account, t.scope) for t in runner.run_connector("k8s", account="222222222222").targets] == [
        ("cn", "lab")]
    res = runner.run_connector("k8s", account="global", scope="nope")
    assert (res.status, res.targets) == ("no_targets", [])


def test_a_raising_collector_is_a_failed_run_and_the_next_target_still_runs(db, monkeypatch, builds):
    fake = _Fake([Target(GLOBAL, "bad", "us-east-1"), Target(GLOBAL, "lab", "us-east-1")],
                 {"bad": KeyError("items"), "lab": _complete("lab")})
    _install(monkeypatch, fake)
    res = runner.run_connector("k8s")
    assert [(t.scope, t.status) for t in res.targets] == [("bad", "failed"), ("lab", "complete")]
    assert res.status == "partial"
    assert res.targets[0].error == "bad not collected — collector raised KeyError: 'items'"
    row = db.get(ConnectorRun, res.targets[0].run_id)
    assert (row.status, row.error) == ("failed", "bad not collected — collector raised KeyError: 'items'")


def test_an_ingest_error_rolls_its_target_back_records_it_failed_and_the_next_target_still_runs(db, monkeypatch,
                                                                                                 builds):
    """M-2: a DB error writing one target (on PostgreSQL, e.g. a value over a column length) must not skip the
    targets after it or leave the failed one without a run row."""
    unwritable = EntityObservation(provider="kubernetes", resource_type="K8s_ConfigMap",
                                   resource_id="bad/ConfigMap/default/cfg", name="cfg", region="us-east-1",
                                   raw_data={"cluster": "bad", "keys": {"not", "json"}}, tags={}, status="active")
    bad = CollectResult(entities=[_deployment("bad"), unwritable],
                        completeness={("bad", "K8s_Deployment"): True, ("bad", "K8s_ConfigMap"): True})
    _install(monkeypatch, _Fake([Target(GLOBAL, "bad", "us-east-1"), Target(GLOBAL, "lab", "us-east-1")],
                                {"bad": bad, "lab": _complete("lab")}))

    res = runner.run_connector("k8s")

    assert [(t.scope, t.status) for t in res.targets] == [("bad", "failed"), ("lab", "complete")]
    assert res.status == "partial"
    assert res.targets[0].error.startswith("bad not ingested — StatementError: ")
    row = db.get(ConnectorRun, res.targets[0].run_id)
    assert (row.status, row.scope, row.error) == ("failed", "bad", res.targets[0].error)
    db.expire_all()
    assert [r.resource_id for r in db.query(CloudResource).order_by(CloudResource.resource_id)] == [
        "lab/Deployment/default/web"]                    # target 1 rolled back whole, target 2 written


def test_status_rolls_up_over_targets(db, monkeypatch, builds):
    failed = CollectResult(errors=["cluster x not collected — no kubeconfig"])
    _install(monkeypatch, _Fake([Target(GLOBAL, "a", "r"), Target(GLOBAL, "b", "r")], {"a": failed, "b": failed}))
    assert runner.run_connector("k8s").status == "failed"


def test_the_time_budget_is_shared_by_every_target(db, monkeypatch, builds):
    fake = _Fake([Target(GLOBAL, "lab", "us-east-1"), Target(CN, "prod", "cn-north-1")],
                 {"lab": _complete("lab"), "prod": _complete("prod")})
    _install(monkeypatch, fake)
    runner.run_connector("k8s", timeout_seconds=20)
    assert 0 < fake.budgets[1] <= fake.budgets[0] <= 20
    runner.run_connector("k8s")
    assert fake.budgets[2:] == [None, None]


def test_a_second_run_of_the_same_connector_waits_and_gives_up_as_busy_within_its_budget(db, monkeypatch, builds):
    _install(monkeypatch, _Fake([Target(GLOBAL, "lab", "us-east-1")], {"lab": _complete("lab")}))
    with runner._LOCKS["k8s"]:
        res = runner.run_connector("k8s", trigger="rca", timeout_seconds=0.2)
    assert (res.status, res.targets) == ("busy", [])
    assert db.query(ConnectorRun).count() == 0


def test_disabled_connector_runs_nothing_and_says_so(db, monkeypatch, builds):
    monkeypatch.setattr(settings, "k8s_connector_enabled", False)
    _install(monkeypatch, _Fake([], {}))
    monkeypatch.setattr(_Fake, "targets", lambda self, s: pytest.fail("a disabled connector must not look for targets"))
    res = runner.run_connector("k8s")
    assert (res.status, res.targets) == ("disabled", [])
    assert db.query(ConnectorRun).count() == 0


def test_unknown_connector_and_trigger_are_refused(db):
    with pytest.raises(runner.UnknownConnector, match="known: k8s"):
        runner.run_connector("cmdb")
    with pytest.raises(ValueError, match="trigger"):
        runner.run_connector("k8s", trigger="auto")


# ── schedule ──────────────────────────────────────────────────────────────────


def test_discovery_schedule_is_seeded_once_and_a_user_edit_survives(db, monkeypatch):
    from agenticops.scheduler.scheduler import Schedule

    monkeypatch.setattr(settings, "k8s_discovery_interval_minutes", 10)
    assert runner.seed_discovery_schedule() is True
    row = db.query(Schedule).filter_by(name="k8s-discovery").one()
    assert (row.pipeline_name, row.cron_expression, row.config) == ("K8sDiscovery", "*/10 * * * *", {})

    row.cron_expression, row.is_enabled = "*/30 * * * *", False
    db.commit()
    assert runner.seed_discovery_schedule() is False
    db.expire_all()
    row = db.query(Schedule).filter_by(name="k8s-discovery").one()
    assert (row.cron_expression, row.is_enabled) == ("*/30 * * * *", False)


def test_no_seed_while_the_connector_is_off(db, monkeypatch):
    from agenticops.scheduler.scheduler import Schedule

    monkeypatch.setattr(settings, "k8s_connector_enabled", False)
    assert runner.seed_discovery_schedule() is False
    assert db.query(Schedule).count() == 0


@pytest.mark.parametrize("status,expected", [("complete", "completed"), ("partial", "completed"),
                                             ("disabled", "completed"), ("failed", "failed")])
def test_scheduler_dispatches_k8s_discovery(db, monkeypatch, status, expected):
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution, Scheduler

    db.add(Schedule(id=9, name="k8s-discovery", pipeline_name="K8sDiscovery", cron_expression="*/10 * * * *",
                    config={}))
    db.commit()
    calls = []
    target = runner.TargetRun(account="global", scope="lab", run_id=3, status=status, changed=False, counts={},
                              error="cluster lab not collected — no kubeconfig" if status == "failed" else "")

    def fake_run(name, **kw):
        calls.append((name, kw))
        return runner.ConnectorRunResult(connector=name, status=status,
                                         targets=[] if status == "disabled" else [target])
    monkeypatch.setattr(runner, "run_connector", fake_run)

    Scheduler()._execute_schedule_by_info({"id": 9, "name": "k8s-discovery", "pipeline_name": "K8sDiscovery",
                                           "account_name": None, "config": {}})

    assert calls == [("k8s", {"trigger": "schedule"})]
    execution = db.query(ScheduleExecution).filter_by(schedule_id=9).one()
    assert execution.status == expected and execution.completed_at is not None
    assert execution.result == {"pipeline": "K8sDiscovery", "status": status,
                                "targets": 0 if status == "disabled" else 1, "changed": False,
                                "graph_build_id": None}
    assert execution.error == ("cluster lab not collected — no kubeconfig" if status == "failed" else None)


def test_pipeline_options_include_k8s_discovery(db):
    from starlette.testclient import TestClient
    from agenticops.web.app import app

    assert "K8sDiscovery" in TestClient(app).get("/api/schedules/pipeline-options").json()["pipelines"]
