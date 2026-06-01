"""Tests for agenticops.pipeline.health_patrol module."""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass
from typing import List

import pytest

from agenticops.pipeline.health_patrol import (
    FetchExternalAlertsStep,
    HealthPatrolPipeline,
    RunDetectStep,
)
from agenticops.pipeline.orchestrator import StepStatus


# --- Helpers ---

@dataclass
class FakeAlert:
    source: str = "cloudwatch"
    external_id: str = "alert-1"
    severity: str = "high"
    title: str = "CPU High"
    resource_hint: str = "i-12345"


class FakeProvider:
    name = "cloudwatch"

    def __init__(self, alerts: List[FakeAlert] = None, fail: bool = False):
        self._alerts = alerts or []
        self._fail = fail

    def list_active_alerts(self):
        if self._fail:
            raise RuntimeError("Provider error")
        return self._alerts


# --- FetchExternalAlertsStep tests ---

class TestFetchExternalAlertsStep:
    def _run(self, context):
        step = FetchExternalAlertsStep()
        return asyncio.get_event_loop().run_until_complete(step.execute(context))

    def test_no_providers_configured(self):
        step = FetchExternalAlertsStep()
        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock()}):
            import sys
            mock_mod = sys.modules["agenticops.integrations"]
            mock_mod.get_providers.return_value = []
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {"providers": "all"}})
            )
            assert result["alerts"] == []
            assert "No monitoring providers configured" in result["note"]

    def test_providers_all_with_alerts(self):
        step = FetchExternalAlertsStep()
        fake_provider = FakeProvider(alerts=[FakeAlert(), FakeAlert(external_id="alert-2")])

        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock()}):
            import sys
            mock_mod = sys.modules["agenticops.integrations"]
            mock_mod.get_providers.return_value = [fake_provider]
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {"providers": "all"}})
            )
            assert result["count"] == 2
            assert len(result["alerts"]) == 2
            assert result["alerts"][0]["title"] == "CPU High"

    def test_specific_providers(self):
        step = FetchExternalAlertsStep()
        fake_provider = FakeProvider(alerts=[FakeAlert()])

        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock()}):
            import sys
            mock_mod = sys.modules["agenticops.integrations"]
            mock_mod.get_provider.return_value = fake_provider
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {"providers": "cloudwatch"}})
            )
            assert result["count"] == 1

    def test_provider_failure_continues(self):
        step = FetchExternalAlertsStep()
        failing_provider = FakeProvider(fail=True)

        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock()}):
            import sys
            mock_mod = sys.modules["agenticops.integrations"]
            mock_mod.get_providers.return_value = [failing_provider]
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {"providers": "all"}})
            )
            # Should not crash, returns empty alerts
            assert result["alerts"] == []
            assert result["count"] == 0

    def test_import_error_handled(self):
        step = FetchExternalAlertsStep()

        def raise_import(*a, **kw):
            raise ImportError("no module")

        with patch("builtins.__import__", side_effect=raise_import):
            # Direct test - simulate ImportError in execute
            pass

        # Better approach: remove the module to trigger ImportError
        with patch.dict("sys.modules", {"agenticops.integrations": None}):
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {}})
            )
            assert result["alerts"] == []
            assert "not available" in result.get("note", "")

    def test_empty_config_defaults(self):
        step = FetchExternalAlertsStep()

        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock()}):
            import sys
            mock_mod = sys.modules["agenticops.integrations"]
            mock_mod.get_providers.return_value = []
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {}})
            )
            assert result["alerts"] == []


# --- RunDetectStep tests ---

