"""Agent tools for sending content to notification channels and IM aliases.

Provides three tools for the notification-operator skill:
- list_notification_channels: discover channels with format preferences
- send_to_channel: send text/references to a single channel
- distribute_report: batch format-aware report distribution to multiple channels

Delegates to the shared send_to.py infrastructure (target resolution, content
resolution, dispatch) and NotificationManager for multi-channel delivery.
"""

import asyncio
import json
import logging
from typing import Dict, List

from strands import tool

logger = logging.getLogger(__name__)

_VALID_CONTENT_TYPES = {"text", "report", "issue", "file"}


@tool
def list_notification_channels() -> str:
    """List all configured notification channels with format preferences and severity filters.

    Returns JSON array of channels with: name, type, enabled, preferred_format,
    severity_filter, and key config summary. Also includes IM aliases if any.
    Use this to discover available targets before sending notifications.

    Returns:
        JSON with channels array and im_aliases array.
    """
    from agenticops.notify.im_config import load_channels

    channels = load_channels()
    channel_list = []
    for ch in channels:
        entry = {
            "name": ch.name,
            "channel_type": ch.channel_type,
            "is_enabled": ch.is_enabled,
            "preferred_format": ch.preferred_format,
            "severity_filter": ch.severity_filter or [],
        }
        channel_list.append(entry)

    result: dict = {"channels": channel_list}

    # Also include IM aliases
    try:
        from agenticops.models import IMAlias, get_session

        session = get_session()
        try:
            aliases = session.query(IMAlias).all()
            result["im_aliases"] = [
                {
                    "name": a.name,
                    "platform": a.platform,
                    "chat_id": a.chat_id[:20] + "..." if len(a.chat_id) > 20 else a.chat_id,
                }
                for a in aliases
            ]
        finally:
            session.close()
    except Exception:
        result["im_aliases"] = []

    return json.dumps(result, default=str)


@tool
def send_to_channel(
    target_name: str,
    content: str,
    content_type: str = "text",
) -> str:
    """Send content to a notification channel or IM alias.

    Use list_notification_channels first to discover available targets.

    Args:
        target_name: Channel name (from channels.yaml) or IM alias name.
        content: The content to send. For content_type "text" this is the
            message body (markdown/plain text). For "report", "issue", or
            "file" this should be the numeric ID (e.g. "42").
        content_type: One of "text" (default), "report" (Report ID),
            "issue" (HealthIssue ID), "file" (LocalDoc ID).

    Returns:
        JSON string with "success" (bool) and "message" (str).
    """
    if content_type not in _VALID_CONTENT_TYPES:
        return json.dumps({
            "success": False,
            "message": f"Invalid content_type '{content_type}'. Must be one of: {', '.join(sorted(_VALID_CONTENT_TYPES))}",
        })

    # Build the synthetic /send_to command string
    if content_type == "text":
        command = f"/send_to {target_name} {content}"
    elif content_type == "report":
        command = f"/send_to {target_name} #R{content}"
    elif content_type == "issue":
        command = f"/send_to {target_name} #I{content}"
    elif content_type == "file":
        command = f"/send_to {target_name} #D{content}"
    else:
        # Unreachable due to validation above, but defensive
        command = f"/send_to {target_name} {content}"

    from agenticops.chat.send_to import execute_send_to

    result = execute_send_to(command)

    return json.dumps({
        "success": result.success,
        "message": result.message,
    })


