"""Report renderings (MVP-2.7.0 S6): the source language is the source itself; another language is translated by
the cheap model in the background with every protected value checked (fails closed); a GET never calls a model;
a changed source makes a rendering stale; each new report queues its other language."""
import threading

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ContentRendering, Report, get_session

ADMIN = Actor("user", "admin@example.com", 3, ("read", "write", "admin"))
F = "`" * 3
SRC = (f"# Daily report\n\nnginx on i-0abc123 hit 97% CPU for 15 minutes (I#12, E-301).\n\n"
       f"{F}bash\nsudo systemctl restart nginx\n{F}\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.services import content_rendering as cr
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/cr.db")
    Base.metadata.create_all(models_mod.get_engine())
    calls = {"n": 0, "reply": None, "raise": None}

    def _model(prompt, model_id, max_tokens):
        calls["n"] += 1
        if calls["raise"]:
            raise calls["raise"]
        masked = prompt.split("\n\n", 1)[1]
        return calls["reply"](masked) if calls["reply"] else masked.replace("Daily report", "日报").replace(
            "hit", "达到").replace("CPU for", "CPU，持续").replace("minutes", "分钟")
    monkeypatch.setattr(cr, "_call_model", _model)

    class _Inline:                       # run the background worker inline
        def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
            self._t, self._a, self._k = target, args, kwargs or {}
        def start(self):
            self._t(*self._a, **self._k)
    monkeypatch.setattr(cr.threading, "Thread", _Inline)
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    yield TestClient(app), calls, cr
    app.dependency_overrides.pop(deps.current_actor, None)


def _report(body=SRC):
    s = get_session()
    try:
        r = Report(report_type="daily", title="daily", summary="s", content_markdown=body)
        s.add(r); s.commit()
        return r.id
    finally:
        s.close()


def _get(client, rid, lang, version=1):
    return client.get(f"/api/content/report/{rid}/rendering?version={version}&language={lang}")


def test_source_language_is_ready_without_a_model(env):
    client, calls, _ = env
    rid = _report()
    body = _get(client, rid, "en").json()
    assert body["status"] == "ready" and body["body_markdown"] == SRC and body["language"] == "en"
    assert body["entity"] == {"entity_type": "report", "entity_id": rid} and body["source_version"] == 1
    assert calls["n"] == 0


def test_get_rendering_never_calls_the_model(env):
    client, calls, _ = env
    rid = _report()
    assert _get(client, rid, "zh").json()["status"] == "missing"
    assert calls["n"] == 0


def test_translation_round_trip(env):
    from agenticops.services.content_protect import protect, protected_hash
    client, calls, cr = env
    rid = _report()
    cr.translate_now(rid, 1, "zh")
    body = _get(client, rid, "zh").json()
    assert body["status"] == "ready" and "日报" in body["body_markdown"]
    for v in protect(SRC)[1]:
        assert v in body["body_markdown"]
    assert body["protected_value_hash"] == protected_hash(SRC)


def test_tampered_translation_fails_closed(env):
    client, calls, cr = env
    rid = _report()
    calls["reply"] = lambda masked: masked.replace("⟦P0⟧", "", 1)
    cr.translate_now(rid, 1, "zh")
    body = _get(client, rid, "zh").json()
    assert (body["status"], body["error_code"], body["body_markdown"]) == ("failed", "protected_values_changed", None)


def test_model_error_is_failed(env):
    client, calls, cr = env
    rid = _report()
    calls["raise"] = RuntimeError("throttled")
    cr.translate_now(rid, 1, "zh")
    assert _get(client, rid, "zh").json()["error_code"] == "model_failed"


def test_a_changed_source_marks_the_rendering_stale(env):
    client, _, cr = env
    rid = _report()
    cr.translate_now(rid, 1, "zh")
    s = get_session(); s.get(Report, rid).content_markdown = SRC + "\nmore"; s.commit(); s.close()
    assert _get(client, rid, "zh").json()["status"] == "stale"


def test_post_translations_queues_and_dedups(env):
    client, calls, _ = env
    rid = _report()
    r = client.post(f"/api/content/report/{rid}/translations", json={"source_version": 1, "languages": ["zh"]})
    assert r.status_code == 202 and calls["n"] == 1
    r = client.post(f"/api/content/report/{rid}/translations", json={"source_version": 1, "languages": ["zh", "en"]})
    assert r.status_code == 202 and calls["n"] == 1
    assert {x["language"]: x["status"] for x in r.json()} == {"zh": "ready", "en": "ready"}


def test_a_failed_translation_can_be_retried(env):
    client, calls, cr = env
    rid = _report()
    calls["raise"] = RuntimeError("x")
    cr.translate_now(rid, 1, "zh")
    calls["raise"] = None
    client.post(f"/api/content/report/{rid}/translations", json={"source_version": 1, "languages": ["zh"]})
    assert _get(client, rid, "zh").json()["status"] == "ready"


@pytest.mark.parametrize("qs,code", [("version=2&language=zh", 404), ("version=1&language=fr", 422)])
def test_bad_queries(env, qs, code):
    client, _, _ = env
    rid = _report()
    assert client.get(f"/api/content/report/{rid}/rendering?{qs}").status_code == code


def test_translation_request_shape(env):
    client, _, _ = env
    rid = _report()
    assert client.post(f"/api/content/report/{rid}/translations", json={"source_version": 1, "languages": ["zh"], "x": 1}).status_code == 422
    assert client.post(f"/api/content/report/{rid}/translations", json={"source_version": 1, "languages": []}).status_code == 422
    assert client.post(f"/api/content/report/{rid}/translations", json={"source_version": 2, "languages": ["zh"]}).status_code == 404


def test_startup_marks_pending_failed(env):
    _, _, cr = env
    rid = _report()
    s = get_session()
    s.add(ContentRendering(entity_type="report", entity_id=rid, source_version=1, language="zh", source_hash="x",
                           status="pending"))
    s.commit(); s.close()
    assert cr.interrupt_pending() == 1
    s = get_session()
    row = s.query(ContentRendering).one()
    s.close()
    assert (row.status, row.error_code) == ("failed", "interrupted")


def test_enqueue_other_language_picks_the_language_it_is_not_in(env):
    client, calls, cr = env
    rid = _report()
    cr.enqueue_other_language(rid)
    assert _get(client, rid, "zh").json()["status"] == "ready"


def test_saving_a_report_queues_its_other_language(env, monkeypatch, tmp_path):
    from agenticops.config import settings
    _, _, cr = env
    # never the owner's real S3 bucket (settings.yaml names one): local storage in tmp only
    monkeypatch.setattr(settings, "report_s3_bucket", "")
    monkeypatch.setattr(settings, "report_storage", "local")
    monkeypatch.setattr(settings, "reports_dir", tmp_path)
    import agenticops.storage.backend as backend_mod
    import agenticops.services.notification_service as ns
    monkeypatch.setattr(backend_mod, "_backend", None, raising=False)
    monkeypatch.setattr(ns, "notify_report_saved", lambda *a, **k: None)   # never the owner's real channels
    seen = []
    monkeypatch.setattr(cr, "enqueue_other_language", lambda rid: seen.append(rid))
    from agenticops.tools.report_tools import save_report
    fn = getattr(save_report, "_tool_func", None) or save_report
    out = fn(report_type="daily", title="t", content_markdown="all fine", summary="s")
    assert seen and f"#{seen[0]}" in out
