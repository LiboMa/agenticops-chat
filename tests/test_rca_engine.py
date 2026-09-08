"""Unit tests for agenticops.analyze.rca module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agenticops.analyze.rca import BedrockLLM, RCAAnalysis, RCAEngine


class TestRCAAnalysis:
    """Tests for RCAAnalysis dataclass."""

    def test_default_fields(self):
        analysis = RCAAnalysis(root_cause="disk full", confidence_score=0.9)
        assert analysis.root_cause == "disk full"
        assert analysis.confidence_score == 0.9
        assert analysis.contributing_factors == []
        assert analysis.recommendations == []
        assert analysis.related_resources == []
        assert analysis.llm_response == ""

    def test_full_fields(self):
        analysis = RCAAnalysis(
            root_cause="OOM kill",
            confidence_score=0.85,
            contributing_factors=["memory leak", "no limits"],
            recommendations=["set memory limits", "add monitoring"],
            related_resources=["i-123", "i-456"],
            llm_response="raw response",
        )
        assert len(analysis.contributing_factors) == 2
        assert len(analysis.recommendations) == 2
        assert len(analysis.related_resources) == 2
        assert analysis.llm_response == "raw response"

    def test_confidence_boundaries(self):
        low = RCAAnalysis(root_cause="unknown", confidence_score=0.0)
        high = RCAAnalysis(root_cause="known", confidence_score=1.0)
        assert low.confidence_score == 0.0
        assert high.confidence_score == 1.0


class TestBedrockLLM:
    """Tests for BedrockLLM initialization."""

    @patch("agenticops.analyze.rca.settings")
    def test_default_init(self, mock_settings):
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_model_id = "anthropic.claude-3-haiku"
        llm = BedrockLLM()
        assert llm.region == "us-east-1"
        assert llm.model_id == "anthropic.claude-3-haiku"
        assert llm._client is None

    @patch("agenticops.analyze.rca.settings")
    def test_custom_init(self, mock_settings):
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_model_id = "default-model"
        llm = BedrockLLM(region="eu-west-1", model_id="custom-model")
        assert llm.region == "eu-west-1"
        assert llm.model_id == "custom-model"


class TestRCAEngineParseResponse:
    """Tests for RCAEngine._parse_rca_response."""

    @patch("agenticops.analyze.rca.settings")
    def setup_method(self, method, mock_settings=None):
        mock_settings = MagicMock()
        with patch("agenticops.analyze.rca.settings", mock_settings):
            self.engine = RCAEngine.__new__(RCAEngine)
            self.engine.llm = MagicMock()
            self.engine.monitor = None
            self.engine.account = None

    def test_valid_json_response(self):
        response = json.dumps(
            {
                "root_cause": "CPU throttling due to burst credit exhaustion",
                "confidence_score": 0.92,
                "contributing_factors": ["high traffic", "undersized instance"],
                "recommendations": ["upgrade instance", "add autoscaling"],
                "related_resources": ["i-abc123"],
            }
        )
        result = self.engine._parse_rca_response(response)
        assert result.root_cause == "CPU throttling due to burst credit exhaustion"
        assert result.confidence_score == 0.92
        assert "high traffic" in result.contributing_factors
        assert len(result.recommendations) == 2
        assert "i-abc123" in result.related_resources

    def test_json_embedded_in_text(self):
        response = """Here is my analysis:

```json
{
    "root_cause": "Network partition",
    "confidence_score": 0.75,
    "contributing_factors": ["AZ failure"],
    "recommendations": ["multi-AZ deploy"],
    "related_resources": []
}
```

