"""Workspace UI endpoints (MVP-2.7.0 S2, contract `workspace-ui-1`): bootstrap + preferences.

Both identify the signed-in user from the request — APIAuthMiddleware's user, or the Bearer token validated
here when the middleware is off — so they work in either auth mode (the web UI always signs in). Bootstrap
says what this deployment can do; it never carries a secret or connector configuration.
"""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agenticops.auth.actor import Actor
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
    """What the chat send handler accepts, in its own dispatch order: an image, then a native document,
    then the text fallback (chat/file_reader)."""
    from agenticops.chat import file_reader as fr
    documents = set(fr.DOCUMENT_FORMAT_MAP)
    return {
        "max_files": fr.MAX_UPLOAD_FILES,
        "image_max_bytes": fr.MAX_IMAGE_SIZE,
        "document_max_bytes": fr.MAX_DOCUMENT_SIZE,
        "text_fallback_max_bytes": fr.MAX_FILE_SIZE,
        "image_extensions": sorted(fr.IMAGE_FORMAT_MAP),
        "document_extensions": sorted(documents),
        "text_extensions": sorted(fr.TEXT_EXTENSIONS - documents),
    }


def _features() -> dict:
    """Only what is built and switched on. Later stages turn their flags on as they ship."""
    return {
        "context_chat": False,
        "revision_guards": False,     # approvals are guarded by content_hash + 409 today, not If-Match
        "content_rendering": False,
        "report_export": False,
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
        "preferences": preferences,
        # 2.7.0 additions to the contract (it allows extra fields): the avatar menu, auth-dependent controls,
        # the sidebar footer
        "user": {"id": user.id, "email": user.email, "name": user.name, "is_admin": bool(user.is_admin)},
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
                     actor: Actor = Depends(current_actor), _user=Depends(signed_in_user)) -> dict:
    """Work that waits on this actor (contract workspace-ui-1 AttentionPage, plus `ref` / `reason_detail` and the
    reasons review_required / execution_not_started). Plain def: it is DB work (S1 rule)."""
    from agenticops.services.attention import attention_page
    return attention_page(actor, account_id=account_id, limit=limit, offset=int(cursor or 0))
