"""Alert parsers for external monitoring systems."""

import hashlib
import logging
import re
from typing import Callable

from agenticops.integrations.base import AlertPayload

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low"})

# Maps commonly seen severity strings to the canonical four-level set.
_SEVERITY_MAP: dict[str, str] = {
    # Canonical values
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    # Datadog / PagerDuty / Grafana variants
    "error": "high",
    "warning": "medium",
    "warn": "medium",
    "info": "low",
    "informational": "low",
    "normal": "low",
    "urgent": "critical",
    "fatal": "critical",
    "emergency": "critical",
    "emerg": "critical",
    "alert": "high",
    "notice": "low",
    "debug": "low",
    "p1": "critical",
    "p2": "high",
    "p3": "medium",
    "p4": "low",
    "p5": "low",
}


def _normalize_severity(severity: str) -> str:
    """Map an arbitrary severity string to one of: critical, high, medium, low.

    Performs a case-insensitive lookup against known severity aliases. Returns
    'medium' for any unrecognised value.

    Args:
        severity: Raw severity string from the alert payload.

    Returns:
        One of 'critical', 'high', 'medium', or 'low'.
    """
    if not severity:
        return "medium"
    normalised = severity.strip().lower()
    return _SEVERITY_MAP.get(normalised, "medium")


def _hash_title(title: str) -> str:
    """Generate a deterministic external_id from an alert title.

    Uses a truncated SHA-256 hex digest so the same title always produces
    the same dedup key.

    Args:
        title: Alert title text.

    Returns:
        A 16-character hex string suitable as a dedup key.
    """
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]


# Regex for extracting AWS-style resource IDs, ARNs, and pod names from text.
_RESOURCE_HINT_RE = re.compile(
    r"(arn:[a-zA-Z0-9:\-_/]+|i-[0-9a-f]{8,17}|pod/[\w\-]+|[\w\-]+\.[\w\-]+\.[\w\-]+)"
)


def _extract_resource_hint_from_tags(tags: list) -> str:
    """Extract a resource hint from a Datadog-style tag list.

    Datadog tags are strings in ``key:value`` format.  This function looks
    for well-known tag keys that typically identify a resource (host,
    instance, pod, container_name, arn).

    Args:
        tags: List of ``"key:value"`` strings (Datadog format).

    Returns:
        The best-effort resource identifier, or an empty string.
    """
    hint_keys = ("host", "instance", "pod", "pod_name", "container_name", "arn")
    for tag in tags or []:
        if not isinstance(tag, str) or ":" not in tag:
            continue
        key, _, value = tag.partition(":")
        if key.strip().lower() in hint_keys and value.strip():
            return value.strip()
    return ""


def _tags_list_to_dict(tags: list) -> dict[str, str]:
    """Convert a Datadog-style tag list to a dict.

    Tags without a colon are stored with an empty-string value.

    Args:
        tags: List of ``"key:value"`` strings.

    Returns:
        Dict mapping tag keys to values.
    """
    result: dict[str, str] = {}
    for tag in tags or []:
        if not isinstance(tag, str):
            continue
        if ":" in tag:
            key, _, value = tag.partition(":")
            result[key.strip()] = value.strip()
        else:
            result[tag.strip()] = ""
    return result


# ---------------------------------------------------------------------------
# Source parsers
# ---------------------------------------------------------------------------


def parse_datadog(body: dict) -> AlertPayload:
    """Parse a Datadog webhook / Events API v2 payload into an AlertPayload.

    Datadog webhooks typically include ``id`` or ``event_id``, ``title``,
    ``text`` (or ``body``), ``alert_type`` or ``priority``, and a ``tags``
    list of ``"key:value"`` strings.

    Args:
        body: Raw JSON body from the Datadog webhook.

    Returns:
        An AlertPayload with source='datadog'.
    """
    title = body.get("title", "")

    # External ID: prefer explicit IDs, fall back to title hash.
    external_id = str(body.get("id") or body.get("event_id") or "") or _hash_title(title)

    # Severity: Datadog uses "priority" (P1-P5) or "alert_type" (error/warning/...).
    raw_severity = body.get("priority") or body.get("alert_type") or ""
    severity = _normalize_severity(str(raw_severity))

    description = body.get("text", "") or body.get("body", "")

    raw_tags = body.get("tags", [])
    if not isinstance(raw_tags, list):
        raw_tags = []

    resource_hint = _extract_resource_hint_from_tags(raw_tags)
    tags = _tags_list_to_dict(raw_tags)

    return AlertPayload(
        source="datadog",
        external_id=str(external_id),
        severity=severity,
        title=title,
        description=description,
        resource_hint=resource_hint,
        tags=tags,
        raw=body,
    )


