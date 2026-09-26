"""authz — the single authorization checkpoint (MVP-2.6.0).

check(actor, permission, subject) evaluates config/rbac.yaml:
  1. matrix: required flags ⊆ actor flags (users.permissions for user actors, `subjects` for others)
  2. rules:  structured deny rules. THREE types:
             - actor_must_differ_from_field       — str(actor) != subject.<field> (SoD, e.g. approver ≠ requester)
             - actor_must_match_field_unless_admin — actor.key must equal subject.<field>, unless the actor has
                                                     admin (e.g. only the requester or an admin may cancel/clarify)
             - deny_actor_kind_when_risk_in        — an actor kind may not act above a risk ceiling
             The two field rules need identities, so both are skipped for the anonymous `web` actor
             (api_auth_enabled=false). EVERY rule bearing on the permission is evaluated and an
             `enforce: always` deny wins over a shadow deny. A rule cannot be evaluated without its subject,
             so a permission that has a matching rule is denied (fail-closed) when `subject is None`.
Denials raise AuthzDenied when settings.rbac_enforce is true OR the matching rule says
`enforce: always`; otherwise (shadow mode) the denial is written to audit_logs as
`authz.denied_shadow` and the call is allowed — i.e. behavior is exactly today's.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agenticops.auth.actor import Actor

logger = logging.getLogger(__name__)

PERMISSIONS = (
    "change.request", "change.review", "change.approve", "change.reject", "change.cancel", "change.clarify",
    "change.execute", "plan.approve", "plan.reject", "plan.execute", "plan.edit", "audit.read",
)

_RULE_TYPES = {"actor_must_differ_from_field", "actor_must_match_field_unless_admin", "deny_actor_kind_when_risk_in"}
_TOP_LEVEL_KEYS = {"version", "permissions", "subjects", "rules"}
_RULE_KEYS = {"name", "type", "permission", "field", "actor_kind", "risk_levels", "enforce"}

DEFAULT_POLICY: dict = {
    "version": 1,
    "permissions": {
        "change.request": ["read"], "change.review": ["write"], "change.approve": ["write"],
        "change.reject": ["write"], "change.cancel": ["write"], "change.clarify": ["read"],
        "change.execute": ["write"], "plan.approve": ["write"], "plan.reject": ["write"],
        "plan.execute": ["write"], "plan.edit": ["write"], "audit.read": ["admin"],
    },
    "subjects": {
        "anonymous": ["read", "write", "admin"], "cli": ["read", "write", "admin"],
        "agents": ["read", "write"], "im": ["read"], "webhook": ["read"],
    },
    "rules": [
        {"name": "sod-change-approver-not-requester", "permission": "change.approve",
         "type": "actor_must_differ_from_field", "field": "requested_by"},
        {"name": "requester-or-admin", "permission": ["change.cancel", "change.clarify"],
         "type": "actor_must_match_field_unless_admin", "field": "requested_by"},
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
        """Returns (allowed, reason, rule_name, always_enforce).

        Every rule whose `permission` covers the request is evaluated. If any denying rule is
        `enforce: always`, THAT deny is returned (a shadow-only deny listed earlier must never mask
        it); otherwise the first deny; otherwise allowed. A rule needs its subject to be evaluated,
        so `subject is None` denies (fail-closed) with that rule's own enforce flag.
        """
        required = set(self.permissions.get(permission, ["admin"]))
        have = self.effective_permissions(actor)
        if not required.issubset(have):
            missing = ", ".join(sorted(required - have))
            return False, f"missing permission flag(s): {missing}", None, False
        denies: list[tuple[str, Optional[str], bool]] = []  # (reason, rule_name, always)
        for rule in self.rules:
            perms = rule.get("permission")
            perms = [perms] if isinstance(perms, str) else list(perms or [])
            if permission not in perms:
                continue
            name = rule.get("name")
            always = rule.get("enforce") == "always"
            rtype = rule.get("type")
            if rtype in ("actor_must_differ_from_field", "actor_must_match_field_unless_admin") and actor.kind == "web":
                # Both field rules are only evaluable between IDENTIFIED actors; the anonymous web actor
                # (api_auth_enabled=false) has no identity — enable auth to enforce them on the web.
                continue
            if subject is None:
                denies.append((f"subject required to evaluate rule {name}", name, always))
                continue
            if rtype == "actor_must_differ_from_field":
                other = getattr(subject, rule.get("field", ""), None)
                if other and str(other) == actor.key:
                    denies.append((f"separation of duties: actor equals {rule.get('field')}", name, always))
            elif rtype == "actor_must_match_field_unless_admin":
                # ownership rule: the actor must BE the subject's <field> (e.g. the requester) — an admin overrides.
                # A missing/empty field is falsy, so a non-admin is denied (fail-closed: no requester ⇒ admin-only).
                if "admin" in self.effective_permissions(actor):
                    continue
                other = getattr(subject, rule.get("field", ""), None)
                if not (other and str(other) == actor.key):
                    denies.append((f"only the requester or an admin may {permission}", name, always))
            elif rtype == "deny_actor_kind_when_risk_in":
                risk = getattr(subject, "risk_level", None)
                if actor.kind == rule.get("actor_kind") and risk in (rule.get("risk_levels") or []):
                    denies.append((f"{actor.kind} actors may not {permission} at risk {risk}", name, always))
        if denies:
            reason, name, always = next((d for d in denies if d[2]), denies[0])
            return False, reason, name, always
        return True, "allowed", None, False


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def validate_rbac(data: Any) -> list[str]:
    """Strict schema check. ANY error rejects the whole file (load() then uses DEFAULT_POLICY):
    a file that is partly misread — an inert rule, a typo'd key, a YAML boolean where the string
    "always" was meant — must not half-apply."""
    if not isinstance(data, dict):
        return ["rbac file must be a mapping"]
    errors: list[str] = []
    errors.extend(f"unknown top-level key {key!r}" for key in data if key not in _TOP_LEVEL_KEYS)
    for section in ("permissions", "subjects"):
        mapping = data.get(section)
        if not isinstance(mapping, dict) or not mapping:
            errors.append(f"'{section}' must be a non-empty mapping")
            continue
        for key, flags in mapping.items():
            if not _is_str_list(flags):
                errors.append(f"{section}.{key}: must be a list of strings, got {flags!r}")
            if section == "permissions" and key not in PERMISSIONS:
                errors.append(f"permissions.{key}: unknown permission")
    rules = data.get("rules")
    if rules is None:
        rules = []
    if not isinstance(rules, list):
        errors.append("'rules' must be a list")
        rules = []
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rules[{i}]: must be a mapping")
            continue
        name = rule.get("name")
        label = name if isinstance(name, str) and name else f"rules[{i}]"
        if not (isinstance(name, str) and name):
            errors.append(f"{label}: 'name' is required")
        errors.extend(f"{label}: unknown key {key!r}" for key in rule if key not in _RULE_KEYS)
        rtype = rule.get("type")
        if rtype not in _RULE_TYPES:
            errors.append(f"{label}: unknown rule type {rtype!r}")
        perms = rule.get("permission")
        perms = [perms] if isinstance(perms, str) else perms
        if not perms or not _is_str_list(perms):
            errors.append(f"{label}: 'permission' must be a string or a non-empty list of strings")
        else:
            errors.extend(f"{label}: unknown permission {p!r}" for p in perms if p not in PERMISSIONS)
        if rtype in ("actor_must_differ_from_field", "actor_must_match_field_unless_admin") and not (isinstance(rule.get("field"), str) and rule.get("field")):
            errors.append(f"{label}: 'field' (string) is required")
        if rtype == "deny_actor_kind_when_risk_in":
            if not (isinstance(rule.get("actor_kind"), str) and rule.get("actor_kind")):
                errors.append(f"{label}: 'actor_kind' (string) is required")
            if not rule.get("risk_levels") or not _is_str_list(rule.get("risk_levels")):
                errors.append(f"{label}: 'risk_levels' (non-empty list of strings) is required")
        if "enforce" in rule and rule["enforce"] != "always":
            errors.append(f"{label}: 'enforce' must be the string \"always\" (got {rule['enforce']!r}; a YAML boolean is not accepted)")
    return errors


_policy: Optional[RbacPolicy] = None
_policy_lock = threading.Lock()


def get_rbac_policy(reload: bool = False) -> RbacPolicy:
    global _policy
    with _policy_lock:
        if _policy is None or reload:
            _policy = RbacPolicy.load()
        return _policy


_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _entity_type_for(subject: Any) -> str:
    """Audit entity_type in the EntityTypes vocabulary: FixPlan → fix_plan, ChangeRequest → change_request,
    any other class → snake_case of its name, no subject → system."""
    from agenticops.audit.service import EntityTypes
    if subject is None:
        return EntityTypes.SYSTEM
    name = type(subject).__name__
    by_class = {"FixPlan": EntityTypes.FIX_PLAN, "ChangeRequest": EntityTypes.CHANGE_REQUEST}
    return by_class.get(name) or _CAMEL_BOUNDARY.sub("_", name).lower()


def _audit_denial(actor: Actor, permission: str, reason: str, rule: Optional[str], subject: Any, enforced: bool,
                  details: Optional[dict] = None) -> None:
    """Write the denial to audit_logs — in shadow mode this row is the ONLY artefact of the decision.
    `details` (caller context such as claimed_name / context_actor) is merged in; the decision keys win."""
    try:
        from agenticops.audit.service import AuditService
        AuditService.log(
            action="authz.denied" if enforced else "authz.denied_shadow",
            entity_type=_entity_type_for(subject), entity_id=str(getattr(subject, "id", "") or "-"),
            actor=actor.key, user_id=actor.user_id,
            details={**(details or {}), "permission": permission, "reason": reason, "rule": rule},
        )
    except Exception:
        logger.warning("authz audit write failed: %s denied %s (%s, rule=%s)",
                       actor.key, permission, reason, rule, exc_info=True)


def check(actor: Actor, permission: str, subject: Any = None, *, details: Optional[dict] = None) -> None:
    """Raise AuthzDenied when denied under enforce (or an always-enforced rule); shadow otherwise.
    `details` is extra context recorded on the denial audit row (e.g. the claimed name behind a check)."""
    from agenticops.config import settings
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")
    allowed, reason, rule, always = get_rbac_policy().decide(actor, permission, subject)
    if allowed:
        return
    enforced = bool(settings.rbac_enforce) or always
    _audit_denial(actor, permission, reason, rule, subject, enforced, details)
    if enforced:
        raise AuthzDenied(actor.key, permission, reason, rule)
    logger.info("authz shadow: %s would be denied %s (%s)", actor.key, permission, reason)
