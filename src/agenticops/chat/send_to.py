"""/send_to command processor — shared by CLI, Web chat, and IM chat.

Syntax: /send_to <target> #R<id>, #D<id>, #I<id>, "free text"

References:
  #R<id>  → Report (by Report.id) — includes content_markdown[:2000]
  #D<id>  → LocalDoc (by LocalDoc.id) — reads file content[:4000]
  #I<id>  → HealthIssue (by HealthIssue.id) — formatted issue summary with RCA
  Free text → passed as-is

Target resolution order:
  1. NotificationChannel.name (exact match, is_enabled=True) → NotificationManager
  2. IMAlias.name (exact match) → platform-specific Notifier directly
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"#([RDI])(\d+)")


@dataclass
class SendToResult:
    success: bool
    message: str


def parse_send_to(command: str) -> tuple[Optional[str], str]:
    """Parse a /send_to command string.

    Args:
        command: Full command string, e.g. "/send_to ops-team #R1 check this"

    Returns:
        (target, content_spec) on success, or (None, help_text) on failure.
    """
    # Strip the /send_to prefix
    text = command.strip()
    for prefix in ("/send_to ", "/sendto "):
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break
    else:
        # Just "/send_to" with no args
        if text.lower().rstrip() in ("/send_to", "/sendto"):
            return None, _help_text()
        return None, _help_text()

    if not text:
        return None, _help_text()

    # First token is the target
    parts = text.split(None, 1)
    target = parts[0]
    content_spec = parts[1] if len(parts) > 1 else ""

    if not content_spec:
        return None, f"Missing content for target '{target}'. Usage: /send_to <target> #R<id>, #I<id>, or \"text\""

    return target, content_spec


def _help_text() -> str:
    return (
        "Usage: /send_to <target> <content>\n\n"
        "Target: notification channel name or IM alias name\n"
        "Content:\n"
        "  #R<id>  — Send Report by ID\n"
        "  #D<id>  — Send LocalDoc by ID\n"
        "  #I<id>  — Send HealthIssue by ID\n"
        "  \"text\" — Send free text\n\n"
        "Examples:\n"
        "  /send_to ops-team #R1\n"
        "  /send_to sre-oncall #I42\n"
        "  /send_to sre-oncall #D3 please review\n"
        "  /send_to slack-alerts Critical: service down"
    )


def resolve_target(name: str) -> tuple[str, dict]:
    """Resolve a target name to a channel or IM alias config.

    Channels are resolved from channels.yaml; IM aliases from DB.

    Returns:
        ("channel", channel_config) or ("im", alias_config) or ("unknown", {})
    """
    # Try channels.yaml first
    from agenticops.notify.im_config import get_channel

    channel = get_channel(name)
    if channel and channel.is_enabled:
        return "channel", {
            "name": channel.name,
            "channel_type": channel.channel_type,
            "config": channel.config,
        }

    # Try IMAlias (still in DB)
    from agenticops.models import IMAlias, get_db_session

    with get_db_session() as db:
        alias = db.query(IMAlias).filter_by(name=name).first()
        if alias:
            return "im", {
                "name": alias.name,
                "platform": alias.platform,
                "chat_id": alias.chat_id,
                "app_name": alias.app_name,
            }

    return "unknown", {}


def resolve_content(spec: str) -> tuple[str, str]:
    """Resolve content spec (#R<id>, #D<id>, free text) into (subject, body).

    Returns:
        (subject, body) tuple.
    """
    parts = []
    free_text_parts = []

    # Split by whitespace-separated tokens, matching references
    tokens = spec.split()
    for token in tokens:
        m = _REF_RE.match(token)
        if m:
            ref_type, ref_id = m.group(1), int(m.group(2))
            if ref_type == "R":
                subject, body = _resolve_report(ref_id)
                if body:
                    parts.append((subject, body))
                else:
                    free_text_parts.append(f"(Report #{ref_id} not found)")
            elif ref_type == "D":
                subject, body = _resolve_local_doc(ref_id)
                if body:
                    parts.append((subject, body))
                else:
                    free_text_parts.append(f"(LocalDoc #{ref_id} not found)")
            elif ref_type == "I":
                subject, body = _resolve_issue(ref_id)
                if body:
                    parts.append((subject, body))
                else:
                    free_text_parts.append(f"(Issue #{ref_id} not found)")
        else:
            free_text_parts.append(token)

    # Build final subject and body
    if parts and free_text_parts:
        subject = parts[0][0]
        body = "\n\n".join(b for _, b in parts) + "\n\n" + " ".join(free_text_parts)
    elif parts:
        subject = parts[0][0]
        body = "\n\n".join(b for _, b in parts)
    else:
        text = " ".join(free_text_parts)
        subject = text[:100]
        body = text

    return subject, body


def _resolve_report(report_id: int) -> tuple[str, str]:
    """Resolve a Report reference."""
    try:
        from agenticops.models import Report, get_db_session

        with get_db_session() as db:
            report = db.query(Report).filter_by(id=report_id).first()
            if not report:
                return "", ""
            subject = f"Report #{report.id}: {report.title}"
            body = report.content_markdown[:2000] if report.content_markdown else report.summary
            return subject, body
    except Exception:
        logger.debug("Failed to resolve Report #%d", report_id, exc_info=True)
        return "", ""


def _resolve_local_doc(doc_id: int) -> tuple[str, str]:
    """Resolve a LocalDoc reference."""
    try:
        from agenticops.models import LocalDoc, get_db_session

        with get_db_session() as db:
            doc = db.query(LocalDoc).filter_by(id=doc_id).first()
            if not doc:
                return "", ""

            subject = f"Doc #{doc.id}: {doc.title}"

            # Read file content
            try:
                content = Path(doc.file_path).read_text(encoding="utf-8", errors="replace")[:4000]
            except Exception:
                content = f"(Could not read file: {doc.file_path})"

            return subject, content
    except Exception:
        logger.debug("Failed to resolve LocalDoc #%d", doc_id, exc_info=True)
        return "", ""


def _resolve_issue(issue_id: int) -> tuple[str, str]:
    """Resolve a HealthIssue reference."""
    try:
        from agenticops.models import HealthIssue, RCAResult, get_db_session

        with get_db_session() as db:
            issue = db.query(HealthIssue).filter_by(id=issue_id).first()
            if not issue:
                return "", ""

            subject = f"Issue #{issue.id} [{issue.severity.upper()}]: {issue.title}"
            lines = [
                f"**Issue #{issue.id}**: {issue.title}",
                f"**Severity**: {issue.severity} | **Status**: {issue.status}",
                f"**Resource**: {issue.resource_id}",
                f"**Source**: {issue.source}",
                f"**Detected**: {issue.detected_at}",
                "",
                issue.description[:2000] if issue.description else "",
            ]

            # Append RCA if available
            rca = (
                db.query(RCAResult)
                .filter_by(health_issue_id=issue.id)
                .order_by(RCAResult.id.desc())
                .first()
            )
            if rca:
                lines.append("")
                lines.append(f"**Root Cause** (confidence {rca.confidence:.0%}): {rca.root_cause[:1000]}")

            return subject, "\n".join(lines)
    except Exception:
        logger.debug("Failed to resolve Issue #%d", issue_id, exc_info=True)
        return "", ""


def execute_send_to(command: str) -> SendToResult:
    """Execute a /send_to command synchronously.

    Shared by CLI, Web chat, and IM chat interfaces.

    Args:
        command: Full command string, e.g. "/send_to ops-team #R1"

    Returns:
        SendToResult with success flag and message.
    """
    target_name, content_or_help = parse_send_to(command)
    if target_name is None:
        return SendToResult(success=False, message=content_or_help)

    # Resolve target
    target_type, target_config = resolve_target(target_name)
    if target_type == "unknown":
        return SendToResult(
            success=False,
            message=f"Target '{target_name}' not found. Check notification channels or IM aliases.",
        )

    # Resolve content
    subject, body = resolve_content(content_or_help)
    if not body.strip():
        return SendToResult(success=False, message="No content to send.")

    # Send
    try:
        if target_type == "channel":
            return _send_via_channel(target_name, subject, body)
        else:
            return _send_via_im(target_config, subject, body)
    except Exception as e:
        logger.error("send_to failed: %s", e)
        return SendToResult(success=False, message=f"Send failed: {e}")


def _send_via_channel(channel_name: str, subject: str, body: str) -> SendToResult:
    """Send via NotificationManager to a specific channel.

    For sns-report channels with a #R<id> reference, triggers rich report distribution
    (formatted files uploaded to S3 with presigned URLs).
    """
    from agenticops.notify.im_config import get_channel

    channel = get_channel(channel_name)

    # Rich report distribution for sns-report channels
    if channel and channel.channel_type == "sns-report":
        report_id = _extract_report_id(body)
        if report_id:
            return _send_report_via_channel(channel_name, channel.config, report_id)

    # Default: plain text via NotificationManager
    from agenticops.notify.notifier import NotificationManager

    manager = NotificationManager()
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(
            manager.send_notification(
                subject=subject,
                body=body,
                channel_names=[channel_name],
            )
        )
    finally:
        loop.close()

    if not results:
        return SendToResult(success=False, message=f"No enabled channel '{channel_name}' found.")

    success = all(results.values())
    detail = ", ".join(f"{k}: {'OK' if v else 'FAILED'}" for k, v in results.items())
    return SendToResult(
        success=success,
        message=f"Sent to {channel_name}: {detail}",
    )


def _extract_report_id(body: str) -> Optional[int]:
    """Extract a Report ID from body text (looks for 'Report #N' pattern)."""
    m = re.search(r"Report\s*#(\d+)", body)
    return int(m.group(1)) if m else None


def _send_report_via_channel(
    channel_name: str, config: dict, report_id: int,
) -> SendToResult:
    """Send a formatted report via sns-report channel."""
    from agenticops.notify.notifier import SNSReportNotifier
    from agenticops.models import Report, get_db_session

    with get_db_session() as db:
        report = db.query(Report).filter_by(id=report_id).first()
        if not report:
            return SendToResult(success=False, message=f"Report #{report_id} not found.")
        title = report.title
        summary = report.summary
        content_md = report.content_markdown
        report_type = report.report_type

    notifier = SNSReportNotifier(config)
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            notifier.send_report(
                report_id=report_id,
                title=title,
                summary=summary,
                content_markdown=content_md,
                report_type=report_type,
            )
        )
    finally:
        loop.close()

    fmts = result.get("formats", [])
    urls = result.get("urls", {})
    if fmts:
        url_lines = ", ".join(f"{k}: {v[:60]}..." for k, v in urls.items())
        return SendToResult(
            success=True,
            message=f"Report #{report_id} published to {channel_name} ({', '.join(fmts)}). {url_lines}",
        )
    return SendToResult(
        success=False,
        message=f"Report #{report_id} distribution to {channel_name} produced no formats.",
    )


def _send_via_im(config: dict, subject: str, body: str) -> SendToResult:
    """Send directly to an IM group chat via platform-specific Notifier."""
    platform = config["platform"]
    chat_id = config["chat_id"]
    app_name = config.get("app_name", "default")

    notifier_map = {
        "feishu": "FeishuNotifier",
        "dingtalk": "DingTalkNotifier",
        "wecom": "WeComNotifier",
    }

    notifier_cls_name = notifier_map.get(platform)
    if not notifier_cls_name:
        return SendToResult(success=False, message=f"Unsupported IM platform: {platform}")

    from agenticops.notify import notifier as notifier_mod

    notifier_cls = getattr(notifier_mod, notifier_cls_name)
    notifier = notifier_cls({"chat_id": chat_id, "app_name": app_name})

    loop = asyncio.new_event_loop()
    try:
        success = loop.run_until_complete(notifier.send(subject=subject, body=body))
    finally:
        loop.close()

    if success:
        return SendToResult(success=True, message=f"Sent to {config['name']} ({platform}:{chat_id[:20]})")
    else:
        return SendToResult(success=False, message=f"Failed to send to {config['name']} ({platform})")
