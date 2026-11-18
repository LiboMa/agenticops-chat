"""An agent run's steps, on record while it works (MVP-2.9.0 N10).

Until N10 the pages could only say «an agent is on it»: what a diagnosis looked at, or which command an execution
was on, was known only once the run ended — and for a diagnosis or a plan, never. StepRecorder is a Strands hook
on the rca, sre and executor agents. It writes one `agent_steps` row when a tool call starts and closes it when
the call ends, and one row for what the model says between calls:

- kind `tool`: the tool, a one-line summary of its input and the first 200 characters of its result — both through
  chat/tool_steps (the display redaction) —, when it started and ended, and how: ok | error | refused (a hook, e.g.
  agents/run_guard, cancelled it: the tool did not run);
- `look` says what the row is: `read` = a fact the code fetched (a tool that only reads, or a command whose tier is
  read-only), `act` = something the agent did (everything else — recording a result, changing something);
- an executor's command is matched, word for word (whitespace collapsed), to its plan: `step:3`, `rollback:1`,
  `pre:1`, `post:2` — and `off` for a command that is not read-only and is none of them. `off` is a fact about the
  text of the command (the executor types its commands itself), shown to the person who accepts the run;
- kind `say`: the model's own words — its inference, not a fact.

Display only: nothing decides on these rows. Every write is fail-soft — a recorder that cannot write must never be
what stops a run.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry, MessageAddedEvent

logger = logging.getLogger(__name__)

SAY_MAX = 300
NOT_KEPT = "[not kept: the command reads secret material]"
READ_PREFIXES = ("get_", "describe_", "list_", "lookup_", "query_", "search_", "find_", "detect_", "analyze_",
                 "check_", "map_", "read_", "retrieve_")


def step_look(tool_name: str, tool_input) -> tuple[str, Optional[str]]:
    """(look, tier) of one tool call. A call that carries a `command` is judged by the command (the tier the plan
    pages show beside a step: services/change_steps.command_tier); any other by its name: the tools that only read
    are named for it, everything else counts as an act."""
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and command.strip():
        from agenticops.services.change_steps import command_tier
        tier = command_tier(command)
        return ("read" if tier == "readonly" else "act"), tier
    return ("read" if (tool_name or "").startswith(READ_PREFIXES) else "act"), None


def keeps_result(tool_name: str, tool_input) -> bool:
    """Whether the start of a call's result goes on record. The record is readable by every signed-in account, a
    read-only one too, and a read-only account's own kubectl is refused the reads that reveal secret material
    (skills/execution._reveals_secret_material: a Secret, a raw kubeconfig) — so those results are not kept here."""
    if tool_name != "run_kubectl" or not isinstance(tool_input, dict):
        return True
    from agenticops.skills.execution import _reveals_secret_material
    return not _reveals_secret_material(str(tool_input.get("command") or ""))


def plan_refs(plan) -> dict[str, str]:
    """Every command a plan carries → where it stands in the plan: its steps, its rollback, its pre- and post-checks.
    A command that appears twice keeps its first place (a step before a rollback step)."""
    from agenticops.services.change_steps import _command, plan_steps, rollback_steps
    from agenticops.services.verification import declared_checks
    out: dict[str, str] = {}

    def add(part: str, steps) -> None:
        for n, step in enumerate(steps or [], 1):
            command = _command(step)
            if command:
                out.setdefault(command, f"{part}:{n}")

    add("step", plan_steps(plan.steps))
    add("rollback", rollback_steps(plan.rollback_plan))
    add("pre", plan_steps(plan.pre_checks))
    add("post", declared_checks(plan.post_checks))
    return out


def _text_of(content) -> str:
    """The text of a tool result's or a message's content blocks."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


