"""change_service: creation, review lifecycle, watchdog (MVP-2.6.0 S2).

``sre_agent_review_change`` is patched with ``create=True``: the SRE Mode C entry point lands in
a later task, and patch() would otherwise fail on the missing attribute. ``_run_review`` imports
the name from the module at call time, so the patched attribute is what runs.
"""
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cs.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={"account_id": "111111111111"}, regions=["ap-southeast-1"]))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


ALICE = Actor("user", "alice", user_id=1, permissions=("read", "write"))


def _audits(db, action):
    from agenticops.audit.models import AuditLog
    return db.query(AuditLog).filter_by(action=action).all()


class TestCreate:
    def test_create_writes_cr_audit_event_and_notifies(self, db):
        from agenticops.services import change_service as cs
        with patch.object(cs, "notify_change_requested") as notify, patch.object(cs, "start_review") as sr:
            cr = cs.create_change_request(source="web", actor=ALICE, title="Tag prod EC2", description="add Env=prod to i-0abc",
                                          account_name="dev", targets=["i-0abc"], justification="compliance")
        assert cr["status"] == "draft" and cr["requested_by"] == "user:alice" and cr["requester_user_id"] == 1
        assert cr["target_hints"] == ["i-0abc"] and cr["target_resources"] == [] and cr["source"] == "web"
        assert cr["account_id"] is not None and cr["trace_id"].startswith("TRC-")
        assert len(_audits(db, "change.requested")) == 1
        ev = db.query(PipelineEvent).filter_by(change_request_id=cr["id"]).one()
        assert ev.event_type == "change_requested" and ev.stage == "intake"
        notify.assert_called_once()
        sr.assert_called_once_with(cr["id"], sync=False)

    def test_unknown_account_is_validation_error(self, db):
        from agenticops.services import change_service as cs
        with pytest.raises(cs.ChangeValidationError):
            cs.create_change_request(source="web", actor=ALICE, title="t", description="d", account_name="nope", start_review=False)

    def test_bad_source_and_type(self, db):
        from agenticops.services import change_service as cs
        with pytest.raises(cs.ChangeValidationError):
            cs.create_change_request(source="carrier-pigeon", actor=ALICE, title="t", description="d", start_review=False)
        with pytest.raises(cs.ChangeValidationError):
            cs.create_change_request(source="web", actor=ALICE, title="t", description="d", requested_change_type="urgent", start_review=False)

    def test_disabled_flag(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        with patch.object(settings, "change_management_enabled", False):
            with pytest.raises(cs.ChangeStateError):
                cs.create_change_request(source="web", actor=ALICE, title="t", description="d", start_review=False)

    def test_authz_denied_maps_to_forbidden(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        im = Actor("im", "feishu:ou_1", permissions=())  # im subject: read only → change.request allowed
        cs.create_change_request(source="im", actor=im, title="t", description="d", start_review=False)
        nobody = Actor("user", "nobody", permissions=())
        with patch.object(settings, "rbac_enforce", True):
            with pytest.raises(cs.ChangeForbidden):
                cs.create_change_request(source="web", actor=nobody, title="t", description="d", start_review=False)


class TestReviewLifecycle:
    def _cr(self, db):
        from agenticops.services import change_service as cs
        with patch.object(cs, "notify_change_requested"):
            return cs.create_change_request(source="cli", actor=cli_actor(), title="t", description="d", start_review=False)

    def test_start_review_sync_calls_sre_and_transitions(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        seen = {}

        def fake_sre(change_request_id):
            seen["status_during"] = db.query(ChangeRequest.status).filter_by(id=change_request_id).scalar()
            # a well-behaved SRE submits a verdict; here we simulate it by moving to planned directly
            with cs._session() as s:
                row = s.get(ChangeRequest, change_request_id)
                cs.transition_change(row, "needs_clarification")
            return "reviewed"

        with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre, create=True):
            out = cs.start_review(cr["id"], sync=True)
        assert out == "reviewed" and seen["status_during"] == "under_review"
        assert cs.get_change(cr["id"])["status"] == "needs_clarification"

    def test_review_without_verdict_rolls_back_to_draft(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch("agenticops.agents.sre_agent.sre_agent_review_change", return_value="I forgot to submit", create=True), \
             patch.object(cs, "notify_change_result") as notify:
            cs.start_review(cr["id"], sync=True)
        c = cs.get_change(cr["id"])
        assert c["status"] == "draft"
        assert any(e.event_type == "review_failed" for e in db.query(PipelineEvent).filter_by(change_request_id=cr["id"]))
        notify.assert_called_once()

    def test_review_exception_rolls_back_to_draft(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=RuntimeError("bedrock down"), create=True), \
             patch.object(cs, "notify_change_result"):
            cs.start_review(cr["id"], sync=True)
        assert cs.get_change(cr["id"])["status"] == "draft"

    def test_watchdog_fires_when_still_under_review(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with cs._session() as s:
            cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
        with patch.object(cs, "notify_change_result"):
            cs._watchdog_fire(cr["id"])
        assert cs.get_change(cr["id"])["status"] == "draft"

    def test_watchdog_noop_when_review_finished(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review"); cs.transition_change(row, "planned")
        cs._watchdog_fire(cr["id"])
        assert cs.get_change(cr["id"])["status"] == "planned"

    def test_start_review_from_wrong_state_is_409(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review"); cs.transition_change(row, "planned")
        with pytest.raises(cs.ChangeStateError):
            cs.start_review(cr["id"], sync=True)

    def test_async_start_review_spawns_thread(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch.object(cs.threading, "Thread") as thread, patch.object(cs.threading, "Timer") as timer:
            cs.start_review(cr["id"], sync=False)
        assert thread.called and timer.called
        assert cs.get_change(cr["id"])["status"] == "under_review"

    def test_restart_review_requires_draft(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch.object(cs, "start_review") as sr:
            cs.restart_review(cr["id"], actor=cli_actor())
        sr.assert_called_once_with(cr["id"], sync=False)
