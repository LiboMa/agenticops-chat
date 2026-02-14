"""Pipeline Orchestrator - Automated workflow execution for AgenticOps."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic

from agenticops.models import AWSAccount, get_db_session

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    """Status of a pipeline step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """Result from a pipeline step execution."""
    step_name: str
    status: StepStatus
    data: Any = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    @property
    def success(self) -> bool:
        return self.status == StepStatus.COMPLETED


@dataclass
class PipelineResult:
    """Result from a pipeline execution."""
    pipeline_name: str
    status: StepStatus
    step_results: List[StepResult] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    @property
    def success(self) -> bool:
        return self.status == StepStatus.COMPLETED

    def get_step(self, name: str) -> Optional[StepResult]:
        """Get a step result by name."""
        for step in self.step_results:
            if step.step_name == name:
                return step
        return None


class PipelineStep(ABC):
    """Abstract base class for pipeline steps."""

    def __init__(self, name: str, depends_on: Optional[List[str]] = None):
        self.name = name
        self.depends_on = depends_on or []

    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> Any:
        """Execute the step with the given context.

        Args:
            context: Shared context dictionary containing data from previous steps

        Returns:
            Result data to be stored in context
        """
        pass


class FunctionStep(PipelineStep):
    """Pipeline step that wraps a function."""

    def __init__(
        self,
        name: str,
        func: Callable,
        depends_on: Optional[List[str]] = None,
        **kwargs,
    ):
        super().__init__(name, depends_on)
        self.func = func
        self.kwargs = kwargs

    async def execute(self, context: Dict[str, Any]) -> Any:
        """Execute the wrapped function."""
        # Merge context with step kwargs
        call_kwargs = {**self.kwargs}
        for key, value in call_kwargs.items():
            if isinstance(value, str) and value.startswith("$"):
                # Reference to context value
                context_key = value[1:]
                if context_key in context:
                    call_kwargs[key] = context[context_key]

        # Handle async or sync functions
        if asyncio.iscoroutinefunction(self.func):
            return await self.func(**call_kwargs)
        else:
            return self.func(**call_kwargs)


class Pipeline:
    """Pipeline for orchestrating multi-step operations."""

    def __init__(self, name: str, account: Optional[AWSAccount] = None):
        self.name = name
        self.account = account
        self.steps: List[PipelineStep] = []
        self.context: Dict[str, Any] = {}

    def add_step(self, step: PipelineStep) -> "Pipeline":
        """Add a step to the pipeline."""
        self.steps.append(step)
        return self

    def add_function(
        self,
        name: str,
        func: Callable,
        depends_on: Optional[List[str]] = None,
        **kwargs,
    ) -> "Pipeline":
        """Add a function as a pipeline step."""
        step = FunctionStep(name, func, depends_on, **kwargs)
        return self.add_step(step)

    def set_context(self, key: str, value: Any) -> "Pipeline":
        """Set a value in the pipeline context."""
        self.context[key] = value
        return self

    async def execute(self) -> PipelineResult:
        """Execute all pipeline steps in order."""
        result = PipelineResult(
            pipeline_name=self.name,
            status=StepStatus.RUNNING,
            started_at=datetime.utcnow(),
        )

        # Initialize context with account
        if self.account:
            self.context["account"] = self.account

        completed_steps = set()

        try:
            for step in self.steps:
                # Check dependencies
                for dep in step.depends_on:
                    if dep not in completed_steps:
                        dep_result = result.get_step(dep)
                        if dep_result and not dep_result.success:
                            # Skip if dependency failed
                            step_result = StepResult(
                                step_name=step.name,
                                status=StepStatus.SKIPPED,
                                error=f"Dependency '{dep}' failed",
                            )
                            result.step_results.append(step_result)
                            continue

                # Execute step
                step_result = StepResult(
                    step_name=step.name,
                    status=StepStatus.RUNNING,
                    started_at=datetime.utcnow(),
                )

                try:
                    logger.info(f"Executing step: {step.name}")
                    data = await step.execute(self.context)
                    step_result.data = data
                    step_result.status = StepStatus.COMPLETED

                    # Store result in context
                    self.context[step.name] = data
                    completed_steps.add(step.name)

                except Exception as e:
                    logger.error(f"Step '{step.name}' failed: {e}")
                    step_result.status = StepStatus.FAILED
                    step_result.error = str(e)

                step_result.completed_at = datetime.utcnow()
                if step_result.started_at:
                    step_result.duration_ms = int(
                        (step_result.completed_at - step_result.started_at).total_seconds() * 1000
                    )

                result.step_results.append(step_result)

            # Determine overall status
            failed_steps = [s for s in result.step_results if s.status == StepStatus.FAILED]
            if failed_steps:
                result.status = StepStatus.FAILED
            else:
                result.status = StepStatus.COMPLETED

        except Exception as e:
            logger.error(f"Pipeline '{self.name}' failed: {e}")
            result.status = StepStatus.FAILED

        result.completed_at = datetime.utcnow()
        if result.started_at:
            result.duration_ms = int(
                (result.completed_at - result.started_at).total_seconds() * 1000
            )

        return result


