# tests/test_actor_attribution.py
"""Verify actor_type/actor_id wiring at every entry point."""

import inspect

from agenticops.services import agent_log_service


def test_track_agent_accepts_actor_params():
    sig = inspect.signature(agent_log_service.track_agent)
    assert "actor_type" in sig.parameters
    assert "actor_id" in sig.parameters


def test_log_agent_call_accepts_actor_params():
    sig = inspect.signature(agent_log_service.log_agent_call)
    assert "actor_type" in sig.parameters
    assert "actor_id" in sig.parameters


def test_web_sse_passes_user_actor():
    """The chat turn logs the request's actor (user:<email> when signed in, web:anonymous otherwise) — its kind
    and key, never request.state.user (a User object; MVP-2.7.0). Behaviour: test_chat_session_access."""
    import agenticops.web.app as appmod
    src = inspect.getsource(appmod)
    assert "actor_type=actor.kind" in src and "actor_id=actor.key" in src
    assert 'actor_id=getattr(getattr(request, "state", None), "user", None)' not in src


def test_cli_passes_cli_actor():
    import agenticops.cli.main as climod
    src = inspect.getsource(climod)
    assert 'actor_type="cli"' in src
