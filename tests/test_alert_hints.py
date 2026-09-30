"""Webhook field enrichment (MVP-2.6.1 spec §3.B.5): each of the six parsers fills `observed_at` (when the source
says the fault happened, aware UTC) and `hints` ({account, region, cluster, namespace, workload, pod, service}, only
what the source itself carries); CloudWatch also hands over its alarm name. alert_processor passes all three to
SignalInput, so an issue from a webhook anchors like one from the agent."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agenticops.integrations.parsers import _observed_at, parse_alerts

UTC = timezone.utc


def _one(body, source):
    alerts = parse_alerts(body, source=source)
    assert len(alerts) == 1
    return alerts[0]


# ── CloudWatch ────────────────────────────────────────────────────────────────

CI_ALARM = {
    "AlarmName": "EKS-shop-prod-PodRestarts-High",
    "AlarmArn": "arn:aws:cloudwatch:ap-southeast-1:111111111111:alarm:EKS-shop-prod-PodRestarts-High",
    "AWSAccountId": "111111111111",
    "Region": "Asia Pacific (Singapore)",                    # a display name, never a region hint
    "NewStateValue": "ALARM",
    "NewStateReason": "restarts > 5",
    "StateChangeTime": "2026-09-29T08:01:02.123+0000",
    "Trigger": {"MetricName": "pod_number_of_container_restarts", "Namespace": "ContainerInsights",
                "Dimensions": [{"name": "ClusterName", "value": "shop-prod"},
                               {"name": "Namespace", "value": "shop"},
                               {"name": "PodName", "value": "checkout"},
                               {"name": "FullPodName", "value": "checkout-7d9f8b6c5-x2k4q"},
                               {"name": "Service", "value": "checkout-svc"}]},
}


def test_cloudwatch_container_insights_alarm_carries_the_k8s_identity():
    a = _one(CI_ALARM, "cloudwatch")
    assert a.hints == {"account": "111111111111", "region": "ap-southeast-1", "cluster": "shop-prod",
                       "namespace": "shop", "pod": "checkout-7d9f8b6c5-x2k4q", "service": "checkout-svc"}
    assert a.observed_at == datetime(2026, 9, 29, 8, 1, 2, 123000, tzinfo=UTC)
    assert a.alarm_name == "EKS-shop-prod-PodRestarts-High"


def test_cloudwatch_pod_falls_back_to_pod_name():
    body = {**CI_ALARM, "Trigger": {**CI_ALARM["Trigger"], "Dimensions": [
        {"name": "ClusterName", "value": "shop-prod"}, {"name": "Namespace", "value": "shop"},
        {"name": "PodName", "value": "checkout"}]}}
    assert _one(body, "cloudwatch").hints["pod"] == "checkout"


@pytest.mark.parametrize("namespace", ["AWS/EC2", "ECS/ContainerInsights", "AWS/ECS"])
def test_cloudwatch_cluster_dimensions_outside_k8s_container_insights_are_not_k8s_hints(namespace):
    """An ECS ClusterName is not an EKS cluster; only the ContainerInsights (EKS/K8s) namespace means K8s."""
    body = {**CI_ALARM, "Trigger": {"MetricName": "CPUUtilization", "Namespace": namespace,
                                    "Dimensions": [{"name": "ClusterName", "value": "shop-prod"},
                                                   {"name": "ServiceName", "value": "api"}]}}
    assert _one(body, "cloudwatch").hints == {"account": "111111111111", "region": "ap-southeast-1"}


@pytest.mark.parametrize("dimensions", [5, [{"name": {"x": 1}, "value": "shop-prod"}]])
def test_malformed_container_insights_dimensions_never_fail_the_parse(dimensions):
    """Hints are best-effort enrichment: a Dimensions value that is not a list of {name: str, value} must not turn
    a parse that used to succeed into an HTTP 400; it just adds no K8s hints."""
    body = {**CI_ALARM, "Trigger": {**CI_ALARM["Trigger"], "Dimensions": dimensions}}
    assert _one(body, "cloudwatch").hints == {"account": "111111111111", "region": "ap-southeast-1"}


def test_cloudwatch_without_arn_account_or_time_leaves_them_out():
    body = {"AlarmName": "EKS-agenticops-chaos-lab-RunningPods-Low", "NewStateValue": "ALARM",
            "Trigger": {"MetricName": "pod_number_of_running_pods", "Namespace": "ContainerInsights"}}
    a = _one(body, "cloudwatch")
    assert (a.hints, a.observed_at, a.alarm_name) == ({}, None, "EKS-agenticops-chaos-lab-RunningPods-Low")


# ── Alertmanager / Grafana ────────────────────────────────────────────────────


def _am_alert(fp, starts, **labels):
    return {"status": "firing", "fingerprint": fp, "startsAt": starts, "endsAt": "0001-01-01T00:00:00Z",
            "labels": {"alertname": "KubePodCrashLooping", "severity": "critical", **labels},
            "annotations": {"description": "crash looping"}}


def test_prometheus_labels_become_hints_and_each_entry_keeps_its_own_start():
    body = {"status": "firing", "alerts": [
        _am_alert("fp1", "2026-09-29T08:00:00.123456789Z", cluster="shop-prod", namespace="shop",
                  pod="checkout-7d9f8b6c5-x2k4q", service="kube-state-metrics", job="kube-state-metrics"),
        _am_alert("fp2", "2026-09-29T09:30:00+08:00", namespace="db", statefulset="redis")]}
    first, second = parse_alerts(body, source="prometheus")
    # `service` is the scrape target that kube-prometheus relabels onto every series, not the faulty object
    assert first.hints == {"cluster": "shop-prod", "namespace": "shop", "pod": "checkout-7d9f8b6c5-x2k4q"}
    assert first.observed_at == datetime(2026, 9, 29, 8, 0, 0, 123456, tzinfo=UTC)
    assert second.hints == {"namespace": "db", "workload": "redis"}
    assert second.observed_at == datetime(2026, 9, 29, 1, 30, tzinfo=UTC)
    assert first.alarm_name == ""                            # an alert rule name is not a CloudWatch alarm


@pytest.mark.parametrize("label", ["deployment", "statefulset", "daemonset"])
def test_kube_state_metrics_workload_labels(label):
    body = {"alerts": [_am_alert("fp", "2026-09-29T08:00:00Z", namespace="shop", **{label: "checkout"})]}
    assert _one(body, "prometheus").hints == {"namespace": "shop", "workload": "checkout"}


def test_grafana_labels_and_start():
    body = {"state": "alerting", "title": "checkout down", "alerts": [
        {"status": "firing", "fingerprint": "g1", "startsAt": "2026-09-29T08:00:00Z",
         "labels": {"cluster": "shop-prod", "namespace": "shop", "deployment": "checkout", "region": "us-east-1"}}]}
    a = _one(body, "grafana")
    assert a.hints == {"region": "us-east-1", "cluster": "shop-prod", "namespace": "shop", "workload": "checkout"}
    assert a.observed_at == datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


# ── Datadog / PagerDuty / generic ─────────────────────────────────────────────


def test_datadog_standard_tags_and_epoch_seconds():
    body = {"id": "dd1", "title": "checkout restarts", "alert_type": "error", "date_happened": 1790668862,
            "tags": ["kube_cluster_name:shop-prod", "kube_namespace:shop", "pod_name:checkout-7d9f8b6c5-x2k4q",
                     "kube_deployment:checkout", "kube_service:checkout-svc", "region:ap-southeast-1",
                     "aws_account:111111111111", "env:prod"]}
    a = _one(body, "datadog")
    assert a.hints == {"account": "111111111111", "region": "ap-southeast-1", "cluster": "shop-prod",
                       "namespace": "shop", "workload": "checkout", "pod": "checkout-7d9f8b6c5-x2k4q",
                       "service": "checkout-svc"}
    assert a.observed_at == datetime.fromtimestamp(1790668862, tz=UTC)


def test_datadog_epoch_milliseconds_from_a_webhook_template():
    body = {"id": "dd2", "title": "x", "alert_type": "error", "last_updated": "1790668862000"}
    assert _one(body, "datadog").observed_at == datetime.fromtimestamp(1790668862, tz=UTC)


def test_pagerduty_timestamp_and_hint_keys_in_custom_details():
    body = {"routing_key": "k", "dedup_key": "pd1", "payload": {
        "summary": "checkout down", "severity": "critical", "source": "checkout",
        "timestamp": "2026-09-29T08:00:00.000Z",
        "custom_details": {"cluster": "shop-prod", "namespace": "shop", "workload": "checkout", "owner": "team-a"}}}
    a = _one(body, "pagerduty")
    assert a.hints == {"cluster": "shop-prod", "namespace": "shop", "workload": "checkout"}
    assert a.observed_at == datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


def test_generic_hints_are_filtered_to_the_known_keys_and_plain_values():
    body = {"title": "x", "observed_at": "2026-09-29 08:00:00", "hints": {
        "cluster": " shop-prod ", "namespace": "shop", "account": 111111111111, "pod": "", "service": None,
        "workload": True, "region": {"nested": 1}, "owner": "team-a"}}
    a = _one(body, "generic")
    assert a.hints == {"cluster": "shop-prod", "namespace": "shop", "account": "111111111111"}
    assert a.observed_at == datetime(2026, 9, 29, 8, 0, tzinfo=UTC)       # naive text is read as UTC
    assert _one({"title": "x", "hints": ["cluster"]}, "generic").hints == {}


# ── time parsing ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [None, "", "  ", "yesterday", True, False, "0001-01-01T00:00:00Z",
                                   "1999-12-31T23:59:59Z", 10 ** 20, -1, [], {}, "2026-13-01T00:00:00Z"])
def test_anything_that_is_not_a_plausible_time_is_none(value):
    assert _observed_at(value) is None


def test_every_time_is_aware_utc():
    for value in ("2026-09-29T16:00:00+08:00", "2026-09-29T08:00:00Z", "2026-09-29T08:00:00", 1790668800,
                  1790668800.5, 1790668800000, "1790668800"):
        dt = _observed_at(value)
        assert dt.tzinfo == UTC and dt.replace(microsecond=0) == datetime(2026, 9, 29, 8, 0, tzinfo=UTC), value


# ── alert_processor → SignalInput → HealthIssue ───────────────────────────────


def test_alert_processor_hands_hints_time_and_alarm_name_to_the_signal_gate():
    from agenticops.integrations.alert_processor import process_alert
    from agenticops.services.signal_gate import GateDecision

    alert = _one(CI_ALARM, "cloudwatch")
    seen = []
    with patch("agenticops.services.signal_gate.process_signal",
               side_effect=lambda sig: seen.append(sig) or GateDecision(disposition="noise", reason="test")):
        process_alert(alert)
    (sig,) = seen
    assert (sig.hints, sig.observed_at, sig.alarm_name) == (alert.hints, alert.observed_at, alert.alarm_name)
    assert sig.hints is not alert.hints                      # the gate may keep it; the parser's dict stays ours


@pytest.fixture
def gate_db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.models import Base, CloudAccount, get_session

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/hints.db"
    Base.metadata.create_all(models_mod.get_engine())
    for key, value in (("signal_gate_enabled", True), ("signal_gate_llm_enabled", False),
                       ("webhook_auto_create_issue", True), ("issue_exclude_patterns", [])):
        monkeypatch.setattr(settings, key, value)
    s = get_session()
    s.add(CloudAccount(id=1, name="global", provider="aws", is_enabled=True,
                       credentials={"account_id": "111111111111"}))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def test_a_webhook_issue_stores_hints_and_the_source_time(gate_db):
    from agenticops.integrations.alert_processor import process_alert
    from agenticops.models import HealthIssue

    with patch("agenticops.services.rca_service.trigger_auto_rca"), \
         patch("agenticops.services.notification_service.notify_issue_created"):
        result = process_alert(_one(CI_ALARM, "cloudwatch"))
    assert result.action == "created"
    issue = gate_db.get(HealthIssue, result.health_issue_id)
    assert issue.metric_data["hints"]["cluster"] == "shop-prod"
    assert issue.alarm_name == "EKS-shop-prod-PodRestarts-High"
    assert issue.observed_at.replace(tzinfo=UTC) == datetime(2026, 9, 29, 8, 1, 2, 123000, tzinfo=UTC)


def test_the_chaos_lab_alarm_anchors_to_its_cluster_by_name_alone(gate_db):
    """The chaos-lab scenarios send only AlarmName (no Dimensions, no AlarmArn): rule 7 must see it."""
    from agenticops.integrations.alert_processor import process_alert
    from agenticops.models import CloudResource, HealthIssue

    gate_db.add(CloudResource(id=1355, account_id=1, provider="aws", region="ap-southeast-1", resource_type="EKS",
                              resource_id="agenticops-chaos-lab", name="agenticops-chaos-lab", tags={}, raw_data={}))
    gate_db.commit()
    with patch("agenticops.services.rca_service.trigger_auto_rca"), \
         patch("agenticops.services.notification_service.notify_issue_created"):
        result = process_alert(_one({"AlarmName": "EKS-agenticops-chaos-lab-RunningPods-Low",
                                     "NewStateValue": "ALARM"}, "cloudwatch"))
    issue = gate_db.get(HealthIssue, result.health_issue_id)
    assert (issue.anchor_status, issue.resource_ref, issue.account_id) == ("anchored", 1355, 1)


def test_an_alarm_name_longer_than_the_column_anchors_whole_and_is_not_stored(gate_db, monkeypatch):
    """CloudWatch allows 255 characters, the column holds 200. A cut copy could later re-anchor to a wrong cluster
    (reanchor_open_issues reads the column), so the whole name anchors once and the column stays empty."""
    from agenticops.integrations.alert_processor import process_alert
    from agenticops.models import HealthIssue
    from agenticops.services import identity_resolver

    name = "EKS-" + "c" * 240 + "-Pod-High"
    seen = []
    real = identity_resolver.resolve
    monkeypatch.setattr(identity_resolver, "resolve", lambda s, **kw: seen.append(kw["alarm_name"]) or real(s, **kw))
    with patch("agenticops.services.rca_service.trigger_auto_rca"), \
         patch("agenticops.services.notification_service.notify_issue_created"):
        result = process_alert(_one({"AlarmName": name, "NewStateValue": "ALARM"}, "cloudwatch"))
    issue = gate_db.get(HealthIssue, result.health_issue_id)
    assert seen == [name] and issue.alarm_name is None
    assert gate_db.get(HealthIssue, result.health_issue_id).title.startswith("EKS-cccc")   # still readable
