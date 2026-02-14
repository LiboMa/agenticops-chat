"""OpsAgent - LLM-powered operations agent using LangChain.

DEPRECATED: This module is no longer imported by any active code path.
It is superseded by the Strands-based multi-agent system in agenticops.agents.
Use agenticops.agents.create_main_agent() for new code.

The ``aiops chat --legacy`` flag has been removed. This file is retained only
because the web dashboard (web/app.py) may still reference it; it will be
cleaned up when the Web Dashboard is refactored.
"""

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Optional

warnings.warn(
    "agenticops.agent.ops_agent.OpsAgent is deprecated and no longer used. "
    "Use agenticops.agents.create_main_agent() (Strands SDK) instead.",
    DeprecationWarning,
    stacklevel=2,
)

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import Tool, tool
from langchain_aws import ChatBedrock

from agenticops.config import settings
from agenticops.models import AWSAccount, get_session

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Response from agent with token usage."""
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0

    @property
    def has_usage(self) -> bool:
        return self.total_tokens > 0


class OpsAgent:
    """LLM-powered operations agent for cloud management."""

    def __init__(self, account: Optional[AWSAccount] = None):
        """Initialize the agent."""
        self.account = account
        self._llm = None
        self._tools = None

    @property
    def llm(self) -> ChatBedrock:
        """Get LangChain Bedrock LLM."""
        if self._llm is None:
            self._llm = ChatBedrock(
                model_id=settings.bedrock_model_id,
                region_name=settings.bedrock_region,
                model_kwargs={"max_tokens": 4096},
            )
        return self._llm

    def _get_tools(self) -> list[Tool]:
        """Get agent tools."""
        if self._tools is not None:
            return self._tools

        # Import modules here to avoid circular imports
        from agenticops.scan import AWSScanner
        from agenticops.monitor import CloudWatchMonitor
        from agenticops.detect import AnomalyDetector
        from agenticops.analyze import RCAEngine
        from agenticops.report import ReportGenerator

        tools = []

        # Scan tool
        @tool
        def scan_resources(
            services: str = "all",
            regions: str = "all",
        ) -> str:
            """
            Scan AWS resources in the configured account.

            Args:
                services: Comma-separated list of services or 'all'
                regions: Comma-separated list of regions or 'all'

            Returns:
                Summary of scanned resources
            """
            if not self.account:
                return "Error: No AWS account configured"

            scanner = AWSScanner(self.account)

            # Parse services
            service_list = None
            if services.lower() != "all":
                service_list = [s.strip() for s in services.split(",")]

            # Parse regions
            region_list = None
            if regions.lower() != "all":
                region_list = [r.strip() for r in regions.split(",")]

            results = scanner.scan_all_services(
                regions=region_list,
                services=service_list,
            )

            # Save and summarize
            saved = scanner.save_results(results)
            total = sum(r.count for r in results if r.success)
            errors = sum(1 for r in results if not r.success)

            return f"Scanned {total} resources across {len(results)} service/region combinations. Saved {saved} new resources. {errors} errors encountered."

        tools.append(scan_resources)

        # Monitor tool
        @tool
        def get_metrics(
            resource_id: str,
            resource_type: str,
            region: str,
            hours: int = 1,
        ) -> str:
            """
            Get CloudWatch metrics for a resource.

            Args:
                resource_id: AWS resource ID
                resource_type: Resource type (EC2, Lambda, RDS, etc.)
                region: AWS region
                hours: Hours of data to retrieve

            Returns:
                Metrics summary
            """
            if not self.account:
                return "Error: No AWS account configured"

            monitor = CloudWatchMonitor(self.account)
            metrics = monitor.get_service_metrics(
                service_type=resource_type,
                resource_id=resource_id,
                region=region,
                hours=hours,
            )

            if not metrics:
                return f"No metrics found for {resource_type}/{resource_id}"

            summary = []
            for metric_name, data_points in metrics.items():
                if data_points:
                    values = [dp["value"] for dp in data_points]
                    summary.append(
                        f"- {metric_name}: min={min(values):.2f}, max={max(values):.2f}, avg={sum(values)/len(values):.2f}"
                    )

            return f"Metrics for {resource_type}/{resource_id}:\n" + "\n".join(summary)

        tools.append(get_metrics)

        # Detect tool
        @tool
        def detect_anomalies(
            service_types: str = "all",
            region: str = "",
        ) -> str:
            """
            Run anomaly detection on resources.

            Args:
                service_types: Comma-separated service types or 'all'
                region: Optional region filter

            Returns:
                Anomaly detection summary
            """
            if not self.account:
                return "Error: No AWS account configured"

            detector = AnomalyDetector(self.account)

            type_list = None
            if service_types.lower() != "all":
                type_list = [t.strip() for t in service_types.split(",")]

            results = detector.detect_all(
                service_types=type_list,
                region=region or None,
            )

            total_anomalies = sum(len(v) for v in results.values())

            if total_anomalies == 0:
                return "No anomalies detected."

            summary = [f"Detected {total_anomalies} anomalies:"]
            for resource_id, anomalies in results.items():
                for a in anomalies:
                    summary.append(f"- [{a.severity.upper()}] {a.title}")

            return "\n".join(summary)

        tools.append(detect_anomalies)

        # Analyze tool
        @tool
        def analyze_anomaly(anomaly_id: int) -> str:
            """
            Perform Root Cause Analysis on an anomaly.

            Args:
                anomaly_id: ID of the anomaly to analyze

            Returns:
                RCA result summary
            """
            from agenticops.models import Anomaly

            session = get_session()
            try:
                anomaly = session.query(Anomaly).filter_by(id=anomaly_id).first()
                if not anomaly:
                    return f"Anomaly {anomaly_id} not found"

                rca_engine = RCAEngine(self.account)
                analysis = rca_engine.analyze_with_metrics(anomaly)

                return f"""Root Cause Analysis for Anomaly #{anomaly_id}:

