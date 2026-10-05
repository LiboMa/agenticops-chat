from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor, agent_actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixExecution, FixPlan, get_session

ALICE = Actor("user", "alice", user_id=1, permissions=("read", "write"))
BOB = Actor("user", "bob", user_id=2, permissions=("read", "write"))


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(settings, "change_management_enabled", True)
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/exec.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"])
    s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


def _planned(db, requester=ALICE):
    """A CR in 'planned' with a pending_approval change plan (the state after a positive review)."""
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=requester, title="tag", description="add Env=prod",
                                      account_name="dev", targets=["i-0abc"], start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    cs.ground_targets(cr["id"])
    plan = FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="p", summary="s",
                   steps=[{"action": "tag", "command": "aws ec2 create-tags"}], rollback_plan={"steps": ["aws ec2 delete-tags"]},
                   post_checks=[{"check": "tag present", "command": "aws ec2 describe-tags"}], status="draft")
    db.add(plan); db.commit()
    with patch.object(cs, "notify_change_pending_approval"):
        cs.submit_review(cr["id"], verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
    return cr["id"], plan.id


def _seen(cr_id):
    """The content hash of the change's implementation plan, as the approver is shown it (spec §3.D.1)."""
    from agenticops.services.plan_content import current_hash
    s = get_session()
    try:
        plan = (s.query(FixPlan).filter_by(change_request_id=cr_id, plan_kind="change")
                .order_by(FixPlan.id.desc()).first())
        return current_hash(s, plan)
    finally:
        s.close()


def _audits(db, action):
    from agenticops.audit.models import AuditLog
    return db.query(AuditLog).filter_by(action=action).all()


class TestApproveRejectCancel:
    def test_approve_binds_actor_and_reason(self, db):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        out = cs.approve(cr_id, actor=BOB, reason="reviewed, low risk", content_hash=_seen(cr_id))
        assert out["status"] == "approved" and out["approved_by"] == "user:bob" and out["approval_reason"] == "reviewed, low risk"
        db.expire_all()
        assert db.get(FixPlan, plan_id).status == "approved" and db.get(FixPlan, plan_id).approved_by == "user:bob"
        assert len(_audits(db, "change.approved")) == 1

    def test_approve_requires_reason(self, db):
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        with pytest.raises(cs.ChangeValidationError):
            cs.approve(cr_id, actor=BOB, reason="  ", content_hash=_seen(cr_id))

    def test_sod_enforced_when_rbac_enforce(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db, requester=ALICE)
        with patch.object(settings, "rbac_enforce", True):
            with pytest.raises(cs.ChangeForbidden):
                cs.approve(cr_id, actor=ALICE, reason="self", content_hash=_seen(cr_id))
        assert len(_audits(db, "authz.denied")) == 1
        with patch.object(settings, "rbac_enforce", False):
            out = cs.approve(cr_id, actor=ALICE, reason="self, shadow mode", content_hash=_seen(cr_id))  # allowed, audited as shadow
        assert out["status"] == "approved" and len(_audits(db, "authz.denied_shadow")) == 1

    def test_approve_wrong_state_409(self, db):
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        cs.approve(cr_id, actor=BOB, reason="ok", content_hash=_seen(cr_id))
        with pytest.raises(cs.ChangeStateError):
            cs.approve(cr_id, actor=BOB, reason="again", content_hash=_seen(cr_id))

    def test_reject_and_cancel(self, db):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        with patch.object(cs, "notify_change_result") as notify:
            out = cs.reject(cr_id, actor=BOB, reason="not now")
        assert out["status"] == "rejected" and out["rejected_by"] == "user:bob" and out["rejection_reason"] == "not now"
        db.expire_all()
        assert db.get(FixPlan, plan_id).status == "rejected"
        notify.assert_called_once()
        cr2, plan2 = _planned(db)
        cs.approve(cr2, actor=BOB, reason="ok", content_hash=_seen(cr2))
        out2 = cs.cancel(cr2, actor=ALICE, reason="changed my mind")
        assert out2["status"] == "cancelled"
        db.expire_all()
        assert db.get(FixPlan, plan2).status == "rejected"  # withdrawn
        assert len(_audits(db, "change.cancelled")) == 1

    def test_clarify_appends_and_restarts_review(self, db):
        from agenticops.services import change_service as cs
        with patch.object(cs, "notify_change_requested"):
            cr = cs.create_change_request(source="web", actor=ALICE, title="t", description="vague", start_review=False)
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review"); cs.transition_change(row, "needs_clarification")
        with patch.object(cs, "start_review") as sr:
            out = cs.clarify(cr["id"], actor=ALICE, message="the instance is i-0abc")
        assert "i-0abc" in out["description"] and "Clarification" in out["description"]
        sr.assert_called_once_with(cr["id"], sync=False)
        assert len(_audits(db, "change.clarified")) == 1


class TestExecution:
    def test_request_execution_enqueues_and_transitions(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        cs.approve(cr_id, actor=BOB, reason="ok", content_hash=_seen(cr_id))
        with patch.object(settings, "executor_enabled", True):
            out = cs.request_execution(cr_id, actor=BOB)
        ex = db.get(FixExecution, out["execution_id"])
        assert ex.status == "pending" and ex.fix_plan_id == plan_id and ex.executed_by == "user:bob"
        db.expire_all()
        assert db.get(FixPlan, plan_id).status == "executing" and out["change"]["status"] == "executing"
        assert len(_audits(db, "change.execution_started")) == 1

    def test_request_execution_requires_approved(self, db):
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        with pytest.raises(cs.ChangeStateError):
            cs.request_execution(cr_id, actor=BOB)

    def test_request_execution_executor_disabled(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        cs.approve(cr_id, actor=BOB, reason="ok", content_hash=_seen(cr_id))
        with patch.object(settings, "executor_enabled", False):
            with pytest.raises(cs.ChangeStateError):
                cs.request_execution(cr_id, actor=BOB)


def _executing(db):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr_id, plan_id = _planned(db)
    cs.approve(cr_id, actor=BOB, reason="ok", content_hash=_seen(cr_id))
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr_id, actor=BOB)
    return cr_id, plan_id


class TestTerminalMapper:
    @pytest.mark.parametrize("status,results,expected", [
        ("succeeded", [{"check": "tag present", "status": "pass"}], "completed"),
        ("succeeded", [], "needs_review"),
        ("succeeded", [{"check": "tag present", "status": "fail"}], "needs_review"),
        ("failed", [], "failed"),
        ("rolled_back", [], "rolled_back"),
        ("aborted", [], "failed"),
    ])
    def test_mapping(self, db, status, results, expected):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _executing(db)
        with patch.object(cs, "notify_change_result") as notify, \
             patch.object(cs, "notify_execution_pending_acceptance") as pending:
            out = cs.on_execution_result(plan_id, status, post_check_results=results)
        assert out["status"] == expected
        if status == "succeeded" and not results:  # pending acceptance: its own notification, not change_result
            notify.assert_not_called()
            assert pending.call_args.args[1] == "post-check results missing or incomplete"
        else:
            pending.assert_not_called()
            notify.assert_called_once()
            assert notify.call_args.args[1] == expected
        if expected in ("completed", "failed", "rolled_back"):
            assert out["closed_at"] is not None

    def test_non_change_plan_returns_none(self, db):
        from agenticops.models import HealthIssue, RCAResult
        from agenticops.services import change_service as cs
        issue = HealthIssue(title="t", description="d", severity="low", source="t", status="fix_approved", resource_id="r")
        db.add(issue); db.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9); db.add(rca); db.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s", status="executing")
        db.add(plan); db.commit()
        assert cs.on_execution_result(plan.id, "succeeded") is None

    def test_resolve_review_by_human(self, db):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _executing(db)
        with patch.object(cs, "notify_change_result"):
            cs.on_execution_result(plan_id, "succeeded", post_check_results=[])
        out = cs.resolve_review(cr_id, actor=BOB, outcome="completed", reason="verified manually in console")
        assert out["status"] == "completed" and out["closed_at"] is not None
        assert _audits(db, "change.completed")[-1].details["resolved_by_human"] is True
        with pytest.raises(cs.ChangeValidationError):
            cs.resolve_review(cr_id, actor=BOB, outcome="maybe", reason="x")


def test_change_timeline_merges_events_and_audits(db):
    from agenticops.services import change_service as cs
    cr_id, _ = _planned(db)
    tl = cs.change_timeline(cr_id)
    kinds = {e["kind"] for e in tl}
    assert kinds == {"event", "audit"}
    assert tl == sorted(tl, key=lambda e: e["ts"])
    assert any(e["type"] == "change.requested" for e in tl) and any(e["type"] == "change_requested" for e in tl)


class TestLostClaimRace:
    """Ruling 4 — the two execution-gating transitions MUST lose to a concurrent state change.

    The TOCTOU is reproduced deterministically: patch active_plan_for (called AFTER the status guard but
    BEFORE the _claim) to move the CR row off its from-status on approve's OWN session with an uncommitted
    ``synchronize_session=False`` UPDATE. The loaded ORM row therefore still reads the from-status (the
    guard passes) while the claim's ``... WHERE status=<from>`` now matches 0 rows → False → ChangeStateError
    → the whole transaction (including the injected move) rolls back.

    Each test FAILS if the _claim is dropped for a bare _transition: the in-memory row still holds the
    from-status, so validate_change_transition passes, the ORM write commits, and the row advances
    (approve → 'approved' + approved_by; request_execution → a FixExecution row + 'executing').
    """

    @staticmethod
    def _move_off(from_to, target):
        """A patched active_plan_for that first moves the CR off `target` (same session, uncommitted,
        no identity-map sync) then returns the real active plan."""
        from agenticops.services import change_service as cs
        real = cs.active_plan_for

        def _patched(session, cid):
            session.query(ChangeRequest).filter(ChangeRequest.id == cid).update(
                {"status": target}, synchronize_session=False)
            return real(session, cid)
        return _patched

    def test_approve_lost_claim_raises_and_leaves_no_trace(self, db):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        seen = _seen(cr_id)
        with patch.object(cs, "active_plan_for", self._move_off("planned", "cancelled")):
            with pytest.raises(cs.ChangeStateError):
                cs.approve(cr_id, actor=BOB, reason="racing an approve", content_hash=seen)
        db.expire_all()
        cr = db.get(ChangeRequest, cr_id)
        assert cr.status == "planned"          # approve rolled back entirely — FAILS if the claim is dropped
        assert cr.approved_by is None           # no field-write leak
        assert db.get(FixPlan, plan_id).status != "approved"   # plan not advanced
        assert len(_audits(db, "change.approved")) == 0

    def test_request_execution_lost_claim_creates_no_execution(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        cs.approve(cr_id, actor=BOB, reason="ok", content_hash=_seen(cr_id))
        before = db.query(FixExecution).count()
        with patch.object(settings, "executor_enabled", True), \
             patch.object(cs, "active_plan_for", self._move_off("approved", "cancelled")):
            with pytest.raises(cs.ChangeStateError):
                cs.request_execution(cr_id, actor=BOB)
        db.expire_all()
        assert db.query(FixExecution).count() == before   # load-bearing: no FixExecution enqueued (no double AWS mutation)
        assert db.get(ChangeRequest, cr_id).status == "approved"       # request_execution rolled back
        assert db.get(FixPlan, plan_id).status == "approved"           # plan not moved to executing


class TestKillSwitch:
    """change_management_enabled=false stops every human decision before it reads, checks or writes anything;
    work already in flight still lands, so a flag flip never strands a running execution."""

    @pytest.mark.parametrize("call,kwargs", [
        ("approve", {"reason": "ok", "content_hash": "any"}),
        ("reject", {"reason": "no"}),
        ("cancel", {"reason": "x"}),
        ("clarify", {"message": "m"}),
        ("request_execution", {}),
        ("restart_review", {}),
        ("resolve_review", {"outcome": "completed", "reason": "r"}),
    ])
    def test_every_human_decision_refuses_when_disabled(self, db, call, kwargs):
        from agenticops.audit.models import AuditLog
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        audits = db.query(AuditLog).count()
        authz_rows = db.query(AuditLog).filter(AuditLog.action.like("authz.%")).count()
        executions = db.query(FixExecution).count()
        # The executor is on, so request_execution's own "Executor is disabled" cannot pass for the kill switch.
        # ALICE is the requester: a gate placed after _check would leave an authz.denied_shadow row behind.
        with patch.object(settings, "change_management_enabled", False), patch.object(settings, "executor_enabled", True), \
             patch.object(cs, "notify_change_result"), patch.object(cs, "start_review") as sr:
            with pytest.raises(cs.ChangeStateError, match="Change management is disabled"):
                getattr(cs, call)(cr_id, actor=ALICE, **kwargs)
        sr.assert_not_called()
        db.expire_all()
        assert db.get(ChangeRequest, cr_id).status == "planned"
        assert db.query(AuditLog).count() == audits
        assert db.query(AuditLog).filter(AuditLog.action.like("authz.%")).count() == authz_rows
        assert db.query(FixExecution).count() == executions

    def test_an_approved_change_queues_no_execution_when_disabled(self, db):
        """The case the switch exists for: an already-approved change must not reach the executor."""
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        cs.approve(cr_id, actor=BOB, reason="ok", content_hash=_seen(cr_id))
        executions = db.query(FixExecution).count()
        with patch.object(settings, "change_management_enabled", False), patch.object(settings, "executor_enabled", True):
            with pytest.raises(cs.ChangeStateError, match="Change management is disabled"):
                cs.request_execution(cr_id, actor=BOB)
        db.expire_all()
        assert db.query(FixExecution).count() == executions
        assert db.get(ChangeRequest, cr_id).status == "approved"
        assert db.get(FixPlan, plan_id).status == "approved"

    def test_an_execution_in_flight_still_completes_when_disabled(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _executing(db)
        with patch.object(settings, "change_management_enabled", False), patch.object(cs, "notify_change_result"):
            out = cs.on_execution_result(plan_id, "succeeded", post_check_results=[{"check": "tag present", "status": "pass"}])
        assert out["status"] == "completed"
        db.expire_all()
        assert db.get(ChangeRequest, cr_id).status == "completed"


# ── G15 FR-3: the auto-approve branch of submit_review is durable ──────────────

def _under_review_with_draft_l1_plan(db):
    """A CR at 'under_review' with a grounded target and a draft L1 change plan — the exact state
    submit_review consumes. Unlike _planned it does NOT call submit_review, so the caller drives the
    auto-approve branch itself (with the settings it wants)."""
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=ALICE, title="tag", description="add Env=prod",
                                      account_name="dev", targets=["i-0abc"], start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    cs.ground_targets(cr["id"])
    plan = FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="p", summary="s",
                   steps=[{"action": "tag", "command": "aws ec2 create-tags"}], rollback_plan={"steps": ["aws ec2 delete-tags"]},
                   post_checks=[{"check": "tag present", "command": "aws ec2 describe-tags"}], status="draft")
    db.add(plan); db.commit()
    return cr["id"], plan.id


class TestAutoApproveDurability:
    """FR-3: a standard-change auto-approve must survive a failed enqueue or a failed approve. The approval
    is durable and submit_review never errors out — on BASE the exception propagates straight through it."""

    def test_disabled_executor_leaves_the_change_approved_and_notifies(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _under_review_with_draft_l1_plan(db)
        with patch.object(settings, "change_auto_approve_standard", True), \
             patch.object(settings, "executor_enabled", False), \
             patch.object(cs, "notify_change_pending_approval") as pending, \
             patch.object(cs, "notify_change_result") as result:
            out = cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                   reasons=["ok"], actor=agent_actor("sre"))
        assert isinstance(out, dict)                        # no ChangeStateError escaped submit_review
        db.expire_all()
        assert db.get(ChangeRequest, cr_id).status == "approved"   # approval is durable, the change waits
        assert db.query(FixExecution).count() == 0                 # nothing was enqueued
        assert [c.args[1] for c in result.call_args_list] == ["execution_not_queued"]
        pending.assert_not_called()

    def test_enabled_executor_queues_exactly_one_run(self, db):
        """The auto-approve goes through the same approve-then-queue path as a human approval: one run, no
        execution_not_queued (a second queue attempt after the first would raise and notify it wrongly)."""
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _under_review_with_draft_l1_plan(db)
        with patch.object(settings, "change_auto_approve_standard", True), \
             patch.object(settings, "executor_enabled", True), \
             patch.object(cs, "notify_change_pending_approval") as pending, \
             patch.object(cs, "notify_change_result") as result:
            out = cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                   reasons=["ok"], actor=agent_actor("sre"))
        assert out["status"] == "executing" and out["approved_by"] == "agent:auto-pipeline"
        db.expire_all()
        runs = db.query(FixExecution).filter_by(fix_plan_id=plan_id).all()
        assert len(runs) == 1 and runs[0].executed_by == "agent:auto-pipeline"
        result.assert_not_called()
        pending.assert_not_called()

    def test_an_exception_after_the_auto_approval_never_asks_a_human_to_approve(self, db):
        """2026-10-05 final review Minor 1: only the approve step falls back to the human gate. An exception
        after the approval committed (here: reading the change back) must not send the pending-approval notice
        for a change that is already approved and queued."""
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _under_review_with_draft_l1_plan(db)
        with patch.object(settings, "change_auto_approve_standard", True), \
             patch.object(settings, "executor_enabled", True), \
             patch.object(cs, "get_change", side_effect=RuntimeError("db gone")), \
             patch.object(cs, "notify_change_pending_approval") as pending, \
             patch.object(cs, "notify_change_result"):
            with pytest.raises(RuntimeError):
                cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                 reasons=["ok"], actor=agent_actor("sre"))
        pending.assert_not_called()
        db.expire_all()
        assert db.get(ChangeRequest, cr_id).status == "executing"
        assert db.query(FixExecution).filter_by(fix_plan_id=plan_id).count() == 1

    def test_failed_auto_approve_falls_back_to_the_human_gate(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _under_review_with_draft_l1_plan(db)
        with patch.object(settings, "change_auto_approve_standard", True), \
             patch.object(settings, "executor_enabled", True), \
             patch.object(cs, "approve", side_effect=cs.ChangeStateError("lost the claim")) as approve, \
             patch.object(cs, "notify_change_pending_approval") as pending, \
             patch.object(cs, "notify_change_result") as result:
            out = cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                   reasons=["ok"], actor=agent_actor("sre"))
        assert isinstance(out, dict)                        # no exception escaped
        approve.assert_called_once()
        db.expire_all()
        assert db.get(ChangeRequest, cr_id).status == "planned"    # stays planned for a human approver
        assert db.query(FixExecution).count() == 0
        pending.assert_called_once()                        # fell back to the pending-approval notification
        result.assert_not_called()


