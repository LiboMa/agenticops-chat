"""
Skills Framework — Security layer.

5-layer defense-in-depth:
  Layer 1: GLOBAL_BLACKLIST (inviolable)
  Layer 2: @secure_tool decorator (framework-enforced)
  Layer 3: Skill-level policy (per-skill allow/deny)
  Layer 4: Agent tier binding (max_tier gate)
  Layer 5: Approval gate (T2: token, T3: dual token)

Architecture: ADR-006 §4 Security Model
"""

from __future__ import annotations

import functools
import logging
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from ._models import SecurityTier, ToolResult, ToolStatus

from contextvars import ContextVar

logger = logging.getLogger(__name__)


# ─── Layer 1: GLOBAL BLACKLIST — INVIOLABLE ───────────────────

GLOBAL_BLACKLIST_COMMANDS = frozenset([
    "rm -rf /", "rm -rf /*", "rm -rf .", "rm --no-preserve-root",
    "mkfs", "dd if=", "shutdown -h", "halt", "init 0",
    "> /dev/sda", ":(){ :|:& };:",
    "chmod -R 777 /", "mv / ",
    "drop database", "drop schema", "truncate",
    "kubectl delete namespace kube-system",
    "kubectl delete --all --all-namespaces",
    "kubectl delete nodes",
])

GLOBAL_BLACKLIST_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"rm\s+-[rf]+\s+/",
        r"rm\s+--no-preserve-root",
        r">\s*/dev/[sh]d[a-z]",
        r"dd\s+if=.*of=/dev",
        r"curl.*\|\s*sh",
        r"wget.*\|\s*sh",
        r";\s*rm\s",
        r"&&\s*rm\s",
        r"\|\s*sh\b",
        r"\$\(.*rm\s",
        r"`.*rm\s",
    ]
]

# Injection patterns — checked on ALL command-type parameters
INJECTION_PATTERNS = [
    re.compile(p) for p in [
        r";\s*\w",          # semicolon injection
        r"&&\s*\w",         # AND injection
        r"\|\|\s*\w",       # OR injection
        r"\$\(",            # command substitution
        r"`[^`]+`",         # backtick substitution
    ]
]


class SecurityViolation(Exception):
    """Raised when a security check fails."""
    def __init__(self, layer: str, reason: str):
        self.layer = layer
        self.reason = reason
        super().__init__(f"[{layer}] {reason}")


# ─── Runtime context (set by agent before tool invocation) ────

_agent_tier: ContextVar[SecurityTier] = ContextVar("secure_tool_tier", default=SecurityTier.T0_READONLY)
_agent_id: ContextVar[str] = ContextVar("secure_tool_agent", default="unknown")
_skill_policies: Dict[str, Any] = {}


def set_agent_context(agent_id: str, max_tier: SecurityTier) -> None:
    """Set the current agent context for security checks."""
    _agent_tier.set(max_tier)
    _agent_id.set(agent_id)


def register_skill_policy(skill_name: str, policy: Any) -> None:
    """Register a skill-level security policy module."""
    _skill_policies[skill_name] = policy


# ─── Layer 2: @secure_tool Decorator ──────────────────────────

