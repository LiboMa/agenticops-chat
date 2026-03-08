"""IM alert pipeline — deterministic alert detection + shared pipeline bridge.

Detection is config-driven (channel role, sender identity, known prefixes).
No regex classification, no confidence scores.
"""

import logging
import time
from datetime import datetime

from agenticops.config import settings
from agenticops.integrations.alert_processor import AlertProcessResult, process_alert
from agenticops.integrations.base import AlertPayload
from agenticops.integrations.parsers import _hash_title
from agenticops.notify.im_config import find_channel_by_chat

logger = logging.getLogger(__name__)

# In-memory cooldown: "title_hash" -> last_processed_ts
_cooldown_map: dict[str, float] = {}

# Known alert prefixes — deterministic, not regex
_ALERT_PREFIXES = (
    "[FIRING:",
    "[RESOLVED]",
    "ALARM:",
    "OK:",
    "[Alert]",
    "[Alerting]",
    "Problem:",
)


def is_alert_channel(platform: str, chat_id: str) -> bool:
    """Check if the chat is a dedicated alert channel."""
    ch = find_channel_by_chat(platform, chat_id)
    return ch is not None and ch.role == "alert"


def is_alert_sender(platform: str, chat_id: str, sender_id: str) -> bool:
    """Check if the sender is a known alert bot in this channel."""
    ch = find_channel_by_chat(platform, chat_id)
    if ch and ch.alert_senders and sender_id:
        return sender_id in ch.alert_senders
    return False


def is_alert_by_prefix(text: str) -> bool:
    """Quick prefix check for known monitoring system formats."""
    return any(text.startswith(p) for p in _ALERT_PREFIXES)


def should_handle_as_alert(
    platform: str, chat_id: str, sender_id: str, text: str
) -> bool:
    """Deterministic alert detection — no regex, no guessing.

    Three signals (short-circuit):
    1. Channel role == "alert" -> all messages are alerts
    2. Sender is a known alert bot
    3. Message starts with known monitoring prefix
    """
    if is_alert_channel(platform, chat_id):
        return True
    if is_alert_sender(platform, chat_id, sender_id):
        return True
    if is_alert_by_prefix(text):
        return True
    return False


def handle_alert_message(
    text: str,
    platform: str,
    chat_id: str,
) -> AlertProcessResult:
    """Process an IM alert through debounce + shared pipeline.

    Called ONLY when should_handle_as_alert() returns True.
    """
    # Debounce check
    title = text.split("\n")[0][:200]
    debounce_key = _hash_title(title)
    now = time.monotonic()
    cooldown = settings.im_alert_cooldown_seconds
    last = _cooldown_map.get(debounce_key)
    if last and (now - last) < cooldown:
        remaining = int(cooldown - (now - last))
        return AlertProcessResult(
            action="cooldown",
            message=f"Alert in cooldown ({remaining}s remaining). Skipping.",
        )
    _cooldown_map[debounce_key] = now

    # Handle resolved status — auto-resolve matching open HealthIssue
    status = _detect_status(text)
    if status in ("resolved", "ok"):
        resolved_id = _try_auto_resolve(title, text)
        if resolved_id:
            return AlertProcessResult(
                action="resolved",
                health_issue_id=resolved_id,
                message=f"Alert resolved. HealthIssue #{resolved_id} marked resolved.",
            )
        return AlertProcessResult(
            action="resolved",
            message="Alert resolved (no matching open issue found).",
        )

    # Build AlertPayload from raw text
    alert = _text_to_alert_payload(text, platform)
    im_origin = {"platform": platform, "chat_id": chat_id}

    # Graph context enrichment (best-effort, non-blocking)
    graph_ctx = _get_graph_context(alert.resource_hint)
    if graph_ctx:
        im_origin["graph_context"] = graph_ctx

    # Feed to shared pipeline: dedup -> HealthIssue -> RCA
    result = process_alert(alert, im_origin=im_origin)

    # Trigger on-demand graph sync for freshness (fire-and-forget)
    if alert.resource_hint and result.action == "created":
        try:
            from agenticops.services.graph_sync_service import trigger_sync_for_resource
            trigger_sync_for_resource(alert.resource_hint)
        except Exception:
            logger.debug("On-demand graph sync trigger failed", exc_info=True)

    # Enrich IM reply
    if result.action == "created" and result.health_issue_id:
        parts = [
            f"Alert: {title}",
            f"Issue #{result.health_issue_id} created. RCA triggered.",
        ]
        if graph_ctx:
            parts.append(f"Context: {graph_ctx.get('topology_summary', '')}")
        result.message = "\n".join(parts)
    elif result.action == "deduplicated":
        result.message = f"Alert already tracked (Issue #{result.health_issue_id})."

    return result


