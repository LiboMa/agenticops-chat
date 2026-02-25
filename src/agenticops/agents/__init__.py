"""Strands SDK multi-agent system for AgenticOps.

Architecture: Main Agent (Orchestrator) -> Sub-agents as tools
- Scan Agent: Resource discovery and inventory
- Detect Agent: Health monitoring via CloudWatch
- RCA Agent: Root cause analysis
- SRE Agent: Fix plan generation (read-only)
- Executor Agent: Fix plan execution (L4 Auto Operation)
- Reporter Agent: Reports and case studies
"""

from agenticops.agents.main_agent import create_main_agent
from agenticops.agents.scan_agent import scan_agent
from agenticops.agents.detect_agent import detect_agent
from agenticops.agents.rca_agent import rca_agent
from agenticops.agents.executor_agent import executor_agent
from agenticops.agents.reporter_agent import reporter_agent

__all__ = [
    "create_main_agent",
    "scan_agent",
    "detect_agent",
    "rca_agent",
    "executor_agent",
    "reporter_agent",
]
