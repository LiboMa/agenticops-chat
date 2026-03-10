"""Agent tier bindings — per-agent max SecurityTier.

Architecture: SECURE_TOOL_MIGRATION_GUIDE §3.4
"""

from __future__ import annotations

import logging
from typing import Dict

from ._models import SecurityTier
from ._security import set_agent_context

logger = logging.getLogger(__name__)

# Default tier bindings for ClawOps 7+1 agents
AGENT_TIER_BINDINGS: Dict[str, SecurityTier] = {
    "scan_agent": SecurityTier.T0_READONLY,       # Read-only scanning
    "detect_agent": SecurityTier.T0_READONLY,     # Read-only detection
    "rca_agent": SecurityTier.T1_LOW_RISK,        # Diagnostic + evidence
    "reporter_agent": SecurityTier.T0_READONLY,   # Read-only reporting
    "executor_agent": SecurityTier.T2_HIGH_RISK,  # Remediation (needs approval)
    "sre_agent": SecurityTier.T3_DESTRUCTIVE,     # Full ops (dual approval)
    "main_agent": SecurityTier.T1_LOW_RISK,       # Coordinator
    "proactive_agent": SecurityTier.T0_READONLY,  # Phase 3: read-only
}


def bind_agent(agent_id: str) -> SecurityTier:
    """Set agent context from bindings. Returns the bound tier.

    If agent_id is not in AGENT_TIER_BINDINGS, defaults to T0_READONLY
    (principle of least privilege).
    """
    tier = AGENT_TIER_BINDINGS.get(agent_id, SecurityTier.T0_READONLY)
    set_agent_context(agent_id, tier)
    logger.debug("Agent '%s' bound to tier %s", agent_id, tier.name)
    return tier


def get_agent_tier(agent_id: str) -> SecurityTier:
    """Get the tier for an agent without setting context."""
    return AGENT_TIER_BINDINGS.get(agent_id, SecurityTier.T0_READONLY)


def register_agent_tier(agent_id: str, tier: SecurityTier) -> None:
    """Register or update an agent's tier binding at runtime."""
    AGENT_TIER_BINDINGS[agent_id] = tier
    logger.info("Agent '%s' tier updated to %s", agent_id, tier.name)
