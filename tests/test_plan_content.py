# tests/test_plan_content.py
"""A plan's version, content hash and approval binding (MVP-2.6.1 Plan D, spec §3.D.1)."""
import json
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import (
    Base, ChangeRequest, CloudAccount, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult, get_session,
)
from agenticops.services import plan_content as pc

BOB = Actor("user", "bob", 2, ("read", "write"))
FIELDS = dict(steps=[{"command": "aws ec2 reboot-instances"}], rollback_plan={"steps": ["none"]},
              pre_checks=[{"check": "running"}], post_checks=[{"check": "healthy"}], account_id=1, risk_level="L1")


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/plans.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    # approving a change queues its run: pin the executor on so that does not depend on the local settings.yaml
    monkeypatch.setattr(settings, "executor_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()


@pytest.fixture
def client(db):
    from agenticops.web.app import app
    return TestClient(app)  # bare — no `with`, so the lifespan never starts


def _account(db, name="dev"):
    acct = CloudAccount(name=name, provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"])
    db.add(acct); db.commit()
    return acct.id


def _fix_plan(db, status="pending_approval", *, issue_status="fix_planned", account_id=None, stamp=True,
              steps=None):
    """A fix plan as save_fix_plan leaves it; an approved/executing one as its approval (or the backfill) left it."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status=issue_status,
                        resource_id="i-0abc", account_id=account_id)
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   steps=steps if steps is not None else [{"command": "echo a"}], status=status)
    db.add(plan); db.flush()
    if stamp:
        pc.stamp_content(db, plan)
        if status in ("approved", "executing"):
            pc.stamp_approval(db, plan)
    db.commit()
    return plan


def _change_plan(db, cr_status="planned", plan_status="pending_approval"):
    cr = ChangeRequest(title="tag web", description="d", requested_by="user:alice", status=cr_status)
    db.add(cr); db.flush()
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s",
                   steps=[{"command": "aws ec2 create-tags"}], rollback_plan={"steps": ["aws ec2 delete-tags"]},
                   post_checks=[{"check": "present"}], status=plan_status)
    db.add(plan); db.flush()
    pc.stamp_content(db, plan)
    if plan_status in ("approved", "executing"):
        pc.stamp_approval(db, plan)
    db.commit()
    return cr.id, plan


def _fresh(model, pk):
    s = get_session()
    try:
        return s.get(model, pk)
    finally:
        s.close()


def _set_steps(plan_id, steps):
    """A content write that bypassed every stamping path (the gate must still catch it)."""
    s = get_session()
    try:
        s.query(FixPlan).filter_by(id=plan_id).update({"steps": steps}, synchronize_session=False)
        s.commit()
    finally:
        s.close()


# ── the hash and the version ────────────────────────────────────────────────

def test_the_hash_is_canonical_and_covers_what_would_run():
    base = pc.content_hash(**FIELDS)
    assert len(base) == 64
    assert pc.content_hash(**dict(reversed(list(FIELDS.items())))) == base
    assert (pc.content_hash(**{**FIELDS, "steps": [{"a": 1, "b": 2}]})
            == pc.content_hash(**{**FIELDS, "steps": [{"b": 2, "a": 1}]}))
    for key, other in (("steps", []), ("rollback_plan", {}), ("pre_checks", []), ("post_checks", []),
                       ("account_id", 2), ("risk_level", "L2")):
        assert pc.content_hash(**{**FIELDS, key: other}) != base, key


def test_prose_is_not_content(db):
    plan = _fix_plan(db)
    before = pc.current_hash(db, plan)
    plan.title, plan.summary, plan.estimated_impact = "new title", "new summary", "new impact"
    assert pc.current_hash(db, plan) == before


def test_the_version_moves_only_with_the_content(db):
    plan = _fix_plan(db)
    assert (plan.plan_version, plan.content_hash) == (1, pc.current_hash(db, plan))
    plan.title = "retitled"
    pc.stamp_content(db, plan)
    assert plan.plan_version == 1
    plan.steps = [{"command": "echo b"}]
    pc.stamp_content(db, plan)
    assert (plan.plan_version, plan.content_hash) == (2, pc.current_hash(db, plan))


def test_a_plan_is_named_by_what_it_belongs_to_and_its_version(db):
    from agenticops.tools.metadata_tools import get_fix_plan
    plan = _fix_plan(db)
    cr_id, change = _change_plan(db)
    assert pc.plan_label(plan) == f"I#{plan.health_issue_id} fix plan v1"
    assert pc.plan_label(change) == f"C#{cr_id} implementation plan v1"
    data = json.loads(get_fix_plan(plan.health_issue_id))
    assert (data["label"], data["plan_version"], data["content_hash"]) == (
        f"I#{plan.health_issue_id} fix plan v1", 1, plan.content_hash)


def test_an_issue_anchored_to_its_account_is_new_plan_content(db, monkeypatch):
    """The account is plan content: anchoring an unanchored issue restamps its live plans (so the hash the UI
    shows is the one an approval must send)."""
    import agenticops.services.identity_resolver as ir
    acct = _account(db)
    plan = _fix_plan(db)
    done = _fix_plan(db, status="rejected")
    monkeypatch.setattr(ir, "resolve", lambda *a, **k: ir.Anchor(ir.ACCOUNT_LEVEL, account_id=acct,
                                                                  rule=ir.ACCOUNT_LEVEL))
    assert ir.reanchor_open_issues(db) == 2
    db.commit()
    moved = _fresh(FixPlan, plan.id)
    assert (moved.plan_version, moved.content_hash) == (2, pc.current_hash(get_session(), moved))
    assert _fresh(FixPlan, done.id).plan_version == 1  # a terminal plan is history, not restamped



def test_the_anchor_backfill_restamps_a_plan_hashed_before_its_issue_had_an_account(db, monkeypatch):
    """M-4: an issue the 2.6.1 backfill anchors after its plans were hashed has its live plans restamped (else a
    Web approval 409s and no reload clears it); an unhashed plan is left to the hash backfill, which also records
    an approved plan's approved hash, so it can still run."""
    import agenticops.models as models_mod
    import agenticops.services.identity_resolver as ir
    acct = _account(db)
    live, done = _fix_plan(db), _fix_plan(db, status="rejected")
    unhashed = _fix_plan(db, status="approved", issue_status="fix_approved", stamp=False)
    live_id, live_hash, done_id, done_hash, unhashed_id = (live.id, live.content_hash, done.id, done.content_hash,
                                                           unhashed.id)
    monkeypatch.setattr(ir, "resolve", lambda *a, **k: ir.Anchor(ir.ACCOUNT_LEVEL, account_id=acct,
                                                                  rule=ir.ACCOUNT_LEVEL))
    models_mod._backfill_anchors_2_6_1(models_mod.get_engine())
    models_mod._backfill_plan_hashes_2_6_1(models_mod.get_engine())
    moved = _fresh(FixPlan, live_id)
    assert _fresh(HealthIssue, moved.health_issue_id).account_id == acct
    assert moved.content_hash != live_hash
    assert (moved.plan_version, moved.content_hash) == (2, pc.current_hash(get_session(), moved))
    assert _fresh(FixPlan, done_id).content_hash == done_hash  # a terminal plan is history, not restamped
    runnable = _fresh(FixPlan, unhashed_id)
    assert runnable.approved_hash == runnable.content_hash == pc.current_hash(get_session(), runnable)


# ── every approval records what it approved ─────────────────────────────────

def _assert_bound(plan_id, version=1, status="approved"):
    plan = _fresh(FixPlan, plan_id)
    assert plan.status == status
    assert plan.approved_hash == plan.content_hash == pc.current_hash(get_session(), plan)
    assert plan.approved_version == plan.plan_version == version


def test_the_agent_approval_records_the_hash(db):
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _fix_plan(db)
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"), \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:main")
    assert out.startswith(f"I#{plan.health_issue_id} fix plan v1 (FixPlan #{plan.id}) approved"), out
    _assert_bound(plan.id)


def test_the_auto_approval_records_the_hash(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.services.pipeline_service import trigger_auto_approve
    for key, value in (("auto_fix_enabled", True), ("executor_auto_approve_l0_l1", True),
                       ("policy_engine_enabled", False)):
        monkeypatch.setattr(settings, key, value)
    # a step the code can classify: auto-approval leaves an unclassified one (`echo a`) for a human
    plan = _fix_plan(db, status="draft", steps=[{"command": "kubectl get pods -n web"}])
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        trigger_auto_approve(plan.id)
    _assert_bound(plan.id)


def test_the_cli_approval_records_the_hash(db):
    from agenticops.cli import main as cli
    plan = _fix_plan(db)
    out = cli._slash_approve(None, [str(plan.id), "looks", "fine"])
    assert f"I#{plan.health_issue_id} fix plan v1" in out and plan.content_hash[:12] in out
    _assert_bound(plan.id)


def test_the_web_approval_binds_to_the_content_it_was_shown(db, client):
    plan = _fix_plan(db)
    shown = client.get(f"/api/fix-plans/{plan.id}").json()
    assert (shown["plan_version"], shown["content_hash"], shown["approved_hash"]) == (1, plan.content_hash, None)
    # an editor changes the plan meanwhile (naming the content it edited — MVP-2.7.0 S3)
    assert client.put(f"/api/fix-plans/{plan.id}", json={"steps": [{"command": "echo b"}],
                                                         "content_hash": shown["content_hash"]}).status_code == 200
    with patch("agenticops.services.pipeline_service.trigger_auto_execute") as trigger:
        stale = client.put(f"/api/fix-plans/{plan.id}/approve", json={"content_hash": shown["content_hash"]})
        assert stale.status_code == 409
        assert f"I#{plan.health_issue_id} fix plan v2 changed since it was loaded" in stale.json()["detail"]
        trigger.assert_not_called()
        assert _fresh(FixPlan, plan.id).status == "pending_approval"
        reloaded = client.get(f"/api/fix-plans/{plan.id}").json()
        r = client.put(f"/api/fix-plans/{plan.id}/approve", json={"content_hash": reloaded["content_hash"]})
    assert r.status_code == 200 and (r.json()["approved_hash"], r.json()["approved_version"]) == (
        reloaded["content_hash"], 2)
    _assert_bound(plan.id, version=2)


@pytest.mark.parametrize("closed", ["resolved", "dismissed"])
def test_no_path_approves_the_plan_of_a_closed_issue(db, client, monkeypatch, closed):
    """FR-D5: Web, the agent tool, the CLI and the auto-approval all refuse a closed issue's plan — nothing is
    approved or bound, nothing runs, and the issue stays closed."""
    from agenticops.cli import main as cli
    from agenticops.config import settings
    from agenticops.services.pipeline_service import trigger_auto_approve
    from agenticops.tools.metadata_tools import approve_fix_plan
    for key, value in (("auto_fix_enabled", True), ("executor_auto_approve_l0_l1", True),
                       ("policy_engine_enabled", False)):
        monkeypatch.setattr(settings, key, value)
    web, tool, slash = (_fix_plan(db, issue_status=closed) for _ in range(3))
    auto = _fix_plan(db, status="draft", issue_status=closed)
    refusal = "HealthIssue #{} is '%s'; reopen it before approving its plan" % closed
    with patch("agenticops.services.pipeline_service.trigger_auto_execute") as trigger, \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        r = client.put(f"/api/fix-plans/{web.id}/approve", json={"content_hash": web.content_hash})
        assert (r.status_code, r.json()["detail"]) == (409, refusal.format(web.health_issue_id))
        assert approve_fix_plan(fix_plan_id=tool.id, approved_by="agent:main") == refusal.format(tool.health_issue_id)
        assert refusal.format(slash.health_issue_id) in cli._slash_approve(None, [str(slash.id), "looks", "fine"])
        trigger_auto_approve(auto.id)
    trigger.assert_not_called()
    for plan, status in ((web, "pending_approval"), (tool, "pending_approval"), (slash, "pending_approval"),
                         (auto, "draft")):
        row = _fresh(FixPlan, plan.id)
        assert (row.status, row.approved_by, row.approved_hash) == (status, None, None)
        assert _fresh(HealthIssue, plan.health_issue_id).status == closed


def _clear_hash(plan_id):
    s = get_session()
    try:
        s.query(FixPlan).filter_by(id=plan_id).update({"content_hash": None}, synchronize_session=False)
        s.commit()
    finally:
        s.close()


def test_an_empty_or_unstamped_hash_is_the_reload_409(db, client):
    """FR-D8: the UI sends `content_hash ?? ""` — an empty hash is the 409 that says reload, not a 422; a plan
    stored without a hash is stamped by that request, so the reload shows the hash to approve."""
    fix = _fix_plan(db)
    unstamped = _fix_plan(db, stamp=False)
    cr_id, change = _change_plan(db)
    _clear_hash(change.id)
    with patch("agenticops.services.pipeline_service.trigger_auto_execute") as trigger:
        for plan_id in (fix.id, unstamped.id):
            r = client.put(f"/api/fix-plans/{plan_id}/approve", json={"content_hash": ""})
            assert r.status_code == 409 and "reload it and review it again" in r.json()["detail"], r.text
            assert _fresh(FixPlan, plan_id).status == "pending_approval"
        shown = client.get(f"/api/fix-plans/{unstamped.id}").json()
        assert shown["content_hash"] == pc.current_hash(get_session(), _fresh(FixPlan, unstamped.id))
        r = client.put(f"/api/fix-plans/{unstamped.id}/approve", json={"content_hash": shown["content_hash"]})
        assert r.status_code == 200, r.text
    assert trigger.call_count == 1
    _assert_bound(unstamped.id)
    r = client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok", "content_hash": ""})
    assert r.status_code == 409 and "reload it and review it again" in r.json()["detail"], r.text
    assert _fresh(ChangeRequest, cr_id).status == "planned"
    shown = client.get(f"/api/changes/{cr_id}").json()["plans"][0]["content_hash"]
    assert shown and shown == pc.current_hash(get_session(), _fresh(FixPlan, change.id))
    r = client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok", "content_hash": shown})
    assert r.status_code == 200 and r.json()["status"] == "executing"  # approving a change runs it
    _assert_bound(change.id, status="executing")


def test_the_change_approval_binds_to_the_implementation_plan(db, client):
    from agenticops.services import change_service as cs
    cr_id, plan = _change_plan(db)
    with pytest.raises(cs.ChangeStateError, match=f"C#{cr_id} implementation plan v1 changed since"):
        cs.approve(cr_id, actor=BOB, reason="ok", content_hash="0" * 64)
    assert client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok"}).status_code == 422
    assert client.post(f"/api/changes/{cr_id}/approve",
                       json={"reason": "ok", "content_hash": "0" * 64}).status_code == 409
    assert _fresh(ChangeRequest, cr_id).status == "planned"
    shown = client.get(f"/api/changes/{cr_id}").json()["plans"][0]["content_hash"]
    r = client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok", "content_hash": shown})
    assert r.status_code == 200 and r.json()["status"] == "executing"  # approving a change runs it
    _assert_bound(plan.id, status="executing")


# ── the execution gate ──────────────────────────────────────────────────────

def test_the_gate_serves_an_unchanged_approved_plan(db):
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    plan = _fix_plan(db, status="approved", issue_status="fix_approved")
    data = json.loads(get_approved_fix_plan(plan.id))
    assert data["status"] == "approved" and data["label"] == f"I#{plan.health_issue_id} fix plan v1"
    assert data["approved_hash"] == data["content_hash"] and data["approved_version"] == 1
    assert _fresh(FixPlan, plan.id).status == "approved"


def test_a_fix_plan_changed_after_approval_is_aborted_and_withdrawn(db):
    """Chat path (no queued ticket): the refusal is recorded as an aborted execution, the plan is withdrawn
    (approved → rejected) and the issue goes back to root_cause_identified for a new plan."""
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    plan = _fix_plan(db, status="approved", issue_status="fix_approved")
    _set_steps(plan.id, [{"command": "rm -rf /data"}])
    out = get_approved_fix_plan(plan.id)
    assert out.startswith(f"REJECTED: I#{plan.health_issue_id} fix plan v1: content changed after approval "
                          f"(approved v1, now v1)"), out
    assert "root_cause_identified" in out
    s = get_session()
    try:
        ex = s.query(FixExecution).filter_by(fix_plan_id=plan.id).one()
        assert (ex.status, ex.error_message) == ("aborted", pc.CONTENT_CHANGED)
        row = s.get(FixPlan, plan.id)
        assert (row.status, row.rejection_reason) == ("rejected", pc.CONTENT_CHANGED)
        assert s.get(HealthIssue, plan.health_issue_id).status == "root_cause_identified"
        moves = [json.loads(e.detail) for e in s.query(PipelineEvent).filter_by(
            health_issue_id=plan.health_issue_id, event_type="status_changed")]
        assert [(m["from"], m["to"]) for m in moves] == [("fix_approved", "root_cause_identified")]
    finally:
        s.close()
    assert get_approved_fix_plan(plan.id).startswith("REJECTED:")  # withdrawn: it cannot run later either


def test_an_account_anchored_after_approval_aborts_the_queued_run(db):
    """Queued path: the run's own ticket is closed as aborted in place and the executing plan fails."""
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    acct = _account(db)
    plan = _fix_plan(db, status="executing", issue_status="fix_executing")
    ticket = FixExecution(fix_plan_id=plan.id, health_issue_id=plan.health_issue_id, status="running",
                          executed_by="user:bob")
    db.add(ticket); db.commit()
    issue = db.get(HealthIssue, plan.health_issue_id)
    issue.account_id = acct
    pc.restamp_issue_plans(db, issue.id)
    db.commit()
    token = set_run_context(RunContext(actor="agent:executor", agent_name="executor", fix_plan_id=plan.id,
                                       execution_id=ticket.id))
    try:
        out = get_approved_fix_plan(plan.id)
    finally:
        reset_run_context(token)
    assert out.startswith(f"REJECTED: I#{issue.id} fix plan v2: content changed after approval "
                          f"(approved v1, now v2)"), out
    s = get_session()
    try:
        rows = s.query(FixExecution).filter_by(fix_plan_id=plan.id).all()
        assert [(r.id, r.status, r.error_message) for r in rows] == [(ticket.id, "aborted", pc.CONTENT_CHANGED)]
        assert s.get(FixPlan, plan.id).status == "failed"
        assert s.get(HealthIssue, issue.id).status == "root_cause_identified"
    finally:
        s.close()


def test_a_change_plan_changed_after_approval_fails_its_change_request(db):
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    from agenticops.services import change_service as cs
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    cr_id, plan = _change_plan(db, cr_status="executing", plan_status="executing")
    ticket = FixExecution(fix_plan_id=plan.id, status="running", executed_by="user:bob")
    db.add(ticket); db.commit()
    _set_steps(plan.id, [{"command": "aws ec2 terminate-instances"}])
    token = set_run_context(RunContext(actor="agent:executor", agent_name="executor", fix_plan_id=plan.id,
                                       change_request_id=cr_id, execution_id=ticket.id))
    try:
        with patch.object(cs, "notify_change_result"):
            out = get_approved_fix_plan(plan.id)
    finally:
        reset_run_context(token)
    assert out.startswith(f"REJECTED: C#{cr_id} implementation plan v1: content changed after approval"), out
    assert "change request is failed" in out
    assert _fresh(FixExecution, ticket.id).status == "aborted"
    assert _fresh(FixPlan, plan.id).status == "failed"
    assert _fresh(ChangeRequest, cr_id).status == "failed"


def test_an_approved_plan_without_an_approved_hash_is_refused(db):
    """Fail-closed: a plan approved before 2.6.1 that the backfill did not reach needs a new approval."""
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    plan = _fix_plan(db, status="approved", issue_status="fix_approved", stamp=False)
    out = get_approved_fix_plan(plan.id)
    assert out.startswith(f"REJECTED: I#{plan.health_issue_id} fix plan v1: content changed after approval "
                          f"(approved v?, now v1)"), out
    assert _fresh(FixPlan, plan.id).status == "rejected"


# ── people read a plan by its label (MVP-2.6.1 Plan E) ──────────────────────

def test_the_fix_notifications_carry_the_plan_label(db):
    """save → planned, a content update → the next version, approve → approved: each names "I#N fix plan vK"."""
    from agenticops.tools.metadata_tools import approve_fix_plan, save_fix_plan
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="root_cause_identified",
                        resource_id="i-0abc")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.commit()
    args = dict(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="Reboot", summary="s",
                steps=json.dumps([{"command": "aws ec2 reboot-instances"}]), rollback_plan=json.dumps({"steps": []}))
    with patch("agenticops.services.pipeline_service.trigger_auto_approve"), \
         patch("agenticops.services.notification_service.notify_fix_planned") as planned:
        save_fix_plan(**args)
        save_fix_plan(**{**args, "steps": json.dumps([{"command": "aws ec2 reboot-instances --dry-run"}])})
    assert [c.args[1] for c in planned.call_args_list] == [f"I#{issue.id} fix plan v1", f"I#{issue.id} fix plan v2"]
    plan = db.query(FixPlan).filter_by(health_issue_id=issue.id).one()
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"), \
         patch("agenticops.services.notification_service.notify_fix_approved") as approved:
        approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:main")
    assert approved.call_args.args[0] == f"I#{issue.id} fix plan v2"


def test_the_cli_shows_a_plan_by_its_label(db):
    from agenticops.cli import main as cli
    plan = _fix_plan(db)
    out = cli._slash_fix(None, ["show", str(plan.id)])
    assert f"I#{plan.health_issue_id} fix plan v1" in out and "Fix Plan #" not in out


# ── MVP-2.9.0 N15: a plan whose content the database redaction rewrote could never be approved ───────────────────
# Found live on the copy database: an approval answered 409 «changed since it was loaded … reload it», twice, on a
# plan nobody had touched. The plan's step named an access key id. The hash was stamped over the step as the agent
# wrote it; the flush that followed scrubbed the key id out of the stored step (security/db_redaction). From then
# on the stored hash — the one every page sends — was not the hash of the stored content, and no reload could
# fix that. 4 of the 80 plans waiting for approval in that database were in this state.

KEY_STEP = [{"action": "deactivate the leaked key",
             "command": "aws iam update-access-key --user-name app --access-key-id AKIAIOSFODNN7EXAMPLE --status Inactive"}]


def _saved_by_the_agent(db, *, steps=KEY_STEP):
    """A fix plan saved the way the SRE agent saves one (tools.save_fix_plan): the hash is stamped on the plan as it
    was written, in the same transaction whose flush scrubs the stored content."""
    from agenticops.tools.metadata_tools import save_fix_plan
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="root_cause_identified", resource_id="i-0abc")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.commit()
    with patch("agenticops.services.pipeline_service.trigger_auto_approve"):
        out = save_fix_plan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="Deactivate the key", summary="s",
                            steps=json.dumps(steps), rollback_plan=json.dumps({"steps": [{"command": "aws iam update-access-key --user-name app --access-key-id AKIAIOSFODNN7EXAMPLE --status Active"}]}),
                            post_checks=json.dumps([{"check": "the key is inactive"}]))
    assert "saved" in out, out
    s = get_session()
    try:
        return s.query(FixPlan).filter_by(health_issue_id=issue.id).one().id
    finally:
        s.close()


