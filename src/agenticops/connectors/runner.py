"""Runs a pull connector: targets → collect → ingest, one connector_runs row per target (MVP-2.6.1 spec §3.B.6).

Callers: the k8s-discovery schedule (trigger="schedule"), CLI `aiops connectors run` and
POST /api/connectors/{name}/run (trigger="manual"), and the RCA recollect (trigger="rca": one account + scope and a
time budget). When a schedule / manual run changes structure, the graph is refreshed once with a rule-only build;
an rca run leaves that to its caller, which refreshes under its own trigger.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from agenticops.config import settings
from agenticops.connectors.base import CollectResult, Target
from agenticops.connectors.ingest import ingest
from agenticops.connectors.k8s import K8sConnector
from agenticops.models import CloudAccount, ConnectorRun, get_db_session

logger = logging.getLogger(__name__)

CONNECTORS = {"k8s": K8sConnector}
_ENABLED_FLAG = {"k8s": "k8s_connector_enabled"}
# Two runs of one connector in this process would race on inserting the same new rows; the second waits.
_LOCKS = {name: threading.Lock() for name in CONNECTORS}
TRIGGERS = ("schedule", "manual", "rca")
_GRAPH_TRIGGERS = ("schedule", "manual")
SCHEDULE_NAME = "k8s-discovery"
PIPELINE_NAME = "K8sDiscovery"


class UnknownConnector(ValueError):
    pass


@dataclass
class TargetRun:
    account: str    # account name
    scope: str
    run_id: int     # connector_runs.id
    status: str     # complete | partial | failed
    changed: bool
    counts: dict
    error: str      # "; "-joined collect errors, "" when none


@dataclass
class ConnectorRunResult:
    connector: str
    status: str     # disabled | busy | no_targets | complete | partial | failed
    targets: list[TargetRun] = field(default_factory=list)
    changed: bool = False
    graph_build_id: Optional[int] = None


def is_enabled(name: str) -> bool:
    return bool(getattr(settings, _ENABLED_FLAG[name]))


def is_running(name: str) -> bool:
    """A run of `name` is in progress in THIS process (the lock is per process)."""
    return _LOCKS[name].locked()


def disabled_message(name: str) -> str:
    return f"connector {name} is disabled — set {_ENABLED_FLAG[name]}: true in config/settings.yaml"


def check_known(name: str) -> None:
    if name not in CONNECTORS:
        raise UnknownConnector(f"unknown connector {name!r}; known: {', '.join(sorted(CONNECTORS))}")


def run_connector(name: str, *, account: str = "", scope: str = "", trigger: str = "manual",
                  timeout_seconds: Optional[float] = None) -> ConnectorRunResult:
    """Collect and ingest every target of connector `name`, or only those of `account` (name or cloud account
    id) and / or `scope`. `timeout_seconds` bounds the whole call, including waiting for a run already in
    progress (then status "busy"); None means no budget."""
    check_known(name)
    if trigger not in TRIGGERS:
        raise ValueError(f"connector trigger must be one of {TRIGGERS}, got {trigger!r}")
    if not is_enabled(name):
        return ConnectorRunResult(connector=name, status="disabled")
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    lock = _LOCKS[name]
    if not lock.acquire(timeout=-1 if deadline is None else max(0.0, deadline - time.monotonic())):
        return ConnectorRunResult(connector=name, status="busy")
    try:
        return _run(name, account, scope, trigger, deadline)
    finally:
        lock.release()


def _run(name: str, account: str, scope: str, trigger: str, deadline: Optional[float]) -> ConnectorRunResult:
    connector = CONNECTORS[name]()
    with get_db_session() as s:
        targets = [t for t in connector.targets(s) if _selected(t, account, scope)]
    if not targets:
        return ConnectorRunResult(connector=name, status="no_targets")

    runs = []
    for target in targets:
        started = datetime.now(timezone.utc)
        budget = None if deadline is None else max(0.0, deadline - time.monotonic())
        try:
            result = connector.collect(target, timeout_seconds=budget)
        except Exception as exc:  # one broken target must not stop the others or lose its run record
            logger.exception("connector %s: collect(%s) raised", name, target.scope)
            result = CollectResult(errors=[f"{target.scope} not collected — collector raised "
                                           f"{type(exc).__name__}: {exc}"])
        res = ingest(connector, target, result, trigger=trigger, started_at=started)
        runs.append(TargetRun(account=target.account.name, scope=target.scope, run_id=res.run_id,
                              status=res.status, changed=res.changed, counts=res.counts,
                              error="; ".join(result.errors)))

    statuses = {r.status for r in runs}
    status = statuses.pop() if len(statuses) == 1 else "partial"
    changed = any(r.changed for r in runs)
    build_id = None
    if changed and trigger in _GRAPH_TRIGGERS and settings.galaxy_enabled:
        try:
            from agenticops.galaxy.builder import build_graph

            build_id = build_graph(trigger="k8s-discovery", full=False, llm=False)
        except Exception as exc:  # the runs are recorded; the next change retries the refresh
            logger.warning("connector %s: graph refresh failed: %s", name, exc)
    return ConnectorRunResult(connector=name, status=status, targets=runs, changed=changed, graph_build_id=build_id)


def _selected(target: Target, account: str, scope: str) -> bool:
    if account and account not in (target.account.name, str(target.account.credentials.get("account_id") or "")):
        return False
    return not scope or target.scope == scope


def connector_status(name: str, *, limit: int = 10) -> dict:
    """What CLI `aiops connectors list` and GET /api/connectors show: the switch, whether a run is in progress,
    the discovery schedule row (None until seeded) and the newest `limit` runs, newest first."""
    check_known(name)
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as s:
        names = dict(s.query(CloudAccount.id, CloudAccount.name).all())
        rows = (s.query(ConnectorRun).filter_by(connector=name)
                .order_by(ConnectorRun.id.desc()).limit(limit).all())
        runs = [{"id": r.id, "account": names.get(r.account_id), "scope": r.scope, "trigger": r.trigger,
                 "status": r.status, "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
                 "counts": r.counts or {}, "error": r.error} for r in rows]
        sched = s.query(Schedule).filter_by(name=SCHEDULE_NAME).first()
        schedule = sched and {"name": sched.name, "cron_expression": sched.cron_expression,
                              "is_enabled": bool(sched.is_enabled)}
    return {"name": name, "enabled": is_enabled(name), "running": is_running(name), "schedule": schedule,
            "recent_runs": runs}


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def seed_discovery_schedule() -> bool:
    """Create the k8s-discovery schedule once (startup, scheduler worker). An existing row — even one a user
    edited or disabled — is left alone. True when it was created."""
    if not settings.k8s_connector_enabled:
        return False
    from agenticops.scheduler.scheduler import Schedule, Scheduler
    from agenticops.security.posture_snapshot import cron_from_interval

    with get_db_session() as s:
        if s.query(Schedule.id).filter_by(name=SCHEDULE_NAME).first():
            return False
    cron = cron_from_interval(settings.k8s_discovery_interval_minutes)
    Scheduler.add_schedule(name=SCHEDULE_NAME, pipeline_name=PIPELINE_NAME, cron_expression=cron, config={})
    logger.info("k8s: seeded %s schedule (cron=%s)", SCHEDULE_NAME, cron)
    return True
