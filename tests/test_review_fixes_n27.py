"""MVP-2.9.0 N27 — the review of round 3 (four reviewers, one per surface): each fix with the test that failed first.

Back end. The front end's are in src/agenticops/web/frontend/src/__tests__/."""
from __future__ import annotations

import pytest

from agenticops.services import change_steps
from agenticops.skills.security import classify_kubectl_command
from agenticops.tools.aws_cli_tool import _classify_command


# ── D1: a command is judged as the tool will run it, not as it is spelled ─────────────────────────────────────
# The tools hand the line to shlex before running it, so `get-object''`, `get-ob\ject` and "get-object" all run
# get-object; the classifier compared the spelling, and the file-saving «reads» of N26 passed as read-only.

@pytest.mark.parametrize("command", [
    "aws s3api get-object'' --bucket b --key k /tmp/x",
    "aws s3api get-ob\\ject --bucket b --key k /tmp/x",
    'aws s3api "get-object" --bucket b --key k /tmp/x',
    "aws 's3api' get-object-torrent --bucket b --key k /tmp/x",
    'aws apigateway get-export"" --rest-api-id a --stage-name s --export-type oas30 /tmp/x',
    "aws apigateway 'get-sdk' --rest-api-id a --stage-name s --sdk-type javascript /tmp/x",
    "aws   s3api    get-object --bucket b --key k /tmp/x",                  # runs of spaces
    "aws\ts3api get-object --bucket b --key k /tmp/x",                      # a tab
])
def test_a_file_saving_read_spelled_another_way_is_still_a_write(command):
    assert _classify_command(command) == "write"
    assert change_steps.command_tier(command) != "readonly"


@pytest.mark.parametrize("command", [
    "cluster-info  dump --output-directory=/tmp/d",                          # two spaces
    "cluster-info dump '--output-directory=/tmp/d'",
    'cluster-info dump "--output-directory" /tmp/d',
    "cluster-info 'dump' --output-directory=/tmp/d",
    "cluster-info --request-timeout=30s dump --output-directory=/tmp/d",     # an option between the two words
    "cluster-info --request-timeout 30s dump --output-directory /tmp/d",     # … with its value apart
    "kubectl  cluster-info dump --output-directory=/tmp/d",
    "cluster-info dump --output-dir\\ectory=/tmp/d",
])
def test_a_cluster_dump_into_a_directory_spelled_another_way_is_still_a_write(command):
    assert classify_kubectl_command(command) == "write"
    assert change_steps.command_tier(change_steps.tool_command("run_kubectl", command)) != "readonly"


def test_a_line_the_tool_could_not_split_is_not_read_only():
    """An unbalanced quote: the tool refuses to run it, and nothing vouches for it as a read."""
    assert _classify_command("aws s3api get-bucket-acl --bucket 'b") == "unknown"
    assert classify_kubectl_command("get pods -l 'app=x") == "unknown"


@pytest.mark.parametrize("command, classify", [
    ("aws s3api get-object-acl '--bucket' b --key k", _classify_command),
    ("aws ec2 describe-instances --query 'Reservations[].Instances[].{id:InstanceId,st:State.Name}'", _classify_command),
    ("aws  ec2   describe-instances", _classify_command),                    # the CLI runs it the same
    ("get pods -o jsonpath='{.items[*].metadata.name}'", classify_kubectl_command),
    ("cluster-info dump", classify_kubectl_command),
    ("cluster-info  dump --namespaces kube-system", classify_kubectl_command),
    ("get  pods   -n web", classify_kubectl_command),
])
def test_a_read_spelled_with_quotes_or_spaces_is_still_a_read(command, classify):
    assert classify(command) == "readonly"


@pytest.mark.parametrize("command, classify, tier", [
    ("aws ec2 terminate-instances'' --instance-ids i-0", _classify_command, None),   # blocked or write: never less
    ("aws iam 'delete-user' --user-name u", _classify_command, None),        # blocked or write: never less
    ("delete 'namespace' kube-system", classify_kubectl_command, "blocked"),
    ("'delete' pod x", classify_kubectl_command, "write"),
])
def test_a_change_spelled_with_quotes_is_the_change_it_runs(command, classify, tier):
    got = classify(command)
    assert got in ("write", "blocked") and (tier is None or got == tier)


# ── C1 / C6: the execution switches — an environment that says «off» is off; a stored value of the wrong shape ──
# N25 stored the switches so that «off» survives a restart. It also made a stored «on» outrank a process started
# with the switch off in its environment: a copy of a database (how every preview here is made) would run the
# executor against the real accounts it holds credentials for.

from types import SimpleNamespace

from fastapi.testclient import TestClient

import agenticops.web.app  # noqa: E402,F401 — imported at collection (the auth middleware is added only when auth is on at import)

SWITCHES = ("executor_enabled", "auto_fix_enabled", "executor_auto_approve_l0_l1", "executor_hitl_enabled")
ACTS_ALONE = SWITCHES[:3]


@pytest.fixture
def sw(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.auth.service import AuthService
    from agenticops.config import settings
    from agenticops.services import exec_switches, runtime_settings
    from agenticops.web.app import APIAuthMiddleware, app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/switches.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    for name in SWITCHES:
        monkeypatch.setattr(settings, name, False)
        monkeypatch.delenv("AIOPS_" + name.upper(), raising=False)
    models_mod.init_db()
    runtime_settings.reset_cache()
    exec_switches.invalidate()

    def login(email, **kw):
        user = AuthService.create_user(email, "pw-123456", **kw)
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}

    def environment(name, text):
        """As the process was started: the variable is set, and settings carries what it parses to."""
        monkeypatch.setenv("AIOPS_" + name.upper(), text)
        monkeypatch.setattr(settings, name, text.strip().lower() in ("1", "true", "t", "yes", "y", "on"))

    def stored(value):
        """What a (copied) database holds, written as a row — not through save()."""
        runtime_settings.put(exec_switches.KEY, value, "user:someone-else")
        exec_switches.invalidate()

    yield SimpleNamespace(client=TestClient(APIAuthMiddleware(app)), login=login, settings=settings, switches=exec_switches,
                          environment=environment, stored=stored, monkeypatch=monkeypatch)
    runtime_settings.reset_cache()
    exec_switches.invalidate()


@pytest.mark.parametrize("name", ACTS_ALONE)
@pytest.mark.parametrize("text", ["false", "0", "off", "No", " FALSE "])
def test_an_environment_that_says_off_is_off_whatever_is_stored(sw, name, text):
    sw.environment(name, text)
    sw.stored({name: True})
    assert getattr(sw.switches.effective(), name) is False
    assert sw.switches.locked() == {name: False}


