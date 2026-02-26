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

    def generate_network_health_report(self, regions: Optional[list[str]] = None, save: bool = True) -> str:
        """Generate a network health report across all configured regions.

        Collects region topology, per-VPC anomaly detection, and network
        segmentation analysis, then produces a consolidated markdown report.

        Args:
            regions: List of AWS regions to report on. If None, uses the
                     active account's configured regions.
            save: Whether to persist the report to DB and file.

        Returns:
            Markdown report string.
        """
        import json
        from agenticops.tools.network_tools import describe_region_topology, analyze_vpc_topology
        from agenticops.graph.engine import InfraGraph
        from agenticops.graph.algorithms import detect_anomalies as graph_detect_anomalies, network_segments

        # Resolve regions
        if not regions:
            if self.account and self.account.regions:
                regions = self.account.regions
            else:
                regions = ["us-east-1"]

        now = datetime.utcnow()
        lines = [
            "# Network Health Report",
            f"**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Regions**: {', '.join(regions)}",
            "",
            "---",
            "",
        ]

        total_vpcs = 0
        total_subnets = 0
        total_tgws = 0
        total_peerings = 0
        all_anomalies: list[dict] = []

        for region in regions:
            try:
                raw = describe_region_topology(region=region)
                topo = json.loads(raw)
            except Exception as e:
                lines.extend([f"## {region}", "", f"> ⚠ Failed to collect topology: {e}", ""])
                continue

            vpcs = topo.get("vpcs", [])
            tgws = topo.get("transit_gateways", [])
            peerings = topo.get("peering_connections", [])
            total_vpcs += len(vpcs)
            total_tgws += len(tgws)
            total_peerings += len(peerings)

            lines.extend([f"## {region}", ""])

            # Region summary table
            lines.extend([
                "| Metric | Count |",
                "|--------|-------|",
                f"| VPCs | {len(vpcs)} |",
                f"| Transit Gateways | {len(tgws)} |",
                f"| VPC Peering Connections | {len(peerings)} |",
                "",
            ])

            # Per-VPC analysis
            for vpc in vpcs:
                vpc_id = vpc.get("vpc_id", "")
                vpc_name = vpc.get("name") or vpc_id
                subnet_count = vpc.get("subnet_count", 0)
                total_subnets += subnet_count

                try:
                    vpc_raw = analyze_vpc_topology(region=region, vpc_id=vpc_id)
                    vpc_topo = json.loads(vpc_raw)
                except Exception:
                    lines.extend([f"### {vpc_name} (`{vpc_id}`)", "", "> ⚠ Failed to analyze", ""])
                    continue

                reach = vpc_topo.get("reachability_summary", {})
                blackholes = vpc_topo.get("blackhole_routes", [])
                issues = reach.get("issues", [])

                # Graph anomaly detection
                try:
                    graph = InfraGraph().build_from_vpc_topology(vpc_topo)
                    anomaly_report = graph_detect_anomalies(graph)
                    vpc_anomalies = [a.model_dump() for a in anomaly_report.anomalies]
                except Exception:
                    vpc_anomalies = []

                for a in vpc_anomalies:
                    a["region"] = region
                    a["vpc_id"] = vpc_id
                all_anomalies.extend(vpc_anomalies)

                status = "🟢 Healthy" if not vpc_anomalies and not issues else "🔴 Issues Detected"
                lines.extend([
                    f"### {vpc_name} (`{vpc_id}`) — {status}",
                    "",
                    f"- CIDR: `{vpc_topo.get('vpc_cidr', '-')}`",
                    f"- Subnets: {reach.get('public_subnet_count', 0)} public / {reach.get('private_subnet_count', 0)} private",
                    f"- Internet Gateway: {'Yes' if reach.get('has_internet_gateway') else 'No'}",
                    f"- NAT Gateways: {reach.get('nat_gateway_count', 0)}",
                    f"- TGW Attachments: {reach.get('transit_gateway_attachments', 0)}",
                    f"- VPC Endpoints: {reach.get('vpc_endpoint_count', 0)}",
                    f"- Blackhole Routes: {len(blackholes)}",
                    f"- Anomalies: {len(vpc_anomalies)}",
                    "",
                ])

                if vpc_anomalies:
                    lines.extend([
                        "| Severity | Type | Description |",
                        "|----------|------|-------------|",
                    ])
                    for a in vpc_anomalies:
                        lines.append(f"| {a['severity'].upper()} | {a['type']} | {a['description']} |")
                    lines.append("")

                if issues:
                    lines.append("**Issues:**")
                    for issue in issues:
                        lines.append(f"- {issue}")
                    lines.append("")

        # Executive summary at the top (insert after header)
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for a in all_anomalies:
            sev = a.get("severity", "medium")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        summary_lines = [
            "## Executive Summary",
            "",
            f"- **Regions Scanned**: {len(regions)}",
            f"- **Total VPCs**: {total_vpcs}",
            f"- **Total Subnets**: {total_subnets}",
            f"- **Transit Gateways**: {total_tgws}",
            f"- **VPC Peerings**: {total_peerings}",
            f"- **Network Anomalies**: {len(all_anomalies)}",
            "",
            "| Severity | Count |",
            "|----------|-------|",
            f"| Critical | {severity_counts['critical']} |",
            f"| High | {severity_counts['high']} |",
            f"| Medium | {severity_counts['medium']} |",
            f"| Low | {severity_counts['low']} |",
            "",
        ]

        # Insert summary after the header block (after "---\n\n")
        insert_idx = lines.index("---") + 2
        for i, sl in enumerate(summary_lines):
            lines.insert(insert_idx + i, sl)

        lines.extend(["---", "", "*Report generated by AgenticOps*"])
        report_md = "\n".join(lines)

        if save:
            self._save_report(
                report_type="network",
                title=f"Network Health Report - {now.strftime('%Y-%m-%d')}",
                content=report_md,
            )

        return report_md

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
