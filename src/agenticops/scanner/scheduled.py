"""The resource-scan schedule: the W2 scan of POST /api/scan on a timer, so a resource that vanished from a
completely listed type and region is marked absent within one interval even when nobody triggers a scan."""

import asyncio
import logging

from agenticops.config import settings
from agenticops.models import CloudAccount, get_db_session
from agenticops.scanner.engine import PROVIDER_COMMANDS, scan_accounts_parallel

logger = logging.getLogger(__name__)

SCHEDULE_NAME = "resource-scan"
PIPELINE_NAME = "ResourceScan"


def seed_scan_schedule() -> bool:
    """Create the resource-scan schedule once (startup, scheduler worker). An existing row — even one a user
    edited or disabled — is left alone. True when it was created."""
    from agenticops.scheduler.scheduler import Schedule, Scheduler
    from agenticops.security.posture_snapshot import cron_from_interval

    with get_db_session() as s:
        if s.query(Schedule.id).filter_by(name=SCHEDULE_NAME).first():
            return False
    cron = cron_from_interval(settings.resource_scan_interval_minutes)
    Scheduler.add_schedule(name=SCHEDULE_NAME, pipeline_name=PIPELINE_NAME, cron_expression=cron, config={})
    logger.info("scan: seeded %s schedule (cron=%s)", SCHEDULE_NAME, cron)
    return True


def run_scheduled_scan(account_name: str | None = None) -> dict:
    """One W2 scan of every enabled account of a provider the scan has commands for (a kubernetes account is
    the K8s connector's), or only the schedule's own account. Runs on the scheduler thread, which has no event
    loop. `skipped_accounts` names each selected account whose credentials failed: its rows were neither
    refreshed nor marked this run."""
    with get_db_session() as s:
        q = s.query(CloudAccount.id, CloudAccount.name).filter(CloudAccount.is_enabled == True,  # noqa: E712
                                                               CloudAccount.provider.in_(list(PROVIDER_COMMANDS)))
        if account_name:
            q = q.filter(CloudAccount.name == account_name)
        selected = q.order_by(CloudAccount.id).all()
    if account_name and not selected:
        raise ValueError(f"account '{account_name}' not found, disabled or of a provider the scan cannot list")
    if not selected:
        return {"pipeline": PIPELINE_NAME, "accounts": 0, "total_found": 0, "total_updated": 0,
                "resources_absent": 0, "errors": 0, "skipped_accounts": []}
    # Explicit ids: scan_accounts_parallel reads an empty list as "every enabled account".
    result = asyncio.run(scan_accounts_parallel(account_ids=[pk for pk, _ in selected]))
    scanned = {a.account_name for a in result.accounts}
    return {
        "pipeline": PIPELINE_NAME,
        "accounts": len(result.accounts),
        "total_found": result.total_found,
        "total_updated": result.total_updated,
        "resources_absent": sum(a.resources_absent for a in result.accounts),
        "errors": sum(len(a.errors) for a in result.accounts),
        "skipped_accounts": [name for _, name in selected if name not in scanned],
    }
