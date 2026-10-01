"""connectors.ingest (MVP-2.6.1 spec §3.B.2): the one writer for connector observations. Upserts, marks
absent only what a complete listing no longer sees (never deletes, never a partial kind, never outside the
target's account / provider / scope), keeps the build-written unresolved_refs, records one connector_runs
row per call."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agenticops.connectors.base import CollectResult, EntityObservation, Target
from agenticops.connectors.ingest import ingest, last_success_at
from agenticops.models import Base, CloudAccount, CloudResource, ConnectorRun, get_session

ACCT, OTHER = 1, 2
T0 = datetime(2026, 9, 1, 12, 0)


class _Conn:
    name = "k8s"
    provider = "kubernetes"


CONN = _Conn()


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/ingest.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=ACCT, name="global", provider="aws", is_enabled=True, credentials={}),
               CloudAccount(id=OTHER, name="cn", provider="aws", is_enabled=True, credentials={})])
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _target(scope="lab", account=ACCT):
    return Target(account=SimpleNamespace(id=account, name="global", provider="aws"), scope=scope, region="us-east-1")


def _obs(kind, name, ns="default", scope="lab", raw=None):
    return EntityObservation(provider="kubernetes", resource_type=f"K8s_{kind}",
                             resource_id=f"{scope}/{kind}/{ns}/{name}", name=name, region="us-east-1",
                             raw_data=raw if raw is not None else {"cluster": scope, "namespace": ns},
                             tags={}, status="active")


def _row(s, kind, name, ns="default", scope="lab", account=ACCT, provider="kubernetes", raw=None):
    r = CloudResource(account_id=account, provider=provider, region="us-east-1", resource_type=f"K8s_{kind}",
                      resource_id=f"{scope}/{kind}/{ns}/{name}", name=name, tags={},
                      raw_data=raw if raw is not None else {"cluster": scope, "namespace": ns},
                      status="active", scanned_at=T0)
    s.add(r)
    s.commit()
    return r.id


def _get(s, pk):
    s.expire_all()
    return s.get(CloudResource, pk)


def _complete(*kinds, scope="lab", value=True):
    return {(scope, f"K8s_{k}"): value for k in kinds}


def test_first_ingest_creates_rows_and_a_complete_run(db):
    res = ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web"), _obs("Service", "web")],
                                                completeness=_complete("Deployment", "Service")), trigger="manual")
    assert (res.status, res.changed) == ("complete", True)
    assert res.counts["created"] == 2
    rows = db.query(CloudResource).order_by(CloudResource.resource_id).all()
    assert [(r.provider, r.resource_id, r.absent_since) for r in rows] == [
        ("kubernetes", "lab/Deployment/default/web", None), ("kubernetes", "lab/Service/default/web", None)]
    run = db.get(ConnectorRun, res.run_id)
    assert (run.connector, run.account_id, run.scope, run.trigger, run.status) == ("k8s", ACCT, "lab", "manual",
                                                                                  "complete")
    assert run.per_kind == {"K8s_Deployment": {"complete": True, "count": 1},
                            "K8s_Service": {"complete": True, "count": 1}}
    assert run.error is None


def test_unchanged_reingest_is_not_a_structure_change_but_refreshes_scanned_at(db):
    pk = _row(db, "Deployment", "web")
    res = ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web")],
                                                completeness=_complete("Deployment")), trigger="schedule")
    assert (res.changed, res.counts["updated"]) == (False, 1)
    assert _get(db, pk).scanned_at > T0


def test_pod_summary_churn_is_not_a_structure_change(db):
    pk = _row(db, "Deployment", "web", raw={"cluster": "lab", "namespace": "default", "pod_summary": {"ready": 1}})
    raw = {"cluster": "lab", "namespace": "default", "pod_summary": {"ready": 0, "restarts": 7}}
    res = ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web", raw=raw)],
                                                completeness=_complete("Deployment")), trigger="schedule")
    assert res.changed is False
    assert _get(db, pk).raw_data["pod_summary"] == {"ready": 0, "restarts": 7}


def test_content_change_is_a_structure_change(db):
    _row(db, "Deployment", "web")
    raw = {"cluster": "lab", "namespace": "default", "selector": {"app": "web"}}
    res = ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web", raw=raw)],
                                                completeness=_complete("Deployment")), trigger="schedule")
    assert res.changed is True


def test_complete_kind_marks_unseen_rows_absent_and_never_deletes(db):
    gone = _row(db, "Deployment", "old")
    res = ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web")],
                                                completeness=_complete("Deployment")), trigger="schedule")
    assert (res.changed, res.counts["absent"]) == (True, 1)
    assert _get(db, gone).absent_since is not None
    assert db.query(CloudResource).count() == 2


def test_partial_kind_never_marks_absent(db):
    secret = _row(db, "Secret", "db-password")
    unlisted = _row(db, "ConfigMap", "app-config")  # kind missing from completeness entirely counts as partial
    res = ingest(CONN, _target(), CollectResult(entities=[], completeness=_complete("Secret", value=False),
                                                errors=["K8s_Secret not collected — forbidden"]), trigger="schedule")
    assert res.status == "failed"
    assert _get(db, secret).absent_since is None
    assert _get(db, unlisted).absent_since is None


def test_a_row_touched_after_the_run_began_is_not_marked(db):
    """PF-e, as in the W2 scan: another writer saw this row after this run's listing began, so the run's seen set
    is stale for it."""
    started = datetime.now(timezone.utc)
    touched, gone = _row(db, "Deployment", "new"), _row(db, "Deployment", "old")
    db.query(CloudResource).filter_by(id=touched).update({"scanned_at": started + timedelta(seconds=1)})
    db.commit()
    res = ingest(CONN, _target(), CollectResult(entities=[], completeness=_complete("Deployment")),
                 trigger="schedule", started_at=started)
    assert res.counts["absent"] == 1
    assert _get(db, touched).absent_since is None
    assert _get(db, gone).absent_since is not None


def test_absent_marking_stays_inside_account_provider_and_scope(db):
    other_cluster = _row(db, "Deployment", "web", scope="lab-2")   # "lab" is a string prefix of "lab-2"
    underscore = _row(db, "Deployment", "web", scope="laXb")       # LIKE would treat "_" as a wildcard
    other_account = _row(db, "Deployment", "web", account=OTHER)
    other_provider = _row(db, "Deployment", "web", provider="aws")
    ingest(CONN, _target(scope="la_b"), CollectResult(entities=[], completeness=_complete("Deployment", scope="la_b")),
           trigger="schedule")
    ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "api")], completeness=_complete("Deployment")),
           trigger="schedule")
    for pk in (other_cluster, underscore, other_account, other_provider):
        assert _get(db, pk).absent_since is None


def test_returning_row_clears_absent_and_counts_as_change(db):
    pk = _row(db, "Deployment", "web")
    db.query(CloudResource).filter_by(id=pk).update({"absent_since": T0})
    db.commit()
    res = ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web")],
                                                completeness=_complete("Deployment")), trigger="schedule")
    assert (res.changed, res.counts["returned"]) == (True, 1)
    assert _get(db, pk).absent_since is None


def test_build_written_unresolved_refs_survive_the_overwrite(db):
    refs = [{"kind": "ConfigMap", "name": "missing"}]
    pk = _row(db, "Deployment", "web", raw={"cluster": "lab", "namespace": "default", "unresolved_refs": refs})
    ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web")], completeness=_complete("Deployment")),
           trigger="schedule")
    assert _get(db, pk).raw_data["unresolved_refs"] == refs


def test_partial_run_records_errors_verbatim(db):
    """The DB write boundary masks "secret: <value>" (security/db_redaction), so a connector error must never
    read "K8s_Secret: ..." — the connector's "<kind> not collected — <why>" shape survives the round trip."""
    err = "K8s_Secret not collected — kubectl exit 1: secrets is forbidden"
    res = ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web")],
                                                completeness={**_complete("Deployment"), **_complete("Secret", value=False)},
                                                errors=[err]), trigger="manual")
    run = db.get(ConnectorRun, res.run_id)
    assert run.status == "partial"
    assert run.per_kind["K8s_Secret"] == {"complete": False, "count": 0}
    assert run.error == err