**Root Cause**: {analysis.root_cause}
**Confidence**: {analysis.confidence_score * 100:.0f}%

**Contributing Factors**:
{chr(10).join(f'- {f}' for f in analysis.contributing_factors)}

**Recommendations**:
{chr(10).join(f'- {r}' for r in analysis.recommendations)}
"""
            finally:
                session.close()

        tools.append(analyze_anomaly)

        # Report tool
        @tool
        def generate_report(report_type: str = "daily") -> str:
            """
            Generate an operations report.

            Args:
                report_type: Type of report (daily, inventory, anomaly)

            Returns:
                Report path or summary
            """
            generator = ReportGenerator(self.account)

            if report_type == "daily":
                report = generator.generate_daily_report()
                return f"Daily report generated. Preview:\n{report[:1000]}..."
            elif report_type == "inventory":
                report = generator.generate_inventory_report()
                return f"Inventory report generated. Preview:\n{report[:1000]}..."
            else:
                return f"Unknown report type: {report_type}. Use 'daily' or 'inventory'."

        tools.append(generate_report)

        # List resources tool
        @tool
        def list_resources(
            resource_type: str = "",
            region: str = "",
            limit: int = 0,
        ) -> str:
            """
            List monitored resources from the database.

            Args:
                resource_type: Filter by resource type (e.g., EC2, Lambda)
                region: Filter by region
                limit: Maximum number of results (0 = use default from config)

            Returns:
                List of resources
            """
            # Use config default if not specified
            if limit <= 0:
                limit = settings.agent_list_limit
            from agenticops.models import AWSResource

            session = get_session()
            try:
                query = session.query(AWSResource)

                if self.account:
                    query = query.filter_by(account_id=self.account.id)
                if resource_type:
                    query = query.filter_by(resource_type=resource_type)
                if region:
                    query = query.filter_by(region=region)

                total = query.count()
                resources = query.limit(limit).all()

                if not resources:
                    return "No resources found matching criteria."

                lines = [f"**Resources** (showing {len(resources)} of {total}):", ""]
                for r in resources:
                    name = r.resource_name or r.resource_id
                    lines.append(f"| {r.resource_type} | {name} | {r.region} | {r.status} |")

                lines.append("")
                lines.append("[DISPLAY ALL LINES ABOVE TO USER]")
                return "\n".join(lines)

            finally:
                session.close()

        tools.append(list_resources)

        # Get anomalies tool
        @tool
        def list_anomalies(
            severity: str = "",
            status: str = "open",
            limit: int = 10,
        ) -> str:
            """
            List detected anomalies.

            Args:
                severity: Filter by severity (critical, high, medium, low)
                status: Filter by status (open, resolved)
                limit: Maximum results

            Returns:
                List of anomalies
            """
            from agenticops.models import Anomaly

            session = get_session()
            try:
                query = session.query(Anomaly).order_by(Anomaly.detected_at.desc())

                if severity:
                    query = query.filter_by(severity=severity.lower())
                if status:
                    query = query.filter_by(status=status.lower())

                total = query.count()
                anomalies = query.limit(limit).all()

                if not anomalies:
                    return "No anomalies found."

                lines = [f"**Anomalies** (showing {len(anomalies)} of {total}):", ""]
                lines.append("| ID | Severity | Title | Detected |")
                lines.append("|---|---|---|---|")
                for a in anomalies:
                    lines.append(
                        f"| #{a.id} | {a.severity.upper()} | {a.title} | {a.detected_at.strftime('%Y-%m-%d %H:%M')} |"
                    )

                lines.append("")
                lines.append("[DISPLAY THIS TABLE TO USER]")
                return "\n".join(lines)

            finally:
                session.close()

        tools.append(list_anomalies)

        # List accounts tool
        @tool
        def list_accounts() -> str:
            """
            List all configured AWS accounts.

            Returns:
                List of AWS accounts with their details
            """
            from agenticops.models import AWSAccount

            session = get_session()
            try:
                accounts = session.query(AWSAccount).all()

                if not accounts:
                    return "No AWS accounts configured."

                lines = ["**AWS Accounts:**", ""]
                lines.append("| Name | Account ID | Status | Regions | Last Scan |")
                lines.append("|---|---|---|---|---|")
                for acc in accounts:
                    status = "✓ Active" if acc.is_active else "Inactive"
                    last_scan = acc.last_scanned_at.strftime('%Y-%m-%d %H:%M') if acc.last_scanned_at else "Never"
                    regions = ', '.join(acc.regions[:3])
                    lines.append(f"| {acc.name} | {acc.account_id} | {status} | {regions} | {last_scan} |")

                lines.append("")
                lines.append("[DISPLAY THIS TABLE TO USER]")
                return "\n".join(lines)

            finally:
                session.close()

        tools.append(list_accounts)

        # Acknowledge anomaly tool
        @tool
        def acknowledge_anomaly(anomaly_id: int, note: str = "") -> str:
            """
            Acknowledge an anomaly to indicate it has been reviewed.

            Args:
                anomaly_id: ID of the anomaly to acknowledge
                note: Optional note about the acknowledgment

            Returns:
                Confirmation message
            """
            from agenticops.models import Anomaly

            session = get_session()
            try:
                anomaly = session.query(Anomaly).filter_by(id=anomaly_id).first()
                if not anomaly:
                    return f"Anomaly #{anomaly_id} not found."

                if anomaly.status != "open":
                    return f"Anomaly #{anomaly_id} is already {anomaly.status}."

                anomaly.status = "acknowledged"
                session.commit()

                result = f"Anomaly #{anomaly_id} has been acknowledged."
                if note:
                    result += f" Note: {note}"
                return result

            except Exception as e:
                session.rollback()
                return f"Error acknowledging anomaly: {str(e)}"
            finally:
                session.close()

        tools.append(acknowledge_anomaly)

        # Resolve anomaly tool
        @tool
        def resolve_anomaly(anomaly_id: int, resolution: str = "") -> str:
            """
            Mark an anomaly as resolved.

            Args:
                anomaly_id: ID of the anomaly to resolve
                resolution: Description of the resolution

            Returns:
                Confirmation message
            """
            from agenticops.models import Anomaly
            from datetime import datetime

            session = get_session()
            try:
                anomaly = session.query(Anomaly).filter_by(id=anomaly_id).first()
                if not anomaly:
                    return f"Anomaly #{anomaly_id} not found."

                if anomaly.status == "resolved":
                    return f"Anomaly #{anomaly_id} is already resolved."

                anomaly.status = "resolved"
                anomaly.resolved_at = datetime.utcnow()
                session.commit()

                result = f"Anomaly #{anomaly_id} has been resolved."
                if resolution:
                    result += f" Resolution: {resolution}"
                return result

            except Exception as e:
                session.rollback()
                return f"Error resolving anomaly: {str(e)}"
            finally:
                session.close()

        tools.append(resolve_anomaly)

        # Get monitoring config tool
        @tool
        def get_monitoring_config(account_name: str = "") -> str:
            """
            Get monitoring configuration for an account.

            Args:
                account_name: Optional account name to filter by

            Returns:
                Monitoring configuration details
            """
            from agenticops.models import MonitoringConfig, AWSAccount

            session = get_session()
            try:
                query = session.query(MonitoringConfig)

                if account_name:
                    account = session.query(AWSAccount).filter_by(name=account_name).first()
                    if not account:
                        return f"Account '{account_name}' not found."
                    query = query.filter_by(account_id=account.id)
                elif self.account:
                    query = query.filter_by(account_id=self.account.id)

                configs = query.all()

                if not configs:
                    return "No monitoring configurations found."

                lines = ["Monitoring Configurations:"]
                for config in configs:
                    status = "Enabled" if config.is_enabled else "Disabled"
                    lines.append(f"\n- {config.service_type} ({status}):")
                    if config.thresholds:
                        for metric, threshold in config.thresholds.items():
                            lines.append(f"    {metric}: {threshold}")

                return "\n".join(lines)

            finally:
                session.close()

        tools.append(get_monitoring_config)

        # Update monitoring threshold tool
        @tool
        def update_monitoring_threshold(
            service: str,
            metric: str,
            threshold: float,
            account_name: str = "",
        ) -> str:
            """
            Update a monitoring threshold for a service.

            Args:
                service: Service type (EC2, Lambda, RDS, etc.)
                metric: Metric name (CPUUtilization, Memory, etc.)
                threshold: New threshold value
                account_name: Optional account name

            Returns:
                Confirmation message
            """
            from agenticops.models import MonitoringConfig, AWSAccount

            session = get_session()
            try:
                # Get account
                if account_name:
                    account = session.query(AWSAccount).filter_by(name=account_name).first()
                    if not account:
                        return f"Account '{account_name}' not found."
                elif self.account:
                    account = self.account
                else:
                    account = session.query(AWSAccount).filter_by(is_active=True).first()
                    if not account:
                        return "No active account found."

                # Get or create config
                config = session.query(MonitoringConfig).filter_by(
                    account_id=account.id,
                    service_type=service,
                ).first()

                if not config:
                    config = MonitoringConfig(
                        account_id=account.id,
                        service_type=service,
                        is_enabled=True,
                        metrics_config={},
                        logs_config={},
                        thresholds={},
                    )
                    session.add(config)

                # Update threshold
                if not config.thresholds:
                    config.thresholds = {}
                config.thresholds[metric] = threshold
                session.commit()

                return f"Updated {service}/{metric} threshold to {threshold} for account '{account.name}'."

            except Exception as e:
                session.rollback()
                return f"Error updating threshold: {str(e)}"
            finally:
                session.close()

        tools.append(update_monitoring_threshold)

        # Get resource details tool
        @tool
        def get_resource_details(resource_id: str) -> str:
            """
            Get detailed information about a specific resource.

            Args:
                resource_id: The AWS resource ID (e.g., i-1234567890abcdef0)

            Returns:
                Detailed resource information
            """
            from agenticops.models import AWSResource

            session = get_session()
            try:
                resource = session.query(AWSResource).filter_by(resource_id=resource_id).first()
                if not resource:
                    # Try by internal ID
                    try:
                        resource = session.query(AWSResource).filter_by(id=int(resource_id)).first()
                    except ValueError:
                        pass

                if not resource:
                    return f"Resource '{resource_id}' not found."

                details = [
                    f"Resource: {resource.resource_name or resource.resource_id}",
                    f"Type: {resource.resource_type}",
                    f"ID: {resource.resource_id}",
                    f"ARN: {resource.resource_arn or 'N/A'}",
                    f"Region: {resource.region}",
                    f"Status: {resource.status}",
                    f"Created: {resource.created_at.strftime('%Y-%m-%d %H:%M') if resource.created_at else 'Unknown'}",
                ]
                if resource.tags:
                    details.append(f"Tags: {resource.tags}")
                if resource.config:
                    details.append(f"Configuration: {resource.config}")

                return "\n".join(details)

            finally:
                session.close()

        tools.append(get_resource_details)

        # Get anomaly details tool
        @tool
        def get_anomaly_details(anomaly_id: int) -> str:
            """
            Get detailed information about a specific anomaly.

            Args:
                anomaly_id: The anomaly ID

            Returns:
                Detailed anomaly information including RCA if available
            """
            from agenticops.models import Anomaly, RCAResult

            session = get_session()
            try:
                anomaly = session.query(Anomaly).filter_by(id=anomaly_id).first()
                if not anomaly:
                    return f"Anomaly #{anomaly_id} not found."

                details = [
                    f"Anomaly #{anomaly.id}: {anomaly.title}",
                    f"Severity: {anomaly.severity.upper()}",
                    f"Status: {anomaly.status}",
                    f"Description: {anomaly.description}",
                    f"Resource: {anomaly.resource_type}/{anomaly.resource_id}",
                    f"Detected: {anomaly.detected_at.strftime('%Y-%m-%d %H:%M')}",
                ]

                if anomaly.resolved_at:
                    details.append(f"Resolved: {anomaly.resolved_at.strftime('%Y-%m-%d %H:%M')}")

                # Check for RCA
                rca = session.query(RCAResult).filter_by(anomaly_id=anomaly.id).order_by(RCAResult.analyzed_at.desc()).first()
                if rca:
                    details.append(f"\n**Root Cause Analysis:**")
                    details.append(f"Root Cause: {rca.root_cause}")
                    details.append(f"Confidence: {rca.confidence_score * 100:.0f}%")
                    if rca.recommendations:
                        details.append(f"Recommendations:")
                        for rec in rca.recommendations[:3]:
                            details.append(f"  - {rec}")

                return "\n".join(details)

            finally:
                session.close()

        tools.append(get_anomaly_details)

        # Get system status tool
        @tool
        def get_system_status() -> str:
            """
            Get overall system status including accounts, resources, and anomalies.

            Returns:
                System status summary
            """
            from agenticops.models import AWSAccount, AWSResource, Anomaly

            session = get_session()
            try:
                accounts = session.query(AWSAccount).all()
                active_account = next((a for a in accounts if a.is_active), None)

                resources = session.query(AWSResource).count()
                open_anomalies = session.query(Anomaly).filter_by(status="open").count()
                ack_anomalies = session.query(Anomaly).filter_by(status="acknowledged").count()
                critical_anomalies = session.query(Anomaly).filter(
                    Anomaly.status.in_(["open", "acknowledged"]),
                    Anomaly.severity == "critical"
                ).count()

                lines = [
                    "**System Status**",
                    "",
                    f"Accounts: {len(accounts)} configured",
                    f"Active Account: {active_account.name if active_account else 'None'}",
                    "",
                    f"Resources: {resources} tracked",
                    "",
                    f"Anomalies:",
                    f"  - Open: {open_anomalies}",
                    f"  - Acknowledged: {ack_anomalies}",
                    f"  - Critical: {critical_anomalies}",
                ]

                if critical_anomalies > 0:
                    lines.append("\n⚠️ There are critical anomalies requiring attention!")

                return "\n".join(lines)

            finally:
                session.close()

        tools.append(get_system_status)

        # Activate account tool
        @tool
        def activate_account(account_name: str) -> str:
            """
            Activate an AWS account (only one can be active at a time).

            Args:
                account_name: Name of the account to activate

            Returns:
                Confirmation message
            """
            from agenticops.models import AWSAccount

            session = get_session()
            try:
                account = session.query(AWSAccount).filter_by(name=account_name).first()
                if not account:
                    return f"Account '{account_name}' not found."

                if account.is_active:
                    return f"Account '{account_name}' is already active."

                # Deactivate all others
                session.query(AWSAccount).update({"is_active": False})
                account.is_active = True
                session.commit()

                return f"Account '{account_name}' is now active. All other accounts have been deactivated."

            except Exception as e:
                session.rollback()
                return f"Error activating account: {str(e)}"
            finally:
                session.close()

        tools.append(activate_account)

        # List reports tool
        @tool
        def list_reports(report_type: str = "", limit: int = 10) -> str:
            """
            List generated reports.

            Args:
                report_type: Filter by report type (daily, inventory, anomaly)
                limit: Maximum number of reports to return

            Returns:
                List of reports
            """
            from agenticops.models import Report

            session = get_session()
            try:
                query = session.query(Report).order_by(Report.created_at.desc())

                if report_type:
                    query = query.filter_by(report_type=report_type)

                reports = query.limit(limit).all()

                if not reports:
                    return "No reports found."

                lines = [f"Found {len(reports)} reports:"]
                for r in reports:
                    lines.append(
                        f"- #{r.id} [{r.report_type}] {r.title} ({r.created_at.strftime('%Y-%m-%d %H:%M')})"
                    )

                return "\n".join(lines)

            finally:
                session.close()

        tools.append(list_reports)

        # Search resources tool
        @tool
        def search_resources(query: str, limit: int = 20) -> str:
            """
            Search resources by name, ID, or tags.

            Args:
                query: Search query (matches name, ID, or tag values)
                limit: Maximum results

            Returns:
                Matching resources
            """
            from agenticops.models import AWSResource
            from sqlalchemy import or_

            session = get_session()
            try:
                search_pattern = f"%{query}%"
                resources = session.query(AWSResource).filter(
                    or_(
                        AWSResource.resource_id.ilike(search_pattern),
                        AWSResource.resource_name.ilike(search_pattern),
                        AWSResource.resource_arn.ilike(search_pattern),
                    )
                ).limit(limit).all()

                if not resources:
                    return f"No resources found matching '{query}'."

                lines = [f"Found {len(resources)} resources matching '{query}':"]
                for r in resources:
                    name = r.resource_name or r.resource_id
                    lines.append(f"- {r.resource_type}/{name} ({r.region})")

                return "\n".join(lines)

            finally:
                session.close()

        tools.append(search_resources)

        self._tools = tools
        return tools

    def chat(self, message: str, return_usage: bool = False) -> str | AgentResponse:
        """
        Chat with the agent.

        Args:
            message: User message
            return_usage: If True, return AgentResponse with token usage

        Returns:
            Agent response string, or AgentResponse if return_usage=True
        """
        system_prompt = """You are AgenticAIOps, an AI-powered cloud operations assistant.

