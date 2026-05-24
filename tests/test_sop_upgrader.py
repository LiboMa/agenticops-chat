"""Unit tests for agenticops.pipeline.sop_upgrader — covers helpers, fallback, and LLM paths."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agenticops.pipeline.sop_upgrader import (
    _extract_keywords,
    _generate_fallback_sop,
    generate_new_sop,
    upgrade_existing_sop,
)


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_basic_extraction(self):
        data = {
            "resource_type": "EC2",
            "issue_pattern": "high CPU utilisation spike",
            "root_cause": "runaway process consuming resources",
            "title": "EC2 CPU Spike Remediation",
        }
        kw = _extract_keywords(data)
        assert "ec2" in kw
        assert isinstance(kw, list)
        assert len(kw) <= 8

    def test_empty_case_data(self):
        kw = _extract_keywords({})
        assert kw == []

    def test_filters_short_and_stopwords(self):
        data = {"issue_pattern": "the and for was with that this ok ab"}
        kw = _extract_keywords(data)
        # none of the stopwords or <= 3-char words should appear
        for stop in ("the", "and", "for", "was", "with", "that", "this", "ok", "ab"):
            assert stop not in kw

    def test_max_eight_keywords(self):
        data = {
            "resource_type": "Lambda",
            "issue_pattern": "timeout invocation cold start latency spike error",
            "root_cause": "memory allocation misconfiguration provisioned concurrency",
            "title": "Lambda timeout remediation plan",
        }
        kw = _extract_keywords(data)
        assert len(kw) <= 8


# ---------------------------------------------------------------------------
# _generate_fallback_sop
# ---------------------------------------------------------------------------

class TestGenerateFallbackSop:
    def test_contains_frontmatter(self):
        data = {
            "resource_type": "EKS",
            "issue_pattern": "pod crash loop",
            "severity": "high",
            "title": "EKS Pod CrashLoopBackOff",
            "symptoms": "Pods restarting repeatedly",
            "fix_steps": "1. Check logs\n2. Fix config",
            "rollback_plan": "Revert deployment",
            "verification_steps": "kubectl get pods",
            "prevention": "Add liveness probe",
        }
        sop = _generate_fallback_sop(data, "2026-04-25")
        assert sop.startswith("---")
        assert "resource_type: EKS" in sop
        assert "issue_pattern: pod crash loop" in sop
        assert "severity: high" in sop
        assert "# EKS Pod CrashLoopBackOff" in sop
        assert "Pods restarting repeatedly" in sop
        assert "Add liveness probe" in sop

    def test_defaults_for_missing_fields(self):
        sop = _generate_fallback_sop({}, "2026-04-25")
        assert "resource_type: Unknown" in sop
        assert "severity: medium" in sop
        assert "## Fix Procedure" in sop
        assert "## Prevention" in sop


# ---------------------------------------------------------------------------
# generate_new_sop (LLM path + fallback)
# ---------------------------------------------------------------------------

class TestGenerateNewSop:
    @patch("agenticops.pipeline.sop_upgrader._call_llm")
    def test_uses_llm_result(self, mock_llm):
        mock_llm.return_value = "---\nresource_type: EC2\n---\n# SOP Title"
        result = generate_new_sop({
            "resource_type": "EC2",
            "issue_pattern": "disk full",
            "severity": "high",
            "title": "Disk Full SOP",
        })
        assert result == "---\nresource_type: EC2\n---\n# SOP Title"
        mock_llm.assert_called_once()

    @patch("agenticops.pipeline.sop_upgrader._call_llm", return_value=None)
    def test_falls_back_when_llm_fails(self, mock_llm):
        result = generate_new_sop({
            "resource_type": "RDS",
            "issue_pattern": "connection exhaustion",
            "severity": "critical",
            "title": "RDS Connection Pool Exhaustion",
        })
        assert "resource_type: RDS" in result
        assert "# RDS Connection Pool Exhaustion" in result


# ---------------------------------------------------------------------------
# upgrade_existing_sop
# ---------------------------------------------------------------------------

class TestUpgradeExistingSop:
    EXISTING = "---\nresource_type: EC2\n---\n# Original SOP"

    @patch("agenticops.pipeline.sop_upgrader._call_llm")
    def test_returns_upgraded_sop(self, mock_llm):
        mock_llm.return_value = "---\nresource_type: EC2\n---\n# Upgraded SOP"
        result = upgrade_existing_sop(self.EXISTING, {"new": "data"})
        assert "Upgraded SOP" in result

    @patch("agenticops.pipeline.sop_upgrader._call_llm", return_value=None)
    def test_returns_original_on_failure(self, mock_llm):
        result = upgrade_existing_sop(self.EXISTING, {"new": "data"})
        assert result == self.EXISTING


# ---------------------------------------------------------------------------
# _call_llm
# ---------------------------------------------------------------------------

class TestCallLlm:
    @patch("boto3.client")
    @patch("agenticops.pipeline.sop_upgrader.settings")
    def test_successful_call(self, mock_settings, mock_boto3_client):
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_model_id = "anthropic.claude-v2"

        body_payload = json.dumps({
            "content": [{"text": "---\nresource_type: EC2\n---\n# Test SOP"}]
        }).encode()
        mock_resp_body = MagicMock()
        mock_resp_body.read.return_value = body_payload

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": mock_resp_body}
        mock_boto3_client.return_value = mock_client

        from agenticops.pipeline.sop_upgrader import _call_llm
        result = _call_llm("test prompt")
        assert "resource_type: EC2" in result
        mock_client.invoke_model.assert_called_once()

    @patch("boto3.client")
    @patch("agenticops.pipeline.sop_upgrader.settings")
    def test_strips_code_fences(self, mock_settings, mock_boto3_client):
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_model_id = "anthropic.claude-v2"

        body_payload = json.dumps({
            "content": [{"text": "```markdown\n# My SOP\nContent here\n```"}]
        }).encode()
        mock_resp_body = MagicMock()
        mock_resp_body.read.return_value = body_payload
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": mock_resp_body}
        mock_boto3_client.return_value = mock_client

        from agenticops.pipeline.sop_upgrader import _call_llm
        result = _call_llm("test prompt")
        assert not result.startswith("```")
        assert not result.endswith("```")
        assert "# My SOP" in result

    @patch("boto3.client")
    @patch("agenticops.pipeline.sop_upgrader.settings")
    def test_returns_none_on_exception(self, mock_settings, mock_boto3_client):
        mock_settings.bedrock_region = "us-east-1"
        mock_settings.bedrock_model_id = "anthropic.claude-v2"
        mock_boto3_client.side_effect = Exception("connection error")

        from agenticops.pipeline.sop_upgrader import _call_llm
        result = _call_llm("test prompt")
        assert result is None
