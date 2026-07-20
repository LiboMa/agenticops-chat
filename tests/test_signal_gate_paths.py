"""Signal Gate path wiring — webhook, agent tool, parsers (MVP-2.2.0).

Run:
    pytest tests/test_signal_gate_paths.py -v
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from agenticops.models import AlertEvent, Base, HealthIssue, get_session


@pytest.fixture
def db_session(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/test_gate_paths.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def gate_settings():
    from agenticops.config import settings

    saved = {k: getattr(settings, k) for k in (
        "signal_gate_enabled", "signal_gate_llm_enabled", "noise_flap_threshold",
        "noise_flap_window_minutes", "webhook_auto_create_issue",
        "dedup_resolved_cooldown_minutes", "issue_exclude_patterns",
    )}
    settings.signal_gate_enabled = True
    settings.signal_gate_llm_enabled = False  # deterministic-only for path tests
    settings.noise_flap_threshold = 12  # out of the way unless a test lowers it
    settings.noise_flap_window_minutes = 30
    settings.webhook_auto_create_issue = True
    settings.dedup_resolved_cooldown_minutes = 60
    settings.issue_exclude_patterns = []
    yield settings
    for k, v in saved.items():
        setattr(settings, k, v)


PROM_BODY = {
    "status": "firing",
    "alerts": [
        {"status": "firing", "fingerprint": "fp-cpu-1",
         "labels": {"alertname": "HighCPU", "severity": "high", "instance": "i-abc"},
         "annotations": {"description": "CPU > 90%"}},
        {"status": "firing", "fingerprint": "fp-mem-2",
         "labels": {"alertname": "MemoryPressure", "severity": "medium", "instance": "i-def"},
         "annotations": {"description": "Memory > 85%"}},
    ],
}

CW_ALARM = {
    "AlarmName": "cpu-high-prod",
    "AlarmArn": "arn:aws:cloudwatch:us-east-1:123:alarm:cpu-high-prod",
    "NewStateValue": "ALARM",
    "NewStateReason": "CPU exceeded 90%",
    "Trigger": {"MetricName": "CPUUtilization", "Namespace": "AWS/EC2",
                "Dimensions": [{"name": "InstanceId", "value": "i-abc"}]},
}


def _webhook(alert):
    from agenticops.integrations.alert_processor import process_alert

    with patch("agenticops.services.rca_service.trigger_auto_rca") as rca, \
         patch("agenticops.services.notification_service.notify_issue_created"):
        result = process_alert(alert)
    return result, rca


class TestParsers:
    def test_prometheus_multi_alert(self):
        from agenticops.integrations.parsers import parse_alerts

        alerts = parse_alerts(PROM_BODY, source="prometheus")
        assert len(alerts) == 2
        assert alerts[0].external_id == "fp-cpu-1"
        assert alerts[0].issue_type == "cpu_spike"
        assert alerts[1].external_id == "fp-mem-2"
        assert alerts[1].issue_type == "memory_pressure"

    def test_prometheus_resolved_kind(self):
        from agenticops.integrations.parsers import parse_alerts

        body = {"alerts": [{"status": "resolved", "fingerprint": "fp-cpu-1",
                            "labels": {"alertname": "HighCPU"}}]}
        alerts = parse_alerts(body, source="prometheus")
        assert alerts[0].kind == "resolution"

    def test_cloudwatch_uses_alarm_arn_and_ok_is_resolution(self):
        from agenticops.integrations.parsers import parse_alerts

        firing = parse_alerts(CW_ALARM, source="cloudwatch")[0]
        assert firing.external_id == CW_ALARM["AlarmArn"]
        assert firing.kind == "alert"
        assert firing.issue_type == "cpu_spike"

        ok = dict(CW_ALARM, NewStateValue="OK")
        recovered = parse_alerts(ok, source="cloudwatch")[0]
        assert recovered.kind == "resolution"
        assert recovered.external_id == firing.external_id


class TestWebhookPath:
    def test_replay_10x_one_issue_one_rca(self, db_session, gate_settings):
        """Acceptance #1: same alert replayed 10x → 1 issue, 10 signals, 1 RCA."""
        from agenticops.integrations.parsers import parse_alerts

        rca_calls = 0
        for _ in range(10):
            alert = parse_alerts(CW_ALARM, source="cloudwatch")[0]
            result, rca = _webhook(alert)
            rca_calls += rca.call_count

        assert db_session.query(HealthIssue).count() == 1
        assert db_session.query(AlertEvent).count() == 10
        assert db_session.query(AlertEvent).filter_by(disposition="promoted").count() == 1
        assert db_session.query(AlertEvent).filter_by(disposition="merged").count() == 9
        assert rca_calls == 1
        issue = db_session.query(HealthIssue).one()
        assert issue.occurrence_count == 10
        assert issue.issue_type == "cpu_spike"

    def test_flap_becomes_noise(self, db_session, gate_settings):
        """Acceptance #2: fire→resolve cycles (cooldown expired) hit the flap
        threshold instead of creating a fresh issue per cycle.

        While an issue is ACTIVE, repeats merge (better than noise). Flapping
        bites when each firing would otherwise create a NEW issue.
        """
        from agenticops.integrations.parsers import parse_alerts

        gate_settings.noise_flap_threshold = 4

        def _resolve_all_long_ago():
            for i in db_session.query(HealthIssue).filter(HealthIssue.status != "resolved"):
                i.status = "resolved"
                i.resolved_at = datetime.now(timezone.utc) - timedelta(hours=5)
            db_session.commit()

        results = []
        for _ in range(4):
            alert = parse_alerts(CW_ALARM, source="cloudwatch")[0]
            result, _ = _webhook(alert)
            results.append(result.action)
            _resolve_all_long_ago()

        assert results[:3] == ["created", "created", "created"]
        assert results[3] == "noise"
        assert db_session.query(AlertEvent).filter_by(
            disposition="noise", disposition_reason="flapping").count() == 1

    def test_webhook_resolved_cooldown_now_applies(self, db_session, gate_settings):
        """Webhook path historically had NO cooldown → new issue per flap. Fixed."""
        from agenticops.integrations.parsers import parse_alerts

        alert = parse_alerts(CW_ALARM, source="cloudwatch")[0]
        _webhook(alert)
        issue = db_session.query(HealthIssue).one()
        issue.status = "resolved"
        issue.resolved_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db_session.commit()

        result, rca = _webhook(parse_alerts(CW_ALARM, source="cloudwatch")[0])
        assert result.action == "deduplicated"
        assert rca.call_count == 0
        assert db_session.query(HealthIssue).count() == 1

    def test_cross_path_same_problem_single_issue(self, db_session, gate_settings):
        """Acceptance #3: webhook first, then agent detection, same resource+type → one issue."""
        alert = __import__("agenticops.integrations.parsers", fromlist=["parse_alerts"]).parse_alerts(
            CW_ALARM, source="cloudwatch")[0]
        _webhook(alert)

        from agenticops.tools.metadata_tools import _create_health_issue_impl

        with patch("agenticops.services.rca_service.trigger_auto_rca"), \
             patch("agenticops.services.notification_service.notify_issue_created"):
            msg = _create_health_issue_impl(
                resource_id="i-abc", severity="high", source="metric_anomaly",
                title="CPU utilization pegged above 95 percent",
                description="sustained saturation", issue_type="cpu_spike",
            )
        assert "Deduplicated" in msg
        assert db_session.query(HealthIssue).count() == 1


