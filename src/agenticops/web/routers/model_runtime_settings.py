"""Model connection settings (2026-11-08): the stream read timeout in force, changed by admins at runtime, audited.

    GET    /api/settings/model-runtime   effective + defaults + overridden fields + ranges + can_edit
    PATCH  /api/settings/model-runtime   partial {field: value}; 422 {code: invalid_model_runtime, field} on a bad one
    DELETE /api/settings/model-runtime   back to the settings.yaml defaults

Stored in the DB (`runtime_settings`, key `model_runtime`), so a change survives a restart. Agents read it when they
are built: a change clears the cached chat agents, so the next turn of every chat uses it. With auth on, PATCH /
DELETE need an admin (an API key's scopes cap it); a viewer reads only with `settings_read` and never writes.
"""
import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agenticops.agents import model_runtime
from agenticops.auth.actor import Actor
from agenticops.auth.viewer import can_view_settings, read_only_detail
from agenticops.config import ModelRuntimeSettings, get_trace_id, settings
from agenticops.services import runtime_settings
from agenticops.web.deps import current_actor, require_authenticated_user
from agenticops.web.routers.upload_settings import _can_edit

router = APIRouter(tags=["settings"])
URL = "/api/settings/model-runtime"


def _ranges() -> dict[str, list]:
    out = {}
    for name, field in ModelRuntimeSettings.model_fields.items():
        lo = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        hi = next((m.le for m in field.metadata if hasattr(m, "le")), None)
        if lo is not None or hi is not None:
            out[name] = [lo, hi]
    return out


def _body(request: Request) -> dict:
    row = runtime_settings.get_row(model_runtime.KEY)
    return {
        "effective": model_runtime.effective().model_dump(),
        "defaults": model_runtime.defaults().model_dump(),
        "overridden": sorted(model_runtime.overrides()),
        "ranges": _ranges(),
        "updated_by": row["updated_by"] if row else None,
        "updated_at": row["updated_at"].isoformat() if row and row["updated_at"] else None,
        "can_edit": _can_edit(request),
    }


def _invalid(e: model_runtime.ModelRuntimeError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(e), "code": "invalid_model_runtime",
                                                  "field": e.field, "trace_id": get_trace_id() or None})


def _audit(action: str, actor: Actor, old: dict, new: dict) -> None:
    from agenticops.audit.service import AuditService
    AuditService.log(action, "runtime_setting", model_runtime.KEY, entity_name="model connection settings",
                     actor=actor.key, user_id=actor.user_id, old_values=old, new_values=new)


def _rebuild_chat_agents() -> None:
    from agenticops.web.app import _chat_sessions   # import here: app imports this router
    _chat_sessions.clear()


@router.get(URL)
def get_model_runtime_settings(request: Request):
    user = getattr(request.state, "user", None)
    if settings.api_auth_enabled and user is not None and not can_view_settings(user):
        return JSONResponse(status_code=403, content=read_only_detail())
    return _body(request)


@router.patch(URL)
async def patch_model_runtime_settings(request: Request, actor: Actor = Depends(current_actor)):
    if settings.api_auth_enabled:
        await require_authenticated_user(request, admin=True)
    try:
        patch = await request.json()
    except ValueError:
        patch = None
    if not isinstance(patch, dict):
        return _invalid(model_runtime.ModelRuntimeError("", "Send a JSON object of settings"))

    def _apply():
        before = model_runtime.effective().model_dump()
        try:
            checked = model_runtime.validate_patch(patch)
        except model_runtime.ModelRuntimeError as e:
            return e
        model_runtime.save_patch(checked, actor.key)
        _audit("update", actor, {k: before[k] for k in checked}, checked)
        _rebuild_chat_agents()
        return None
    error = await asyncio.to_thread(_apply)
    if error is not None:
        return _invalid(error)
    return await asyncio.to_thread(_body, request)


@router.delete(URL)
async def reset_model_runtime_settings(request: Request, actor: Actor = Depends(current_actor)):
    if settings.api_auth_enabled:
        await require_authenticated_user(request, admin=True)

    def _apply():
        before = model_runtime.overrides()
        model_runtime.reset(actor.key)
        _audit("reset", actor, before, {})
        _rebuild_chat_agents()
    await asyncio.to_thread(_apply)
    return await asyncio.to_thread(_body, request)
