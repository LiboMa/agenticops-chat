"""A kubectl command with the namespace flag before the subcommand is the command it runs (MVP-2.9.0 N29).

Found in the real run inside the lab cluster, 2026-11-20: `kubectl -n shop get pods` was tier `unknown` — the tables
are matched from the first word — while `kubectl get pods -n shop` is a read. Three of that run's seven plans were
written with the flag first: every step «unclassifiable», no rollback line «runnable as written», never
auto-approved, and their reads refused after a stop. ONE leading namespace flag is recognised now; every other
leading option (which cluster, as whom) still leaves the line `unknown`.

Found while planning it: the read-only account's «no Secret reads» check looked at the raw spelling of the command,
while the tier and the argv come from its shlex words — `get sec''ret x` was a read that missed the check.
"""
from unittest.mock import patch

import pytest

from agenticops.agents.run_guard import guard_decision, may_change_something
from agenticops.agents.step_recorder import keeps_result, step_look
from agenticops.models import CommandAudit, get_session
from agenticops.run_context import run_context
from agenticops.services import change_steps
from agenticops.skills.execution import _reveals_secret_material
from agenticops.skills.security import classify_kubectl_command, kubectl_words
from tests.test_viewer_role import _temp_db

READS = [
    "get pods", "get pods -o wide", "describe deployment backend", "logs deploy/web --tail=50",
    "rollout status deployment/web --timeout=180s", "rollout history deployment/web", "top pods",
    "auth can-i list pods", "get pods -o jsonpath='{.items[*].metadata.name}'", "events --for deployment/web",
]
WRITES = [
    "scale deployment/backend --replicas=2", "rollout undo deployment/web --to-revision=3", "delete pod web-1",
    "apply -f x.yaml", "set image deployment/web nginx=nginx:1.25", "exec web-1 -- ls", "rollout restart deployment/web",
    "patch deployment web -p '{}'", "label pod web-1 a=b",
]
LEADS = ["-n shop {}", "--namespace shop {}", "--namespace=shop {}"]


@pytest.mark.parametrize("lead", LEADS)
@pytest.mark.parametrize("command", READS)
def test_a_read_written_with_the_namespace_first_is_a_read(lead, command):
    for word in ("", "kubectl "):
        assert classify_kubectl_command(word + lead.format(command)) == "readonly"
    assert classify_kubectl_command(command + " -n shop") == "readonly"            # … as it always was written so


@pytest.mark.parametrize("lead", LEADS)
@pytest.mark.parametrize("command", WRITES)
def test_a_change_written_with_the_namespace_first_is_a_change(lead, command):
    for word in ("", "kubectl "):
        assert classify_kubectl_command(word + lead.format(command)) == "write"


@pytest.mark.parametrize("command", [
    "-n kube-system delete namespace kube-system", "--namespace=x delete ns kube-system",
    "-n x delete --all --all-namespaces", "--namespace x delete clusterrole admin", "-n x delete crd --all",
    "-n delete namespace kube-system",          # the whole line is searched: taking the flag off first would hide it
])
def test_what_is_blocked_stays_blocked(command):
    assert classify_kubectl_command(command) == "blocked"


def test_a_dump_into_a_directory_is_a_write_with_the_namespace_first_too():
    assert classify_kubectl_command("-n shop cluster-info dump --output-directory=/tmp/d") == "write"
    assert classify_kubectl_command("--namespace=shop cluster-info dump --output-directory /tmp/d") == "write"
    assert classify_kubectl_command("-n shop cluster-info dump") == "readonly"


@pytest.mark.parametrize("command", [
    # another option before the subcommand says WHICH cluster, or as WHOM: nothing vouches for the line
    "--context prod get pods", "--kubeconfig /x get pods", "--server https://x get pods", "--as admin get pods",
    "--token abc get pods", "--cache-dir /x get pods", "-v 6 get pods", "--cluster c get pods", "--user u get pods",
    "-n shop --context prod get pods", "--context prod -n shop get pods", "-n shop --as admin delete pod x",
    # only ONE namespace flag is taken off
    "-n a -n b get pods", "--namespace=a --namespace=b get pods", "-n a --namespace b scale deploy/x --replicas=0",
    # a flag with no namespace after it, or with something that is not a namespace's name
    "-n", "--namespace", "--namespace=", "-n shop", "-n --context get pods", "-n -o get pods", "-n Shop get pods",
    "-n shop/x get pods", "-n 'a b' get pods", "-n shop. get pods", "-n -shop get pods", "-n " + "a" * 64 + " get pods",
    "--namespace=Shop get pods", "--namespace=a/b get pods", "--namespace= get pods", "--namespace=-x scale deploy/y --replicas=0",
    "--namespace=" + "a" * 64 + " get pods",
    # spellings kubectl may take that this rule does not: left alone
    "-N shop get pods", "--NAMESPACE=shop get pods", "-nshop get pods", "-n=shop get pods",
    # the word after the flag IS the namespace: what follows is no subcommand
    "-n get pods", "-n delete pod x", "-n scale deployment/x --replicas=0",
])
def test_every_other_way_of_starting_the_line_is_still_unclassifiable(command):
    assert classify_kubectl_command(command) == "unknown"
    assert classify_kubectl_command("kubectl " + command) == "unknown"