class StepRecorder(HookProvider):
    """One instance per agent run. `item` = the work item the run belongs to ("I12" / "C3")."""

    def __init__(self, agent: str, item: str, *, execution_id: Optional[int] = None, plan_id: Optional[int] = None):
        self.agent, self.item = agent, item
        self.execution_id, self.plan_id = execution_id, plan_id
        self.run_key = uuid.uuid4().hex
        self._refs: Optional[dict[str, str]] = None
        try:                                    # a new run is when old steps are let go (once per process-day)
            from agenticops.services.agent_steps import maybe_prune_daily
            maybe_prune_daily()
        except Exception:
            logger.debug("step recorder: prune skipped", exc_info=True)

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(MessageAddedEvent, self._said)
        registry.add_callback(BeforeToolCallEvent, self._started)
        registry.add_callback(AfterToolCallEvent, self._ended)

    # -- what goes on a row -------------------------------------------------------------------------------------

    def _plan_ref(self, tool_input, tier: Optional[str]) -> Optional[str]:
        """Where an executor's command stands in its plan; None for a run without a plan or a call without a command."""
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if self.plan_id is None or not isinstance(command, str) or not command.strip():
            return None
        if self._refs is None:
            from agenticops.models import FixPlan, get_db_session
            with get_db_session() as session:
                plan = session.get(FixPlan, self.plan_id)
                self._refs = plan_refs(plan) if plan is not None else {}
        ref = self._refs.get(" ".join(command.split()))
        return ref or (None if tier == "readonly" else "off")

    def _add(self, **fields) -> None:
        from agenticops.models import AgentStep, get_db_session
        with get_db_session() as session:
            session.add(AgentStep(run_key=self.run_key, agent=self.agent, item=self.item,
                                  execution_id=self.execution_id, started_at=datetime.now(timezone.utc), **fields))

    # -- the hooks ----------------------------------------------------------------------------------------------

    def _said(self, event: MessageAddedEvent) -> None:
        try:
            message = event.message or {}
            if message.get("role") != "assistant":
                return
            from agenticops.chat.tool_steps import redact_for_display
            text = " ".join(_text_of(message.get("content")).split())
            if text:
                cut = text if len(text) <= SAY_MAX else text[: SAY_MAX - 1] + "…"
                now = datetime.now(timezone.utc)
                self._add(kind="say", summary=redact_for_display(cut), ended_at=now, outcome="ok")
        except Exception:
            logger.debug("step recorder: could not record what the model said (%s %s)", self.agent, self.item, exc_info=True)

    def _started(self, event: BeforeToolCallEvent) -> None:
        try:
            from agenticops.chat.tool_steps import result_preview, summarize_input
            use = event.tool_use or {}
            name, tool_input = use.get("name") or "", use.get("input")
            look, tier = step_look(name, tool_input)
            refused = getattr(event, "cancel_tool", None)          # a hook before this one cancelled it: it will not run
            closed = {"ended_at": datetime.now(timezone.utc), "outcome": "refused",
                      "preview": result_preview(refused if isinstance(refused, str) else "")} if refused else {}
            self._add(kind="tool", tool_name=name[:128], call_id=str(use.get("toolUseId") or "")[:128] or None,
                      look=look, tier=tier, plan_ref=self._plan_ref(tool_input, tier),
                      summary=summarize_input(tool_input), **closed)
        except Exception:
            logger.debug("step recorder: could not record a step's start (%s %s)", self.agent, self.item, exc_info=True)

    def _ended(self, event: AfterToolCallEvent) -> None:
        try:
            from sqlalchemy import update
            from agenticops.chat.tool_steps import result_preview
            from agenticops.models import AgentStep, get_db_session
            use = event.tool_use or {}
            call_id = str(use.get("toolUseId") or "")[:128]
            if not call_id:
                return
            result = event.result or {}
            text = _text_of(result.get("content"))
            failed = (getattr(event, "exception", None) is not None or result.get("status") == "error"
                      or text.lstrip().startswith("Error:"))
            kept = keeps_result(use.get("name") or "", use.get("input"))
            with get_db_session() as session:
                session.execute(
                    update(AgentStep)
                    .where(AgentStep.run_key == self.run_key, AgentStep.call_id == call_id, AgentStep.ended_at.is_(None))
                    .values(ended_at=datetime.now(timezone.utc), outcome="error" if failed else "ok",
                            preview=result_preview(text) if kept else NOT_KEPT))
        except Exception:
            logger.debug("step recorder: could not record a step's end (%s %s)", self.agent, self.item, exc_info=True)
