"""Lambda: Alert Gateway — SNS → configurable IM channels.

Receives SNS notifications (CloudWatch Alarms, Prometheus AlertManager, etc.),
formats them as readable alert messages, and forwards to configured IM channels.

Supports multiple targets simultaneously — each can be independently enabled/disabled.

Environment variables:
    ALERT_TARGETS  — JSON config string (see below)

Config format (ALERT_TARGETS):
{
    "targets": [
        {
            "name": "slack-alerts",
            "platform": "slack",
            "enabled": true,
            "webhook_url": "https://hooks.slack.com/services/...",
        },
        {
            "name": "feishu-alerts",
            "platform": "feishu",
            "enabled": true,
            "app_id": "cli_xxx",
            "app_secret": "xxx",
            "chat_id": "oc_xxx"
        },
        {
            "name": "ops-webhook",
            "platform": "webhook",
            "enabled": false,
            "url": "https://your-agenticops.example.com/api/webhooks/alerts",
            "method": "POST",
            "headers": {"X-Source": "alert-gateway"}
        }
    ]
}
"""

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Load config from env var
_TARGETS_RAW = os.environ.get("ALERT_TARGETS", '{"targets": []}')
try:
    _CONFIG = json.loads(_TARGETS_RAW)
except json.JSONDecodeError:
    logger.error("Invalid ALERT_TARGETS JSON: %s", _TARGETS_RAW[:200])
    _CONFIG = {"targets": []}


# =====================================================================
# Alert Formatters
# =====================================================================


def format_cloudwatch_alarm(alarm: dict) -> Dict[str, str]:
    """Format a CloudWatch Alarm SNS notification.

    Returns dict with 'text' (plain), 'severity', 'title' keys.
    """
    state = alarm.get("NewStateValue", "UNKNOWN")
    alarm_name = alarm.get("AlarmName", "Unknown Alarm")
    description = alarm.get("AlarmDescription", "")
    reason = alarm.get("NewStateReason", "")
    region = alarm.get("Region", "")

    trigger = alarm.get("Trigger", {})
    metric = trigger.get("MetricName", "")
    namespace = trigger.get("Namespace", "")
    dimensions = trigger.get("Dimensions", [])
    dim_str = ", ".join(
        f"{d.get('name', '')}={d.get('value', '')}"
        for d in dimensions if isinstance(d, dict)
    )

    if state == "ALARM":
        prefix = "ALARM"
        severity = "high"
    elif state == "OK":
        prefix = "OK"
        severity = "low"
    else:
        prefix = state
        severity = "medium"

    lines = [
        f'{prefix}: "{alarm_name}" in {region}',
        f"Severity: {severity}",
        f"Description: {description}" if description else "",
        f"Metric: {namespace}/{metric}" if metric else "",
        f"Dimensions: {dim_str}" if dim_str else "",
        f"Reason: {reason}" if reason else "",
    ]
    text = "\n".join(line for line in lines if line)
    title = f'{prefix}: "{alarm_name}"'

    return {"text": text, "severity": severity, "title": title}


def format_prometheus_alert(alert: dict) -> Dict[str, str]:
    """Format a Prometheus AlertManager webhook payload."""
    status = alert.get("status", "unknown")  # firing / resolved
    alerts = alert.get("alerts", [])

    if not alerts:
        return {
            "text": f"[Prometheus] {status} — no alert details",
            "severity": "medium",
            "title": f"Prometheus: {status}",
        }

    lines = []
    severity = "medium"
    for a in alerts:
        labels = a.get("labels", {})
        annotations = a.get("annotations", {})
        alert_name = labels.get("alertname", "Unknown")
        alert_sev = labels.get("severity", "warning")
        summary = annotations.get("summary", "")
        description = annotations.get("description", "")

        if alert_sev in ("critical",):
            severity = "critical"
        elif alert_sev in ("high", "error") and severity != "critical":
            severity = "high"

        s = a.get("status", status).upper()
        lines.append(f"[{s}] {alert_name} ({alert_sev})")
        if summary:
            lines.append(f"  Summary: {summary}")
        if description:
            lines.append(f"  Detail: {description}")
        # Key labels
        for k in ("namespace", "pod", "instance", "service", "job"):
            if k in labels:
                lines.append(f"  {k}: {labels[k]}")
        lines.append("")

    text = "\n".join(lines).strip()
    title = f"Prometheus: {len(alerts)} alert(s) {status}"

    return {"text": text, "severity": severity, "title": title}


def parse_sns_message(sns_message: str) -> Dict[str, str]:
    """Parse an SNS message body and return formatted alert dict.

    Auto-detects source: CloudWatch Alarm, Prometheus, or raw text.
    """
    try:
        payload = json.loads(sns_message)
    except (json.JSONDecodeError, TypeError):
        return {
            "text": f"[Alert] {sns_message}",
            "severity": "medium",
            "title": "Alert Notification",
        }

    # CloudWatch Alarm: has AlarmName + NewStateValue
    if "AlarmName" in payload and "NewStateValue" in payload:
        return format_cloudwatch_alarm(payload)

    # Prometheus AlertManager: has "alerts" array
    if "alerts" in payload and isinstance(payload.get("alerts"), list):
        return format_prometheus_alert(payload)

    # Unknown JSON — forward as-is
    text = json.dumps(payload, indent=2, ensure_ascii=False)[:2000]
    return {
        "text": f"[Alert]\n{text}",
        "severity": "medium",
        "title": "Alert Notification",
    }


# =====================================================================
# Platform Senders
# =====================================================================


