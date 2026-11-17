"""The executor stops when its run's record is closed, and only rolls back once a person stopped it
(MVP-2.9.0 N8, N9).

A cancel (POST /api/fix-executions/{id}/cancel), the total-time watchdog and the reconcile close the run's
record — but the agent is a thread inside a model loop, and until N8 nothing told it: it went on calling its
tools, and a write command that no plan-context rule refuses still ran after «cancelled».

RunGuard is a Strands hook on the executor's agent. Before every tool call it reads the record
(services/run_tickets.ticket_state — the database, so a record closed or stopped by another thread or another
process counts):

- the record is closed (not `running`): the call is cancelled, and so is the next model call, which ends the loop;
- a person asked it to stop (N9; the record stays `running` so the result can still be recorded): only a read-only
  command, a tool that reads or records, and a command that is — word for word — a step of this plan's rollback
  go through. Everything else is cancelled with a message that tells the agent to roll back and record. The loop
  goes on: it has to, for the rollback to run.

A record that cannot be read lets the call through and is logged: the guard exists to stop a run that was closed or
stopped, and must never be what stops a healthy one.
"""

import logging
from typing import Optional

from strands.hooks import BeforeModelCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)

CLOSED = ("This run was closed ({status}): it was cancelled or timed out. Nothing further may run and no result "
          "can be recorded. Stop here.")
STOPPED = ("A person stopped this run ({by}). Do not run any further step of the plan. Roll back what was already "
           "applied using ONLY this plan's rollback steps, exactly as they are written — any other command is refused; "
           "read-only checks are allowed. Then call save_execution_result with status 'rolled_back' (or 'failed' if "
           "nothing could be rolled back) and say what was and what was not undone.")

# Tools that only read or record: they go through after a stop. Anything else without a `command` to judge
# (activate_skill, assume_role, run_skill_script, a tool a skill registered at run time) does not.
READS_OR_RECORDS = frozenset({
    "get_approved_fix_plan", "save_execution_result", "mark_fix_executed", "mark_fix_failed", "get_health_issue",
    "get_active_account", "query_reachability", "find_network_path", "detect_network_anomalies",
    "read_skill_reference", "search_agent_memory", "retrieve_offloaded_content",
})


def guard_decision(state: Optional[dict], tool_name: Optional[str] = None,
                   tool_input: Optional[dict] = None) -> Optional[str]:
    """Why the run's next step must not happen, or None when it may.

    `state` is run_tickets.ticket_state()'s answer; None (no such record — nothing to guard) lets it through.
    `tool_name` None = the next step is a model call: only a closed record stops that.
    """
    if not state:
        return None
    if state.get("status") != "running":
        return CLOSED.format(status=state.get("status"))
    by = state.get("stopped_by")
    if not by or tool_name is None:
        return None
    if tool_name in READS_OR_RECORDS or tool_name.startswith("describe_"):
        return None
    command = (tool_input or {}).get("command")
    if isinstance(command, str) and command.strip():
        from agenticops.services.change_steps import command_tier
        if " ".join(command.split()) in (state.get("rollback") or ()) or command_tier(command) == "readonly":
            return None
    return STOPPED.format(by=by)


class RunGuard(HookProvider):
    def __init__(self, execution_id: int):
        self.execution_id = execution_id

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(BeforeModelCallEvent, self._before_model)

    def _refusal(self, tool_name: Optional[str] = None, tool_input: Optional[dict] = None) -> Optional[str]:
        try:
            from agenticops.services.run_tickets import ticket_state
            return guard_decision(ticket_state(self.execution_id), tool_name, tool_input)
        except Exception:
            logger.warning("run guard could not read Execution #%s; letting the step through", self.execution_id,
                           exc_info=True)
            return None

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        use = event.tool_use or {}
        refusal = self._refusal(use.get("name") or "", use.get("input") if isinstance(use.get("input"), dict) else {})
        if refusal:
            event.cancel_tool = refusal

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        refusal = self._refusal()
        if refusal:
            event.cancel = refusal
