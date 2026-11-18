"""An agent run's steps are on record while it works (MVP-2.9.0 N10).

The recorder is a Strands hook. These tests drive a REAL strands Agent — its loop, its hooks, its tool executor —
with a model that answers from a script and tools that only record what they were asked: no Bedrock, no cloud.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from strands import Agent, tool
from strands.models import Model
from strands.tools.executors import SequentialToolExecutor

from agenticops.agents.run_guard import RunGuard
from agenticops.agents.step_recorder import StepRecorder, plan_refs, step_look
from agenticops.models import AgentStep, Base, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services.plan_content import stamp_approval
from agenticops.services.run_tickets import close_ticket, open_ticket, request_stop

STEP_1 = "aws ec2 revoke-security-group-ingress --group-id sg-1 --protocol tcp --port 22 --cidr 0.0.0.0/0"
STEP_2 = "aws ec2 create-tags --resources sg-1 --tags Key=reviewed,Value=yes"
ROLLBACK = "aws ec2 authorize-security-group-ingress --group-id sg-1 --protocol tcp --port 22 --cidr 0.0.0.0/0"
CHECK = "aws ec2 describe-security-groups --group-ids sg-1"
READ = "aws ec2 describe-instances --instance-ids i-1"


class Scripted(Model):
    """Answers each model call with the next entry of `script`: a final text, a list of (tool, input) calls, or
    {"say": text, "calls": [...]} — words and calls in one message, as a model narrates before it acts."""

    def __init__(self, script):
        self.config = {"model_id": "scripted"}
        self.script, self.calls = list(script), 0

    def update_config(self, **kw):
        self.config.update(kw)

    def get_config(self):
        return self.config

    async def structured_output(self, *a, **k):  # pragma: no cover
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        step = self.script.pop(0) if self.script else "done"
        say, calls = (step, []) if isinstance(step, str) else (step.get("say"), step["calls"]) if isinstance(step, dict) else (None, step)
        yield {"messageStart": {"role": "assistant"}}
        if say:
            yield {"contentBlockDelta": {"delta": {"text": say}}}
            yield {"contentBlockStop": {}}
        for n, (name, args) in enumerate(calls):
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.calls}-{n}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use" if calls else "end_turn"}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/steps.db")
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()


def _plan(db, *, approved=True):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="approved", approved_by="user:alice",
                   steps=[{"action": "close ssh", "command": STEP_1}, {"action": "tag", "command": STEP_2}],
                   rollback_plan={"steps": [{"action": "reopen ssh", "command": ROLLBACK}]},
                   post_checks=[{"check_id": "pc-1", "command": CHECK, "expected": "no 22"}])
    db.add(plan); db.flush()
    if approved:
        stamp_approval(db, plan)
    db.commit()
    return issue.id, plan.id


def _agent(script, hooks, on_command=None, fail=None):
    ran = []

    @tool
    def run_aws_cli(command: str) -> str:
        """Run a command."""
        ran.append(command)
        if on_command:
            on_command(command)
        if fail and command in fail:
            if fail[command] == "raise":
                raise RuntimeError("boom")
            return fail[command]
        return f"ran {command}"

    @tool
    def describe_vpcs(region: str) -> str:
        """Describe VPCs."""
        return f"2 vpcs in {region}"

    @tool
    def save_rca_result(root_cause: str) -> str:
        """Save."""
        return "saved"

    model = Scripted(script)
    agent = Agent(model=model, tools=[run_aws_cli, describe_vpcs, save_rca_result], hooks=hooks, callback_handler=None,
                  tool_executor=SequentialToolExecutor())
    return agent, model, ran


def _rows(db):
    db.expire_all()
    return db.query(AgentStep).order_by(AgentStep.id).all()


# ── what a step is ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, tool_input, want", [
    ("describe_vpcs", {"region": "us-east-1"}, ("read", None)),                 # named for reading
    ("get_health_issue", {"issue_id": 3}, ("read", None)),
    ("search_similar_cases", {"query": "x"}, ("read", None)),
    ("save_rca_result", {"root_cause": "x"}, ("act", None)),                    # recording a result is something it did
    ("activate_skill", {"name": "linux-admin"}, ("act", None)),
    ("some_tool_nobody_knows", {}, ("act", None)),
    ("run_aws_cli", {"command": READ}, ("read", "readonly")),                   # a command: judged by the command
    ("run_aws_cli_readonly", {"command": STEP_1}, ("act", "write")),            # … whatever the tool is called
    ("run_on_host", {"instance_id": "i-1", "command": "df -h && rm -rf /tmp/x"}, ("act", "unknown")),
])
def test_a_step_is_a_fact_the_code_fetched_or_something_the_agent_did(name, tool_input, want):
    assert step_look(name, tool_input) == want


def test_every_command_of_a_plan_has_its_place(db):
    _, plan_id = _plan(db)
    assert plan_refs(db.get(FixPlan, plan_id)) == {STEP_1: "step:1", STEP_2: "step:2", ROLLBACK: "rollback:1", CHECK: "post:1"}


# ── recording ────────────────────────────────────────────────────────────────

def test_a_tool_call_is_on_record_while_it_runs_and_closed_when_it_ends(db):
    seen = []

    def during(command):
        [row] = _rows(db)
        seen.append((row.kind, row.tool_name, row.summary, row.outcome, row.ended_at))

    recorder = StepRecorder("rca", "I7")
    agent, _, ran = _agent([[("run_aws_cli", {"command": READ})], "the instance is stopped"], [recorder], on_command=during)
    agent("go")
    assert ran == [READ]
    assert seen == [("tool", "run_aws_cli", READ, None, None)]                  # on record before its result exists
    step, said = _rows(db)
    assert (step.run_key, step.agent, step.item, step.execution_id) == (recorder.run_key, "rca", "I7", None)
    assert (step.look, step.tier, step.plan_ref, step.outcome, step.preview) == ("read", "readonly", None, "ok", f"ran {READ}")
    assert step.started_at is not None and step.ended_at is not None and step.ended_at >= step.started_at
    assert (said.kind, said.summary, said.tool_name) == ("say", "the instance is stopped", None)


def test_what_the_model_says_before_it_acts_comes_before_the_act(db):
    agent, _, _ = _agent([{"say": "I will look at the VPCs first.", "calls": [("describe_vpcs", {"region": "us-east-1"})]}, "done"],
                         [StepRecorder("rca", "I7")])
    agent("go")
    assert [(r.kind, r.summary) for r in _rows(db)] == [
        ("say", "I will look at the VPCs first."), ("tool", "us-east-1"), ("say", "done")]


def test_a_tool_that_fails_is_recorded_as_an_error(db):
    agent, _, _ = _agent([[("run_aws_cli", {"command": "one"})], [("run_aws_cli", {"command": "two"})], "done"],
                         [StepRecorder("sre", "I7")], fail={"one": "raise", "two": "Error: AccessDenied when calling X"})
    agent("go")
    one, two = [r for r in _rows(db) if r.kind == "tool"]
    assert one.outcome == "error" and two.outcome == "error" and two.preview.startswith("Error: AccessDenied")
    assert one.ended_at is not None


def test_a_call_a_hook_refused_is_recorded_as_refused_and_did_not_run(db):
    _, plan_id = _plan(db)
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket, why

    def stopped_during(command):
        if command == STEP_1:
            request_stop(ticket, by="user:alice")

    agent, _, ran = _agent([[("run_aws_cli", {"command": STEP_1}), ("run_aws_cli", {"command": STEP_2})],
                            [("run_aws_cli", {"command": ROLLBACK})], "rolled back"],
                           [RunGuard(ticket), StepRecorder("executor", "I1", execution_id=ticket, plan_id=plan_id)],
                           on_command=stopped_during)
    agent("go")
    assert ran == [STEP_1, ROLLBACK]
    steps = [r for r in _rows(db) if r.kind == "tool"]
    assert [(r.plan_ref, r.outcome) for r in steps] == [("step:1", "ok"), ("step:2", "refused"), ("rollback:1", "ok")]
    assert "stopped this run" in steps[1].preview and steps[1].ended_at is not None
    assert {r.execution_id for r in steps} == {ticket}


def test_an_executor_command_that_is_not_in_its_plan_is_marked(db):
    _, plan_id = _plan(db)
    other = "aws ec2 terminate-instances --instance-ids i-9"
    agent, _, _ = _agent([[("run_aws_cli", {"command": READ}), ("run_aws_cli", {"command": other}),
                           ("run_aws_cli", {"command": "  aws ec2   create-tags --resources sg-1 --tags Key=reviewed,Value=yes "}),
                           ("run_aws_cli", {"command": CHECK})], "done"],
                         [StepRecorder("executor", "I1", plan_id=plan_id)])
    agent("go")
    assert [r.plan_ref for r in _rows(db) if r.kind == "tool"] == [None, "off", "step:2", "post:1"]


def test_a_run_without_a_plan_marks_nothing(db):
    agent, _, _ = _agent([[("run_aws_cli", {"command": STEP_1})], "done"], [StepRecorder("rca", "I7")])
    agent("go")
    assert [r.plan_ref for r in _rows(db) if r.kind == "tool"] == [None]


def test_secrets_do_not_reach_the_record(db):
    agent, _, _ = _agent([[("run_aws_cli", {"command": "mysql --password hunter2 -e 'select 1'"})],
                          "the token is Bearer abcdefghijklmnop"], [StepRecorder("rca", "I7")],
                         fail={"mysql --password hunter2 -e 'select 1'": "connected with password=hunter2"})
    agent("go")
    text = " ".join(f"{r.summary} {r.preview or ''}" for r in _rows(db))
    assert "hunter2" not in text and "abcdefghijklmnop" not in text


def test_a_long_speech_is_cut(db):
    agent, _, _ = _agent(["x" * 1000], [StepRecorder("rca", "I7")])
    agent("go")
    [said] = _rows(db)
    assert len(said.summary) == 300 and said.summary.endswith("…")


def test_a_recorder_that_cannot_write_never_stops_the_run(db):
    agent, model, ran = _agent([[("run_aws_cli", {"command": "one"})], "done"], [StepRecorder("rca", "I7")])
    with patch("agenticops.models.get_db_session", side_effect=RuntimeError("database is locked")):
        result = agent("go")
    assert ran == ["one"] and "done" in str(result)


def test_two_runs_keep_their_steps_apart(db):
    a, b = StepRecorder("rca", "I7"), StepRecorder("rca", "I7")
    _agent([[("describe_vpcs", {"region": "a"})], "done"], [a])[0]("go")
    _agent([[("describe_vpcs", {"region": "b"})], "done"], [b])[0]("go")
    assert a.run_key != b.run_key
    assert {r.run_key for r in _rows(db)} == {a.run_key, b.run_key}


# ── which run's steps a page gets ────────────────────────────────────────────

def _step(db, run_key, *, agent="rca", item="I7", at, execution_id=None, summary="s", ended=True, kind="tool"):
    row = AgentStep(run_key=run_key, agent=agent, item=item, execution_id=execution_id, kind=kind, tool_name="describe_vpcs",
                    look="read", summary=summary, started_at=at, ended_at=at if ended else None, outcome="ok" if ended else None)
    db.add(row); db.commit()
    return row.id


T0 = datetime(2026, 11, 18, 3, 0, 0, tzinfo=timezone.utc)


def test_the_steps_of_the_newest_run_of_an_agent_on_an_item(db):
    from agenticops.services.agent_steps import run_steps
    _step(db, "old", at=T0, summary="old-1")
    a = _step(db, "new", at=T0 + timedelta(minutes=30), summary="new-1")
    b = _step(db, "new", at=T0 + timedelta(minutes=31), summary="new-2", ended=False)
    _step(db, "other-agent", agent="sre", at=T0 + timedelta(minutes=40))
    _step(db, "other-item", item="I8", at=T0 + timedelta(minutes=41))
    got = run_steps("I7", "rca")
    assert got["run"] == {"key": "new", "agent": "rca", "item": "I7", "execution_id": None,
                          "started_at": (T0 + timedelta(minutes=30)).isoformat()}
    assert [(s["id"], s["summary"], s["outcome"], s["ended_at"] is None) for s in got["steps"]] == [
        (a, "new-1", "ok", False), (b, "new-2", None, True)]
    assert got["more"] is False
    assert set(got["steps"][0]) == {"id", "kind", "tool", "look", "tier", "plan_ref", "summary", "preview", "outcome", "by",
                                    "started_at", "ended_at", "delivered_at"}


def test_only_what_came_after_the_step_the_page_already_has(db):
    from agenticops.services.agent_steps import run_steps
    ids = [_step(db, "r", at=T0 + timedelta(seconds=n), summary=f"s{n}") for n in range(5)]
    assert [s["id"] for s in run_steps("I7", "rca", after=ids[2])["steps"]] == ids[3:]
    cut = run_steps("I7", "rca", limit=2)
    assert [s["id"] for s in cut["steps"]] == ids[:2] and cut["more"] is True


def test_a_run_that_began_before_the_lane_did_is_not_this_lanes_run(db):
    """The page asks for the run in flight since `since`: the steps of an older run must not be shown as its steps."""
    from agenticops.services.agent_steps import run_steps
    _step(db, "old", at=T0)
    assert run_steps("I7", "rca", since=T0 + timedelta(minutes=5)) == {"run": None, "steps": [], "more": False}
    _step(db, "now", at=T0 + timedelta(minutes=6))
    assert run_steps("I7", "rca", since=T0 + timedelta(minutes=5))["run"]["key"] == "now"


def test_the_run_that_left_a_result_is_the_newest_one_that_began_before_it(db):
    from agenticops.services.agent_steps import run_steps
    _step(db, "first", at=T0)
    _step(db, "second", at=T0 + timedelta(hours=2))
    assert run_steps("I7", "rca", before=T0 + timedelta(hours=1))["run"]["key"] == "first"
    assert run_steps("I7", "rca", before=T0 - timedelta(hours=1))["run"] is None


def test_an_execution_is_asked_for_by_its_record(db):
    from agenticops.services.agent_steps import run_steps
    _step(db, "x41", agent="executor", item="I7", execution_id=41, at=T0)
    _step(db, "x42", agent="executor", item="I7", execution_id=42, at=T0 + timedelta(hours=1))
    assert run_steps("I7", "executor", execution_id=41)["run"]["key"] == "x41"
    assert run_steps("I7", "executor", execution_id=99)["run"] is None
    assert run_steps("I8", "executor", execution_id=41)["run"] is None           # the record belongs to another item


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from agenticops.web.app import app
    return TestClient(app)


def test_the_route_serves_any_signed_in_user_and_refuses_what_it_cannot_read(db, client):
    from types import SimpleNamespace
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    a = _step(db, "r", at=T0, summary="one")
    _step(db, "r", at=T0 + timedelta(seconds=5), summary="two")
    assert client.get("/api/ui/activity/steps?item=I7&agent=rca").status_code == 401          # not signed in
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=4)        # any account, a read-only one too
    try:
        body = client.get("/api/ui/activity/steps?item=I7&agent=rca").json()
        assert body["run"]["key"] == "r" and [s["summary"] for s in body["steps"]] == ["one", "two"]
        assert [s["summary"] for s in client.get(f"/api/ui/activity/steps?item=I7&agent=rca&after={a}").json()["steps"]] == ["two"]
        assert client.get("/api/ui/activity/steps?item=I7&agent=rca&since=2026-11-18T04:00:00Z").json()["run"] is None
        for bad in ("item=X7&agent=rca", "item=I0&agent=rca", "item=I7&agent=main", "item=I7", "agent=rca",
                    "item=I7&agent=rca&since=yesterday", "item=I7&agent=rca&limit=0"):
            assert client.get(f"/api/ui/activity/steps?{bad}").status_code == 422, bad
    finally:
        app.dependency_overrides.clear()


# ── kept for a while, then gone ──────────────────────────────────────────────

def test_old_steps_are_pruned_once_a_day(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.services import agent_steps
    monkeypatch.setattr(settings, "agent_steps_retention_days", 30)
    monkeypatch.setattr(agent_steps, "_last_prune", None)
    now = datetime(2026, 12, 20, tzinfo=timezone.utc)
    _step(db, "old", at=now - timedelta(days=31)); keep = _step(db, "new", at=now - timedelta(days=29))
    assert agent_steps.maybe_prune_daily(now=now) == 1
    assert [r.id for r in _rows(db)] == [keep]
    _step(db, "old2", at=now - timedelta(days=40))
    assert agent_steps.maybe_prune_daily(now=now) == 0                           # once a day
    assert agent_steps.maybe_prune_daily(now=now + timedelta(days=1)) == 1


def test_a_retention_of_zero_keeps_everything(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.services import agent_steps
    monkeypatch.setattr(settings, "agent_steps_retention_days", 0)
    monkeypatch.setattr(agent_steps, "_last_prune", None)
    _step(db, "old", at=T0 - timedelta(days=4000))
    assert agent_steps.maybe_prune_daily(now=T0) == 0 and len(_rows(db)) == 1


# ── the three agents carry a recorder ────────────────────────────────────────

def test_the_diagnosis_agent_records_its_steps_under_its_issue(db):
    from unittest.mock import MagicMock
    ra = "agenticops.agents.rca_agent"
    with patch(f"{ra}.Agent") as agent_cls, patch(f"{ra}.BedrockModel"), \
         patch("agenticops.config.get_agent_model_config", return_value=("m", 16384)), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch(f"{ra}.resolve_rca_effort", return_value=(0, None)), \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="done"), \
         patch("agenticops.services.agent_log_service.track_agent"), \
         patch("agenticops.services.rca_quality.run_post_rca_pipeline"), \
         patch("agenticops.models.get_db_session", side_effect=RuntimeError("no db here")):
        agent_cls.return_value.messages = []
        from agenticops.agents.rca_agent import rca_agent
        assert rca_agent(issue_id=7) == "done"
    [recorder] = [h for h in agent_cls.call_args.kwargs["hooks"] if isinstance(h, StepRecorder)]
    assert (recorder.agent, recorder.item, recorder.execution_id, recorder.plan_id) == ("rca", "I7", None, None)


def _added_recorders(fake_agent):
    return [c.args[0] for c in fake_agent.hooks.add_hook.call_args_list if isinstance(c.args[0], StepRecorder)]


def test_the_plan_agent_records_its_steps_under_its_issue():
    from unittest.mock import MagicMock
    from agenticops.agents import sre_agent as mod
    fake = MagicMock()
    with patch.object(mod, "_create_sre_agent", return_value=fake), patch.object(mod, "rejection_feedback", return_value=""), \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="plan saved"), \
         patch("agenticops.services.agent_log_service.track_agent"), \
         patch("agenticops.services.pipeline_events.plan_written_since", return_value=True), \
         patch("agenticops.models.get_db_session", side_effect=RuntimeError("no db here")):
        assert mod.sre_agent(issue_id=7) == "plan saved"
    [recorder] = _added_recorders(fake)
    assert (recorder.agent, recorder.item) == ("sre", "I7")


def test_a_change_review_records_its_steps_under_its_change():
    from unittest.mock import MagicMock
    from agenticops.agents import sre_agent as mod
    fake = MagicMock()
    with patch.object(mod, "_create_sre_agent", return_value=fake), \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="verdict delivered"), \
         patch("agenticops.services.change_service.get_change", return_value={"id": 5, "account_id": None}), \
         patch("agenticops.services.agent_log_service.log_agent_call"):
        assert mod.sre_agent_review_change(5) == "verdict delivered"
    [recorder] = _added_recorders(fake)
    assert (recorder.agent, recorder.item) == ("sre", "C5")


def test_the_executor_records_its_steps_under_its_run_record_after_the_guard(db, monkeypatch):
    """The guard comes first: the recorder must see that a call was refused."""
    from unittest.mock import MagicMock
    from agenticops.agents.executor_agent import executor_agent
    from agenticops.config import settings
    from agenticops.models import FixExecution
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    monkeypatch.setattr(settings, "executor_enabled", True)
    issue_id, plan_id = _plan(db)
    ea = "agenticops.agents.executor_agent"
    token = set_run_context(RunContext(actor="agent:auto-pipeline", agent_name="executor", fix_plan_id=plan_id))
    try:
        with patch(f"{ea}.Agent") as agent_cls, patch(f"{ea}.BedrockModel"), \
             patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
             patch(f"{ea}.get_cli_tool_for_issue", return_value=None), \
             patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
             patch("agenticops.agents.preamble.invoke_with_retry", return_value="no result"), \
             patch("agenticops.services.agent_log_service.track_agent"), \
             patch("agenticops.services.notification_service.notify_execution_result"), \
             patch("agenticops.services.notification_service.notify_im_origin"):
            executor_agent(fix_plan_id=plan_id)
    finally:
        reset_run_context(token)
    ticket = db.query(FixExecution.id).filter_by(fix_plan_id=plan_id).scalar()
    guard, recorder = agent_cls.call_args.kwargs["hooks"]
    assert isinstance(guard, RunGuard) and isinstance(recorder, StepRecorder)
    assert (recorder.agent, recorder.item, recorder.execution_id, recorder.plan_id) == ("executor", f"I{issue_id}", ticket, plan_id)


def test_a_new_run_lets_the_old_steps_go_and_is_not_stopped_when_that_fails(db):
    with patch("agenticops.services.agent_steps.maybe_prune_daily") as prune:
        StepRecorder("rca", "I7")
    prune.assert_called_once_with()
    with patch("agenticops.services.agent_steps.maybe_prune_daily", side_effect=RuntimeError("database is locked")):
        assert StepRecorder("rca", "I7").run_key


def test_the_result_of_a_kubectl_command_that_reads_secrets_is_not_kept(db):
    """The record is readable by every signed-in account, a read-only one too — and a read-only account's own
    kubectl is refused exactly these reads (skills/execution._reveals_secret_material)."""
    @tool
    def run_kubectl(cluster_name: str, command: str) -> str:
        """kubectl."""
        return "apiVersion: v1\ndata:\n  tls.key: LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLQ==\n"

    script = [[("run_kubectl", {"cluster_name": "c1", "command": "get secret tls-cert -o yaml"})],
              [("run_kubectl", {"cluster_name": "c1", "command": "get pods -n web"})], "done"]
    Agent(model=Scripted(script), tools=[run_kubectl], hooks=[StepRecorder("rca", "I7")], callback_handler=None,
          tool_executor=SequentialToolExecutor())("go")
    secret, pods = [r for r in _rows(db) if r.kind == "tool"]
    assert "LS0tLS1" not in (secret.preview or "") and "not kept" in secret.preview and secret.outcome == "ok"
    assert secret.summary == "get secret tls-cert -o yaml"                 # what was asked stays on record
    assert "LS0tLS1" in pods.preview                                        # any other read keeps the start of its result
