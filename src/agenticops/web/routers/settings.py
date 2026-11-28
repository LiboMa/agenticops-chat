"""GET / PATCH /api/settings — the runtime settings, their checks, their audit rows (split from web/app.py)."""
import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.models import get_db_session
from agenticops.web.deps import current_actor, require_authenticated_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/settings/scan-focus-options")
async def api_scan_focus_options():
    """Return valid scan focus options and default."""
    from agenticops.config import VALID_SCAN_FOCUS, SCAN_FOCUS_SERVICES
    return {
        "options": list(VALID_SCAN_FOCUS),
        "default": settings.scan_focus,
        "services": SCAN_FOCUS_SERVICES,
    }


def _model_version_label(model_id: str) -> str:
    """Extract a short version label from a Bedrock model ID (e.g., '4.6', '4.5')."""
    import re
    m = re.search(r"(\d+[\.\-]\d+)", model_id.split("claude-")[-1] if "claude-" in model_id else model_id)
    return m.group(1).replace("-", ".") if m else ""


def _acp_available_backends() -> list[str]:
    """Registered enhanced-backend provider names (empty if acp module unavailable)."""
    try:
        import agenticops.acp  # noqa: F401 — triggers register_backend at import
        from agenticops.acp.registry import available_backends
        return available_backends()
    except Exception:
        return []


def _acp_blocked() -> Optional[str]:
    from agenticops.agents.enhanced import blocked_reason
    return blocked_reason()


