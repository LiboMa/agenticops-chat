"""Tests for pipeline/orchestrator.py — Pipeline framework, steps, and preset pipelines.

Targets coverage from 27% → 60%+.
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from agenticops.pipeline.orchestrator import (
    FunctionStep,
    Pipeline,
    PipelineResult,
    PipelineStep,
    StepResult,
    StepStatus,
)


# ============================================================================
# StepStatus / StepResult / PipelineResult — dataclasses & properties
# ============================================================================


class TestStepStatus:
    def test_enum_values(self):
        assert StepStatus.PENDING == "pending"
        assert StepStatus.RUNNING == "running"
        assert StepStatus.COMPLETED == "completed"
        assert StepStatus.FAILED == "failed"
        assert StepStatus.SKIPPED == "skipped"


class TestStepResult:
    def test_success_when_completed(self):
        r = StepResult(step_name="s1", status=StepStatus.COMPLETED)
        assert r.success is True

    def test_not_success_when_failed(self):
        r = StepResult(step_name="s1", status=StepStatus.FAILED, error="boom")
        assert r.success is False

    def test_not_success_when_pending(self):
        r = StepResult(step_name="s1", status=StepStatus.PENDING)
        assert r.success is False

    def test_data_stored(self):
        r = StepResult(step_name="s1", status=StepStatus.COMPLETED, data={"key": 42})
        assert r.data == {"key": 42}

    def test_duration_fields(self):
        now = datetime.now(timezone.utc)
        r = StepResult(
            step_name="s1",
            status=StepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            duration_ms=123,
        )
        assert r.duration_ms == 123


class TestPipelineResult:
    def test_success_when_completed(self):
        r = PipelineResult(pipeline_name="p1", status=StepStatus.COMPLETED)
        assert r.success is True

    def test_not_success_when_failed(self):
        r = PipelineResult(pipeline_name="p1", status=StepStatus.FAILED)
        assert r.success is False

    def test_get_step_found(self):
        s = StepResult(step_name="scan", status=StepStatus.COMPLETED)
        r = PipelineResult(pipeline_name="p1", status=StepStatus.COMPLETED, step_results=[s])
        assert r.get_step("scan") is s

    def test_get_step_not_found(self):
        r = PipelineResult(pipeline_name="p1", status=StepStatus.COMPLETED, step_results=[])
        assert r.get_step("missing") is None

    def test_get_step_multiple(self):
        s1 = StepResult(step_name="a", status=StepStatus.COMPLETED)
        s2 = StepResult(step_name="b", status=StepStatus.FAILED)
        r = PipelineResult(pipeline_name="p1", status=StepStatus.FAILED, step_results=[s1, s2])
        assert r.get_step("b") is s2

    def test_duration_fields(self):
        now = datetime.now(timezone.utc)
        r = PipelineResult(
            pipeline_name="p1",
            status=StepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            duration_ms=500,
        )
        assert r.duration_ms == 500


# ============================================================================
# PipelineStep (abstract) and FunctionStep
# ============================================================================


class TestPipelineStep:
    def test_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            PipelineStep("step1")

    def test_concrete_subclass(self):
        class MyStep(PipelineStep):
            async def execute(self, context):
                return "ok"

        step = MyStep("test", depends_on=["dep1"])
        assert step.name == "test"
        assert step.depends_on == ["dep1"]

    def test_default_no_deps(self):
        class MyStep(PipelineStep):
            async def execute(self, context):
                return None

        step = MyStep("test")
        assert step.depends_on == []


class TestFunctionStep:
    @pytest.mark.asyncio
    async def test_sync_function(self):
        def add(a, b):
            return a + b

        step = FunctionStep("add", add, a=1, b=2)
        result = await step.execute({})
        assert result == 3

    @pytest.mark.asyncio
    async def test_async_function(self):
        async def fetch():
            return {"data": 42}

        step = FunctionStep("fetch", fetch)
        result = await step.execute({})
        assert result == {"data": 42}

    @pytest.mark.asyncio
    async def test_context_variable_substitution(self):
        def greet(who):
            return f"hello {who}"

        step = FunctionStep("greet", greet, who="$prev_name")
        result = await step.execute({"prev_name": "Alice"})
        assert result == "hello Alice"

    @pytest.mark.asyncio
    async def test_context_var_missing_keeps_literal(self):
        """If $ref not in context, the literal string '$key' is passed."""
        def echo(val):
            return val

        step = FunctionStep("echo", echo, val="$nonexistent")
        result = await step.execute({})
        assert result == "$nonexistent"

    @pytest.mark.asyncio
    async def test_non_dollar_kwarg_unchanged(self):
        def echo(val):
            return val

        step = FunctionStep("echo", echo, val="literal")
        result = await step.execute({"literal": "should not be used"})
        assert result == "literal"

    @pytest.mark.asyncio
    async def test_depends_on(self):
        step = FunctionStep("s", lambda: None, depends_on=["a", "b"])
        assert step.depends_on == ["a", "b"]


# ============================================================================
# Pipeline — core execution engine
# ============================================================================


class TestPipeline:
    def test_init(self):
        p = Pipeline("test-pipeline")
        assert p.name == "test-pipeline"
        assert p.steps == []
        assert p.context == {}
        assert p.account is None

    def test_add_step(self):
        p = Pipeline("p")
        step = FunctionStep("s1", lambda: None)
        ret = p.add_step(step)
        assert ret is p  # fluent API
        assert len(p.steps) == 1

    def test_add_function(self):
        p = Pipeline("p")
        ret = p.add_function("s1", lambda: 42)
        assert ret is p
        assert len(p.steps) == 1
        assert p.steps[0].name == "s1"

    def test_set_context(self):
        p = Pipeline("p")
        ret = p.set_context("key", "value")
        assert ret is p
        assert p.context["key"] == "value"

    @pytest.mark.asyncio
    async def test_execute_empty_pipeline(self):
        p = Pipeline("empty")
        result = await p.execute()
        assert result.success is True
        assert result.status == StepStatus.COMPLETED
        assert result.step_results == []
        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_single_step(self):
        p = Pipeline("single")
        p.add_function("step1", lambda: {"count": 10})
        result = await p.execute()
        assert result.success is True
        assert len(result.step_results) == 1
        assert result.step_results[0].step_name == "step1"
        assert result.step_results[0].data == {"count": 10}
        assert result.step_results[0].duration_ms is not None

    @pytest.mark.asyncio
    async def test_execute_multi_step_sequential(self):
        p = Pipeline("multi")
        p.add_function("a", lambda: 1)
        p.add_function("b", lambda: 2)
        p.add_function("c", lambda: 3)
        result = await p.execute()
        assert result.success is True
        assert len(result.step_results) == 3
        names = [s.step_name for s in result.step_results]
        assert names == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_execute_step_failure_marks_pipeline_failed(self):
        def fail():
            raise ValueError("boom")

        p = Pipeline("fail")
        p.add_function("good", lambda: 1)
        p.add_function("bad", fail)
        result = await p.execute()
        assert result.success is False
        assert result.status == StepStatus.FAILED
        assert result.step_results[0].status == StepStatus.COMPLETED
        assert result.step_results[1].status == StepStatus.FAILED
        assert "boom" in result.step_results[1].error

    @pytest.mark.asyncio
    async def test_context_propagation_between_steps(self):
        """Step results are stored in context and accessible via $ refs."""
        p = Pipeline("ctx")
        p.add_function("produce", lambda: {"val": 42})
        p.add_function("consume", lambda produce: produce["val"], produce="$produce")
        result = await p.execute()
        assert result.success is True
        assert result.step_results[1].data == 42

    @pytest.mark.asyncio
    async def test_dependency_skip_on_failed_dep(self):
        """If a dependency failed, dependent step is skipped."""
        def fail():
            raise RuntimeError("broken")

        p = Pipeline("dep-fail")
        p.add_function("step1", fail)
        p.add_function("step2", lambda: "ok", depends_on=["step1"])
        result = await p.execute()
        assert result.status == StepStatus.FAILED

        step2_result = result.get_step("step2")
        assert step2_result is not None
        assert step2_result.status == StepStatus.SKIPPED
        assert "step1" in step2_result.error

    @pytest.mark.asyncio
    async def test_dependency_passes_when_dep_succeeds(self):
        p = Pipeline("dep-ok")
        p.add_function("step1", lambda: "done")
        p.add_function("step2", lambda: "also done", depends_on=["step1"])
        result = await p.execute()
        assert result.success is True
        assert result.get_step("step2").status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_account_injected_into_context(self):
        account = MagicMock()
        account.name = "test-acct"
        p = Pipeline("acct", account=account)

        captured = {}

        def capture(account):
            captured["account"] = account
            return "ok"

        p.add_function("s1", capture, account="$account")
        # Note: account is set in context by Pipeline.execute()
        # but the $ substitution looks up context keys, and "account" key
        # comes from the pipeline's own context setup
        result = await p.execute()
        # The account should be in the pipeline context
        assert p.context.get("account") is account

    @pytest.mark.asyncio
    async def test_async_step_execution(self):
        async def async_work():
            return "async result"

        p = Pipeline("async")
        p.add_function("s1", async_work)
        result = await p.execute()
        assert result.success is True
        assert result.step_results[0].data == "async result"

    @pytest.mark.asyncio
    async def test_pipeline_timestamps(self):
        p = Pipeline("ts")
        p.add_function("s1", lambda: None)
        result = await p.execute()
        assert result.started_at is not None
        assert result.completed_at is not None
        assert result.completed_at >= result.started_at

    @pytest.mark.asyncio
    async def test_step_timestamps_and_duration(self):
        p = Pipeline("ts2")
        p.add_function("s1", lambda: None)
        result = await p.execute()
        step = result.step_results[0]
        assert step.started_at is not None
        assert step.completed_at is not None
        assert step.duration_ms is not None
        assert step.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_multiple_dependencies(self):
        p = Pipeline("multi-dep")
        p.add_function("a", lambda: 1)
        p.add_function("b", lambda: 2)
        p.add_function("c", lambda: 3, depends_on=["a", "b"])
        result = await p.execute()
        assert result.success is True
        assert result.get_step("c").status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_partial_dep_failure_skips(self):
        """If one of multiple deps fails, step is skipped."""
        def fail():
            raise RuntimeError("fail")

        p = Pipeline("partial")
        p.add_function("a", lambda: 1)
        p.add_function("b", fail)
        p.add_function("c", lambda: 3, depends_on=["a", "b"])
        result = await p.execute()
        assert result.status == StepStatus.FAILED
        c = result.get_step("c")
        assert c.status == StepStatus.SKIPPED


# ============================================================================
# Preset Pipelines — FullScan, Monitoring, DailyReport
# ============================================================================


class TestPresetPipelines:
    """Verify preset pipeline factories create correct structure."""

    def _make_account(self):
        account = MagicMock()
        account.id = 1
        account.name = "test"
        account.provider = "aws"
        account.regions = ["us-east-1"]
        return account

    def test_full_scan_pipeline_structure(self):
        from agenticops.pipeline.orchestrator import FullScanPipeline

        account = self._make_account()
        p = FullScanPipeline(account)
        assert p.name == "FullScan"
        assert len(p.steps) == 4
        names = [s.name for s in p.steps]
        assert names == ["scan", "detect", "analyze", "report"]
        # Check deps
        assert p.steps[0].depends_on == []
        assert p.steps[1].depends_on == ["scan"]
        assert p.steps[2].depends_on == ["detect"]
        assert p.steps[3].depends_on == ["scan", "detect"]

    def test_monitoring_pipeline_structure(self):
        from agenticops.pipeline.orchestrator import MonitoringPipeline

        account = self._make_account()
        p = MonitoringPipeline(account)
        assert p.name == "Monitoring"
        assert len(p.steps) == 3
        names = [s.name for s in p.steps]
        assert names == ["monitor", "detect", "notify"]
        assert p.steps[2].depends_on == ["detect"]

    def test_daily_report_pipeline_structure(self):
        from agenticops.pipeline.orchestrator import DailyReportPipeline

        account = self._make_account()
        p = DailyReportPipeline(account)
        assert p.name == "DailyReport"
        assert len(p.steps) == 4
        names = [s.name for s in p.steps]
        assert names == ["scan", "detect", "analyze", "daily_report"]
        assert p.steps[3].depends_on == ["analyze"]


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_step_exception_does_not_crash_pipeline(self):
        """Pipeline catches step exceptions and continues."""
        call_order = []

        def step_a():
            call_order.append("a")
            return 1

        def step_b():
            call_order.append("b")
            raise Exception("error in b")

        def step_c():
            call_order.append("c")
            return 3

        p = Pipeline("robust")
        p.add_function("a", step_a)
        p.add_function("b", step_b)
        p.add_function("c", step_c)  # no dependency on b
        result = await p.execute()
        assert result.status == StepStatus.FAILED
        assert "a" in call_order
        assert "b" in call_order
        assert "c" in call_order  # c still runs because no dependency on b

    @pytest.mark.asyncio
    async def test_fluent_api_chaining(self):
        p = (
            Pipeline("fluent")
            .set_context("env", "test")
            .add_function("s1", lambda: 1)
            .add_function("s2", lambda: 2)
        )
        assert len(p.steps) == 2
        assert p.context["env"] == "test"
        result = await p.execute()
        assert result.success is True
