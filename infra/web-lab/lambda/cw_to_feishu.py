"""Lambda: CloudWatch Alarm → SNS → Feishu alert group.

Receives SNS notifications from CloudWatch Alarms, formats them as
readable alert messages, and sends to the configured Feishu chat group
via the Feishu Bot API.

Environment variables:
    FEISHU_APP_ID      — Feishu app ID
    FEISHU_APP_SECRET  — Feishu app secret
    FEISHU_CHAT_ID     — Target Feishu group chat ID (alert channel)
"""

import json
import logging
import os
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_CHAT_ID = os.environ.get("FEISHU_CHAT_ID", "")

# Feishu API endpoints
TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
SEND_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"


def get_tenant_token() -> str:
    """Get Feishu tenant access token."""
    payload = json.dumps({
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("code") != 0:
        raise RuntimeError(f"Feishu token error: {data}")
    return data["tenant_access_token"]


def send_feishu_message(token: str, chat_id: str, text: str) -> dict:
    """Send a text message to a Feishu group chat."""
    payload = json.dumps({
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }).encode()
    req = urllib.request.Request(
        SEND_MSG_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def format_alarm_message(alarm: dict) -> str:
    """Format a CloudWatch Alarm notification as a readable alert message.

    The output format is designed to be easily parsed by AgenticOps
    Agent's alert detection (5-step LLM analysis).
    """
    state = alarm.get("NewStateValue", "UNKNOWN")
    alarm_name = alarm.get("AlarmName", "Unknown Alarm")
    description = alarm.get("AlarmDescription", "")
    reason = alarm.get("NewStateReason", "")
    region = alarm.get("Region", "")

    # Extract trigger details
    trigger = alarm.get("Trigger", {})
    metric = trigger.get("MetricName", "")
    namespace = trigger.get("Namespace", "")
    dimensions = trigger.get("Dimensions", [])
    dim_str = ", ".join(
        f"{d.get('name', '')}={d.get('value', '')}"
        for d in dimensions if isinstance(d, dict)
    )

    # Map state to prefix
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
    return "\n".join(line for line in lines if line)


def handler(event, context):
    """Lambda handler: SNS event → parse CW alarm → send to Feishu."""
    logger.info("Event: %s", json.dumps(event))

    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_CHAT_ID]):
        logger.error("Missing FEISHU_* environment variables")
        return {"statusCode": 500, "body": "Missing config"}

    token = get_tenant_token()

    for record in event.get("Records", []):
        sns_message = record.get("Sns", {}).get("Message", "")

        # SNS message from CloudWatch is a JSON string
        try:
            alarm = json.loads(sns_message)
        except (json.JSONDecodeError, TypeError):
            # Not JSON — forward raw text
            alarm = None
            text = f"[CloudWatch SNS] {sns_message}"

        if alarm:
            text = format_alarm_message(alarm)

        logger.info("Sending to Feishu chat %s: %s", FEISHU_CHAT_ID, text[:200])
        result = send_feishu_message(token, FEISHU_CHAT_ID, text)
        logger.info("Feishu response: %s", json.dumps(result))

    return {"statusCode": 200, "body": "OK"}
