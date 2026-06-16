"""Governed-autonomy policy engine — declarative approval rules for fix plans.

Replaces the hardcoded ``risk_level in (L0, L1)`` auto-approve check with
rules loaded from ``config/policies.yaml``. Every decision carries the rule
that produced it and human-readable reasons, and is logged to the pipeline
event timeline — the policy file plus the decision log together form the
auditable "autonomy contract" (SOC 2 CC8.1: every automated change traces
to a pre-authorized rule).

Actions:
    auto_approve        — approve without a human (still creates audit events)
    require_human       — wait for in-app/IM human approval (legacy default)
    require_itsm_change — gate on an external ITSM change request approval
    block               — never execute (e.g., inside a change freeze)
    escalate            — re-evaluate as one risk tier higher

Fail-closed: a missing/invalid policy file falls back to built-in defaults
that replicate the historical behavior exactly; an unmatchable input falls
through to the configured default action (require_human).
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

RISK_ORDER = ["L0", "L1", "L2", "L3", "L4"]

VALID_ACTIONS = {"auto_approve", "require_human", "require_itsm_change", "block", "escalate"}

# Replicates pre-2.0 hardcoded behavior: L0/L1 auto, everything else human.
DEFAULT_POLICY: dict = {
    "version": 1,
    "defaults": {"action": "require_human"},
    "rules": [
        {
            "name": "auto-approve-low-risk",
            "match": {"risk_level": ["L0", "L1"]},
            "action": "auto_approve",
            "itsm_change_type": "standard",
        },
    ],
}


@dataclass
class PolicyDecision:
    """Outcome of a policy evaluation — attached to the audit timeline."""

    action: str
    rule_name: str
    reasons: list[str] = field(default_factory=list)
    itsm_change_type: Optional[str] = None
    effective_risk_level: Optional[str] = None
    escalated_from: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "rule": self.rule_name,
            "reasons": self.reasons,
            "itsm_change_type": self.itsm_change_type,
            "effective_risk_level": self.effective_risk_level,
            "escalated_from": self.escalated_from,
        }


def _bump_risk(risk_level: str) -> str:
    try:
        idx = RISK_ORDER.index(risk_level)
    except ValueError:
        return risk_level
    return RISK_ORDER[min(idx + 1, len(RISK_ORDER) - 1)]


class PolicyEngine:
    """Evaluates fix-plan approval policy rules in declaration order."""

    def __init__(self, policy: dict):
        self.policy = policy or DEFAULT_POLICY
        self.rules = self.policy.get("rules") or []
        defaults = self.policy.get("defaults") or {}
        self.default_action = defaults.get("action", "require_human")
        if self.default_action not in VALID_ACTIONS:
            logger.warning(
                "policy defaults.action %r invalid — using require_human",
                self.default_action,
            )
            self.default_action = "require_human"

    # ── Loading ──────────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path | None = None) -> "PolicyEngine":
        """Load policies.yaml; fall back to built-in defaults on any error."""
        import yaml

        if path is None:
            from agenticops.config import settings
            path = settings.policy_file
        p = Path(path)
        if not p.is_absolute():
            from agenticops.config import PROJECT_ROOT
            p = PROJECT_ROOT / p
        if not p.exists():
            logger.info("policy file %s not found — using built-in defaults", p)
            return cls(DEFAULT_POLICY)
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
                raise ValueError("policy file must be a mapping with a 'rules' list")
            errors = validate_policy(data)
            if errors:
                raise ValueError("; ".join(errors))
            return cls(data)
        except Exception as e:
            logger.error("Failed to load policy file %s (%s) — using built-in defaults", p, e)
            return cls(DEFAULT_POLICY)

    # ── Evaluation ───────────────────────────────────────────────────

    def evaluate(
        self,
        *,
        risk_level: str,
        severity: Optional[str] = None,
        provider: Optional[str] = None,
        resource_id: Optional[str] = None,
        blast_radius: Optional[int] = None,
        impact_severity: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> PolicyDecision:
        """Evaluate rules in order; first match wins. 'escalate' re-runs one tier up."""
        now = now or datetime.now(timezone.utc)
        original_risk = risk_level
        seen_levels: set[str] = set()
        fired_escalations: set[int] = set()  # each escalate rule bumps at most once

        while True:
            seen_levels.add(risk_level)
            for rule_idx, rule in enumerate(self.rules):
                if rule_idx in fired_escalations:
                    continue
                matched, reasons = self._matches(
                    rule.get("match") or {},
                    risk_level=risk_level,
                    severity=severity,
                    provider=provider,
                    resource_id=resource_id,
                    blast_radius=blast_radius,
                    impact_severity=impact_severity,
                    now=now,
                )
                if not matched:
                    continue
                action = rule.get("action", self.default_action)
                name = rule.get("name", "unnamed")
                if action == "escalate":
                    fired_escalations.add(rule_idx)
                    bumped = _bump_risk(risk_level)
                    if bumped in seen_levels:
                        # Already at top tier (or cycle) — escalate degrades to human gate
                        return PolicyDecision(
                            action="require_human",
                            rule_name=name,
                            reasons=reasons + [f"escalation from {risk_level} capped"],
                            effective_risk_level=risk_level,
                            escalated_from=original_risk if original_risk != risk_level else None,
                        )
                    risk_level = bumped
                    break  # restart rule scan at the higher tier
                return PolicyDecision(
                    action=action if action in VALID_ACTIONS else self.default_action,
                    rule_name=name,
                    reasons=reasons,
                    itsm_change_type=rule.get("itsm_change_type"),
                    effective_risk_level=risk_level,
                    escalated_from=original_risk if original_risk != risk_level else None,
                )
            else:
                # No rule matched at this tier — default action
                return PolicyDecision(
                    action=self.default_action,
                    rule_name="(default)",
                    reasons=[f"no rule matched risk_level={risk_level}"],
                    effective_risk_level=risk_level,
                    escalated_from=original_risk if original_risk != risk_level else None,
                )

    def _matches(
        self,
        match: dict,
        *,
        risk_level: str,
        severity: Optional[str],
        provider: Optional[str],
        resource_id: Optional[str],
        blast_radius: Optional[int],
        impact_severity: Optional[str] = None,
        now: datetime,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        levels = match.get("risk_level")
        if levels is not None:
            if risk_level not in levels:
                return False, []
            reasons.append(f"risk_level={risk_level}")

        severities = match.get("severity")
        if severities is not None:
            if severity not in severities:
                return False, []
            reasons.append(f"severity={severity}")

        providers = match.get("provider")
        if providers is not None:
            if provider not in providers:
                return False, []
            reasons.append(f"provider={provider}")

        pattern = match.get("resource_pattern")
        if pattern is not None:
            if not resource_id or not re.search(pattern, resource_id):
                return False, []
            reasons.append(f"resource matches {pattern!r}")

        br_gte = match.get("blast_radius_gte")
        if br_gte is not None:
            if blast_radius is None or blast_radius < br_gte:
                return False, []
            reasons.append(f"blast_radius={blast_radius} >= {br_gte}")

        impact_severities = match.get("impact_severity")
        if impact_severities is not None:
            if impact_severity not in impact_severities:
                return False, []
            reasons.append(f"simulated impact_severity={impact_severity}")

        if match.get("in_change_freeze"):
            window = self._active_freeze_window(now)
            if window is None:
                return False, []
            reasons.append(f"inside change freeze '{window}'")

        if not match:
            reasons.append("match-all rule")

        return True, reasons

    def _active_freeze_window(self, now: datetime) -> Optional[str]:
        """Return the name of the freeze window containing `now`, if any."""
        for window in self.policy.get("freeze_windows") or []:
            try:
                start = datetime.fromisoformat(str(window["start"]).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(window["end"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                logger.warning("Skipping malformed freeze window: %r", window)
                continue
            if start <= now <= end:
                return window.get("name", f"{start.isoformat()}..{end.isoformat()}")
        return None


def validate_policy(data: dict) -> list[str]:
    """Static validation of a policy document. Returns a list of error strings."""
    errors: list[str] = []
    for i, rule in enumerate(data.get("rules") or []):
        label = rule.get("name") or f"rules[{i}]"
        action = rule.get("action")
        if action not in VALID_ACTIONS:
            errors.append(f"{label}: invalid action {action!r}")
        match = rule.get("match")
        if match is not None and not isinstance(match, dict):
            errors.append(f"{label}: 'match' must be a mapping")
        pattern = (match or {}).get("resource_pattern")
        if pattern:
            try:
                re.compile(pattern)
            except re.error as e:
                errors.append(f"{label}: bad resource_pattern: {e}")
    defaults = data.get("defaults") or {}
    if defaults.get("action") and defaults["action"] not in VALID_ACTIONS:
        errors.append(f"defaults.action invalid: {defaults['action']!r}")
    return errors


# ── Singleton accessor (reloadable) ─────────────────────────────────

_engine: Optional[PolicyEngine] = None
_engine_lock = threading.Lock()


def get_policy_engine(reload: bool = False) -> PolicyEngine:
    global _engine
    with _engine_lock:
        if _engine is None or reload:
            _engine = PolicyEngine.from_yaml()
        return _engine


# ── Blast-radius helper (graph engine, fail-soft) ───────────────────


def _find_graph_node(resource_id: str, account_id: Optional[str] = None) -> Optional[str]:
    """Find the graph node ID for a resource, optionally scoped to one account.

    Account scoping prevents cross-account resource-ID collisions from feeding
    the wrong topology into policy decisions (graph_nodes.account_id stores the
    cloud-native account number, e.g. the AWS 12-digit ID).
    """
    from agenticops.graph.store import GraphStore

    hits = GraphStore().search_nodes(query=resource_id, limit=10)
    if account_id:
        hits = [h for h in hits if not h.get("account_id") or h["account_id"] == account_id]
    if not hits:
        return None
    # Prefer exact ID match over substring match
    for h in hits:
        if h["id"] == resource_id:
            return h["id"]
    return hits[0]["id"]


def estimate_blast_radius(
    resource_id: Optional[str], account_id: Optional[str] = None
) -> Optional[int]:
    """Count downstream-affected nodes for a resource via the infra graph.

    Returns None when the graph is unavailable or the resource isn't in it —
    policy rules using blast_radius_gte simply don't match in that case.
    """
    if not resource_id:
        return None
    try:
        from agenticops.graph.store import GraphStore
        from agenticops.graph.algorithms import impact_analysis

        node_id = _find_graph_node(resource_id, account_id)
        if not node_id:
            return None
        neighborhood = GraphStore().get_node_neighborhood(node_id, depth=3)
        result = impact_analysis(neighborhood, node_id)
        return len(result.affected_nodes)
    except Exception:
        logger.debug("blast-radius estimation unavailable for %s", resource_id, exc_info=True)
        return None


def simulate_fix_impact(
    resource_id: Optional[str], account_id: Optional[str] = None
) -> Optional[dict]:
    """Pre-execution simulation: what breaks if this resource is disrupted?

    Runs impact_analysis on the persisted graph (zero AWS calls) and returns
    {severity, affected_nodes, isolated_subnets, lost_connections} or None
    when the graph is unavailable — policy rules using impact_severity simply
    don't match in that case (fail-soft, behavior identical to no simulation).
    """
    if not resource_id:
        return None
    try:
        from agenticops.graph.store import GraphStore
        from agenticops.graph.algorithms import impact_analysis

        node_id = _find_graph_node(resource_id, account_id)
        if not node_id:
            return None
        neighborhood = GraphStore().get_node_neighborhood(node_id, depth=3)
        result = impact_analysis(neighborhood, node_id)
        return {
            "severity": result.severity,
            "affected_nodes": len(result.affected_nodes),
            "isolated_subnets": len(result.isolated_subnets),
            "lost_connections": len(result.lost_connections),
        }
    except Exception:
        logger.debug("fix-impact simulation unavailable for %s", resource_id, exc_info=True)
        return None
