"""The executor stops when its run's record is closed, and only rolls back once a person stopped it
(MVP-2.9.0 N8, N9).

A cancel (POST /api/fix-executions/{id}/cancel), the total-time watchdog and the reconcile close the run's
record — but the agent is a thread inside a model loop, and until N8 nothing told it: it went on calling its
tools, and a write command that no plan-context rule refuses still ran after «cancelled».

RunGuard is a Strands hook on the executor's agent. Before every tool call it reads the record
(services/run_tickets.ticket_state — the database, so a record closed or stopped by another thread or another
process counts):

- the record was closed FROM OUTSIDE (a cancel, the timeout): the call is cancelled, and so is the next model
  call, which ends the loop;
- the run closed its record ITSELF — it recorded its result (save_execution_result closes the record in place), or
  get_approved_fix_plan found the plan changed after approval and aborted it: nothing more may run, but the agent
  may still read, record (mark_fix_executed) and say what it did. Its last word is what Main answers the person
  from and the last step on the run's record; until the round-2 review it was replaced, after every run that
  recorded a result, by «this run was closed: it was cancelled or timed out»;
- a person asked it to stop (N9; the record stays `running` so the result can still be recorded): only a read-only
  command, a tool that reads or records, and a command that is — word for word — a step of this plan's rollback
  go through. Everything else is cancelled with a message that tells the agent to roll back and record. The loop
  goes on: it has to, for the rollback to run. When this run let no command through that could have changed
  anything, there is nothing to roll back and the rollback is refused too (`kubectl rollout undo` on a
  deployment the run never touched would itself be a change).
  The agent is TOLD of the stop by that refusal — or, when nothing it does next is refused, at its next model
  call (N27). The first real run inside the lab cluster showed why: a plan that restores what was scaled to zero
  has a rollback that repeats its own remaining steps (a rollback may never bring the outage back), every one of
  them is let through, and the agent — never told anyone had stopped it — ran the plan to its end and recorded
  «succeeded».

A command is judged as its tool would run it: run_kubectl takes the subcommand without the word («get pods»), so
it is read — for its tier and against the rollback — as `kubectl get pods` (services/change_steps.tool_command).

A record that cannot be read lets the call through and is logged: the guard exists to stop a run that was closed or
stopped, and must never be what stops a healthy one. But a stop is never withdrawn and a closed record never
reopens — once the guard has seen either, a read that fails afterwards decides from what it saw.
"""

import logging
import weakref
from typing import Optional

from strands.hooks import AfterToolCallEvent, BeforeModelCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)

CLOSED = ("This run was closed ({status}): it was cancelled or timed out. Nothing further may run and no result "
          "can be recorded. Stop here.")
OVER = "This run is over ({status}); nothing further may run. Say what was done and stop."
STOPPED = ("A person stopped this run ({by}). Do not run any further step of the plan. Roll back what was already "
           "applied using ONLY this plan's rollback steps, exactly as they are written — any other command is refused; "
           "read-only checks are allowed. Then call save_execution_result with status 'rolled_back' (or 'failed' if "
           "nothing could be rolled back) and say what was and what was not undone.")
NOTHING_APPLIED = ("A person stopped this run ({by}) before it changed anything, so there is nothing to roll back: do "
                   "not run any step of the plan and do not run its rollback steps. Read-only checks are allowed. Then "
                   "call save_execution_result with status 'aborted' and say that the run was stopped before its first "
                   "change.")

# Tools that only read or record: they go through after a stop. Anything else without a `command` to judge
# (activate_skill, assume_role, run_skill_script, a tool a skill registered at run time) does not.
READS_OR_RECORDS = frozenset({
    "get_approved_fix_plan", "save_execution_result", "mark_fix_executed", "mark_fix_failed", "get_health_issue",
    "get_active_account", "query_reachability", "find_network_path", "detect_network_anomalies",
    "read_skill_reference", "search_agent_memory", "retrieve_offloaded_content",
})
# The two tools through which a run closes its OWN record.
CLOSES_ITS_OWN_RECORD = frozenset({"save_execution_result", "get_approved_fix_plan"})


def is_guard_text(text: str) -> bool:
    """Whether `text` is this guard's own sentence for a run closed from outside — what Strands makes the assistant
    message of the model call the guard cancelled. It is not something the model said (agents/step_recorder)."""
    return (text or "").startswith(CLOSED.split("{")[0])


