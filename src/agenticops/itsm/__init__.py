"""ITSM integration — sync HealthIssue/FixPlan lifecycle into ServiceNow/Jira.

The bridge subscribes to pipeline events and mirrors them as incident +
change-request records, giving every automated fix an auditable change
record (SOC 2 CC8.1 / ITIL change enablement).
"""

from agenticops.itsm.base import ITSMAdapter, ITSMResult
from agenticops.itsm.bridge import start_itsm_bridge, stop_itsm_bridge

__all__ = ["ITSMAdapter", "ITSMResult", "start_itsm_bridge", "stop_itsm_bridge"]
