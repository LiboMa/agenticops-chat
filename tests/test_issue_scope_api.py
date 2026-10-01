"""Issue list scope: ops events vs security findings (MVP-2.6.1 Plan E, spec §3.E.1).

The scope filters on the server: the list is paged (default 50), so filtering a page on the client would leave the
ops view nearly empty whenever security findings dominate the newest rows."""
import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, HealthIssue, get_session


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/scope.db")
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    for source in ("security_poll", "security_posture", "cloudwatch_alarm", "securityXpoll", "vuln_scan"):
        s.add(HealthIssue(resource_id=f"r-{source}", severity="high", source=source, title=source,
                          description="d", status="open"))
    s.commit()
    s.close()
    from agenticops.web.app import app
    return TestClient(app)  # bare — no `with`, so the lifespan never starts


def _sources(resp):
    assert resp.status_code == 200, resp.text
    return sorted(i["anomaly_type"] for i in resp.json())


@pytest.mark.parametrize("path", ["/api/issues", "/api/anomalies"])
def test_security_scope_is_the_security_prefix(client, path):
    assert _sources(client.get(f"{path}?scope=security")) == ["security_poll", "security_posture"]


@pytest.mark.parametrize("path", ["/api/issues", "/api/anomalies"])
def test_ops_scope_is_everything_else(client, path):
    # `_` is a LIKE wildcard: an unescaped pattern would count securityXpoll as security
    assert _sources(client.get(f"{path}?scope=ops")) == ["cloudwatch_alarm", "securityXpoll", "vuln_scan"]


@pytest.mark.parametrize("query", ["", "?scope=all"])
def test_all_scope_is_the_default(client, query):
    assert len(_sources(client.get(f"/api/issues{query}"))) == 5


def test_unknown_scope_is_422(client):
    assert client.get("/api/issues?scope=bogus").status_code == 422
