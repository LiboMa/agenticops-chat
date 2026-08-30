"""Slow-frequency security posture snapshot job (SecurityPostureSnapshot).

Stage 0: stub entry point + cron helper. Stage 1 fills in collect->score->persist.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def cron_from_interval(minutes: int) -> str:
    """Interval minutes -> cron. Mirrors the galaxy-auto-build seed helper:
    <60 -> every N minutes; >=60 -> minute 0 of every (N//60) hours."""
    m = max(1, int(minutes))
    if m < 60:
        return f"*/{m} * * * *"
    return f"0 */{max(1, m // 60)} * * *"


def run_posture_snapshot() -> int:
    """Return the number of snapshots written. Stage 0 stub returns 0."""
    return 0