@pytest.mark.parametrize("name", ACTS_ALONE)
def test_an_environment_that_says_on_is_only_a_default(sw, name):
    sw.environment(name, "true")
    assert getattr(sw.switches.effective(), name) is True
    sw.stored({name: False})                                   # an administrator switched it off: that survives
    assert getattr(sw.switches.effective(), name) is False
    assert sw.switches.locked() == {}


@pytest.mark.parametrize("name", ACTS_ALONE)
def test_a_file_that_says_off_is_only_a_default(sw, name):
    """settings.yaml (no environment variable): an administrator's «on» stands, as N25 has it."""
    sw.stored({name: True})
    assert getattr(sw.switches.effective(), name) is True
    assert sw.switches.locked() == {}


def test_the_human_gate_is_held_the_other_way_round(sw):
    """For the executor's confirmation gate «on» is the strict side: an environment that says on holds it on."""
    sw.environment("executor_hitl_enabled", "true")
    sw.stored({"executor_hitl_enabled": False})
    assert sw.switches.effective().executor_hitl_enabled is True
    assert sw.switches.locked() == {"executor_hitl_enabled": True}
    sw.environment("executor_hitl_enabled", "false")           # «off» there is only a default
    sw.stored({"executor_hitl_enabled": True})
    assert sw.switches.effective().executor_hitl_enabled is True and sw.switches.locked() == {}


def test_a_held_switch_is_still_off_when_the_store_cannot_be_read(sw):
    sw.environment("executor_hitl_enabled", "true")
    sw.monkeypatch.setattr(sw.switches.runtime_settings, "get_row", lambda key: (_ for _ in ()).throw(RuntimeError("down")))
    sw.switches.invalidate()
    got = sw.switches.effective()
    assert (got.executor_enabled, got.auto_fix_enabled, got.executor_auto_approve_l0_l1) == (False, False, False)
    assert got.executor_hitl_enabled is True


def test_switching_on_what_the_environment_holds_off_is_refused_and_nothing_else_of_the_request_is_applied(sw):
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    admin = sw.login("root@x", is_admin=True)
    sw.environment("executor_enabled", "false")
    focus = sw.settings.scan_focus
    r = sw.client.patch("/api/settings", json={"executor_enabled": True, "auto_fix_enabled": True, "scan_focus": "computing"}, headers=admin)
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "held_by_environment" and body["fields"] == ["executor_enabled"]
    assert "AIOPS_EXECUTOR_ENABLED" in body["detail"]
    assert sw.settings.scan_focus == focus                      # validated before anything is applied
    assert sw.switches.effective().auto_fix_enabled is False    # the other switch of the same request is not stored
    with get_db_session() as s:
        assert s.query(AuditLog).filter(AuditLog.entity_name == "settings").count() == 0
    # asking for what is already in force is not a change, and is not refused
    assert sw.client.patch("/api/settings", json={"executor_enabled": False}, headers=admin).status_code == 200
    # nor may the store be written around the route
    with pytest.raises(sw.switches.ExecSwitchError) as held:
        sw.switches.save({"executor_enabled": True}, "user:root@x")
    assert held.value.field == "executor_enabled"


def test_the_settings_answer_says_which_switches_the_environment_holds(sw):
    admin = sw.login("root@x", is_admin=True)
    sw.environment("auto_fix_enabled", "false")
    sw.stored({"auto_fix_enabled": True, "executor_enabled": True})
    got = sw.client.get("/api/settings", headers=admin).json()
    assert got["auto_fix_enabled"] is False and got["executor_enabled"] is True
    assert got["execution_switches"]["locked"] == {"auto_fix_enabled": False}


@pytest.mark.parametrize("bad", [0, 1, "false", "true", None, [], {"on": True}, 1.0])
@pytest.mark.parametrize("name", ACTS_ALONE)
def test_a_stored_value_that_is_no_switch_reads_as_off_not_as_the_default(sw, name, bad):
    """Somebody stored SOMETHING for it — a hand edit, a restore from another version: nobody can tell what they
    meant, so nothing happens by itself (the store that cannot be read is treated the same way)."""
    sw.monkeypatch.setattr(sw.settings, name, True)             # the file: on
    sw.stored({name: bad})
    assert getattr(sw.switches.effective(), name) is False


def test_a_stored_value_that_is_no_switch_leaves_the_human_gate_at_its_default(sw):
    sw.monkeypatch.setattr(sw.settings, "executor_hitl_enabled", True)
    sw.stored({"executor_hitl_enabled": "false", "something_else": True})
    assert sw.switches.effective().executor_hitl_enabled is True


def test_the_executor_is_told_where_the_switch_is(sw):
    """The refusal used to say «Set AIOPS_EXECUTOR_ENABLED=true» — which does nothing against a stored «off»."""
    import importlib
    mod = importlib.import_module("agenticops.agents.executor_agent")   # the package exports the tool under this name
    text = mod.EXECUTOR_DISABLED_MESSAGE
    assert "Settings" in text and "administrator" in text
    assert "Set AIOPS_EXECUTOR_ENABLED=true" not in text
    import inspect
    assert "Set AIOPS_EXECUTOR_ENABLED=true" not in inspect.getsource(mod)


# ── D2 / D4: a run starts only while its issue waits for it ──────────────────────────────────────────────────
# A run moves its issue fix_approved → fix_executing and its result moves it on from there. N26 refused a closed
# issue's plan with «reopen it before running its plan» — but a reopened issue is `open`, which cannot follow a
# run (a passed run would not resolve it, an acceptance would be refused), and a resolved one cannot be reopened.
# And a ticket queued before the issue was closed — from the command line, during its confirmation prompt, without
# limit — was run when claimed.

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from agenticops.auth.actor import Actor
from agenticops.models import (Base, CloudAccount, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult,
                               get_session)
from agenticops.run_context import RunContext, reset_run_context, set_run_context
from agenticops.services.plan_content import stamp_approval
from agenticops.services.run_tickets import open_ticket

ADMIN = Actor("user", "root", 3, ("read", "write", "admin"))
CANNOT_FOLLOW = ["open", "investigating", "acknowledged", "root_cause_identified", "fix_planned", "fix_executed"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.galaxy.models  # noqa: F401
    import agenticops.models as models_mod
    import agenticops.scheduler.scheduler  # noqa: F401
    from agenticops.config import settings
    from agenticops.services import exec_switches
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/n27.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.delenv("AIOPS_EXECUTOR_ENABLED", raising=False)
    Base.metadata.create_all(models_mod.get_engine())
    exec_switches.invalidate()
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]))
    s.commit()
    with patch("agenticops.services.notification_service.notify_execution_result"), \
         patch("agenticops.services.notification_service.notify_im_origin"), \
         patch("agenticops.services.resolution_service.trigger_post_resolution"):
        yield s
    s.close()