@router.get("/api/settings")
def api_get_settings():  # plain def: model presets may list Bedrock models synchronously (one process — S1c)
    """Return all toggleable runtime settings."""
    from agenticops.config import AGENT_NAMES, MODEL_ALIASES, get_agent_model_config, FULL_CONTEXT, get_agent_window_size

    agent_models = {}
    for name in AGENT_NAMES:
        model_id, max_tokens = get_agent_model_config(name)
        ws = get_agent_window_size(name)
        agent_models[name] = {
            "model_id": model_id,
            "max_tokens": max_tokens,
            "window_size": ws,
            "window_mode": "full" if ws == FULL_CONTEXT else "sliding",
        }

    # Model presets — dynamic from Bedrock API + custom_models (cached), and the providers' chat models (N35)
    from agenticops.llm import model_settings as model_settings_mod
    from agenticops.llm import registry as provider_registry
    try:
        from agenticops.services.model_service import get_model_presets
        model_presets = get_model_presets()
    except Exception:
        # Fallback to static aliases (Bedrock ids: none while Bedrock is off)
        model_presets = [
            {"label": alias.capitalize() + " " + _model_version_label(model_id), "value": model_id}
            for alias, model_id in MODEL_ALIASES.items()
        ] if provider_registry.bedrock_enabled() else []

    # IM WS auto-detect status from channels.yaml
    try:
        from agenticops.notify.im_config import load_channels
        _channels = load_channels()
        feishu_ws_active = any(c.channel_type == "feishu" and c.is_enabled for c in _channels)
        slack_ws_active = any(c.channel_type == "slack" and c.is_enabled for c in _channels)
    except Exception:
        feishu_ws_active = False
        slack_ws_active = False

    from agenticops.services import exec_switches
    switches = exec_switches.effective()        # the four high-impact switches: the values in force (N25)
    return {
        "scan_focus": settings.scan_focus,
        "executor_enabled": switches.executor_enabled,
        "auto_fix_enabled": switches.auto_fix_enabled,
        "auto_rca_enabled": settings.auto_rca_enabled,
        "notifications_enabled": settings.notifications_enabled,
        "executor_auto_approve_l0_l1": switches.executor_auto_approve_l0_l1,
        "executor_hitl_enabled": switches.executor_hitl_enabled,
        # which of the four are an administrator's stored values, the yaml defaults, and who last changed them
        "execution_switches": exec_switches.stored_info(),
        "notifications_consolidated": settings.notifications_consolidated,
        "bedrock_cache_enabled": settings.bedrock_cache_enabled,
        "skills_auto_improve_enabled": settings.skills_auto_improve_enabled,
        "skills_post_resolution_review": settings.skills_post_resolution_review,
        "skills_improvement_notify": settings.skills_improvement_notify,
        "agent_models": agent_models,
        "model_presets": model_presets,
        # MVP-2.9.0 N35: the model settings beside the agents' own ({value, effective, default}) and every setting in
        # force whose model cannot be used ({setting, value, reason, inherited})
        "model_settings": model_settings_mod.view(),
        "model_issues": model_settings_mod.issues(),
        # Galaxy build model override — "" means use bedrock_model_id_cheap
        "galaxy_model_id": settings.galaxy_model_id,
        # IM WebSocket status (read-only, derived from channels.yaml)
        "feishu_ws_active": feishu_ws_active,
        "slack_ws_active": slack_ws_active,
        # Report S3 storage config
        "report_storage": settings.report_storage,
        "report_s3_bucket": settings.report_s3_bucket,
        "report_s3_prefix": settings.report_s3_prefix,
        "report_s3_region": settings.report_s3_region,
        "report_presigned_url_expiry": settings.report_presigned_url_expiry,
        # ACP enhanced backend (optional task delegation)
        "acp_enhanced_enabled": settings.acp_enhanced_enabled,
        "acp_enhanced_backend": settings.acp_enhanced_backend,
        "acp_available_backends": _acp_available_backends(),
        # "bedrock_off": switched on, but its backend runs on Bedrock and Bedrock is turned off — not offered
        "acp_enhanced_blocked": _acp_blocked(),
        # Change management (MVP-2.6.0) — the two security toggles persist to settings.yaml
        "change_management_enabled": settings.change_management_enabled,
        "change_auto_approve_standard": settings.change_auto_approve_standard,
        "rbac_enforce": settings.rbac_enforce,
        # Read-only: whether the graph's potential impact feeds the change policy or is shadow-recorded (MVP-2.6.1)
        "policy_graph_impact_enforce": settings.policy_graph_impact_enforce,
        # Read-only: the post-RCA gate's threshold, so IssueDetail can say why auto-fix paused (2026-10-04 spec §8)
        "rca_min_confidence_for_autofix": settings.rca_min_confidence_for_autofix,
        # Read-only: how long a fix plan's auto-run counts as in flight, so IssueDetail and POST /execute agree
        "executor_total_timeout": settings.executor_total_timeout,
    }


# What PATCH /api/settings changes without the audited transactions of the high-impact switches and the security
# toggles: the low-impact keys. Their change is audited by comparing the value before and after (N25).
_LOW_IMPACT_SETTINGS = (
    "auto_rca_enabled", "notifications_enabled", "notifications_consolidated", "bedrock_cache_enabled",
    "skills_auto_improve_enabled", "skills_post_resolution_review", "skills_improvement_notify",
    "scan_focus", "galaxy_model_id", "acp_enhanced_enabled", "acp_enhanced_backend",
    "report_storage", "report_s3_bucket", "report_s3_prefix", "report_s3_region", "report_presigned_url_expiry",
)
_AGENT_MODEL_FIELDS = ("model_id", "max_tokens", "window_size")


def _low_impact_values(body: dict) -> dict:
    """The current value of every low-impact setting the request names (an agent's model settings by attribute, a
    model setting by its settings field — N35)."""
    from agenticops.llm.model_settings import SETTINGS as MODEL_SETTINGS
    out = {key: getattr(settings, key, None) for key in _LOW_IMPACT_SETTINGS if key in body}
    named = body.get("model_settings")
    for name in (named if isinstance(named, dict) else ()):
        if name in MODEL_SETTINGS:
            out[MODEL_SETTINGS[name]] = getattr(settings, MODEL_SETTINGS[name], None)
    models = body.get("agent_models")
    for name, cfg in (models.items() if isinstance(models, dict) else ()):
        for field in (_AGENT_MODEL_FIELDS if isinstance(cfg, dict) else ()):
            if field in cfg:
                out[f"agent_{name}_{field}"] = getattr(settings, f"agent_{name}_{field}", None)
    return out


