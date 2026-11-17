"""The executor stops when its run's record is closed (MVP-2.9.0 N8).

A cancel (POST /api/fix-executions/{id}/cancel), the total-time watchdog and the reconcile close the run's
record — but the agent is a thread inside a model loop, and until N8 nothing told it: it went on calling its
tools, and a write command that no plan-context rule refuses still ran after «cancelled».

RunGuard is a Strands hook on the executor's agent. Before every tool call it reads the record
(services/run_tickets.ticket_state — the database, so a record closed by another thread or another process
counts): once it is no longer `running` the call is cancelled, and so is the next model call, which ends the loop.
A record that cannot be read lets the call through and is logged: the guard exists to stop a closed run, and
must never be what stops a healthy one.
"""

import logging
from typing import Optional

from strands.hooks import BeforeModelCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)

CLOSED = ("This run was closed ({status}): it was cancelled or timed out. Nothing further may run and no result "
          "can be recorded. Stop here.")


def guard_decision(state: Optional[dict]) -> Optional[str]:
    """Why the run's next step must not happen, or None when it may. `state` is run_tickets.ticket_state()'s
    answer: None (no such record — nothing to guard) and a `running` record let it through."""
    if not state or state.get("status") == "running":
        return None
    return CLOSED.format(status=state.get("status"))


class RunGuard(HookProvider):
    def __init__(self, execution_id: int):
        self.execution_id = execution_id

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(BeforeModelCallEvent, self._before_model)

    def _refusal(self) -> Optional[str]:
        try:
            from agenticops.services.run_tickets import ticket_state
            return guard_decision(ticket_state(self.execution_id))
        except Exception:
            logger.warning("run guard could not read Execution #%s; letting the step through", self.execution_id,
                           exc_info=True)
            return None

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        refusal = self._refusal()
        if refusal:
            event.cancel_tool = refusal

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        refusal = self._refusal()
        if refusal:
            event.cancel = refusal