@tool
def distribute_report(
    report_id: str,
    channel_names: str = "",
    severity: str = "",
) -> str:
    """Distribute a saved report to notification channels with format-aware batching.

    Determines each channel's preferred format, generates each unique format ONCE,
    then dispatches to all channels. For sns-report channels, uploads to S3 and
    sends via SES/SNS. For other channels, sends the formatted content directly.

    Args:
        report_id: Report database ID (numeric string).
        channel_names: Comma-separated channel names. Empty = all enabled channels.
        severity: Optional severity tag for channel filtering (e.g. "critical").

    Returns:
        JSON summary with success status and per-channel results.
    """
    # --- Load report from DB ---
    try:
        rid = int(report_id)
    except (ValueError, TypeError):
        return json.dumps({"success": False, "message": f"Invalid report_id: {report_id}"})

    from agenticops.models import Report, get_session

    session = get_session()
    try:
        report = session.query(Report).filter_by(id=rid).first()
        if not report:
            return json.dumps({"success": False, "message": f"Report #{rid} not found."})
        title = report.title
        summary = report.summary or ""
        content_md = report.content_markdown or ""
        report_type = report.report_type or "report"
        report_meta = report.report_metadata or {}
    finally:
        session.close()

    if not content_md:
        return json.dumps({"success": False, "message": f"Report #{rid} has no markdown content."})

    # --- Resolve target channels ---
    from agenticops.notify.im_config import load_channels

    all_channels = load_channels()

    if channel_names:
        requested = {n.strip() for n in channel_names.split(",") if n.strip()}
        channels = [c for c in all_channels if c.name in requested and c.is_enabled]
        missing = requested - {c.name for c in channels}
        if missing:
            logger.warning("Channels not found or disabled: %s", missing)
    else:
        channels = [c for c in all_channels if c.is_enabled]

    # Apply severity filter
    if severity:
        channels = [
            c for c in channels
            if not c.severity_filter or severity in c.severity_filter
        ]

    if not channels:
        return json.dumps({"success": False, "message": "No matching enabled channels found."})

    # --- Group channels by preferred_format ---
    format_groups: Dict[str, List] = {}
    for ch in channels:
        fmt = ch.preferred_format or "markdown"
        format_groups.setdefault(fmt, []).append(ch)

    # --- Batch format: generate each unique format once ---
    unique_formats = list(format_groups.keys())
    formatted_content: Dict[str, str] = {}

    # For text format, just use the raw markdown
    if "text" in unique_formats:
        formatted_content["text"] = content_md[:4000]

    # For markdown, use raw markdown
    if "markdown" in unique_formats:
        formatted_content["markdown"] = content_md[:4000]

    # For html/pdf, use report_formatter
    needs_formatter = [f for f in unique_formats if f in ("html", "pdf")]
    if needs_formatter:
        try:
            from agenticops.notify.report_formatter import format_report

            meta = dict(report_meta)
            meta["report_type"] = report_type
            formatted_reports = format_report(
                title=title,
                content_markdown=content_md,
                formats=needs_formatter,
                report_metadata=meta,
            )
            for fr in formatted_reports:
                formatted_content[fr.format] = fr.content.decode("utf-8", errors="replace")[:8000]
        except Exception as e:
            logger.warning("Report formatting failed for %s: %s", needs_formatter, e)
            # Fallback to markdown for these channels
            for fmt in needs_formatter:
                formatted_content[fmt] = content_md[:4000]

    # --- Dispatch to each channel ---
    results = []

    for ch in channels:
        fmt = ch.preferred_format or "markdown"
        body = formatted_content.get(fmt, content_md[:4000])

        # Special handling for sns-report and ses channels: use the full pipeline
        if ch.channel_type in ("sns-report", "ses"):
            try:
                result_entry = _distribute_via_report_channel(ch, rid, title, summary, content_md, report_type, report_meta)
                results.append(result_entry)
            except Exception as e:
                results.append({"channel": ch.name, "format": fmt, "status": "error", "error": str(e)})
            continue

        # Standard channels: send formatted body via NotificationManager
        try:
            from agenticops.notify.notifier import NotificationManager

            manager = NotificationManager()
            loop = asyncio.new_event_loop()
            try:
                send_results = loop.run_until_complete(
                    manager.send_notification(
                        subject=f"Report #{rid}: {title}",
                        body=body,
                        severity=severity or None,
                        channel_names=[ch.name],
                    )
                )
            finally:
                loop.close()

            success = send_results.get(ch.name, False)
            results.append({
                "channel": ch.name,
                "format": fmt,
                "status": "sent" if success else "failed",
            })
        except Exception as e:
            results.append({"channel": ch.name, "format": fmt, "status": "error", "error": str(e)})

    all_ok = all(r.get("status") == "sent" for r in results)
    return json.dumps({
        "success": all_ok,
        "report_id": rid,
        "channels_targeted": len(channels),
        "formats_generated": list(formatted_content.keys()),
        "results": results,
    })


