# tests/test_pipeline_events_change.py
import pytest

from agenticops.models import Base, ChangeRequest, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/pe.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def test_log_event_for_change_request(db):
    from agenticops.services.pipeline_events import get_timeline, log_event
    cr = ChangeRequest(title="t", description="d", requested_by="cli:x", trace_id="TRC-cr01")
    db.add(cr); db.commit()
    log_event(None, "change_requested", "intake", detail={"source": "cli"}, actor="cli:x", change_request_id=cr.id)
    rows = db.query(PipelineEvent).all()
    assert len(rows) == 1 and rows[0].change_request_id == cr.id and rows[0].health_issue_id is None
    assert rows[0].trace_id == "TRC-cr01"  # resolved from the ChangeRequest
    tl = get_timeline(change_request_id=cr.id)
    assert tl[0]["event_type"] == "change_requested" and tl[0]["change_request_id"] == cr.id


def test_log_event_without_any_id_is_dropped(db):
    from agenticops.services.pipeline_events import log_event
    log_event(None, "orphan", "x")
    assert db.query(PipelineEvent).count() == 0


def test_subscribers_not_called_for_change_events(db):
    from agenticops.services import pipeline_events as pe
    calls = []
    pe.subscribe(lambda *a: calls.append(a))
    try:
        pe.log_event(None, "change_requested", "intake", change_request_id=1)
        import time; time.sleep(0.05)
        assert calls == []
        pe.log_event(1, "issue_created", "detection")
        time.sleep(0.05)
        assert len(calls) == 1
    finally:
        pe._subscribers.clear()


def test_issue_timeline_unchanged(db):
    from agenticops.services.pipeline_events import get_timeline, log_event
    log_event(42, "rca_started", "rca", trace_id="TRC-x")
    assert get_timeline(42)[0]["event_type"] == "rca_started"
