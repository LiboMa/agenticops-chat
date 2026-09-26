"""change_service: creation, review lifecycle, watchdog (MVP-2.6.0 S2).

``sre_agent_review_change`` is patched with ``create=True``: the SRE Mode C entry point lands in
a later task, and patch() would otherwise fail on the missing attribute. ``_run_review`` imports
the name from the module at call time, so the patched attribute is what runs.
"""
import itertools
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, call, patch

import pytest

from agenticops.auth.actor import Actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(settings, "change_management_enabled", True)
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


def _wait_until(pred, what, timeout=10.0):
    """Poll a predicate written by another thread (real-thread tests only)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


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
            cs._watchdog_fire(cr["id"], 0)  # no start_review ran, so the row is still at attempt 0
        assert cs.get_change(cr["id"])["status"] == "draft"

    def test_watchdog_noop_when_review_finished(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review"); cs.transition_change(row, "planned")
        cs._watchdog_fire(cr["id"], 0)
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
        """Pins the whole async wiring: target, args (incl. the attempt), daemon, name — and who starts what.

        `not timer.called` is the MAJOR-1 regression pin — a Timer is not bound to an attempt, so a
        stale one from a failed attempt used to time out the next, legitimate review. Round 2: the
        worker is constructed here but STARTED by the watchdog, so exactly one start happens at this
        level and a worker can never run without the thread that guards it.
        """
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        worker_mock, watchdog_mock = Mock(name="worker"), Mock(name="watchdog")
        with patch.object(cs.threading, "Thread", side_effect=[worker_mock, watchdog_mock]) as thread, \
             patch.object(cs.threading, "Timer") as timer:
            cs.start_review(cr["id"], sync=False)
        assert not timer.called
        assert thread.call_count == 2
        worker, watchdog = thread.call_args_list
        assert worker.args == () and worker.kwargs == {
            "target": cs._run_review, "args": (cr["id"], cr["trace_id"], 1),
            "daemon": True, "name": f"change-review-{cr['id']}",
        }
        assert watchdog.args == () and watchdog.kwargs == {
            "target": cs._watchdog_join,
            "args": (cr["id"], 1, worker_mock, settings.change_review_timeout_seconds),
            "daemon": True, "name": f"change-review-watchdog-{cr['id']}",
        }
        watchdog_mock.start.assert_called_once_with()  # the only start at this level
        worker_mock.start.assert_not_called()  # the watchdog owns the worker's start
        snap = cs.get_change(cr["id"])
        assert snap["status"] == "under_review" and snap["review_attempt"] == 1

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

    def test_a_failing_audit_row_rolls_the_claim_back(self, db):
        """The other direction of one-transaction: no audit row → no claim. The CR stays a draft at
        attempt 0, so a failed start cannot burn an attempt number or leave the CR under_review."""
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch.object(cs, "_audit", side_effect=RuntimeError("audit write failed")):
            with pytest.raises(RuntimeError):
                cs.start_review(cr["id"], sync=True)
        c = cs.get_change(cr["id"])
        assert c["status"] == "draft" and c["review_attempt"] == 0
        assert _audits(db, "change.reviewed") == []

    def test_review_attempt_counts_starts_and_is_in_the_snapshot(self, db):
        """Every entry into under_review bumps the counter; both audit rows of an attempt carry it."""
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        assert cr["review_attempt"] == 0
        with patch("agenticops.agents.sre_agent.sre_agent_review_change", return_value="no verdict", create=True), \
             patch.object(cs, "notify_change_result"):
            cs.start_review(cr["id"], sync=True)
        c = cs.get_change(cr["id"])
        assert c["status"] == "draft" and c["review_attempt"] == 1
        assert {a.details["phase"]: a.details["attempt"] for a in _audits(db, "change.reviewed")} == {
            "started": 1, "failed": 1,
        }
        with patch.object(cs.threading, "Thread"):  # the restart's worker/watchdog stay inert
            out = cs.restart_review(cr["id"], actor=cli_actor())
        assert out["status"] == "under_review" and out["review_attempt"] == 2

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
        finished = Mock(name="attempt-1-worker")
        finished.is_alive.return_value = False
        with cs._session() as s:  # attempt #2 is legitimately under review
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review")
            row.review_attempt = 2
        with patch.object(cs, "notify_change_result") as notify:
            cs._watchdog_join(cr["id"], 1, finished, 0)
        assert cs.get_change(cr["id"])["status"] == "under_review"
        notify.assert_not_called()

    def test_watchdog_join_starts_joins_and_fires_only_if_alive(self, db):
        """The watchdog owns its worker: start → join(timeout) → fire ONLY while the worker is alive."""
        from agenticops.services import change_service as cs
        for alive in (True, False):
            worker = Mock(name="worker")
            worker.is_alive.return_value = alive
            with patch.object(cs, "_watchdog_fire") as fire:
                cs._watchdog_join(7, 3, worker, 1.5)
            worker.start.assert_called_once_with()
            worker.join.assert_called_once_with(timeout=1.5)
            assert fire.call_args_list == ([call(7, 3)] if alive else [])
        unstartable = Mock(name="unstartable-worker")
        unstartable.start.side_effect = RuntimeError("can't start new thread")
        with patch.object(cs, "_review_failed") as failed:
            with pytest.raises(RuntimeError):
                cs._watchdog_join(7, 3, unstartable, 1.5)
        assert failed.call_count == 1 and failed.call_args.args[:2] == (7, 3)
        unstartable.join.assert_not_called()

    def test_review_failed_leaves_a_finished_review_untouched(self, db):
        """MAJOR 2, status half of the key: 0 rows → no transition, no audit row, no event, no notify."""
        from agenticops.services import change_service as cs
        cr = _draft()
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review")
            cs.transition_change(row, "planned")
            row.review_attempt = 1  # the attempt matches, so only the status can stop the rollback
            row.review_reasons = ["the real verdict"]
        before = db.query(PipelineEvent).filter_by(change_request_id=cr["id"]).count()
        with patch.object(cs, "notify_change_result") as notify:
            cs._review_failed(cr["id"], 1, "a stale watchdog fired")
        c = cs.get_change(cr["id"])
        assert c["status"] == "planned" and c["review_reasons"] == ["the real verdict"]
        assert db.query(PipelineEvent).filter_by(change_request_id=cr["id"]).count() == before
        assert _audits(db, "change.reviewed") == []
        notify.assert_not_called()

    def test_review_failed_is_a_noop_for_a_different_attempt(self, db):
        """MAJOR 1 round 2, attempt half of the key: a late actor from #1 cannot roll back #2."""
        from agenticops.services import change_service as cs
        cr = _draft()
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review")  # attempt #2 genuinely IS under review
            row.review_attempt = 2
            row.review_reasons = ["attempt 2 is running"]
        before = db.query(PipelineEvent).filter_by(change_request_id=cr["id"]).count()
        with patch.object(cs, "notify_change_result") as notify:
            cs._review_failed(cr["id"], 1, "late")
        c = cs.get_change(cr["id"])
        assert c["status"] == "under_review" and c["review_reasons"] == ["attempt 2 is running"]
        assert db.query(PipelineEvent).filter_by(change_request_id=cr["id"]).count() == before
        assert _audits(db, "change.reviewed") == []
        notify.assert_not_called()
        with patch.object(cs, "notify_change_result") as notify:  # the current attempt still rolls back
            cs._review_failed(cr["id"], 2, "now")
        assert cs.get_change(cr["id"])["status"] == "draft"
        notify.assert_called_once()


