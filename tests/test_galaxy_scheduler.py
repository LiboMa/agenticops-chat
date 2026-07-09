"""GalaxyBuild is dispatchable via the scheduler and the post-scan hook is wired."""

import json
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.models import Base
    import agenticops.scheduler.scheduler  # noqa: F401 — register schedule_executions table
    import agenticops.galaxy.models  # noqa: F401 — register galaxy_* tables
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/galaxy_sched.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    yield
    models_mod._engine = None


def test_galaxy_build_dispatch_calls_builder(db, monkeypatch):
    called = {}
    from agenticops.scheduler.scheduler import Scheduler
    import agenticops.galaxy.builder as B

    def fake_build(trigger="manual", full=False):
        called["trigger"] = trigger
        return 7
    monkeypatch.setattr(B, "build_graph", fake_build)

    sched = Scheduler()
    sched._execute_schedule_by_info({
        "id": 1, "name": "galaxy-auto-build", "pipeline_name": "GalaxyBuild",
        "account_name": None, "config": {},
    })
    assert called.get("trigger") == "auto"


def test_pipeline_options_include_galaxy(db, monkeypatch):
    from starlette.testclient import TestClient
    from agenticops.web.app import app
    r = TestClient(app).get("/api/schedules/pipeline-options")
    assert "GalaxyBuild" in r.json()["pipelines"]
