"""Actor resolution + rbac.yaml matrix + shadow/enforce semantics (MVP-2.6.0 S1)."""
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from agenticops.auth.actor import (
    Actor, actor_from_request, actor_from_run_context, agent_actor, cli_actor, im_actor, parse_actor,
    web_anonymous_actor,
)
from agenticops.auth.authz import DEFAULT_POLICY, AuthzDenied, RbacPolicy, check, get_rbac_policy, validate_rbac
from agenticops.run_context import RunContext


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

    def test_parse_actor_rejects_empty_kind_or_id(self):
        # a key with an empty kind or an empty id is not a valid key — legacy free text, never a claimed kind
        assert parse_actor("cli:") == Actor("web", "cli:")
        assert parse_actor(":x") == Actor("web", ":x")
        assert parse_actor("") == Actor("web", "anonymous")

    def test_from_request_intersects_api_key_permissions(self):
        """I-5 (spec §3.3 row 1): on API-key auth the middleware leaves the key on request.state and the actor's
        flags are the OWNER's ∩ the KEY's — a read-only key never carries its owner's write/admin."""
        user = SimpleNamespace(id=5, email="admin", permissions=["read", "write", "admin"])
        req = SimpleNamespace(state=SimpleNamespace(user=user, api_key=SimpleNamespace(permissions=["read"])))
        a = actor_from_request(req)
        assert (a.kind, a.id, a.user_id, a.permissions) == ("user", "admin", 5, ("read",))
        # a key can never GRANT a flag its owner lacks
        owner_rw = SimpleNamespace(id=6, email="rw", permissions=["read", "write"])
        req = SimpleNamespace(state=SimpleNamespace(user=owner_rw, api_key=SimpleNamespace(permissions=["read", "admin"])))
        assert actor_from_request(req).permissions == ("read",)
        # a key without permissions (default create_api_key → ["read"] happens upstream; None here) grants nothing
        req = SimpleNamespace(state=SimpleNamespace(user=user, api_key=SimpleNamespace(permissions=None)))
        assert actor_from_request(req).permissions == ()
        # session auth (no api_key on state) is unchanged
        assert actor_from_request(SimpleNamespace(state=SimpleNamespace(user=user))).permissions == ("read", "write", "admin")

    def test_actor_from_run_context_rebuilds_user_with_permissions(self):
        # Task 9 agent tools rebuild the actor from the Run Context; without the permission flags every
        # authenticated user would fail the rbac matrix (shadow-denied) — the flags must round-trip.
        ctx = RunContext(actor="user:alice", actor_user_id=3, actor_permissions=("read", "write"))
        a = actor_from_run_context(ctx)
        assert (a.kind, a.id, a.user_id) == ("user", "alice", 3)
        assert "read" in a.permissions and "write" in a.permissions


@pytest.fixture
def policy():
    return get_rbac_policy(reload=True)