class TestAttemptKeying:
    """A rollback is only ever legitimate for the attempt that issued it."""

    @pytest.mark.parametrize("ending", ["no_verdict", "crash"])
    def test_late_rollback_from_a_timed_out_attempt_cannot_touch_the_next_one(self, db, ending):
        """Attempt #1 hangs past the timeout, a human restarts, then #1 finally returns (or raises).

        Its own end-of-run / crash rollback must be a 0-row no-op: attempt #2 genuinely IS
        `under_review`, so the status half of the key cannot stop it — only the attempt half can.
        Releasing #2 afterwards proves the CURRENT attempt's rollback still applies.
        """
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr = _draft()
        gate1, gate2 = threading.Event(), threading.Event()
        started1, started2 = threading.Event(), threading.Event()
        turn = itertools.count(1)
        rollbacks: list = []
        real_failed = cs._review_failed

        def spy_failed(*a, **kw):  # signature-agnostic: appended AFTER the write, so a wait means "done"
            try:
                return real_failed(*a, **kw)
            finally:
                rollbacks.append(a)

        def fake_sre(change_request_id):
            if next(turn) == 1:
                started1.set()
                gate1.wait(timeout=15)
                if ending == "crash":
                    raise RuntimeError("attempt 1 died on its way out")
                return "attempt 1 returns far too late"
            started2.set()
            gate2.wait(timeout=15)
            return "attempt 2 forgot the verdict too"

        def failed_events():
            return (db.query(PipelineEvent)
                    .filter_by(change_request_id=cr["id"], event_type="review_failed")
                    .order_by(PipelineEvent.id).all())

        try:
            with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre, create=True), \
                 patch.object(cs, "_review_failed", spy_failed), \
                 patch.object(cs, "notify_change_result") as notify:
                with patch.object(settings, "change_review_timeout_seconds", 0.05):
                    cs.start_review(cr["id"], sync=False)
                    assert started1.wait(timeout=5), "attempt 1's worker never ran"
                    _wait_until(lambda: len(rollbacks) >= 1, "attempt 1 to time out")
                assert cs.get_change(cr["id"])["status"] == "draft" and notify.call_count == 1

                with patch.object(settings, "change_review_timeout_seconds", 30):  # #2's watchdog must not fire
                    cs.restart_review(cr["id"], actor=cli_actor())
                assert started2.wait(timeout=5), "attempt 2's worker never ran"
                assert cs.get_change(cr["id"])["status"] == "under_review"

                gate1.set()  # attempt 1 returns (or raises) long after its own attempt was rolled back
                _wait_until(lambda: len(rollbacks) >= 2, "attempt 1's late rollback to run")
                c = cs.get_change(cr["id"])
                assert c["status"] == "under_review", "attempt 1's late rollback hit attempt 2"
                assert c["review_attempt"] == 2
                assert c["review_reasons"][0].startswith("review timed out")  # worker #1 wrote nothing
                assert len(failed_events()) == 1 and notify.call_count == 1

                gate2.set()  # the current attempt's own rollback still applies
                _wait_until(lambda: len(rollbacks) >= 3, "attempt 2's rollback to run")
                rows = failed_events()
                assert cs.get_change(cr["id"])["status"] == "draft"
                assert len(rows) == 2 and json.loads(rows[1].detail)["attempt"] == 2
                assert notify.call_count == 2
        finally:
            gate1.set()
            gate2.set()
            for t in threading.enumerate():
                if t.name.startswith("change-review"):
                    t.join(timeout=5)


