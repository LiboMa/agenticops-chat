"""authz — the single authorization checkpoint (MVP-2.6.0).

check(actor, permission, subject) evaluates config/rbac.yaml:
  1. matrix: required flags ⊆ actor flags (users.permissions for user actors, `subjects` for others)
  2. rules:  structured deny rules (SoD, agent risk ceiling)
Denials raise AuthzDenied when settings.rbac_enforce is true OR the matching rule says
`enforce: always`; otherwise (shadow mode) the denial is written to audit_logs as
`authz.denied_shadow` and the call is allowed — i.e. behavior is exactly today's.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agenticops.auth.actor import Actor

logger = logging.getLogger(__name__)

PERMISSIONS = (
    "change.request", "change.review", "change.approve", "change.reject", "change.cancel", "change.execute",
    "plan.approve", "plan.reject", "plan.execute", "audit.read",
)

_RULE_TYPES = {"actor_must_differ_from_field", "deny_actor_kind_when_risk_in"}

DEFAULT_POLICY: dict = {
    "version": 1,
    "permissions": {
        "change.request": ["read"], "change.review": ["write"], "change.approve": ["write"],
        "change.reject": ["write"], "change.cancel": ["write"], "change.execute": ["write"],
        "plan.approve": ["write"], "plan.reject": ["write"], "plan.execute": ["write"],
        "audit.read": ["admin"],
    },
    "subjects": {
        "anonymous": ["read", "write", "admin"], "cli": ["read", "write", "admin"],
        "agents": ["read", "write"], "im": ["read"], "webhook": ["read"],
    },
    "rules": [
        {"name": "sod-change-approver-not-requester", "permission": "change.approve",
         "type": "actor_must_differ_from_field", "field": "requested_by"},
        {"name": "no-agent-approval-above-l1", "permission": ["plan.approve", "change.approve"],
         "type": "deny_actor_kind_when_risk_in", "actor_kind": "agent", "risk_levels": ["L2", "L3"],
         "enforce": "always"},
    ],
}

_SUBJECT_KEY = {"web": "anonymous", "cli": "cli", "agent": "agents", "im": "im", "webhook": "webhook"}


class AuthzDenied(Exception):
    def __init__(self, actor: str, permission: str, reason: str, rule: Optional[str] = None):
        super().__init__(f"{actor} is not allowed to {permission}: {reason}")
        self.actor, self.permission, self.reason, self.rule = actor, permission, reason, rule


@dataclass
class RbacPolicy:
    permissions: dict[str, list[str]] = field(default_factory=dict)
    subjects: dict[str, list[str]] = field(default_factory=dict)
    rules: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "RbacPolicy":
        return cls(
            permissions=dict(data.get("permissions") or {}),
            subjects=dict(data.get("subjects") or {}),
            rules=list(data.get("rules") or []),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RbacPolicy":
        import yaml
        if path is None:
            from agenticops.config import settings
            path = settings.rbac_file
        p = Path(path)
        if not p.is_absolute():
            from agenticops.config import PROJECT_ROOT
            p = PROJECT_ROOT / p
        if not p.exists():
            logger.info("rbac file %s not found — using built-in defaults", p)
            return cls.from_dict(DEFAULT_POLICY)
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            errors = validate_rbac(data)
            if errors:
                raise ValueError("; ".join(errors))
            return cls.from_dict(data)
        except Exception as e:
            logger.error("Failed to load rbac file %s (%s) — using built-in defaults", p, e)
            return cls.from_dict(DEFAULT_POLICY)

    def effective_permissions(self, actor: Actor) -> set[str]:
        if actor.kind == "user":
            return set(actor.permissions)
        if actor.permissions:
            return set(actor.permissions)
        return set(self.subjects.get(_SUBJECT_KEY.get(actor.kind, actor.kind), []))

    def decide(self, actor: Actor, permission: str, subject: Any) -> tuple[bool, str, Optional[str], bool]:
        """Returns (allowed, reason, rule_name, always_enforce)."""
        required = set(self.permissions.get(permission, ["admin"]))
        have = self.effective_permissions(actor)
        if not required.issubset(have):
            missing = ", ".join(sorted(required - have))
            return False, f"missing permission flag(s): {missing}", None, False
        for rule in self.rules:
            perms = rule.get("permission")
            perms = [perms] if isinstance(perms, str) else list(perms or [])
            if permission not in perms:
                continue
            always = str(rule.get("enforce", "")).lower() == "always"
            rtype = rule.get("type")
            if rtype == "actor_must_differ_from_field" and subject is not None:
                other = getattr(subject, rule.get("field", ""), None)
                if other and str(other) == actor.key:
                    return False, f"separation of duties: actor equals {rule.get('field')}", rule.get("name"), always
            elif rtype == "deny_actor_kind_when_risk_in" and subject is not None:
                risk = getattr(subject, "risk_level", None)
                if actor.kind == rule.get("actor_kind") and risk in (rule.get("risk_levels") or []):
                    return False, f"{actor.kind} actors may not {permission} at risk {risk}", rule.get("name"), always
        return True, "allowed", None, False


def validate_rbac(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data.get("permissions", {}), dict):
        errors.append("'permissions' must be a mapping")
    for i, rule in enumerate(data.get("rules") or []):
        label = rule.get("name") or f"rules[{i}]"
        if rule.get("type") not in _RULE_TYPES:
            errors.append(f"{label}: unknown rule type {rule.get('type')!r}")
        if not rule.get("permission"):
            errors.append(f"{label}: 'permission' is required")
    return errors


_policy: Optional[RbacPolicy] = None
_policy_lock = threading.Lock()


def get_rbac_policy(reload: bool = False) -> RbacPolicy:
    global _policy
    with _policy_lock:
        if _policy is None or reload:
            _policy = RbacPolicy.load()
        return _policy


def _audit_shadow_denial(actor: Actor, permission: str, reason: str, rule: Optional[str], subject: Any, enforced: bool) -> None:
    try:
        from agenticops.audit.service import AuditService
        entity_type = type(subject).__name__.lower() if subject is not None else "system"
        entity_id = str(getattr(subject, "id", "") or "-")
        AuditService.log(
            action="authz.denied" if enforced else "authz.denied_shadow",
            entity_type=entity_type, entity_id=entity_id, actor=actor.key, user_id=actor.user_id,
            details={"permission": permission, "reason": reason, "rule": rule},
        )
    except Exception:
        logger.debug("authz audit write failed", exc_info=True)


def check(actor: Actor, permission: str, subject: Any = None) -> None:
    """Raise AuthzDenied when denied under enforce (or an always-enforced rule); shadow otherwise."""
    from agenticops.config import settings
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")
    allowed, reason, rule, always = get_rbac_policy().decide(actor, permission, subject)
    if allowed:
        return
    enforced = bool(settings.rbac_enforce) or always
    _audit_shadow_denial(actor, permission, reason, rule, subject, enforced)
    if enforced:
        raise AuthzDenied(actor.key, permission, reason, rule)
    logger.info("authz shadow: %s would be denied %s (%s)", actor.key, permission, reason)