def _approved(db, issue_status="fix_approved"):
    """An approved fix plan of an issue → (issue_id, plan_id)."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status=issue_status, resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="approved", approved_by="user:alice",
                   steps=[{"action": "look", "command": "aws sts get-caller-identity"}])
    db.add(plan); db.flush()
    stamp_approval(db, plan); db.commit()
    return issue.id, plan.id


def _state(db, issue_id, plan_id):
    db.expire_all()
    return (db.get(FixPlan, plan_id).status, db.get(HealthIssue, issue_id).status,
            [(r.status, r.error_message) for r in db.query(FixExecution).order_by(FixExecution.id)])


@contextmanager
def _as(actor, **fields):
    token = set_run_context(RunContext(actor=actor, agent_name="executor", **fields))
    try:
        yield
    finally:
        reset_run_context(token)


@contextmanager
def _executor():
    """executor_agent's real body without Bedrock; the model must never be reached."""
    ea = "agenticops.agents.executor_agent"
    with patch(f"{ea}.Agent") as agent_cls, patch(f"{ea}.BedrockModel"), \
         patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch(f"{ea}.get_cli_tool_for_issue", return_value=None), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.preamble.invoke_with_retry", side_effect=AssertionError("the model was reached")), \
         patch("agenticops.services.agent_log_service.track_agent"):
        yield agent_cls


@pytest.mark.parametrize("status", CANNOT_FOLLOW)
def test_no_run_is_opened_for_an_issue_that_cannot_follow_it(db, status):
    issue_id, plan_id = _approved(db, issue_status=status)
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket is None
    assert why.startswith(f"HealthIssue #{issue_id} is '{status}', not waiting for this plan's run")
    assert _state(db, issue_id, plan_id) == ("approved", status, [])       # nothing moved, nothing was written


@pytest.mark.parametrize("status", ["resolved", "dismissed"])
def test_a_closed_issue_is_said_as_closed_and_reopening_is_not_offered_as_the_way_to_run_its_plan(db, status):
    issue_id, plan_id = _approved(db, issue_status=status)
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket is None
    assert why.startswith(f"HealthIssue #{issue_id} is '{status}': its approved plan is not run")
    assert "reopen it before" not in why
    assert _state(db, issue_id, plan_id) == ("approved", status, [])


def test_an_issue_that_waits_for_the_run_gets_it(db):
    issue_id, plan_id = _approved(db)
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket and why == ""
    assert _state(db, issue_id, plan_id)[:2] == ("executing", "fix_executing")


@pytest.mark.parametrize("status", ["open", "dismissed"])
def test_the_run_route_refuses_what_the_issue_cannot_follow(db, status):
    from agenticops.web import deps
    from agenticops.web.app import app
    issue_id, plan_id = _approved(db, issue_status=status)
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    try:
        r = TestClient(app).post(f"/api/fix-plans/{plan_id}/execute", json={})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 409, r.text
    assert r.json()["detail"].startswith(f"HealthIssue #{issue_id} is '{status}'")
    assert _state(db, issue_id, plan_id) == ("approved", status, [])


def test_the_page_is_not_offered_a_run_the_issue_cannot_follow(db):
    from agenticops.services import ui_actions
    _issue, plan_id = _approved(db, issue_status="open")
    plan = db.get(FixPlan, plan_id)
    for status in CANNOT_FOLLOW:
        acts = {a["action"]: a for a in ui_actions.plan_actions(plan, ADMIN, issue_status=status, run_in_flight=False)}
        assert (acts["execute"]["allowed"], acts["execute"]["reason_code"]) == (False, "issue_moved"), status
    closed = {a["action"]: a for a in ui_actions.plan_actions(plan, ADMIN, issue_status="dismissed", run_in_flight=False)}
    assert closed["execute"]["reason_code"] == "issue_closed"
    live = {a["action"]: a for a in ui_actions.plan_actions(plan, ADMIN, issue_status="fix_approved", run_in_flight=False)}
    assert live["execute"]["allowed"] is True
    # a plan with no issue status known (the caller did not look) is not refused on a guess
    unknown = {a["action"]: a for a in ui_actions.plan_actions(plan, ADMIN, issue_status=None, run_in_flight=False)}
    assert unknown["execute"]["allowed"] is True


@pytest.mark.parametrize("closed_as", ["dismissed", "resolved"])
def test_a_queued_run_whose_issue_was_closed_meanwhile_is_refused_when_it_is_claimed(db, closed_as):
    from agenticops.agents.executor_agent import executor_agent
    from agenticops.services.issue_state import transition_issue
    issue_id, plan_id = _approved(db)
    ticket, _ = open_ticket(plan_id, executed_by="user:alice")     # what POST /execute + the claim leave: running
    transition_issue(db, issue_id, closed_as, actor="user:bob", reason="not needed any more")
    db.commit()
    with _executor() as agent_cls, _as("agent:executor", fix_plan_id=plan_id, execution_id=ticket):
        answer = executor_agent(fix_plan_id=plan_id)
    assert answer.startswith("REJECTED") and f"is '{closed_as}'" in answer
    agent_cls.assert_not_called()                                  # no model was built, no command could run
    plan_status, issue_status, rows = _state(db, issue_id, plan_id)
    assert (plan_status, issue_status) == ("failed", closed_as)    # the approval is spent; the issue stays closed
    assert rows[0][0] == "failed" and f"is '{closed_as}'" in rows[0][1]
    db.expire_all()
    assert db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type="rca_disputed").count() == 0


def test_a_queued_run_whose_issue_still_waits_is_not_refused(db):
    from agenticops.agents.executor_agent import executor_agent
    issue_id, plan_id = _approved(db)
    ticket, _ = open_ticket(plan_id, executed_by="user:alice")
    ea = "agenticops.agents.executor_agent"
    with patch(f"{ea}.Agent") as agent_cls, patch(f"{ea}.BedrockModel"), \
         patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch(f"{ea}.get_cli_tool_for_issue", return_value=None), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.preamble.invoke_with_retry", side_effect=lambda agent, prompt, **kw: "worked"), \
         patch("agenticops.services.agent_log_service.track_agent"), \
         _as("agent:executor", fix_plan_id=plan_id, execution_id=ticket):
        executor_agent(fix_plan_id=plan_id)
    agent_cls.assert_called_once()


def test_the_refusal_reads_the_issue_as_it_is_now_not_as_the_session_remembers_it(db):
    """A session that has the issue in hand (the command line's, over its unbounded prompt; any long request)
    must not answer from that copy."""
    from agenticops.services.issue_state import run_refusal, transition_issue
    issue_id, _plan_id = _approved(db)
    held = db.get(HealthIssue, issue_id)                           # this session holds the issue …
    assert held.status == "fix_approved" and run_refusal(db, issue_id) is None
    other = get_session()
    try:
        transition_issue(other, issue_id, "dismissed", actor="user:bob", reason="not needed")   # … another closes it
        other.commit()
    finally:
        other.close()
    assert "is 'dismissed'" in (run_refusal(db, issue_id) or "")
    assert held.status == "dismissed"


