"""Run Context — who is acting, on what, under which trace (MVP-2.6.0).

A single ContextVar carrying the actor and the plan/change/trace identifiers for the
current request, chat turn, CLI turn, IM message, or executor run. Entry points SET it
(web deps, chat handler, CLI, IM gateways, ExecutorService worker, pipeline threads);
tools and services only READ it (get_run_context()).

Thread rule: ContextVars do NOT cross threading.Thread boundaries — every new thread
must call set_run_context() itself (the same discipline as trace_id today). Strands runs
sync tools inside copy_context(), so reads inside tools work; writes inside tools are
invisible outside — never rely on them.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Iterator, Optional


@dataclass(frozen=True)
class RunContext:
    actor: str = "system"                     # actor key: user:<email> | web:anonymous | cli:<os user> | agent:<name> | im:<platform>:<id> | webhook:<source>
    actor_user_id: Optional[int] = None
    actor_permissions: tuple[str, ...] = ()   # the user's rbac flags (user actors); () for every other kind
    on_behalf_of: Optional[str] = None        # e.g. executor runs on behalf of the approver
    trace_id: Optional[str] = None
    agent_name: Optional[str] = None
    fix_plan_id: Optional[int] = None
    change_request_id: Optional[int] = None
    chat_session_id: Optional[str] = None
    execution_id: Optional[int] = None        # the queued FixExecution an ExecutorService run is closing
    bound_account_id: Optional[int] = None     # a change run/review may touch ONLY this account id (resolver fails closed on any other)
    read_only: bool = False                    # a viewer's turn: every CLI tool refuses non-readonly commands (auth/viewer)
    via_api_key: bool = False                  # the request / chat turn came through an API key (no human decisions)
    # Facts the code knows and the model does not (2.7.0 E2E observations 4 / 5): what its save tool records
    model_id: Optional[str] = None             # the model rca_agent built its agent with → RCAResult.model_id
    run_started_at: Optional[datetime] = None  # when executor_agent began this run → the run's measured duration_ms
    # The claim this thread holds on an issue (services/agent_runs, MVP-2.9.0 N11): rca_agent / sre_agent use it as
    # it is instead of claiming the issue a second time — and refuse when someone else's run is on the issue
    agent_run: Optional[Any] = None
    # What a reporter run's tools read (services/report_coverage, MVP-2.9.0 N21): begun by reporter_agent, written by
    # the tools while they run, stored on the report by save_report. None outside a reporter run.
    coverage: Optional[Any] = None


_run_context_var: contextvars.ContextVar[RunContext] = contextvars.ContextVar(
    "agenticops_run_context", default=RunContext()
)


def get_run_context() -> RunContext:
    return _run_context_var.get()


def set_run_context(ctx: RunContext) -> contextvars.Token:
    return _run_context_var.set(ctx)


def reset_run_context(token: contextvars.Token) -> None:
    _run_context_var.reset(token)


def update_run_context(**fields) -> contextvars.Token:
    """Copy the current context with `fields` replaced; returns the reset token."""
    return _run_context_var.set(replace(_run_context_var.get(), **fields))


@contextmanager
def run_context(**fields) -> Iterator[RunContext]:
    token = update_run_context(**fields)
    try:
        yield _run_context_var.get()
    finally:
        _run_context_var.reset(token)
