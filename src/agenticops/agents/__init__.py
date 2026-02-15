"""Strands SDK multi-agent system for AgenticOps.

Architecture: Main Agent (Orchestrator) -> Sub-agents as tools
- Scan Agent: Resource discovery and inventory
- Detect Agent: Health monitoring via CloudWatch
- RCA Agent: Root cause analysis
- Reporter Agent: Reports and case studies (Phase 2)
"""

from agenticops.agents.main_agent import create_main_agent
from agenticops.agents.scan_agent import scan_agent
from agenticops.agents.detect_agent import detect_agent
from agenticops.agents.rca_agent import rca_agent
from agenticops.agents.reporter_agent import reporter_agent

__all__ = [
    "create_main_agent",
    "scan_agent",
    "detect_agent",
    "rca_agent",
    "reporter_agent",
]