def secure_tool(
    tier: SecurityTier,
    skill: str,
    *,
    command_param: Optional[str] = "command",
    dry_run_support: bool = False,
) -> Callable:
    """Decorator factory: wraps a function with mandatory security enforcement.

    Every tool MUST use this decorator. The SkillRegistry validates this
    at registration time — undecorated tools are rejected.

    Args:
        tier: Security tier of this tool.
        skill: Skill name this tool belongs to.
        command_param: Name of the kwarg containing a shell command (for blacklist check).
            Set to None for tools that don't execute commands.
        dry_run_support: If True, intercepts dry_run=True before execution.
    """
    tier = SecurityTier(tier)

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            tool_name = fn.__name__
            invocation_id = str(uuid.uuid4())[:8]

            try:
                # Layer 1: Global blacklist — INVIOLABLE
                if command_param and command_param in kwargs:
                    _check_global_blacklist(kwargs[command_param])

                # Check injection patterns on all string kwargs
                _check_injection(kwargs)

                # Layer 4: Agent tier gate
                if _agent_tier.get() < tier:
                    raise SecurityViolation(
                        "TIER_GATE",
                        f"Agent '{_agent_id.get()}' has tier {_agent_tier.get().name} "
                        f"but tool '{tool_name}' requires {tier.name}",
                    )

                # Layer 3: Skill-level policy
                policy = _skill_policies.get(skill)
                if policy and hasattr(policy, "check"):
                    ok, reason = policy.check(tool_name, kwargs)
                    if not ok:
                        raise SecurityViolation("SKILL_POLICY", reason)

                # Layer 5: Approval gate (T2+)
                if tier >= SecurityTier.T2_HIGH_RISK:
                    _check_approval(tier, kwargs, tool_name)

                # Dry-run intercept
                if dry_run_support and kwargs.get("dry_run", False):
                    return ToolResult(
                        status=ToolStatus.DRY_RUN,
                        data={"tool": tool_name, "kwargs": {k: str(v) for k, v in kwargs.items() if k != "dry_run"}},
                        metadata={"invocation_id": invocation_id},
                    ).to_json()

                # ✅ All checks passed — execute
                result = fn(*args, **kwargs)

                # Audit success
                logger.info(
                    "AUDIT tool=%s skill=%s agent=%s tier=%s status=OK id=%s",
                    tool_name, skill, _agent_id.get(), tier.name, invocation_id,
                )
                return result

            except SecurityViolation as e:
                logger.warning(
                    "AUDIT tool=%s skill=%s agent=%s tier=%s status=BLOCKED layer=%s reason='%s' id=%s",
                    tool_name, skill, _agent_id.get(), tier.name,
                    e.layer, e.reason, invocation_id,
                )
                return ToolResult.blocked(e.reason, e.layer).to_json()

            except Exception as e:
                logger.error(
                    "AUDIT tool=%s skill=%s status=ERROR error='%s' id=%s",
                    tool_name, skill, str(e), invocation_id,
                )
                return ToolResult.fail(str(e)).to_json()

        # Attach metadata for SkillRegistry validation
        wrapper._security_tier = tier
        wrapper._tool_name = fn.__name__
        wrapper._skill_name = skill
        wrapper._dry_run_support = dry_run_support

        return wrapper

    return decorator


# ─── Internal check functions ─────────────────────────────────

def _check_global_blacklist(command: str) -> None:
    """Layer 1: Check command against global blacklist."""
    cmd_lower = command.lower().strip()

    for blocked in GLOBAL_BLACKLIST_COMMANDS:
        if blocked in cmd_lower:
            raise SecurityViolation(
                "GLOBAL_BLACKLIST",
                f"Command matches global blacklist: '{blocked}'",
            )

    for pattern in GLOBAL_BLACKLIST_PATTERNS:
        if pattern.search(command):
            raise SecurityViolation(
                "GLOBAL_BLACKLIST",
                f"Command matches blacklist pattern: {pattern.pattern}",
            )


def _check_injection(kwargs: Dict[str, Any]) -> None:
    """Check all string kwargs for injection patterns."""
    for key, value in kwargs.items():
        if not isinstance(value, str):
            continue
        for pattern in INJECTION_PATTERNS:
            if pattern.search(value):
                raise SecurityViolation(
                    "INJECTION",
                    f"Potential injection in parameter '{key}': pattern {pattern.pattern}",
                )


def _check_approval(tier: SecurityTier, kwargs: Dict[str, Any], tool_name: str) -> None:
    """Layer 5: Approval gate for T2+ operations — HMAC verified."""
    try:
        from agenticops.skills.approval_token import verify as verify_token
    except ImportError:
        raise SecurityViolation(
            "APPROVAL_GATE",
            f"Tool '{tool_name}' requires T2+ approval but approval_token module not configured",
        )

    token = kwargs.pop("approval_token", None)

    if tier == SecurityTier.T3_DESTRUCTIVE:
        # T3 needs dual approval
        token2 = kwargs.pop("approval_token_2", None)
        if not token or not token2:
            raise SecurityViolation(
                "APPROVAL_GATE",
                f"Tool '{tool_name}' is T3_DESTRUCTIVE — requires dual approval_token + approval_token_2",
            )
        # Tokens verified with different action suffixes (primary/secondary)
        # HMAC verify both tokens (different action suffixes to ensure distinct sources)
        ok1, reason1 = verify_token(token, f"{tool_name}:primary")
        if not ok1:
            raise SecurityViolation("APPROVAL_GATE", f"approval_token invalid: {reason1}")
        ok2, reason2 = verify_token(token2, f"{tool_name}:secondary")
        if not ok2:
            raise SecurityViolation("APPROVAL_GATE", f"approval_token_2 invalid: {reason2}")
        logger.info("T3 dual approval HMAC-verified for '%s'", tool_name)

    elif tier == SecurityTier.T2_HIGH_RISK:
        if not token:
            raise SecurityViolation(
                "APPROVAL_GATE",
                f"Tool '{tool_name}' is T2_HIGH_RISK — requires approval_token",
            )
        ok, reason = verify_token(token, tool_name)
        if not ok:
            raise SecurityViolation("APPROVAL_GATE", f"approval_token invalid: {reason}")
        logger.info("T2 approval HMAC-verified for '%s'", tool_name)
