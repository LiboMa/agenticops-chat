"""Actor resolution + rbac.yaml matrix + shadow/enforce semantics (MVP-2.6.0 S1)."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agenticops.auth.actor import (
    Actor, actor_from_request, agent_actor, cli_actor, im_actor, parse_actor, web_anonymous_actor,
)
from agenticops.auth.authz import AuthzDenied, RbacPolicy, check, get_rbac_policy


class TestActor:
    def test_key_format(self):
        assert Actor("cli", "malibo").key == "cli:malibo"
        assert im_actor("feishu", "ou_1").key == "im:feishu:ou_1"
        assert agent_actor("auto-pipeline").key == "agent:auto-pipeline"

    def test_from_request_uses_state_user(self):
        user = SimpleNamespace(id=5, email="admin", permissions=["read", "write", "admin"])
        req = SimpleNamespace(state=SimpleNamespace(user=user))
        a = actor_from_request(req)
        assert (a.kind, a.id, a.user_id) == ("user", "admin", 5)
        assert "admin" in a.permissions

    def test_from_request_without_user_is_anonymous(self):
        req = SimpleNamespace(state=SimpleNamespace())
        assert actor_from_request(req) == web_anonymous_actor()

    def test_cli_actor_uses_os_user(self):
        with patch("getpass.getuser", return_value="malibo"):
            assert cli_actor().key == "cli:malibo"

    def test_parse_roundtrip(self):
        assert parse_actor("cli:malibo") == Actor("cli", "malibo")
        assert parse_actor("im:feishu:ou_1") == Actor("im", "feishu:ou_1")
        assert parse_actor("web-user") == Actor("web", "web-user")


@pytest.fixture
def policy():
    return get_rbac_policy(reload=True)


class TestMatrix:
    def test_default_file_loads(self, policy):
        assert policy.permissions["change.approve"] == ["write"]
        assert "anonymous" in policy.subjects

    def test_user_needs_write_to_approve(self, policy):
        reader = Actor("user", "ro", permissions=("read",))
        allowed, reason, _, _ = policy.decide(reader, "change.approve", None)
        assert allowed is False and "write" in reason
        writer = Actor("user", "rw", permissions=("read", "write"))
        assert policy.decide(writer, "change.approve", None)[0] is True

    def test_anonymous_can_do_everything_like_today(self, policy):
        for perm in ("change.request", "change.approve", "plan.execute", "audit.read"):
            assert policy.decide(web_anonymous_actor(), perm, None)[0] is True

    def test_im_can_only_request(self, policy):
        im = im_actor("feishu", "ou_1")
        assert policy.decide(im, "change.request", None)[0] is True
        assert policy.decide(im, "change.approve", None)[0] is False

    def test_sod_rule_denies_self_approval(self, policy):
        cr = SimpleNamespace(requested_by="user:alice", risk_level="L1")
        alice = Actor("user", "alice", permissions=("read", "write"))
        allowed, reason, rule, always = policy.decide(alice, "change.approve", cr)
        assert allowed is False and rule == "sod-change-approver-not-requester" and always is False
        bob = Actor("user", "bob", permissions=("read", "write"))
        assert policy.decide(bob, "change.approve", cr)[0] is True

    def test_agent_cannot_approve_l2_l3_and_this_is_always_enforced(self, policy):
        plan = SimpleNamespace(risk_level="L2", requested_by=None)
        allowed, _, rule, always = policy.decide(agent_actor("sre"), "plan.approve", plan)
        assert allowed is False and rule == "no-agent-approval-above-l1" and always is True
        plan_l1 = SimpleNamespace(risk_level="L1", requested_by=None)
        assert policy.decide(agent_actor("auto-pipeline"), "plan.approve", plan_l1)[0] is True

    def test_bad_file_falls_back_to_defaults(self, tmp_path):
        bad = tmp_path / "rbac.yaml"
        bad.write_text("rules:\n  - name: x\n    permission: change.approve\n    type: no_such_rule\n")
        p = RbacPolicy.load(bad)
        assert p.permissions["change.approve"] == ["write"]  # defaults, not the broken file


class TestCheck:
    def test_shadow_mode_allows_but_audits(self, policy):
        from agenticops.config import settings
        cr = SimpleNamespace(id=1, requested_by="user:alice", risk_level="L1")
        alice = Actor("user", "alice", permissions=("read", "write"))
        with patch.object(settings, "rbac_enforce", False), \
             patch("agenticops.audit.service.AuditService.log") as log:
            check(alice, "change.approve", subject=cr)  # no raise
        assert log.called
        assert log.call_args.kwargs["action"] == "authz.denied_shadow"

    def test_enforce_mode_raises(self, policy):
        from agenticops.config import settings
        cr = SimpleNamespace(id=1, requested_by="user:alice", risk_level="L1")
        alice = Actor("user", "alice", permissions=("read", "write"))
        with patch.object(settings, "rbac_enforce", True), \
             patch("agenticops.audit.service.AuditService.log"):
            with pytest.raises(AuthzDenied) as ei:
                check(alice, "change.approve", subject=cr)
        assert ei.value.permission == "change.approve"

    def test_always_enforced_rule_raises_even_in_shadow(self, policy):
        from agenticops.config import settings
        plan = SimpleNamespace(id=2, risk_level="L3", requested_by=None)
        with patch.object(settings, "rbac_enforce", False), \
             patch("agenticops.audit.service.AuditService.log"):
            with pytest.raises(AuthzDenied):
                check(agent_actor("sre"), "plan.approve", subject=plan)

    def test_allowed_is_silent(self, policy):
        with patch("agenticops.audit.service.AuditService.log") as log:
            check(cli_actor(), "change.request")
        assert not log.called
