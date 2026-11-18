"""Workspace UI endpoints (MVP-2.7.0 S2, contract `workspace-ui-1`): bootstrap + preferences.

Both identify the signed-in user from the request — APIAuthMiddleware's user, or the Bearer token validated
here when the middleware is off — so they work in either auth mode (the web UI always signs in). Bootstrap
says what this deployment can do; it never carries a secret or connector configuration.
"""

from datetime import datetime
from typing import List, Literal, Optional

from fastapi import HTTPException, APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
                     item: Optional[str] = Query(None, pattern=r"^[IC][1-9]\d{0,8}$"),
                     sort: str = Query("waiting_longest", pattern="^(waiting_longest|newest|severity|decision)$"),
                     snoozed: Optional[str] = Query(None, pattern="^last$"),
                     actor: Actor = Depends(current_actor), user=Depends(signed_in_user)) -> dict:
    """Work that waits on this actor (contract workspace-ui-1 AttentionPage, plus `ref` / `reason_detail` and the
    reasons review_required / execution_not_started). MVP-2.8.0 S2: `reason` (comma list) / `q` / `sort`, and each
    item's severity / risk level / resource / region / waiting_on, `counts` per reason. MVP-2.9.0: `item` (I12 / C3)
    = that one work item, when it is on this actor's list. N14: every item carries `snoozed_until` (this person's
    «later», while it applies); `snoozed=last` puts those at the end of their group — only NewUI asks for it, so
    the classic lists keep their order. Plain def: DB work (S1)."""
    from agenticops.services.attention import attention_page
    reasons = [r for r in (reason or "").split(",") if r] or None
    try:
        return attention_page(actor, account_id=account_id, reason=reasons, q=q, item=item, sort=sort, limit=limit,
                              offset=int(cursor or 0), snooze_user_id=getattr(user, "id", None),
                              snoozed_last=snoozed == "last")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class SnoozeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item: str = Field(..., pattern=r"^[IC][1-9]\d{0,8}$")


@router.post("/api/ui/attention/snooze")
def api_ui_attention_snooze(data: SnoozeBody, actor: Actor = Depends(current_actor), user=Depends(signed_in_user)):
    """«Later» (MVP-2.9.0 N14): put one of MY waiting items at the end of its group for `attention_snooze_minutes`.
    It changes nothing about the item, and nothing for anyone else. 409 `not_waiting` when the item is not on this
    person's list. Plain def: DB work."""
    from agenticops.services import attention_snooze
    got = attention_snooze.snooze(user.id, actor, data.item)
    if got is None:
        return _ui_error(409, "not_waiting", f"{data.item} is not waiting on you; there is nothing to put off.")
    return got


@router.delete("/api/ui/attention/snooze", status_code=204)
def api_ui_attention_unsnooze(item: str = Query(..., pattern=r"^[IC][1-9]\d{0,8}$"), user=Depends(signed_in_user)):
    """Take my «later» back: the item returns to its place. 204 whether or not there was one."""
    from agenticops.services import attention_snooze
    attention_snooze.unsnooze(user.id, item)
    return Response(status_code=204)


@router.get("/api/ui/events")
def api_ui_events(hours: int = Query(24, ge=1, le=24), account_id: Optional[int] = Query(None, ge=1),
                  _user=Depends(signed_in_user)) -> dict:
    """What happened in the last `hours` (MVP-2.9.0 N15; services/ui_events): an issue found, an agent's start and
    end, a person's decision, a change's course — each with its time and its work item. The top bar's band and the
    map's replay read it. Plain def: DB work."""
    from agenticops.services.ui_events import recent_events
    return recent_events(hours=hours, account_id=account_id)


@router.get("/api/ui/activity")
def api_ui_activity(account_id: Optional[int] = Query(None, ge=1), actor: Actor = Depends(current_actor),
                    _user=Depends(signed_in_user)) -> dict:
    """What agents are doing now, what is scheduled next and what ended in the last day (MVP-2.9.0, NewUI «现场»;
    services/activity): `running` / `upcoming` / `recent`, each from state that can be checked — an `open` issue is
    not an agent at work. Any signed-in user. Plain def: DB work."""
    from agenticops.services.activity import activity
    return activity(actor, account_id=account_id)


