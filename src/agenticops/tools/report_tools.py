"""Report tools for Strands agents.

Wraps Report model persistence: save reports to DB + markdown files,
and list recent reports.
"""

import json
import logging
from datetime import datetime

from strands import tool

from agenticops.models import Report, get_session

logger = logging.getLogger(__name__)


@tool
def save_report(
    report_type: str,
    title: str,
    summary: str,
    content_markdown: str,
    report_metadata: str = "{}",
) -> str:
    """Save a generated report to the database and write a markdown file.

    Creates a Report record in the database and writes the markdown content
    to a .md file in the reports directory.

    Args:
        report_type: Type of report: daily, incident, or inventory
        title: Report title (max 200 chars)
        summary: Brief summary of the report
        content_markdown: Full report content in markdown format
        report_metadata: Optional JSON object with additional metadata

    Returns:
        Confirmation with the Report ID and file path.
    """
    valid_types = {"daily", "incident", "inventory", "network"}
    if report_type.lower() not in valid_types:
        return f"Invalid report_type '{report_type}'. Valid: {', '.join(sorted(valid_types))}"

    try:
        metadata_parsed = json.loads(report_metadata) if isinstance(report_metadata, str) else report_metadata
    except json.JSONDecodeError:
        metadata_parsed = {}

    # Write via storage backend (local or S3)
    from agenticops.storage import get_storage_backend

    backend = get_storage_backend()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    key = f"{report_type.lower()}/{report_type.lower()}-{timestamp}.md"

    try:
        uri = backend.write(key, content_markdown.encode("utf-8"), "text/markdown")
    except Exception as e:
        return f"Error writing report file: {e}"

    # Save to database
    session = get_session()
    try:
        report = Report(
            report_type=report_type.lower(),
            title=title[:200],
            summary=summary,
            content_markdown=content_markdown,
            file_path=uri,
            report_metadata=metadata_parsed,
        )
        session.add(report)
        session.commit()

        # Auto-notify
        try:
            from agenticops.services.notification_service import notify_report_saved
            notify_report_saved(report.id, report_type, title)
        except Exception:
            logger.debug("Notification trigger failed", exc_info=True)

        return (
            f"Report #{report.id} saved: [{report_type.upper()}] {title}. "
            f"File: {uri}"
        )
    except Exception as e:
        session.rollback()
        # Clean up file if DB write failed
        try:
            backend.delete(uri)
        except Exception:
            pass
        return f"Error saving report: {e}"
    finally:
        session.close()


@tool
def list_reports(report_type: str = "", limit: int = 20) -> str:
    """List recent reports, optionally filtered by type.

    Args:
        report_type: Filter by type (daily, incident, inventory) or empty for all
        limit: Maximum number of results (default 20)

    Returns:
        JSON array of reports with id, report_type, title, summary, file_path, created_at.
    """
    session = get_session()
    try:
        query = session.query(Report).order_by(Report.created_at.desc())

        if report_type:
            query = query.filter_by(report_type=report_type.lower())

        reports = query.limit(min(limit, 100)).all()

        if not reports:
            filter_msg = f" (type={report_type})" if report_type else ""
            return f"No reports found{filter_msg}."

        result = []
        for r in reports:
            result.append({
                "id": r.id,
                "report_type": r.report_type,
                "title": r.title,
                "summary": r.summary,
                "file_path": r.file_path,
                "created_at": str(r.created_at),
            })

        return json.dumps(result, default=str)
    finally:
        session.close()


def get_report_content(file_path: str) -> str | None:
    """Read report content from storage (local or S3) by file_path URI."""
    from agenticops.storage import get_storage_backend

    backend = get_storage_backend()
    try:
        return backend.read(file_path).decode("utf-8")
    except Exception:
        logger.debug("Failed to read report from %s", file_path, exc_info=True)
        return None
