"""
Skills Framework — Shared data models.

Architecture: ADR-006 §3 Skill Specification + §4.2 Security Tiers
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class SecurityTier(enum.IntEnum):
    """Security tier levels. Higher = more dangerous."""
    T0_READONLY = 0
    T1_LOW_RISK = 1
    T2_HIGH_RISK = 2
    T3_DESTRUCTIVE = 3


class ToolStatus(str, enum.Enum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    DRY_RUN = "dry_run"
    TIMEOUT = "timeout"


@dataclass
class ToolResult:
    """Standardized result from any skill tool."""
    status: ToolStatus
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }, indent=2, default=str)

    @classmethod
    def success(cls, data: Any, **meta: Any) -> "ToolResult":
        return cls(status=ToolStatus.SUCCESS, data=data, metadata=meta)

    @classmethod
    def blocked(cls, reason: str, layer: str = "") -> "ToolResult":
        return cls(
            status=ToolStatus.BLOCKED,
            error=reason,
            metadata={"layer": layer} if layer else {},
        )

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        return cls(status=ToolStatus.ERROR, error=error)


@dataclass(frozen=True)
class SkillManifest:
    """Skill metadata from SKILL.md frontmatter (Pydantic-like validation)."""
    name: str
    description: str
    version: str = "1.0.0"
    display_name: str = ""
    role: str = ""
    domain: str = ""
    icon: str = ""
    tool_count: int = 0
    domains: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    confidence_boost: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Skill name is required")
        if not self.description:
            raise ValueError("Skill description is required")
        # Clamp confidence_boost to [0.0, 1.0] — Reviewer suggestion
        if self.confidence_boost < 0.0 or self.confidence_boost > 1.0:
            object.__setattr__(
                self, "confidence_boost",
                max(0.0, min(1.0, self.confidence_boost)),
            )