def test_the_command_line_looks_at_the_issue_after_its_confirmation_not_before(db):
    """The prompt waits without limit: an issue dismissed while it waited was queued and run."""
    import agenticops.cli.main as cli
    from agenticops.services.issue_state import transition_issue
    issue_id, plan_id = _approved(db)

    def dismissed_meanwhile(*_a, **_k):
        other = get_session()
        try:
            transition_issue(other, issue_id, "dismissed", actor="user:bob", reason="not needed")
            other.commit()
        finally:
            other.close()
        return True                                                # «yes, execute»

    with patch("rich.prompt.Confirm.ask", side_effect=dismissed_meanwhile), patch.object(cli, "init_db"), \
         patch("agenticops.auth.actor.cli_actor", return_value=ADMIN):
        out = cli._slash_execute(None, [str(plan_id)])
    assert "is 'dismissed'" in out
    assert _state(db, issue_id, plan_id) == ("approved", "dismissed", [])


# ── D5: a run that only ran the plan's own checks tried nothing ──────────────────────────────────────────────
# N26 ①: «a run that was aborted before any step does not dispute the diagnosis». What «tried» meant was every
# command the guard let through that is not provably read-only — and most real pre-checks are not on any read
# list (`systemctl is-active nginx`, `curl -s localhost/health`, `ss -ltnp`): a failed pre-check still disputed.

import json
from types import SimpleNamespace as NS

from agenticops.agents.run_guard import RunGuard, applied_of, tried_of

PRE = "systemctl is-active nginx"                      # no read list knows it: tier `unknown`
POST = "curl -s -o /dev/null -w '%{http_code}' http://localhost/health"
STEP = "systemctl restart nginx"


