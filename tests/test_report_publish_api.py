"""Publishing a report (MVP-2.7.0 S6): it sends exactly the chosen version and language — every language asked for
must be ready — and an Idempotency-Key makes a repeat return the first result without sending again."""
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ContentRendering, Report, get_session

ADMIN = Actor("user", "admin@example.com", 3, ("read", "write", "admin"))
KEY = "publish-key-0123456789"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    import agenticops.notify.im_config as im_config
    import agenticops.notify.notifier as notifier
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/pub.db")
    Base.metadata.create_all(models_mod.get_engine())
    monkeypatch.setattr(im_config, "get_channel", lambda name: SimpleNamespace(
        name=name, channel_type="sns-report", config={"topic_arn": "arn:aws:sns:us-east-1:1:t"}))
    sent = []

    async def _send(self, **kw):
        sent.append(kw)
        return {"formats": ["html"], "urls": {"html": "https://x/y"}, "message_id": f"m{len(sent)}"}
    monkeypatch.setattr(notifier.SNSReportNotifier, "send_report", _send)
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    yield TestClient(app), sent
    app.dependency_overrides.pop(deps.current_actor, None)


def _report(zh_ready=False):
    s = get_session()
    try:
        r = Report(report_type="daily", title="Daily", summary="s", content_markdown="# Daily\n\nall fine")
        s.add(r); s.flush()
        if zh_ready:
            s.add(ContentRendering(entity_type="report", entity_id=r.id, source_version=1, language="zh",
                                   source_hash=r.content_hash, status="ready", body_markdown="# 日报\n\n一切正常"))
        s.commit()
        return r.id
    finally:
        s.close()


def _publish(client, rid, body=None, key=KEY):
    headers = {"Idempotency-Key": key} if key is not None else {}
    return client.post(f"/api/reports/{rid}/publish",
                       json=body or {"channel_name": "ops-reports", "formats": ["html"], "version": 1, "language": "en"},
                       headers=headers)


def test_publish_needs_an_idempotency_key(env):
    client, sent = env
    rid = _report()
    assert _publish(client, rid, key=None).status_code == 422
    assert _publish(client, rid, key="short").status_code == 422
    assert sent == []


def test_publish_needs_a_version_and_language(env):
    client, _ = env
    rid = _report()
    assert _publish(client, rid, body={"channel_name": "ops-reports", "formats": ["html"]}).status_code == 422


def test_publish_sends_the_pinned_language(env):
    client, sent = env
    rid = _report()
    r = _publish(client, rid, body={"channel_name": "ops-reports", "formats": ["html"], "version": 1, "language": "zh"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "rendering_not_ready" and sent == []
    r = _publish(client, rid)
    assert r.status_code == 200 and r.json()["sns_message_id"] == "m1"
    assert sent[0]["content_markdown"] == "# Daily\n\nall fine" and "v1 · en" in sent[0]["title"]


def test_publish_zh_en_sends_both(env):
    client, sent = env
    rid = _report(zh_ready=True)
    _publish(client, rid, body={"channel_name": "ops-reports", "formats": ["html"], "version": 1, "language": "zh-en"})
    body = sent[0]["content_markdown"]
    assert body.index("日报") < body.index("---") < body.index("Daily")


def test_the_same_key_publishes_once(env):
    client, sent = env
    rid = _report()
    a, b = _publish(client, rid), _publish(client, rid)
    assert len(sent) == 1 and a.json() == b.json()


def test_a_new_key_publishes_again(env):
    client, sent = env
    rid = _report()
    _publish(client, rid)
    _publish(client, rid, key="another-key-0123456789")
    assert len(sent) == 2


def test_wrong_version_is_404(env):
    client, sent = env
    rid = _report()
    r = _publish(client, rid, body={"channel_name": "ops-reports", "formats": ["html"], "version": 2, "language": "en"})
    assert r.status_code == 404 and sent == []


def test_a_concurrent_repeat_of_a_key_in_flight_is_refused(env):
    import agenticops.web.app as webapp
    client, sent = env
    rid = _report()
    webapp._publishing_keys.add((rid, KEY))
    try:
        r = _publish(client, rid)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "publish_in_flight" and sent == []
    finally:
        webapp._publishing_keys.discard((rid, KEY))