def _audit_low_impact(before: dict, after: dict, actor: Actor) -> None:
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    changed = sorted(key for key in before if before[key] != after.get(key))
    if not changed:
        return
    with get_db_session() as s:
        for key in changed:
            AuditService.log(Actions.UPDATE, EntityTypes.SYSTEM, key, entity_name="settings", actor=actor.key,
                             user_id=actor.user_id, old_values={key: before[key]}, new_values={key: after.get(key)},
                             session=s)


def _model_refusal(setting: str, reason: str, detail: str) -> JSONResponse:
    code = "bedrock_off" if reason == "bedrock_off" else "unknown_model"
    return JSONResponse(status_code=400, content={"detail": f"{setting}: {detail}", "code": code, "setting": setting,
                                                  "reason": reason})


def _checked_model_updates(body: dict):
    """The settings fields `model_settings` changes ({field: value}), after checking every model value the request
    names — those and each agent's `model_id` (MVP-2.9.0 N35: an agent's model was not checked before). A value that
    cannot be used is a 400 JSONResponse (`unknown_model` / `bedrock_off`, the setting, the reason); an empty value
    is allowed where it means a fallback (an agent → its tier, a direct caller → the cheap tier)."""
    from agenticops.config import AGENT_NAMES
    from agenticops.llm import model_settings
    named = body.get("model_settings", {})
    if not isinstance(named, dict):
        raise HTTPException(400, "model_settings must be a dict")
    unknown = set(named) - set(model_settings.SETTINGS)
    if unknown:
        raise HTTPException(400, f"Unknown model settings: {', '.join(sorted(unknown))}")
    updates: dict[str, str] = {}
    for name in model_settings.SETTINGS:                     # a fixed order: the first refusal is always the same
        if name not in named:
            continue
        field = model_settings.SETTINGS[name]
        val = named[name]
        if not isinstance(val, str):
            raise HTTPException(400, f"model_settings.{name} must be a string")
        val = val.strip()
        if not val:
            if field in model_settings.NEVER_EMPTY:
                return _model_refusal(name, "empty", "a tier must name a model")
        else:
            found = model_settings.problem(val)
            if found:
                return _model_refusal(name, *found)
        updates[field] = val
    am = body.get("agent_models")
    for name, cfg in (am.items() if isinstance(am, dict) else ()):
        if name in AGENT_NAMES and isinstance(cfg, dict) and cfg.get("model_id"):
            found = model_settings.problem(str(cfg["model_id"]).strip())
            if found:
                return _model_refusal(f"agent_models.{name}", *found)
    # The Galaxy model by its older top-level key (the General tab's Galaxy card): the same setting, the same checks
    # and the same write as model_settings.galaxy — and it wins when a request carries both, as it always did
    if "galaxy_model_id" in body:
        galaxy = str(body.get("galaxy_model_id") or "").strip()
        if galaxy:
            found = model_settings.problem(galaxy)
            if found:
                return _model_refusal("galaxy_model_id", *found)
        updates["galaxy_model_id"] = galaxy
    return updates


@router.patch("/api/settings")
async def api_update_settings(request: Request, body: dict = Body(...), current: Actor = Depends(current_actor)):
    """Update runtime settings (`_apply_settings`) — and leave one audit row per changed value (MVP-2.9.0 N25: «每次
    设置变更都留审计记录»). The high-impact switches and the security toggles write theirs inside their own
    transactions; every other key is audited here, from its value before and after — also when a later key of the
    same request was refused (those keys are applied one by one)."""
    before = _low_impact_values(body)
    try:
        return await _apply_settings(request, body, current)
    finally:
        await asyncio.to_thread(_audit_low_impact, before, _low_impact_values(body), current)


