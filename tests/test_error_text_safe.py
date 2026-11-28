"""A provider's error never carries its key out (MVP-2.9.0 review, Spec ②).

An OpenAI / Anthropic SDK error's text is the provider's own sentence, and an authentication failure quotes part of
the key it was given («Incorrect API key provided: sk-…»). N35 made two sinks keep only the class and the HTTP status
(`llm/errors.safe_error_text`); these are the rest: the agent-call record (`track_agent` → `/api/agent-logs`), every
specialist agent's error answer (it reaches Main, the chat and the database), and the logs — one filter on the
service's handlers turns an SDK exception's traceback and arguments into class + status."""
import ast
import io
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

KEY = "sk-SECRETKEY1234567890abcdef"
AGENTS = Path(__file__).resolve().parents[1] / "src" / "agenticops" / "agents"


def _auth_error():
    import httpx
    import openai
    req = httpx.Request("POST", "http://provider.invalid/v1/chat/completions")
    message = f"Incorrect API key provided: {KEY}"
    resp = httpx.Response(401, request=req, json={"error": {"message": message}})
    return openai.AuthenticationError(message, response=resp, body={"error": {"message": message}})


def test_the_agent_call_record_keeps_class_and_status_only(monkeypatch):
    from agenticops.services import agent_log_service as m
    seen = {}
    monkeypatch.setattr(m, "log_agent_call", lambda **kw: seen.update(kw))
    with pytest.raises(Exception):
        with m.track_agent("detect", "detect_health_issues", "scope=all", model_id="p::m"):
            raise _auth_error()
    assert seen["error"] == "AuthenticationError (401)" and KEY not in seen["error"]


def test_no_agent_formats_a_caught_exception_itself():
    """In agents/, a caught exception reaches text only through safe_error_text (its answer goes to the model, the
    chat and the database)."""
    found = []
    for path in sorted(AGENTS.glob("*.py")):
        source = path.read_text()
        for handler in ast.walk(ast.parse(source)):
            if not (isinstance(handler, ast.ExceptHandler) and handler.name):
                continue
            for node in ast.walk(handler):
                if isinstance(node, ast.JoinedStr) and any(
                        isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) and v.value.id == handler.name
                        for v in node.values):
                    found.append(f"{path.name}:{node.lineno} {ast.get_source_segment(source, node)}")
    assert not found, "format the exception with safe_error_text(e):\n" + "\n".join(found)


def test_an_agents_error_answer_names_the_error_not_the_key():
    import importlib
    mod = importlib.import_module("agenticops.agents.detect_agent")    # the package re-exports the tool by name
    with patch("agenticops.scanner.engine._load_accounts", return_value=[]), \
         patch("agenticops.llm.factory.build_model", side_effect=_auth_error()), \
         patch("agenticops.services.agent_log_service.log_agent_call"):
        answer = mod.detect_agent(scope="all")
    assert "AuthenticationError (401)" in answer and KEY not in answer


def test_the_log_filter_keeps_no_key():
    from agenticops.llm.errors import SdkErrorFilter
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(SdkErrorFilter())
    log = logging.getLogger("agenticops.test_error_text_safe")
    log.addHandler(handler)
    log.propagate = False
    try:
        try:
            raise _auth_error()
        except Exception as e:
            log.exception("Chat stream error for session %s", "s1")
            log.warning("provider call failed: %s", e)
        try:
            raise RuntimeError("an ordinary failure")
        except RuntimeError:
            log.exception("something else")
    finally:
        log.removeHandler(handler)
    out = stream.getvalue()
    assert KEY not in out
    assert out.count("AuthenticationError (401)") == 2
    assert "Traceback" in out and "an ordinary failure" in out      # other errors keep their traceback


def test_a_traceback_that_holds_an_sdk_error_further_down_is_cut_too():
    """A traceback prints the error it was raised from: a wrapper around an SDK error still carries the key."""
    from agenticops.llm.errors import SdkErrorFilter
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SdkErrorFilter())
    log = logging.getLogger("agenticops.test_error_text_safe.chain")
    log.addHandler(handler)
    log.propagate = False
    try:
        try:
            try:
                raise _auth_error()
            except Exception as inner:
                raise RuntimeError("the agent turn failed") from inner
        except RuntimeError:
            log.exception("Chat stream error")
    finally:
        log.removeHandler(handler)
    out = stream.getvalue()
    assert KEY not in out and "AuthenticationError (401)" in out


def test_the_service_logs_carry_the_filter(tmp_path, monkeypatch):
    from agenticops.config import settings
    from agenticops.llm.errors import SdkErrorFilter
    import agenticops.web.app as webapp
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))
    monkeypatch.setattr(webapp, "_SERVICE_LOG_HANDLERS", {})
    webapp._setup_service_logging()
    handlers = list(webapp._SERVICE_LOG_HANDLERS.values())
    try:
        assert handlers and all(any(isinstance(f, SdkErrorFilter) for f in h.filters) for h in handlers)
    finally:
        for name in ("agenticops", "uvicorn.error", "uvicorn", "uvicorn.access"):
            for h in handlers:
                logging.getLogger(name).removeHandler(h)
        for h in handlers:
            h.close()