def _command(tool_name: Optional[str], tool_input: Optional[dict]) -> str:
    """The command a tool call would run, as a plan writes it — "" for a call that carries none."""
    command = (tool_input or {}).get("command")
    if not isinstance(command, str) or not command.strip():
        return ""
    from agenticops.services.change_steps import tool_command
    return tool_command(tool_name or "", command)


def may_change_something(tool_name: Optional[str], tool_input: Optional[dict]) -> bool:
    """Whether a call that was let through could have changed the account, a host or a cluster: it carries a
    command, and the command is not read-only."""
    command = _command(tool_name, tool_input)
    if not command:
        return False
    from agenticops.services.change_steps import command_tier
    return command_tier(command) != "readonly"


def guard_decision(state: Optional[dict], tool_name: Optional[str] = None, tool_input: Optional[dict] = None, *,
                   recorded: bool = False, applied: Optional[int] = None) -> Optional[str]:
    """Why the run's next step must not happen, or None when it may.

    `state` is run_tickets.ticket_state()'s answer; None (no such record — nothing to guard) lets it through.
    `tool_name` None = the next step is a model call: only a record closed from outside stops that.
    `recorded`: the run closed its record itself (its own result, or the drift abort).
    `applied`: how many commands that could have changed something this run was let through; None = not known
    (then a stop lets the rollback through, as it does when something was applied).
    """
    if not state:
        return None
    reads = False
    command = _command(tool_name, tool_input)
    if tool_name is not None:
        reads = tool_name in READS_OR_RECORDS or tool_name.startswith("describe_")
        if not reads and command:
            from agenticops.services.change_steps import command_tier
            reads = command_tier(command) == "readonly"
    if state.get("status") != "running":
        if not recorded:
            return CLOSED.format(status=state.get("status"))
        return None if tool_name is None or reads else OVER.format(status=state.get("status"))
    by = state.get("stopped_by")
    if not by or tool_name is None or reads:
        return None
    if applied == 0:
        return NOTHING_APPLIED.format(by=by)
    if command:
        from agenticops.services.change_steps import exact_text
        rollback = state.get("rollback") or ()
        # the plan's own rollback text — as the tool runs it, or as the call wrote it
        if command in rollback or exact_text((tool_input or {}).get("command") or "") in rollback:
            return None
    return STOPPED.format(by=by)


# The guards of the runs in flight in this process, by the id of the run's record — so that what a run let through
# can be asked of the code that watched it (MVP-2.9.0 N26: save_execution_result), not of the agent's own account.
# Weak: a guard lives as long as its agent, and nothing is kept of a run that is over.
_GUARDS: "weakref.WeakValueDictionary[int, RunGuard]" = weakref.WeakValueDictionary()


def applied_of(execution_id: Optional[int]) -> Optional[int]:
    """How many commands that could have changed something the run with this record was let through — the
    cautious count a stop decides on (anything not provably a read). None = not known: no guard watched such a
    run in this process."""
    guard = _GUARDS.get(execution_id) if execution_id else None
    return None if guard is None else guard.applied


def tried_of(execution_id: Optional[int]) -> Optional[int]:
    """How many of those were not word for word one of the plan's own declared checks — 0 = the run did not try
    the plan (MVP-2.9.0 N27: a failed pre-check that no read list knows is still only a check). None = not known."""
    guard = _GUARDS.get(execution_id) if execution_id else None
    return None if guard is None else guard.tried