def _apply_validated_settings(body: dict, current: Actor, model_updates: dict, change_updates: dict,
                              exec_updates: dict, keys: dict) -> None:
    """The half of PATCH /api/settings that reads and writes storage — settings.yaml, the audit rows, the stored
    switches. A plain function: `_apply_settings` runs it in a worker thread, so the ONE process's event loop (every
    chat stream) never waits on a file or the database (review of MVP-2.9.0, Standards 3). The order, the
    transactions and the errors (an HTTPException raised here reaches the client) are what they were inline."""
    from agenticops.web.app import _chat_sessions, _executor_service  # here: app imports this router
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.config import AGENT_NAMES, VALID_SCAN_FOCUS, set_scan_focus, save_to_yaml
    from agenticops.services import exec_switches
    BOOL_KEYS, REPORT_STR_KEYS, REPORT_INT_KEYS = keys["bool"], keys["report_str"], keys["report_int"]

    for key in BOOL_KEYS:
        if key in body:
            if not isinstance(body[key], bool):
                raise HTTPException(400, f"{key} must be a boolean")
            setattr(settings, key, body[key])

    if "scan_focus" in body:
        val = body["scan_focus"]
        parts = [p.strip() for p in val.split(",")]
        for p in parts:
            if p not in VALID_SCAN_FOCUS:
                raise HTTPException(400, f"Invalid scan_focus value: {p}")
        settings.scan_focus = val
        set_scan_focus(val)

    if "agent_models" in body:
        am = body["agent_models"]
        if not isinstance(am, dict):
            raise HTTPException(400, "agent_models must be a dict")
        yaml_agent_updates: dict[str, Any] = {}
        for name, cfg in am.items():
            if name not in AGENT_NAMES:
                raise HTTPException(400, f"Unknown agent: {name}")
            if not isinstance(cfg, dict):
                raise HTTPException(400, f"agent_models.{name} must be a dict")
            if "model_id" in cfg:
                val = str(cfg["model_id"])
                setattr(settings, f"agent_{name}_model_id", val)
                yaml_agent_updates[f"agent_{name}_model_id"] = val
            if "max_tokens" in cfg:
                val = int(cfg["max_tokens"])
                setattr(settings, f"agent_{name}_max_tokens", val)
                yaml_agent_updates[f"agent_{name}_max_tokens"] = val
            if "window_size" in cfg:
                val = int(cfg["window_size"])
                setattr(settings, f"agent_{name}_window_size", val)
                yaml_agent_updates[f"agent_{name}_window_size"] = val
        if yaml_agent_updates:
            save_to_yaml(yaml_agent_updates)
            _chat_sessions.clear()

    # Report S3 config — update in-memory + persist to settings.yaml
    report_changed = False
    for key in REPORT_STR_KEYS:
        if key in body:
            if key == "report_storage" and body[key] not in ("local", "s3"):
                raise HTTPException(400, "report_storage must be 'local' or 's3'")
            setattr(settings, key, str(body[key]))
            report_changed = True
    for key in REPORT_INT_KEYS:
        if key in body:
            setattr(settings, key, int(body[key]))
            report_changed = True
    if report_changed:
        yaml_updates = {}
        for key in REPORT_STR_KEYS | REPORT_INT_KEYS:
            if key in body:
                yaml_updates[key] = getattr(settings, key)
        save_to_yaml(yaml_updates)

    # ACP enhanced backend — persist to YAML + clear session cache so agents
    # rebuild with the new tool registration / provider on the next message.
    acp_yaml: dict[str, Any] = {}
    if "acp_enhanced_enabled" in body:
        if not isinstance(body["acp_enhanced_enabled"], bool):
            raise HTTPException(400, "acp_enhanced_enabled must be a boolean")
        settings.acp_enhanced_enabled = body["acp_enhanced_enabled"]
        acp_yaml["acp_enhanced_enabled"] = settings.acp_enhanced_enabled
    if "acp_enhanced_backend" in body:
        val = str(body["acp_enhanced_backend"])
        if val not in _acp_available_backends():
            raise HTTPException(400, f"Unknown enhanced backend: {val}")
        settings.acp_enhanced_backend = val
        acp_yaml["acp_enhanced_backend"] = val
    if acp_yaml:
        save_to_yaml(acp_yaml)
        _chat_sessions.clear()

    # The model settings beside the agents' own (N35), the Galaxy model too — checked above; in memory, then the yaml
    if model_updates:
        for field, val in model_updates.items():
            setattr(settings, field, val)
        save_to_yaml(model_updates)
        _chat_sessions.clear()

    # Security toggles — last. One audit row per changed value, then the ONE yaml write, inside one session: a
    # yaml failure rolls the rows back, and a commit that fails after the write puts the old values back in the
    # yaml. Only then does the in-memory value flip, so any failure leaves the old value live and an identical
    # retry still sees the change and redoes all three steps.
    changed = {k: v for k, v in sorted(change_updates.items()) if getattr(settings, k) != v}
    if changed:
        old = {k: getattr(settings, k) for k in changed}
        yaml_written = False
        try:
            with get_db_session() as s:
                for key, new in changed.items():
                    AuditService.log(Actions.UPDATE, EntityTypes.SYSTEM, key, entity_name="settings",
                                     actor=current.key, user_id=current.user_id, old_values={key: old[key]},
                                     new_values={key: new}, session=s)
                save_to_yaml(changed)
                yaml_written = True
        except BaseException:
            if yaml_written:
                try:
                    save_to_yaml(old)  # best effort; the commit's own error is what the request raises
                except Exception:
                    logger.exception("The audit commit failed and settings.yaml could not be restored: it still "
                                     "holds the new value of %s", ", ".join(changed))
            raise
        for key, new in changed.items():
            setattr(settings, key, new)

    # The high-impact switches: one audit row per changed value and the stored object, in ONE transaction — the
    # value is in force only once that commits (services/exec_switches reads the database, not the process).
    in_force = exec_switches.effective()
    switched = {k: v for k, v in sorted(exec_updates.items()) if getattr(in_force, k) != v}
    if switched:
        def _store():
            with get_db_session() as s:
                for key, new in switched.items():
                    AuditService.log(Actions.UPDATE, EntityTypes.SYSTEM, key, entity_name="settings",
                                     actor=current.key, user_id=current.user_id,
                                     old_values={key: getattr(in_force, key)}, new_values={key: new}, session=s)
                exec_switches.save(switched, current.key, session=s)
        _store()                                     # already off the event loop
        if switched.get("executor_enabled"):
            # The queue's poller is started at boot only when the executor is on: switched on at runtime, the
            # tickets queued from then on waited for the next restart (MVP-2.9.0 N8). start() is idempotent.
            _executor_service.start()