class TestApproveAndExecute:
    """Owner ruling 2026-10-03 (joint E2E): a human approval of a change runs it — no separate Execute click,
    as a fix plan already runs on approval. approve() stays the pure state move; approve_and_execute() is the
    one approve-then-queue path (Web API, CLI, the policy auto-approve)."""

    def test_approval_queues_the_run_as_the_approver(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        with patch.object(settings, "executor_enabled", True), patch.object(cs, "notify_change_result") as result:
            out = cs.approve_and_execute(cr_id, actor=BOB, reason="reviewed", content_hash=_seen(cr_id))
        assert out["status"] == "executing" and out["approved_by"] == BOB.key
        db.expire_all()
        runs = db.query(FixExecution).filter_by(fix_plan_id=plan_id).all()
        assert len(runs) == 1 and runs[0].status == "pending" and runs[0].executed_by == BOB.key
        assert db.get(FixPlan, plan_id).status == "executing"
        assert [a.actor for a in _audits(db, "change.approved")] == [BOB.key]
        assert [a.actor for a in _audits(db, "change.execution_started")] == [BOB.key]
        result.assert_not_called()

    def test_a_run_that_cannot_be_queued_keeps_the_approval_and_notifies(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        with patch.object(settings, "executor_enabled", False), patch.object(cs, "notify_change_result") as result:
            out = cs.approve_and_execute(cr_id, actor=BOB, reason="reviewed", content_hash=_seen(cr_id))
        assert out["status"] == "approved" and out["approved_by"] == BOB.key   # the approval is durable
        db.expire_all()
        assert db.query(FixExecution).count() == 0
        assert db.get(FixPlan, plan_id).status == "approved"
        assert [c.args[1] for c in result.call_args_list] == ["execution_not_queued"]
        # the retry path is the existing manual one, still open while the change waits at approved
        with patch.object(settings, "executor_enabled", True):
            assert cs.request_execution(cr_id, actor=BOB)["change"]["status"] == "executing"

    def test_a_refused_approval_queues_nothing_and_raises(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db, requester=ALICE)
        with patch.object(settings, "executor_enabled", True), patch.object(settings, "rbac_enforce", True), \
             patch.object(cs, "request_execution") as execute:
            with pytest.raises(cs.ChangeForbidden):     # SoD: the requester may not approve
                cs.approve_and_execute(cr_id, actor=ALICE, reason="self", content_hash=_seen(cr_id))
            with pytest.raises(cs.ChangeStateError):    # a plan other than the one reviewed
                cs.approve_and_execute(cr_id, actor=BOB, reason="stale", content_hash="0" * 64)
        execute.assert_not_called()
        db.expire_all()
        assert db.get(ChangeRequest, cr_id).status == "planned" and db.query(FixExecution).count() == 0

    def test_the_not_queued_notice_says_why(self, db):
        """2026-10-05 final review Minor 1: the refusal is in the notification, not only in the log."""
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        with patch.object(settings, "executor_enabled", False), patch.object(cs, "notify_change_result") as result:
            cs.approve_and_execute(cr_id, actor=BOB, reason="reviewed", content_hash=_seen(cr_id))
        assert result.call_args.args[1] == "execution_not_queued"
        assert "Executor is disabled" in result.call_args.kwargs["reason"]

    def test_the_not_queued_notification_body_carries_the_refusal(self):
        from agenticops.services import notification_service as ns
        cr = {"id": 3, "title": "t", "requested_by": "user:alice", "risk_level": "L1", "needs_review_reason": None}
        with patch.object(ns, "notify_event") as sent:
            ns.notify_change_result(cr, "execution_not_queued", reason="Executor is disabled\n(executor_enabled=false)")
        assert "Reason: Executor is disabled (executor_enabled=false)\n" in sent.call_args.args[2]  # one line

    def test_a_claim_lost_to_a_concurrent_execute_is_not_reported_as_not_queued(self, db):
        """Losing approved → executing means another request moved the change: a concurrent /execute already
        queued it. That is no 'not queued' — no notification, and the one run stays the only one."""
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        carol = Actor("user", "carol", user_id=3, permissions=("read", "write"))
        real = cs.request_execution

        def raced(cid, *, actor):
            real(cid, actor=carol)            # the concurrent request lands first
            return real(cid, actor=actor)     # ours loses: the change is no longer approved

        with patch.object(settings, "executor_enabled", True), patch.object(cs, "request_execution", side_effect=raced), \
             patch.object(cs, "notify_change_result") as result:
            out = cs.approve_and_execute(cr_id, actor=BOB, reason="reviewed", content_hash=_seen(cr_id))
        assert out["status"] == "executing"
        result.assert_not_called()
        db.expire_all()
        assert [r.executed_by for r in db.query(FixExecution).filter_by(fix_plan_id=plan_id)] == ["user:carol"]

    def test_a_claim_lost_to_a_cancel_is_not_reported_as_not_queued(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        real = cs.request_execution

        def cancelled(cid, *, actor):
            cs.cancel(cid, actor=ALICE, reason="not now")
            return real(cid, actor=actor)

        with patch.object(settings, "executor_enabled", True), patch.object(cs, "request_execution", side_effect=cancelled), \
             patch.object(cs, "notify_change_result") as result:
            out = cs.approve_and_execute(cr_id, actor=BOB, reason="reviewed", content_hash=_seen(cr_id))
        assert out["status"] == "cancelled"
        assert "execution_not_queued" not in [c.args[1] for c in result.call_args_list]
        db.expire_all()
        assert db.query(FixExecution).count() == 0