def test_signals_go_through_the_gate_and_a_bad_one_does_not_lose_the_run(db, monkeypatch):
    import agenticops.services.signal_gate as gate

    seen = []

    def fake(sig):
        seen.append(sig.title)
        if sig.title == "bad":
            raise RuntimeError("boom")

    monkeypatch.setattr(gate, "process_signal", fake)
    sigs = [gate.SignalInput(source="k8s", title=t, description="", severity="high") for t in ("ok", "bad")]
    res = ingest(CONN, _target(), CollectResult(signals=sigs, completeness=_complete("Deployment")), trigger="manual")
    assert seen == ["ok", "bad"]
    assert (res.counts["signals"], res.counts["signal_errors"]) == (1, 1)
    assert db.get(ConnectorRun, res.run_id) is not None


def test_last_success_at_skips_failed_runs_and_is_aware_utc(db):
    assert last_success_at(db, "k8s", ACCT, "lab") is None
    ok = ingest(CONN, _target(), CollectResult(entities=[_obs("Deployment", "web")],
                                               completeness=_complete("Deployment")), trigger="schedule")
    ingest(CONN, _target(), CollectResult(errors=["cluster unreachable"]), trigger="schedule")
    ingest(CONN, _target(scope="lab-2"), CollectResult(entities=[_obs("Deployment", "web", scope="lab-2")],
                                                       completeness=_complete("Deployment", scope="lab-2")),
           trigger="schedule")
    finished = db.get(ConnectorRun, ok.run_id).finished_at
    got = last_success_at(db, "k8s", ACCT, "lab")
    assert got.tzinfo is timezone.utc
    assert got == finished.replace(tzinfo=timezone.utc)
    assert datetime.now(timezone.utc) - got < timedelta(minutes=1)


def test_aws_scan_never_touches_kubernetes_rows(db):
    """spec §3.B.2: the AWS scan writes through save_resources, which is keyed on provider — guard it."""
    from agenticops.tools.metadata_tools import save_resources

    pk = _row(db, "Deployment", "web")
    before = db.query(CloudResource).count()
    out = save_resources(json.dumps([{"resource_id": "lab/Deployment/default/web", "resource_type": "EKS",
                                      "region": "us-east-1", "name": "clash"},
                                     {"resource_id": "i-0abc", "resource_type": "EC2", "region": "us-east-1"}]),
                         account_id=ACCT, provider="aws")
    assert "Saved 2 new" in out
    row = _get(db, pk)
    assert (row.provider, row.resource_type, row.scanned_at, row.absent_since) == ("kubernetes", "K8s_Deployment",
                                                                                   T0, None)
    assert db.query(CloudResource).count() == before + 2