@router.get("/api/ui/activity/steps")
def api_ui_activity_steps(item: str = Query(..., pattern=r"^[IC][1-9]\d*$"), agent: str = Query(..., pattern="^(rca|sre|executor)$"),
                          execution: Optional[int] = Query(None, ge=1), since: Optional[datetime] = Query(None),
                          before: Optional[datetime] = Query(None), after: int = Query(0, ge=0),
                          limit: int = Query(200, ge=1, le=200), actor: Actor = Depends(current_actor),
                          _user=Depends(signed_in_user)) -> dict:
    """One agent run's steps as the code recorded them while it worked (MVP-2.9.0 N10; agents/step_recorder,
    services/agent_steps): each tool call with its start, its end and how it ended, and what the model said in
    between. Which run: `execution` (a run record), else the newest run of `agent` on `item` that began at or after
    `since` (a lane in flight) or before `before` (the run that left a result); `after` = the last step id the page
    has. Any signed-in user reads which steps there were; a read-only account is not shown a command line or the
    start of a result (`withheld`) — the display redaction does not know every shape of a secret. Plain def: DB work."""
    from agenticops.services.agent_steps import run_steps
    return run_steps(item, agent, execution_id=execution, since=since, before=before, after=after, limit=limit,
                     withhold=actor.read_only)


class ActivityNote(BaseModel):
    lane: str = Field(..., pattern=r"^([IC][1-9]\d*:[a-z_]+|[A-Z]+\d+)$", max_length=64)
    text: str = Field(..., min_length=1, max_length=200)
    # the run the note was written for (the key the step list carries); without it, the run in flight on the lane
    run: Optional[str] = Field(None, pattern=r"^[0-9a-f]{32}$")

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        from agenticops.services.issue_notes import reads_as_written
        if not v.strip():
            raise ValueError("the note is empty")
        if not reads_as_written(v):
            raise ValueError("the note may not contain control characters")
        return v


# a lane of «现场» that takes a word from a person → the agent whose run it is; an execution, a schedule, a graph
# build are not steered
_STEERABLE_LANES = {"diagnosis": "rca", "plan": "sre", "change_review": "sre"}


@router.post("/api/ui/activity/note", status_code=201)
def api_ui_activity_note(data: ActivityNote, actor: Actor = Depends(current_actor), _user=Depends(signed_in_user)):
    """Say a word to an agent while it works (MVP-2.9.0 N12): the note is recorded as a step of the run (kind `you`,
    the session actor — never the body) and handed to the agent before its next model call, as information from
    the person watching, not as a new task. Only a diagnosis, a plan or a change review in flight in THIS process;
    an execution follows the plan that was approved and can only be stopped. 403 a read-only account ·
    409 `not_steerable` (not that kind of lane) · 409 `not_running` (nothing in flight there, it just ended, or
    the run the note names is not the one in flight any more) · 503 `not_stored` (the note could not be recorded:
    the run goes on, send it again). Plain def: DB work."""
    from agenticops.agents.step_recorder import NoteNotStored, live_recorder
    from agenticops.auth import authz

    if actor.read_only:
        raise HTTPException(status_code=403, detail={"detail": "A read-only account cannot say a word to an agent.", "code": "read_only"})
    item, _, kind = data.lane.partition(":")
    agent = _STEERABLE_LANES.get(kind)
    if agent is None:
        return _ui_error(409, "not_steerable", "This lane takes no notes: only a diagnosis, a plan or a change review in flight does.")
    try:
        authz.check(actor, "issue.note", subject=None)
    except authz.AuthzDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    recorder = live_recorder(item, agent)
    if recorder is not None and data.run is not None and recorder.run_key != data.run:
        return _ui_error(409, "not_running", "The run this note was written for has ended; another run is on it now. "
                                              "The note was not delivered.")
    try:
        row = recorder.note(data.text, by=actor.key) if recorder is not None else None
    except NoteNotStored:
        return _ui_error(503, "not_stored", "The note could not be recorded, so it was not delivered. The run goes on: send it again.")
    if row is None:
        return _ui_error(409, "not_running", "No such run is in flight: it has ended, or it never started here. The note was not delivered.")
    return row


@router.get("/api/ui/nav-counts")
def api_ui_nav_counts(account_id: Optional[int] = Query(None, ge=1), actor: Actor = Depends(current_actor),
                      _user=Depends(signed_in_user)) -> dict:
    """The sidebar's numbers in one request (MVP-2.8.0 direction A; services/nav_counts): the to-do total from the
    same source as /api/ui/attention (and its critical issues), open high / critical security findings, failed
    schedules, skill drafts. A viewer gets none; a count that fails is null, never 0. Plain def: DB work."""
    from agenticops.services.nav_counts import nav_counts
    return nav_counts(actor, account_id=account_id)