class TestMatrix:
    def test_default_file_loads(self, policy):
        assert policy.permissions["change.approve"] == ["write"]
        assert "anonymous" in policy.subjects

    def test_user_needs_write_to_approve(self, policy):
        cr = SimpleNamespace(requested_by="user:someone-else", risk_level="L1")  # approve needs a subject (fail-closed)
        reader = Actor("user", "ro", permissions=("read",))
        allowed, reason, _, _ = policy.decide(reader, "change.approve", cr)
        assert allowed is False and "write" in reason
        writer = Actor("user", "rw", permissions=("read", "write"))
        assert policy.decide(writer, "change.approve", cr)[0] is True

    def test_anonymous_can_do_everything_like_today(self, policy):
        cr = SimpleNamespace(requested_by="web:anonymous", risk_level="L3")  # even self-requested, even L3
        for perm in ("change.request", "change.approve", "plan.execute", "audit.read"):
            assert policy.decide(web_anonymous_actor(), perm, cr)[0] is True

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

    def test_sod_skipped_for_anonymous_web_actor(self, policy):
        cr = SimpleNamespace(requested_by="web:anonymous", risk_level="L1")
        allowed, _, rule, _ = policy.decide(web_anonymous_actor(), "change.approve", cr)
        assert allowed is True and rule is None

    def test_sod_still_applies_to_identified_actors(self, policy):
        cr = SimpleNamespace(requested_by="cli:malibo", risk_level="L1")
        with patch("getpass.getuser", return_value="malibo"):
            allowed, _, rule, _ = policy.decide(cli_actor(), "change.approve", cr)
        assert allowed is False and rule == "sod-change-approver-not-requester"

    def test_agent_cannot_approve_l2_l3_and_this_is_always_enforced(self, policy):
        plan = SimpleNamespace(risk_level="L2", requested_by=None)
        allowed, _, rule, always = policy.decide(agent_actor("sre"), "plan.approve", plan)
        assert allowed is False and rule == "no-agent-approval-above-l1" and always is True
        plan_l1 = SimpleNamespace(risk_level="L1", requested_by=None)
        assert policy.decide(agent_actor("auto-pipeline"), "plan.approve", plan_l1)[0] is True

    def test_always_enforced_rule_wins_over_shadow_deny(self, policy):
        # agent:sre approving its OWN L3 change matches both rules; the always-enforced ceiling must be
        # the returned deny — a shadow-only SoD deny listed first must never mask it
        cr = SimpleNamespace(requested_by="agent:sre", risk_level="L3")
        allowed, _, rule, always = policy.decide(agent_actor("sre"), "change.approve", cr)
        assert (allowed, rule, always) == (False, "no-agent-approval-above-l1", True)

    def test_subject_required_for_rule_bearing_permissions(self, policy):
        # a permission that has a matching rule cannot be evaluated without its subject → fail-closed
        allowed, reason, rule, always = policy.decide(agent_actor("sre"), "plan.approve", None)
        assert allowed is False and always is True and "subject required" in reason
        assert rule == "no-agent-approval-above-l1"
        # permissions with no matching rule keep working without a subject
        assert policy.decide(cli_actor(), "change.request", None)[0] is True

    def test_bad_file_falls_back_to_defaults(self, tmp_path):
        bad = tmp_path / "rbac.yaml"
        bad.write_text("rules:\n  - name: x\n    permission: change.approve\n    type: no_such_rule\n")
        p = RbacPolicy.load(bad)
        assert p.permissions["change.approve"] == ["write"]  # defaults, not the broken file


_VALID_RBAC = """\
version: 1
permissions:
  change.request: [read]
  change.approve: [admin]   # deliberately differs from DEFAULT_POLICY (write): accepting the file is visible
  plan.approve: [write]
subjects:
  anonymous: [read, write, admin]
  cli: [read, write, admin]
  agents: [read, write]
  im: [read]
  webhook: [read]
rules:
  - name: sod
    permission: change.approve
    type: actor_must_differ_from_field
    field: requested_by
  - name: ceiling
    permission: [plan.approve, change.approve]
    type: deny_actor_kind_when_risk_in
    actor_kind: agent
    risk_levels: [L2, L3]
    enforce: always
"""

# variant name → (unique anchor in _VALID_RBAC, replacement) — one poison per file
_BAD_RBAC_VARIANTS = {
    "enforce-yaml-boolean": ("    enforce: always\n", "    enforce: true\n"),
    "typoed-rule-permission": ("    permission: change.approve\n    type: actor_must_differ_from_field\n",
                               "    permission: change.aprove\n    type: actor_must_differ_from_field\n"),
    "missing-field": ("    field: requested_by\n", ""),
    "scalar-flag-value": ("  change.request: [read]\n", "  change.request: read\n"),
    "top-level-key-typo": ("rules:\n", "rule:\n"),
    "unknown-rule-key": ("    enforce: always\n", "    enforce_always: true\n"),
}


def _defaults_loaded(p: RbacPolicy) -> bool:
    return (p.permissions == DEFAULT_POLICY["permissions"]
            and p.subjects == DEFAULT_POLICY["subjects"]
            and p.rules == DEFAULT_POLICY["rules"])


