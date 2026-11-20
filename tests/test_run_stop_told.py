"""A person's stop reaches the agent even when nothing it does next is refused (MVP-2.9.0 N27, the real run).

Found in the first real run inside the lab cluster, 2026-11-20. The plan restored two workloads that had been scaled
to zero; its rollback — which may never bring the outage back — was «keep both at their baseline», so the rollback's
lines were, word for word, the plan's own remaining steps. A person held «stop» in Live after the first step. The
guard lets a line of the plan's rollback through after a stop, and it told the agent of the stop only in the
sentence of a REFUSED call: nothing was refused, the agent never learned that anyone had stopped it, ran the rest of
the plan and recorded «succeeded». The page had said «it stops after the command in progress».

Now the guard says it at the agent's next model call when no refusal has said it yet — once.
"""
import copy
from unittest.mock import patch

import pytest
from strands import Agent, tool
from strands.tools.executors import SequentialToolExecutor

from agenticops.agents.run_guard import NOTHING_APPLIED, STOPPED, RunGuard
from agenticops.models import Base, CloudAccount, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services.plan_content import stamp_approval
from agenticops.services.run_tickets import close_ticket, open_ticket, request_stop
from tests.test_run_guard import Scripted

STEP_1 = "kubectl scale deployment/backend --replicas=2 -n shop"
STEP_2 = "kubectl scale deployment/frontend --replicas=3 -n shop"
CHECK = "kubectl get deploy -n shop"
TOLD = STOPPED.split("{")[0]                 # «A person stopped this run (»
NOTHING = "nothing to roll back"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/told.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]))
    s.commit()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _no_side_effects():
    with patch("agenticops.services.notification_service.notify_execution_result"), \
         patch("agenticops.services.notification_service.notify_im_origin"), \
         patch("agenticops.services.resolution_service.trigger_post_resolution"):
        yield


