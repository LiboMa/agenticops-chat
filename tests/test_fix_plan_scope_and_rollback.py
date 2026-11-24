"""2.7.0 E2E observations 1 and 2 (owner 10-09: both; a take-down rollback is refused, not flagged).

1. The SRE over-reached: a «replicas at 0» fix plan added a cluster add-on, an HPA and annotations. The SRE
   prompt now scopes a fix plan to restoring the affected resource; improvements go to the summary as
   follow-ups for a change request. (Prompt-only: no code can judge «beyond restoring» reliably.)
2. A rollback brought the outage back: «restore failed half-way» was rolled back by scaling both Deployments
   to 0. save_fix_plan now refuses a fix plan whose rollback takes the service down — nothing is saved and the
   SRE rewrites it. A change plan is not checked: undoing a scale-up from 0 is a legitimate rollback there.
"""
import json
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, CloudAccount, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services.change_steps import outage_commands, rollback_steps


# ── the pure reading ──────────────────────────────────────────────────


@pytest.mark.parametrize("command", [
    "kubectl scale deployment/frontend --replicas=0 -n web",
    "kubectl -n web scale deploy backend --replicas 0",
    "kubectl delete deployment frontend -n web",
    "kubectl delete deploy/backend",
    "kubectl delete statefulset db -n data",
    "kubectl delete svc frontend -n web",
    "aws ecs update-service --cluster c --service s --desired-count 0",
    "aws --region us-east-1 autoscaling set-desired-capacity --auto-scaling-group-name g --desired-capacity 0",
    "aws autoscaling update-auto-scaling-group --auto-scaling-group-name g --max-size=0",
    "aws eks update-nodegroup-config --cluster-name lab --nodegroup-name ng --scaling-config minSize=0,maxSize=2,desiredSize=0",
    "aws ec2 stop-instances --instance-ids i-0abc",
    "aws rds stop-db-instance --db-instance-identifier db",
    "aws rds stop-db-cluster --db-cluster-identifier c",
    "aws lambda put-function-concurrency --function-name f --reserved-concurrent-executions 0",
    "systemctl stop nginx",
    "sudo systemctl stop nginx",
    "service nginx stop",
])
def test_a_take_down_command_is_named(command):
    assert outage_commands([{"command": command}]) == [command]


@pytest.mark.parametrize("command", [
    "kubectl scale deployment/frontend --replicas=2 -n web",
    "kubectl scale deploy x --replicas=10",
    "kubectl delete pod web-abc -n web",
    "kubectl rollout undo deploy/web -n web",
    "aws ecs update-service --cluster c --service s --desired-count 2",
    "aws autoscaling set-desired-capacity --auto-scaling-group-name g --desired-capacity 10",
    "aws ec2 start-instances --instance-ids i-0abc",
    "aws ec2 delete-tags --resources i-0abc",
    "systemctl restart nginx",
    "systemctl status nginx",
])
def test_a_rollback_that_keeps_the_service_up_passes(command):
    assert outage_commands([{"command": command}]) == []


def test_strings_and_dicts_are_both_read_and_prose_adds_nothing():
    rollback = {"description": "scale both back to 0", "steps": ["kubectl scale deploy/a --replicas=0",
                                                                {"action": "b", "command": "kubectl scale deploy/b --replicas=0"}]}
    assert outage_commands(rollback_steps(rollback)) == ["kubectl scale deploy/a --replicas=0",
                                                         "kubectl scale deploy/b --replicas=0"]


# ── save_fix_plan ─────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    saved = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/rollback.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[])); s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved


RESTORE = json.dumps([{"action": "restore", "command": "kubectl scale deploy/frontend --replicas=3 -n web"},
                      {"action": "restore", "command": "kubectl scale deploy/backend --replicas=2 -n web"}])
TAKE_DOWN = json.dumps({"steps": [{"command": "kubectl scale deploy/frontend --replicas=0 -n web"},
                                  {"command": "kubectl scale deploy/backend --replicas=0 -n web"}]})
POST = json.dumps([{"check": "ready", "command": "kubectl get deploy -n web"}])


def _issue(db):
    issue = HealthIssue(title="replicas at 0", description="d", severity="high", source="t",
                        status="root_cause_identified", resource_id="frontend")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="scaled to 0", confidence=0.9)
    db.add(rca); db.commit()
    return issue.id, rca.id


def _save_fix(issue_id, rca_id, rollback):
    from agenticops.tools.metadata_tools import save_fix_plan
    with patch("agenticops.services.pipeline_service.trigger_auto_approve") as auto:
        out = save_fix_plan(health_issue_id=issue_id, rca_result_id=rca_id, risk_level="L1", title="restore",
                            summary="s", steps=RESTORE, rollback_plan=rollback, post_checks=POST)
    return out, auto


def test_a_fix_plan_whose_rollback_takes_the_service_down_is_refused(db):
    issue_id, rca_id = _issue(db)
    out, auto = _save_fix(issue_id, rca_id, TAKE_DOWN)
    assert out.startswith("INVALID:"), out
    assert "kubectl scale deploy/frontend --replicas=0 -n web" in out and "Nothing was saved" in out
    assert db.query(FixPlan).count() == 0
    auto.assert_not_called()


def test_a_fix_plan_whose_rollback_keeps_what_was_restored_is_saved(db):
    issue_id, rca_id = _issue(db)
    rollback = json.dumps({"description": "keep the restored replicas; nothing to undo",
                           "steps": [{"command": "kubectl rollout undo deploy/frontend -n web"}]})
    out, auto = _save_fix(issue_id, rca_id, rollback)
    assert not out.startswith("INVALID:"), out
    assert db.query(FixPlan).count() == 1
    auto.assert_called_once()


def test_a_change_plan_may_roll_back_to_zero(db):
    from agenticops.services import change_service as cs
    from agenticops.tools.metadata_tools import save_fix_plan
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=Actor("user", "a", 1, ("read", "write")), title="scale up",
                                      description="0 → 2 for the launch", account_name="dev", start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    out = save_fix_plan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="scale up",
                        summary="s", steps=json.dumps([{"action": "scale", "command": "kubectl scale deploy/a --replicas=2"}]),
                        rollback_plan=json.dumps({"steps": [{"command": "kubectl scale deploy/a --replicas=0"}]}),
                        post_checks=POST)
    assert not out.startswith("INVALID:"), out
    assert db.query(FixPlan).filter_by(plan_kind="change").count() == 1


# ── the SRE prompt ────────────────────────────────────────────────────


def test_the_sre_prompt_scopes_a_fix_plan_to_restoring_and_keeps_its_rollback_out_of_the_fault():
    from agenticops.agents.sre_agent import SRE_SYSTEM_PROMPT
    prompt = " ".join(SRE_SYSTEM_PROMPT.split())  # the prompt wraps lines; the rule is what is pinned
    assert "SCOPE: a fix plan only returns the affected resource to its last working state" in prompt
    assert "never go into a fix plan" in prompt and "follow-ups for a change request" in prompt
    assert "ROLLBACK: undoes this plan's own steps" in prompt
    assert "never recreates the fault the issue describes" in prompt
