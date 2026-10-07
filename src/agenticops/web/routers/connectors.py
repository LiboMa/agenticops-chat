"""Pull-connector API (MVP-2.6.1 spec §3.B.6): the Settings connector card lists recent runs and runs one now.

A run only reads the target (kubectl get) and writes the inventory, like POST /api/schedules/{id}/run and
POST /api/galaxy/rebuild — it sits behind APIAuthMiddleware and carries no RBAC permission of its own.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from agenticops.connectors import runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("")
async def api_list_connectors(limit: int = Query(10, ge=1, le=100)):
    return {"connectors": [runner.connector_status(name, limit=limit) for name in sorted(runner.CONNECTORS)]}


@router.post("/{name}/run", status_code=202)
async def api_run_connector(name: str, background_tasks: BackgroundTasks):
    """Run every target of `name` now in the background (trigger=manual); the runs land in GET /api/connectors."""
    try:
        runner.check_known(name)
    except runner.UnknownConnector as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not runner.is_enabled(name):
        raise HTTPException(status_code=409, detail=runner.disabled_message(name))
    if runner.is_running(name):
        raise HTTPException(status_code=409, detail=f"connector {name} is already running")

    def _run_in_background():
        try:
            runner.run_connector(name, trigger="manual")
        except Exception as e:
            logger.error("connector %s: manual run failed: %s", name, e)

    background_tasks.add_task(_run_in_background)
    return {"connector": name, "status": "accepted"}
