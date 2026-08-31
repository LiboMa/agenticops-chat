"""Slow-frequency security posture snapshot job (SecurityPostureSnapshot).

Stage 0: stub entry point + cron helper. Stage 1 fills in collect->score->persist.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from agenticops.config import settings
from agenticops.models import SecuritySnapshot, get_db_session
from agenticops.security.collectors import _enabled_regions, collect_posture
from agenticops.security.scoring import score

logger = logging.getLogger(__name__)


def cron_from_interval(minutes: int) -> str:
    """Interval minutes -> cron. Mirrors the galaxy-auto-build seed helper:
    <60 -> every N minutes; >=60 -> minute 0 of every (N//60) hours."""
    m = max(1, int(minutes))
    if m < 60:
        return f"*/{m} * * * *"
    return f"0 */{max(1, m // 60)} * * *"


def _resolve_security_accounts() -> list[str]:
    """Enabled account NAMES — the platform's account-addressing key, passed
    straight to collectors' _get_client(svc, region, account). Uses the resolver's
    official helper (CloudAccount has no `account_id`/`is_active` column; it keys
    by `name` and filters `is_enabled`). Empty on failure — never ambient."""
    try:
        from agenticops.credentials.resolver import list_enabled_accounts
        return [a.name for a in list_enabled_accounts("aws")]
    except Exception as e:
        logger.warning("resolve security accounts failed: %s", e)
        return []


def _prune_old_snapshots(session) -> None:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.security_snapshot_retention_days)
    session.query(SecuritySnapshot).filter(SecuritySnapshot.created_at < cutoff).delete()


def _agg_get_client(service: str, region: str, account: str):
    """Indirection point so tests can patch the provider-layer client."""
    from agenticops.security.collectors import _get_client
    return _get_client(service, region, account)


def _aggregate_topology(account: str) -> tuple[dict, dict, dict, dict]:
    """(instances, subnets, security_groups, nacls) across enabled regions.
    Fail-soft per region and per VPC — partial data is fine (reachability marks
    anything it cannot resolve as 'undetermined', never 'not_reachable')."""
    import json as _json

    from agenticops.security.collectors import collect_network_acls

    instances: dict = {}
    subnets: dict = {}
    sgs: dict = {}
    nacls: dict = {}
    for region in _enabled_regions(account):
        try:
            ec2 = _agg_get_client("ec2", region, account)
            vpc_ids = [v["VpcId"] for v in ec2.describe_vpcs().get("Vpcs", [])]
            nacls.update(collect_network_acls(account, region))
        except Exception as e:
            logger.warning("topology region %s failed for %s: %s", region, account, e)
            continue
        for vpc_id in vpc_ids:
            try:
                from agenticops.graph.collectors import collect_vpc_compute
                from agenticops.tools.network_tools import analyze_vpc_topology
                topo = _json.loads(analyze_vpc_topology(region, vpc_id, account))
                for sn in topo.get("subnets", []) or []:
                    if sn.get("subnet_id"):
                        subnets[sn["subnet_id"]] = sn
                sgs.update(topo.get("security_group_dependency_map", {}) or {})
                comp = collect_vpc_compute(region, vpc_id, account)
                for inst in comp.get("ec2_instances", []) or []:
                    if inst.get("instance_id"):
                        instances[inst["instance_id"]] = inst
            except Exception as e:
                logger.warning("topology vpc %s/%s failed for %s: %s",
                               region, vpc_id, account, e)
    return instances, subnets, sgs, nacls


def run_posture_snapshot() -> int:
    """Collect posture + score + persist one SecuritySnapshot per enabled account.
    Returns the number of snapshots written. Per-account failures are isolated."""
    written = 0
    for account in _resolve_security_accounts():
        try:
            findings = collect_posture(account)
            result = score(findings)
            with get_db_session() as session:
                session.add(SecuritySnapshot(
                    account_id=account, provider="aws",
                    overall_score=result.overall_score,
                    category_scores=result.category_scores,
                    metrics=result.metrics,
                    exposure_paths=[],  # filled by reachability in Stage 2+
                    cis_results=result.cis_results,
                ))
                _prune_old_snapshots(session)
            written += 1
        except Exception as e:
            logger.warning("posture snapshot failed for account %s: %s", account, e)
    return written
