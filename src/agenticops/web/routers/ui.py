"""Workspace UI endpoints (MVP-2.7.0 S2, contract `workspace-ui-1`): bootstrap + preferences.

Both identify the signed-in user from the request — APIAuthMiddleware's user, or the Bearer token validated
here when the middleware is off — so they work in either auth mode (the web UI always signs in). Bootstrap
says what this deployment can do; it never carries a secret or connector configuration.
"""

from typing import List, Literal, Optional

from fastapi import HTTPException, APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agenticops.auth.actor import Actor
from agenticops.auth.viewer import can_view_settings, is_viewer
from agenticops.config import get_trace_id, settings
from agenticops.services import ui_preferences as prefs
from agenticops.web.deps import current_actor, require_authenticated_user

router = APIRouter(tags=["workspace-ui"])


async def signed_in_user(request: Request):
    """A dependency, so identity is checked before the body is: an unauthenticated PATCH is a 401, never a
    422 that describes the body."""
    return await require_authenticated_user(request, admin=False)

CONTRACT_VERSION = "workspace-ui-1"


def _ui_error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code, "trace_id": get_trace_id() or None})


def _upload_policy() -> dict:
    """What the chat composer may attach: the upload limits in force (chat/upload_config — yaml defaults + the
    admins' overrides), read on every bootstrap so a change applies without a restart."""
    from agenticops.chat import upload_config
    return upload_config.upload_policy()


def _report_export_formats() -> list[str]:
    """S6: the export formats this server can produce — html always, pdf / docx when their libraries are installed."""
    from agenticops.services.report_export import available_formats
    return available_formats()


def _features() -> dict:
    """Only what is built and switched on. Later stages turn their flags on as they ship."""
    return {
        "context_chat": True,         # S5: chats carry a server-checked context (services/chat_context)
        "revision_guards": False,     # approvals are guarded by content_hash + 409 today, not If-Match
        "content_rendering": True,    # S6: zh / en report renderings (services/content_rendering)
        "report_export": True,        # S6: GET /api/reports/{id}/export (formats in report_export_formats)
        "attention": True,
        "change_management": bool(settings.change_management_enabled),
        "chat_replay": False,
    }


@router.get("/api/ui/bootstrap")
async def api_ui_bootstrap(user=Depends(signed_in_user)) -> dict:
    """Everything the shell needs before its first screen: who you are, what is enabled, the upload limits
    and your preferences (so the shell never needs a second request to decide where to land)."""
    from agenticops import __version__
    from agenticops.models import deployment_id
    preferences = prefs.read(user.id)
    return {
        "contract_version": CONTRACT_VERSION,
        "deployment_id": deployment_id(),
        "user_id": user.id,
        "locale": preferences["locale"],
        "features": _features(),
        "upload_policy": _upload_policy(),
        "report_export_formats": _report_export_formats(),
        "preferences": preferences,
        # 2.7.0 additions to the contract (it allows extra fields): the avatar menu, auth-dependent controls,
        # the sidebar footer
        "user": {"id": user.id, "email": user.email, "name": user.name, "is_admin": bool(user.is_admin),
                 "read_only": is_viewer(user),  # a viewer account: the UI offers no write controls
                 "can_view_settings": can_view_settings(user)},  # Settings in the nav (read-only for a viewer)
        "auth_enabled": bool(settings.api_auth_enabled),
        "version": __version__,
    }


@router.get("/api/users/me/preferences")
async def api_get_preferences(response: Response, user=Depends(signed_in_user)) -> dict:
    doc = prefs.read(user.id)
    response.headers["ETag"] = prefs.etag(doc["revision"])
    return doc


class PreferencesUpdate(BaseModel):
    """Any of the four fields, at least one; nothing else (no tokens, message text or action URLs)."""
    model_config = ConfigDict(extra="forbid")

    locale: Optional[Literal["zh", "en"]] = None
    home: Optional[Literal["resume", "chat", "issues", "reports"]] = None
    last_route: Optional[str] = None
    nav_groups_open: Optional[List[Literal["tools", "administration"]]] = None

    @field_validator("last_route")
    @classmethod
    def _route(cls, value):
        if value is not None and not prefs.allowed_route(value):
            raise ValueError("last_route must be an allow-listed /app route (no query string, no fragment)")
        return value

    @field_validator("nav_groups_open")
    @classmethod
    def _unique(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("nav_groups_open must not repeat a group")
        return value

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_fields_set:
            raise ValueError("send at least one preference")
        for name in ("locale", "home", "nav_groups_open"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


@router.patch("/api/users/me/preferences")
async def api_update_preferences(response: Response, data: PreferencesUpdate, user=Depends(signed_in_user),
                                 if_match: Optional[str] = Header(default=None)):
    """Write some preferences. If-Match must carry the ETag (revision) you read — or `*` to merge these
    fields whatever else changed (the last route uses that); 428 without it, 412 when it is stale."""
    expected = prefs.parse_if_match(if_match)
    if expected is None:
        return _ui_error(428, "if_match_required", "Send If-Match with the preferences ETag you read (or *)")
    try:
        doc = prefs.write(user.id, data.model_dump(include=data.model_fields_set), expected)
    except prefs.PreferencesConflict:
        return _ui_error(412, "revision_mismatch", "Preferences changed; fetch the latest and reconcile")
    response.headers["ETag"] = prefs.etag(doc["revision"])
    return doc


@router.get("/api/ui/attention")
def api_ui_attention(account_id: Optional[int] = Query(None, ge=1), limit: int = Query(25, ge=1, le=100),
                     cursor: Optional[str] = Query(None, pattern=r"^\d{1,6}$"),
                     reason: Optional[str] = Query(None, max_length=200),
                     q: Optional[str] = Query(None, max_length=200),
                     sort: str = Query("waiting_longest", pattern="^(waiting_longest|newest|severity)$"),
                     actor: Actor = Depends(current_actor), _user=Depends(signed_in_user)) -> dict:
    """Work that waits on this actor (contract workspace-ui-1 AttentionPage, plus `ref` / `reason_detail` and the
    reasons review_required / execution_not_started). MVP-2.8.0 S2: `reason` (comma list) / `q` / `sort`, and each
    item's severity / risk level / resource / region / waiting_on, `counts` per reason. Plain def: DB work (S1)."""
    from agenticops.services.attention import attention_page
    reasons = [r for r in (reason or "").split(",") if r] or None
    try:
        return attention_page(actor, account_id=account_id, reason=reasons, q=q, sort=sort, limit=limit,
                              offset=int(cursor or 0))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
