# tests/test_audit_service_actor.py
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from agenticops.models import Base, CommandAudit, get_engine, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/audit.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def test_log_records_actor(db):
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.audit.models import AuditLog
    AuditService.log(Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, "9", actor="user:admin",
                     details={"reason": "ok"}, old_values={"status": "draft"}, new_values={"status": "approved"})
    row = db.query(AuditLog).one()
    assert row.actor == "user:admin" and row.action == "plan.approved" and row.entity_type == "fix_plan"


def test_log_with_caller_session_does_not_commit(db):
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.audit.models import AuditLog
    AuditService.log(Actions.CHANGE_REQUESTED, EntityTypes.CHANGE_REQUEST, "1", actor="cli:x", session=db)
    db.rollback()
    assert db.query(AuditLog).count() == 0  # never committed by the service
    AuditService.log(Actions.CHANGE_REQUESTED, EntityTypes.CHANGE_REQUEST, "1", actor="cli:x", session=db)
    db.commit()
    assert db.query(AuditLog).count() == 1


def test_new_action_constants_exist():
    from agenticops.audit.service import Actions
    for name in ("CHANGE_REQUESTED", "CHANGE_REVIEWED", "CHANGE_CLARIFIED", "CHANGE_APPROVED", "CHANGE_REJECTED",
                 "CHANGE_CANCELLED", "CHANGE_EXECUTION_STARTED", "CHANGE_COMPLETED", "CHANGE_FAILED",
                 "CHANGE_ROLLED_BACK", "CHANGE_NEEDS_REVIEW", "PLAN_APPROVED", "PLAN_REJECTED",
                 "PLAN_EXECUTE_REQUESTED", "AUTHZ_DENIED", "AUTHZ_DENIED_SHADOW"):
        assert getattr(Actions, name).startswith(("change.", "plan.", "authz."))


def test_prune_daily_deletes_old_rows_once_per_day(db):
    from agenticops.audit import service as svc
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    old = datetime.now(timezone.utc) - timedelta(days=400)
    db.add(AuditLog(action="x", entity_type="t", entity_id="1", timestamp=old))
    db.add(AuditLog(action="y", entity_type="t", entity_id="2"))
    db.add(CommandAudit(actor="a", tool="run_aws_cli", tier="write", command="c", outcome="executed", created_at=old))
    db.commit()
    svc._last_prune_date = None
    with patch.object(settings, "audit_retention_days", 365):
        svc.AuditService.maybe_prune_daily()
    db.expire_all()
    assert db.query(AuditLog).count() == 1
    assert db.query(CommandAudit).count() == 0
    # second call same day is a no-op even if new old rows appear
    db.add(AuditLog(action="z", entity_type="t", entity_id="3", timestamp=old)); db.commit()
    svc.AuditService.maybe_prune_daily()
    db.expire_all()
    assert db.query(AuditLog).count() == 2


def test_prune_disabled_when_retention_zero(db):
    from agenticops.audit import service as svc
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    db.add(AuditLog(action="x", entity_type="t", entity_id="1", timestamp=datetime(2000, 1, 1))); db.commit()
    svc._last_prune_date = None
    with patch.object(settings, "audit_retention_days", 0):
        svc.AuditService.maybe_prune_daily()
    assert db.query(AuditLog).count() == 1


def test_prune_failure_warns_and_retries_on_the_next_call(db, caplog):
    """M-14: a failed prune (DB outage) must not burn the day marker — it logs at WARNING and the next call
    prunes; the marker is set only after a successful prune."""
    import logging
    from agenticops.audit import service as svc
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    old = datetime.now(timezone.utc) - timedelta(days=400)
    db.add(AuditLog(action="x", entity_type="t", entity_id="1", timestamp=old)); db.commit()
    svc._last_prune_date = None
    with patch.object(settings, "audit_retention_days", 365), \
         patch.object(svc, "get_db_session", side_effect=RuntimeError("db down")), \
         caplog.at_level(logging.WARNING, logger="agenticops.audit.service"):
        svc.AuditService.maybe_prune_daily()
    assert svc._last_prune_date is None
    assert any(r.levelno == logging.WARNING and "audit prune failed" in r.getMessage() for r in caplog.records)
    db.expire_all()
    assert db.query(AuditLog).count() == 1  # nothing pruned yet
    with patch.object(settings, "audit_retention_days", 365):
        svc.AuditService.maybe_prune_daily()  # retried on the very next call
    db.expire_all()
    assert db.query(AuditLog).count() == 0
    assert svc._last_prune_date == datetime.now(timezone.utc).date()
