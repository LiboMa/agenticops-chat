"""ITSM adapter contract + shared result type.

Adapters are deliberately synchronous and exception-free at the boundary:
every method returns an ITSMResult; the bridge decides what to do with
failures (log + continue — ITSM mirroring must never break the pipeline).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ITSMResult:
    """Outcome of one ITSM call."""

    ok: bool
    external_id: Optional[str] = None    # sys_id / issue key
    external_ref: Optional[str] = None   # human number: INC0010002 / CHG0030005 / OPS-123
    url: Optional[str] = None
    error: Optional[str] = None
    detail: dict = field(default_factory=dict)

    @classmethod
    def failure(cls, error: str) -> "ITSMResult":
        return cls(ok=False, error=error)


class ITSMAdapter(ABC):
    """One ITSM backend (ServiceNow, Jira Service Management, ...).

    State-machine contract (AgenticOps 9-state → ITSM):
      open                   → create_incident
      investigating/acknowledged/root_cause_identified
                             → update_incident_state + append_worknote
      fix_planned            → create_change (type from policy: standard/normal/emergency)
      fix_approved           → change moves to scheduled/implement
      fix_executing          → append per-step worknotes to the change
      fix_executed           → change to review
      resolved               → close_change(successful) + resolve_incident
    """

    name: str = "itsm"

    @abstractmethod
    def create_incident(
        self,
        *,
        title: str,
        description: str,
        severity: str,
        correlation_id: str,
        resource_id: Optional[str] = None,
    ) -> ITSMResult: ...

    @abstractmethod
    def update_incident_state(self, external_id: str, state: str) -> ITSMResult:
        """state: one of new|in_progress|on_hold|resolved (adapter maps to native values)."""
        ...

    @abstractmethod
    def append_worknote(self, external_id: str, note: str) -> ITSMResult: ...

    @abstractmethod
    def create_change(
        self,
        *,
        incident_external_id: Optional[str],
        change_type: str,           # standard | normal | emergency
        title: str,
        description: str,
        implementation_plan: str,
        backout_plan: str,
        risk_level: str,
        correlation_id: str,
    ) -> ITSMResult: ...

    @abstractmethod
    def update_change_state(self, external_id: str, state: str) -> ITSMResult:
        """state: assess|scheduled|implement|review|closed|cancelled (adapter maps)."""
        ...

    @abstractmethod
    def get_change_approval(self, external_id: str) -> ITSMResult:
        """detail['approval'] ∈ not_requested|requested|approved|rejected."""
        ...

    @abstractmethod
    def close_change(self, external_id: str, success: bool, notes: str) -> ITSMResult: ...

    @abstractmethod
    def resolve_incident(self, external_id: str, close_notes: str) -> ITSMResult: ...
