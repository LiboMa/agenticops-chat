"""Graph Sync Service — background sync of AWS infrastructure into GraphStore.

Non-blocking: runs in a daemon thread with configurable interval.
Controlled by settings.graph_sync_enabled (AIOPS_GRAPH_SYNC_ENABLED).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from agenticops.config import settings

logger = logging.getLogger(__name__)

_sync_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_graph_sync() -> None:
    """Start the background graph sync loop (daemon thread)."""
    global _sync_thread
    if not settings.graph_sync_enabled:
        logger.info("Graph sync disabled — not starting")
        return
    if _sync_thread is not None and _sync_thread.is_alive():
        logger.info("Graph sync already running")
        return

    _stop_event.clear()
    _sync_thread = threading.Thread(
        target=_sync_loop,
        daemon=True,
        name="graph-sync",
    )
    _sync_thread.start()
    logger.info("Graph sync started (interval=%dm)", settings.graph_sync_interval_minutes)


def stop_graph_sync() -> None:
    """Signal the background sync loop to stop."""
    _stop_event.set()
    logger.info("Graph sync stop requested")


def _sync_loop() -> None:
    """Background loop: sync_all() every interval, clean stale nodes."""
    while not _stop_event.is_set():
        try:
            sync_all()
        except Exception:
            logger.exception("Graph sync cycle failed")

        # Clean stale nodes
        try:
            from agenticops.graph.store import GraphStore
            removed = GraphStore().remove_stale_nodes(ttl_hours=settings.graph_node_ttl_hours)
            if removed:
                logger.info("Graph sync cleaned %d stale nodes", removed)
        except Exception:
            logger.exception("Stale node cleanup failed")

        _stop_event.wait(timeout=settings.graph_sync_interval_minutes * 60)


def sync_all() -> dict[str, Any]:
    """Full sync: discover VPCs across configured regions and sync each."""
    from agenticops.graph.api import _ensure_aws_session

    stats: dict[str, Any] = {"regions": {}}

    # Attribute graph nodes to the registered default account (no ambient STS).
    try:
        from agenticops.credentials.resolver import resolve_default_account
        snap = resolve_default_account("aws")
        account_id = str(snap.credentials.get("account_id") or snap.name)
    except Exception as e:
        account_id = ""
        logger.warning("Could not determine registered AWS account for graph sync: %s", e)

    # Discover regions with VPCs — start with bedrock_region
    regions = [settings.bedrock_region]
    for region in regions:
        try:
            _ensure_aws_session(region)
            region_stats = sync_region(region, account_id=account_id)
            stats["regions"][region] = region_stats
        except Exception:
            logger.exception("Failed to sync region %s", region)
            stats["regions"][region] = {"error": True}

    return stats


def sync_region(region: str, account_id: str = "") -> dict[str, Any]:
    """Sync all VPCs in a region."""
    from agenticops.graph.api import _ensure_aws_session

    _ensure_aws_session(region)
    stats: dict[str, Any] = {"vpcs": {}}

    try:
        from agenticops.graph.collectors import _get_client
        ec2 = _get_client("ec2", region)
        vpcs_resp = ec2.describe_vpcs()
        vpc_ids = [v["VpcId"] for v in vpcs_resp.get("Vpcs", [])]

        for vpc_id in vpc_ids:
            try:
                vpc_stats = sync_vpc(region, vpc_id, account_id=account_id)
                stats["vpcs"][vpc_id] = vpc_stats
            except Exception:
                logger.exception("Failed to sync VPC %s in %s", vpc_id, region)
                stats["vpcs"][vpc_id] = {"error": True}
    except Exception:
        logger.exception("Failed to list VPCs in %s", region)

    return stats


def sync_vpc(region: str, vpc_id: str, account_id: str = "") -> dict[str, int]:
    """Sync a single VPC: topology + compute -> GraphStore."""
    from agenticops.graph.api import _build_enriched_vpc_graph
    from agenticops.graph.store import GraphStore

    graph = _build_enriched_vpc_graph(region, vpc_id)
    store = GraphStore()
    return store.save_graph(graph, scope=vpc_id, region=region, account_id=account_id)