def _run(db):
    """An approved plan whose rollback repeats its steps (a restore: the state before it is the outage) → ticket."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s",
                   status="approved", approved_by="user:alice",
                   steps=[{"action": "backend back", "command": STEP_1}, {"action": "frontend back", "command": STEP_2}],
                   rollback_plan={"steps": [{"action": "keep frontend at its baseline", "command": STEP_2},
                                            {"action": "keep backend at its baseline", "command": STEP_1}]})
    db.add(plan); db.flush()
    stamp_approval(db, plan); db.commit()
    ticket, why = open_ticket(plan.id, executed_by="agent:auto-pipeline")
    assert ticket, why
    return ticket


class Recording(Scripted):
    """The scripted model, keeping what each model call was sent."""

    def __init__(self, script):
        super().__init__(script)
        self.sent = []

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.sent.append(copy.deepcopy(messages))
        async for chunk in super().stream(messages, tool_specs, system_prompt, **kwargs):
            yield chunk


def _texts(messages) -> list[str]:
    """Every text a request holds: plain blocks and the text of tool results."""
    out = []
    for m in messages:
        for b in m.get("content") or []:
            if "text" in b:
                out.append(b["text"])
            for c in (b.get("toolResult") or {}).get("content") or []:
                if "text" in c:
                    out.append(c["text"])
    return out


def _said(messages, sentence=TOLD) -> int:
    return sum(sentence in t for t in _texts(messages))


def _agent(ticket, model, on_command):
    @tool
    def run_kubectl(command: str) -> str:
        """Run a command."""
        on_command(command)
        return "ok"
    guard = RunGuard(ticket)
    return guard, Agent(model=model, tools=[run_kubectl], hooks=[guard], callback_handler=None,
                        tool_executor=SequentialToolExecutor())


def _cmd(*commands):
    return [("run_kubectl", {"command": c}) for c in commands]


# ── the real run's case ─────────────────────────────────────────────────────

def test_a_stop_is_said_at_the_next_model_call_when_every_call_since_was_let_through(db):
    ticket = _run(db)
    ran = []

    def on_command(command):
        ran.append(command)
        if command == STEP_1:
            assert request_stop(ticket, by="user:alice", note="not now")

    model = Recording([_cmd(STEP_1),           # the first step: the stop lands while it runs
                       _cmd(STEP_2),           # the next step — word for word a line of this plan's rollback: let through
                       "recorded"])
    guard, agent = _agent(ticket, model, on_command)
    agent("go")
    assert ran == [STEP_1, STEP_2]                         # nothing was refused, as before
    assert _said(model.sent[0]) == 0                        # before the stop: nothing to say
    assert _said(model.sent[1]) == 1                        # the model's next call is told
    told = next(t for t in _texts(model.sent[1]) if TOLD in t)
    assert told == STOPPED.format(by="user:alice")         # it changed something: roll back by the plan's own steps, then record
    assert "user:alice" in told and "rollback" in told and "save_execution_result" in told and NOTHING not in told
    assert _said(model.sent[2]) == 1                        # … once: the same sentence is still in the history, not a second one
    assert _said(agent.messages) == 1


def test_it_is_put_after_the_tool_results_of_the_call_it_arrives_on(db):
    ticket = _run(db)
    model = Recording([_cmd(STEP_1), "ok"])
    guard, agent = _agent(ticket, model, lambda c: request_stop(ticket, by="user:alice", note=""))
    agent("go")
    last = model.sent[1][-1]
    assert last["role"] == "user"
    assert "toolResult" in last["content"][0]              # the step's own result first …
    assert TOLD in last["content"][-1]["text"]             # … then the notice


def test_a_run_stopped_before_it_changed_anything_is_told_there_is_nothing_to_roll_back(db):
    ticket = _run(db)
    ran = []

    def on_command(command):
        ran.append(command)
        if len(ran) == 1:
            assert request_stop(ticket, by="user:alice", note="")

    model = Recording([_cmd(CHECK),            # a pre-check: the stop lands here
                       _cmd(CHECK),            # it only looks again — let through, so no refusal would ever tell it
                       "stopped before the first change"])
    guard, agent = _agent(ticket, model, on_command)
    agent("go")
    assert ran == [CHECK, CHECK]
    assert _said(model.sent[1], NOTHING) == 1
    told = next(t for t in _texts(model.sent[1]) if NOTHING in t)
    assert told == NOTHING_APPLIED.format(by="user:alice")
    assert _said(agent.messages, NOTHING) == 1


def test_a_refused_call_has_said_it_already(db):
    ticket = _run(db)
    ran = []

    def on_command(command):
        ran.append(command)
        if command == STEP_1:
            assert request_stop(ticket, by="user:alice", note="")

    model = Recording([_cmd(STEP_1),
                       _cmd("kubectl delete deployment/frontend -n shop"),     # not the plan's rollback: refused, and told why
                       _cmd(STEP_2),
                       "rolled back"])
    guard, agent = _agent(ticket, model, on_command)
    agent("go")
    assert ran == [STEP_1, STEP_2]
    # call 2 was told by the notice; the refusal of its own command says the same sentence; nothing is added after that
    assert _said(model.sent[1]) == 1
    assert _said(model.sent[2]) == 2
    assert _said(model.sent[3]) == 2
    assert _said(agent.messages) == 2


def test_when_the_refusal_comes_first_the_notice_is_not_added(db):
    ticket = _run(db)
    ran = []

    def on_command(command):
        ran.append(command)
        if command == STEP_1:
            assert request_stop(ticket, by="user:alice", note="")

    # both calls in ONE model turn: the second is refused before any model call could carry a notice
    model = Recording([_cmd(STEP_1, "kubectl delete deployment/frontend -n shop"), "rolled back"])
    guard, agent = _agent(ticket, model, on_command)
    agent("go")
    assert ran == [STEP_1]
    assert _said(model.sent[1]) == 1                        # the refusal's sentence only
    assert _said(agent.messages) == 1


def test_a_run_nobody_stopped_is_told_nothing(db):
    ticket = _run(db)
    model = Recording([_cmd(STEP_1), _cmd(STEP_2), "done"])
    guard, agent = _agent(ticket, model, lambda c: None)
    agent("go")
    assert all(_said(sent) == 0 for sent in model.sent)


def test_a_run_closed_from_outside_is_ended_not_told(db):
    ticket = _run(db)

    def on_command(command):
        request_stop(ticket, by="user:alice", note="")
        close_ticket(ticket, "aborted", "cancelled by user:alice")

    model = Recording([_cmd(STEP_1), "never reached"])
    guard, agent = _agent(ticket, model, on_command)
    agent("go")
    assert model.calls == 1                                 # the next model call is cancelled
    assert _said(agent.messages) == 0


# ── the callback by itself ───────────────────────────────────────────────────

class _Event:
    def __init__(self, messages):
        self.agent = type("A", (), {"messages": messages})()
        self.cancel = None


def test_with_no_user_message_to_carry_it_the_next_call_has_it(db):
    ticket = _run(db)
    guard = RunGuard(ticket)
    guard.applied = 1
    assert request_stop(ticket, by="user:alice", note="")
    assistant_last = [{"role": "user", "content": [{"text": "go"}]}, {"role": "assistant", "content": [{"text": "…"}]}]
    guard._before_model(_Event(assistant_last))
    assert _said(assistant_last) == 0
    ready = [{"role": "user", "content": [{"text": "go"}]}]
    guard._before_model(_Event(ready))
    assert _said(ready) == 1
    guard._before_model(_Event(ready))
    assert _said(ready) == 1                                # once


def test_a_run_that_recorded_its_result_is_not_told(db):
    ticket = _run(db)
    guard = RunGuard(ticket)
    guard.applied = 1
    guard.recorded = True
    assert request_stop(ticket, by="user:alice", note="")
    messages = [{"role": "user", "content": [{"text": "go"}]}]
    guard._before_model(_Event(messages))
    assert _said(messages) == 0
