"""Tests for the ITSM module — adapters + bridge logic.

Covers:
  - ITSMResult dataclass
  - ServiceNowAdapter (dry_run mode)
  - JiraAdapter (dry_run mode)
  - Bridge wiring: build_adapters, start/stop
  - Bridge event handlers via handle_pipeline_event
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

from agenticops.itsm.base import ITSMAdapter, ITSMResult
from agenticops.itsm.jira import JiraAdapter
from agenticops.itsm.servicenow import ServiceNowAdapter


# ════════════════════════════════════════════════════════════════════
# ITSMResult
# ════════════════════════════════════════════════════════════════════


class TestITSMResult:
    def test_success(self):
        r = ITSMResult(ok=True, external_id="abc", external_ref="INC001")
        assert r.ok
        assert r.external_id == "abc"
        assert r.error is None

    def test_failure_classmethod(self):
        r = ITSMResult.failure("timeout")
        assert not r.ok
        assert r.error == "timeout"
        assert r.external_id is None

    def test_detail_defaults_to_empty_dict(self):
        r = ITSMResult(ok=True)
        assert r.detail == {}


# ════════════════════════════════════════════════════════════════════
# ServiceNowAdapter (dry_run)
# ════════════════════════════════════════════════════════════════════


class TestServiceNowAdapterDryRun:
    @pytest.fixture
    def adapter(self):
        return ServiceNowAdapter(
            instance_url="https://dev123.service-now.com",
            username="admin",
            password="secret",
            dry_run=True,
        )

    def test_create_incident(self, adapter):
        r = adapter.create_incident(
            title="High CPU on prod-web-1",
            description="CPU at 99% for 10 mins",
            severity="high",
            correlation_id="AIOPS-HI-42",
            resource_id="i-0abc123",
        )
        assert r.ok
        assert "DRY" in r.external_ref
        assert r.detail["dry_run"] is True
        assert r.detail["method"] == "POST"
        assert "incident" in r.detail["path"]

    def test_update_incident_state_valid(self, adapter):
        r = adapter.update_incident_state("sys-001", "in_progress")
        assert r.ok

    def test_update_incident_state_invalid(self, adapter):
        r = adapter.update_incident_state("sys-001", "bogus_state")
        assert not r.ok
        assert "unknown" in r.error

    def test_append_worknote(self, adapter):
        r = adapter.append_worknote("sys-001", "RCA completed: disk full")
        assert r.ok
        assert r.detail["body"]["work_notes"] == "RCA completed: disk full"

    def test_resolve_incident(self, adapter):
        r = adapter.resolve_incident("sys-001", "Fixed by clearing temp files")
        assert r.ok
        body = r.detail["body"]
        assert body["state"] == "6"
        assert "close_notes" in body

    def test_create_change_normal(self, adapter):
        r = adapter.create_change(
            incident_external_id="sys-001",
            change_type="normal",
            title="Scale up web tier",
            description="Add 2 instances",
            implementation_plan="1. terraform apply\n2. verify",
            backout_plan="terraform destroy added instances",
            risk_level="L2",
            correlation_id="AIOPS-FP-7",
        )
        assert r.ok
        assert "normal" in r.detail["path"]

    def test_create_change_emergency(self, adapter):
        r = adapter.create_change(
            incident_external_id=None,
            change_type="emergency",
            title="Emergency rollback",
            description="Bad deploy",
            implementation_plan="revert",
            backout_plan="re-deploy",
            risk_level="L3",
            correlation_id="AIOPS-FP-8",
        )
        assert r.ok
        assert "emergency" in r.detail["path"]

    def test_create_change_standard_no_template(self, adapter):
        r = adapter.create_change(
            incident_external_id=None,
            change_type="standard",
            title="Auto-restart service",
            description="Standard fix",
            implementation_plan="systemctl restart",
            backout_plan="systemctl stop",
            risk_level="L0",
            correlation_id="AIOPS-FP-9",
        )
        assert r.ok
        # Falls back to normal when no template configured
        assert "normal" in r.detail["path"]

    def test_create_change_standard_with_template(self, adapter):
        adapter.standard_template_id = "tmpl-123"
        r = adapter.create_change(
            incident_external_id=None,
            change_type="standard",
            title="Auto-restart service",
            description="Standard fix",
            implementation_plan="systemctl restart",
            backout_plan="systemctl stop",
            risk_level="L0",
            correlation_id="AIOPS-FP-10",
        )
        assert r.ok
        assert "standard/tmpl-123" in r.detail["path"]

    def test_update_change_state_valid(self, adapter):
        r = adapter.update_change_state("chg-001", "implement")
        assert r.ok

    def test_update_change_state_invalid(self, adapter):
        r = adapter.update_change_state("chg-001", "nope")
        assert not r.ok

    def test_get_change_approval_dry_run(self, adapter):
        r = adapter.get_change_approval("chg-001")
        assert r.ok
        assert r.detail["approval"] == "approved"

    def test_close_change_success(self, adapter):
        r = adapter.close_change("chg-001", success=True, notes="All good")
        assert r.ok
        assert r.detail["body"]["close_code"] == "successful"

    def test_close_change_failure(self, adapter):
        r = adapter.close_change("chg-001", success=False, notes="Rollback applied")
        assert r.ok
        assert r.detail["body"]["close_code"] == "unsuccessful"

    def test_append_change_worknote(self, adapter):
        r = adapter.append_change_worknote("chg-001", "Step 1 done")
        assert r.ok

    def test_name(self, adapter):
        assert adapter.name == "servicenow"


# ════════════════════════════════════════════════════════════════════
# JiraAdapter (dry_run)
# ════════════════════════════════════════════════════════════════════


class TestJiraAdapterDryRun:
    @pytest.fixture
    def adapter(self):
        return JiraAdapter(
            base_url="https://myorg.atlassian.net",
            email="bot@myorg.com",
            api_token="token123",
            project_key="OPS",
            dry_run=True,
        )

    def test_create_incident(self, adapter):
        r = adapter.create_incident(
            title="DB connection pool exhausted",
            description="Pool at max (100/100)",
            severity="critical",
            correlation_id="AIOPS-HI-99",
            resource_id="rds-prod-main",
        )
        assert r.ok
        assert "OPS-DRY" in r.external_ref
        assert r.detail["dry_run"] is True

    def test_update_incident_state(self, adapter):
        # Jira uses worknote-based state tracking
        r = adapter.update_incident_state("OPS-100", "in_progress")
        assert r.ok

    def test_append_worknote(self, adapter):
        r = adapter.append_worknote("OPS-100", "Investigating RCA")
        assert r.ok

    def test_resolve_incident(self, adapter):
        r = adapter.resolve_incident("OPS-100", "Connection pool resized")
        assert r.ok

    def test_create_change(self, adapter):
        r = adapter.create_change(
            incident_external_id="OPS-100",
            change_type="normal",
            title="Resize connection pool",
            description="Increase from 100 to 200",
            implementation_plan="1. Update config\n2. Rolling restart",
            backout_plan="Revert config",
            risk_level="L1",
            correlation_id="AIOPS-FP-50",
        )
        assert r.ok
        assert r.detail["dry_run"] is True

    def test_update_change_state(self, adapter):
        r = adapter.update_change_state("OPS-200", "review")
        assert r.ok

    def test_get_change_approval_dry_run(self, adapter):
        r = adapter.get_change_approval("OPS-200")
        assert r.ok
        assert r.detail["approval"] == "approved"

    def test_close_change(self, adapter):
        r = adapter.close_change("OPS-200", success=True, notes="Completed")
        assert r.ok

    def test_adf_helper(self, adapter):
        doc = JiraAdapter._adf("Hello world")
        assert doc["type"] == "doc"
        assert doc["content"][0]["content"][0]["text"] == "Hello world"

    def test_name(self, adapter):
        assert adapter.name == "jira"


# ════════════════════════════════════════════════════════════════════
# ServiceNowAdapter (live mode - mocked httpx)
# ════════════════════════════════════════════════════════════════════


class TestServiceNowAdapterLive:
    @pytest.fixture
    def adapter(self):
        return ServiceNowAdapter(
            instance_url="https://dev123.service-now.com",
            username="admin",
            password="secret",
            dry_run=False,
        )

    def test_create_incident_success(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"result": {"sys_id": "abc123", "number": "INC0010001"}}'
        mock_resp.json.return_value = {"result": {"sys_id": "abc123", "number": "INC0010001"}}

        with patch("httpx.request", return_value=mock_resp):
            r = adapter.create_incident(
                title="Test", description="desc", severity="high",
                correlation_id="test-1",
            )
        assert r.ok
        assert r.external_id == "abc123"
        assert r.external_ref == "INC0010001"

    def test_create_incident_http_error(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("httpx.request", return_value=mock_resp):
            r = adapter.create_incident(
                title="Test", description="desc", severity="high",
                correlation_id="test-2",
            )
        assert not r.ok
        assert "500" in r.error

    def test_create_incident_network_error(self, adapter):
        import httpx as httpx_mod

        with patch("httpx.request", side_effect=httpx_mod.ConnectError("refused")):
            r = adapter.create_incident(
                title="Test", description="desc", severity="high",
                correlation_id="test-3",
            )
        assert not r.ok
        assert "request failed" in r.error


class TestJiraAdapterLive:
    @pytest.fixture
    def adapter(self):
        return JiraAdapter(
            base_url="https://myorg.atlassian.net",
            email="bot@myorg.com",
            api_token="token123",
            project_key="OPS",
            dry_run=False,
        )

    def test_create_incident_success(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"key": "OPS-42"}'
        mock_resp.json.return_value = {"key": "OPS-42"}

        with patch("httpx.request", return_value=mock_resp):
            r = adapter.create_incident(
                title="Test", description="desc", severity="high",
                correlation_id="test-1",
            )
        assert r.ok
        assert r.external_id == "OPS-42"
        assert "browse/OPS-42" in r.url

    def test_get_change_approval_live(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"values": [{"finalDecision": "approved"}]}'
        mock_resp.json.return_value = {"values": [{"finalDecision": "approved"}]}

        with patch("httpx.request", return_value=mock_resp):
            r = adapter.get_change_approval("OPS-200")
        assert r.ok
        assert r.detail["approval"] == "approved"

    def test_get_change_approval_declined(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"values": [{"finalDecision": "declined"}]}'
        mock_resp.json.return_value = {"values": [{"finalDecision": "declined"}]}

        with patch("httpx.request", return_value=mock_resp):
            r = adapter.get_change_approval("OPS-200")
        assert r.ok
        assert r.detail["approval"] == "rejected"


# ════════════════════════════════════════════════════════════════════
# Bridge logic
# ════════════════════════════════════════════════════════════════════


class TestBridge:
    @pytest.fixture(autouse=True)
    def _reset_bridge(self):
        """Reset bridge module state between tests."""
        import agenticops.itsm.bridge as bridge_mod
        bridge_mod._adapters = []
        bridge_mod._started = False
        yield
        bridge_mod._adapters = []
        bridge_mod._started = False

    def test_build_adapters_empty_when_no_config(self):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.itsm_servicenow_url = ""
            mock_settings.itsm_jira_url = ""
            from agenticops.itsm.bridge import build_adapters
            adapters = build_adapters()
        assert adapters == []

    def test_build_adapters_servicenow(self):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.itsm_servicenow_url = "https://dev.service-now.com"
            mock_settings.itsm_servicenow_user = "admin"
            mock_settings.itsm_servicenow_password = "pw"
            mock_settings.itsm_dry_run = True
            mock_settings.itsm_jira_url = ""
            from agenticops.itsm.bridge import build_adapters
            adapters = build_adapters()
        assert len(adapters) == 1
        assert adapters[0].name == "servicenow"

    def test_build_adapters_jira(self):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.itsm_servicenow_url = ""
            mock_settings.itsm_jira_url = "https://myorg.atlassian.net"
            mock_settings.itsm_jira_email = "bot@org.com"
            mock_settings.itsm_jira_api_token = "tok"
            mock_settings.itsm_jira_project_key = "OPS"
            mock_settings.itsm_dry_run = True
            from agenticops.itsm.bridge import build_adapters
            adapters = build_adapters()
        assert len(adapters) == 1
        assert adapters[0].name == "jira"

    def test_start_bridge_disabled(self):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.itsm_enabled = False
            from agenticops.itsm.bridge import start_itsm_bridge
            result = start_itsm_bridge()
        assert result is False

    def test_start_bridge_no_adapters(self):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.itsm_enabled = True
            mock_settings.itsm_servicenow_url = ""
            mock_settings.itsm_jira_url = ""
            from agenticops.itsm.bridge import start_itsm_bridge
            result = start_itsm_bridge()
        assert result is False

    def test_start_bridge_success(self):
        with patch("agenticops.config.settings") as mock_settings:
            mock_settings.itsm_enabled = True
            mock_settings.itsm_servicenow_url = "https://dev.service-now.com"
            mock_settings.itsm_servicenow_user = "admin"
            mock_settings.itsm_servicenow_password = "pw"
            mock_settings.itsm_dry_run = True
            mock_settings.itsm_jira_url = ""
            with patch("agenticops.services.pipeline_events.subscribe"):
                from agenticops.itsm.bridge import start_itsm_bridge
                result = start_itsm_bridge()
        assert result is True

    def test_stop_bridge(self):
        import agenticops.itsm.bridge as bridge_mod
        bridge_mod._started = True
        bridge_mod._adapters = [MagicMock()]
        with patch("agenticops.services.pipeline_events.unsubscribe"):
            bridge_mod.stop_itsm_bridge()
        assert bridge_mod._started is False
        assert bridge_mod._adapters == []

    def test_handle_pipeline_event_unknown_type(self):
        """Unknown event types are silently ignored."""
        from agenticops.itsm.bridge import handle_pipeline_event
        # Should not raise
        handle_pipeline_event(1, "unknown_event", "unknown", "ok", {})

    def test_handle_pipeline_event_issue_created(self):
        """issue_created creates an incident on each adapter."""
        import agenticops.itsm.bridge as bridge_mod

        mock_adapter = MagicMock(spec=ServiceNowAdapter)
        mock_adapter.name = "servicenow"
        mock_adapter.create_incident.return_value = ITSMResult(
            ok=True, external_id="sys-001", external_ref="INC001"
        )
        bridge_mod._adapters = [mock_adapter]

        mock_issue = MagicMock()
        mock_issue.id = 42
        mock_issue.title = "High CPU"
        mock_issue.description = "CPU at 99%"
        mock_issue.severity = "high"
        mock_issue.resource_id = "i-abc"
        mock_issue.trace_id = "trace-1"

        with patch("agenticops.itsm.bridge._get_link", return_value=None), \
             patch("agenticops.itsm.bridge._save_link"), \
             patch("agenticops.itsm.bridge._load_issue", return_value=mock_issue):
            bridge_mod.handle_pipeline_event(42, "issue_created", "open", "ok", {})

        mock_adapter.create_incident.assert_called_once()
        call_kwargs = mock_adapter.create_incident.call_args.kwargs
        assert "High CPU" in call_kwargs["title"]
        assert call_kwargs["severity"] == "high"

    def test_handle_pipeline_event_issue_created_already_linked(self):
        """If link already exists, adapter is not called again (idempotent)."""
        import agenticops.itsm.bridge as bridge_mod

        mock_adapter = MagicMock(spec=ServiceNowAdapter)
        mock_adapter.name = "servicenow"
        bridge_mod._adapters = [mock_adapter]

        mock_issue = MagicMock()
        mock_issue.id = 42

        with patch("agenticops.itsm.bridge._get_link", return_value="sys-existing"), \
             patch("agenticops.itsm.bridge._load_issue", return_value=mock_issue):
            bridge_mod.handle_pipeline_event(42, "issue_created", "open", "ok", {})

        mock_adapter.create_incident.assert_not_called()

    def test_handle_rca_completed(self):
        import agenticops.itsm.bridge as bridge_mod

        mock_adapter = MagicMock(spec=ServiceNowAdapter)
        mock_adapter.name = "servicenow"
        mock_adapter.update_incident_state.return_value = ITSMResult(ok=True)
        mock_adapter.append_worknote.return_value = ITSMResult(ok=True)
        bridge_mod._adapters = [mock_adapter]

        with patch("agenticops.itsm.bridge._get_link", return_value="sys-001"):
            bridge_mod.handle_pipeline_event(
                42, "rca_completed", "root_cause_identified", "ok",
                {"root_cause": "Disk full on /var", "confidence": 0.92},
            )

        mock_adapter.update_incident_state.assert_called_once_with("sys-001", "in_progress")
        note = mock_adapter.append_worknote.call_args[0][1]
        assert "Disk full" in note
        assert "0.92" in note

    def test_handle_resolved(self):
        import agenticops.itsm.bridge as bridge_mod

        mock_adapter = MagicMock(spec=ServiceNowAdapter)
        mock_adapter.name = "servicenow"
        mock_adapter.close_change.return_value = ITSMResult(ok=True)
        mock_adapter.resolve_incident.return_value = ITSMResult(ok=True)
        bridge_mod._adapters = [mock_adapter]

        with patch("agenticops.itsm.bridge._get_link", side_effect=lambda et, eid, sys, rt: {
            ("fix_plan", 10, "servicenow", "change"): "chg-001",
            ("health_issue", 42, "servicenow", "incident"): "sys-001",
        }.get((et, eid, sys, rt))):
            mock_session = MagicMock()
            mock_plan = MagicMock()
            mock_plan.id = 10
            mock_session.query.return_value.filter_by.return_value.all.return_value = [mock_plan]
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = lambda s: mock_session
            mock_ctx.__exit__ = lambda s, *a: None
            with patch("agenticops.models.get_db_session", return_value=mock_ctx):
                bridge_mod.handle_pipeline_event(
                    42, "resolved", "resolved", "ok",
                    {"summary": "Fixed by clearing disk"},
                )

        mock_adapter.close_change.assert_called_once_with("chg-001", success=True, notes="Fixed by clearing disk")
        mock_adapter.resolve_incident.assert_called_once()


# ════════════════════════════════════════════════════════════════════
# Abstract base class contract
# ════════════════════════════════════════════════════════════════════


class TestITSMAdapterContract:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ITSMAdapter()

    def test_servicenow_is_itsm_adapter(self):
        a = ServiceNowAdapter("https://x.service-now.com", dry_run=True)
        assert isinstance(a, ITSMAdapter)

    def test_jira_is_itsm_adapter(self):
        a = JiraAdapter("https://x.atlassian.net", dry_run=True)
        assert isinstance(a, ITSMAdapter)
