"""An executor whose run record is closed stops (MVP-2.9.0 N8).

Until N8 a cancel only changed the record: the agent's thread went on, and a write command that no plan-context
rule refuses still ran after «cancelled». These tests drive a REAL strands Agent — its loop, its hooks, its
tool executor — with a model that answers from a script and a command tool that only records what it was asked
to run: no Bedrock, no cloud.
"""
import json
from unittest.mock import patch

import pytest
from strands import Agent, tool
from strands.models import Model
from strands.tools.executors import SequentialToolExecutor

from agenticops.agents.run_guard import RunGuard, guard_decision
from agenticops.models import Base, FixExecution, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services.plan_content import stamp_approval
from agenticops.services.run_tickets import close_ticket, open_ticket


class Scripted(Model):
    """Answers each model call with the next entry of `script`: a list of (tool, input) calls, or a final text."""

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
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(step, str):
            yield {"contentBlockDelta": {"delta": {"text": step}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            return
        for n, (name, args) in enumerate(step):
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.calls}-{n}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


@pytest.fixture
def run(tmp_path, monkeypatch):
    """An approved fix plan with its run record open → the execution id."""
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/guard.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    s.add(issue); s.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    s.add(rca); s.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="approved", approved_by="user:alice")
    s.add(plan); s.flush()
    stamp_approval(s, plan); s.commit()
    plan_id = plan.id
    s.close()
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket, why
    return ticket


def _agent(script, execution_id, on_command=None):
    ran = []

    @tool
    def run_aws_cli(command: str) -> str:
        """Run a command."""
        ran.append(command)
        if on_command:
            on_command(command)
        return f"ran {command}"

    model = Scripted(script)
    agent = Agent(model=model, tools=[run_aws_cli], hooks=[RunGuard(execution_id)], callback_handler=None,
                  tool_executor=SequentialToolExecutor())
    return agent, model, ran


def _cmd(*commands):
    return [("run_aws_cli", {"command": c}) for c in commands]


def test_while_the_record_is_running_every_command_runs(run):
    agent, model, ran = _agent([_cmd("one"), _cmd("two", "three"), "all done"], run)
    result = agent("go")
    assert ran == ["one", "two", "three"] and model.calls == 3 and "all done" in str(result)


def test_once_the_record_is_closed_the_next_command_does_not_run_and_the_loop_ends(run):
    """The cancel lands while step one is running: step one finishes, nothing after it starts."""
    def cancelled_during(command):
        if command == "one":
            assert close_ticket(run, "aborted", "Cancelled by operator")
    agent, model, ran = _agent([_cmd("one", "two"), _cmd("three"), "all done"], run, on_command=cancelled_during)
    result = agent("go")
    assert ran == ["one"]                                   # «two» was in the same turn and still did not run
    assert model.calls == 1                                 # … and the model was not asked again
    assert "closed" in str(result) and "aborted" in str(result)


def test_a_record_closed_between_turns_stops_the_run_before_the_model_is_asked_again(run):
    def timed_out_after(command):
        if command == "two":
            assert close_ticket(run, "failed", "Execution timed out after 1800s")
    agent, model, ran = _agent([_cmd("one"), _cmd("two"), _cmd("three"), "all done"], run, on_command=timed_out_after)
    agent("go")
    assert ran == ["one", "two"] and model.calls == 2


def test_a_record_that_cannot_be_read_never_stops_a_healthy_run(run, caplog):
    agent, model, ran = _agent([_cmd("one"), "all done"], run)
    with patch("agenticops.services.run_tickets.ticket_state", side_effect=RuntimeError("database is locked")):
        agent("go")
    assert ran == ["one"] and model.calls == 2
    assert "could not read Execution" in caplog.text


def test_the_decision_itself():
    assert guard_decision(None) is None                                     # no such record: nothing to guard
    assert guard_decision({"status": "running"}) is None
    for status in ("aborted", "failed", "succeeded", "rolled_back", "pending"):
        assert status in guard_decision({"status": status})
