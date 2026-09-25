# tests/test_change_service_review.py
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor, agent_actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixPlan, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/rev.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={"account_id": "111111111111"}, regions=["ap-southeast-1"])
    s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance",
                        resource_id="i-0abc", name="web-1", tags={"Name": "web-1"}))
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="SecurityGroup",
                        resource_id="sg-111", name="web-sg"))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


def _cr(db, targets=("i-0abc",), change_type="normal", under_review=True):
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="cli", actor=cli_actor(), title="tag", description="add Env=prod",
                                      account_name="dev", targets=list(targets), requested_change_type=change_type,
                                      start_review=False)
    if under_review:
        with cs._session() as s:
            cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    return cr["id"]


def _draft_plan(db, cr_id, rollback=None, post_checks=None):
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s",
                   steps=[{"action": "tag", "command": "aws ec2 create-tags ..."}],
                   rollback_plan=rollback if rollback is not None else {"steps": [{"command": "aws ec2 delete-tags ..."}]},
                   post_checks=post_checks if post_checks is not None else [{"check": "tag present", "command": "aws ec2 describe-tags ..."}],
                   status="draft")
    db.add(plan); db.commit()
    return plan


class TestGrounding:
    def test_ground_matches_inventory_by_id_and_name(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-0abc", "web-sg", "i-missing"))
        out = cs.ground_targets(cr_id)
        assert {g["resource_id"] for g in out["grounded"]} == {"i-0abc", "sg-111"}
        assert out["unresolved"] == ["i-missing"]
        c = cs.get_change(cr_id)
        assert len(c["target_resources"]) == 2 and c["target_resources"][0]["evidence"] == "inventory"

    def test_attach_target_runs_code_describe(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-0def",))
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"Reservations": [1]}') as ex:
            out = cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"))
        assert ex.call_args.args[0].startswith("aws ec2 describe-instances --instance-ids i-0def")
        assert ex.call_args.args[1] == "dev"
        assert out["resource_id"] == "i-0def" and out["evidence"]["command"].startswith("aws ec2 describe-instances")
        assert cs.ground_targets(cr_id)["unresolved"] == []

    def test_attach_target_not_found_is_rejected(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-0def",))
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="Error (exit code 254): InvalidInstanceID.NotFound"):
            with pytest.raises(cs.ChangeValidationError):
                cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"))
        assert cs.get_change(cr_id)["target_resources"] == []

    def test_attach_target_unknown_type_uses_arn_or_fails(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=())
        with pytest.raises(cs.ChangeValidationError):
            cs.attach_target(cr_id, "thing-1", "made:up", actor=agent_actor("sre"))
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"ResourceTagMappingList":[{}]}') as ex:
            cs.attach_target(cr_id, "arn:aws:sqs:ap-southeast-1:111111111111:q1", "sqs:queue", actor=agent_actor("sre"))
        assert "resourcegroupstaggingapi get-resources" in ex.call_args.args[0]

    # ── Ruling 3: attach_target input validation is LOAD-BEARING security ──
    # An LLM-supplied resource_id like "i-0abc --profile other" would smuggle a --profile flag into the
    # describe command → a read on the WRONG account (violates the multi-account credential 铁律 §3).
    def test_attach_target_rejects_injected_resource_id(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=())
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli") as ex:
            with pytest.raises(cs.ChangeValidationError):  # embedded space + injected flag
                cs.attach_target(cr_id, "i-0abc --profile other", "ec2:instance", actor=agent_actor("sre"))
            with pytest.raises(cs.ChangeValidationError):  # leading dash → looks like a flag
                cs.attach_target(cr_id, "-rf", "ec2:instance", actor=agent_actor("sre"))
        assert not ex.called  # the describe must never run on unvalidated input

    def test_attach_target_rejects_malformed_region(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=())
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli") as ex:
            with pytest.raises(cs.ChangeValidationError):
                cs.attach_target(cr_id, "i-0abc", "ec2:instance", actor=agent_actor("sre"), region="; rm -rf")
        assert not ex.called

    # ── A requester hint resolves the same way in ground_targets and submit_review ──
    def test_attach_with_hint_repairs_a_default_hint(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("web-2",))  # a name that is not in the inventory
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"Reservations": [1]}'):
            cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"))  # no hint: defaults to the id
            assert cs.ground_targets(cr_id)["unresolved"] == ["web-2"]
            cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"), hint="web-2")  # the retry repairs it
            assert cs.ground_targets(cr_id)["unresolved"] == []
            cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"), hint="web-3")  # a real hint is kept
        items = cs.get_change(cr_id)["target_resources"]
        assert [(t["resource_id"], t["hint"]) for t in items] == [("i-0def", "web-2")]

    def test_hint_resolved_via_an_attached_items_hint_is_not_unresolved(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("web-2",))
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"Reservations": [1]}'):
            cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"), hint="web-2")
        assert "web-2" not in cs.ground_targets(cr_id)["unresolved"]

    def test_grounding_is_refused_outside_review(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-0abc", "web-2"), under_review=False)  # a draft: no review is running
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"Reservations": [1]}') as ex:
            with pytest.raises(cs.ChangeStateError, match="targets can only be grounded during review"):
                cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"), hint="web-2")
            with pytest.raises(cs.ChangeStateError, match="targets can only be grounded during review"):
                cs.ground_targets(cr_id)
        assert not ex.called  # a refused attach runs no command
        c = cs.get_change(cr_id)
        assert c["status"] == "draft" and c["target_resources"] == [] and c["target_hints"] == ["i-0abc", "web-2"]

    # ── The write re-checks the review, keyed to the attempt (mirrors submit_review) ──
    def test_attach_writes_nothing_when_the_review_ends_during_the_describe(self, db):
        from agenticops.audit.models import AuditLog
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("web-2",))

        def describe_while_the_review_ends(*args, **kwargs):
            with cs._session() as s:  # e.g. a needs_clarification verdict lands while the describe runs
                cs.transition_change(s.get(ChangeRequest, cr_id), "needs_clarification")
            return '{"Reservations": [1]}'

        audits = db.query(AuditLog).count()
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", side_effect=describe_while_the_review_ends) as ex:
            with pytest.raises(cs.ChangeStateError, match="targets can only be grounded during review"):
                cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"), hint="web-2")
        assert ex.called  # the review was live when the call began: the describe ran, the WRITE was refused
        c = cs.get_change(cr_id)
        assert c["status"] == "needs_clarification"
        assert c["target_resources"] == [] and c["target_hints"] == ["web-2"]
        assert db.query(AuditLog).count() == audits

    def test_grounding_is_keyed_to_the_review_attempt(self, db):
        """A stale SRE run (its attempt was rolled back and restarted) must not ground targets on the newer one."""
        from agenticops.audit.models import AuditLog
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-0abc", "web-2"))
        with cs._session() as s:  # a timeout + restart happened: the row is now attempt 2, still under_review
            s.get(ChangeRequest, cr_id).review_attempt = 2
        before, audits = cs.get_change(cr_id), db.query(AuditLog).count()
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"Reservations": [1]}'):
            token = cs._review_attempt_var.set(1)  # the stale, still-running SRE invocation of attempt 1
            try:
                with pytest.raises(cs.ChangeStateError, match="no longer at review attempt 1"):
                    cs.ground_targets(cr_id)
                with pytest.raises(cs.ChangeStateError, match="no longer at review attempt 1"):
                    cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"), hint="web-2")
            finally:
                cs._review_attempt_var.reset(token)
            assert cs.get_change(cr_id) == before and db.query(AuditLog).count() == audits  # nothing written
            token = cs._review_attempt_var.set(2)  # the live attempt
            try:
                assert [g["resource_id"] for g in cs.ground_targets(cr_id)["grounded"]] == ["i-0abc"]
                cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"), hint="web-2")
            finally:
                cs._review_attempt_var.reset(token)
        c = cs.get_change(cr_id)
        assert [(t["resource_id"], t["hint"]) for t in c["target_resources"]] == [("i-0abc", "i-0abc"), ("i-0def", "web-2")]
        assert cs.ground_targets(cr_id)["unresolved"] == []  # the direct/manual path (no attempt) is unchanged


