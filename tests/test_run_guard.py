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


# ── round-2 review ───────────────────────────────────────────────────────────────────────────────────
#
# A-I1: the record is closed by the run's own result too (save_execution_result closes it in place). The guard
# then cancelled the model's next call like any closed record — so after EVERY run that recorded its result the
# executor's last word, the sentence Main answers the person from and the last «recorded step» of the run, was
# «This run was closed (succeeded): it was cancelled or timed out … no result can be recorded».

def _record(ticket, status="succeeded"):
    """What save_execution_result does to the run's own record: a compare-and-set on status='running'."""
    s = get_session()
    try:
        done = s.query(FixExecution).filter_by(id=ticket, status="running").update({"status": status})
        s.commit()
        return f"FixExecution #{ticket} recorded as {status}" if done else "REJECTED: no longer running"
    finally:
        s.close()


def _executor(script, ticket, *, drift=False):
    """An agent with a command tool and stand-ins for the tools that close a run's own record."""
    ran = []

    @tool
    def run_aws_cli(command: str) -> str:
        """Run a command."""
        ran.append(command)
        return f"ran {command}"

    @tool
    def save_execution_result(status: str) -> str:
        """Record the run's result."""
        return _record(ticket, status)

    @tool
    def get_approved_fix_plan(fix_plan_id: int) -> str:
        """Read the approved plan."""
        if drift:
            _record(ticket, "aborted")
            return "REJECTED: I#1 fix plan v2: content changed after approval. The execution was recorded as aborted."
        return "the plan"

    @tool
    def mark_fix_executed(execution_id: int) -> str:
        """Mark the issue."""
        ran.append("mark_fix_executed")
        return "marked"

    model = Scripted(script)
    agent = Agent(model=model, tools=[run_aws_cli, save_execution_result, get_approved_fix_plan, mark_fix_executed],
                  hooks=[RunGuard(ticket)], callback_handler=None, tool_executor=SequentialToolExecutor())
    return agent, model, ran


def test_a_run_that_recorded_its_own_result_keeps_its_last_word(run):
    agent, model, ran = _executor([_cmd("one"), [("save_execution_result", {"status": "succeeded"})],
                                   [("mark_fix_executed", {"execution_id": run})],
                                   "Done: step one was applied and its check passed."], run)
    result = agent("go")
    assert "Done: step one was applied" in str(result)
    assert "cancelled" not in str(result) and "timed out" not in str(result)
    assert ran == ["one", "mark_fix_executed"] and model.calls == 4       # the protocol's last tool call ran too


def test_once_its_result_is_on_record_a_run_runs_nothing_more(run):
    agent, model, ran = _executor([[("save_execution_result", {"status": "failed"})], _cmd("one more thing"),
                                   "I recorded the failure."], run)
    result = agent("go")
    assert ran == []                                                       # the command after the result did not run
    assert "I recorded the failure." in str(result) and model.calls == 3  # … and the agent was told, not cut off
    refusal = [b["toolResult"]["content"][0]["text"] for m in agent.messages for b in m["content"] if "toolResult" in b][-1]
    assert "is over (failed)" in refusal and "cancelled" not in refusal


def test_a_plan_that_changed_after_approval_is_reported_in_the_agents_own_words(run):
    """The drift abort closes the record inside get_approved_fix_plan: the reason must reach the person, not be
    replaced by «it was cancelled or timed out»."""
    agent, model, ran = _executor([[("get_approved_fix_plan", {"fix_plan_id": 1})],
                                   "Not run: the plan changed after it was approved."], run, drift=True)
    result = agent("go")
    assert "the plan changed after it was approved" in str(result) and model.calls == 2


def test_a_record_closed_from_outside_still_ends_the_run_at_once(run):
    """The other way a record closes — a cancel, the timeout — is unchanged: no further model call."""
    agent, model, ran = _executor([_cmd("one"), "never asked"], run)
    close_ticket(run, "aborted", "Cancelled by operator")
    result = agent("go")
    assert ran == [] and model.calls == 0 and "closed (aborted)" in str(result)


# A-M1: «a record that cannot be read lets the step through» is right for a healthy run. But a stop is never
# withdrawn and a closed record never reopens: once the guard has seen one, a failed read must not let a write
# through.

def _reads_fail_after(first_restrictive):
    """ticket_state that answers until it has returned a state for which `first_restrictive` holds, then raises."""
    from agenticops.services import run_tickets
    real, seen = run_tickets.ticket_state, []

    def state(execution_id):
        if seen:
            raise RuntimeError("database is locked")
        answer = real(execution_id)
        if answer and first_restrictive(answer):
            seen.append(True)
        return answer
    return patch("agenticops.services.run_tickets.ticket_state", side_effect=state)


def test_a_stop_the_guard_has_seen_holds_when_the_record_cannot_be_read_any_more(run):
    from agenticops.services.run_tickets import request_stop

    def stopped_during(command):
        if command == "aws ec2 stop-instances --instance-ids i-1":
            assert request_stop(run, by="user:alice")
    agent, model, ran = _agent([_cmd("aws ec2 stop-instances --instance-ids i-1"),
                                _cmd("aws ec2 terminate-instances --instance-ids i-1"),     # refused: the guard reads «stopped»
                                _cmd("aws ec2 delete-volume --volume-id vol-1"),            # the read fails now
                                "done"], run, on_command=stopped_during)
    with _reads_fail_after(lambda s: s.get("stopped_by")):
        agent("go")
    assert ran == ["aws ec2 stop-instances --instance-ids i-1"]


def test_a_close_the_guard_has_seen_holds_when_the_record_cannot_be_read_any_more(run):
    def cancelled_during(command):
        if command == "one":
            assert close_ticket(run, "aborted", "Cancelled by operator")
    agent, model, ran = _agent([_cmd("one", "two"), _cmd("three"), "all done"], run, on_command=cancelled_during)
    with _reads_fail_after(lambda s: s.get("status") != "running"):
        agent("go")
    assert ran == ["one"] and model.calls == 1
