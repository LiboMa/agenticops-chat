"""Auto-notification service — fire-and-forget notifications on pipeline events.

Sends notifications to all enabled NotificationChannels when key events occur
(issue created, RCA done, fix planned, approved, executed, report saved, schedule run).

Non-blocking: runs async NotificationManager.send_notification() in a daemon thread
with a fresh event loop. Follows the same pattern as pipeline_service.py.

Gated by settings.notifications_enabled — when disabled, all calls are no-ops.
"""

import asyncio
import logging
import threading
from typing import Optional

from agenticops.config import settings

logger = logging.getLogger(__name__)


def notify_event(
    event_type: str,
    subject: str,
    body: str,
    severity: Optional[str] = None,
    channel_names: Optional[list[str]] = None,
) -> None:
    """Fire-and-forget: send a notification to all matching channels.

    Runs in a daemon thread with its own event loop. Never raises —
    errors are logged at debug level and swallowed.

    Args:
        event_type: Event identifier (e.g. "issue_created", "rca_completed").
        subject: Notification subject line.
        body: Notification body text.
        severity: Optional severity for channel filtering.
        channel_names: Optional list of specific channels to target.
    """
    if not settings.notifications_enabled:
        return

    thread = threading.Thread(
        target=_run_notify,
        args=(event_type, subject, body, severity, channel_names),
        daemon=True,
        name=f"notify-{event_type}",
    )
    thread.start()


def _run_notify(
    event_type: str,
    subject: str,
    body: str,
    severity: Optional[str],
    channel_names: Optional[list[str]],
) -> None:
    """Send notification in a new event loop (runs in daemon thread)."""
    try:
        from agenticops.notify.notifier import NotificationManager

        manager = NotificationManager()
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(
                manager.send_notification(
                    subject=subject,
                    body=body,
                    severity=severity,
                    channel_names=channel_names,
                )
            )
            if results:
                ok = sum(1 for v in results.values() if v)
                fail = len(results) - ok
                logger.info(
                    "Notification [%s]: sent=%d failed=%d channels=%s",
                    event_type, ok, fail, list(results.keys()),
                )
        finally:
            loop.close()
    except Exception:
        logger.debug("Notification [%s] failed", event_type, exc_info=True)


# ── Convenience functions (called from tool/service code) ─────────────


def notify_issue_created(
    issue_id: int, severity: str, title: str, resource_id: str
) -> None:
    """Notify: new HealthIssue created."""
    notify_event(
        event_type="issue_created",
        subject=f"[{severity.upper()}] New Issue #{issue_id}: {title}",
        body=(
            f"HealthIssue #{issue_id} detected.\n\n"
            f"Resource: {resource_id}\n"
            f"Severity: {severity.upper()}\n"
            f"Title: {title}"
        ),
        severity=severity,
    )


def notify_rca_completed(
    issue_id: int, root_cause: str, confidence: float
) -> None:
    """Notify: RCA completed for an issue."""
    notify_event(
        event_type="rca_completed",
        subject=f"RCA Completed for Issue #{issue_id}",
        body=(
            f"Root cause analysis completed for HealthIssue #{issue_id}.\n\n"
            f"Root Cause: {root_cause[:300]}\n"
            f"Confidence: {confidence:.0%}"
        ),
    )


def notify_fix_planned(
    issue_id: int, plan_id: int, risk_level: str, title: str
) -> None:
    """Notify: fix plan generated."""
    notify_event(
        event_type="fix_planned",
        subject=f"Fix Plan #{plan_id} ({risk_level}) for Issue #{issue_id}",
        body=(
            f"Fix plan generated for HealthIssue #{issue_id}.\n\n"
            f"Plan #{plan_id}: {title}\n"
            f"Risk Level: {risk_level}"
        ),
    )


def notify_fix_approved(
    plan_id: int, approved_by: str, risk_level: str
) -> None:
    """Notify: fix plan approved."""
    notify_event(
        event_type="fix_approved",
        subject=f"Fix Plan #{plan_id} Approved ({risk_level})",
        body=(
            f"FixPlan #{plan_id} has been approved.\n\n"
            f"Approved by: {approved_by}\n"
            f"Risk Level: {risk_level}"
        ),
    )


def notify_execution_result(
    plan_id: int, issue_id: int, status: str, error: str = ""
) -> None:
    """Notify: fix execution completed (success or failure)."""
    severity = "high" if status != "succeeded" else None
    body = (
        f"Execution result for FixPlan #{plan_id} (Issue #{issue_id}).\n\n"
        f"Status: {status.upper()}"
    )
    if error:
        body += f"\nError: {error[:300]}"
    notify_event(
        event_type="execution_result",
        subject=f"Execution {status.upper()}: Plan #{plan_id}",
        body=body,
        severity=severity,
    )


def notify_report_saved(
    report_id: int, report_type: str, title: str
) -> None:
    """Notify: report generated and saved.

    Also triggers rich report distribution to any enabled sns-report channels.
    """
    # Plain text notification (existing behaviour)
    notify_event(
        event_type="report_saved",
        subject=f"Report #{report_id} Generated: {title}",
        body=(
            f"A new {report_type} report has been generated.\n\n"
            f"Report #{report_id}: {title}"
        ),
    )

    # Rich report distribution to sns-report channels
    if settings.notifications_enabled:
        _trigger_report_distribution(report_id, report_type)


def _trigger_report_distribution(report_id: int, report_type: str) -> None:
    """Fire-and-forget: distribute formatted report to sns-report channels."""
    thread = threading.Thread(
        target=_run_report_distribution,
        args=(report_id, report_type),
        daemon=True,
        name=f"report-dist-{report_id}",
    )
    thread.start()


def _run_report_distribution(report_id: int, report_type: str) -> None:
    """Load report from DB, find sns-report channels, call send_report()."""
    try:
        from agenticops.notify.im_config import load_channels
        from agenticops.notify.notifier import SNSReportNotifier
        from agenticops.models import Report, get_db_session

        # Find enabled sns-report channels
        channels = [
            c for c in load_channels()
            if c.channel_type == "sns-report" and c.is_enabled
        ]
        if not channels:
            return

        # Load report from DB
        with get_db_session() as db:
            report = db.query(Report).filter_by(id=report_id).first()
            if not report:
                logger.debug("Report #%d not found for distribution", report_id)
                return
            title = report.title
            summary = report.summary
            content_md = report.content_markdown
            report_meta = report.report_metadata or {}

        loop = asyncio.new_event_loop()
        try:
            for ch in channels:
                # Filter by report_types config (empty = all)
                ch_report_types = ch.config.get("report_types", [])
                if ch_report_types and report_type not in ch_report_types:
                    continue

                notifier = SNSReportNotifier(ch.config)
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
                    fmts = result.get("formats", [])
                    logger.info(
                        "Report #%d distributed to '%s': formats=%s",
                        report_id, ch.name, fmts,
                    )
                except Exception:
                    logger.debug(
                        "Report distribution to '%s' failed", ch.name, exc_info=True,
                    )
        finally:
            loop.close()
    except Exception:
        logger.debug("Report distribution for #%d failed", report_id, exc_info=True)


def notify_schedule_result(
    name: str, success: bool, error: str = ""
) -> None:
    """Notify: scheduled pipeline completed or failed."""
    status = "completed" if success else "failed"
    severity = "high" if not success else None
    body = f"Scheduled pipeline '{name}' {status}."
    if error:
        body += f"\nError: {error[:300]}"
    notify_event(
        event_type="schedule_result",
        subject=f"Schedule '{name}' {status.upper()}",
        body=body,
        severity=severity,
    )