MOST IMPORTANT RULE: When a tool returns data, you MUST copy the ENTIRE output verbatim into your response. DO NOT summarize, paraphrase, or abbreviate. Show every single line of data.

Example of CORRECT behavior:
- Tool returns: "Found 20 resources:\n- EC2/i-123 (us-east-1)\n- EC2/i-456 (us-west-2)\n..."
- Your response MUST include ALL 20 lines exactly as returned

Example of WRONG behavior (NEVER DO THIS):
- Saying "The tool found 20 EC2 instances across multiple regions"
- Summarizing or describing the results instead of showing them

Available tools: list_resources, get_resource_details, search_resources, scan_resources, list_anomalies, get_anomaly_details, detect_anomalies, acknowledge_anomaly, resolve_anomaly, analyze_anomaly, get_metrics, list_accounts, activate_account, get_system_status, generate_report, list_reports, get_monitoring_config, update_monitoring_threshold

When user asks to see/list/show anything, call the appropriate tool and COPY THE ENTIRE OUTPUT into your response."""

        tools = self._get_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=message),
        ]

        # Track token usage
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0

        def extract_usage(resp) -> tuple[int, int]:
            """Extract token usage from response metadata."""
            input_tok = 0
            output_tok = 0
            if hasattr(resp, "response_metadata"):
                meta = resp.response_metadata
                # Bedrock format
                if "usage" in meta:
                    input_tok = meta["usage"].get("input_tokens", 0)
                    output_tok = meta["usage"].get("output_tokens", 0)
                # Alternative format
                elif "token_usage" in meta:
                    input_tok = meta["token_usage"].get("prompt_tokens", 0)
                    output_tok = meta["token_usage"].get("completion_tokens", 0)
            return input_tok, output_tok

        # Simple tool-calling loop
        max_iterations = 5
        for _ in range(max_iterations):
            response = llm_with_tools.invoke(messages)

            # Track tokens
            inp, out = extract_usage(response)
            total_input_tokens += inp
            total_output_tokens += out

            # Check for tool calls
            if hasattr(response, "tool_calls") and response.tool_calls:
                messages.append(response)
                tool_call_count += len(response.tool_calls)

                for tool_call in response.tool_calls:
                    # Find and execute tool
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]

                    tool_fn = next(
                        (t for t in tools if t.name == tool_name), None
                    )
                    if tool_fn:
                        try:
                            result = tool_fn.invoke(tool_args)
                        except Exception as e:
                            result = f"Tool error: {str(e)}"
                    else:
                        result = f"Unknown tool: {tool_name}"

                    # Add tool result to messages
                    from langchain_core.messages import ToolMessage

                    messages.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tool_call["id"],
                        )
                    )
            else:
                # No more tool calls, return response
                if return_usage:
                    return AgentResponse(
                        content=response.content,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        total_tokens=total_input_tokens + total_output_tokens,
                        tool_calls=tool_call_count,
                    )
                return response.content

        content = "Max iterations reached. Please try a more specific request."
        if return_usage:
            return AgentResponse(
                content=content,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_tokens=total_input_tokens + total_output_tokens,
                tool_calls=tool_call_count,
            )
        return content

    def execute_command(self, command: str) -> str:
        """
        Execute a direct command without chat context.

        Args:
            command: Command to execute (scan, monitor, detect, analyze, report)

        Returns:
            Command result
        """
        tools = self._get_tools()
        tool_map = {t.name: t for t in tools}

        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Map commands to tools
        command_tool_map = {
            "scan": "scan_resources",
            "list": "list_resources",
            "metrics": "get_metrics",
            "detect": "detect_anomalies",
            "analyze": "analyze_anomaly",
            "report": "generate_report",
            "anomalies": "list_anomalies",
        }

        tool_name = command_tool_map.get(cmd)
        if not tool_name:
            return f"Unknown command: {cmd}. Available: {', '.join(command_tool_map.keys())}"

        tool_fn = tool_map.get(tool_name)
        if not tool_fn:
            return f"Tool not found: {tool_name}"

        try:
            # Parse simple key=value args
            kwargs = {}
            if args:
                for pair in args.split():
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        kwargs[k] = v

            return tool_fn.invoke(kwargs)
        except Exception as e:
            return f"Error executing {cmd}: {str(e)}"
