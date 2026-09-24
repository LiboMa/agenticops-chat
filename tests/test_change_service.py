"""change_service: creation, review lifecycle, watchdog (MVP-2.6.0 S2).

``sre_agent_review_change`` is patched with ``create=True``: the SRE Mode C entry point lands in
a later task, and patch() would otherwise fail on the missing attribute. ``_run_review`` imports
the name from the module at call time, so the patched attribute is what runs.
"""
import threading
import time
from datetime import datetime, timedelta, timezone
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


def _draft():
    """A committed draft CR, no review started (the starting point of every review test)."""
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        return cs.create_change_request(source="cli", actor=cli_actor(), title="t", description="d",
                                        start_review=False)


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
        return _draft()

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

    def test_async_start_review_spawns_worker_and_a_join_watchdog(self, db):
        """Pins the whole async wiring: target, args, daemon, name and the started-ness of BOTH threads.

        `not timer.called` is the MAJOR-1 regression pin — a Timer is not bound to an attempt, so a
        stale one from a failed attempt used to time out the next, legitimate review.
        """
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch.object(cs.threading, "Thread") as thread, patch.object(cs.threading, "Timer") as timer:
            cs.start_review(cr["id"], sync=False)
        assert not timer.called
        assert thread.call_count == 2
        worker, watchdog = thread.call_args_list
        assert worker.args == () and worker.kwargs == {
            "target": cs._run_review, "args": (cr["id"], cr["trace_id"]),
            "daemon": True, "name": f"change-review-{cr['id']}",
        }
        assert watchdog.args == () and watchdog.kwargs == {
            "target": cs._watchdog_join,
            "args": (cr["id"], thread.return_value, settings.change_review_timeout_seconds),
            "daemon": True, "name": f"change-review-watchdog-{cr['id']}",
        }
        assert thread.return_value.start.call_count == 2  # both spawned threads were actually started
        assert cs.get_change(cr["id"])["status"] == "under_review"

    def test_spawn_failure_rolls_the_review_back_and_surfaces(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch.object(cs.threading, "Thread", side_effect=RuntimeError("can't start new thread")), \
             patch.object(cs, "notify_change_result") as notify:
            with pytest.raises(RuntimeError):
                cs.start_review(cr["id"], sync=False)
        assert cs.get_change(cr["id"])["status"] == "draft"
        notify.assert_called_once()

    def test_base_exception_rolls_back_then_propagates(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=KeyboardInterrupt, create=True), \
             patch.object(cs, "notify_change_result") as notify:
            with pytest.raises(KeyboardInterrupt):
                cs.start_review(cr["id"], sync=True)
        assert cs.get_change(cr["id"])["status"] == "draft"
        notify.assert_called_once()

    def test_review_start_audit_row_lands_with_the_transition(self, db):
        """The change.reviewed row and the under_review transition become visible together = one transaction."""
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        seen = {}

        def fake_sre(change_request_id):
            seen["status"] = db.query(ChangeRequest.status).filter_by(id=change_request_id).scalar()
            seen["audits"] = [(a.old_values, a.new_values, a.actor, a.details.get("phase"))
                              for a in _audits(db, "change.reviewed")]
            with cs._session() as s:
                cs.transition_change(s.get(ChangeRequest, change_request_id), "planned")
            return "verdict delivered"

        with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre, create=True):
            cs.start_review(cr["id"], sync=True)
        assert seen["status"] == "under_review"
        assert seen["audits"] == [({"status": "draft"}, {"status": "under_review"}, "agent:sre", "started")]
        rows = _audits(db, "change.reviewed")
        assert len(rows) == 1  # a review that reached a verdict writes no failure row
        assert rows[0].entity_type == "change_request" and rows[0].entity_id == str(cr["id"])

    def test_restart_review_requires_draft(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch.object(cs, "start_review") as sr:
            cs.restart_review(cr["id"], actor=cli_actor())
        sr.assert_called_once_with(cr["id"], sync=False)


class TestWatchdog:
    """The watchdog guards ONE attempt by joining that attempt's own thread."""

    def test_watchdog_rolls_back_a_hung_review(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr = _draft()
        started, release = threading.Event(), threading.Event()

        def hung_sre(change_request_id):
            started.set()
            release.wait(timeout=10)
            return "too late to matter"

        with patch.object(settings, "change_review_timeout_seconds", 0.05), \
             patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=hung_sre, create=True), \
             patch.object(cs, "notify_change_result") as notify:
            cs.start_review(cr["id"], sync=False)
            assert started.wait(timeout=5), "review worker never ran"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and cs.get_change(cr["id"])["status"] != "draft":
                time.sleep(0.02)
            assert cs.get_change(cr["id"])["status"] == "draft"
            release.set()
            for t in threading.enumerate():
                if t.name.startswith("change-review"):
                    t.join(timeout=5)
        events = [e.event_type for e in db.query(PipelineEvent).filter_by(change_request_id=cr["id"])]
        assert events.count("review_failed") == 1  # the late worker found 'draft' and wrote nothing
        notify.assert_called_once()

    def test_watchdog_of_a_finished_attempt_cannot_kill_the_next_one(self, db):
        """MAJOR 1: attempt #1's watchdog must never roll back attempt #2 (its worker is done → no fire)."""
        from agenticops.services import change_service as cs
        cr = _draft()
        attempt1 = threading.Thread(target=lambda: None, name="change-review-attempt-1")
        attempt1.start()
        attempt1.join()
        with cs._session() as s:  # attempt #2 is legitimately under review
            cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
        with patch.object(cs, "notify_change_result") as notify:
            cs._watchdog_join(cr["id"], attempt1, 0)
        assert cs.get_change(cr["id"])["status"] == "under_review"
        notify.assert_not_called()

    def test_review_failed_leaves_a_finished_review_untouched(self, db):
        """MAJOR 2: 0 rows updated → no transition, no audit row, no event, no notification."""
        from agenticops.services import change_service as cs
        cr = _draft()
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review")
            cs.transition_change(row, "planned")
            row.review_reasons = ["the real verdict"]
        before = db.query(PipelineEvent).filter_by(change_request_id=cr["id"]).count()
        with patch.object(cs, "notify_change_result") as notify:
            cs._review_failed(cr["id"], "a stale watchdog fired")
        c = cs.get_change(cr["id"])
        assert c["status"] == "planned" and c["review_reasons"] == ["the real verdict"]
        assert db.query(PipelineEvent).filter_by(change_request_id=cr["id"]).count() == before
        assert _audits(db, "change.reviewed") == []
        notify.assert_not_called()


class TestStaleReviewRecovery:
    def test_fresh_under_review_and_other_states_are_refused(self, db):
        from agenticops.services import change_service as cs
        cr = _draft()
        with cs._session() as s:
            cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
        with pytest.raises(cs.ChangeStateError):
            cs.restart_review(cr["id"], actor=cli_actor())
        with cs._session() as s:
            cs.transition_change(s.get(ChangeRequest, cr["id"]), "planned")
        with pytest.raises(cs.ChangeStateError):
            cs.restart_review(cr["id"], actor=cli_actor())

    def test_stale_under_review_is_rolled_back_then_restarted(self, db):
        from agenticops.services import change_service as cs
        cr = _draft()
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review")
            row.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
        with patch.object(cs, "start_review") as sr, patch.object(cs, "notify_change_result") as notify:
            out = cs.restart_review(cr["id"], actor=cli_actor())
        sr.assert_called_once_with(cr["id"], sync=False)
        assert out["status"] == "draft"
        rows = _audits(db, "change.reviewed")
        assert len(rows) == 1 and rows[0].details["phase"] == "stale_recovery"
        assert "stale review recovered" in rows[0].details["error"]
        notify.assert_called_once()


class TestCallerContext:
    """sync=True runs in the CALLER's thread: the trace id and Run Context must come back unchanged."""

    def _with_caller_context(self, cs, cr_id, sre_patch, expect_raises=None):
        from agenticops.config import get_trace_id, set_trace_id
        from agenticops.run_context import RunContext, get_run_context, reset_run_context, set_run_context
        tid_token = set_trace_id("TRC-caller01")
        rc_token = set_run_context(RunContext(actor="user:alice", actor_user_id=1, trace_id="TRC-caller01"))
        try:
            with sre_patch, patch.object(cs, "notify_change_result"):
                if expect_raises:
                    with pytest.raises(expect_raises):
                        cs.start_review(cr_id, sync=True)
                else:
                    cs.start_review(cr_id, sync=True)
            return get_trace_id(), get_run_context().actor
        finally:
            reset_run_context(rc_token)
            tid_token.var.reset(tid_token)

    def test_success_path_restores_caller_trace_and_actor(self, db):
        from agenticops.run_context import get_run_context
        from agenticops.services import change_service as cs
        cr = _draft()
        inside = {}

        def fake_sre(change_request_id):
            inside["actor"] = get_run_context().actor
            inside["trace"] = get_run_context().trace_id
            with cs._session() as s:
                cs.transition_change(s.get(ChangeRequest, change_request_id), "planned")
            return "ok"

        patcher = patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre, create=True)
        assert self._with_caller_context(cs, cr["id"], patcher) == ("TRC-caller01", "user:alice")
        assert inside["actor"] == "agent:sre" and inside["trace"] == cr["trace_id"]

    def test_crash_path_restores_caller_trace_and_actor(self, db):
        from agenticops.services import change_service as cs
        cr = _draft()
        patcher = patch("agenticops.agents.sre_agent.sre_agent_review_change",
                        side_effect=RuntimeError("bedrock down"), create=True)
        assert self._with_caller_context(cs, cr["id"], patcher) == ("TRC-caller01", "user:alice")
        assert cs.get_change(cr["id"])["status"] == "draft"