def parse_pagerduty(body: dict) -> AlertPayload:
    """Parse a PagerDuty Events API v2 payload into an AlertPayload.

    PagerDuty v2 payloads typically contain a ``routing_key``, a ``payload``
    object with ``summary``, ``severity``, ``source``, and optional
    ``custom_details``.  A ``dedup_key`` at the top level is used for
    deduplication.

    Args:
        body: Raw JSON body from the PagerDuty webhook.

    Returns:
        An AlertPayload with source='pagerduty'.
    """
    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    custom_details = payload.get("custom_details", {})
    if not isinstance(custom_details, dict):
        custom_details = {}

    # External ID: prefer dedup_key, then nested custom_details dedup_key.
    external_id = (
        str(body.get("dedup_key") or "")
        or str(custom_details.get("dedup_key") or "")
        or _hash_title(payload.get("summary", ""))
    )

    raw_severity = payload.get("severity", "warning")
    severity = _normalize_severity(str(raw_severity))

    title = payload.get("summary", "")
    description = custom_details.get("description", "")
    resource_hint = payload.get("source", "")

    return AlertPayload(
        source="pagerduty",
        external_id=str(external_id),
        severity=severity,
        title=title,
        description=description,
        resource_hint=resource_hint,
        tags={},
        raw=body,
    )


def parse_grafana(body: dict) -> AlertPayload:
    """Parse a Grafana Alerting webhook payload into an AlertPayload.

    Grafana sends a JSON body with a top-level ``alerts`` array, ``title``,
    and ``state`` (``alerting``, ``ok``, ``pending``, etc.).  Each alert in
    the array has ``labels``, ``annotations``, and a ``fingerprint``.

    Args:
        body: Raw JSON body from the Grafana webhook.

    Returns:
        An AlertPayload with source='grafana'.
    """
    alerts = body.get("alerts", [])
    if not isinstance(alerts, list):
        alerts = []
    alert = alerts[0] if alerts else {}

    labels = alert.get("labels", {})
    if not isinstance(labels, dict):
        labels = {}

    annotations = alert.get("annotations", {})
    if not isinstance(annotations, dict):
        annotations = {}

    # External ID: prefer fingerprint, then groupKey.
    external_id = str(alert.get("fingerprint", "") or body.get("groupKey", ""))
    if not external_id:
        external_id = _hash_title(body.get("title", ""))

    # Severity: prefer explicit label, then infer from state.
    raw_severity = labels.get("severity", "")
    if not raw_severity:
        state = body.get("state", "").lower()
        state_map = {"alerting": "high", "ok": "low", "pending": "medium", "no_data": "medium"}
        raw_severity = state_map.get(state, "medium")
    severity = _normalize_severity(str(raw_severity))

    title = body.get("title", "") or labels.get("alertname", "")
    description = annotations.get("description", "") or annotations.get("summary", "")
    resource_hint = labels.get("instance", "") or labels.get("pod", "")

    return AlertPayload(
        source="grafana",
        external_id=str(external_id),
        severity=severity,
        title=title,
        description=description,
        resource_hint=resource_hint,
        tags=dict(labels),
        raw=body,
    )


