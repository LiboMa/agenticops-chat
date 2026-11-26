"""The setup overview (MVP-2.9.0 N23): how far this installation is set up, and the model verification.

    GET  /api/setup/readiness      any signed-in person (a read-only account too); reads only, runs no check
    POST /api/setup/verify-model   admins: one tiny call to Main's model, recorded and audited

Plain functions: the verification is a blocking model call, the overview reads the database.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from agenticops.auth.actor import Actor
from agenticops.web.deps import current_actor
from agenticops.web.routers.upload_settings import can_edit

router = APIRouter(tags=["setup"])


@router.get("/api/setup/readiness")
def api_setup_readiness(request: Request, actor: Actor = Depends(current_actor)):
    from agenticops.services import readiness
    return readiness.readiness(actor, can_verify=can_edit(request))


@router.post("/api/setup/verify-model")
def api_setup_verify_model(request: Request, actor: Actor = Depends(current_actor)):
    if not can_edit(request):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    from agenticops.services import readiness
    return readiness.verify_model(actor)