def test_the_line_is_judged_as_the_tool_will_run_it():
    assert classify_kubectl_command("-n 'shop' get pods") == "readonly"            # shlex: the quotes are not part of it
    assert classify_kubectl_command("'-n' shop get pods") == "readonly"
    assert classify_kubectl_command("-n sh''op scale deploy/x --replicas=1") == "write"
    assert classify_kubectl_command("-n shop 'get' pods") == "readonly"
    assert classify_kubectl_command("-n shop get pods '") == "unknown"             # cannot be split: the tool would not run it


def test_the_words_of_a_command():
    assert kubectl_words("kubectl -n shop get 'po ds'") == ["-n", "shop", "get", "po ds"]
    assert kubectl_words("KUBECTL get pods") == ["get", "pods"]                    # the word, in any case, once
    assert kubectl_words("kubectl kubectl get pods") == ["kubectl", "get", "pods"]
    assert kubectl_words("get Secret DB") == ["get", "Secret", "DB"]               # the case as written
    assert kubectl_words("") == [] and kubectl_words("   ") == []
    assert kubectl_words("get pods '") is None


# ── everything that reads the tier follows ───────────────────────────────────

def test_a_plan_step_written_so_has_its_own_tier():
    assert change_steps.command_tier("kubectl -n shop get pods") == "readonly"
    assert change_steps.command_tier("kubectl -n shop scale deployment/x --replicas=2") == "write"
    assert change_steps.command_tier("kubectl --namespace=shop rollout status deployment/x --timeout=180s") == "readonly"
    assert change_steps.command_tier("kubectl -n shop get pods | grep x") == "unknown"       # a shell would split it
    assert change_steps.command_tier("Kubectl -n shop get pods") == "unknown"                # not written as the command is
    assert change_steps.command_tier("kubectl --context prod -n shop get pods") == "unknown"
    assert change_steps.step_tier({"command": "kubectl -n shop rollout undo deployment/x"}) == "write"


def test_such_a_plan_is_no_longer_held_as_unclassifiable_and_its_rollback_counts():
    steps = [{"action": "a", "command": "kubectl -n shop scale deployment/backend --replicas=2"},
             {"action": "b", "command": "kubectl -n shop rollout status deployment/backend --timeout=180s"}]
    rollback = {"steps": [{"action": "look", "command": "kubectl -n shop describe deployment backend"},
                          {"action": "look", "command": "kubectl -n shop get events --sort-by=.lastTimestamp"}]}
    assert change_steps.unclassified_commands(steps, rollback["steps"]) == []
    assert change_steps.rollback_outlook(rollback) == {"steps": 2, "commands": 2, "as_written": 2}


def test_after_a_stop_a_read_written_so_is_let_through_and_a_change_is_not():
    stopped = {"status": "running", "fix_plan_id": 1, "stopped_by": "user:alice", "rollback": frozenset()}
    assert guard_decision(stopped, "run_kubectl", {"command": "-n shop get pods"}, applied=1) is None
    assert guard_decision(stopped, "run_kubectl", {"command": "kubectl --namespace=shop describe deployment x"}, applied=1) is None
    assert guard_decision(stopped, "run_kubectl", {"command": "-n shop scale deployment/x --replicas=3"}, applied=1) is not None
    assert guard_decision(stopped, "run_kubectl", {"command": "--context prod get pods"}, applied=1) is not None
    assert may_change_something("run_kubectl", {"command": "-n shop get pods"}) is False
    assert may_change_something("run_kubectl", {"command": "-n shop delete pod x"}) is True


def test_the_recorded_step_is_a_read():
    assert step_look("run_kubectl", {"command": "-n shop get pods"}) == ("read", "readonly")
    assert step_look("run_kubectl", {"command": "-n shop scale deployment/x --replicas=3"}) == ("act", "write")


