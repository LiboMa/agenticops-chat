"""Metrics Collector - Scheduled metrics collection."""

import logging
from datetime import datetime
from typing import Optional

from agenticops.models import AWSAccount, AWSResource, MonitoringConfig, get_session
from agenticops.monitor.cloudwatch import CloudWatchMonitor

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collector for scheduled metrics gathering."""

    def __init__(self, account: AWSAccount):
        """Initialize collector with account."""
        self.account = account
        self.monitor = CloudWatchMonitor(account)

    def collect_for_resource(
        self,
        resource: AWSResource,
        hours: int = 1,
        save: bool = True,
    ) -> dict:
        """Collect metrics for a single resource."""
        logger.info(f"Collecting metrics for {resource.resource_type}:{resource.resource_id}")

        metrics = self.monitor.get_service_metrics(
            service_type=resource.resource_type,
            resource_id=resource.resource_id,
            region=resource.region,
            hours=hours,
        )

        if save and metrics:
            saved = self.monitor.save_metric_data(resource.resource_id, metrics)
            logger.info(f"Saved {saved} data points")

        return metrics

    def collect_for_service(
        self,
        service_type: str,
        region: Optional[str] = None,
        hours: int = 1,
        save: bool = True,
    ) -> dict[str, dict]:
        """Collect metrics for all resources of a service type."""
        session = get_session()
        results = {}

        try:
            query = session.query(AWSResource).filter_by(
                account_id=self.account.id,
                resource_type=service_type,
            )

            if region:
                query = query.filter_by(region=region)

            resources = query.all()
            logger.info(f"Found {len(resources)} {service_type} resources to collect metrics for")

            for resource in resources:
                try:
                    metrics = self.collect_for_resource(resource, hours, save)
                    results[resource.resource_id] = metrics
                except Exception as e:
                    logger.warning(f"Failed to collect metrics for {resource.resource_id}: {e}")

        finally:
            session.close()

        return results

    def collect_all(
        self,
        hours: int = 1,
        save: bool = True,
    ) -> dict[str, dict[str, dict]]:
        """Collect metrics for all monitored resources."""
        session = get_session()
        results = {}

        try:
            # Get enabled monitoring configs
            configs = (
                session.query(MonitoringConfig)
                .filter_by(account_id=self.account.id, is_enabled=True)
                .all()
            )

            for config in configs:
                logger.info(f"Collecting metrics for service: {config.service_type}")
                service_results = self.collect_for_service(
                    service_type=config.service_type,
                    hours=hours,
                    save=save,
                )
                results[config.service_type] = service_results

        finally:
            session.close()

        return results

    def get_collection_summary(self) -> dict:
        """Get summary of collected metrics."""
        session = get_session()

        try:
            from sqlalchemy import func

            from agenticops.models import MetricDataPoint

            # Count by resource
            resource_counts = (
                session.query(
                    MetricDataPoint.resource_id,
                    func.count(MetricDataPoint.id).label("count"),
                    func.min(MetricDataPoint.timestamp).label("earliest"),
                    func.max(MetricDataPoint.timestamp).label("latest"),
                )
                .group_by(MetricDataPoint.resource_id)
                .all()
            )

            return {
                "total_resources": len(resource_counts),
                "resources": [
                    {
                        "resource_id": r.resource_id,
                        "data_points": r.count,
                        "earliest": r.earliest.isoformat() if r.earliest else None,
                        "latest": r.latest.isoformat() if r.latest else None,
                    }
                    for r in resource_counts
                ],
            }
        finally:
            session.close()