class TestPolicy:
    def test_evaluate_policy_uses_change_kind_and_logs_event(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        cs.ground_targets(cr_id)
        d = cs.evaluate_policy(cr_id, "L1", "tag")
        assert d.action == "auto_approve" and d.itsm_change_type == "standard"
        assert any(e.event_type == "policy_decision" for e in db.query(PipelineEvent).filter_by(change_request_id=cr_id))

    def test_emergency_flag_is_passed(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, change_type="emergency")
        with patch("agenticops.services.policy_engine.PolicyEngine.evaluate") as ev:
            ev.return_value.to_dict.return_value = {}
            ev.return_value.action = "require_human"; ev.return_value.rule_name = "x"; ev.return_value.itsm_change_type = "normal"
            cs.evaluate_policy(cr_id, "L2", "network")
        assert ev.call_args.kwargs["emergency"] is True and ev.call_args.kwargs["plan_kind"] == "change"


class TestSubmitReview:
    def test_requires_grounded_targets_and_plan(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        with pytest.raises(cs.ChangeStateError):  # nothing grounded, no plan
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
        cs.ground_targets(cr_id)
        with pytest.raises(cs.ChangeStateError):  # no plan yet
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
        _draft_plan(db, cr_id, rollback={})
        with pytest.raises(cs.ChangeStateError):  # rollback missing
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))

    def test_planned_waits_for_human_by_default(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        cs.ground_targets(cr_id)
        plan = _draft_plan(db, cr_id)
        with patch.object(cs, "notify_change_pending_approval") as notify:
            out = cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                   reasons=["single instance tag"], actor=agent_actor("sre"))
        assert out["status"] == "planned" and out["effective_change_type"] == "standard"
        assert out["policy_rule"] == "change-standard-low-risk" and out["policy_action"] == "auto_approve"
        db.refresh(plan)
        assert plan.status == "pending_approval"
        notify.assert_called_once()

    def test_auto_approve_when_flag_and_rule_agree(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        cs.ground_targets(cr_id)
        _draft_plan(db, cr_id)
        with patch.object(settings, "change_auto_approve_standard", True), \
             patch.object(cs, "approve") as approve, patch.object(cs, "request_execution") as execute:
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
        approve.assert_called_once()
        assert approve.call_args.kwargs["actor"].key == "agent:auto-pipeline"
        assert "change-standard-low-risk" in approve.call_args.kwargs["reason"]
        execute.assert_called_once()

    def test_block_forces_rejected(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        cs.ground_targets(cr_id)
        _draft_plan(db, cr_id)
        from agenticops.services.policy_engine import PolicyDecision
        with patch.object(cs, "evaluate_policy", return_value=PolicyDecision(action="block", rule_name="freeze-window-block", reasons=["freeze"])), \
             patch.object(cs, "notify_change_result") as notify:
            out = cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
        assert out["status"] == "rejected" and out["policy_rule"] == "freeze-window-block"
        assert "freeze" in " ".join(out["review_reasons"])
        notify.assert_called_once()

    def test_needs_clarification_and_rejected_verdicts(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-missing",))
        with patch.object(cs, "notify_change_result"):
            out = cs.submit_review(cr_id, verdict="needs_clarification", reasons=["i-missing not found"], actor=agent_actor("sre"))
        assert out["status"] == "needs_clarification" and out["review_reasons"] == ["i-missing not found"]
        cr2 = _cr(db)
        with patch.object(cs, "notify_change_result"):
            out2 = cs.submit_review(cr2, verdict="rejected", reasons=["out of scope"], actor=agent_actor("sre"))
        assert out2["status"] == "rejected" and out2["rejected_by"] == "agent:sre"

    def test_bad_verdict_or_risk(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        with pytest.raises(cs.ChangeValidationError):
            cs.submit_review(cr_id, verdict="maybe", reasons=[], actor=agent_actor("sre"))
        with pytest.raises(cs.ChangeValidationError):
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L9", action_type="tag", reasons=[], actor=agent_actor("sre"))


class TestStaleAttemptRace:
    """Ruling 4d — the stale-run race on the SUBMIT path.

    Attempt N's SRE run exceeds change_review_timeout_seconds; the watchdog rolls attempt N back (keyed N,
    Task 3) and a restart bumps the row to attempt N+1 (still under_review). Attempt N's STILL-RUNNING
    invocation (a join-timeout does not kill the thread) finally calls submit_review. A status-only claim
    would MATCH (the row IS under_review) and attempt N's stale verdict would land on attempt N+1. The
    attempt-keyed claim must reject it — the row stays under_review at N+1 and NO field write leaks.

    This test FAILS against a status-only claim (drop `attempt=` from _claim and the verdict lands: status
    becomes planned and reviewed_by is stamped).
    """

    def test_stale_attempt_verdict_cannot_land_on_the_next_attempt(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)  # under_review, review_attempt 0
        cs.ground_targets(cr_id)
        _draft_plan(db, cr_id)
        with cs._session() as s:  # a timeout+restart happened: the row is now attempt 2, still under_review
            s.get(ChangeRequest, cr_id).review_attempt = 2
        token = cs._review_attempt_var.set(1)  # the stale, still-running SRE invocation belongs to attempt 1
        try:
            with patch.object(cs, "notify_change_pending_approval"), patch.object(cs, "notify_change_result"):
                with pytest.raises(cs.ChangeStateError):
                    cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                     reasons=["stale verdict from attempt 1"], actor=agent_actor("sre"))
        finally:
            cs._review_attempt_var.reset(token)
        c = cs.get_change(cr_id)
        assert c["status"] == "under_review"     # the verdict did not land
        assert c["review_attempt"] == 2          # the newer attempt is untouched
        assert c["reviewed_by"] is None          # the whole transaction rolled back — no field-write trace