class RunGuard(HookProvider):
    def __init__(self, execution_id: int):
        self.execution_id = execution_id
        self.applied = 0                 # commands let through that could have changed something
        self.tried = 0                   # … of which were not the plan's own declared checks (pre / post)
        self._checks: Optional[frozenset] = None     # those checks' commands, read once (approved content)
        _GUARDS[execution_id] = self
        self.recorded = False            # the run closed its own record
        self._seen: Optional[dict] = None        # the last state that was closed or stopped (neither is ever undone)
        self._open: set[str] = set()     # calls let through while the record was running
        self._told = False               # the agent has been told a person stopped this run (a refusal, or the notice)

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)
        registry.add_callback(BeforeModelCallEvent, self._before_model)

    def _state(self) -> Optional[dict]:
        """The record now. When it cannot be read: what was last seen of a closed or stopped record, else None
        (a healthy run is never stopped by a failed read)."""
        try:
            from agenticops.services.run_tickets import ticket_state
            state = ticket_state(self.execution_id)
        except Exception:
            logger.warning("run guard could not read Execution #%s; %s", self.execution_id,
                           "deciding from the stop / close it saw before" if self._seen else "letting the step through",
                           exc_info=True)
            return self._seen
        if state and (state.get("status") != "running" or state.get("stopped_by")):
            self._seen = state
        return state

    def _refusal(self, state: Optional[dict], tool_name: Optional[str] = None,
                 tool_input: Optional[dict] = None) -> Optional[str]:
        try:
            return guard_decision(state, tool_name, tool_input, recorded=self.recorded, applied=self.applied)
        except Exception:                # the decision itself failed: a restrictive state seen before still holds
            logger.warning("run guard could not decide for Execution #%s", self.execution_id, exc_info=True)
            if state and state.get("status") != "running":
                return CLOSED.format(status=state.get("status"))
            if state and state.get("stopped_by") and tool_name is not None:
                return STOPPED.format(by=state.get("stopped_by"))
            return None

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        use = event.tool_use or {}
        name = use.get("name") or ""
        tool_input = use.get("input") if isinstance(use.get("input"), dict) else {}
        state = self._state()
        refusal = self._refusal(state, name, tool_input)
        if refusal:
            event.cancel_tool = refusal
            if state and state.get("status") == "running" and state.get("stopped_by"):
                self._told = True        # the refusal's own sentence says who stopped the run and what may still run
            return
        if state and state.get("status") == "running":
            self._open.add(str(use.get("toolUseId") or ""))
        try:
            if may_change_something(name, tool_input):
                self.applied += 1
                if not self._is_declared_check(name, tool_input):
                    self.tried += 1
        except Exception:
            self.applied += 1            # not known to be a read: it counts
            self.tried += 1

    def _is_declared_check(self, tool_name: str, tool_input: dict) -> bool:
        """Whether the call's command is, word for word, one of this plan's declared pre- or post-checks — as the
        tool runs it, or as the call wrote it. When the plan's checks cannot be read, nothing is one."""
        if self._checks is None:
            try:
                from agenticops.services import run_tickets
                self._checks = run_tickets.check_commands_of(self.execution_id)
            except Exception:
                logger.warning("run guard could not read the checks of Execution #%s; every command counts as a try",
                               self.execution_id, exc_info=True)
                self._checks = frozenset()
        if not self._checks:
            return False
        from agenticops.services.change_steps import exact_text
        return (_command(tool_name, tool_input) in self._checks
                or exact_text((tool_input or {}).get("command") or "") in self._checks)

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        """A record that was running when one of the two closing tools was called and is closed when it returns was
        closed by the run itself."""
        use = event.tool_use or {}
        was_running = str(use.get("toolUseId") or "") in self._open
        self._open.discard(str(use.get("toolUseId") or ""))
        if self.recorded or not was_running or (use.get("name") or "") not in CLOSES_ITS_OWN_RECORD:
            return
        state = self._state()
        if state and state.get("status") != "running":
            self.recorded = True

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        state = self._state()
        refusal = self._refusal(state)
        if refusal:
            event.cancel = refusal
            return
        self._say_stop(event, state)

    def _say_stop(self, event: BeforeModelCallEvent, state: Optional[dict]) -> None:
        """A person stopped the run and no refusal has told the agent yet — every call since was one a stop lets
        through (a look, a record, a line of the rollback that is also a step of the plan): say it on this model
        call, once, after whatever results the call carries. With no user message to put it on, the next call has it."""
        if self._told or self.recorded or not state or state.get("status") != "running" or not state.get("stopped_by"):
            return
        try:
            messages = event.agent.messages
            last = messages[-1] if messages else None
            if not last or last.get("role") != "user" or not isinstance(last.get("content"), list):
                return
            sentence = NOTHING_APPLIED if self.applied == 0 else STOPPED
            last["content"].append({"text": sentence.format(by=state.get("stopped_by"))})
            self._told = True
        except Exception:                # the notice is a courtesy to a run that may go on; the refusals still hold
            logger.warning("run guard could not tell Execution #%s that it was stopped", self.execution_id, exc_info=True)