class TestValidation:
    def test_valid_custom_file_is_accepted(self, tmp_path):
        f = tmp_path / "rbac.yaml"
        f.write_text(_VALID_RBAC)
        p = RbacPolicy.load(f)
        assert p.permissions["change.approve"] == ["admin"]  # the file, not the defaults
        assert [r["name"] for r in p.rules] == ["sod", "ceiling"]

    @pytest.mark.parametrize("variant", sorted(_BAD_RBAC_VARIANTS))
    def test_bad_file_is_rejected_whole_and_defaults_load(self, tmp_path, variant):
        old, new = _BAD_RBAC_VARIANTS[variant]
        assert _VALID_RBAC.count(old) == 1, f"fixture anchor for {variant} must be unique"
        bad = tmp_path / "rbac.yaml"
        bad.write_text(_VALID_RBAC.replace(old, new))
        assert validate_rbac(yaml.safe_load(bad.read_text())) != []
        assert _defaults_loaded(RbacPolicy.load(bad))

    def test_shipped_file_and_builtin_defaults_validate(self):
        from agenticops.config import PROJECT_ROOT
        data = yaml.safe_load((PROJECT_ROOT / "config" / "rbac.yaml").read_text(encoding="utf-8"))
        assert validate_rbac(data) == []
        assert validate_rbac(DEFAULT_POLICY) == []


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

    def test_read_only_api_key_cannot_approve_under_enforce(self, policy):
        """I-5: user [read, write, admin] + key [read] → plan.approve is denied under rbac_enforce; the same user
        through session auth is allowed."""
        from agenticops.config import settings
        user = SimpleNamespace(id=5, email="admin", permissions=["read", "write", "admin"])
        plan = SimpleNamespace(id=1, risk_level="L1", requested_by=None)
        via_key = actor_from_request(SimpleNamespace(state=SimpleNamespace(user=user, api_key=SimpleNamespace(permissions=["read"]))))
        via_session = actor_from_request(SimpleNamespace(state=SimpleNamespace(user=user)))
        with patch.object(settings, "rbac_enforce", True), \
             patch("agenticops.audit.service.AuditService.log") as log:
            with pytest.raises(AuthzDenied) as ei:
                check(via_key, "plan.approve", subject=plan)
            check(via_session, "plan.approve", subject=plan)  # unchanged
        assert "write" in ei.value.reason and ei.value.actor == "user:admin"
        assert log.call_count == 1 and log.call_args.kwargs["action"] == "authz.denied"

    def test_current_actor_stamps_intersected_permissions_on_run_context(self):
        """The web dependency carries the intersected flags onto the Run Context, so agent tools rebuilding the
        actor from it (approve_fix_plan) see the key's ceiling too."""
        import asyncio
        from agenticops.run_context import get_run_context, run_context
        from agenticops.web.deps import current_actor
        user = SimpleNamespace(id=5, email="admin", permissions=["read", "write"])
        req = SimpleNamespace(state=SimpleNamespace(user=user, api_key=SimpleNamespace(permissions=["read"])))

        async def go():
            actor = await current_actor(req)
            return actor, get_run_context()

        with run_context():
            actor, ctx = asyncio.run(go())
        assert actor.permissions == ("read",) and ctx.actor_permissions == ("read",) and ctx.actor == "user:admin"

    def test_allowed_is_silent(self, policy):
        with patch("agenticops.audit.service.AuditService.log") as log:
            check(cli_actor(), "change.request")
        assert not log.called

    def test_audit_entity_type_uses_entity_types_vocabulary(self, policy):
        from agenticops.config import settings

        class FixPlan(SimpleNamespace):  # same class NAME as the ORM model; no DB session needed
            pass

        plan = FixPlan(id=7, requested_by="user:alice", risk_level="L1")
        alice = Actor("user", "alice", permissions=("read", "write"))
        with patch.object(settings, "rbac_enforce", False), \
             patch("agenticops.audit.service.AuditService.log") as log:
            check(alice, "change.approve", subject=plan)
        assert log.call_args.kwargs["entity_type"] == "fix_plan"
        assert log.call_args.kwargs["entity_id"] == "7"

    def test_entity_type_mapping(self):
        from agenticops.auth.authz import _entity_type_for
        from agenticops.audit.service import EntityTypes

        class ChangeRequest(SimpleNamespace):
            pass

        class HealthIssue(SimpleNamespace):
            pass

        assert _entity_type_for(ChangeRequest()) == EntityTypes.CHANGE_REQUEST == "change_request"
        assert _entity_type_for(HealthIssue()) == "health_issue"
        assert _entity_type_for(None) == "system"

    def test_audit_write_failure_is_warned_not_hidden(self, policy, caplog):
        from agenticops.config import settings
        cr = SimpleNamespace(id=1, requested_by="user:alice", risk_level="L1")
        alice = Actor("user", "alice", permissions=("read", "write"))
        with patch.object(settings, "rbac_enforce", False), \
             patch("agenticops.audit.service.AuditService.log", side_effect=RuntimeError("db down")), \
             caplog.at_level(logging.WARNING, logger="agenticops.auth.authz"):
            check(alice, "change.approve", subject=cr)  # shadow mode: still allowed
        assert any(r.levelno == logging.WARNING and "authz audit write failed" in r.getMessage()
                   for r in caplog.records)
