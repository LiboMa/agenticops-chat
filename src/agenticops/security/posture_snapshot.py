"""Slow-frequency security posture snapshot job (SecurityPostureSnapshot).

Stage 0: stub entry point + cron helper. Stage 1 fills in collect->score->persist.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from agenticops.config import settings
from agenticops.models import SecuritySnapshot, get_db_session
from agenticops.security.collectors import collect_posture
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
