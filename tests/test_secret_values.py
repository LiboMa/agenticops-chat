"""A read-only run reads a Secret's names and keys, never its values («之后» 25①, 2026-11-26).

A diagnosis, a fix-plan run and a detection only read (N28–N31) — but a Secret read IS a read: `kubectl get secret
db -o yaml` passed, and so did `cat` of a mounted Secret file on a node (over SSM, as root). The owner: names and keys
only — `get secret(s)` (the table), `-o name|wide`, `describe secret` (key names and sizes) — never values; the
detection run too; mounted Secret files on hosts too. One check, in the shared check point
(`command_audit.change_context_refusal`), for both kubectl tools (`run_kubectl`, the account-bound `run_kubectl_<a>`)
and both host tools (`run_on_host`, `run_ssh_<a>`); ledger reason `secret_value`. A viewer keeps its stricter rule
(no Secret at all)."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agenticops.run_context import run_context
from tests.test_read_only_runs import _kube, _rows, _ssh, ledger  # noqa: F401  (the fixture)

KINDS = ["diagnosis", "plan", "detect"]

NAMES = ["get secrets", "get secret db", "get secrets -A", "-n shop get secrets", "--namespace=shop get secrets",
         "describe secret/db", "-n shop describe secret/db", "describe sec''ret/db", "get 'secret' db",
         'get "secrets"', "get pods,sec''rets", "get Secret db", "get SECRETS -A", "get secrets.v1. db",
         "get sec\\ret db", "get secret db -o name", "get secrets -o wide", "get secrets -w"]
VALUES = ["get secret db -o yaml", "-n shop get secret db -o yaml", "get sec''ret db -o yaml",
          "get secret db -ojson", "get secret db -o=json", "get secret db --output yaml", "get secret db --output=json",
          "get secret db -o jsonpath={.data.password}", "get secret db -o go-template={{.data}}",
          "get secret db -o custom-columns=P:.data.password", "get secret db --template={{.data}}",
          "get pods,secrets -o yaml", "edit secret db", "exec web -- cat /var/run/secrets/kubernetes.io/serviceaccount/token",
          "config view --raw", "config view --ra''w", "config view '--raw'", "get --ra\\w /api/v1/namespaces/x/secrets/y",
          "auth can-i get secrets", "get secret db '"]


@pytest.mark.parametrize("command", NAMES)
def test_names_and_keys_are_not_values(command):
    from agenticops.skills.security import reveals_secret_values
    assert reveals_secret_values(command) is False
    assert reveals_secret_values("kubectl " + command) is False


@pytest.mark.parametrize("command", VALUES)
def test_values_are(command):
    from agenticops.skills.security import reveals_secret_values
    assert reveals_secret_values(command) is True


@pytest.mark.parametrize("command", ["get pods", "get configmap app-secretary -o yaml", "logs deploy/secrets-sync",
                                     "get pod web -o yaml", "config view"])
def test_what_is_no_secret_is_not_judged(command):
    from agenticops.skills.security import reveals_secret_values
    assert reveals_secret_values(command) is False


# ── run_kubectl ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
def test_run_kubectl_refuses_values_and_runs_names(ledger, kind):
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only_run=kind), \
            patch("agenticops.skills.execution._execute_kubectl", return_value="NAME TYPE DATA") as ex:
        out = run_kubectl(cluster_name="c1", command="get secret db -o yaml", require_confirmation=True)
        assert "never its values" in out and "names and keys" in out
        assert not ex.called                                          # refused before anything resolves credentials
        assert run_kubectl(cluster_name="c1", command="get secrets") == "NAME TYPE DATA"
        assert run_kubectl(cluster_name="c1", command="-n shop describe secret/db") == "NAME TYPE DATA"
    assert _rows(ledger) == [("run_kubectl", "readonly", "refused", "secret_value")]


def test_outside_a_read_only_run_nothing_changes(ledger):
    from agenticops.skills.execution import run_kubectl
    with patch("agenticops.skills.execution._execute_kubectl", return_value="OK"):
        assert run_kubectl(cluster_name="c1", command="get secret db -o yaml") == "OK"
    assert _rows(ledger) == []


def test_a_viewer_keeps_the_stricter_rule(ledger):
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only=True), patch("agenticops.skills.execution._execute_kubectl") as ex:
        assert "read-only" in run_kubectl(cluster_name="c1", command="get secrets")   # names too, as before
    assert not ex.called


# ── the account-bound kubectl tool ───────────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
def test_the_account_bound_kubectl_tool_refuses_values_and_runs_names(ledger, monkeypatch, kind):
    tool, target = _kube(monkeypatch)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="NAME TYPE DATA", stderr=""))
    monkeypatch.setattr(target, run)
    with run_context(read_only_run=kind):
        assert "never its values" in tool("get secret db -o jsonpath={.data.password}")
        assert not run.called
        assert tool("get secrets -A") == "NAME TYPE DATA"
    assert _rows(ledger) == [("provider_kubectl", "readonly", "refused", "secret_value")]


def test_the_account_bound_kubectl_tool_outside_a_run_is_as_it_was(ledger, monkeypatch):
    tool, target = _kube(monkeypatch)
    monkeypatch.setattr(target, Mock(return_value=SimpleNamespace(returncode=0, stdout="data", stderr="")))
    assert tool("get secret db -o yaml") == "data"
    assert _rows(ledger) == []


# ── mounted Secret files on a host ───────────────────────────────────────────

MOUNTED = ["cat /var/run/secrets/kubernetes.io/serviceaccount/token",
           "cat /var/lib/kubelet/pods/3f2a/volumes/kubernetes.io~secret/db-creds/password",
           "cat /var/lib/kubelet/pods/*/volumes/kubernetes.io~secret/*/*",
           "head -c 64 /var/lib/kubelet/pods/*/volumes/kubernetes.io~s*/*/*",
           "tail /var/lib/kubelet/pods/u/volumes/kubernetes.io~projected/kube-api-access/token",
           "cat /run/secrets/db_password",
           "cd /var/run/secrets/kubernetes.io/serviceaccount && cat token",
           "cd /var/lib/kubelet/pods && cat */volumes/*/*/*",
           "cat ../../../../var/run/secrets/kubernetes.io/serviceaccount/token",
           "grep -r password /var/lib/kubelet", "grep -Rn pass /var/lib/kubelet/pods", "grep -ri x /",
           "cd /var/run/secrets && grep -r . .", "ps aux | grep x; cat /run/secrets/k"]
NOT_MOUNTED = ["ls /var/run/secrets/kubernetes.io/serviceaccount",
               "ls -la /var/lib/kubelet/pods/*/volumes/kubernetes.io~secret/*",
               "stat /var/run/secrets/kubernetes.io/serviceaccount/token",
               "du -sh /var/lib/kubelet/pods", "cat /etc/hostname", "grep -r error /var/log/nginx",
               "grep password /var/lib/kubelet/config.yaml", "cat token", "df -h /"]


@pytest.mark.parametrize("command", MOUNTED)
def test_a_mounted_secret_read(command):
    from agenticops.services.change_steps import reads_mounted_secret
    assert reads_mounted_secret(command) is True


@pytest.mark.parametrize("command", NOT_MOUNTED)
def test_not_a_mounted_secret_read(command):
    from agenticops.services.change_steps import reads_mounted_secret
    assert reads_mounted_secret(command) is False


@pytest.mark.parametrize("kind", KINDS)
def test_run_on_host_refuses_a_mounted_secret_and_runs_the_rest(ledger, kind):
    from agenticops.skills.execution import run_on_host
    with run_context(read_only_run=kind), \
            patch("agenticops.skills.execution._run_auto_ladder", return_value="ok") as host:
        out = run_on_host(host_id="i-0123456789abcdef0", command="cat /var/run/secrets/kubernetes.io/serviceaccount/token")
        assert "never its values" in out and not host.called
        assert run_on_host(host_id="i-0123456789abcdef0", command="ls /var/run/secrets/kubernetes.io/serviceaccount") == "ok"
    assert _rows(ledger) == [("run_on_host", "readonly", "refused", "secret_value")]


@pytest.mark.parametrize("kind", KINDS)
def test_the_ssh_tool_refuses_a_mounted_secret(ledger, monkeypatch, kind):
    tool, target = _ssh(monkeypatch)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="ok", stderr=""))
    monkeypatch.setattr(target, run)
    with run_context(read_only_run=kind):
        assert "never its values" in tool("cat /run/secrets/db_password")
        assert not run.called
    assert _rows(ledger) == [("provider_ssh", "readonly", "refused", "secret_value")]


def test_outside_a_read_only_run_a_host_read_is_as_it_was(ledger):
    from agenticops.skills.execution import run_on_host
    with patch("agenticops.skills.execution._run_auto_ladder", return_value="tok"):
        assert run_on_host(host_id="i-0123456789abcdef0",
                           command="cat /var/run/secrets/kubernetes.io/serviceaccount/token") == "tok"
    assert _rows(ledger) == []


# ── the work log ─────────────────────────────────────────────────────────────

def test_the_account_bound_tools_secret_read_is_not_kept_in_the_work_log():
    from agenticops.agents.step_recorder import keeps_result
    assert keeps_result("run_kubectl_prod_cluster", {"command": "get secret db -o yaml"}) is False
    assert keeps_result("run_kubectl_prod_cluster", {"command": "get pods"}) is True