class TestSnapshotsAndQueries:
    def test_timestamps_are_utc_aware_on_both_paths(self, db):
        from agenticops.services import change_service as cs
        fresh = _draft()  # snapshot of a live ORM object (tz-aware)
        reread = cs.get_change(fresh["id"])  # re-read from SQLite (stored without an offset)
        for field in ("created_at", "requested_at"):
            assert fresh[field].endswith("+00:00"), field
            assert fresh[field] == reread[field], field

    def test_active_plan_for_returns_the_latest_non_terminal_change_plan(self, db):
        from agenticops.models import FixPlan
        from agenticops.services import change_service as cs
        cr = _draft()
        t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
        with cs._session() as s:
            s.add_all([
                FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="rejected one",
                        summary="s", status="rejected", created_at=t0 + timedelta(minutes=3)),
                FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="older draft",
                        summary="s", status="draft", created_at=t0),
                FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="latest",
                        summary="s", status="pending_approval", created_at=t0 + timedelta(minutes=2)),
            ])
        with cs._session() as s:
            assert cs.active_plan_for(s, cr["id"]).title == "latest"
            assert cs.active_plan_for(s, cr["id"] + 999) is None
        with cs._session() as s:
            for p in s.query(FixPlan).all():
                p.status = "executed"
        with cs._session() as s:
            assert cs.active_plan_for(s, cr["id"]) is None

    def test_list_changes_filters_ordering_and_paging(self, db):
        from agenticops.services import change_service as cs
        with patch.object(cs, "notify_change_requested"):
            a = cs.create_change_request(source="web", actor=ALICE, title="a", description="d",
                                         account_name="dev", start_review=False)
            b = cs.create_change_request(source="cli", actor=cli_actor(), title="b", description="d",
                                         start_review=False)
            c = cs.create_change_request(source="web", actor=ALICE, title="c", description="d",
                                         start_review=False)
        titles = lambda rows: [r["title"] for r in rows]  # noqa: E731
        assert titles(cs.list_changes()) == ["c", "b", "a"]  # newest first
        assert titles(cs.list_changes(requested_by="user:alice")) == ["c", "a"]
        assert titles(cs.list_changes(account_id=a["account_id"])) == ["a"]
        assert titles(cs.list_changes(limit=1)) == ["c"]
        assert titles(cs.list_changes(limit=1, offset=1)) == ["b"]
        assert len(cs.list_changes(status="draft")) == 3
        with cs._session() as s:
            cs.transition_change(s.get(ChangeRequest, b["id"]), "under_review")
        assert titles(cs.list_changes(status="under_review")) == ["b"]
        assert len(cs.list_changes(since=datetime.now(timezone.utc) - timedelta(minutes=5))) == 3
        assert cs.list_changes(since=datetime.now(timezone.utc) + timedelta(minutes=5)) == []

    def test_create_survives_a_failing_start_review(self, db):
        """The row is already committed: a spawn failure must not make a retrying client file duplicates."""
        from agenticops.services import change_service as cs
        with patch.object(cs, "notify_change_requested"), \
             patch.object(cs, "start_review", side_effect=RuntimeError("no threads left")):
            cr = cs.create_change_request(source="web", actor=ALICE, title="t", description="d")
        assert cs.get_change(cr["id"])["status"] == "draft"
        assert len(cs.list_changes()) == 1