Hope this helps!"""
        result = self.engine._parse_rca_response(response)
        assert result.root_cause == "Network partition"
        assert result.confidence_score == 0.75

    def test_invalid_json_fallback(self):
        response = "This is not JSON but a plain text analysis of the issue."
        result = self.engine._parse_rca_response(response)
        # Falls back to raw text as root cause
        assert "not JSON" in result.root_cause
        assert result.confidence_score == 0.5

    def test_malformed_json_fallback(self):
        response = '{"root_cause": "incomplete json'
        result = self.engine._parse_rca_response(response)
        assert result.confidence_score == 0.5

    def test_missing_fields_use_defaults(self):
        response = json.dumps({"root_cause": "unknown issue"})
        result = self.engine._parse_rca_response(response)
        assert result.root_cause == "unknown issue"
        assert result.confidence_score == 0.5
        assert result.contributing_factors == []
        assert result.recommendations == []
        assert result.related_resources == []

    def test_no_json_braces(self):
        response = "No braces at all in this response"
        result = self.engine._parse_rca_response(response)
        assert result.root_cause == response
        assert result.confidence_score == 0.5

    def test_confidence_as_string(self):
        response = json.dumps(
            {
                "root_cause": "test",
                "confidence_score": "0.88",
                "contributing_factors": [],
                "recommendations": [],
                "related_resources": [],
            }
        )
        result = self.engine._parse_rca_response(response)
        assert result.confidence_score == 0.88

    def test_long_response_truncated(self):
        long_text = "A" * 2000
        response = long_text  # no JSON
        result = self.engine._parse_rca_response(response)
        assert len(result.root_cause) <= 1000

    def test_nested_json_takes_outermost(self):
        response = '{"root_cause": "outer", "confidence_score": 0.9, "contributing_factors": [], "recommendations": [], "related_resources": [], "nested": {"root_cause": "inner"}}'
        result = self.engine._parse_rca_response(response)
        assert result.root_cause == "outer"


class TestRCAEngineBuildPrompt:
    """Tests for RCAEngine._build_rca_prompt."""

    @patch("agenticops.analyze.rca.settings")
    def setup_method(self, method, mock_settings=None):
        with patch("agenticops.analyze.rca.settings", MagicMock()):
            self.engine = RCAEngine.__new__(RCAEngine)
            self.engine.llm = MagicMock()
            self.engine.monitor = None
            self.engine.account = None

    def _make_anomaly(self, **kwargs):
        anomaly = MagicMock()
        anomaly.title = kwargs.get("title", "High CPU")
        anomaly.description = kwargs.get("description", "CPU > 95%")
        anomaly.resource_id = kwargs.get("resource_id", "i-abc123")
        anomaly.resource_type = kwargs.get("resource_type", "ec2")
        anomaly.region = kwargs.get("region", "us-east-1")
        anomaly.severity = kwargs.get("severity", "high")
        anomaly.detected_at = kwargs.get("detected_at", "2026-08-07T00:00:00Z")
        anomaly.anomaly_type = kwargs.get("anomaly_type", "metric_spike")
        anomaly.metric_name = kwargs.get("metric_name", "CPUUtilization")
        anomaly.expected_value = kwargs.get("expected_value", 40.0)
        anomaly.actual_value = kwargs.get("actual_value", 98.5)
        anomaly.deviation_percent = kwargs.get("deviation_percent", 146.25)
        anomaly.raw_data = kwargs.get("raw_data", None)
        return anomaly

    def test_prompt_contains_anomaly_details(self):
        anomaly = self._make_anomaly()
        prompt = self.engine._build_rca_prompt(anomaly, {})
        assert "High CPU" in prompt
        assert "i-abc123" in prompt
        assert "us-east-1" in prompt
        assert "CPUUtilization" in prompt

    def test_prompt_includes_context(self):
        anomaly = self._make_anomaly()
        context = {"related_events": ["deploy at 23:45"]}
        prompt = self.engine._build_rca_prompt(anomaly, context)
        assert "deploy at 23:45" in prompt

    def test_prompt_empty_context(self):
        anomaly = self._make_anomaly()
        prompt = self.engine._build_rca_prompt(anomaly, {})
        # Empty dict is falsy, so it triggers the "No additional context" branch
        assert "No additional context" in prompt

    def test_prompt_none_context(self):
        anomaly = self._make_anomaly()
        # When context is empty dict after defaulting
        prompt = self.engine._build_rca_prompt(anomaly, {})
        assert "JSON" in prompt  # asks for JSON format


class TestRCAEngineAnalyze:
    """Tests for RCAEngine.analyze_anomaly with mocked LLM."""

    @patch("agenticops.analyze.rca.settings")
    def setup_method(self, method, mock_settings=None):
        with patch("agenticops.analyze.rca.settings", MagicMock()):
            self.engine = RCAEngine.__new__(RCAEngine)
            self.engine.llm = MagicMock()
            self.engine.monitor = None
            self.engine.account = None

    def _make_anomaly(self):
        anomaly = MagicMock()
        anomaly.id = 42
        anomaly.title = "High CPU"
        anomaly.description = "CPU spike"
        anomaly.resource_id = "i-abc123"
        anomaly.resource_type = "ec2"
        anomaly.region = "us-east-1"
        anomaly.severity = "high"
        anomaly.detected_at = "2026-08-07T00:00:00Z"
        anomaly.anomaly_type = "metric_spike"
        anomaly.metric_name = "CPUUtilization"
        anomaly.expected_value = 40.0
        anomaly.actual_value = 98.5
        anomaly.deviation_percent = 146.25
        anomaly.raw_data = None
        return anomaly

    def test_analyze_success_no_save(self):
        self.engine.llm.invoke.return_value = json.dumps(
            {
                "root_cause": "burst credits exhausted",
                "confidence_score": 0.9,
                "contributing_factors": ["sustained load"],
                "recommendations": ["upgrade to m5"],
                "related_resources": [],
            }
        )
        anomaly = self._make_anomaly()
        result = self.engine.analyze_anomaly(anomaly, save=False)
        assert result.root_cause == "burst credits exhausted"
        assert result.confidence_score == 0.9
        self.engine.llm.invoke.assert_called_once()

    def test_analyze_llm_failure(self):
        self.engine.llm.invoke.side_effect = Exception("Bedrock timeout")
        anomaly = self._make_anomaly()
        result = self.engine.analyze_anomaly(anomaly, save=False)
        assert "failed" in result.root_cause.lower()
        assert result.confidence_score == 0.0

    @patch("agenticops.analyze.rca.get_session")
    def test_analyze_with_save(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        self.engine.llm.invoke.return_value = json.dumps(
            {
                "root_cause": "disk full",
                "confidence_score": 0.8,
                "contributing_factors": [],
                "recommendations": [],
                "related_resources": [],
            }
        )
        self.engine.llm.model_id = "claude-3"
        anomaly = self._make_anomaly()
        result = self.engine.analyze_anomaly(anomaly, save=True)
        assert result.root_cause == "disk full"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()


class TestRCAEngineBatchAnalyze:
    """Tests for batch_analyze."""

    @patch("agenticops.analyze.rca.settings")
    def setup_method(self, method, mock_settings=None):
        with patch("agenticops.analyze.rca.settings", MagicMock()):
            self.engine = RCAEngine.__new__(RCAEngine)
            self.engine.llm = MagicMock()
            self.engine.monitor = None
            self.engine.account = None

    def _make_anomaly(self, id_val):
        anomaly = MagicMock()
        anomaly.id = id_val
        anomaly.title = f"Anomaly {id_val}"
        anomaly.description = "desc"
        anomaly.resource_id = f"r-{id_val}"
        anomaly.resource_type = "ec2"
        anomaly.region = "us-east-1"
        anomaly.severity = "medium"
        anomaly.detected_at = "2026-08-07"
        anomaly.anomaly_type = "spike"
        anomaly.metric_name = "CPU"
        anomaly.expected_value = 50
        anomaly.actual_value = 90
        anomaly.deviation_percent = 80.0
        anomaly.raw_data = None
        return anomaly

    def test_batch_multiple(self):
        self.engine.llm.invoke.return_value = json.dumps(
            {
                "root_cause": "generic issue",
                "confidence_score": 0.7,
                "contributing_factors": [],
                "recommendations": [],
                "related_resources": [],
            }
        )
        anomalies = [self._make_anomaly(i) for i in range(3)]
        results = self.engine.batch_analyze(anomalies, save=False)
        assert len(results) == 3
        assert all(r.root_cause == "generic issue" for r in results.values())

    def test_batch_partial_failure(self):
        call_count = [0]

        def side_effect(prompt, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("LLM error")
            return json.dumps(
                {
                    "root_cause": "ok",
                    "confidence_score": 0.8,
                    "contributing_factors": [],
                    "recommendations": [],
                    "related_resources": [],
                }
            )

        self.engine.llm.invoke.side_effect = side_effect
        anomalies = [self._make_anomaly(i) for i in range(3)]
        results = self.engine.batch_analyze(anomalies, save=False)
        assert len(results) == 3
        # Second one should have failed
        assert results[1].confidence_score == 0.0
        assert results[0].root_cause == "ok"
        assert results[2].root_cause == "ok"