def _detect_status(text: str) -> str:
    """Detect alert status from text prefix."""
    if text.startswith("[RESOLVED]"):
        return "resolved"
    if text.startswith("OK:"):
        return "ok"
    return "firing"


def _text_to_alert_payload(text: str, platform: str) -> AlertPayload:
    """Convert raw IM alert text to AlertPayload. Simple, no regex."""
    lines = text.strip().split("\n")
    title = lines[0][:200]

    # Source detection by prefix
    source = "im_generic"
    if text.startswith("[FIRING:"):
        source = "im_prometheus"
    elif text.startswith("[RESOLVED]"):
        source = "im_prometheus"
    elif text.startswith("ALARM:") or text.startswith("OK:"):
        source = "im_cloudwatch"
    elif text.startswith("[Alert]") or text.startswith("[Alerting]"):
        source = "im_grafana"
    elif text.startswith("Problem:"):
        source = "im_generic"

    # Severity: simple keyword check
    t = text.lower()
    severity = "high"  # default for alerts
    if "critical" in t or "p1" in t or "emergency" in t:
        severity = "critical"
    elif "warning" in t or "p3" in t or "info" in t:
        severity = "medium"

    # Resource hint: look for common patterns
    resource_hint = ""
    for line in lines:
        for pattern in ("pod/", "node/", "instance=", "resource_id=", "i-", "vpc-"):
            idx = line.find(pattern)
            if idx >= 0:
                resource_hint = line[idx:].split()[0].split(",")[0].strip('"')
                break
        if resource_hint:
            break

    return AlertPayload(
        source=source,
        external_id=_hash_title(title),
        severity=severity,
        title=title,
        description=text[:2000],
        resource_hint=resource_hint,
        tags={"im_platform": platform, "status": _detect_status(text)},
        raw={"text": text},
    )


def _get_graph_context(resource_hint: str) -> dict | None:
    """Best-effort graph context enrichment."""
    if not resource_hint:
        return None
    try:
        from agenticops.graph.context import get_alert_context
        return get_alert_context(resource_hint)
    except Exception:
        logger.debug("Graph context lookup failed for %s", resource_hint, exc_info=True)
        return None


def _try_auto_resolve(title: str, text: str) -> int | None:
    """Try to resolve a matching open HealthIssue for a resolved alert."""
    try:
        from agenticops.models import HealthIssue, get_db_session

        with get_db_session() as session:
            query = session.query(HealthIssue).filter(
                HealthIssue.status.in_(["open", "investigating"]),
            )
            # Try to match by title similarity
            alert_name = title.replace("[RESOLVED]", "").replace("OK:", "").strip().strip('"')
            if alert_name:
                query = query.filter(
                    HealthIssue.title.contains(alert_name[:80])
                )

            issue = query.first()
            if issue:
                issue.status = "resolved"
                issue.resolved_at = datetime.utcnow()
                session.flush()
                return issue.id
    except Exception:
        logger.exception("Failed to auto-resolve HealthIssue for resolved alert")
    return None
