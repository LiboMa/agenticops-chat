"""NewUI (MVP-2.9.0): a plan's response says how the CODE classifies each step's command.

The approval brief shows «changes things / read-only / unclassified / blocked» beside every step and says it is
classified by code, not stated by the model. The classifier is the one the auto-approval floor already uses
(services/change_steps.command_tier); the response only exposes it. Read context: computed from the steps on the way
out, never stored, never part of the content hash an approval is bound to.
"""
import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services.change_steps import step_tier, step_tiers, unclassified_commands

WRITE = {"action": "close it", "command": "aws ec2 revoke-security-group-ingress --group-id sg-1"}
READ = {"action": "look", "command": "aws ec2 describe-security-groups"}
UNKNOWN = {"action": "x", "command": "aws custom-service do-thing --id 1"}
BLOCKED = {"action": "bad", "command": "aws iam create-user --user-name x"}
NO_COMMAND = {"action": "restart the worker"}


class TestStepTier:
    @pytest.mark.parametrize("step,tier", [
        (WRITE, "write"),
        (READ, "readonly"),
        ({"command": "kubectl get pods -n web"}, "readonly"),
        ({"command": "kubectl rollout restart deploy/web"}, "write"),
        ({"command": "systemctl restart nginx"}, "write"),
        (UNKNOWN, "unknown"),
        (BLOCKED, "blocked"),
        (NO_COMMAND, "unknown"),          # no command: the executor would decide what to run
        ("aws s3 ls", "readonly"),        # a bare string is its own command
        ("restart it by hand", "unknown"),
        ("", "unknown"), (None, "unknown"), ({}, "unknown"),
    ])
    def test_one_step(self, step, tier):
        assert step_tier(step) == tier

    def test_a_list_has_one_tier_per_step_in_order(self):
        assert step_tiers([WRITE, READ, NO_COMMAND, UNKNOWN, BLOCKED]) == ["write", "readonly", "unknown", "unknown", "blocked"]
        assert step_tiers([]) == [] and step_tiers(None) == []

    def test_legacy_json_string_steps_are_decoded_first(self):
        assert step_tiers('[{"command": "aws ec2 describe-instances"}, {"action": "by hand"}]') == ["readonly", "unknown"]

    def test_it_agrees_with_the_auto_approval_floor(self):
        """«unknown» here is exactly what unclassified_commands() sends to a person."""
        steps = [WRITE, READ, NO_COMMAND, UNKNOWN, BLOCKED]
        unknown = [s for s, t in zip(steps, step_tiers(steps)) if t == "unknown"]
        assert len(unknown) == len(unclassified_commands(steps)) == 2


@pytest.fixture
def client(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/tiers.db"
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    models_mod._engine = None


def _plan(steps):
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status="fix_planned", resource_id="i-1")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s",
                       status="pending_approval", steps=steps)
        s.add(plan); s.flush()
        from agenticops.services.plan_content import stamp_content
        stamp_content(s, plan); s.commit()
        return plan.id, issue.id, plan.content_hash
    finally:
        s.close()


def test_the_plan_response_carries_one_tier_per_step(client):
    pid, iid, _ = _plan([WRITE, READ, NO_COMMAND, UNKNOWN])
    want = ["write", "readonly", "unknown", "unknown"]
    assert client.get(f"/api/fix-plans/{pid}").json()["step_tiers"] == want
    assert client.get("/api/fix-plans?kind=fix").json()[0]["step_tiers"] == want
    assert client.get(f"/api/health-issues/{iid}/fix-plans").json()[0]["step_tiers"] == want


def test_a_plan_without_steps_has_no_tiers(client):
    pid, _, _ = _plan([])
    assert client.get(f"/api/fix-plans/{pid}").json()["step_tiers"] == []


def test_the_tiers_are_not_part_of_the_content_an_approval_is_bound_to(client):
    """Same steps → same hash, with or without the response field; and a client cannot write the field."""
    pid, _, content_hash = _plan([WRITE])
    body = client.get(f"/api/fix-plans/{pid}").json()
    assert body["content_hash"] == content_hash
    s = get_session()
    try:
        assert "step_tiers" not in FixPlan.__table__.columns        # computed on the way out, never stored
        from agenticops.services.plan_content import current_hash
        assert current_hash(s, s.get(FixPlan, pid)) == content_hash
    finally:
        s.close()
    refused = client.put(f"/api/fix-plans/{pid}", json={"content_hash": content_hash, "step_tiers": ["readonly"]})
    assert refused.status_code == 422                               # the update body takes no such field
    assert client.get(f"/api/fix-plans/{pid}").json()["step_tiers"] == ["write"]
