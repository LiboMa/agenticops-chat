"""connectors.k8s (MVP-2.6.1 spec §3.B.3): one kubectl listing per kind under the target account's env, raw_data
exactly the galaxy.rules.K8S_RAW_DATA_CONTRACT whitelist (a Secret never keeps data / stringData), pods rolled up
into their workload, and every failure a partial kind or a failed target, never a guess."""
import hashlib
import json
import sys
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agenticops.config import settings
from agenticops.connectors.base import Target
from agenticops.connectors.ingest import ingest, run_status
from agenticops.connectors.k8s import K8sConnector, _run_capped
from agenticops.credentials.kube import KubeconfigError
from agenticops.models import Base, CloudAccount, CloudResource, ConnectorRun, get_session
from agenticops.security.redaction import redact_obj

ENV = {"PATH": "/usr/bin", "AWS_ACCESS_KEY_ID": "target-access-key-id", "KUBECONFIG": "/data/kube/1/us-east-1/lab"}
TYPES = {"K8s_Namespace", "K8s_Deployment", "K8s_StatefulSet", "K8s_DaemonSet", "K8s_Pod", "K8s_Service",
         "K8s_Ingress", "K8s_Node", "K8s_ConfigMap", "K8s_Secret", "K8s_PVC", "K8s_PDB", "K8s_NetworkPolicy"}


def _md(name, ns=None, labels=None, owner=None, **extra):
    md = {"name": name, "labels": labels or {}, "uid": f"uid-{name}", "resourceVersion": "42", **extra}
    if ns:
        md["namespace"] = ns
    if owner:
        md["ownerReferences"] = [{"kind": owner[0], "name": owner[1], "controller": True}]
    return md


def _pod(name, owner=None, node="n1", ready=True, labels=None, containers=None, spec=None):
    return {"metadata": _md(name, "shop", labels, owner),
            "spec": {"nodeName": node, **(spec or {})},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
                       "containerStatuses": containers or [{"name": "c", "restartCount": 0,
                                                            "state": {"running": {}}}]}}


