"""Report Generator - Daily and on-demand reports."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from agenticops.config import settings
from agenticops.models import (
    Anomaly,
    AWSAccount,
    AWSResource,
    RCAResult,
    Report,
    get_session,
)

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generator for various report types."""

    def __init__(self, account: Optional[AWSAccount] = None):
        """Initialize report generator."""
        self.account = account
        settings.ensure_dirs()

    def generate_daily_report(
        self,
        date: Optional[datetime] = None,
        save: bool = True,
    ) -> str:
        """Generate daily operations report."""
        if date is None:
            date = datetime.utcnow()

        start_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(days=1)

        session = get_session()

        try:
            # Gather data
            resource_count = session.query(AWSResource).count()
            if self.account:
                resource_count = (
                    session.query(AWSResource)
                    .filter_by(account_id=self.account.id)
                    .count()
                )

            # Get anomalies for the day
            anomaly_query = session.query(Anomaly).filter(
                Anomaly.detected_at >= start_time,
                Anomaly.detected_at < end_time,
            )
            anomalies = anomaly_query.all()

            # Get RCA results
            rca_query = session.query(RCAResult).filter(
                RCAResult.created_at >= start_time,
                RCAResult.created_at < end_time,
            )
            rca_results = rca_query.all()

            # Build report
            report_md = self._build_daily_report_md(
                date=date,
                resource_count=resource_count,
                anomalies=anomalies,
                rca_results=rca_results,
            )

            if save:
                self._save_report(
                    report_type="daily",
                    title=f"Daily Report - {date.strftime('%Y-%m-%d')}",
                    content=report_md,
                )

            return report_md

        finally:
            session.close()

    def _build_daily_report_md(
        self,
        date: datetime,
        resource_count: int,
        anomalies: list[Anomaly],
        rca_results: list[RCAResult],
    ) -> str:
        """Build daily report in Markdown format."""
        # Categorize anomalies by severity
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for a in anomalies:
            severity_counts[a.severity] = severity_counts.get(a.severity, 0) + 1

        # Build markdown
        lines = [
            f"# Daily Operations Report",
            f"**Date**: {date.strftime('%Y-%m-%d')}",
            f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            f"- **Total Resources Monitored**: {resource_count}",
            f"- **Anomalies Detected**: {len(anomalies)}",
            f"- **RCA Analyses Performed**: {len(rca_results)}",
            "",
            "### Anomalies by Severity",
            "",
            f"| Severity | Count |",
            f"|----------|-------|",
            f"| Critical | {severity_counts['critical']} |",
            f"| High | {severity_counts['high']} |",
            f"| Medium | {severity_counts['medium']} |",
            f"| Low | {severity_counts['low']} |",
            "",
        ]

        # Critical and High anomalies section
        critical_high = [a for a in anomalies if a.severity in ["critical", "high"]]
        if critical_high:
            lines.extend(
                [
                    "---",
                    "",
                    "## Critical & High Severity Anomalies",
                    "",
                ]
            )

            for anomaly in critical_high[:10]:  # Limit to 10
                lines.extend(
                    [
                        f"### {anomaly.title}",
                        "",
                        f"- **Severity**: {anomaly.severity.upper()}",
                        f"- **Resource**: {anomaly.resource_type}/{anomaly.resource_id}",
                        f"- **Region**: {anomaly.region}",
                        f"- **Detected**: {anomaly.detected_at.strftime('%H:%M:%S')}",
                        f"- **Status**: {anomaly.status}",
                        "",
                        f"> {anomaly.description}",
                        "",
                    ]
                )

                # Add RCA if available
                rca = next(
                    (r for r in rca_results if r.anomaly_id == anomaly.id), None
                )
                if rca:
                    lines.extend(
                        [
                            "**Root Cause Analysis:**",
                            f"> {rca.root_cause}",
                            "",
                            "**Recommendations:**",
                        ]
                    )
                    for rec in rca.recommendations[:3]:
                        lines.append(f"- {rec}")
                    lines.append("")

        # Resource summary by type
        lines.extend(
            [
                "---",
                "",
                "## Resource Summary",
                "",
            ]
        )

        session = get_session()
        try:
            from sqlalchemy import func

            type_counts = (
                session.query(
                    AWSResource.resource_type,
                    func.count(AWSResource.id).label("count"),
                )
                .group_by(AWSResource.resource_type)
                .all()
            )

            lines.extend(
                [
                    "| Resource Type | Count |",
                    "|---------------|-------|",
                ]
            )
            for rt, count in type_counts:
                lines.append(f"| {rt} | {count} |")
            lines.append("")

        finally:
            session.close()

        # Footer
        lines.extend(
            [
                "---",
                "",
                "*Report generated by AgenticAIOps*",
            ]
        )

        return "\n".join(lines)

    def generate_anomaly_report(
        self,
        anomaly: Anomaly,
        rca: Optional[RCAResult] = None,
        save: bool = True,
    ) -> str:
        """Generate detailed report for a single anomaly."""
        lines = [
            f"# Anomaly Report",
            "",
            f"**ID**: {anomaly.id}",
            f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "---",
            "",
            "## Anomaly Details",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Title | {anomaly.title} |",
            f"| Severity | {anomaly.severity.upper()} |",
            f"| Type | {anomaly.anomaly_type} |",
            f"| Status | {anomaly.status} |",
            f"| Detected | {anomaly.detected_at} |",
            "",
            "## Resource Information",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Resource ID | {anomaly.resource_id} |",
            f"| Resource Type | {anomaly.resource_type} |",
            f"| Region | {anomaly.region} |",
            "",
            "## Metrics",
            "",
            f"| Metric | Expected | Actual | Deviation |",
            f"|--------|----------|--------|-----------|",
            f"| {anomaly.metric_name or 'N/A'} | {anomaly.expected_value or 'N/A'} | {anomaly.actual_value or 'N/A'} | {f'{anomaly.deviation_percent:.1f}%' if anomaly.deviation_percent else 'N/A'} |",
            "",
            "## Description",
            "",
            f"> {anomaly.description}",
            "",
        ]

        if rca:
            lines.extend(
                [
                    "---",
                    "",
                    "## Root Cause Analysis",
                    "",
                    f"**Confidence**: {rca.confidence_score * 100:.0f}%",
                    "",
                    "### Root Cause",
                    "",
                    f"{rca.root_cause}",
                    "",
                    "### Contributing Factors",
                    "",
                ]
            )
            for factor in rca.contributing_factors:
                lines.append(f"- {factor}")

            lines.extend(
                [
                    "",
                    "### Recommendations",
                    "",
                ]
            )
            for i, rec in enumerate(rca.recommendations, 1):
                lines.append(f"{i}. {rec}")

            if rca.related_resources:
                lines.extend(
                    [
                        "",
                        "### Related Resources",
                        "",
                    ]
                )
                for res in rca.related_resources:
                    lines.append(f"- {res}")

        lines.extend(
            [
                "",
                "---",
                "",
                "*Report generated by AgenticAIOps*",
            ]
        )

        report_md = "\n".join(lines)

        if save:
            self._save_report(
                report_type="anomaly",
                title=f"Anomaly Report - {anomaly.title}",
                content=report_md,
            )

        return report_md

    def generate_inventory_report(self, save: bool = True) -> str:
        """Generate resource inventory report."""
        session = get_session()

        try:
            query = session.query(AWSResource)
            if self.account:
                query = query.filter_by(account_id=self.account.id)

            resources = query.all()

            lines = [
                "# Resource Inventory Report",
                "",
                f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                f"**Total Resources**: {len(resources)}",
                "",
                "---",
                "",
            ]

            # Group by service type
            by_type: dict[str, list[AWSResource]] = {}
            for r in resources:
                if r.resource_type not in by_type:
                    by_type[r.resource_type] = []
                by_type[r.resource_type].append(r)

            for service_type, service_resources in sorted(by_type.items()):
                lines.extend(
                    [
                        f"## {service_type} ({len(service_resources)} resources)",
                        "",
                        "| Resource ID | Name | Region | Status |",
                        "|-------------|------|--------|--------|",
                    ]
                )

                for r in service_resources[:50]:  # Limit per service
                    name = r.resource_name or "-"
                    lines.append(f"| {r.resource_id} | {name} | {r.region} | {r.status} |")

                lines.append("")

            report_md = "\n".join(lines)

            if save:
                self._save_report(
                    report_type="inventory",
                    title="Resource Inventory Report",
                    content=report_md,
                )

            return report_md

        finally:
            session.close()

    def _save_report(
        self,
        report_type: str,
        title: str,
        content: str,
    ) -> Report:
        """Save report to database and file."""
        session = get_session()

        try:
            # Save to file
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{report_type}_{timestamp}.md"
            file_path = settings.reports_dir / filename

            file_path.write_text(content)
            logger.info(f"Report saved to {file_path}")

            # Save to database
            report = Report(
                report_type=report_type,
                title=title,
                summary=content[:500],
                content_markdown=content,
                file_path=str(file_path),
            )
            session.add(report)
            session.commit()

            return report

        except Exception as e:
            session.rollback()
            logger.exception("Failed to save report")
            raise
        finally:
            session.close()

    def get_recent_reports(
        self,
        report_type: Optional[str] = None,
        limit: int = 10,
    ) -> list[Report]:
        """Get recent reports."""
        session = get_session()

        try:
            query = session.query(Report).order_by(Report.created_at.desc())

            if report_type:
                query = query.filter_by(report_type=report_type)

            return query.limit(limit).all()

        finally:
            session.close()
