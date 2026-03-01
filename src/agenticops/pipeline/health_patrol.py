"""HealthPatrol pipeline — proactive health patrol via detect_agent on a schedule."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from agenticops.models import AWSAccount
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


class HealthPatrolPipeline(Pipeline):
    """Proactive health patrol — runs detect_agent on a schedule.

    Config options (passed via Schedule.config):
        scope: Resource type filter (default "all")
        deep: Run deep investigation (default False)
        providers: Comma-separated provider names or "all" (default "all")
    """

    def __init__(self, account: Optional[AWSAccount] = None, config: Optional[dict] = None):
        super().__init__(
            name="HealthPatrol",
            steps=[
                FetchExternalAlertsStep(),
                RunDetectStep(),
            ],
        )
        self.account = account
        self.patrol_config = config or {}

    async def execute(self) -> PipelineResult:
        started = datetime.utcnow()
        result = PipelineResult(
            pipeline_name=self.name,
            status=StepStatus.RUNNING,
            started_at=started,
        )

        context: Dict[str, Any] = {"config": self.patrol_config}
        if self.account:
            context["account"] = {
                "name": self.account.name,
                "account_id": self.account.account_id,
                "role_arn": self.account.role_arn,
            }

        for step in self.steps:
            step_started = datetime.utcnow()
            try:
                data = await step.execute(context)
                step_result = StepResult(
                    step_name=step.name,
                    status=StepStatus.COMPLETED,
                    data=data,
                    started_at=step_started,
                    completed_at=datetime.utcnow(),
                )
                context[step.name] = data
            except Exception as e:
                logger.exception("HealthPatrol step '%s' failed", step.name)
                step_result = StepResult(
                    step_name=step.name,
                    status=StepStatus.FAILED,
                    error=str(e),
                    started_at=step_started,
                    completed_at=datetime.utcnow(),
                )

            result.step_results.append(step_result)

            if step_result.status == StepStatus.FAILED:
                result.status = StepStatus.FAILED
                result.completed_at = datetime.utcnow()
                return result

        result.status = StepStatus.COMPLETED
        result.completed_at = datetime.utcnow()
        if result.started_at:
            result.duration_ms = int(
                (result.completed_at - result.started_at).total_seconds() * 1000
            )
        return result