def _listing():
    return {
        "namespaces": [{"metadata": _md("shop", labels={"kubernetes.io/metadata.name": "shop"}),
                        "status": {"phase": "Active"}}],
        "deployments.apps": [{
            "metadata": _md("web", "shop", {"app": "web"}),
            "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "web"}},
                     "template": {"metadata": {"labels": {"app": "web", "tier": "front"}}, "spec": {
                         "volumes": [{"name": "cfg", "configMap": {"name": "web-config"}},
                                     {"name": "data", "persistentVolumeClaim": {"claimName": "web-data"}},
                                     {"name": "p", "projected": {"sources": [{"secret": {"name": "tls"}}]}}],
                         "containers": [{"name": "app", "image": "web:1",
                                         "envFrom": [{"secretRef": {"name": "db-creds"}}],
                                         "env": [{"name": "MODE", "valueFrom": {
                                                     "configMapKeyRef": {"name": "flags", "key": "mode"}}},
                                                 {"name": "PLAIN", "value": "x"}]}]}}},
            "status": {"conditions": [
                {"type": "Progressing", "status": "True", "reason": "NewReplicaSetAvailable", "message": "m",
                 "lastUpdateTime": "2026-09-29T10:00:00Z"},
                {"type": "Available", "status": "False", "reason": "MinimumReplicasUnavailable"}]}}],
        "statefulsets.apps": [{"metadata": _md("db", "shop", {"app": "db"}),
                               "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "db"}},
                                        "template": {"metadata": {"labels": {"app": "db"}},
                                                     "spec": {"containers": [{"name": "pg"}]}}},
                               "status": {}}],
        "daemonsets.apps": [{"metadata": _md("agent", "shop"),
                             "spec": {"selector": {"matchLabels": {"app": "agent"}},
                                      "template": {"metadata": {"labels": {"app": "agent"}},
                                                   "spec": {"containers": [{"name": "a"}]}}},
                             "status": {"desiredNumberScheduled": 2}}],
        "replicasets.apps": [{"metadata": _md("web-5d4f", "shop", owner=("Deployment", "web"))}],
        "pods": [
            _pod("web-5d4f-a", ("ReplicaSet", "web-5d4f"), node="n1", containers=[
                {"name": "app", "restartCount": 3, "state": {"running": {}},
                 "lastState": {"terminated": {"reason": "OOMKilled", "finishedAt": "2026-09-29T10:00:00Z"}}}]),
            _pod("web-5d4f-b", ("ReplicaSet", "web-5d4f"), node="n2", ready=False, containers=[
                {"name": "app", "restartCount": 0, "state": {"waiting": {"reason": "ImagePullBackOff"}}}]),
            _pod("db-0", ("StatefulSet", "db"), node="n1"),
            _pod("stress-test", labels={"run": "stress-test"}, node="n2",
                 spec={"containers": [{"name": "s", "env": [{"name": "K", "valueFrom": {
                     "secretKeyRef": {"name": "api", "key": "k"}}}]}]},
                 containers=[{"name": "s", "restartCount": 1, "state": {"running": {}},
                              "lastState": {"terminated": {"reason": "Error",
                                                           "finishedAt": "2026-09-29T09:00:00Z"}}}]),
            _pod("job-x", ("Job", "batch-1")),
        ],
        "services": [{"metadata": _md("web", "shop"),
                      "spec": {"type": "LoadBalancer", "selector": {"app": "web"}, "clusterIP": "10.0.0.1"},
                      "status": {"loadBalancer": {"ingress": [{"hostname": "abc.elb.amazonaws.com"},
                                                              {"ip": "1.2.3.4"}]}}},
                     {"metadata": _md("ext", "shop"), "spec": {"type": "ExternalName"}, "status": {}}],
        "ingresses.networking.k8s.io": [{"metadata": _md("web", "shop"), "spec": {
            "defaultBackend": {"service": {"name": "fallback"}},
            "rules": [{"http": {"paths": [{"backend": {"service": {"name": "web"}}},
                                          {"backend": {"resource": {"kind": "Bucket", "name": "b"}}}]}}]}}],
        "nodes": [{"metadata": _md("n1"), "spec": {"providerID": "aws:///us-east-1a/i-0abc"},
                   "status": {"conditions": [{"type": "Ready", "status": "True"}]}}],
        "configmaps": [{"metadata": _md("web-config", "shop"), "data": {"b": "2", "a": "1"},
                        "binaryData": {"c": "AA=="}}],
        "secrets": [{"metadata": _md("db-creds", "shop", annotations={
                        "kubectl.kubernetes.io/last-applied-configuration":
                            '{"stringData":{"password":"hunter2-leak"}}'}),
                     "type": "Opaque", "data": {"password": "aHVudGVyMi1sZWFr"},
                     "stringData": {"password": "hunter2-leak"}}],
        "persistentvolumeclaims": [{"metadata": _md("web-data", "shop"),
                                    "spec": {"storageClassName": "gp3", "volumeName": "pvc-1"},
                                    "status": {"phase": "Bound"}}],
        "poddisruptionbudgets.policy": [{"metadata": _md("web", "shop"),
                                         "spec": {"selector": {"matchLabels": {"app": "web"}}}}],
        "networkpolicies.networking.k8s.io": [{"metadata": _md("deny", "shop"), "spec": {"podSelector": {
            "matchLabels": {"app": "web"},
            "matchExpressions": [{"key": "tier", "operator": "In", "values": ["front"]}]}}}],
    }


class _FakeKubectl:
    """Stands in for _run_capped: answers `kubectl ... get <resource> ...` from a listing, records every call."""

    def __init__(self, listing=None, fail=None, missing=False):
        self.listing = _listing() if listing is None else listing
        self.fail = fail or {}   # resource -> (returncode, stdout, stderr, problem)
        self.missing = missing
        self.calls = []

    def __call__(self, args, env, timeout, cap):
        self.calls.append((args, env, timeout, cap))
        if self.missing:
            raise FileNotFoundError("kubectl")
        resource = args[args.index("get") + 1]
        if resource in self.fail:
            return self.fail[resource]
        return 0, json.dumps({"kind": "List", "items": self.listing.get(resource, [])}).encode(), "", ""


def _aws_account(pk=1, name="global"):
    return SimpleNamespace(id=pk, name=name, provider="aws", credentials={"account_id": "111111111111"},
                           regions=["us-east-1"], labels={}, credential_source_type="assume_role")


def _target(**kw):
    return Target(account=kw.pop("account", _aws_account()), scope=kw.pop("scope", "lab"),
                  region=kw.pop("region", "us-east-1"), **kw)


