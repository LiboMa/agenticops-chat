"""HealthPatrol pipeline — proactive health patrol via detect_agent on a schedule."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agenticops.models import CloudAccount
from agenticops.pipeline.orchestrator import (
    Pipeline,
    PipelineResult,
    PipelineStep,
    StepResult,
    StepStatus,
)

logger = logging.getLogger(__name__)


class FetchExternalAlertsStep(PipelineStep):
    """Pull active alerts from configured external monitoring providers."""

    def __init__(self):
        super().__init__("fetch_external_alerts")

    async def execute(self, context: Dict[str, Any]) -> Any:
        config = context.get("config", {})
        providers_cfg = config.get("providers", "all")

        try:
            from agenticops.integrations import get_provider, get_providers

            if providers_cfg == "all":
                providers = get_providers()
            else:
                names = [p.strip() for p in providers_cfg.split(",") if p.strip()]
                providers = [
                    p for name in names if (p := get_provider(name)) is not None
                ]

            if not providers:
                return {"alerts": [], "note": "No monitoring providers configured"}

            all_alerts = []
            for provider in providers:
                try:
                    alerts = provider.list_active_alerts()
                    all_alerts.extend(
                        {
                            "source": a.source,
                            "external_id": a.external_id,
                            "severity": a.severity,
                            "title": a.title,
                            "resource_hint": a.resource_hint,
                        }
                        for a in alerts
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to fetch alerts from %s: %s", provider.name, e
                    )

            return {"alerts": all_alerts, "count": len(all_alerts)}

        except ImportError:
            return {"alerts": [], "note": "Integrations module not available"}


class RunDetectStep(PipelineStep):
    """Run the detect_agent for health detection."""

    def __init__(self):
        super().__init__("run_detect", depends_on=["fetch_external_alerts"])

    async def execute(self, context: Dict[str, Any]) -> Any:
        config = context.get("config", {})
        scope = config.get("scope", "all")
        deep = config.get("deep", False)

        from agenticops.agents.detect_agent import detect_agent

        result = detect_agent(scope=scope, deep=deep)
        return {"detect_result": str(result)[:2000]}


class AnalyzeGraphRisksStep(PipelineStep):
    """Preventive structural risk analysis from the persisted infra graph.

    Runs SPOF detection and capacity-risk analysis as pure code (zero LLM,
    zero AWS calls — reads the GraphStore populated by graph sync). Findings
    become HealthIssues with auto_rca=False: structural risks need design
    review, not CloudTrail forensics. Fingerprint dedup in the issue layer
    collapses repeat patrol findings into one open issue.
    """

    def __init__(self):
        super().__init__("analyze_graph_risks", depends_on=["run_detect"])

    async def execute(self, context: Dict[str, Any]) -> Any:
        config = context.get("config", {})
        from agenticops.config import settings

        enabled = config.get("graph_checks", settings.patrol_graph_checks_enabled)
        if not enabled:
            return {"skipped": True, "note": "graph checks disabled"}

        try:
            from agenticops.graph.store import GraphStore
            from agenticops.graph.algorithms import detect_spof, capacity_risk_analysis
        except ImportError:
            return {"skipped": True, "note": "graph module not available"}

        try:
            store = GraphStore()
            graph = store.load_graph(scope=config.get("graph_scope", ""))
        except Exception as e:
            logger.warning("Graph load failed in patrol: %s", e)
            return {"skipped": True, "note": f"graph load failed: {e}"}

        if graph.graph.number_of_nodes() == 0:
            return {"skipped": True, "note": "graph empty — run graph sync first"}

        from agenticops.tools.metadata_tools import _create_health_issue_impl

        issues_created: list[str] = []

        spof_report = detect_spof(graph)
        for item in spof_report.articulation_points:
            result = _create_health_issue_impl(
                resource_id=item.node_id,
                severity="medium",
                source="graph_patrol",
                title=f"SPOF: {item.label or item.node_id}",
                description=(
                    f"{item.impact_description} "
                    f"(affected components: {item.affected_components})"
                ),
                auto_rca=False,
            )
            issues_created.append(result)

        capacity_report = capacity_risk_analysis(
            graph, threshold=float(config.get("capacity_threshold", 0.8))
        )
        for risk in capacity_report.items:
            result = _create_health_issue_impl(
                resource_id=risk.node_id,
                severity="high" if risk.risk_level == "critical" else "medium",
                source="graph_patrol",
                title=f"Capacity risk: {risk.label or risk.node_id} {risk.metric}",
                description=(
                    f"{risk.metric} at {risk.utilization_pct:.0f}% "
                    f"({risk.current:.0f}/{risk.maximum:.0f})"
                ),
                auto_rca=False,
            )
            issues_created.append(result)

        return {
            "spofs": spof_report.total_spofs,
            "capacity_risks": capacity_report.total_risks,
            "issues": issues_created,
        }


class HealthPatrolPipeline(Pipeline):
    """Proactive health patrol — runs detect_agent on a schedule.

    Config options (passed via Schedule.config):
        scope: Resource type filter (default "all")
        deep: Run deep investigation (default False)
        providers: Comma-separated provider names or "all" (default "all")
        graph_checks: Run SPOF/capacity graph analysis (default from settings)
        graph_scope: Region or vpc-id filter for the graph load (default all)
        capacity_threshold: Utilization threshold 0-1 (default 0.8)
    """

    def __init__(self, account: Optional[CloudAccount] = None, config: Optional[dict] = None):
        super().__init__("HealthPatrol", account)
        self.add_step(FetchExternalAlertsStep())
        self.add_step(RunDetectStep())
        self.add_step(AnalyzeGraphRisksStep())
        self.patrol_config = config or {}

    async def execute(self) -> PipelineResult:
        started = datetime.now(timezone.utc)
        result = PipelineResult(
            pipeline_name=self.name,
            status=StepStatus.RUNNING,
            started_at=started,
        )

        context: Dict[str, Any] = {"config": self.patrol_config}
        if self.account:
            creds = self.account.credentials or {}
            context["account"] = {
                "name": self.account.name,
                "provider": self.account.provider,
                "account_id": creds.get("account_id", ""),
                "role_arn": creds.get("role_arn", ""),
            }

        for step in self.steps:
            step_started = datetime.now(timezone.utc)
            try:
                data = await step.execute(context)
                step_result = StepResult(
                    step_name=step.name,
                    status=StepStatus.COMPLETED,
                    data=data,
                    started_at=step_started,
                    completed_at=datetime.now(timezone.utc),
                )
                context[step.name] = data
            except Exception as e:
                logger.exception("HealthPatrol step '%s' failed", step.name)
                step_result = StepResult(
                    step_name=step.name,
                    status=StepStatus.FAILED,
                    error=str(e),
                    started_at=step_started,
                    completed_at=datetime.now(timezone.utc),
                )

            result.step_results.append(step_result)

            if step_result.status == StepStatus.FAILED:
                result.status = StepStatus.FAILED
                result.completed_at = datetime.now(timezone.utc)
                return result

        result.status = StepStatus.COMPLETED
        result.completed_at = datetime.now(timezone.utc)
        if result.started_at:
            result.duration_ms = int(
                (result.completed_at - result.started_at).total_seconds() * 1000
            )
        return result