def test_the_stored_hash_is_of_the_content_as_it_is_stored(db):
    stored = _fresh(FixPlan, _saved_by_the_agent(db))
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(stored.steps) and "[REDACTED-SECRET]" in json.dumps(stored.steps)
    assert stored.content_hash == pc.current_hash(get_session(), stored)


def test_a_plan_whose_step_was_redacted_can_be_approved(db, client):
    plan_id = _saved_by_the_agent(db)
    shown = client.get(f"/api/fix-plans/{plan_id}").json()
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        r = client.put(f"/api/fix-plans/{plan_id}/approve", json={"content_hash": shown["content_hash"]})
    assert r.status_code == 200, r.text
    _assert_bound(plan_id)


def test_content_without_a_secret_hashes_as_it_always_did():
    """The fix must not move a single existing hash: every stored approval is bound to one."""
    import hashlib
    canonical = json.dumps({"steps": FIELDS["steps"], "rollback_plan": FIELDS["rollback_plan"], "pre_checks": FIELDS["pre_checks"],
                            "post_checks": FIELDS["post_checks"], "account_id": 1, "risk_level": "L1"},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    assert pc.content_hash(**FIELDS) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_two_plans_that_differ_only_in_a_secret_are_the_same_stored_content():
    a = pc.content_hash(**{**FIELDS, "steps": [{"command": "aws iam delete-access-key --access-key-id AKIAIOSFODNN7EXAMPLE"}]})
    b = pc.content_hash(**{**FIELDS, "steps": [{"command": "aws iam delete-access-key --access-key-id AKIAI44QH8DHBEXAMPLE"}]})
    assert a == b == pc.content_hash(**{**FIELDS, "steps": [{"command": "aws iam delete-access-key --access-key-id [REDACTED-SECRET]"}]})


def test_a_stored_hash_that_is_not_of_the_stored_content_is_repaired_by_the_first_refusal(db, client):
    """The rows written before the fix: the first approval is still refused (the page did show another hash), but
    that request restamps the plan — so the reload the refusal asks for shows a hash that CAN be approved."""
    plan = _fix_plan(db)
    s = get_session()
    s.query(FixPlan).filter_by(id=plan.id).update({"content_hash": "0" * 64})       # as a hash stamped before the redaction is
    s.commit(); s.close()
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        first = client.put(f"/api/fix-plans/{plan.id}/approve", json={"content_hash": "0" * 64})
        assert first.status_code == 409 and "reload it and review it again" in first.json()["detail"]
        healed = _fresh(FixPlan, plan.id)
        assert healed.status == "pending_approval" and healed.content_hash == pc.current_hash(get_session(), healed) != "0" * 64
        assert healed.plan_version == 2                                              # what was hashed is not what is stored: a new version
        again = client.put(f"/api/fix-plans/{plan.id}/approve", json={"content_hash": client.get(f"/api/fix-plans/{plan.id}").json()["content_hash"]})
    assert again.status_code == 200, again.text
    _assert_bound(plan.id, version=2)


def test_a_change_plans_stale_hash_is_repaired_the_same_way(db, client):
    cr_id, change = _change_plan(db)
    s = get_session()
    s.query(FixPlan).filter_by(id=change.id).update({"content_hash": "0" * 64})
    s.commit(); s.close()
    first = client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok", "content_hash": "0" * 64})
    assert first.status_code == 409
    healed = _fresh(FixPlan, change.id)
    assert healed.content_hash == pc.current_hash(get_session(), healed) != "0" * 64
    again = client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok", "content_hash": healed.content_hash})
    assert again.status_code == 200, again.text


def test_the_plans_already_waiting_with_a_stale_hash_are_repaired_at_startup(db):
    """So the first approval after the upgrade is not a refusal. Only plans that wait for approval: an approved
    plan is bound to its approved hash, and a plan whose hash is right keeps its version."""
    import agenticops.models as models_mod
    waiting, fine, approved = _fix_plan(db), _fix_plan(db), _fix_plan(db, status="approved", issue_status="fix_approved")
    ids = (waiting.id, fine.id, approved.id)
    before_fine, before_approved = fine.content_hash, approved.content_hash
    s = get_session()
    s.query(FixPlan).filter(FixPlan.id.in_((waiting.id, approved.id))).update({"content_hash": "0" * 64}, synchronize_session=False)
    s.commit(); s.close()
    models_mod._repair_plan_hashes_2_9_0(models_mod.get_engine())
    w, f, a = (_fresh(FixPlan, i) for i in ids)
    assert w.content_hash == pc.current_hash(get_session(), w) != "0" * 64 and w.plan_version == 2
    assert (f.content_hash, f.plan_version) == (before_fine, 1)
    assert (a.content_hash, a.plan_version) == ("0" * 64, 1) and a.approved_hash == before_approved   # not this repair's
    models_mod._repair_plan_hashes_2_9_0(models_mod.get_engine())                                    # again: nothing moves
    assert _fresh(FixPlan, waiting.id).plan_version == 2


@pytest.mark.parametrize("status", ["executing", "executed", "failed"])
def test_the_repair_never_restamps_a_plan_that_is_past_approval(db, client, status):
    """Round-2 review (C-M1): the approve route refuses such a plan only at the status transition, after the hash
    check — so a stale stored hash on a plan that has already run was restamped (and its version bumped) by an
    approval that was refused anyway, and the pages that compare it with the approved hash then read «not what
    was approved» for a finished run."""
    plan = _fix_plan(db)
    s = get_session()
    s.query(FixPlan).filter_by(id=plan.id).update({"status": status, "content_hash": "0" * 64, "approved_hash": "0" * 64,
                                                   "approved_version": 1})
    s.commit(); s.close()
    r = client.put(f"/api/fix-plans/{plan.id}/approve", json={"content_hash": "f" * 64})
    assert r.status_code == 409
    after = _fresh(FixPlan, plan.id)
    assert (after.content_hash, after.plan_version, after.status) == ("0" * 64, 1, status)
