"""Report export (MVP-2.7.0 S6): one version in zh, en or both — html always, pdf / docx when the server can —
as an attachment; a language that is not ready is refused, never replaced by the other; export never publishes."""
import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ContentRendering, Report, get_session

ADMIN = Actor("user", "admin@example.com", 3, ("read", "write", "admin"))
BODY = "# Daily\n\nnginx on i-0abc123 is fine. <script>alert(1)</script>\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/ex.db")
    Base.metadata.create_all(models_mod.get_engine())
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.pop(deps.current_actor, None)


def _report(zh_ready=False):
    s = get_session()
    try:
        r = Report(report_type="daily", title="Daily <b>report</b>", summary="s", content_markdown=BODY)
        s.add(r); s.flush()
        if zh_ready:
            s.add(ContentRendering(entity_type="report", entity_id=r.id, source_version=1, language="zh",
                                   source_hash=r.content_hash, status="ready",
                                   body_markdown="# 日报\n\ni-0abc123 上的 nginx 正常。"))
        s.commit()
        return r.id
    finally:
        s.close()


def _export(client, rid, qs):
    return client.get(f"/api/reports/{rid}/export?{qs}")


def test_export_html_in_the_source_language(client):
    rid = _report()
    r = _export(client, rid, "version=1&language=en")
    assert r.status_code == 200
    assert f'filename="AgenticOps_R{rid}_v1_en.html"' in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith("attachment") and r.headers.get("etag")
    html = r.text
    assert '<html lang="en">' in html and "i-0abc123" in html and "<table" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "<b>report</b>" not in html


def test_export_zh_en_has_both_papers_page_broken(client):
    rid = _report(zh_ready=True)
    html = _export(client, rid, "version=1&language=zh-en").text
    assert html.count('<article class="paper"') == 2
    assert 'lang="zh"' in html and 'lang="en"' in html and "break-before: page" in html
    body = html[html.index("<body>"):]
    assert body.index("日报") < body.index("Daily")
    assert "切换语言不改变" in body and "switching language does not change" in body   # each paper's note in its own language


def test_export_of_a_language_not_ready_is_409(client):
    rid = _report()
    r = _export(client, rid, "version=1&language=zh")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "rendering_not_ready"
    assert _export(client, rid, "version=1&language=zh-en").status_code == 409


def test_unavailable_format_is_422(client, monkeypatch):
    import agenticops.services.report_export as rx
    monkeypatch.setattr(rx, "available_formats", lambda: ["html"])
    rid = _report()
    r = _export(client, rid, "version=1&language=en&format=pdf")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "format_unavailable"


@pytest.mark.parametrize("qs,code", [("version=2&language=en", 404), ("version=1&language=fr", 422),
                                      ("version=1&language=en&format=exe", 422)])
def test_bad_queries(client, qs, code):
    rid = _report()
    assert _export(client, rid, qs).status_code == code


def test_export_never_publishes(client, monkeypatch):
    import agenticops.notify.notifier as notifier
    monkeypatch.setattr(notifier.SNSReportNotifier, "send_report", lambda *a, **k: (_ for _ in ()).throw(AssertionError("published")))
    monkeypatch.setattr(notifier.SESNotifier, "send_report", lambda *a, **k: (_ for _ in ()).throw(AssertionError("published")))
    rid = _report()
    assert _export(client, rid, "version=1&language=en").status_code == 200


def test_bootstrap_says_rendering_and_export():
    from agenticops.web.routers.ui import _features
    f = _features()
    assert f["content_rendering"] is True and f["report_export"] is True


def test_bootstrap_lists_the_export_formats(monkeypatch):
    import agenticops.services.report_export as rx
    from agenticops.web.routers import ui
    monkeypatch.setattr(rx, "available_formats", lambda: ["html", "docx"])
    assert ui._report_export_formats() == ["html", "docx"]