# ============================================================================
# Preset Pipelines
# ============================================================================


def FullScanPipeline(account: AWSAccount) -> Pipeline:
    """Create a full scan pipeline: scan -> detect -> analyze -> report.

    Args:
        account: AWS account to scan

    Returns:
        Configured pipeline
    """
    from agenticops.scan import AWSScanner
    from agenticops.detect import AnomalyDetector
    from agenticops.analyze import RCAEngine
    from agenticops.report import ReportGenerator

    def scan_step(account: AWSAccount) -> dict:
        """Scan AWS resources."""
        scanner = AWSScanner(account)
        results = scanner.scan_all_services()
        saved = scanner.save_results(results)
        return {
            "total_scanned": sum(r.count for r in results if r.success),
            "saved": saved,
            "errors": sum(1 for r in results if not r.success),
        }

    def detect_step(account: AWSAccount) -> dict:
        """Detect anomalies."""
        detector = AnomalyDetector(account)
        results = detector.detect_all()
        total = sum(len(v) for v in results.values())
        return {
            "total_anomalies": total,
            "by_resource": {k: len(v) for k, v in results.items()},
        }

    def analyze_step(account: AWSAccount, detect: dict) -> dict:
        """Analyze detected anomalies."""
        if detect.get("total_anomalies", 0) == 0:
            return {"analyzed": 0}

        from agenticops.models import Anomaly

        rca_engine = RCAEngine(account)
        analyzed = 0

        with get_db_session() as session:
            # Get recent open anomalies
            anomalies = (
                session.query(Anomaly)
                .filter_by(status="open")
                .order_by(Anomaly.detected_at.desc())
                .limit(10)
                .all()
            )

            for anomaly in anomalies:
                try:
                    rca_engine.analyze_with_metrics(anomaly)
                    analyzed += 1
                except Exception as e:
                    logger.warning(f"Failed to analyze anomaly {anomaly.id}: {e}")

        return {"analyzed": analyzed}

    def report_step(account: AWSAccount, scan: dict, detect: dict) -> dict:
        """Generate report."""
        generator = ReportGenerator(account)
        content = generator.generate_daily_report()
        return {
            "report_generated": True,
            "content_length": len(content),
        }

    pipeline = Pipeline("FullScan", account)
    pipeline.add_function("scan", scan_step, account=account)
    pipeline.add_function("detect", detect_step, depends_on=["scan"], account=account)
    pipeline.add_function("analyze", analyze_step, depends_on=["detect"], account=account, detect="$detect")
    pipeline.add_function("report", report_step, depends_on=["scan", "detect"], account=account, scan="$scan", detect="$detect")

    return pipeline