@tool
def share_content(
    subject: str,
    body: str,
    channel_names: str = "",
    upload_to_s3: bool = False,
    expiry_hours: int = 72,
) -> str:
    """Share text content to notification channels, optionally with S3 presigned URL.

    For short content (<4000 chars), sends directly.
    For long content or when upload_to_s3=True, uploads to S3 and includes
    a presigned download URL in the notification.

    Args:
        subject: Message subject / title.
        body: The content to share (markdown text).
        channel_names: Comma-separated channel names. Empty = all enabled.
        upload_to_s3: Force upload to S3 even for short content.
        expiry_hours: Presigned URL expiry (default 72h). Max 168h (7 days).

    Returns:
        JSON with success, channels_sent, presigned_url (if uploaded).
    """
    from datetime import datetime

    if not subject or not body:
        return json.dumps({"success": False, "message": "subject and body are required"})

    expiry_hours = min(max(expiry_hours, 1), 168)
    presigned_url = None
    notification_body = body

    # Upload to S3 for long content or when forced
    if len(body) > 4000 or upload_to_s3:
        try:
            from agenticops.storage.backend import get_storage_backend

            backend = get_storage_backend()
            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in subject[:50])
            key = f"shared/{ts}_{safe_name}.md"
            uri = backend.write(key, body.encode("utf-8"), content_type="text/markdown")
            presigned_url = backend.presigned_url(uri, expiry=expiry_hours * 3600)

            # Build notification body: summary + link
            summary = body[:500].rstrip()
            if len(body) > 500:
                summary += "..."
            notification_body = summary
            if presigned_url:
                notification_body += f"\n\nFull content: {presigned_url}"
            else:
                notification_body += f"\n\n(Content saved to storage: {uri})"
        except Exception as e:
            logger.warning("S3 upload failed for share_content, sending directly: %s", e)
            notification_body = body[:4000]

    # Send notification
    try:
        from agenticops.notify.notifier import NotificationManager

        manager = NotificationManager()
        channels = [n.strip() for n in channel_names.split(",") if n.strip()] if channel_names else None

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(
                manager.send_notification(
                    subject=subject,
                    body=notification_body,
                    channel_names=channels,
                )
            )
        finally:
            loop.close()

        sent = [ch for ch, ok in results.items() if ok]
        failed = [ch for ch, ok in results.items() if not ok]

        result: Dict = {
            "success": len(sent) > 0,
            "channels_sent": sent,
            "channels_failed": failed,
        }
        if presigned_url:
            result["presigned_url"] = presigned_url
        return json.dumps(result, default=str)

    except Exception as e:
        return json.dumps({"success": False, "message": f"Notification failed: {e}"})


def _distribute_via_report_channel(ch, report_id, title, summary, content_md, report_type, report_meta) -> dict:
    """Handle sns-report or ses channel via the full report pipeline."""
    if ch.channel_type == "ses":
        from agenticops.notify.notifier import SESNotifier
        notifier = SESNotifier(ch.config)
    else:
        from agenticops.notify.notifier import SNSReportNotifier
        notifier = SNSReportNotifier(ch.config)

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            notifier.send_report(
                report_id=report_id,
                title=title,
                summary=summary,
                content_markdown=content_md,
                report_type=report_type,
                report_metadata=report_meta,
            )
        )
    finally:
        loop.close()

    fmts = result.get("formats", [])
    if fmts:
        return {
            "channel": ch.name,
            "format": ch.channel_type,
            "status": "sent",
            "formats_uploaded": fmts,
        }
    if result.get("skipped"):
        return {"channel": ch.name, "format": ch.channel_type, "status": "skipped"}
    return {"channel": ch.name, "format": ch.channel_type, "status": "failed"}
