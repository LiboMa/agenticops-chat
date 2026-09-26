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
from typing import Iterator, Optional


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
