# tests/test_run_context.py
import contextvars
import threading

from agenticops.run_context import (
    RunContext, get_run_context, reset_run_context, run_context, set_run_context, update_run_context,
)


def test_default_is_system_actor():
    ctx = get_run_context()
    assert ctx.actor == "system" and ctx.fix_plan_id is None


def test_set_and_reset():
    token = set_run_context(RunContext(actor="cli:malibo", trace_id="TRC-1"))
    assert get_run_context().actor == "cli:malibo"
    reset_run_context(token)
    assert get_run_context().actor == "system"


def test_update_copies_other_fields():
    with run_context(actor="user:admin", trace_id="TRC-2"):
        tok = update_run_context(fix_plan_id=7)
        ctx = get_run_context()
        assert (ctx.actor, ctx.trace_id, ctx.fix_plan_id) == ("user:admin", "TRC-2", 7)
        reset_run_context(tok)
        assert get_run_context().fix_plan_id is None
    assert get_run_context().actor == "system"


def test_context_manager_resets_on_exception():
    try:
        with run_context(actor="agent:executor"):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    assert get_run_context().actor == "system"


def test_copy_context_propagates_reads_like_strands_tools():
    with run_context(actor="user:admin", change_request_id=3):
        seen = contextvars.copy_context().run(lambda: get_run_context().change_request_id)
    assert seen == 3


def test_new_thread_does_not_inherit():
    seen = {}
    with run_context(actor="user:admin"):
        t = threading.Thread(target=lambda: seen.setdefault("actor", get_run_context().actor))
        t.start(); t.join()
    assert seen["actor"] == "system"


def test_frozen():
    import dataclasses
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        get_run_context().actor = "x"  # type: ignore[misc]


def test_actor_permissions_default_and_roundtrip():
    assert get_run_context().actor_permissions == ()
    with run_context(actor="user:alice", actor_user_id=3):
        tok = update_run_context(actor_permissions=("read", "write"))
        assert get_run_context().actor_permissions == ("read", "write")
        reset_run_context(tok)
        assert get_run_context().actor_permissions == ()
