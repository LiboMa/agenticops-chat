"""A private report never reaches another user by a side door (MVP-2.7.0 S6 review): global search, /send_to (a
#R ref or a 'Report #N' in the text), and the agent tools list_reports / distribute_report, which act as the chat
turn's user."""
import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, Report, get_session
from agenticops.run_context import RunContext, reset_run_context, set_run_context

ALICE = Actor("user", "alice@example.com", 1, ("read", "write"))
BOB = Actor("user", "bob@example.com", 2, ("read", "write"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/priv.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    r = Report(report_type="conversation", title="Alice SECRET chat", summary="SECRET summary",
               content_markdown="SECRET body", owner_user_id=1, visibility="private")
    s.add(r); s.commit(); rid = r.id; s.close()
    who = {"actor": ALICE}
    app.dependency_overrides[deps.current_actor] = lambda: who["actor"]
    client = TestClient(app)

    def as_(actor):
        who["actor"] = actor
        return client
    yield SimpleNamespace(as_=as_, rid=rid)
    app.dependency_overrides.pop(deps.current_actor, None)


def _as_turn(actor):
    return set_run_context(RunContext(actor=actor.key, actor_user_id=actor.user_id, actor_permissions=actor.permissions))


def test_search_hides_a_private_report(env):
    found = lambda c: [r["id"] for r in c.get("/api/search?q=SECRET&types=reports").json()["results"].get("reports", [])]
    assert env.rid not in found(env.as_(BOB))
    assert env.rid in found(env.as_(ALICE))


def test_send_to_refuses_a_private_report_ref(env):
    from agenticops.chat.send_to import resolve_content
    assert "SECRET" not in resolve_content(f"#R{env.rid}", actor=BOB)[1]
    assert "SECRET" in resolve_content(f"#R{env.rid}", actor=ALICE)[1]


def test_send_to_rich_distribution_refuses_a_private_report(env, monkeypatch):
    import agenticops.chat.send_to as st
    import agenticops.notify.notifier as notifier
    sent = []
    monkeypatch.setattr(st, "resolve_target", lambda name: ("channel", {}))
    monkeypatch.setattr("agenticops.notify.im_config.get_channel", lambda n: SimpleNamespace(
        name=n, channel_type="sns-report", config={"topic_arn": "arn:aws:sns:us-east-1:1:t"}, is_enabled=True))

    async def _send(self, **kw):
        sent.append(kw)
        return {"formats": [], "urls": {}, "message_id": "m"}
    monkeypatch.setattr(notifier.SNSReportNotifier, "send_report", _send)
    result = st.execute_send_to(f'/send_to ops "Report #{env.rid}"', actor=BOB)
    assert sent == [] and not result.success


def test_the_list_reports_tool_hides_it_from_another_users_turn(env):
    from agenticops.tools.report_tools import list_reports
    fn = getattr(list_reports, "_tool_func", None) or list_reports
    t = _as_turn(BOB)
    try:
        assert "SECRET" not in fn()
    finally:
        reset_run_context(t)
    t = _as_turn(ALICE)
    try:
        assert "SECRET" in fn()
    finally:
        reset_run_context(t)


def test_the_distribute_report_tool_refuses_it_for_another_user(env):
    from agenticops.tools.notification_tools import distribute_report
    fn = getattr(distribute_report, "_tool_func", None) or distribute_report
    t = _as_turn(BOB)
    try:
        out = json.loads(fn(report_id=str(env.rid)))
    finally:
        reset_run_context(t)
    assert out["success"] is False and "not found" in out["message"]
