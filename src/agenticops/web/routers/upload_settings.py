"""Chat upload settings (2026-11-07): the limits in force, changed by admins at runtime, every change audited.

    GET    /api/settings/chat-upload   effective + defaults + overridden fields + supported types + ranges + can_edit
    PATCH  /api/settings/chat-upload   partial {field: value}; 422 {code: invalid_upload_config, field} on a bad one
    DELETE /api/settings/chat-upload   back to the settings.yaml defaults

Stored in the DB (`runtime_settings`, key `chat_upload`), so a change survives a restart and applies at once
(bootstrap `upload_policy` and every upload read the effective values). With auth on, PATCH / DELETE need an admin
(an API key's scopes cap it); a viewer reads only with `settings_read` and never writes (the auth middleware
refuses its writes).
"""
import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agenticops.auth.actor import Actor
from agenticops.auth.viewer import can_view_settings, read_only_detail
from agenticops.chat import upload_config
from agenticops.chat.attachments.types import SUPPORTED
from agenticops.config import ChatUploadSettings, get_trace_id, settings
from agenticops.services import runtime_settings
from agenticops.web.deps import current_actor, require_authenticated_user

router = APIRouter(tags=["settings"])
URL = "/api/settings/chat-upload"


def _ranges() -> dict[str, list]:
    out = {}
    for name, field in ChatUploadSettings.model_fields.items():
        lo = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        hi = next((m.le for m in field.metadata if hasattr(m, "le")), None)
        if lo is not None or hi is not None:
            out[name] = [lo, hi]
    return out


def _supported() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {"image": [], "pdf": [], "office": [], "text": []}
    for ext, ft in sorted(SUPPORTED.items()):
        groups[ft.kind].append(ext)
    return groups


def _can_edit(request: Request) -> bool:
    if not settings.api_auth_enabled:
        return True
    user = getattr(request.state, "user", None)
    api_key = getattr(request.state, "api_key", None)
    return bool(getattr(user, "is_admin", False)) and (
        api_key is None or "admin" in (getattr(api_key, "permissions", None) or ()))


def _body(request: Request) -> dict:
    row = runtime_settings.get_row(upload_config.KEY)
    return {
        "effective": upload_config.effective().model_dump(),
        "defaults": upload_config.defaults().model_dump(),
        "overridden": sorted(upload_config.overrides()),
        "supported": _supported(),
        "ranges": _ranges(),
        "updated_by": row["updated_by"] if row else None,
        "updated_at": row["updated_at"].isoformat() if row and row["updated_at"] else None,
        "can_edit": _can_edit(request),
    }


def _invalid(e: upload_config.UploadConfigError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(e), "code": "invalid_upload_config",
                                                  "field": e.field, "trace_id": get_trace_id() or None})


@router.get(URL)
def get_chat_upload_settings(request: Request):
    user = getattr(request.state, "user", None)
    if settings.api_auth_enabled and user is not None and not can_view_settings(user):
        return JSONResponse(status_code=403, content=read_only_detail())
    return _body(request)


def _audit(action: str, actor: Actor, old: dict, new: dict) -> None:
    from agenticops.audit.service import AuditService
    AuditService.log(action, "runtime_setting", upload_config.KEY, entity_name="chat upload settings",
                     actor=actor.key, user_id=actor.user_id, old_values=old, new_values=new)


@router.patch(URL)
async def patch_chat_upload_settings(request: Request, actor: Actor = Depends(current_actor)):
    if settings.api_auth_enabled:
        await require_authenticated_user(request, admin=True)
    try:
        patch = await request.json()
    except ValueError:
        patch = None
    if not isinstance(patch, dict):
        return _invalid(upload_config.UploadConfigError("", "Send a JSON object of settings"))

    def _apply():
        before = upload_config.effective().model_dump()
        try:
            checked = upload_config.validate_patch(patch)
        except upload_config.UploadConfigError as e:
            return e
        upload_config.save_patch(checked, actor.key)
        _audit("update", actor, {k: before[k] for k in checked}, checked)
        return None
    error = await asyncio.to_thread(_apply)
    if error is not None:
        return _invalid(error)
    return await asyncio.to_thread(_body, request)


@router.delete(URL)
async def reset_chat_upload_settings(request: Request, actor: Actor = Depends(current_actor)):
    if settings.api_auth_enabled:
        await require_authenticated_user(request, admin=True)

    def _apply():
        before = upload_config.overrides()
        upload_config.reset(actor.key)
        _audit("reset", actor, before, {})
    await asyncio.to_thread(_apply)
    return await asyncio.to_thread(_body, request)