def parse_prometheus(body: dict) -> AlertPayload:
    """Parse a Prometheus AlertManager webhook payload into an AlertPayload.

    Prometheus AlertManager sends a JSON body with a top-level ``alerts``
    array, ``status``, ``groupLabels``, ``commonLabels``, ``commonAnnotations``,
    and ``externalURL``.  Each alert in the array has ``labels`` (including
    ``alertname`` and ``severity``), ``annotations``, ``startsAt``,
    ``endsAt``, and ``fingerprint``.

    Args:
        body: Raw JSON body from the Prometheus AlertManager webhook.

    Returns:
        An AlertPayload with source='prometheus'.
    """
    alerts = body.get("alerts", [])
    if not isinstance(alerts, list):
        alerts = []
    alert = alerts[0] if alerts else {}

    labels = alert.get("labels", {})
    if not isinstance(labels, dict):
        labels = {}

    annotations = alert.get("annotations", {})
    if not isinstance(annotations, dict):
        annotations = {}

    # External ID: prefer fingerprint from the first alert.
    external_id = str(alert.get("fingerprint", ""))
    if not external_id:
        external_id = _hash_title(labels.get("alertname", ""))

    # Severity: from labels.severity (Prometheus convention).
    raw_severity = labels.get("severity", "")
    severity = _normalize_severity(str(raw_severity))

    title = labels.get("alertname", "")
    description = annotations.get("description", "") or annotations.get("summary", "")

    # Resource hint: look for common Kubernetes/infrastructure label keys.
    _RESOURCE_HINT_KEYS = (
        "pod", "instance", "node", "container", "deployment",
        "statefulset", "daemonset",
    )
    resource_hint = ""
    for key in _RESOURCE_HINT_KEYS:
        value = labels.get(key, "")
        if value:
            resource_hint = str(value)
            break

    return AlertPayload(
        source="prometheus",
        external_id=str(external_id),
        severity=severity,
        title=title,
        description=description,
        resource_hint=resource_hint,
        tags=dict(labels),
        raw=body,
    )


def parse_cloudwatch(body: dict) -> AlertPayload:
    """Parse a CloudWatch SNS alarm notification into an AlertPayload.

    CloudWatch alarm notifications forwarded via SNS contain
    ``AlarmName``, ``AlarmDescription``, ``NewStateValue`` (``ALARM``,
    ``INSUFFICIENT_DATA``, ``OK``), ``NewStateReason``, ``StateChangeTime``,
    ``Region``, and a ``Trigger`` object with ``MetricName``, ``Namespace``,
    and ``Dimensions``.

    Args:
        body: Raw JSON body from the CloudWatch SNS webhook.

    Returns:
        An AlertPayload with source='cloudwatch'.
    """
    alarm_name = body.get("AlarmName", "")

    # External ID: deterministic hash of the alarm name.
    external_id = _hash_title(alarm_name) if alarm_name else ""

    # Severity: map NewStateValue to canonical levels.
    state_value = body.get("NewStateValue", "").upper()
    _STATE_SEVERITY_MAP = {
        "ALARM": "high",
        "INSUFFICIENT_DATA": "medium",
        "OK": "low",
    }
    severity = _normalize_severity(_STATE_SEVERITY_MAP.get(state_value, "medium"))

    title = alarm_name
    description = body.get("NewStateReason", "") or body.get("AlarmDescription", "")

    # Resource hint: extract from Trigger.Dimensions.
    resource_hint = ""
    trigger = body.get("Trigger", {})
    if isinstance(trigger, dict):
        dimensions = trigger.get("Dimensions", [])
        if isinstance(dimensions, list):
            # Prefer InstanceId, then fall back to first dimension value.
            for dim in dimensions:
                if isinstance(dim, dict) and dim.get("name") == "InstanceId":
                    resource_hint = dim.get("value", "")
                    break
            if not resource_hint and dimensions:
                first = dimensions[0]
                if isinstance(first, dict):
                    resource_hint = first.get("value", "")

    # Tags: include useful CloudWatch metadata.
    tags: dict[str, str] = {}
    if body.get("Region"):
        tags["region"] = str(body["Region"])
    if isinstance(trigger, dict):
        if trigger.get("MetricName"):
            tags["metric_name"] = str(trigger["MetricName"])
        if trigger.get("Namespace"):
            tags["namespace"] = str(trigger["Namespace"])
    if state_value:
        tags["state"] = state_value

    return AlertPayload(
        source="cloudwatch",
        external_id=str(external_id),
        severity=severity,
        title=title,
        description=description,
        resource_hint=resource_hint,
        tags=tags,
        raw=body,
    )