def _collect(fake=None, target=None, env_error=None, **kw):
    fake = fake or _FakeKubectl()
    env_patch = (patch("agenticops.credentials.kube.kubectl_env_for_cluster", side_effect=env_error) if env_error
                 else patch("agenticops.credentials.kube.kubectl_env_for_cluster", return_value=ENV))
    with env_patch as env_for, patch("agenticops.connectors.k8s._run_capped", side_effect=fake):
        result = K8sConnector().collect(target or _target(), **kw)
    return result, fake, env_for


def _by_id(result):
    return {e.resource_id: e for e in result.entities}


def test_every_kind_becomes_a_whitelisted_row():
    result, fake, env_for = _collect()

    env_for.assert_called_once()
    assert env_for.call_args.args[1:] == ("lab", "us-east-1")
    assert result.errors == [] and result.signals == []
    assert result.completeness == {("lab", t): True for t in TYPES}
    rows = _by_id(result)
    assert set(rows) == {
        "lab/Namespace/shop", "lab/Deployment/shop/web", "lab/StatefulSet/shop/db", "lab/DaemonSet/shop/agent",
        "lab/Pod/shop/stress-test", "lab/Service/shop/web", "lab/Service/shop/ext", "lab/Ingress/shop/web",
        "lab/Node/n1", "lab/ConfigMap/shop/web-config", "lab/Secret/shop/db-creds",
        "lab/PersistentVolumeClaim/shop/web-data", "lab/PodDisruptionBudget/shop/web",
        "lab/NetworkPolicy/shop/deny"}
    assert {e.provider for e in result.entities} == {"kubernetes"}
    assert {e.region for e in result.entities} == {"us-east-1"}
    assert {e.tags == {} for e in result.entities} == {True}

    assert rows["lab/Deployment/shop/web"].raw_data == {
        "cluster": "lab", "namespace": "shop", "labels": {"app": "web"},
        "template_labels": {"app": "web", "tier": "front"}, "selector": {"app": "web"},
        "refs": {"configmap": ["flags", "web-config"], "secret": ["db-creds", "tls"], "pvc": ["web-data"]},
        "replicas": 2,
        "conditions": [{"type": "Available", "status": "False", "reason": "MinimumReplicasUnavailable"},
                       {"type": "Progressing", "status": "True", "reason": "NewReplicaSetAvailable"}],
        "pod_summary": {"ready": 1, "desired": 2, "restarts": 3, "last_termination_reason": "OOMKilled",
                        "waiting_reasons": ["ImagePullBackOff"], "nodes": ["n1", "n2"]},
    }
    assert rows["lab/Namespace/shop"].raw_data == {
        "cluster": "lab", "namespace": None, "labels": {"kubernetes.io/metadata.name": "shop"}}
    assert rows["lab/Namespace/shop"].status == "Active"
    assert rows["lab/Service/shop/web"].raw_data == {
        "cluster": "lab", "namespace": "shop", "labels": {}, "selector": {"app": "web"}, "type": "LoadBalancer",
        "load_balancer_hostnames": ["abc.elb.amazonaws.com"]}
    assert rows["lab/Service/shop/ext"].raw_data["selector"] is None
    assert rows["lab/Ingress/shop/web"].raw_data["backends"] == ["fallback", "web"]
    assert rows["lab/Node/n1"].raw_data == {"cluster": "lab", "namespace": None, "labels": {},
                                            "provider_id": "aws:///us-east-1a/i-0abc"}
    assert rows["lab/Node/n1"].status == "Ready"
    assert rows["lab/PersistentVolumeClaim/shop/web-data"].raw_data == {
        "cluster": "lab", "namespace": "shop", "labels": {}, "storage_class": "gp3", "volume_name": "pvc-1"}
    assert rows["lab/PodDisruptionBudget/shop/web"].raw_data == {
        "cluster": "lab", "namespace": "shop", "labels": {}, "selector": {"app": "web"},
        "selector_has_expressions": False}
    assert rows["lab/NetworkPolicy/shop/deny"].raw_data == {
        "cluster": "lab", "namespace": "shop", "labels": {}, "pod_selector": {"app": "web"},
        "selector_has_expressions": True}
    assert rows["lab/DaemonSet/shop/agent"].raw_data["replicas"] == 2