async def _apply_settings(request: Request, body: dict, current: Actor):
    """Update runtime settings. Agent models + report config persist to settings.yaml;
    boolean toggles and scan_focus are session-level (reset on restart).

    The four high-impact switches (EXEC_KEYS: the executor, auto-fix, L0 / L1 auto-approval, the executor's HITL
    gate — MVP-2.9.0 N25) are stored in the database (services/exec_switches), so they survive a restart; like the
    security toggles below they need an admin when api_auth_enabled, write one audit row per changed value in the
    transaction that stores them, and a request refused by their checks applies nothing.

    The security toggles (CHANGE_KEYS: change_auto_approve_standard, rbac_enforce) persist to settings.yaml,
    need an admin when api_auth_enabled, write one audit row per changed value, and are applied last — a
    request refused by the security-toggle checks (400/401/403) applies nothing; the other keys keep their own,
    non-atomic validation. A changed toggle's audit rows are written, then the yaml, then the rows commit — all
    BEFORE the value goes live in memory. A failed yaml write rolls the rows back; a commit that fails after the
    write restores the old values in the yaml (best effort: a failed restore is logged). Either way the old value
    stays in force and an identical retry redoes it all."""
    from agenticops.web.app import _allowed_model_ids  # here: app imports this router
    from agenticops.services import exec_switches

    BOOL_KEYS = {
        "auto_rca_enabled", "notifications_enabled",
        "notifications_consolidated", "bedrock_cache_enabled",
        "skills_auto_improve_enabled", "skills_post_resolution_review",
        "skills_improvement_notify",
    }
    # Report S3 config (persisted to settings.yaml)
    REPORT_STR_KEYS = {"report_storage", "report_s3_bucket", "report_s3_prefix", "report_s3_region"}
    REPORT_INT_KEYS = {"report_presigned_url_expiry"}

    # ACP enhanced backend — persisted to settings.yaml (controls tool registration)
    ACP_KEYS = {"acp_enhanced_enabled", "acp_enhanced_backend"}

    # Change-management security toggles — persisted to settings.yaml (must survive a restart)
    CHANGE_KEYS = {"change_auto_approve_standard", "rbac_enforce"}

    # The high-impact switches — stored in the DB (services/exec_switches), never set on the process's settings
    EXEC_KEYS = set(exec_switches.FIELDS)

    # Which model each setting uses (MVP-2.9.0 N35): an administrator's, like the security toggles
    MODEL_KEYS = {"agent_models", "model_settings", "galaxy_model_id"}

    ALL_KEYS = (BOOL_KEYS | REPORT_STR_KEYS | REPORT_INT_KEYS | ACP_KEYS | CHANGE_KEYS | EXEC_KEYS | MODEL_KEYS
                | {"scan_focus"})
    unknown = set(body.keys()) - ALL_KEYS
    if unknown:
        raise HTTPException(400, f"Unknown settings: {', '.join(sorted(unknown))}")

    # Security toggles are validated and authorized BEFORE anything is applied
    change_updates = {k: body[k] for k in CHANGE_KEYS if k in body}
    exec_updates = {k: body[k] for k in EXEC_KEYS if k in body}
    for key in sorted({**change_updates, **exec_updates}):
        if not isinstance(body[key], bool):
            raise HTTPException(400, f"{key} must be a boolean")
    if (change_updates or exec_updates or MODEL_KEYS & set(body)) and settings.api_auth_enabled:
        await require_authenticated_user(request, admin=True)
    # Every model value is checked BEFORE anything is applied: a refused one changes nothing (N35)
    model_updates = await asyncio.to_thread(_checked_model_updates, body)
    if isinstance(model_updates, JSONResponse):
        return model_updates
    # … and the Galaxy model's own, stricter check (one of the listed models) too, whichever key carries it — it used
    # to run after the other model settings had been written, so a request refused here had already changed them
    # (review of 2.9.0, Spec ⑥), and only on the top-level key (②)
    galaxy_val = (model_updates or {}).get("galaxy_model_id")
    if galaxy_val and galaxy_val not in await asyncio.to_thread(_allowed_model_ids):  # may list Bedrock models
        raise HTTPException(400, f"Unknown galaxy_model_id: {galaxy_val}")
    # a switch this process's environment holds at its strict value cannot be changed here (review, N27)
    held = exec_switches.held(exec_updates)
    if held:
        return JSONResponse(status_code=409, content={
            "detail": exec_switches.held_message(held), "code": "held_by_environment", "fields": held})

    await asyncio.to_thread(_apply_validated_settings, body, current, model_updates or {},
                            change_updates, exec_updates,
                            {"bool": BOOL_KEYS, "report_str": REPORT_STR_KEYS, "report_int": REPORT_INT_KEYS})
    return await asyncio.to_thread(api_get_settings)  # it may list Bedrock models