def _with_checks(db):
    """An approved plan with a pre-check and a post-check the classifier cannot vouch for, its run record open →
    (issue_id, plan_id, rca_id, execution_id)."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="approved", approved_by="user:alice",
                   pre_checks=[{"description": "the unit is up", "command": PRE, "expected": "active"}],
                   steps=[{"action": "restart", "command": STEP}],
                   post_checks=[{"description": "it answers", "command": POST, "expected": "200"}])
    db.add(plan); db.flush()
    stamp_approval(db, plan); db.commit()
    ticket, why = open_ticket(plan.id, executed_by="agent:auto-pipeline")
    assert ticket, why
    return issue.id, plan.id, rca.id, ticket


def _call(guard, command, tool="run_on_host"):
    """One tool call past the guard, as Strands hands it over → the refusal, or None when it was let through."""
    event = NS(tool_use={"name": tool, "toolUseId": f"t-{id(command)}-{guard.applied}", "input": {"command": command}}, cancel_tool=None)
    guard._before_tool(event)
    return event.cancel_tool


def _aborted(plan_id, ticket, steps=()):
    from agenticops.tools.metadata_tools import save_execution_result
    with _as("agent:auto-pipeline", fix_plan_id=plan_id, execution_id=ticket):
        return save_execution_result(fix_plan_id=plan_id, status="aborted", step_results=json.dumps(list(steps)),
                                     error_message="pre-check failed: the unit is not active")


def _disputed(db, issue_id) -> int:
    db.expire_all()
    return db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type="rca_disputed").count()


def test_the_plans_own_checks_are_not_the_plan_being_tried(db):
    issue_id, plan_id, rca_id, ticket = _with_checks(db)
    guard = RunGuard(ticket)
    assert _call(guard, PRE) is None                            # the pre-check ran …
    assert (guard.applied, guard.tried) == (1, 0)               # … not provably a read, but not a step either
    assert tried_of(ticket) == 0 and applied_of(ticket) == 1
    _aborted(plan_id, ticket)                                   # it failed: the run is aborted before its first step
    assert _disputed(db, issue_id) == 0
    assert db.get(RCAResult, rca_id).critic_verdict is None
    assert db.get(HealthIssue, issue_id).status == "root_cause_identified" and db.get(FixPlan, plan_id).status == "failed"


def test_a_check_written_another_way_is_still_that_check(db):
    """As the plan writes it, give or take spaces — and a kubectl check through run_kubectl, which takes the
    subcommand without the word."""
    issue_id, plan_id, _rca, ticket = _with_checks(db)
    guard = RunGuard(ticket)
    assert _call(guard, "  systemctl   is-active  nginx ") is None
    assert _call(guard, POST) is None
    assert guard.tried == 0


def test_a_step_of_the_plan_is_the_plan_being_tried(db):
    issue_id, plan_id, rca_id, ticket = _with_checks(db)
    guard = RunGuard(ticket)
    _call(guard, PRE)
    assert _call(guard, STEP) is None
    assert (guard.applied, guard.tried) == (2, 1)
    _aborted(plan_id, ticket, steps=({"step_index": 1, "status": "failed"},))
    assert _disputed(db, issue_id) == 1
    assert db.get(RCAResult, rca_id).critic_verdict == "disputed_by_execution"


def test_a_command_that_is_not_in_the_plan_at_all_is_something_tried(db):
    """Not a check of this plan, not provably a read: nobody can say it changed nothing."""
    issue_id, plan_id, _rca, ticket = _with_checks(db)
    guard = RunGuard(ticket)
    assert _call(guard, "systemctl is-active redis") is None
    assert guard.tried == 1
    _aborted(plan_id, ticket)
    assert _disputed(db, issue_id) == 1


def test_a_read_only_command_counts_as_neither(db):
    _issue, _plan_id, _rca, ticket = _with_checks(db)
    guard = RunGuard(ticket)
    assert _call(guard, "aws ec2 describe-instances --instance-ids i-0", tool="run_aws_cli_readonly") is None
    assert (guard.applied, guard.tried) == (0, 0)


def test_after_a_stop_a_check_still_counts_as_possibly_applied(db):
    """The stop keeps the cautious count: after a pre-check nobody can vouch for, the plan's rollback is not
    refused as «nothing was applied»."""
    from agenticops.agents.run_guard import guard_decision
    from agenticops.services import run_tickets
    _issue, plan_id, _rca, ticket = _with_checks(db)
    plan = db.get(FixPlan, plan_id)
    plan.rollback_plan = {"steps": [{"action": "back", "command": "systemctl start nginx-old"}]}
    db.commit()
    guard = RunGuard(ticket)
    _call(guard, PRE)
    assert (guard.applied, guard.tried) == (1, 0)
    assert run_tickets.request_stop(ticket, by="user:alice")
    # through the guard's own hook: the plan's rollback line is let through …
    assert _call(guard, "systemctl start nginx-old") is None
    # … which the lenient count would have refused («nothing to roll back»)
    state = run_tickets.ticket_state(ticket)
    assert "nothing to roll back" in guard_decision(state, "run_on_host", {"command": "systemctl start nginx-old"}, applied=0)


def test_when_the_plans_checks_cannot_be_read_everything_counts(db, monkeypatch):
    _issue, _plan_id, _rca, ticket = _with_checks(db)
    from agenticops.services import run_tickets
    monkeypatch.setattr(run_tickets, "check_commands_of", lambda _id: (_ for _ in ()).throw(RuntimeError("database is locked")))
    guard = RunGuard(ticket)
    _call(guard, PRE)
    assert (guard.applied, guard.tried) == (1, 1)


# ── B3 / B6 / B7 / B2: the security collectors ───────────────────────────────────────────────────────────────

from agenticops.security import collectors as col

REPORT_HEAD = ("user,arn,user_creation_time,password_enabled,password_last_used,password_last_changed,mfa_active,"
               "access_key_1_active,access_key_1_last_rotated,access_key_2_active,access_key_2_last_rotated")
OLD, NEW = "2019-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"


def _report(*rows: str) -> dict:
    return {"Content": "\n".join([REPORT_HEAD, *rows]).encode()}


def _user(name, key1=("false", "N/A"), key2=("false", "N/A"), console="false", mfa="false"):
    return f"{name},arn:x,2019-01-01T00:00:00+00:00,{console},N/A,N/A,{mfa},{key1[0]},{key1[1]},{key2[0]},{key2[1]}"


def _iam(report, states=({"State": "COMPLETE"},)):
    iam = MagicMock()
    iam.generate_credential_report.side_effect = list(states) + [states[-1]] * 50
    iam.get_credential_report.return_value = report
    return iam


# B3 — an account is read through a region of its OWN partition
@pytest.mark.parametrize("regions, home", [(["cn-north-1", "cn-northwest-1"], "cn-north-1"),
                                           (["us-gov-west-1"], "us-gov-west-1"),
                                           (["ap-southeast-1", "us-east-1"], "ap-southeast-1")])
def test_the_account_wide_sources_are_read_in_a_region_of_the_accounts_own_partition(regions, home):
    """IAM was asked in us-east-1 and S3 / CloudTrail in the model's region: a China account's credentials are
    refused there, so three sources could never be read (before N20 that read as five passes)."""
    asked = []
    client = MagicMock()
    client.get_credential_report.return_value = _report()
    client.generate_credential_report.return_value = {"State": "COMPLETE"}
    client.list_buckets.return_value = {"Buckets": []}
    client.describe_trails.return_value = {"trailList": []}
    client.get_paginator.return_value.paginate.return_value = []

    def get_client(service, region, account=""):
        asked.append((service, region))
        return client

    with patch.object(col, "_get_client", side_effect=get_client), patch.object(col, "_enabled_regions", return_value=regions):
        col.collect_iam_findings("acct")
        col.collect_data_findings("acct")
        col.collect_logging_findings("acct")
    by_service = {service: region for service, region in asked if service != "ec2"}
    assert by_service == {"iam": home, "s3": home, "cloudtrail": home}
    assert {region for service, region in asked if service == "ec2"} == set(regions)


# B7 — the credential report is read once it is ready
def test_the_credential_report_is_read_once_it_is_ready():
    iam = _iam(_report(_user("alice", console="true")), states=({"State": "STARTED"}, {"State": "INPROGRESS"}, {"State": "COMPLETE"}))
    health, slept = {}, []
    with patch.object(col, "_get_client", return_value=iam), patch.object(col, "_enabled_regions", return_value=["us-east-1"]), \
         patch.object(col, "_sleep", side_effect=slept.append):
        out = col.collect_iam_findings("acct", health=health)
    assert iam.generate_credential_report.call_count == 3 and iam.get_credential_report.call_count == 1
    assert len(slept) == 2                                       # it waited between the asks, not after the last
    assert [f.control_id for f in out] == ["cis-1.10"] and health["iam"]["ok"] is True


def test_a_report_that_does_not_become_ready_in_time_is_a_source_that_was_not_read():
    class NotReady(Exception):
        response = {"Error": {"Code": "ReportInProgress"}}
        operation_name = "GetCredentialReport"
    iam = _iam(None, states=({"State": "INPROGRESS"},))
    iam.get_credential_report.side_effect = NotReady("not yet")
    health, slept = {}, []
    with patch.object(col, "_get_client", return_value=iam), patch.object(col, "_enabled_regions", return_value=["us-east-1"]), \
         patch.object(col, "_sleep", side_effect=slept.append):
        out = col.collect_iam_findings("acct", health=health)
    assert out == [] and health["iam"] == {"ok": False, "error": "ReportInProgress (GetCredentialReport)"}
    assert iam.generate_credential_report.call_count == col.REPORT_ASKS      # bounded …
    assert len(slept) == col.REPORT_ASKS - 1 and sum(slept) <= 30             # … with no wait after the last ask


def test_a_refused_ask_for_a_new_report_still_reads_the_one_there_is():
    iam = _iam(_report(_user("alice", console="true")))
    iam.generate_credential_report.side_effect = RuntimeError("AccessDenied")
    with patch.object(col, "_get_client", return_value=iam), patch.object(col, "_enabled_regions", return_value=["us-east-1"]), \
         patch.object(col, "_sleep"):
        out = col.collect_iam_findings("acct")
    assert [f.control_id for f in out] == ["cis-1.10"]


# B6 — both access keys are looked at
@pytest.mark.parametrize("row, controls", [
    (_user("<root_account>", key2=("true", NEW)), ["cis-1.4"]),                  # root: key 2 alone is active
    (_user("<root_account>", key1=("true", NEW), key2=("true", NEW)), ["cis-1.4"]),   # … said once
    (_user("<root_account>"), []),
    (_user("bob", key2=("true", OLD)), ["cis-1.3"]),                             # key 2 alone is active and old
    (_user("bob", key1=("true", OLD), key2=("true", OLD)), ["cis-1.3"]),         # one finding per user
    (_user("bob", key1=("true", NEW), key2=("true", OLD)), ["cis-1.3"]),
    (_user("bob", key1=("true", NEW), key2=("true", NEW)), []),
    (_user("bob", key1=("false", OLD), key2=("false", OLD)), []),                # old, but not in use
])
def test_both_access_keys_are_looked_at(row, controls):
    with patch.object(col, "_get_client", return_value=_iam(_report(row))), patch.object(col, "_enabled_regions", return_value=["us-east-1"]), \
         patch.object(col, "_sleep"):
        out = col.collect_iam_findings("acct")
    assert [f.control_id for f in out] == controls


def test_a_report_without_the_second_keys_columns_reads_as_before():
    old_head = REPORT_HEAD.rsplit(",access_key_2_active", 1)[0]
    report = {"Content": "\n".join([old_head, "bob,arn:x,2019-01-01T00:00:00+00:00,false,N/A,N/A,false,true," + OLD]).encode()}
    with patch.object(col, "_get_client", return_value=_iam(report)), patch.object(col, "_enabled_regions", return_value=["us-east-1"]), \
         patch.object(col, "_sleep"):
        assert [f.control_id for f in col.collect_iam_findings("acct")] == ["cis-1.3"]


# B2 — what was read before a region failed is kept
def _open_ssh(gid):
    return {"SecurityGroups": [{"GroupId": gid, "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                                                                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]}]}


def test_the_security_groups_read_before_a_region_failed_are_kept():
    """Region 3 was throttled, and the open group seen in region 1 was thrown away with it: the page said «0
    reachable paths» of an account with a group open to the world."""
    def get_client(service, region, account=""):
        client = MagicMock()
        if region == "r3":
            client.describe_security_groups.side_effect = RuntimeError("Throttling")
        else:
            client.describe_security_groups.return_value = _open_ssh("sg-" + region) if region == "r1" else {"SecurityGroups": []}
        return client
    health = {}
    with patch.object(col, "_get_client", side_effect=get_client), patch.object(col, "_enabled_regions", return_value=["r1", "r2", "r3"]):
        out = col.collect_network_findings("acct", health=health)
    assert [(f.control_id, f.resource_id) for f in out] == [("cis-4.1", "sg-r1")]
    assert health["network"]["ok"] is False and health["network"]["error"].startswith("r3: ")


# ── B2 (the page's half): «0 reachable paths» is not said of an account whose security groups were not read ───

@pytest.fixture
def sec(monkeypatch):
    from contextlib import contextmanager as cm
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import agenticops.models as models
    from agenticops.services import security_service
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @cm
    def session():
        s = Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()
    monkeypatch.setattr(security_service, "get_db_session", session)
    with session() as s:
        s.add(models.CloudAccount(id=1, name="acct-a", provider="aws", regions=["us-east-1"], credentials={}))

    def snapshot(network_ok, paths=()):
        from datetime import datetime, timezone
        health = None if network_ok is None else {
            "status": "complete" if network_ok else "partial",
            "sources": {"iam": {"ok": True, "error": ""}, "network": {"ok": network_ok, "error": "" if network_ok else "r3: Throttling"}}}
        with session() as s:
            s.query(models.SecuritySnapshot).delete()
            s.add(models.SecuritySnapshot(account_id="acct-a", provider="aws", overall_score=70.0, category_scores={},
                                          exposure_paths=list(paths), collection_health=health,
                                          created_at=datetime.now(timezone.utc)))
        return security_service.security_summary()["accounts"][0]
    return NS(snapshot=snapshot, service=security_service)


REACH = {"resource_id": "sg-1", "port": 22, "path": ["internet", "i-1:22"], "reachability": "reachable"}


def test_an_account_whose_security_groups_were_not_read_has_no_count_of_reachable_paths(sec):
    row = sec.snapshot(network_ok=False)
    assert (row["reachable_paths"], row["exposure_read"]) == (None, False)


def test_what_was_seen_before_the_read_failed_is_counted_and_marked_as_not_all(sec):
    row = sec.snapshot(network_ok=False, paths=[REACH])
    assert (row["reachable_paths"], row["exposure_read"]) == (1, False)


def test_an_account_that_was_read_says_zero_when_there_is_none(sec):
    assert [sec.snapshot(network_ok=True)[k] for k in ("reachable_paths", "exposure_read")] == [0, True]
    assert [sec.snapshot(network_ok=True, paths=[REACH])[k] for k in ("reachable_paths", "exposure_read")] == [1, True]


def test_a_snapshot_from_before_collection_was_recorded_says_what_it_said(sec):
    assert [sec.snapshot(network_ok=None)[k] for k in ("reachable_paths", "exposure_read")] == [0, None]


# ── B1: one account's finding is not folded into another account's issue ─────────────────────────────────────
# The gate's «same resource and same type» rule did not look at the account. Two accounts that both lack a
# multi-region trail report the same resource («account») and type: the second account never got an issue of its
# own, so since N20 its card lacked the finding its own score counts.

@pytest.fixture
def gate(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/gate.db")
    for name, value in (("signal_gate_enabled", True), ("signal_gate_llm_enabled", False), ("noise_flap_threshold", 0),
                        ("resource_dedup_enabled", True), ("dedup_resolved_cooldown_minutes", 60), ("issue_exclude_patterns", [])):
        monkeypatch.setattr(settings, name, value)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=1, name="acct-a", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"]),
               CloudAccount(id=2, name="acct-b", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])])
    s.commit()
    yield s
    s.close()


def _finding_signal(account, **kw):
    from agenticops.services.signal_gate import SignalInput
    fields = dict(source="security_posture", title="[cis-3.1] CloudTrail account: no multi-region trail actively logging",
                  description="d", severity="high", resource_id="account", account_id=account, provider="aws",
                  issue_type="security_finding", upstream_key="cis-3.1", kind="detection", auto_rca=False,
                  detected_by="security_posture")
    fields.update(kw)
    return SignalInput(**fields)


def _gate(sig):
    from agenticops.services import signal_gate
    with patch("agenticops.services.rca_service.trigger_auto_rca"), \
         patch("agenticops.services.notification_service.notify_issue_created"):
        return signal_gate.process_signal(sig)


def test_the_same_finding_in_two_accounts_is_two_issues(gate):
    first = _gate(_finding_signal("acct-a"))
    second = _gate(_finding_signal("acct-b"))
    assert (first.disposition, second.disposition) == ("promoted", "promoted")
    assert second.issue_id != first.issue_id
    gate.expire_all()
    assert {i.account_id for i in gate.query(HealthIssue)} == {1, 2}


def test_the_same_finding_again_in_the_same_account_is_still_one_issue(gate):
    first = _gate(_finding_signal("acct-a", upstream_key="k1"))
    again = _gate(_finding_signal("acct-a", upstream_key="k2", title="[cis-3.1] CloudTrail: nothing is logging"))
    assert (again.disposition, again.reason, again.issue_id) == ("merged", "resource_type_merge", first.issue_id)


def test_a_signal_that_names_no_account_merges_as_before(gate):
    """Nobody can tell which account it is of: the rule stays what it was (one issue, not two)."""
    first = _gate(_finding_signal("acct-a", upstream_key="k1"))
    unknown = _gate(_finding_signal("", upstream_key="k2", title="[cis-3.1] CloudTrail: nothing is logging"))
    assert (unknown.disposition, unknown.issue_id) == ("merged", first.issue_id)


def test_an_issue_that_has_no_account_takes_a_signal_of_any_account(gate):
    first = _gate(_finding_signal("", upstream_key="k1", detected_by="detect_agent", source="detect_agent"))
    gate.expire_all()
    assert gate.get(HealthIssue, first.issue_id).account_id is None
    second = _gate(_finding_signal("acct-b", upstream_key="k2", detected_by="detect_agent", source="detect_agent",
                                   title="[cis-3.1] CloudTrail: nothing is logging"))
    assert (second.disposition, second.issue_id) == ("merged", first.issue_id)


def test_the_gray_zone_judge_is_not_shown_another_accounts_issue(gate, monkeypatch):
    from agenticops.config import settings
    from agenticops.services import signal_gate
    _gate(_finding_signal("acct-a"))
    monkeypatch.setattr(settings, "signal_gate_llm_enabled", True)
    shown = []
    monkeypatch.setattr(signal_gate, "_llm_judge", lambda sig, candidates: shown.append([c.id for c in candidates]) or None)
    _gate(_finding_signal("acct-b", resource_id="account", issue_type="security_finding"))
    assert shown == [] or all(not ids for ids in shown)          # acct-a's issue is no candidate for acct-b's signal


# ── B5: filling an issue's account at startup restamps its plans ─────────────────────────────────────────────
# The account is plan content (it is in the hash). The 2.9.0 backfill filled the account and left the plans'
# hashes behind: the next approval was answered «changed since it was loaded» though nobody had changed it, and
# «request changes» was refused every time.

def test_the_startup_backfill_that_fills_an_issues_account_restamps_its_waiting_plans(tmp_path):
    import sqlalchemy as sa
    from sqlalchemy.orm import Session
    import agenticops.models as models
    from agenticops.services import plan_content
    eng = sa.create_engine(f"sqlite:///{tmp_path}/backfill.db")
    models.Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(models.CloudAccount(id=1, name="prod", provider="aws"))
        issue = models.HealthIssue(resource_id="arn:aws:s3:::b", severity="high", source="security_poll", title="t",
                                   description="", status="fix_planned", detected_by="security_poll", account_id=None)
        s.add(issue); s.flush()
        s.add(models.AlertEvent(source="security_poll", external_id="k", severity="high", title="t", description="",
                                resource_hint="", raw_payload={}, health_issue_id=issue.id, account_id="prod",
                                disposition="promoted"))
        rca = models.RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        waiting = models.FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s",
                                 status="pending_approval", steps=[{"action": "a", "command": "aws s3api put-public-access-block --bucket b"}])
        s.add(waiting); s.flush()
        plan_content.stamp_content(s, waiting)                      # as it was stamped: with no account
        s.commit()
        issue_id, plan_id, hash_before, version_before = issue.id, waiting.id, waiting.content_hash, waiting.plan_version

    models._backfill_security_issue_accounts_2_9_0(eng)

    with Session(eng) as s:
        assert s.get(models.HealthIssue, issue_id).account_id == 1
        plan = s.get(models.FixPlan, plan_id)
        assert plan.content_hash != hash_before                    # the account is in the hash …
        assert plan.content_hash == plan_content.current_hash(s, plan)   # … and the stored hash is the plan's again
        assert plan.plan_version == version_before + 1
        assert plan_content.approval_conflict(s, plan, plan.content_hash) is None   # what the page loads can be approved


# ── B9: a report's coverage lists what was read — not what was asked for, nor what could not be read ─────────

def _cov_db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.models import CloudResource
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/cov.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(id=1, name="prod", provider="aws", is_enabled=True, regions=["us-east-1"]))
    s.add(CloudResource(account_id=1, provider="aws", region="us-east-1", resource_type="EC2", resource_id="i-1",
                        name="n", tags={}, raw_data={}, managed=True))
    s.commit()
    return s


def test_a_region_the_model_asked_for_and_nothing_was_found_in_is_not_a_region_that_was_read(tmp_path, monkeypatch):
    """The card says «recorded by the system, not written by the model» — and listed whatever region the model
    passed as the filter, inventory there or not."""
    from agenticops.run_context import run_context
    from agenticops.services import report_coverage as rc
    from agenticops.tools.metadata_tools import get_managed_resources
    s = _cov_db(tmp_path, monkeypatch)
    try:
        with run_context(coverage=rc.begin()):
            get_managed_resources(region="eu-central-1")
            get_managed_resources(region="anything at all")
            assert rc.current().as_dict()["regions"] == []
            get_managed_resources(region="us-east-1")
            assert rc.current().as_dict()["regions"] == ["us-east-1"]
    finally:
        s.close()


def test_an_account_whose_credentials_could_not_be_resolved_is_not_coverage(tmp_path, monkeypatch):
    from agenticops.credentials import resolver
    from agenticops.run_context import run_context
    from agenticops.services import report_coverage as rc
    s = _cov_db(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(resolver, "get_cached_session", lambda key: None)
        monkeypatch.setattr("agenticops.providers.get_provider",
                            lambda snap: NS(resolve_credentials=lambda: False, sdk_session=lambda: None))
        with run_context(coverage=rc.begin()):
            with pytest.raises(resolver.AccountResolutionError):
                resolver.resolve_account_session("prod", "us-east-1")
            assert (rc.current().as_dict()["accounts"], rc.current().as_dict()["regions"]) == ([], [])
        # … and one that resolves is
        monkeypatch.setattr("agenticops.providers.get_provider",
                            lambda snap: NS(resolve_credentials=lambda: True, sdk_session=lambda: object()))
        monkeypatch.setattr(resolver, "set_cached_session", lambda key, session: None)
        with run_context(coverage=rc.begin()):
            resolver.resolve_account_session("prod", "us-east-1")
            assert (rc.current().as_dict()["accounts"], rc.current().as_dict()["regions"]) == (["prod"], ["us-east-1"])
    finally:
        s.close()


def test_a_run_that_read_no_account_and_no_region_is_not_called_complete():
    from agenticops.services import report_coverage as rc
    assert rc.begin().as_dict()["completeness"] == "none"
    read = rc.begin(); read.accounts.add("prod")
    assert read.as_dict()["completeness"] == "complete"
    cut = rc.begin(); cut.truncated = 1
    assert cut.as_dict()["completeness"] == "partial"


# ── C2: two administrators saving at once — the stored switches are read under a row lock ───────────────────
# The save read the stored object, merged in Python and wrote it back. On PostgreSQL two saves a few milliseconds
# apart both read the old object, and the second overwrote the first: one administrator's «executor off» was
# silently undone (SQLite serialises writers, so it could not happen there).

def test_the_stored_switches_are_read_for_update_inside_the_saving_transaction(sw):
    from sqlalchemy.dialects import postgresql
    from agenticops.models import get_db_session
    with get_db_session() as s:
        query = sw.switches._stored_row_locked(s)
        sql = str(query.statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "runtime_settings" in sql


def test_a_save_merges_into_what_the_transaction_reads_not_into_what_was_remembered(sw):
    """What another administrator stored after this process last looked is kept: the merge base is read inside
    the saving transaction, never taken from the one-second memo."""
    from agenticops.models import get_db_session
    assert sw.switches.effective().executor_enabled is False        # the memo now holds «nothing stored»
    sw.switches.runtime_settings.put(sw.switches.KEY, {"auto_fix_enabled": True}, "user:other-admin")   # behind the memo's back
    with get_db_session() as s:
        sw.switches.save({"executor_enabled": True}, "user:root@x", session=s)
    sw.switches.invalidate()
    got = sw.switches.effective()
    assert (got.executor_enabled, got.auto_fix_enabled) == (True, True)


# ── C4 / C10: «connected» is recorded for what was tested, and what is kept names no role or account ────────
# N23: «a check counts only for the credentials it tested». The test asked a session cache keyed by the account's
# NAME (an hour): after the credentials were re-pointed from the command line, or the account deleted and created
# again under its name, the old session answered and «connected» was recorded for the new ones.

class _FakeBoto:
    """boto3.Session stand-in: every session built says which AWS account its credentials reach."""
    built = 0
    reaches = "222222222222"

    def __init__(self, **kwargs):
        type(self).built += 1
        self.account = type(self).reaches

    def client(self, name, **kwargs):
        account = self.account
        return NS(get_caller_identity=lambda: {"Arn": f"arn:aws:iam::{account}:user/tester", "Account": account})


@pytest.fixture
def factory(tmp_path, monkeypatch):
    import boto3
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.credentials.session_factory import SessionFactory
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/accounts.db")
    Base.metadata.create_all(models_mod.get_engine())
    _FakeBoto.built, _FakeBoto.reaches = 0, "222222222222"
    monkeypatch.setattr(boto3, "Session", _FakeBoto)
    SessionFactory.reset()
    s = get_session()

    def account(name="prod", provider="aws", credentials=None, source="environment"):
        row = CloudAccount(name=name, provider=provider, is_enabled=True, regions=["us-east-1"],
                           credential_source_type=source, credentials=credentials or {})
        s.add(row); s.commit()
        return row.id
    yield NS(make=SessionFactory.instance, account=account, db=s)
    s.close()
    SessionFactory.reset()


def test_a_connection_test_never_answers_from_a_session_built_before(factory):
    factory.account()
    f = factory.make()
    old = _FakeBoto(); old.account = "111111111111"                 # a session cached while the account pointed elsewhere
    f._cache_session("prod:us-east-1", old)
    built = _FakeBoto.built
    result = f.test_connection("prod")
    assert result["success"] is True and result["account_id"] == "222222222222"      # the credentials stored NOW
    assert _FakeBoto.built == built + 1


def test_credentials_that_reach_another_aws_account_than_the_registered_one_are_not_connected(factory):
    """The provider layer refuses such an account for every scan and command; the test said «connected»."""
    factory.account(credentials={"account_id": "333333333333"})
    result = factory.make().test_connection("prod")
    assert result["success"] is False and result["account_id"] == "222222222222"
    assert "another AWS account" in result["reason"]
    factory.db.query(CloudAccount).update({"credentials": {"account_id": "222222222222"}}); factory.db.commit()
    assert factory.make().test_connection("prod")["success"] is True


def test_an_account_that_is_not_registered_is_not_tested_with_the_hosts_own_credentials(factory):
    built = _FakeBoto.built
    result = factory.make().test_connection("nobody")
    assert result["success"] is False and "not registered" in result["error"]
    assert _FakeBoto.built == built                                  # no session was built: nothing ambient answered


def test_an_account_of_another_provider_gets_no_aws_verdict(factory):
    factory.account(name="cluster", provider="kubernetes", credentials={"kubeconfig_path": "/x"})
    built = _FakeBoto.built
    result = factory.make().test_connection("cluster")
    assert (result["success"], result["untested"]) == (False, True)
    assert _FakeBoto.built == built


def test_a_refused_call_keeps_its_code_and_operation_not_its_sentence(factory):
    class Refused(Exception):
        response = {"Error": {"Code": "AccessDenied"}}
        operation_name = "AssumeRole"

        def __str__(self):
            return ("An error occurred (AccessDenied) when calling the AssumeRole operation: User: "
                    "arn:aws:iam::111111111111:user/ops is not authorized to perform: sts:AssumeRole on resource: "
                    "arn:aws:iam::222222222222:role/aiops")
    factory.account()
    f = factory.make()
    f.get_session = lambda *a, **k: (_ for _ in ()).throw(Refused())
    result = f.test_connection("prod")
    assert result["success"] is False and "111111111111" in result["error"]          # the person who tested sees it all
    assert result["reason"] == "AccessDenied (AssumeRole)"                            # what is kept names nobody


def test_what_the_setup_overview_keeps_of_a_failed_test_names_no_role_or_account(factory):
    from agenticops.models import ReadinessCheck
    from agenticops.services import readiness
    pk = factory.account()
    row = factory.db.get(CloudAccount, pk)
    sentence = ("An error occurred (AccessDenied) when calling the AssumeRole operation: User: arn:aws:iam::111111111111:user/ops "
                "is not authorized to perform: sts:AssumeRole on resource: arn:aws:iam::222222222222:role/aiops")
    # with the reason the test itself gives …
    readiness.record_account_test(factory.db, row, {"success": False, "error": sentence, "reason": "AccessDenied (AssumeRole)"}, "user:root")
    # … and from the sentence alone (an older answer shape)
    readiness.record_account_test(factory.db, row, {"success": False, "error": sentence}, "user:root")
    factory.db.commit()
    details = [r.detail for r in factory.db.query(ReadinessCheck).order_by(ReadinessCheck.id)]
    assert details == ["AccessDenied (AssumeRole)", "AccessDenied (AssumeRole)"]


def test_a_test_that_gave_no_verdict_is_not_recorded(factory):
    from agenticops.models import ReadinessCheck
    from agenticops.services import readiness
    pk = factory.account(name="cluster", provider="kubernetes")
    readiness.record_account_test(factory.db, factory.db.get(CloudAccount, pk),
                                  {"success": False, "untested": True, "error": "only AWS accounts can be tested"}, "user:root")
    factory.db.commit()
    assert factory.db.query(ReadinessCheck).count() == 0
