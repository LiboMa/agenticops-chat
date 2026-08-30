"""Fast-frequency security incremental poll job (SecurityIncrementalPoll).

Stage 0: stub. Stage 4 implements cursor-based GuardDuty/SecurityHub/Config polling.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_incremental_poll() -> int:
    """Return the number of new findings emitted. Stage 0 stub returns 0."""
    return 0