# ── the tool itself ──────────────────────────────────────────────────────────

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    settings = _temp_db(tmp_path, monkeypatch, "n29.db")
    monkeypatch.setattr(settings, "command_audit_enabled", True)
    s = get_session()
    yield s
    s.close()


def _rows(db):
    db.expire_all()
    return [(r.tool, r.tier, r.outcome, r.reason) for r in db.query(CommandAudit).order_by(CommandAudit.id)]


@pytest.mark.parametrize("command", ["-n shop get pods", "kubectl --namespace=shop logs deploy/web --tail=5"])
def test_the_tool_runs_such_a_read_without_asking(ledger, command):
    from agenticops.skills.execution import run_kubectl
    with patch("agenticops.skills.execution._execute_kubectl", return_value="OK") as ex:
        assert run_kubectl(cluster_name="c1", command=command) == "OK"
    assert ex.called and _rows(ledger) == []                       # a read: no confirmation, nothing on the ledger


def test_the_tool_still_asks_before_a_change_written_so(ledger):
    from agenticops.skills.execution import run_kubectl
    with patch("agenticops.skills.execution._execute_kubectl", return_value="OK") as ex:
        out = run_kubectl(cluster_name="c1", command="-n shop scale deployment/x --replicas=0")
    assert "requires confirmation" in out and not ex.called
    assert _rows(ledger) == [("run_kubectl", "write", "refused", "confirmation")]


# ── a read-only account and Secrets ──────────────────────────────────────────

SECRET_READS = [
    "get secret db -o yaml", "get secrets", "describe secret/db", "config view --raw",                # as before
    "-n shop get secret db -o yaml", "--namespace=shop get secrets", "-n shop describe secret/db",    # the namespace first
    "get sec''ret db -o yaml", "get 'secret' db", 'get "secrets"', "get sec\\ret db", "get pods,sec''rets",
    "describe sec''ret/db", "config view --ra''w", "config view '--raw'", "get --ra\\w /api/v1/namespaces/x/secrets/y",
    "get Secret db", "get SECRETS -A", "get secrets.v1. db",
]


@pytest.mark.parametrize("command", SECRET_READS)
def test_however_it_is_spelled_a_secret_read_is_seen(command):
    assert _reveals_secret_material(command) is True


@pytest.mark.parametrize("command", ["get pods", "get configmap app-secretary", "logs deploy/secrets-sync",
                                     "-n shop get deployment my-secret-store", "describe pod x --show-events",
                                     "get pods -l app=secretary", "config view"])
def test_what_only_resembles_one_is_not(command):
    assert _reveals_secret_material(command) is False


def test_a_line_that_cannot_be_split_counts_as_revealing():
    assert _reveals_secret_material("get pods '") is True


@pytest.mark.parametrize("command", SECRET_READS)
def test_a_read_only_account_is_refused_every_spelling(ledger, command):
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only=True), patch("agenticops.skills.execution._execute_kubectl") as ex:
        out = run_kubectl(cluster_name="c1", command=command, namespace="prod", require_confirmation=True)
    assert "read-only" in out and not ex.called
    assert [row[2:] for row in _rows(ledger)] == [("refused", "read_only_account")]


@pytest.mark.parametrize("command", ["-n shop get pods", "--namespace=shop logs deploy/web --tail=50",
                                     "-n shop get configmap app-secretary"])
def test_a_read_only_account_runs_a_plain_read_written_so(ledger, command):
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only=True), patch("agenticops.skills.execution._execute_kubectl", return_value="OK") as ex:
        assert run_kubectl(cluster_name="c1", command=command) == "OK"
    assert ex.called and _rows(ledger) == []


@pytest.mark.parametrize("command", ["-n shop scale deployment/x --replicas=2", "--context prod get pods"])
def test_a_read_only_account_is_refused_what_is_not_a_read(ledger, command):
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only=True), patch("agenticops.skills.execution._execute_kubectl") as ex:
        out = run_kubectl(cluster_name="c1", command=command, require_confirmation=True)
    assert "read-only" in out and not ex.called


def test_the_result_of_a_secret_read_is_not_kept_whatever_its_spelling():
    assert keeps_result("run_kubectl", {"command": "get sec''ret db -o yaml"}) is False
    assert keeps_result("run_kubectl", {"command": "-n shop get secrets"}) is False
    assert keeps_result("run_kubectl", {"command": "-n shop get pods"}) is True