def parse_generic(body: dict) -> AlertPayload:
    """Parse a generic/unknown alert payload into an AlertPayload.

    Accepts common field names (``title``, ``description``, ``severity``,
    ``resource_id``, etc.) and maps them to the canonical AlertPayload
    structure.  This parser is the fallback when the source cannot be
    detected automatically.

    Args:
        body: Raw JSON body from the webhook.

    Returns:
        An AlertPayload with source set to ``body["source"]`` or 'generic'.
    """
    source = body.get("source", "generic")
    title = body.get("title", "Unknown Alert")

    external_id = str(
        body.get("external_id") or body.get("id") or body.get("alert_id") or ""
    )
    if not external_id:
        external_id = _hash_title(title)

    raw_severity = str(body.get("severity", "medium"))
    severity = _normalize_severity(raw_severity)

    description = body.get("description", "") or body.get("message", "") or body.get("body", "")
    resource_hint = (
        body.get("resource_id", "") or body.get("resource_hint", "") or body.get("host", "")
    )

    raw_tags = body.get("tags", {})
    if not isinstance(raw_tags, dict):
        raw_tags = {}

    return AlertPayload(
        source=str(source),
        external_id=str(external_id),
        severity=severity,
        title=title,
        description=description,
        resource_hint=resource_hint,
        tags=raw_tags,
        raw=body,
    )


# ---------------------------------------------------------------------------
# Auto-detection & routing
# ---------------------------------------------------------------------------


def detect_source(body: dict) -> str:
    """Auto-detect the monitoring source from a webhook payload's structure.

    Heuristics (checked in order):
      1. ``event_type`` or ``alert_type`` present -> Datadog
      2. ``routing_key`` present, or ``payload`` dict containing ``severity``
         -> PagerDuty
      3. ``AlarmName`` present -> CloudWatch
      4. ``alerts`` is a list AND any item has ``labels`` dict with
         ``alertname`` key -> Prometheus (checked before Grafana since both
         have an ``alerts`` array)
      5. ``alerts`` key containing a list -> Grafana
      6. Otherwise -> generic

    Args:
        body: Raw JSON body from the webhook.

    Returns:
        One of 'datadog', 'pagerduty', 'cloudwatch', 'prometheus',
        'grafana', or 'generic'.
    """
    if "event_type" in body or "alert_type" in body:
        return "datadog"

    if "routing_key" in body:
        return "pagerduty"
    payload = body.get("payload")
    if isinstance(payload, dict) and "severity" in payload:
        return "pagerduty"

    if "AlarmName" in body:
        return "cloudwatch"

    alerts = body.get("alerts")
    if isinstance(alerts, list):
        # Prometheus AlertManager payloads have alerts with labels.alertname;
        # Grafana payloads do not necessarily have that key.
        for alert in alerts:
            if isinstance(alert, dict):
                labels = alert.get("labels")
                if isinstance(labels, dict) and "alertname" in labels:
                    return "prometheus"
        return "grafana"

    return "generic"


_PARSER_MAP: dict[str, Callable[[dict], AlertPayload]] = {
    "datadog": parse_datadog,
    "pagerduty": parse_pagerduty,
    "grafana": parse_grafana,
    "prometheus": parse_prometheus,
    "cloudwatch": parse_cloudwatch,
    "generic": parse_generic,
}


def parse_alert(body: dict, source: str = "") -> AlertPayload:
    """Parse a webhook payload into a canonical AlertPayload.

    If *source* is not provided (or empty), the source is auto-detected from
    the payload structure via :func:`detect_source`.  The payload is then
    routed to the appropriate source-specific parser.  Regardless of parser,
    the final severity value is normalised to one of the four canonical
    levels.

    Args:
        body: Raw JSON body from the webhook.
        source: Explicit source name (e.g. 'datadog', 'pagerduty',
            'grafana').  When empty, auto-detection is used.

    Returns:
        An AlertPayload with normalised severity.
    """
    if not source:
        source = detect_source(body)

    parser = _PARSER_MAP.get(source.lower(), parse_generic)
    alert = parser(body)

    # Final normalisation guard — ensure severity is always canonical.
    alert.severity = _normalize_severity(alert.severity)

    return alert