def MonitoringPipeline(account: AWSAccount) -> Pipeline:
    """Create a monitoring pipeline: monitor -> detect -> notify.

    Args:
        account: AWS account to monitor

    Returns:
        Configured pipeline
    """
    from agenticops.detect import AnomalyDetector

    def monitor_step(account: AWSAccount) -> dict:
        """Collect metrics."""
        from agenticops.monitor import MetricsCollector

        collector = MetricsCollector(account)
        try:
            results = collector.collect_all_metrics()
            return {"metrics_collected": len(results)}
        except Exception as e:
            logger.warning(f"Metrics collection warning: {e}")
            return {"metrics_collected": 0}

    def detect_step(account: AWSAccount) -> dict:
        """Detect anomalies."""
        detector = AnomalyDetector(account)
        results = detector.detect_all()
        total = sum(len(v) for v in results.values())
        critical = sum(
            1 for anomalies in results.values()
            for a in anomalies if a.severity == "critical"
        )
        return {
            "total_anomalies": total,
            "critical_anomalies": critical,
        }

    def notify_step(detect: dict) -> dict:
        """Send notifications for critical anomalies."""
        critical = detect.get("critical_anomalies", 0)
        if critical > 0:
            logger.info(f"Would notify about {critical} critical anomalies")
            # Actual notification implementation would go here
        return {"notifications_sent": critical}

    pipeline = Pipeline("Monitoring", account)
    pipeline.add_function("monitor", monitor_step, account=account)
    pipeline.add_function("detect", detect_step, depends_on=["monitor"], account=account)
    pipeline.add_function("notify", notify_step, depends_on=["detect"], detect="$detect")

    return pipeline


def DailyReportPipeline(account: AWSAccount) -> Pipeline:
    """Create a daily report pipeline: scan -> detect -> analyze -> daily_report.

    Args:
        account: AWS account

    Returns:
        Configured pipeline
    """
    from agenticops.scan import AWSScanner
    from agenticops.detect import AnomalyDetector
    from agenticops.report import ReportGenerator

    def scan_step(account: AWSAccount) -> dict:
        """Scan AWS resources."""
        scanner = AWSScanner(account)
        results = scanner.scan_all_services()
        saved = scanner.save_results(results)
        return {
            "total_scanned": sum(r.count for r in results if r.success),
            "saved": saved,
        }

    def detect_step(account: AWSAccount) -> dict:
        """Detect anomalies."""
        detector = AnomalyDetector(account)
        results = detector.detect_all()
        return {
            "total_anomalies": sum(len(v) for v in results.values()),
        }

    def analyze_step(account: AWSAccount) -> dict:
        """Brief analysis of top anomalies."""
        from agenticops.models import Anomaly
        from agenticops.analyze import RCAEngine

        rca_engine = RCAEngine(account)
        analyzed = 0

        with get_db_session() as session:
            # Analyze top 3 critical anomalies
            anomalies = (
                session.query(Anomaly)
                .filter_by(status="open", severity="critical")
                .order_by(Anomaly.detected_at.desc())
                .limit(3)
                .all()
            )

            for anomaly in anomalies:
                try:
                    rca_engine.analyze_with_metrics(anomaly)
                    analyzed += 1
                except Exception:
                    pass

        return {"analyzed": analyzed}

    def daily_report_step(account: AWSAccount) -> dict:
        """Generate daily report."""
        generator = ReportGenerator(account)
        content = generator.generate_daily_report()
        return {
            "report_generated": True,
            "report_path": str(generator.reports_dir),
        }

    pipeline = Pipeline("DailyReport", account)
    pipeline.add_function("scan", scan_step, account=account)
    pipeline.add_function("detect", detect_step, depends_on=["scan"], account=account)
    pipeline.add_function("analyze", analyze_step, depends_on=["detect"], account=account)
    pipeline.add_function("daily_report", daily_report_step, depends_on=["analyze"], account=account)

    return pipeline