class TestAgentPathStrings:
    def test_legacy_return_string_formats(self, db_session, gate_settings):
        from agenticops.tools.metadata_tools import _create_health_issue_impl

        with patch("agenticops.services.rca_service.trigger_auto_rca"), \
             patch("agenticops.services.notification_service.notify_issue_created"):
            created = _create_health_issue_impl(
                resource_id="i-xyz", severity="high", source="cloudwatch_alarm",
                title="Disk 95% full on /data", description="d", alarm_name="disk-alarm",
                issue_type="disk_full",
            )
            merged = _create_health_issue_impl(
                resource_id="i-xyz", severity="high", source="cloudwatch_alarm",
                title="Disk 96% full on /data", description="d", alarm_name="disk-alarm",
                issue_type="disk_full",
            )
        assert created.startswith("Created HealthIssue #")
        assert merged.startswith("Deduplicated: updated existing HealthIssue #")


class TestRestPathAndSignalsApi:
    @pytest.fixture
    def client(self, db_session, gate_settings):
        from fastapi.testclient import TestClient
        from agenticops.web.app import app

        return TestClient(app)

    def _create_body(self, **kw):
        body = {
            "resource_id": "i-rest1", "severity": "high", "source": "manual",
            "title": "RDS connections exhausted", "description": "too many conns",
            "issue_type": "capacity_risk",
        }
        body.update(kw)
        return body

    def test_rest_duplicate_merges(self, client, db_session):
        """Acceptance #4: REST duplicate POST → same issue, no second row."""
        with patch("agenticops.services.rca_service.trigger_auto_rca"), \
             patch("agenticops.services.notification_service.notify_issue_created"):
            r1 = client.post("/api/health-issues", json=self._create_body())
            r2 = client.post("/api/health-issues", json=self._create_body())
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]
        assert r2.json()["occurrence_count"] == 2
        assert db_session.query(HealthIssue).count() == 1

    def test_signals_api_list_and_promote(self, client, db_session, gate_settings):
        gate_settings.issue_exclude_patterns = [r"(?i)benign blip"]
        with patch("agenticops.services.rca_service.trigger_auto_rca"), \
             patch("agenticops.services.notification_service.notify_issue_created"):
            resp = client.post("/api/health-issues",
                               json=self._create_body(title="Benign blip in metrics"))
            assert resp.status_code == 409  # suppressed as noise

            listed = client.get("/api/signals", params={"disposition": "noise"})
            assert listed.status_code == 200
            signals = listed.json()
            assert len(signals) == 1
            assert signals[0]["disposition_reason"] == "excluded_pattern"

            promoted = client.post(f"/api/signals/{signals[0]['id']}/promote")
        assert promoted.status_code == 201
        issue_id = promoted.json()["health_issue_id"]
        assert db_session.get(HealthIssue, issue_id) is not None
        row = db_session.get(AlertEvent, signals[0]["id"])
        db_session.refresh(row)
        assert (row.disposition, row.disposition_reason) == ("promoted", "manual_override")