class TestRunDetectStep:
    def test_basic_execution(self):
        step = RunDetectStep()
        assert step.name == "run_detect"
        assert step.depends_on == ["fetch_external_alerts"]

        with patch("agenticops.agents.detect_agent.detect_agent") as mock_detect:
            mock_detect.return_value = "All clear"
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {"scope": "ec2", "deep": True}})
            )
            mock_detect.assert_called_once_with(scope="ec2", deep=True)
            assert "All clear" in result["detect_result"]

    def test_default_config(self):
        step = RunDetectStep()

        with patch("agenticops.agents.detect_agent.detect_agent") as mock_detect:
            mock_detect.return_value = "OK"
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {}})
            )
            mock_detect.assert_called_once_with(scope="all", deep=False)

    def test_long_result_truncated(self):
        step = RunDetectStep()

        with patch("agenticops.agents.detect_agent.detect_agent") as mock_detect:
            mock_detect.return_value = "x" * 5000
            result = asyncio.get_event_loop().run_until_complete(
                step.execute({"config": {}})
            )
            assert len(result["detect_result"]) <= 2000


# --- HealthPatrolPipeline tests ---

class TestHealthPatrolPipeline:
    def test_init_default(self):
        pipeline = HealthPatrolPipeline()
        assert pipeline.name == "HealthPatrol"
        assert len(pipeline.steps) == 2
        assert pipeline.patrol_config == {}
        assert pipeline.account is None

    def test_init_with_config(self):
        config = {"scope": "ec2", "deep": True, "providers": "datadog"}
        pipeline = HealthPatrolPipeline(config=config)
        assert pipeline.patrol_config == config

    def test_init_with_account(self):
        account = MagicMock()
        account.name = "prod"
        account.account_id = "123456789012"
        account.role_arn = "arn:aws:iam::123456789012:role/test"
        pipeline = HealthPatrolPipeline(account=account)
        assert pipeline.account == account

    def test_execute_success(self):
        pipeline = HealthPatrolPipeline()

        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock()}):
            import sys
            mock_mod = sys.modules["agenticops.integrations"]
            mock_mod.get_providers.return_value = []

            with patch("agenticops.agents.detect_agent.detect_agent") as mock_detect:
                mock_detect.return_value = "All healthy"
                result = asyncio.get_event_loop().run_until_complete(
                    pipeline.execute()
                )
                assert result.status == StepStatus.COMPLETED
                assert len(result.step_results) == 2
                assert result.step_results[0].status == StepStatus.COMPLETED
                assert result.step_results[1].status == StepStatus.COMPLETED
                assert result.duration_ms is not None
                assert result.duration_ms >= 0

    def test_execute_first_step_fails(self):
        pipeline = HealthPatrolPipeline()

        with patch.object(
            FetchExternalAlertsStep,
            "execute",
            side_effect=RuntimeError("Connection failed"),
        ):
            result = asyncio.get_event_loop().run_until_complete(pipeline.execute())
            assert result.status == StepStatus.FAILED
            assert len(result.step_results) == 1
            assert result.step_results[0].status == StepStatus.FAILED
            assert "Connection failed" in result.step_results[0].error

    def test_execute_second_step_fails(self):
        pipeline = HealthPatrolPipeline()

        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock()}):
            import sys
            mock_mod = sys.modules["agenticops.integrations"]
            mock_mod.get_providers.return_value = []

            with patch(
                "agenticops.agents.detect_agent.detect_agent",
                side_effect=RuntimeError("Detect crashed"),
            ):
                result = asyncio.get_event_loop().run_until_complete(
                    pipeline.execute()
                )
                assert result.status == StepStatus.FAILED
                assert result.step_results[0].status == StepStatus.COMPLETED
                assert result.step_results[1].status == StepStatus.FAILED

    def test_execute_with_account_context(self):
        account = MagicMock()
        account.name = "staging"
        account.account_id = "111222333444"
        account.role_arn = "arn:aws:iam::111222333444:role/patrol"

        pipeline = HealthPatrolPipeline(account=account, config={"scope": "eks"})

        with patch.dict("sys.modules", {"agenticops.integrations": MagicMock()}):
            import sys
            mock_mod = sys.modules["agenticops.integrations"]
            mock_mod.get_providers.return_value = []

            with patch("agenticops.agents.detect_agent.detect_agent") as mock_detect:
                mock_detect.return_value = "EKS OK"
                result = asyncio.get_event_loop().run_until_complete(
                    pipeline.execute()
                )
                assert result.status == StepStatus.COMPLETED
                mock_detect.assert_called_once_with(scope="eks", deep=False)