def test_secret_rows_never_carry_data_or_annotations():
    result, _, _ = _collect()
    secret = _by_id(result)["lab/Secret/shop/db-creds"]
    assert secret.raw_data == {"cluster": "lab", "namespace": "shop", "labels": {}, "type": "Opaque"}
    dumped = json.dumps([e.__dict__ for e in result.entities])
    assert "hunter2-leak" not in dumped and "aHVudGVyMi1sZWFr" not in dumped
    assert "stringData" not in dumped and "last-applied-configuration" not in dumped


def test_configmap_keeps_key_names_and_an_order_independent_hash_only():
    result, _, _ = _collect()
    cm = _by_id(result)["lab/ConfigMap/shop/web-config"].raw_data
    canonical = json.dumps({"data": {"a": "1", "b": "2"}, "binaryData": {"c": "AA=="}}, sort_keys=True,
                           separators=(",", ":"))
    assert cm == {"cluster": "lab", "namespace": "shop", "labels": {}, "keys": ["a", "b", "c"],
                  "data_sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def test_owned_pods_roll_up_and_only_a_bare_pod_is_stored():
    result, _, _ = _collect()
    rows = _by_id(result)
    assert [e.resource_id for e in result.entities if e.resource_type == "K8s_Pod"] == ["lab/Pod/shop/stress-test"]
    assert rows["lab/StatefulSet/shop/db"].raw_data["pod_summary"] == {
        "ready": 1, "desired": 1, "restarts": 0, "last_termination_reason": None, "waiting_reasons": [],
        "nodes": ["n1"]}
    assert rows["lab/DaemonSet/shop/agent"].raw_data["pod_summary"]["ready"] == 0   # no pods: 0 of 2
    bare = rows["lab/Pod/shop/stress-test"].raw_data
    assert bare["template_labels"] == {"run": "stress-test"} and bare["selector"] == {}
    assert bare["refs"] == {"configmap": [], "secret": ["api"], "pvc": []} and bare["replicas"] == 1
    assert bare["pod_summary"] == {"ready": 1, "desired": 1, "restarts": 1, "last_termination_reason": "Error",
                                   "waiting_reasons": [], "nodes": ["n2"]}
    assert rows["lab/Pod/shop/stress-test"].status == "Running"


def test_failed_or_oversized_kind_is_partial_and_its_error_survives_redaction():
    fake = _FakeKubectl(fail={
        "secrets": (1, b"", 'Error from server (Forbidden): secrets is forbidden: User "system:serviceaccount:'
                            'agenticops:agenticops" cannot list resource "secrets"', ""),
        "configmaps": (-9, b"x" * 101, "", "output exceeded 100 bytes"),
    })
    result, _, _ = _collect(fake)

    assert result.completeness[("lab", "K8s_Secret")] is False
    assert result.completeness[("lab", "K8s_ConfigMap")] is False
    assert all(v for (scope, t), v in result.completeness.items() if t not in ("K8s_Secret", "K8s_ConfigMap"))
    assert result.errors == [
        "K8s_ConfigMap not collected — output exceeded 100 bytes",
        'K8s_Secret not collected — kubectl exit 1: Error from server (Forbidden): secrets is forbidden: User '
        '"system:serviceaccount:agenticops:agenticops" cannot list resource "secrets"',
    ]
    assert redact_obj(result.errors) == result.errors        # the DB write boundary keeps them verbatim
    assert not [e for e in result.entities if e.resource_type in ("K8s_Secret", "K8s_ConfigMap")]
    assert run_status(result) == "partial"


@pytest.mark.parametrize("failing,without", [
    ("replicasets.apps", {"lab/Deployment/shop/web"}),
    ("pods", {"lab/Deployment/shop/web", "lab/StatefulSet/shop/db", "lab/DaemonSet/shop/agent"}),
])
def test_a_missing_pod_or_replicaset_listing_drops_pod_summary_instead_of_reporting_zero(failing, without):
    result, _, _ = _collect(_FakeKubectl(fail={failing: (1, b"", "boom", "")}))
    rows = _by_id(result)
    workloads = {rid for rid, e in rows.items() if e.resource_type in ("K8s_Deployment", "K8s_StatefulSet",
                                                                        "K8s_DaemonSet")}
    assert {rid for rid in workloads if "pod_summary" not in rows[rid].raw_data} == without
    label = {"replicasets.apps": "ReplicaSet", "pods": "K8s_Pod"}[failing]
    assert result.errors == [f"{label} not collected — kubectl exit 1: boom"]
    assert result.completeness.get(("lab", "K8s_Pod")) is (failing != "pods")
    assert ("lab", "ReplicaSet") not in result.completeness


def test_credential_failure_fails_the_target_before_any_kubectl():
    result, fake, _ = _collect(env_error=KubeconfigError("No cluster found for name: lab"))
    assert fake.calls == []
    assert result.errors == ["cluster lab not collected — No cluster found for name: lab"]
    assert result.completeness == {} and result.entities == []
    assert run_status(result) == "failed"


def test_missing_kubectl_fails_the_target_once():
    result, fake, _ = _collect(_FakeKubectl(missing=True))
    assert len(fake.calls) == 1
    assert result.errors == ["cluster lab not collected — kubectl not found on PATH"]
    assert run_status(result) == "failed"


def test_refused_target_collects_nothing():
    reason = "cluster twin not collected — refused"
    result, fake, env_for = _collect(target=_target(scope="twin", refused=reason))
    assert result.errors == [reason] and fake.calls == [] and not env_for.called
    assert run_status(result) == "failed"


def test_kubectl_args_env_and_context():
    result, fake, _ = _collect()
    by_resource = {args[args.index("get") + 1]: (args, env, cap) for args, env, _t, cap in fake.calls}
    assert len(fake.calls) == 14 and len(by_resource) == 14
    assert by_resource["deployments.apps"][0] == ["kubectl", "get", "deployments.apps", "-A", "-o", "json"]
    assert by_resource["nodes"][0] == ["kubectl", "get", "nodes", "-o", "json"]
    assert by_resource["namespaces"][0] == ["kubectl", "get", "namespaces", "-o", "json"]
    assert {id(env) for _a, env, _c in by_resource.values()} == {id(ENV)}
    assert {cap for _a, _e, cap in by_resource.values()} == {settings.k8s_connector_max_output_bytes}

    onprem = SimpleNamespace(id=5, name="onprem", provider="kubernetes",
                             credentials={"kubeconfig_path": "/k", "context": "edge-ctx"}, regions=["dc1"],
                             labels={}, credential_source_type="")
    _, fake, _ = _collect(target=_target(account=onprem, scope="edge", region="dc1"))
    assert fake.calls[0][0][:3] == ["kubectl", "--context", "edge-ctx"]


def test_time_budget_caps_every_call_and_exhaustion_is_partial():
    _, fake, _ = _collect(timeout_seconds=5)
    assert fake.calls and all(0 < timeout <= 5 for _a, _e, timeout, _c in fake.calls)

    result, fake, _ = _collect(timeout_seconds=0)
    assert fake.calls == []
    assert result.completeness == {("lab", t): False for t in TYPES}
    assert "K8s_Deployment not collected — time budget of 0s exhausted" in result.errors
    assert run_status(result) == "failed"


# ── _run_capped: a real child process ─────────────────────────────────────────


def _py(code):
    return [sys.executable, "-c", code]


def test_run_capped_stops_reading_at_the_byte_cap():
    rc, out, _stderr, problem = _run_capped(_py("import sys; sys.stdout.write('x' * 1000000)"), None, 10, 1000)
    assert problem == "output exceeded 1000 bytes" and len(out) <= 1001


def test_run_capped_kills_a_hung_child_at_the_timeout():
    start = time.monotonic()
    rc, out, _stderr, problem = _run_capped(_py("import time; time.sleep(30)"), None, 0.5, 1000)
    assert problem == "timed out after 0.5s" and time.monotonic() - start < 10


def test_run_capped_returns_exit_code_stderr_and_uses_the_given_env():
    rc, out, stderr, problem = _run_capped(
        _py("import os, sys; print(os.environ['ONLY']); sys.stderr.write('boom'); sys.exit(3)"),
        {"ONLY": "target", "PATH": "/usr/bin"}, 10, 1000)
    assert (rc, out.strip(), stderr, problem) == (3, b"target", "boom", "")


def test_run_capped_raises_file_not_found_for_a_missing_binary():
    with pytest.raises(FileNotFoundError):         # collect() turns this into "kubectl not found on PATH"
        _run_capped(["aiops-no-such-kubectl"], {"PATH": "/nonexistent"}, 5, 1000)


# ── targets(): account-addressed, one per physical cluster ─────────────────────


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/k8s.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([
        CloudAccount(id=1, name="global", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"]),
        CloudAccount(id=2, name="old", provider="aws", is_enabled=False, credentials={}, regions=["us-east-1"]),
        CloudAccount(id=3, name="onprem", provider="kubernetes", is_enabled=True,
                     credentials={"cluster_name": "edge", "kubeconfig_path": "/k"}, regions=["dc1"]),
        CloudAccount(id=4, name="bad name", provider="kubernetes", is_enabled=True, credentials={}, regions=[]),
    ])
    s.flush()
    for acct, rtype, rid, region in [
        (1, "EKS", "lab", "us-east-1"),
        (1, "EKS_Cluster", "arn:aws:eks:us-east-1:111111111111:cluster/lab", "us-east-1"),
        (1, "EKS", "twin", "us-east-1"),
        (1, "EKS_Cluster", "arn:aws:eks:us-west-2:111111111111:cluster/twin", "us-west-2"),
        (1, "EC2", "i-1", "us-east-1"),
        (2, "EKS", "retired", "us-east-1"),
    ]:
        s.add(CloudResource(account_id=acct, provider="aws", region=region, resource_type=rtype, resource_id=rid,
                            name=rid, tags={}, raw_data={}))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def test_targets_are_one_per_physical_cluster_and_refuse_what_ids_cannot_tell_apart(db):
    targets = K8sConnector().targets(db)
    got = [(t.account.id, t.scope, t.region, t.refused) for t in targets]
    twin = ("cluster twin not collected — account 'global' has 2 clusters by that name (us-east-1, us-west-2) "
            "and K8s ids carry no region")
    assert got == [
        (1, "lab", "us-east-1", ""),
        (1, "twin", "us-east-1", twin),
        (1, "twin", "us-west-2", twin),
        (3, "edge", "dc1", ""),
        (4, "bad name", "", "cluster 'bad name' not collected — not a safe id segment"),
    ]
    assert targets[0].account.name == "global" and targets[0].account.provider == "aws"


def test_an_absent_cluster_row_does_not_make_a_present_cluster_ambiguous(db):
    db.add_all([
        CloudResource(account_id=1, provider="aws", region="us-west-2", resource_type="EKS", resource_id="solo",
                      name="solo", tags={}, raw_data={}, absent_since=datetime(2026, 9, 1, 12, 0)),
        CloudResource(account_id=1, provider="aws", region="us-east-1", resource_type="EKS_Cluster",
                      resource_id="arn:aws:eks:us-east-1:111111111111:cluster/solo",
                      name="arn:aws:eks:us-east-1:111111111111:cluster/solo", tags={}, raw_data={}),
    ])
    db.commit()
    got = [(t.account.id, t.scope, t.region, t.refused) for t in K8sConnector().targets(db)]
    assert [g for g in got if g[1] == "solo"] == [(1, "solo", "us-east-1", "")]


def test_a_scope_with_a_trailing_newline_is_refused(db):
    db.add(CloudAccount(id=5, name="nl", provider="kubernetes", is_enabled=True,
                        credentials={"cluster_name": "edge\n", "kubeconfig_path": "/k"}, regions=["dc1"]))
    db.commit()
    refused = {t.account.id: t.refused for t in K8sConnector().targets(db)}
    assert refused[5] == "cluster 'edge\\n' not collected — not a safe id segment"


def test_partial_kind_is_never_marked_absent_end_to_end(db):
    for kind, name in (("Secret", "old-secret"), ("Deployment", "gone")):
        db.add(CloudResource(account_id=1, provider="kubernetes", region="us-east-1", resource_type=f"K8s_{kind}",
                             resource_id=f"lab/{kind}/shop/{name}", name=name, tags={},
                             raw_data={"cluster": "lab", "namespace": "shop"}))
    db.commit()
    result, _, _ = _collect(_FakeKubectl(fail={"secrets": (1, b"", "secrets is forbidden", "")}))
    res = ingest(K8sConnector(), _target(), result, trigger="manual")

    db.expire_all()
    rows = {r.resource_id: r for r in db.query(CloudResource).filter_by(provider="kubernetes")}
    assert rows["lab/Secret/shop/old-secret"].absent_since is None      # partial kind: untouched
    assert rows["lab/Deployment/shop/gone"].absent_since is not None    # complete kind: marked, not deleted
    assert rows["lab/Deployment/shop/web"].raw_data["pod_summary"]["desired"] == 2
    run = db.get(ConnectorRun, res.run_id)
    assert run.status == "partial" and run.error == "K8s_Secret not collected — kubectl exit 1: secrets is forbidden"
