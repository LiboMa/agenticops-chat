"""Per-agent memory system for ClawOps.

Factory function to get or create AgentMemory instances.
"""

from agenticops.memory.agent_memory import AgentMemory
from agenticops.memory.types import MemoryEntry, MemoryType, decayed_confidence

_memory_cache: dict[str, AgentMemory] = {}


def get_agent_memory(agent_name: str, db_path: str = "") -> AgentMemory:
    """Get or create an AgentMemory instance for the given agent.

    Uses singleton pattern per agent_name.
    """
    if agent_name not in _memory_cache:
        _memory_cache[agent_name] = AgentMemory(agent_name, db_path=db_path)
    return _memory_cache[agent_name]


def clear_memory_cache() -> None:
    """Clear the singleton cache (for testing)."""
    _memory_cache.clear()


# Pre-defined agent names matching agents/ module
AGENT_NAMES = [
    "main_agent",
    "scan_agent",
    "detect_agent",
    "rca_agent",
    "sre_agent",
    "executor_agent",
    "reporter_agent",
]

__all__ = [
    "AgentMemory",
    "MemoryEntry",
    "MemoryType",
    "decayed_confidence",
    "get_agent_memory",
    "clear_memory_cache",
    "AGENT_NAMES",
]