class TestAtomicClaim:
    """Entry into under_review is a conditional UPDATE, so one attempt number = one review run."""

    def test_claim_for_review_is_atomic_and_bumps(self, db):
        from agenticops.services import change_service as cs
        cr = _draft()
        with cs._session() as s:
            row = cs._load(s, cr["id"])  # identity-mapped BEFORE the bulk UPDATE
            assert cs._claim_for_review(s, cr["id"]) == (True, 1)
            # A bulk UPDATE does not write through the identity map: without the refresh inside the
            # claim these two still read the old row, and the audit snapshot would be wrong.
            assert (row.status, row.review_attempt) == ("under_review", 1)
        with cs._session() as s:  # a second claim on an under_review row loses and writes nothing
            assert cs._claim_for_review(s, cr["id"]) == (False, 0)
        c = cs.get_change(cr["id"])
        assert c["status"] == "under_review" and c["review_attempt"] == 1
        with cs._session() as s:  # needs_clarification is the other legal source state
            cs.transition_change(cs._load(s, cr["id"]), "needs_clarification")
        with cs._session() as s:
            assert cs._claim_for_review(s, cr["id"]) == (True, 2)
        assert cs.get_change(cr["id"])["status"] == "under_review"

    def test_concurrent_start_review_lets_exactly_one_win(self, db):
        """Two starts on one draft: exactly one claims it, the other gets a 409 — never two attempt 1s.

        Against 541e793 both win: the → under_review edge was an in-memory validate plus an ORM UPDATE
        by PK, so both callers read `draft`, both bumped 0 → 1, and two SRE runs then shared one key —
        each run's no-verdict/crash/timeout rollback acting on the other's. The barrier releases both
        threads in exactly that window (after the row read, before the claim).
        """
        from agenticops.services import change_service as cs
        cr = _draft()
        barrier = threading.Barrier(2, timeout=10)
        real_load = cs._load
        reads = itertools.count(1)
        results: list = []

        def barrier_load(session, cr_id):
            row = real_load(session, cr_id)
            if next(reads) <= 2:  # the two racing callers' first read; the winner's second read runs free
                barrier.wait()
            return row

        def start():
            try:
                cs.start_review(cr["id"], sync=False)
                results.append("won")
            except cs.ChangeStateError:
                results.append("409")

        racers = [threading.Thread(target=start, name=f"change-start-{i}", daemon=True) for i in (1, 2)]
        with patch.object(cs, "_load", barrier_load), patch.object(cs, "_run_review"), \
             patch.object(cs, "notify_change_result") as notify:
            try:
                for t in racers:
                    t.start()
                for t in racers:
                    t.join(timeout=20)
            finally:
                barrier.abort()  # a caller left waiting must never wedge the suite
                for t in racers + [t for t in threading.enumerate() if t.name.startswith("change-review")]:
                    t.join(timeout=5)
        assert not any(t.is_alive() for t in racers), "a racing start never finished"
        assert sorted(results) == ["409", "won"], f"both callers claimed the same review: {results}"
        c = cs.get_change(cr["id"])
        assert c["status"] == "under_review" and c["review_attempt"] == 1
        started = [a for a in _audits(db, "change.reviewed") if a.details.get("phase") == "started"]
        assert len(started) == 1 and started[0].details["attempt"] == 1
        notify.assert_not_called()  # a lost claim is not a failed review: no rollback, no notification


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