def _http_post(url: str, data: bytes, headers: Dict[str, str],
               timeout: int = 10) -> dict:
    """Simple HTTP POST using urllib (no external deps in Lambda)."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def send_slack(target: dict, alert: Dict[str, str]) -> bool:
    """Send alert to Slack via Incoming Webhook."""
    webhook_url = target.get("webhook_url", "")
    if not webhook_url:
        logger.error("[%s] Missing webhook_url", target.get("name"))
        return False

    color_map = {
        "critical": "#FF0000",
        "high": "#FF6600",
        "medium": "#FFCC00",
        "low": "#0066FF",
    }
    color = color_map.get(alert["severity"], "#808080")

    payload = {
        "attachments": [{
            "color": color,
            "title": alert["title"],
            "text": alert["text"],
            "footer": "AgenticOps Alert Gateway",
        }],
    }

    # Optional: override channel
    channel = target.get("channel")
    if channel:
        payload["channel"] = channel

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        webhook_url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode()
        ok = resp.status == 200 and body == "ok"
        if not ok:
            logger.error("[%s] Slack webhook response: %s %s",
                         target.get("name"), resp.status, body[:100])
        return ok


def send_slack_bot(target: dict, alert: Dict[str, str]) -> bool:
    """Send alert to Slack via Bot Token API (chat.postMessage).

    Use this instead of webhook when you need the message to come from
    the bot user (so Opsbot can see it via conversations.history).
    Requires 'bot_token' and 'chat_id' in target config.
    """
    bot_token = target.get("bot_token", "")
    chat_id = target.get("chat_id", "")
    if not bot_token or not chat_id:
        logger.error("[%s] Missing bot_token or chat_id", target.get("name"))
        return False

    # Prepend @mention so the target bot picks up the alert
    # Config: "mention": ["U0AKE9VNGN8"] or "mention": "U0AKE9VNGN8"
    text = alert["text"]
    mention = target.get("mention", [])
    if isinstance(mention, str):
        mention = [mention]
    if mention:
        mention_str = " ".join(f"<@{uid}>" for uid in mention)
        text = f"{mention_str}\n{text}"

    payload = {
        "channel": chat_id,
        "text": text,
    }
    data = json.dumps(payload).encode()
    result = _http_post(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bot_token}",
        },
    )
    ok = result.get("ok", False)
    if not ok:
        logger.error("[%s] Slack Bot API error: %s",
                     target.get("name"), result.get("error"))
    return ok


def send_feishu(target: dict, alert: Dict[str, str]) -> bool:
    """Send alert to Feishu via Bot API (app token → chat message)."""
    app_id = target.get("app_id", "")
    app_secret = target.get("app_secret", "")
    chat_id = target.get("chat_id", "")
    if not all([app_id, app_secret, chat_id]):
        logger.error("[%s] Missing feishu config", target.get("name"))
        return False

    # Get tenant token
    token_data = _http_post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
        headers={"Content-Type": "application/json"},
    )
    if token_data.get("code") != 0:
        logger.error("[%s] Feishu token error: %s", target.get("name"), token_data)
        return False
    token = token_data["tenant_access_token"]

    # Send message
    result = _http_post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=json.dumps({
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": alert["text"]}),
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    ok = result.get("code") == 0
    if not ok:
        logger.error("[%s] Feishu send error: %s", target.get("name"), result)
    return ok


def send_webhook(target: dict, alert: Dict[str, str]) -> bool:
    """Send alert to a generic webhook endpoint."""
    url = target.get("url", "")
    if not url:
        logger.error("[%s] Missing webhook url", target.get("name"))
        return False

    payload = {
        "source": "agenticops-alert-gateway",
        "title": alert["title"],
        "text": alert["text"],
        "severity": alert["severity"],
    }

    headers = {"Content-Type": "application/json"}
    headers.update(target.get("headers", {}))

    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        ok = 200 <= resp.status < 300
        if not ok:
            logger.error("[%s] Webhook %s returned %s",
                         target.get("name"), url, resp.status)
        return ok


# Platform dispatcher
_SENDERS = {
    "slack": send_slack,
    "slack_bot": send_slack_bot,
    "feishu": send_feishu,
    "webhook": send_webhook,
}


# =====================================================================
# Lambda Handler
# =====================================================================


def handler(event, context):
    """Lambda handler: SNS event → parse → fan-out to configured targets."""
    logger.info("Event: %s", json.dumps(event)[:2000])

    targets = _CONFIG.get("targets", [])
    enabled_targets = [t for t in targets if t.get("enabled", True)]

    if not enabled_targets:
        logger.warning("No enabled targets in ALERT_TARGETS config")
        return {"statusCode": 200, "body": "No targets configured"}

    results = []

    for record in event.get("Records", []):
        sns_message = record.get("Sns", {}).get("Message", "")
        if not sns_message:
            continue

        alert = parse_sns_message(sns_message)
        logger.info("Parsed alert: title=%s severity=%s",
                     alert["title"], alert["severity"])

        for target in enabled_targets:
            name = target.get("name", "unnamed")
            platform = target.get("platform", "")
            sender = _SENDERS.get(platform)

            if not sender:
                logger.error("Unknown platform '%s' for target '%s'", platform, name)
                results.append({"target": name, "ok": False, "error": "unknown platform"})
                continue

            try:
                ok = sender(target, alert)
                results.append({"target": name, "ok": ok})
                logger.info("Target '%s' (%s): %s", name, platform, "OK" if ok else "FAILED")
            except Exception as e:
                logger.exception("Target '%s' (%s) error", name, platform)
                results.append({"target": name, "ok": False, "error": str(e)})

    return {
        "statusCode": 200,
        "body": json.dumps({"results": results}),
    }
