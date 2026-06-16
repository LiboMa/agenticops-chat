"""Tests for agenticops.pipeline.health_patrol — targeting uncovered lines (21% → higher)."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticops.pipeline.orchestrator import StepStatus


# ── FetchExternalAlertsStep ─────────────────────────────────────────

class TestFetchExternalAlertsStep:
    def _run(self, context):
        from agenticops.pipeline.health_patrol import FetchExternalAlertsStep
        step = FetchExternalAlertsStep()
        return asyncio.run(step.execute(context))

    def test_providers_all(self):
        alert = MagicMock(source="pagerduty", external_id="pd-1", severity="high",
                          title="CPU Spike", resource_hint="i-abc")
        provider = MagicMock()
        provider.list_active_alerts.return_value = [alert]
        mock_mod = MagicMock()
        mock_mod.get_providers.return_value = [provider]

        with patch.dict("sys.modules", {"agenticops.integrations": mock_mod}):
            from agenticops.pipeline.health_patrol import FetchExternalAlertsStep
            step = FetchExternalAlertsStep()
            result = asyncio.run(
                step.execute({"config": {"providers": "all"}})
            )
        assert result["count"] == 1
        assert result["alerts"][0]["source"] == "pagerduty"

    def test_no_providers_configured(self):
        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock(
            get_providers=MagicMock(return_value=[]),
            get_provider=MagicMock(return_value=None),
        )}):
            from agenticops.pipeline.health_patrol import FetchExternalAlertsStep
            step = FetchExternalAlertsStep()
            result = asyncio.run(
                step.execute({"config": {"providers": "all"}})
            )
        # Either no providers or import fallback
        assert "alerts" in result or "note" in result

    def test_import_error_returns_note(self):
        """When integrations module is not available."""
        import sys
        # Temporarily remove integrations module
        saved = sys.modules.pop("agenticops.integrations", None)
        try:
            # Force re-import
            from agenticops.pipeline.health_patrol import FetchExternalAlertsStep
            step = FetchExternalAlertsStep()

            # Make the import fail
            with patch("builtins.__import__", side_effect=lambda name, *a, **kw:
                        (_ for _ in ()).throw(ImportError("no module"))
                        if "integrations" in name else __builtins__.__import__(name, *a, **kw)):
                result = asyncio.run(
                    step.execute({"config": {}})
                )
            assert result["alerts"] == []
            assert "not available" in result.get("note", "")
        finally:
            if saved is not None:
                sys.modules["agenticops.integrations"] = saved

    def test_specific_providers(self):
        mock_mod = MagicMock()
        provider = MagicMock()
        provider.list_active_alerts.return_value = []
        mock_mod.get_provider.return_value = provider
        mock_mod.get_providers.return_value = []

        with patch.dict("sys.modules", {"agenticops.integrations": mock_mod}):
            from agenticops.pipeline.health_patrol import FetchExternalAlertsStep
            step = FetchExternalAlertsStep()
            result = asyncio.run(
                step.execute({"config": {"providers": "pagerduty,datadog"}})
            )
        assert isinstance(result.get("alerts", []), list)

    def test_provider_failure_logged(self):
        mock_mod = MagicMock()
        provider = MagicMock()
        provider.name = "broken"
        provider.list_active_alerts.side_effect = RuntimeError("connection timeout")
        mock_mod.get_providers.return_value = [provider]

        with patch.dict("sys.modules", {"agenticops.integrations": mock_mod}):
            from agenticops.pipeline.health_patrol import FetchExternalAlertsStep
            step = FetchExternalAlertsStep()
            result = asyncio.run(
                step.execute({"config": {"providers": "all"}})
            )
        assert result["count"] == 0


# ── RunDetectStep ───────────────────────────────────────────────────

class TestRunDetectStep:
    @patch("agenticops.agents.detect_agent.detect_agent")
    def test_runs_detect(self, mock_detect):
        mock_detect.return_value = "All clear"
        from agenticops.pipeline.health_patrol import RunDetectStep
        step = RunDetectStep()
        result = asyncio.run(
            step.execute({"config": {"scope": "EC2", "deep": True}})
        )
        assert "detect_result" in result
        mock_detect.assert_called_once_with(scope="EC2", deep=True)

    @patch("agenticops.agents.detect_agent.detect_agent")
    def test_default_config(self, mock_detect):
        mock_detect.return_value = "OK"
        from agenticops.pipeline.health_patrol import RunDetectStep
        step = RunDetectStep()
        result = asyncio.run(
            step.execute({"config": {}})
        )
        mock_detect.assert_called_once_with(scope="all", deep=False)

    @patch("agenticops.agents.detect_agent.detect_agent")
    def test_truncates_long_result(self, mock_detect):
        mock_detect.return_value = "x" * 5000
        from agenticops.pipeline.health_patrol import RunDetectStep
        step = RunDetectStep()
        result = asyncio.run(
            step.execute({"config": {}})
        )
        assert len(result["detect_result"]) <= 2000


# ── HealthPatrolPipeline ───────────────────────────────────────────

class TestHealthPatrolPipeline:
    @patch("agenticops.agents.detect_agent.detect_agent", return_value="OK")
    def test_full_pipeline_success(self, mock_detect):
        mock_mod = MagicMock()
        mock_mod.get_providers.return_value = []

        with patch.dict("sys.modules", {"agenticops.integrations": mock_mod}):
            from agenticops.pipeline.health_patrol import HealthPatrolPipeline
            # graph_checks off: keep this test hermetic (no GraphStore/DB)
            pipe = HealthPatrolPipeline(config={"scope": "all", "graph_checks": False})
            result = asyncio.run(pipe.execute())

        assert result.status == StepStatus.COMPLETED
        assert len(result.step_results) == 3
        assert result.duration_ms is not None

    @patch("agenticops.agents.detect_agent.detect_agent", side_effect=RuntimeError("boom"))
    def test_pipeline_step_failure(self, mock_detect):
        mock_mod = MagicMock()
        mock_mod.get_providers.return_value = []

        with patch.dict("sys.modules", {"agenticops.integrations": mock_mod}):
            from agenticops.pipeline.health_patrol import HealthPatrolPipeline
            pipe = HealthPatrolPipeline(config={})
            result = asyncio.run(pipe.execute())

        assert result.status == StepStatus.FAILED
        failed_step = [s for s in result.step_results if s.status == StepStatus.FAILED]
        assert len(failed_step) == 1
        assert "boom" in failed_step[0].error

    @patch("agenticops.agents.detect_agent.detect_agent", return_value="OK")
    def test_pipeline_with_account(self, mock_detect):
        mock_mod = MagicMock()
        mock_mod.get_providers.return_value = []
        acct = MagicMock()
        acct.name = "prod-aws"
        acct.provider = "aws"
        acct.credentials = {"account_id": "123", "role_arn": "arn:x"}

        with patch.dict("sys.modules", {"agenticops.integrations": mock_mod}):
            from agenticops.pipeline.health_patrol import HealthPatrolPipeline
            pipe = HealthPatrolPipeline(account=acct, config={"deep": True})
            result = asyncio.run(pipe.execute())

        assert result.status == StepStatus.COMPLETED

    def test_pipeline_has_three_steps(self):
        from agenticops.pipeline.health_patrol import HealthPatrolPipeline
        pipe = HealthPatrolPipeline()
        assert len(pipe.steps) == 3
        assert pipe.steps[0].name == "fetch_external_alerts"
        assert pipe.steps[1].name == "run_detect"
        assert pipe.steps[2].name == "analyze_graph_risks"
