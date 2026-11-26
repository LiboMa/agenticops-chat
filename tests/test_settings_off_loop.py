"""PATCH /api/settings does its blocking work off the event loop (review of MVP-2.9.0, Standards 3).

AgenticOps is ONE process: a file write or a database call inside an `async def` handler holds the event loop, and
every chat stream waits meanwhile (CLAUDE.md «ONE process»). The settings handler wrote settings.yaml, the audit
rows and the high-impact switches, and read the switches in force, on the loop itself. Now the async part only
checks; one plain function, run in a worker thread, does the reads and writes."""
import ast
import asyncio
import pathlib
import threading

import httpx
import pytest

from tests.llm_fake_server import llm_db

APP = pathlib.Path(__file__).resolve().parents[1] / "src" / "agenticops" / "web" / "app.py"
BLOCKING = {"save_to_yaml", "get_db_session", "effective", "save", "log"}


def test_the_async_handler_itself_reads_and_writes_nothing():
    tree = ast.parse(APP.read_text())
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_apply_settings")
    calls = []
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            owner = ast.unparse(node.func.value) if isinstance(node.func, ast.Attribute) else ""
            if name in {"save_to_yaml", "get_db_session"} or (name in BLOCKING and owner in {"exec_switches", "AuditService"}):
                calls.append(f"{ast.unparse(node.func)} at line {node.lineno}")
    assert not calls, "run it in the worker: " + ", ".join(calls)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    settings = llm_db(tmp_path, monkeypatch, "off-loop.db")
    for field in ("acp_enhanced_backend", "change_auto_approve_standard", "auto_rca_enabled"):
        monkeypatch.setattr(settings, field, getattr(settings, field))
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    from agenticops.services import model_service
    monkeypatch.setattr(model_service, "_models_cache", (0.0, []))
    monkeypatch.setattr(model_service, "_fetch_bedrock_models", lambda region="us-east-1": [])   # no AWS call
    return settings


def test_a_settings_change_writes_on_a_worker_thread(env, monkeypatch):
    import agenticops.audit.service as audit_mod
    import agenticops.web.app as webapp
    from agenticops.services import exec_switches
    seen: list[tuple[str, int]] = []

    def spy(name, fn):
        def wrapper(*a, **kw):
            seen.append((name, threading.get_ident()))
            return fn(*a, **kw)
        return wrapper
    monkeypatch.setattr("agenticops.config.save_to_yaml", spy("save_to_yaml", lambda updates: None))
    monkeypatch.setattr(webapp, "get_db_session", spy("get_db_session", webapp.get_db_session))
    monkeypatch.setattr(exec_switches, "effective", spy("exec_switches.effective", exec_switches.effective))
    monkeypatch.setattr(audit_mod.AuditService, "log", staticmethod(spy("AuditService.log", audit_mod.AuditService.log)))
    backend = (webapp._acp_available_backends() or ["claude-code"])[0]

    async def go():
        loop_thread = threading.get_ident()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webapp.app), base_url="http://t") as c:
            r = await c.patch("/api/settings", json={"acp_enhanced_backend": backend, "auto_rca_enabled": False,
                                                     "change_auto_approve_standard": True,
                                                     "executor_hitl_enabled": True})
        return loop_thread, r
    loop_thread, r = asyncio.run(go())
    assert r.status_code == 200, r.text
    names = {n for n, _ in seen}
    assert {"save_to_yaml", "get_db_session", "exec_switches.effective", "AuditService.log"} <= names, names
    on_loop = [n for n, t in seen if t == loop_thread]
    assert not on_loop, f"on the event loop: {on_loop}"
