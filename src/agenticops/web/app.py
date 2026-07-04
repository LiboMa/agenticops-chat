"""Web Dashboard - React SPA + API backend."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, Request, Query, HTTPException, Body, BackgroundTasks, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sqlalchemy import case, func, text
from sqlalchemy.orm import joinedload

from agenticops.models import (
    AgentMemory,
    AgentMemoryFact,
    AlertEvent,
    CloudAccount,
    CloudResource,
    Anomaly,
    FixExecution,
    HealthIssue,
    FixPlan,
    RCAResult,
    Report,
    MonitoringConfig,
    ChatSession,
    ChatMessage,
    SOPRecord,
    InvalidSOPTransition,
    validate_sop_transition,
    get_session,
    get_db_session,
    init_db,
)
from agenticops.config import settings

import asyncio
import json
import logging
import time
import urllib.request
import uuid
from sse_starlette.sse import EventSourceResponse

from agenticops.graph.api import router as graph_router
from agenticops.services.executor_service import ExecutorService
from agenticops.web.session_manager import ChatSessionManager

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models for API — extracted to schemas.py (imported below)
# ============================================================================
from agenticops.web.schemas import *  # noqa: F401,F403  (API request/response models)
from agenticops.web import schemas as _schemas  # explicit module handle
from agenticops.web.helpers import (  # cross-router helpers (extracted)
    _infra_ref_key, _guess_type, _build_account_name_map,
    _health_issue_to_anomaly_response, _auto_learn_dismissed, _enrich_report,
)



# ============================================================================
# Application Lifespan (startup + shutdown in async context manager)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown in a single async context manager."""
    # --- Startup ---
    _setup_service_logging()
    init_db()

    # Surface model-ID config drift early (unmatched IDs lose window tuning
    # and may be rejected by Bedrock at invocation time)
    try:
        from agenticops.config import validate_agent_model_ids
        validate_agent_model_ids()
    except Exception:
        pass

    # Seed default admin user if auth is enabled and no users exist
    if settings.api_auth_enabled:
        try:
            from agenticops.auth import AuthService
            from agenticops.auth.models import User
            with get_db_session() as session:
                if session.query(User).count() == 0:
                    admin_password = getattr(settings, "admin_password", None) or os.environ.get("AIOPS_ADMIN_PASSWORD", "aiops2026")
                    AuthService.create_user(
                        email="admin",
                        password=admin_password,
                        name="Administrator",
                        is_admin=True,
                    )
                    logger.info("Auth: seeded default admin user (admin / ***)")
        except Exception as e:
            logger.warning("Auth seed failed: %s", e)

    _chat_sessions.start_cleanup()
    _executor_service.start()

    # ITSM bridge (MVP-2.0.0): mirror issue/fix lifecycle into ServiceNow/Jira
    try:
        from agenticops.itsm import start_itsm_bridge
        if start_itsm_bridge():
            logger.info("ITSM bridge started (dry_run=%s)", settings.itsm_dry_run)
    except Exception as e:
        logger.warning("ITSM bridge failed to start: %s", e)

    # MCP servers: lazy-start on first Agent creation (not here).
    # Pre-starting causes "session is currently running" conflict with Strands.
    try:
        from agenticops.mcp_manager import get_mcp_clients
        mcp_count = len(get_mcp_clients())
        if mcp_count:
            logger.info("MCP: %d server(s) configured (lazy-start on first chat)", mcp_count)
    except Exception as e:
        logger.warning("MCP config load failed: %s", e)

    # Start background cron scheduler — only in ONE worker to avoid duplicate runs.
    # uvicorn multiprocessing: first spawned worker gets the lowest PID after master.
    import os
    _is_scheduler_worker = os.environ.get("AIOPS_SCHEDULER_WORKER") == "1"
    if not _is_scheduler_worker:
        # Auto-elect: only first worker to acquire the file lock runs scheduler
        import fcntl
        _lock_path = Path(settings.data_dir) / ".scheduler.lock"
        _lock_path.parent.mkdir(parents=True, exist_ok=True)
        _lock_fd = open(_lock_path, "w")
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _is_scheduler_worker = True
        except (IOError, OSError):
            _lock_fd.close()
            _lock_fd = None

    scheduler_instance = None
    if _is_scheduler_worker:
        from agenticops.scheduler.scheduler import Scheduler
        scheduler_instance = Scheduler()
        scheduler_instance.start()
        logger.info("Cron scheduler started (this worker elected)")
    else:
        logger.info("Cron scheduler skipped (another worker owns it)")

    # Auto-detect IM WS from channels.yaml (fallback to config override)
    _startup_log = logging.getLogger(__name__)
    try:
        from agenticops.notify.im_config import load_channels
        _channels = load_channels()
        _has_feishu_channel = any(c.channel_type == "feishu" and c.is_enabled for c in _channels)
        _has_slack_channel = any(c.channel_type == "slack" and c.is_enabled for c in _channels)
    except Exception:
        _has_feishu_channel = False
        _has_slack_channel = False

    if _has_feishu_channel or settings.feishu_ws_enabled:
        try:
            from agenticops.im.feishu_ws import start_feishu_ws
            svc = start_feishu_ws()
            if svc:
                _startup_log.info(
                    "Feishu WS: started=%s thread_alive=%s app=%s (auto-detected=%s)",
                    svc._started,
                    svc._thread.is_alive() if svc._thread else False,
                    svc._app_name,
                    _has_feishu_channel,
                )
                print(f"  Feishu WS: started (app={svc._app_name})")
            else:
                _startup_log.error("Feishu WS: start_feishu_ws() returned None — check im-apps.yaml")
                print("  Feishu WS: FAILED — check im-apps.yaml credentials")
        except Exception as e:
            _startup_log.error("Feishu WS failed to start: %s", e, exc_info=True)
            print(f"  Feishu WS: FAILED — {e}")
    else:
        _startup_log.info("Feishu WS: disabled (no enabled feishu channel in channels.yaml)")

    if _has_slack_channel or settings.slack_ws_enabled:
        try:
            from agenticops.im.slack_ws import start_slack_ws
            slack_svc = start_slack_ws()
            if slack_svc:
                _startup_log.info(
                    "Slack WS: started=%s thread_alive=%s app=%s (auto-detected=%s)",
                    slack_svc._started,
                    slack_svc._thread.is_alive() if slack_svc._thread else False,
                    slack_svc._app_name,
                    _has_slack_channel,
                )
                print(f"  Slack WS: started (app={slack_svc._app_name})")
            else:
                _startup_log.warning("Slack WS: start_slack_ws() returned None — check im-apps.yaml")
                print("  Slack WS: FAILED — check im-apps.yaml credentials")
        except Exception as e:
            _startup_log.warning("Slack WS failed to start: %s", e, exc_info=True)
            print(f"  Slack WS: FAILED — {e}")
    else:
        _startup_log.info("Slack WS: disabled (no enabled slack channel in channels.yaml)")

    yield  # --- App is running ---

    # --- Shutdown (guaranteed by async context manager) ---
    _chat_sessions.stop_cleanup()
    _executor_service.stop()

    if scheduler_instance:
        scheduler_instance.stop()
        logger.info("Cron scheduler stopped")
    if _lock_fd:
        _lock_fd.close()

    # Stop MCP clients
    try:
        from agenticops.mcp_manager import stop_mcp_clients
        stop_mcp_clients()
    except Exception:
        pass

    # Stop Feishu WebSocket service
    try:
        from agenticops.im.feishu_ws import stop_feishu_ws
        stop_feishu_ws()
    except Exception:
        pass

    # Stop Slack Socket Mode service
    try:
        from agenticops.im.slack_ws import stop_slack_ws
        stop_slack_ws()
    except Exception:
        pass


# Initialize FastAPI app
app = FastAPI(
    title="AgenticAIOps Dashboard",
    description="Agent-First Cloud Observability Platform",
    version="0.9.0-beta",
    lifespan=lifespan,
)

# Graph API router
app.include_router(graph_router)
from agenticops.web.routers import audit as _audit_router
app.include_router(_audit_router.router)
from agenticops.web.routers import agent_logs as _agent_logs_router
app.include_router(_agent_logs_router.router)
from agenticops.web.routers import auth as _auth_router
app.include_router(_auth_router.router)
from agenticops.web.routers import search as _search_router
app.include_router(_search_router.router)
from agenticops.web.routers import memory as _memory_router
app.include_router(_memory_router.router)
from agenticops.web.routers import accounts as _accounts_router
app.include_router(_accounts_router.router)
from agenticops.web.routers import cost as _cost_router
app.include_router(_cost_router.router)

# Chat session manager
_chat_sessions = ChatSessionManager()
_executor_service = ExecutorService(poll_interval=settings.executor_poll_interval)

# Sessions with an SSE response currently streaming — used to reject
# mid-stream model switches (409). Entries removed in the generator's finally.
_streaming_sessions: set[str] = set()

from agenticops.services.model_service import get_model_presets  # noqa: E402


def _allowed_model_ids() -> set[str]:
    """Valid per-session model ids: cached presets ∪ alias targets (no live call beyond preset cache)."""
    from agenticops.config import MODEL_ALIASES
    return {p["value"] for p in get_model_presets()} | set(MODEL_ALIASES.values())


def _effective_main_model(session_id: str) -> str:
    """Session model override if set, else global main model (for cost attribution)."""
    from agenticops.config import get_agent_model_config
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if row and row.model_id:
            return row.model_id
    return get_agent_model_config("main")[0]



# ============================================================================
# Routes
# ============================================================================


class TraceIdFilter(logging.Filter):
    """Inject pipeline trace_id into log records."""

    def filter(self, record):
        from agenticops.config import get_trace_id
        record.trace_id = get_trace_id() or "-"
        return True


_trace_filter = TraceIdFilter()


def _setup_service_logging() -> None:
    """Configure file-based logging for backend + frontend (access) logs."""
    import logging.handlers

    from agenticops.config import PROJECT_ROOT
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s [%(trace_id)s] %(message)s")

    # backend.log — application errors, startup, agent activity
    backend_handler = logging.handlers.RotatingFileHandler(
        log_dir / "backend.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    backend_handler.setLevel(logging.DEBUG)
    backend_handler.setFormatter(fmt)
    backend_handler.addFilter(_trace_filter)
    for name in ("agenticops", "uvicorn.error", "uvicorn"):
        _logger = logging.getLogger(name)
        _logger.addHandler(backend_handler)
        if _logger.level == logging.NOTSET:
            _logger.setLevel(logging.DEBUG)

    # frontend.log — HTTP access logs (asset + API requests)
    access_handler = logging.handlers.RotatingFileHandler(
        log_dir / "frontend.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(fmt)
    access_handler.addFilter(_trace_filter)
    logging.getLogger("uvicorn.access").addHandler(access_handler)


_scheduler_instance = None


@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    global _scheduler_instance
    _setup_service_logging()
    init_db()

    # Seed default admin user if auth is enabled and no users exist
    if settings.api_auth_enabled:
        try:
            from agenticops.auth import AuthService
            from agenticops.auth.models import User
            with get_db_session() as session:
                if session.query(User).count() == 0:
                    admin_password = getattr(settings, "admin_password", None) or os.environ.get("AIOPS_ADMIN_PASSWORD", "aiops2026")
                    AuthService.create_user(
                        email="admin",
                        password=admin_password,
                        name="Administrator",
                        is_admin=True,
                    )
                    logger.info("Auth: seeded default admin user (admin / ***)")
        except Exception as e:
            logger.warning("Auth seed failed: %s", e)

    _chat_sessions.start_cleanup()
    _executor_service.start()

    # MCP servers: lazy-start (same as lifespan path)
    try:
        from agenticops.mcp_manager import get_mcp_clients
        mcp_count = len(get_mcp_clients())
        if mcp_count:
            logger.info("MCP: %d server(s) configured (lazy-start on first chat)", mcp_count)
    except Exception as e:
        logger.warning("MCP config load failed: %s", e)

    # Start background cron scheduler
    from agenticops.scheduler.scheduler import Scheduler
    _scheduler_instance = Scheduler()
    _scheduler_instance.start()
    logger.info("Cron scheduler started")

    # Auto-detect IM WS from channels.yaml (fallback to config override)
    _startup_log = logging.getLogger(__name__)
    try:
        from agenticops.notify.im_config import load_channels
        _channels = load_channels()
        _has_feishu_channel = any(c.channel_type == "feishu" and c.is_enabled for c in _channels)
        _has_slack_channel = any(c.channel_type == "slack" and c.is_enabled for c in _channels)
    except Exception:
        _has_feishu_channel = False
        _has_slack_channel = False

    if _has_feishu_channel or settings.feishu_ws_enabled:
        try:
            from agenticops.im.feishu_ws import start_feishu_ws
            svc = start_feishu_ws()
            if svc:
                _startup_log.info(
                    "Feishu WS: started=%s thread_alive=%s app=%s (auto-detected=%s)",
                    svc._started,
                    svc._thread.is_alive() if svc._thread else False,
                    svc._app_name,
                    _has_feishu_channel,
                )
                print(f"  Feishu WS: started (app={svc._app_name})")
            else:
                _startup_log.error("Feishu WS: start_feishu_ws() returned None — check im-apps.yaml")
                print("  Feishu WS: FAILED — check im-apps.yaml credentials")
        except Exception as e:
            _startup_log.error("Feishu WS failed to start: %s", e, exc_info=True)
            print(f"  Feishu WS: FAILED — {e}")
    else:
        _startup_log.info("Feishu WS: disabled (no enabled feishu channel in channels.yaml)")

    if _has_slack_channel or settings.slack_ws_enabled:
        try:
            from agenticops.im.slack_ws import start_slack_ws
            slack_svc = start_slack_ws()
            if slack_svc:
                _startup_log.info(
                    "Slack WS: started=%s thread_alive=%s app=%s (auto-detected=%s)",
                    slack_svc._started,
                    slack_svc._thread.is_alive() if slack_svc._thread else False,
                    slack_svc._app_name,
                    _has_slack_channel,
                )
                print(f"  Slack WS: started (app={slack_svc._app_name})")
            else:
                _startup_log.warning("Slack WS: start_slack_ws() returned None — check im-apps.yaml")
                print("  Slack WS: FAILED — check im-apps.yaml credentials")
        except Exception as e:
            _startup_log.warning("Slack WS failed to start: %s", e, exc_info=True)
            print(f"  Slack WS: FAILED — {e}")
    else:
        _startup_log.info("Slack WS: disabled (no enabled slack channel in channels.yaml)")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    _chat_sessions.stop_cleanup()
    _executor_service.stop()
    if _scheduler_instance:
        _scheduler_instance.stop()
        logger.info("Cron scheduler stopped")

    # Stop MCP clients
    try:
        from agenticops.mcp_manager import stop_mcp_clients
        stop_mcp_clients()
    except Exception:
        pass

    # Stop Feishu WebSocket service
    try:
        from agenticops.im.feishu_ws import stop_feishu_ws
        stop_feishu_ws()
    except Exception:
        pass

    # Stop Slack Socket Mode service
    try:
        from agenticops.im.slack_ws import stop_slack_ws
        stop_slack_ws()
    except Exception:
        pass


# ============================================================================
# Legacy Route Redirects (old Jinja2 portal → React SPA)
# ============================================================================


@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/app", status_code=302)


@app.get("/resources")
async def resources_redirect():
    return RedirectResponse(url="/app/resources", status_code=302)


@app.get("/anomalies")
async def anomalies_redirect():
    return RedirectResponse(url="/app/anomalies", status_code=302)


@app.get("/anomaly/{anomaly_id}")
async def anomaly_redirect(anomaly_id: int):
    return RedirectResponse(url=f"/app/anomalies/{anomaly_id}", status_code=302)


@app.get("/reports")
async def reports_redirect():
    return RedirectResponse(url="/app/reports", status_code=302)


# ============================================================================
# Dynamic AWS Region Data
# ============================================================================

_AWS_REGIONAL_TABLE_URL = (
    "https://api.regional-table.region-services.aws.a2z.com/index.json"
)

# Display-name mapping — cosmetic only; the source of truth for which regions
# exist comes from the AWS regional-table API at runtime.
_REGION_DISPLAY_NAMES: dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "af-south-1": "Africa (Cape Town)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-south-2": "Asia Pacific (Hyderabad)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-southeast-4": "Asia Pacific (Melbourne)",
    "ap-southeast-5": "Asia Pacific (Malaysia)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ca-central-1": "Canada (Central)",
    "ca-west-1": "Canada West (Calgary)",
    "eu-central-1": "Europe (Frankfurt)",
    "eu-central-2": "Europe (Zurich)",
    "eu-west-1": "Europe (Ireland)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-south-1": "Europe (Milan)",
    "eu-south-2": "Europe (Spain)",
    "eu-north-1": "Europe (Stockholm)",
    "il-central-1": "Israel (Tel Aviv)",
    "me-south-1": "Middle East (Bahrain)",
    "me-central-1": "Middle East (UAE)",
    "sa-east-1": "South America (São Paulo)",
}

# In-memory cache: (timestamp, data)
_regions_cache: tuple[float, list[dict]] = (0.0, [])
_REGIONS_CACHE_TTL = 86400  # 24 hours


async def _fetch_aws_regions() -> list[dict]:
    """Fetch unique AWS region codes from the public regional-table API."""
    global _regions_cache
    now = time.time()
    cached_at, cached_data = _regions_cache
    if cached_data and (now - cached_at) < _REGIONS_CACHE_TTL:
        return cached_data

    try:
        def _do_fetch():
            req = urllib.request.Request(_AWS_REGIONAL_TABLE_URL)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())

        data = await asyncio.to_thread(_do_fetch)

        codes: set[str] = set()
        for price in data.get("prices", []):
            code = price.get("attributes", {}).get("aws:region")
            if code:
                codes.add(code)

        regions = sorted(
            [
                {"code": c, "name": _REGION_DISPLAY_NAMES.get(c, c)}
                for c in codes
            ],
            key=lambda r: r["code"],
        )
        _regions_cache = (now, regions)
        logger.info("Refreshed AWS region list: %d regions", len(regions))
        return regions
    except Exception:
        logger.exception("Failed to fetch AWS regional-table; using cache")
        if cached_data:
            return cached_data
        # Ultimate fallback: return the display-name keys
        return sorted(
            [{"code": c, "name": n} for c, n in _REGION_DISPLAY_NAMES.items()],
            key=lambda r: r["code"],
        )


@app.get("/api/regions")
async def api_list_regions():
    """Return the list of AWS regions with display names (fetched dynamically)."""
    return await _fetch_aws_regions()


# ============================================================================
# API Endpoints
# ============================================================================


@app.get("/api/settings/scan-focus-options")
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


@app.get("/api/settings")
async def api_get_settings():
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

    # Model presets — dynamic from Bedrock API + custom_models (cached)
    try:
        from agenticops.services.model_service import get_model_presets
        model_presets = get_model_presets()
    except Exception:
        # Fallback to static aliases
        model_presets = [
            {"label": alias.capitalize() + " " + _model_version_label(model_id), "value": model_id}
            for alias, model_id in MODEL_ALIASES.items()
        ]

    # IM WS auto-detect status from channels.yaml
    try:
        from agenticops.notify.im_config import load_channels
        _channels = load_channels()
        feishu_ws_active = any(c.channel_type == "feishu" and c.is_enabled for c in _channels)
        slack_ws_active = any(c.channel_type == "slack" and c.is_enabled for c in _channels)
    except Exception:
        feishu_ws_active = False
        slack_ws_active = False

    return {
        "scan_focus": settings.scan_focus,
        "executor_enabled": settings.executor_enabled,
        "auto_fix_enabled": settings.auto_fix_enabled,
        "auto_rca_enabled": settings.auto_rca_enabled,
        "notifications_enabled": settings.notifications_enabled,
        "executor_auto_approve_l0_l1": settings.executor_auto_approve_l0_l1,
        "notifications_consolidated": settings.notifications_consolidated,
        "bedrock_cache_enabled": settings.bedrock_cache_enabled,
        "skills_auto_improve_enabled": settings.skills_auto_improve_enabled,
        "skills_post_resolution_review": settings.skills_post_resolution_review,
        "skills_improvement_notify": settings.skills_improvement_notify,
        "agent_models": agent_models,
        "model_presets": model_presets,
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
    }


@app.patch("/api/settings")
async def api_update_settings(body: dict = Body(...)):
    """Update runtime settings. Agent models + report config persist to settings.yaml;
    boolean toggles and scan_focus are session-level (reset on restart)."""
    from agenticops.config import AGENT_NAMES, VALID_SCAN_FOCUS, set_scan_focus, save_to_yaml

    BOOL_KEYS = {
        "executor_enabled", "auto_fix_enabled", "auto_rca_enabled",
        "notifications_enabled", "executor_auto_approve_l0_l1",
        "notifications_consolidated", "bedrock_cache_enabled",
        "skills_auto_improve_enabled", "skills_post_resolution_review",
        "skills_improvement_notify",
    }
    # Report S3 config (persisted to settings.yaml)
    REPORT_STR_KEYS = {"report_storage", "report_s3_bucket", "report_s3_prefix", "report_s3_region"}
    REPORT_INT_KEYS = {"report_presigned_url_expiry"}

    # ACP enhanced backend — persisted to settings.yaml (controls tool registration)
    ACP_KEYS = {"acp_enhanced_enabled", "acp_enhanced_backend"}

    ALL_KEYS = BOOL_KEYS | REPORT_STR_KEYS | REPORT_INT_KEYS | ACP_KEYS | {"scan_focus", "agent_models"}
    unknown = set(body.keys()) - ALL_KEYS
    if unknown:
        raise HTTPException(400, f"Unknown settings: {', '.join(sorted(unknown))}")

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

    return await api_get_settings()


# ============================================================================
# Models — Dynamic model listing
# ============================================================================


@app.get("/api/models")
async def api_list_models():
    """Return available Bedrock Claude models (cached, with 1M context variants)."""
    from agenticops.services.model_service import get_model_presets
    return await asyncio.to_thread(get_model_presets)


@app.post("/api/models/refresh")
async def api_refresh_models():
    """Force refresh the model cache from Bedrock API."""
    from agenticops.services.model_service import get_model_presets, invalidate_cache
    invalidate_cache()
    return await asyncio.to_thread(get_model_presets)


# ============================================================================
# IM Apps & Channels
# ============================================================================

_SENSITIVE_IM_KEYS = {"app_secret", "secret", "bot_token", "app_token", "password", "access_key_secret"}


def _mask_im_secrets(config: dict) -> dict:
    """Mask sensitive IM app credential values."""
    return {
        k: f"****{str(v)[-4:]}" if k.lower() in _SENSITIVE_IM_KEYS and v and len(str(v)) >= 4 else v
        for k, v in config.items()
    }


# ============================================================================
# Messaging — unified facade over channels.yaml + im-apps.yaml + NotificationLog
# (replaces the separate Notifications + IM Bots settings tabs)
# ============================================================================

# Schema descriptor: drives the frontend's dynamic Configure form.
# field: {key, label, type: text|password|number|list|select, required, secret}
MESSAGING_SCHEMA: dict = {
    "app_platforms": [
        {"platform": "feishu", "label": "Feishu (飞书)", "fields": [
            {"key": "app_id", "label": "App ID", "type": "text", "required": True, "secret": False},
            {"key": "app_secret", "label": "App Secret", "type": "password", "required": True, "secret": True},
        ]},
        {"platform": "slack", "label": "Slack", "fields": [
            {"key": "bot_token", "label": "Bot Token (xoxb-)", "type": "password", "required": True, "secret": True},
            {"key": "app_token", "label": "App Token (xapp-)", "type": "password", "required": True, "secret": True},
        ]},
        {"platform": "dingtalk", "label": "DingTalk (钉钉)", "fields": [
            {"key": "app_key", "label": "App Key", "type": "text", "required": True, "secret": False},
            {"key": "app_secret", "label": "App Secret", "type": "password", "required": True, "secret": True},
        ]},
        {"platform": "wecom", "label": "WeCom (企业微信)", "fields": [
            {"key": "corp_id", "label": "Corp ID", "type": "text", "required": True, "secret": False},
            {"key": "corp_secret", "label": "Corp Secret", "type": "password", "required": True, "secret": True},
            {"key": "agent_id", "label": "Agent ID", "type": "number", "required": False, "secret": False},
        ]},
    ],
    "channel_types": [
        {"type": "slack", "label": "Slack", "fields": [
            {"key": "webhook_url", "label": "Webhook URL", "type": "text", "required": False, "secret": False},
            {"key": "app_name", "label": "Bot App name (for bot mode)", "type": "text", "required": False, "secret": False},
            {"key": "chat_id", "label": "Channel ID (bot mode)", "type": "text", "required": False, "secret": False},
        ]},
        {"type": "feishu", "label": "Feishu (飞书)", "fields": [
            {"key": "app_name", "label": "Bot App name", "type": "text", "required": True, "secret": False},
            {"key": "chat_id", "label": "Chat ID (oc_...)", "type": "text", "required": True, "secret": False},
        ]},
        {"type": "dingtalk", "label": "DingTalk (钉钉)", "fields": [
            {"key": "app_name", "label": "Bot App name", "type": "text", "required": True, "secret": False},
            {"key": "chat_id", "label": "Conversation ID (cid...)", "type": "text", "required": True, "secret": False},
        ]},
        {"type": "wecom", "label": "WeCom (企业微信)", "fields": [
            {"key": "app_name", "label": "Bot App name", "type": "text", "required": True, "secret": False},
            {"key": "touser", "label": "To user(s)", "type": "text", "required": False, "secret": False},
        ]},
        {"type": "email", "label": "Email (SMTP)", "fields": [
            {"key": "smtp_host", "label": "SMTP Host", "type": "text", "required": True, "secret": False},
            {"key": "smtp_port", "label": "SMTP Port", "type": "number", "required": True, "secret": False},
            {"key": "username", "label": "Username", "type": "text", "required": False, "secret": False},
            {"key": "password", "label": "Password", "type": "password", "required": False, "secret": True},
            {"key": "from_addr", "label": "From", "type": "text", "required": True, "secret": False},
            {"key": "to_addrs", "label": "To (comma-separated)", "type": "list", "required": True, "secret": False},
        ]},
        {"type": "ses", "label": "Email (AWS SES)", "fields": [
            {"key": "sender", "label": "Sender", "type": "text", "required": True, "secret": False},
            {"key": "recipients", "label": "Recipients (comma-separated)", "type": "list", "required": True, "secret": False},
            {"key": "region", "label": "AWS Region", "type": "text", "required": True, "secret": False},
        ]},
        {"type": "sns", "label": "AWS SNS", "fields": [
            {"key": "topic_arn", "label": "Topic ARN", "type": "text", "required": True, "secret": False},
            {"key": "region", "label": "AWS Region", "type": "text", "required": True, "secret": False},
        ]},
        {"type": "sns-report", "label": "SNS Report (SNS + S3)", "fields": [
            {"key": "topic_arn", "label": "Topic ARN", "type": "text", "required": True, "secret": False},
            {"key": "region", "label": "AWS Region", "type": "text", "required": True, "secret": False},
            {"key": "s3_bucket", "label": "S3 Bucket", "type": "text", "required": False, "secret": False},
            {"key": "s3_prefix", "label": "S3 Prefix", "type": "text", "required": False, "secret": False},
        ]},
        {"type": "webhook", "label": "Webhook", "fields": [
            {"key": "url", "label": "URL", "type": "text", "required": True, "secret": False},
        ]},
    ],
}


@app.get("/api/messaging/schema")
async def api_messaging_schema():
    """Field descriptor for the dynamic Configure form (channel types + app platforms)."""
    return MESSAGING_SCHEMA


@app.get("/api/messaging/apps")
async def api_messaging_list_apps():
    """List IM bot apps (credentials) with secrets masked."""
    from agenticops.notify.im_config import get_apps_detail
    apps = get_apps_detail()
    return {
        platform: {name: _mask_im_secrets(cfg) for name, cfg in platform_apps.items()}
        for platform, platform_apps in apps.items()
    }


@app.put("/api/messaging/apps/{platform}/{name}")
async def api_messaging_upsert_app(platform: str, name: str, body: dict = Body(...)):
    """Create/update a bot app credential. Empty secret fields keep the existing value."""
    from agenticops.notify.im_config import save_app, get_apps_detail
    valid = {"feishu", "dingtalk", "wecom", "slack"}
    if platform not in valid:
        raise HTTPException(400, f"Invalid platform. Valid: {', '.join(sorted(valid))}")
    # Merge: a blank secret field means "keep existing" (the GET masked it).
    existing = get_apps_detail().get(platform, {}).get(name, {})
    merged = dict(existing)
    for k, v in body.items():
        if k.lower() in _SENSITIVE_IM_KEYS and (v == "" or v is None or (isinstance(v, str) and v.startswith("****"))):
            continue  # keep existing secret (blank or masked-from-GET)
        merged[k] = v
    save_app(platform, name, merged)
    return {"platform": platform, "name": name, "status": "saved", "restart_hint": True}


@app.delete("/api/messaging/apps/{platform}/{name}")
async def api_messaging_delete_app(platform: str, name: str):
    """Delete a bot app credential."""
    from agenticops.notify.im_config import delete_app
    if not delete_app(platform, name):
        raise HTTPException(404, f"App '{platform}/{name}' not found")
    return {"status": "deleted"}


def _mask_channel_config(config: dict) -> dict:
    """Drop secret-ish keys from a channel config for safe display."""
    return {k: v for k, v in config.items()
            if "token" not in k.lower() and "secret" not in k.lower() and "password" not in k.lower()}


@app.get("/api/messaging/channels")
async def api_messaging_list_channels():
    """List all channels (routing) with full shape + secrets masked."""
    from agenticops.notify.im_config import load_channels
    return [
        {
            "name": c.name,
            "type": c.channel_type,
            "enabled": c.is_enabled,
            "role": c.role,
            "severity_filter": c.severity_filter,
            "preferred_format": c.preferred_format,
            "config": _mask_channel_config(c.config),
        }
        for c in load_channels()
    ]


@app.put("/api/messaging/channels/{name}")
async def api_messaging_upsert_channel(name: str, body: dict = Body(...)):
    """Create/update a channel. Body: {type, enabled, role, severity_filter, config}.
    Blank secret config values keep the existing stored value."""
    from agenticops.notify.im_config import save_channel, get_channel
    channel_type = body.get("type", "")
    if not channel_type:
        raise HTTPException(400, "Field 'type' is required")
    enabled = body.get("enabled", True)
    role = body.get("role", "chat")
    severity_filter = body.get("severity_filter") or None
    config = dict(body.get("config", {}))
    config["role"] = role  # role is stored inside the channel entry (reserved key handled by save_channel)
    # secret-keep merge: blank secret value → keep existing
    existing = get_channel(name)
    if existing:
        for k, v in list(config.items()):
            if ("token" in k.lower() or "secret" in k.lower() or "password" in k.lower()) and (v == "" or v is None):
                if k in existing.config:
                    config[k] = existing.config[k]
                else:
                    config.pop(k, None)
    save_channel(name, channel_type, config, is_enabled=enabled, severity_filter=severity_filter)
    return {"name": name, "type": channel_type, "status": "saved"}


@app.delete("/api/messaging/channels/{name}")
async def api_messaging_delete_channel(name: str):
    """Delete a channel."""
    from agenticops.notify.im_config import delete_channel
    if not delete_channel(name):
        raise HTTPException(404, f"Channel '{name}' not found")
    return {"status": "deleted"}


@app.patch("/api/messaging/channels/{name}/toggle")
async def api_messaging_toggle_channel(name: str, body: dict = Body(...)):
    """Enable/disable a channel."""
    from agenticops.notify.im_config import load_channels, save_channel
    enabled = body.get("enabled", True)
    ch = next((c for c in load_channels() if c.name == name), None)
    if not ch:
        raise HTTPException(404, f"Channel '{name}' not found")
    cfg = dict(ch.config)
    if ch.role:
        cfg["role"] = ch.role
    if ch.preferred_format:
        cfg["preferred_format"] = ch.preferred_format
    if ch.alert_senders:
        cfg["alert_senders"] = ch.alert_senders
    save_channel(name, ch.channel_type, cfg, is_enabled=enabled, severity_filter=ch.severity_filter or None)
    return {"name": name, "enabled": enabled}


@app.post("/api/messaging/channels/{name}/test")
async def api_messaging_test_channel(name: str, data: NotificationSendRequest):
    """Send a test message through a channel (reuses the notifier send path)."""
    from agenticops.notify.im_config import get_channel
    from agenticops.notify.notifier import NotificationManager
    channel = get_channel(name)
    if not channel:
        raise HTTPException(404, "Channel not found")
    notifier_class = NotificationManager.NOTIFIER_CLASSES.get(channel.channel_type)
    if not notifier_class:
        raise HTTPException(400, f"Unknown channel type: {channel.channel_type}")
    try:
        notifier = notifier_class(channel.config)
        success = await notifier.send(subject=data.subject, body=data.body, severity=data.severity)
        return {"status": "sent" if success else "failed", "channel": channel.name}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "failed", "channel": channel.name, "error": str(e)})


@app.get("/api/messaging/logs", response_model=List[NotificationLogResponse])
async def api_messaging_logs(
    channel_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """Delivery logs (reuses NotificationLog)."""
    from agenticops.notify.notifier import NotificationLog
    with get_db_session() as session:
        q = session.query(NotificationLog).order_by(NotificationLog.sent_at.desc())
        if channel_name:
            q = q.filter_by(channel_name=channel_name)
        if status:
            q = q.filter_by(status=status)
        return [NotificationLogResponse.model_validate(log) for log in q.offset(offset).limit(limit).all()]


@app.get("/api/settings/im-apps")
async def api_list_im_apps():
    """List all IM bot apps with masked secrets. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import get_apps_detail
    apps = get_apps_detail()
    # Mask secrets in response
    masked = {}
    for platform, platform_apps in apps.items():
        masked[platform] = {
            name: _mask_im_secrets(cfg) for name, cfg in platform_apps.items()
        }
    return masked


@app.put("/api/settings/im-apps/{platform}/{name}")
async def api_upsert_im_app(platform: str, name: str, body: dict = Body(...)):
    """Create or update an IM bot app credential. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import save_app
    valid = {"feishu", "dingtalk", "wecom", "slack"}
    if platform not in valid:
        raise HTTPException(400, f"Invalid platform. Valid: {', '.join(sorted(valid))}")
    save_app(platform, name, body)
    return {"platform": platform, "name": name, "status": "saved"}


@app.delete("/api/settings/im-apps/{platform}/{name}")
async def api_delete_im_app(platform: str, name: str):
    """Delete an IM bot app. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import delete_app
    if not delete_app(platform, name):
        raise HTTPException(404, f"App '{platform}/{name}' not found")
    return {"status": "deleted"}


@app.get("/api/settings/channels")
async def api_list_channels():
    """List all notification channels. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import load_channels
    channels = load_channels()
    return [
        {
            "name": c.name,
            "type": c.channel_type,
            "enabled": c.is_enabled,
            "role": c.role,
            "preferred_format": c.preferred_format,
            "config": {k: v for k, v in c.config.items()
                       if "token" not in k.lower() and "secret" not in k.lower()},
        }
        for c in channels
    ]


@app.put("/api/settings/channels/{name}")
async def api_upsert_channel(name: str, body: dict = Body(...)):
    """Create or update a notification channel. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import save_channel
    channel_type = body.pop("type", "")
    if not channel_type:
        raise HTTPException(400, "Field 'type' is required")
    enabled = body.pop("enabled", True)
    role = body.pop("role", "chat")
    save_channel(name, channel_type, body, is_enabled=enabled)
    return {"name": name, "type": channel_type, "status": "saved"}


@app.delete("/api/settings/channels/{name}")
async def api_delete_channel(name: str):
    """Delete a notification channel. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import delete_channel
    if not delete_channel(name):
        raise HTTPException(404, f"Channel '{name}' not found")
    return {"status": "deleted"}


@app.patch("/api/settings/channels/{name}/toggle")
async def api_toggle_channel(name: str, body: dict = Body(...)):
    """Enable or disable a channel. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import load_channels, save_channel
    enabled = body.get("enabled", True)
    channels = load_channels()
    ch = next((c for c in channels if c.name == name), None)
    if not ch:
        raise HTTPException(404, f"Channel '{name}' not found")
    save_channel(name, ch.channel_type, ch.config, is_enabled=enabled)
    return {"name": name, "enabled": enabled}


@app.post("/api/settings/im/import")
async def api_import_im_config(body: dict = Body(...)):
    """Bulk import IM apps and/or channels from JSON or YAML string.

    Accepts either:
      - Parsed JSON object: {"apps": {...}, "channels": {...}}
      - Raw string (JSON or YAML): {"raw": "yaml or json text here"}
    """
    import yaml as _yaml
    from agenticops.notify.im_config import save_app, save_channel

    # If "raw" field present, parse as JSON or YAML text
    if "raw" in body:
        raw_text = body["raw"].strip()
        parsed = None
        # Try JSON first
        try:
            parsed = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            pass
        # Try YAML
        if parsed is None:
            try:
                parsed = _yaml.safe_load(raw_text)
            except Exception:
                pass
        if not isinstance(parsed, dict):
            raise HTTPException(400, "Could not parse input as JSON or YAML")
        body = parsed

    imported_apps = 0
    imported_channels = 0

    if "apps" in body:
        for platform, apps in body["apps"].items():
            if not isinstance(apps, dict):
                continue
            for app_name, cfg in apps.items():
                if isinstance(cfg, dict):
                    save_app(platform, app_name, cfg)
                    imported_apps += 1

    if "channels" in body:
        for name, cfg in body["channels"].items():
            if not isinstance(cfg, dict):
                continue
            ch_type = cfg.pop("type", "")
            enabled = cfg.pop("enabled", True)
            if ch_type:
                save_channel(name, ch_type, cfg, is_enabled=enabled)
                imported_channels += 1

    return {"imported_apps": imported_apps, "imported_channels": imported_channels}


# ============================================================================
# MCP Servers
# ============================================================================


@app.get("/api/settings/mcp-servers")
async def api_list_mcp_servers():
    """List all configured MCP servers."""
    from agenticops.mcp_manager import list_mcp_servers
    return list_mcp_servers()


@app.put("/api/settings/mcp-servers/{name}")
async def api_upsert_mcp_server(name: str, body: dict = Body(...)):
    """Create or update an MCP server config."""
    from agenticops.mcp_manager import upsert_mcp_server
    if "command" not in body and "url" not in body:
        raise HTTPException(400, "MCP server must have 'command' (stdio) or 'url' (SSE)")
    return upsert_mcp_server(name, body)


@app.post("/api/settings/mcp-servers/import")
async def api_import_mcp_servers(body: dict = Body(...)):
    """Bulk import MCP servers from standard mcpServers JSON format.

    Accepts: {"mcpServers": {"name": {...}, ...}}
    Merges into existing config (upsert semantics).
    """
    from agenticops.mcp_manager import upsert_mcp_server
    servers = body.get("mcpServers", {})
    if not isinstance(servers, dict) or not servers:
        raise HTTPException(400, "Expected {\"mcpServers\": {\"name\": {...}, ...}}")
    imported = []
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        if "command" not in cfg and "url" not in cfg:
            continue
        upsert_mcp_server(name, cfg)
        imported.append(name)
    return {"imported": imported, "count": len(imported)}


@app.delete("/api/settings/mcp-servers/{name}", status_code=204)
async def api_delete_mcp_server(name: str):
    """Delete an MCP server config."""
    from agenticops.mcp_manager import delete_mcp_server
    if not delete_mcp_server(name):
        raise HTTPException(404, f"MCP server '{name}' not found")


@app.post("/api/settings/mcp-servers/reload")
async def api_reload_mcp_servers():
    """Hot-reload MCP clients: validate → stop → rebuild (lazy-start on next chat)."""
    from agenticops.mcp_manager import reload_mcp_clients
    validation = reload_mcp_clients()
    ok_count = sum(1 for r in validation if r["status"] == "ok")
    return {"reloaded": ok_count, "validation": validation}


@app.post("/api/settings/mcp-servers/validate")
async def api_validate_mcp_servers():
    """Validate MCP server configs without reloading."""
    from agenticops.mcp_manager import validate_mcp_config
    return {"validation": validate_mcp_config()}


@app.get("/api/settings/issue-exclude-patterns")
async def api_get_exclude_patterns():
    return {"patterns": settings.issue_exclude_patterns}


@app.patch("/api/settings/issue-exclude-patterns")
async def api_update_exclude_patterns(body: dict):
    patterns = body.get("patterns", [])
    if not isinstance(patterns, list):
        raise HTTPException(status_code=400, detail="patterns must be a list")
    import re
    for p in patterns:
        try:
            re.compile(p)
        except re.error as e:
            raise HTTPException(status_code=400, detail=f"Invalid regex pattern '{p}': {e}")
    settings.issue_exclude_patterns = patterns
    return {"patterns": settings.issue_exclude_patterns}


@app.get("/api/health", response_model=HealthResponse)
async def api_health():
    """Health check endpoint."""
    import time
    import shutil
    import boto3
    from agenticops import __version__

    checks = {}

    # 1. Database check
    db_start = time.time()
    try:
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = HealthCheckResult(
            status="ok",
            latency_ms=int((time.time() - db_start) * 1000),
        )
    except Exception as e:
        checks["database"] = HealthCheckResult(
            status="error",
            error=str(e),
        )

    # 2. AWS credentials check
    aws_start = time.time()
    try:
        from agenticops.config import get_bedrock_boto_session
        sts = get_bedrock_boto_session().client("sts")
        identity = sts.get_caller_identity()
        checks["aws"] = HealthCheckResult(
            status="ok",
            latency_ms=int((time.time() - aws_start) * 1000),
            details={"account_id": identity.get("Account")},
        )
    except Exception as e:
        checks["aws"] = HealthCheckResult(
            status="error",
            error=str(e),
        )

    # 3. Disk space check
    try:
        usage = shutil.disk_usage(settings.reports_dir)
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        used_pct = (usage.used / usage.total) * 100

        if used_pct > 90:
            disk_status = "error"
        elif used_pct > 80:
            disk_status = "warning"
        else:
            disk_status = "ok"

        checks["disk"] = HealthCheckResult(
            status=disk_status,
            details={
                "path": str(settings.reports_dir),
                "free_gb": round(free_gb, 2),
                "total_gb": round(total_gb, 2),
                "used_pct": round(used_pct, 2),
            },
        )
    except Exception as e:
        checks["disk"] = HealthCheckResult(
            status="error",
            error=str(e),
        )

    # Determine overall status
    if checks["database"].status == "error":
        overall_status = "unhealthy"
    elif any(c.status == "error" for c in checks.values()):
        overall_status = "degraded"
    elif any(c.status == "warning" for c in checks.values()):
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return HealthResponse(
        status=overall_status,
        version=__version__,
        timestamp=datetime.now(timezone.utc),
        checks=checks,
    )


@app.get("/api/stats")
async def api_stats():
    """API endpoint for dashboard stats."""
    with get_db_session() as session:
        return {
            "total_resources": session.query(CloudResource).count(),
            "open_anomalies": session.query(HealthIssue).filter_by(status="open").count(),
            "critical_anomalies": session.query(HealthIssue).filter_by(severity="critical", status="open").count(),
            "total_accounts": session.query(CloudAccount).count(),
        }


@app.get("/api/dashboard/trends")
async def api_dashboard_trends(days: int = Query(default=7, ge=1, le=90)):
    """Dashboard trend data — 5 sparkline datasets."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    with get_db_session() as session:
        # 1) Issue trend: opened/resolved per day
        issues_opened = (
            session.query(func.date(HealthIssue.detected_at).label("d"), func.count().label("n"))
            .filter(HealthIssue.detected_at >= cutoff)
            .group_by("d").all()
        )
        issues_resolved = (
            session.query(func.date(HealthIssue.resolved_at).label("d"), func.count().label("n"))
            .filter(HealthIssue.resolved_at >= cutoff, HealthIssue.resolved_at.isnot(None))
            .group_by("d").all()
        )
        opened_map = {str(r.d): r.n for r in issues_opened}
        resolved_map = {str(r.d): r.n for r in issues_resolved}
        all_dates = sorted(set(opened_map) | set(resolved_map))
        issues = [{"date": d, "opened": opened_map.get(d, 0), "resolved": resolved_map.get(d, 0)} for d in all_dates]

        # 2) Severity distribution per day
        sev_rows = (
            session.query(func.date(HealthIssue.detected_at).label("d"), HealthIssue.severity, func.count().label("n"))
            .filter(HealthIssue.detected_at >= cutoff)
            .group_by("d", HealthIssue.severity).all()
        )
        sev_map: dict = {}
        for r in sev_rows:
            d = str(r.d)
            sev_map.setdefault(d, {"date": d, "critical": 0, "high": 0, "medium": 0, "low": 0})
            if r.severity in sev_map[d]:
                sev_map[d][r.severity] = r.n
        severity = [sev_map[d] for d in sorted(sev_map)]

        # 3) Resource changes per day
        res_rows = (
            session.query(func.date(CloudResource.created_at).label("d"), func.count().label("n"))
            .filter(CloudResource.created_at >= cutoff)
            .group_by("d").all()
        )
        resources = [{"date": str(r.d), "added": r.n} for r in res_rows]

        # 4) MTTR per day (resolved issues only)
        resolved_issues = (
            session.query(HealthIssue)
            .filter(HealthIssue.resolved_at >= cutoff, HealthIssue.resolved_at.isnot(None))
            .all()
        )
        mttr_map: dict = {}
        for iss in resolved_issues:
            d = str(iss.resolved_at.date())
            hours = (iss.resolved_at - iss.detected_at).total_seconds() / 3600
            mttr_map.setdefault(d, []).append(hours)
        mttr = [{"date": d, "avg_hours": round(sum(v) / len(v), 1)} for d, v in sorted(mttr_map.items())]

        # 5) Fix success rate per day
        exec_rows = (
            session.query(func.date(FixExecution.completed_at).label("d"), FixExecution.status, func.count().label("n"))
            .filter(FixExecution.completed_at >= cutoff, FixExecution.completed_at.isnot(None))
            .group_by("d", FixExecution.status).all()
        )
        fx_map: dict = {}
        for r in exec_rows:
            d = str(r.d)
            fx_map.setdefault(d, {"total": 0, "succeeded": 0})
            fx_map[d]["total"] += r.n
            if r.status == "succeeded":
                fx_map[d]["succeeded"] += r.n
        fix_rate = [
            {"date": d, "total": v["total"], "succeeded": v["succeeded"],
             "rate": round(v["succeeded"] / v["total"] * 100, 1) if v["total"] else 0}
            for d, v in sorted(fx_map.items())
        ]

        # Summary
        total_opened = sum(d["opened"] for d in issues)
        total_resolved = sum(d["resolved"] for d in issues)
        all_mttr = [h for vals in mttr_map.values() for h in vals]
        avg_mttr = round(sum(all_mttr) / len(all_mttr), 1) if all_mttr else 0
        total_exec = sum(v["total"] for v in fx_map.values())
        total_succ = sum(v["succeeded"] for v in fx_map.values())
        net_resources = sum(d["added"] for d in resources)

        def _trend(values: list[float]) -> str:
            if len(values) < 2:
                return "flat"
            mid = len(values) // 2
            first = sum(values[:mid]) / mid if mid else 0
            second = sum(values[mid:]) / (len(values) - mid)
            if second > first * 1.1:
                return "up"
            elif second < first * 0.9:
                return "down"
            return "flat"

        return {
            "issues": issues,
            "severity": severity,
            "resources": resources,
            "mttr": mttr,
            "fix_rate": fix_rate,
            "summary": {
                "issues_opened": total_opened,
                "issues_resolved": total_resolved,
                "resource_net_change": net_resources,
                "mttr_avg_hours": avg_mttr,
                "mttr_trend": _trend([d["avg_hours"] for d in mttr]),
                "fix_rate_pct": round(total_succ / total_exec * 100, 1) if total_exec else 0,
                "fix_rate_trend": _trend([d["rate"] for d in fix_rate]),
            },
        }


# ============================================================================
# Account API Endpoints
# ============================================================================














@app.get("/api/settings/available-profiles")
async def api_available_profiles():
    """List AWS profiles available on the server (from ~/.aws/).

    Used by Web UI to show profile options when credential_source_type=profile.
    Returns empty list if no profiles found (e.g., container without mounted ~/.aws/).
    """
    from agenticops.credentials.session_factory import get_session_factory
    factory = get_session_factory()
    profiles = factory.list_available_profiles()
    return {
        "available": len(profiles) > 0,
        "profiles": profiles,
    }


@app.get("/api/settings/environment")
async def api_detect_environment():
    """Detect the current deployment environment.

    Returns environment type (eks, ecs, ec2, local) and credential store backend.
    Helps Web UI adapt its account registration form.
    """
    from agenticops.credentials.session_factory import get_session_factory
    from agenticops.credentials.store import get_credential_store
    factory = get_session_factory()
    store = get_credential_store()
    env_type = factory.detect_environment()
    return {
        "environment": env_type.value,
        "credential_backend": store.backend_name,
        "profiles_available": len(factory.list_available_profiles()) > 0,
    }


# ============================================================================
# Resource API Endpoints
# ============================================================================


@app.get("/api/resources")
async def api_list_resources(
    resource_type: Optional[str] = Query(None, alias="type"),
    region: Optional[str] = None,
    account_id: Optional[int] = None,
    status: Optional[str] = None,
    q: Optional[str] = Query(None, description="Search by resource ID, name, or type"),
    limit: Optional[int] = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
):
    """List resources with filtering and optional pagination."""
    with get_db_session() as session:
        query = session.query(CloudResource)

        if resource_type:
            query = query.filter_by(resource_type=resource_type)
        if region:
            query = query.filter_by(region=region)
        if account_id:
            query = query.filter_by(account_id=account_id)
        if status:
            query = query.filter_by(status=status)
        if q:
            pattern = f"%{q}%"
            query = query.filter(
                CloudResource.resource_id.ilike(pattern)
                | CloudResource.name.ilike(pattern)
                | CloudResource.resource_type.ilike(pattern)
            )

        total = query.count()
        q_paged = query.offset(offset)
        if limit is not None:
            q_paged = q_paged.limit(limit)
        resources = q_paged.all()
        return {
            "total": total,
            "items": [ResourceResponse.from_resource(r) for r in resources],
        }


@app.get("/api/resources/type-counts")
async def api_resource_type_counts():
    """Resource counts grouped by type."""
    with get_db_session() as session:
        rows = (
            session.query(CloudResource.resource_type, func.count())
            .group_by(CloudResource.resource_type)
            .order_by(func.count().desc())
            .all()
        )
        return {rtype: count for rtype, count in rows}


class ScanRequest(BaseModel):
    account_ids: Optional[List[int]] = None
    focus: str = "all"
    regions: Optional[List[str]] = None


@app.post("/api/scan")
async def api_trigger_scan(req: ScanRequest):
    """Trigger parallel resource scan across enabled accounts."""
    from agenticops.scanner import scan_accounts_parallel
    result = await scan_accounts_parallel(
        account_ids=req.account_ids,
        focus=req.focus,
        regions=req.regions,
    )
    return {
        "total_found": result.total_found,
        "total_updated": result.total_updated,
        "duration_s": result.duration_s,
        "accounts": [
            {
                "account_id": a.account_id,
                "account_name": a.account_name,
                "provider": a.provider,
                "resources_found": a.resources_found,
                "resources_updated": a.resources_updated,
                "regions_scanned": a.regions_scanned,
                "errors": a.errors,
            }
            for a in result.accounts
        ],
    }


class HealthCheckRequest(BaseModel):
    account_ids: Optional[List[int]] = None
    scope: str = "all"
    deep: bool = False


@app.post("/api/health-check")
async def api_trigger_health_check(req: HealthCheckRequest):
    """Trigger parallel health check across enabled accounts."""
    from agenticops.checker import check_accounts_parallel
    result = await check_accounts_parallel(
        account_ids=req.account_ids, scope=req.scope, deep=req.deep
    )
    return {
        "total_issues": result.total_issues,
        "duration_s": result.duration_s,
        "token_usage": {
            "input_tokens": result.total_input_tokens,
            "output_tokens": result.total_output_tokens,
            "cache_read_tokens": result.total_cache_read_tokens,
            "cache_write_tokens": result.total_cache_write_tokens,
        },
        "accounts": [
            {
                "account_id": a.account_id,
                "account_name": a.account_name,
                "provider": a.provider,
                "issues_created": a.issues_created,
                "duration_s": a.duration_s,
                "errors": a.errors,
                "token_usage": {
                    "input_tokens": a.input_tokens,
                    "output_tokens": a.output_tokens,
                    "cache_read_tokens": a.cache_read_tokens,
                    "cache_write_tokens": a.cache_write_tokens,
                },
            }
            for a in result.accounts
        ],
    }


@app.get("/api/resources/{resource_id}", response_model=ResourceResponse)
async def api_get_resource(resource_id: int):
    """Get resource by ID."""
    with get_db_session() as session:
        resource = session.query(CloudResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        return ResourceResponse.from_resource(resource)


# ── Resource Detail sub-endpoints ──────────────────────────────────────


class FixPlanWithExecutionsResponse(BaseModel):
    """Fix plan with its executions."""
    id: int
    health_issue_id: int
    rca_result_id: int
    risk_level: str
    title: str
    summary: str
    steps: list
    status: str
    approved_by: Optional[str]
    created_at: datetime
    executions: List[FixExecutionResponse] = []

    model_config = ConfigDict(from_attributes=True)


class RelatedResourceItem(BaseModel):
    id: Optional[int] = None
    resource_id: str
    resource_type: str
    resource_name: Optional[str] = None
    status: Optional[str] = None
    detail: Optional[str] = None


class RelatedResourcesResponse(BaseModel):
    network: List[RelatedResourceItem] = []
    contains: List[RelatedResourceItem] = []


_INFRA_TYPES = {"VPC", "Subnet", "SecurityGroup", "RouteTable", "IGW", "NAT", "TGW",
                "InternetGateway", "NATGateway", "TransitGateway"}






@app.get("/api/resources/{resource_id}/issues", response_model=List[HealthIssueResponse])
async def api_resource_issues(resource_id: int, limit: int = Query(default=20, le=100)):
    """List health issues for a resource."""
    with get_db_session() as session:
        resource = session.query(CloudResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        issues = (
            session.query(HealthIssue)
            .filter(HealthIssue.resource_id == resource.resource_id)
            .order_by(HealthIssue.detected_at.desc())
            .limit(limit)
            .all()
        )
        return [HealthIssueResponse.model_validate(i) for i in issues]


@app.get("/api/resources/{resource_id}/fix-plans", response_model=List[FixPlanWithExecutionsResponse])
async def api_resource_fix_plans(resource_id: int, limit: int = Query(default=20, le=100)):
    """List fix plans for a resource (via linked health issues)."""
    with get_db_session() as session:
        resource = session.query(CloudResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        plans = (
            session.query(FixPlan)
            .options(joinedload(FixPlan.fix_executions))
            .join(HealthIssue, FixPlan.health_issue_id == HealthIssue.id)
            .filter(HealthIssue.resource_id == resource.resource_id)
            .order_by(FixPlan.created_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for p in plans:
            resp = FixPlanWithExecutionsResponse.model_validate(p)
            resp.executions = [FixExecutionResponse.model_validate(e) for e in p.fix_executions]
            result.append(resp)
        return result


@app.get("/api/resources/{resource_id}/related", response_model=RelatedResourcesResponse)
async def api_resource_related(resource_id: int):
    """Get related resources — network context or contained resources."""
    with get_db_session() as session:
        resource = session.query(CloudResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        meta = resource.raw_data or {}
        is_infra = resource.resource_type in _INFRA_TYPES
        network: list[RelatedResourceItem] = []
        contains: list[RelatedResourceItem] = []

        if is_infra:
            ref_key = _infra_ref_key(resource.resource_type)
            if ref_key:
                matched = (
                    session.query(CloudResource)
                    .filter(
                        CloudResource.id != resource.id,
                        func.json_extract(CloudResource.raw_data, f"$.{ref_key}") == resource.resource_id,
                    )
                    .limit(100)
                    .all()
                )
                for c in matched:
                    contains.append(RelatedResourceItem(
                        id=c.id, resource_id=c.resource_id,
                        resource_type=c.resource_type,
                        resource_name=c.name, status=c.status,
                    ))
        else:
            for key in ("vpc_id", "subnet_id", "security_groups", "subnet_ids"):
                val = meta.get(key)
                if not val:
                    continue
                ids = val if isinstance(val, list) else [val]
                for rid in ids:
                    if not isinstance(rid, str):
                        continue
                    linked = session.query(CloudResource).filter_by(resource_id=rid).first()
                    if linked:
                        network.append(RelatedResourceItem(
                            id=linked.id, resource_id=linked.resource_id,
                            resource_type=linked.resource_type,
                            resource_name=linked.name, status=linked.status,
                        ))
                    else:
                        network.append(RelatedResourceItem(resource_id=rid, resource_type=_guess_type(rid)))

        return RelatedResourcesResponse(network=network, contains=contains)




# ============================================================================
# Anomaly API Endpoints (Legacy — backed by HealthIssue)
# ============================================================================




@app.get("/api/anomalies", response_model=List[AnomalyResponse])
async def api_list_anomalies(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    account_id: Optional[int] = Query(None),
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = 0,
):
    """List anomalies (backed by HealthIssue)."""
    with get_db_session() as session:
        query = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc())

        if severity:
            query = query.filter_by(severity=severity)
        if status:
            query = query.filter_by(status=status)
        if account_id is not None:
            query = query.filter_by(account_id=account_id)
        if resource_type:
            query = query.filter(
                HealthIssue.metric_data["resource_type"].as_string() == resource_type
            )

        issues = query.offset(offset).limit(limit).all()
        acct_names = _build_account_name_map(session, issues)
        return [_health_issue_to_anomaly_response(i, acct_names.get(i.account_id)) for i in issues]


@app.get("/api/anomalies/{anomaly_id}", response_model=AnomalyResponse)
async def api_get_anomaly(anomaly_id: int):
    """Get anomaly by ID (backed by HealthIssue)."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=anomaly_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Anomaly not found")
        acct_name = None
        if issue.account_id:
            acct = session.query(CloudAccount.name).filter_by(id=issue.account_id).scalar()
            acct_name = acct
        return _health_issue_to_anomaly_response(issue, acct_name)




@app.put("/api/anomalies/{anomaly_id}/status", response_model=AnomalyResponse)
async def api_update_anomaly_status(anomaly_id: int, update: AnomalyStatusUpdate):
    """Update anomaly status (backed by HealthIssue) with state machine enforcement."""
    from agenticops.models import InvalidStatusTransition, validate_status_transition

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=anomaly_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Anomaly not found")

        try:
            validate_status_transition(issue.status, update.status)
        except InvalidStatusTransition as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        issue.status = update.status
        if update.status == "resolved" and issue.resolved_at is None:
            issue.resolved_at = datetime.now(timezone.utc)

        # Auto-learn: dismissed issues create detect agent memory
        if update.status == "dismissed":
            _auto_learn_dismissed(issue.id, issue.resource_id, issue.title, issue.description)

        session.flush()
        acct_name = None
        if issue.account_id:
            acct_name = session.query(CloudAccount.name).filter_by(id=issue.account_id).scalar()
        return _health_issue_to_anomaly_response(issue, acct_name)


@app.get("/api/anomalies/{issue_id}/rca", response_model=Optional[RCAResponse])
async def api_get_anomaly_rca(issue_id: int):
    """Get RCA result for a health issue (or legacy anomaly ID)."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        rca = (
            session.query(RCAResult)
            .filter_by(health_issue_id=issue_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )

        if not rca:
            return None

        return RCAResponse.model_validate(rca)


@app.post("/api/anomalies/{issue_id}/rca", status_code=202)
async def api_trigger_anomaly_rca(issue_id: int):
    """Trigger RCA for an anomaly (legacy compat — delegates to health-issues endpoint)."""
    return await api_trigger_rca(issue_id)


@app.post("/api/anomalies/{issue_id}/generate-fix-plan", status_code=202)
async def api_trigger_anomaly_fix_plan(issue_id: int):
    """Trigger fix plan for an anomaly (legacy compat — delegates to health-issues endpoint)."""
    return await api_trigger_fix_plan(issue_id)


# ============================================================================
# Issues API Endpoints (canonical /api/issues/* — delegates to anomaly handlers)
# ============================================================================

@app.get("/api/issues", response_model=List[AnomalyResponse])
async def api_list_issues(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    account_id: Optional[int] = Query(None),
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = 0,
):
    """List issues."""
    return await api_list_anomalies(severity, status, resource_type, account_id, limit, offset)


@app.get("/api/issues/{issue_id}", response_model=AnomalyResponse)
async def api_get_issue(issue_id: int):
    """Get issue by ID."""
    return await api_get_anomaly(issue_id)


@app.put("/api/issues/{issue_id}/status", response_model=AnomalyResponse)
async def api_update_issue_status(issue_id: int, update: AnomalyStatusUpdate):
    """Update issue status."""
    return await api_update_anomaly_status(issue_id, update)


@app.get("/api/issues/{issue_id}/rca", response_model=Optional[RCAResponse])
async def api_get_issue_rca(issue_id: int):
    """Get RCA result for an issue."""
    return await api_get_anomaly_rca(issue_id)


@app.post("/api/issues/{issue_id}/rca", status_code=202)
async def api_trigger_issue_rca(issue_id: int):
    """Trigger RCA analysis for an issue."""
    return await api_trigger_rca(issue_id)


@app.post("/api/issues/{issue_id}/generate-fix-plan", status_code=202)
async def api_trigger_issue_fix_plan(issue_id: int):
    """Trigger fix plan generation for an issue."""
    return await api_trigger_fix_plan(issue_id)


# ============================================================================
# HealthIssue API Endpoints
# ============================================================================


@app.get("/api/health-issues", response_model=List[HealthIssueResponse])
async def api_list_health_issues(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    resource_id: Optional[str] = None,
    source: Optional[str] = None,
    trace_id: Optional[str] = None,
    account_id: Optional[int] = Query(None),
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """List health issues with filtering."""
    with get_db_session() as session:
        query = session.query(HealthIssue).order_by(HealthIssue.detected_at.desc())

        if severity:
            query = query.filter_by(severity=severity)
        if status:
            query = query.filter_by(status=status)
        if resource_id:
            query = query.filter_by(resource_id=resource_id)
        if source:
            query = query.filter_by(source=source)
        if trace_id:
            query = query.filter_by(trace_id=trace_id)
        if account_id is not None:
            query = query.filter_by(account_id=account_id)

        issues = query.offset(offset).limit(limit).all()
        acct_names = _build_account_name_map(session, issues)
        return [HealthIssueResponse.from_issue(i, acct_names.get(i.account_id)) for i in issues]


@app.get("/api/health-issues/{issue_id}", response_model=HealthIssueResponse)
async def api_get_health_issue(issue_id: int):
    """Get health issue by ID."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")
        acct_name = None
        if issue.account_id:
            acct_name = session.query(CloudAccount.name).filter_by(id=issue.account_id).scalar()
        return HealthIssueResponse.from_issue(issue, acct_name)


@app.post("/api/health-issues", response_model=HealthIssueResponse, status_code=201)
async def api_create_health_issue(data: HealthIssueCreate):
    """Create a new health issue. Auto-triggers RCA in background."""
    with get_db_session() as session:
        issue = HealthIssue(
            resource_id=data.resource_id,
            provider=data.provider or "aws",
            severity=data.severity,
            source=data.source,
            title=data.title,
            description=data.description,
            alarm_name=data.alarm_name,
            metric_data=data.metric_data,
            related_changes=data.related_changes,
        )
        session.add(issue)
        session.flush()
        response = HealthIssueResponse.model_validate(issue)

    # Auto-trigger RCA after commit
    from agenticops.services.rca_service import trigger_auto_rca
    trigger_auto_rca(response.id)

    return response


@app.put("/api/health-issues/{issue_id}", response_model=HealthIssueResponse)
async def api_update_health_issue(issue_id: int, data: HealthIssueUpdate):
    """Update a health issue with state machine enforcement on status transitions."""
    from agenticops.models import InvalidStatusTransition, validate_status_transition

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        update_data = data.model_dump(exclude_unset=True)

        # Validate status transition if status is being changed
        new_status = update_data.get("status")
        if new_status and new_status != issue.status:
            try:
                validate_status_transition(issue.status, new_status)
            except InvalidStatusTransition as e:
                raise HTTPException(status_code=409, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        # Auto-set resolved_at when status transitions to resolved
        transitioning_to_resolved = (
            new_status == "resolved" and issue.status != "resolved"
        )
        if transitioning_to_resolved:
            update_data["resolved_at"] = datetime.now(timezone.utc)

        for key, value in update_data.items():
            setattr(issue, key, value)

        session.flush()
        result = HealthIssueResponse.model_validate(issue)

    # Trigger post-resolution pipeline (outside DB session)
    if transitioning_to_resolved:
        try:
            from agenticops.services.resolution_service import trigger_post_resolution
            trigger_post_resolution(issue_id)
        except Exception:
            logger.warning("Failed to trigger post-resolution for issue #%d", issue_id)

    return result


@app.delete("/api/health-issues/{issue_id}", status_code=204)
async def api_delete_health_issue(issue_id: int):
    """Delete a health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")
        session.delete(issue)


@app.get("/api/health-issues/{issue_id}/rca", response_model=List[RCAResponse])
async def api_list_health_issue_rca(issue_id: int):
    """List all RCA results for a health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        rcas = (
            session.query(RCAResult)
            .filter_by(health_issue_id=issue_id)
            .order_by(RCAResult.created_at.desc())
            .all()
        )
        return [RCAResponse.model_validate(r) for r in rcas]


@app.get("/api/health-issues/{issue_id}/fix-plans", response_model=List[FixPlanResponse])
async def api_list_health_issue_fix_plans(issue_id: int):
    """List all fix plans for a health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        plans = (
            session.query(FixPlan)
            .filter_by(health_issue_id=issue_id)
            .order_by(FixPlan.created_at.desc())
            .all()
        )
        return [FixPlanResponse.model_validate(p) for p in plans]


@app.post("/api/health-issues/{issue_id}/rca", response_model=RCAResponse, status_code=202)
async def api_trigger_rca(issue_id: int):
    """Trigger RCA analysis for a health issue via the rca_agent.

    Runs the rca_agent as a tool call and stores the result.
    Returns the new RCA result.
    """
    import threading

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        # Run RCA agent in background thread and return immediately
        issue_title = issue.title
        issue_desc = issue.description
        issue_resource = issue.resource_id

    def _run_rca():
        try:
            from agenticops.agents.rca_agent import rca_agent
            result = rca_agent(issue_id=issue_id)
            logger.info("RCA triggered for issue #%d: %s", issue_id, str(result)[:200])
        except Exception:
            logger.exception("RCA trigger failed for issue #%d", issue_id)

    thread = threading.Thread(target=_run_rca, daemon=True, name=f"rca-trigger-{issue_id}")
    thread.start()

    # Return a placeholder — the RCA will be available after the agent completes
    return JSONResponse(
        status_code=202,
        content={
            "message": f"RCA analysis triggered for issue #{issue_id}. Refresh to see results.",
            "health_issue_id": issue_id,
        },
    )


@app.post("/api/health-issues/{issue_id}/generate-fix-plan", status_code=202)
async def api_trigger_fix_plan(issue_id: int):
    """Trigger fix plan generation for a health issue via the sre_agent.

    Requires an existing RCA result. Runs sre_agent in background.
    """
    import threading

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        rca = (
            session.query(RCAResult)
            .filter_by(health_issue_id=issue_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )
        if not rca:
            raise HTTPException(status_code=400, detail="No RCA result found. Run RCA first.")

        # Guard: reject if issue has a locked fix plan (pending_approval/approved/executing)
        from agenticops.models import FIXPLAN_LOCKED_STATUSES
        locked = (
            session.query(FixPlan)
            .filter_by(health_issue_id=issue_id)
            .filter(FixPlan.status.in_(FIXPLAN_LOCKED_STATUSES))
            .first()
        )
        if locked:
            raise HTTPException(
                status_code=409,
                detail=f"Issue #{issue_id} already has FixPlan #{locked.id} in '{locked.status}' state. "
                       f"Wait for it to complete or reject it first.",
            )

    def _run_fix_plan():
        try:
            from agenticops.agents.sre_agent import sre_agent
            result = sre_agent(issue_id=issue_id)
            logger.info("Fix plan generated for issue #%d: %s", issue_id, str(result)[:200])
        except Exception:
            logger.exception("Fix plan generation failed for issue #%d", issue_id)

    thread = threading.Thread(target=_run_fix_plan, daemon=True, name=f"fixplan-trigger-{issue_id}")
    thread.start()

    return JSONResponse(
        status_code=202,
        content={
            "message": f"Fix plan generation triggered for issue #{issue_id}. Refresh to see results.",
            "health_issue_id": issue_id,
        },
    )


# ============================================================================
# Webhook — Inbound Alert Intake
# ============================================================================


@app.post("/api/webhooks/alert")
async def api_webhook_alert_auto(request: Request):
    """Receive an alert from any external monitoring system (auto-detect source).

    Accepts JSON from Datadog, PagerDuty, Grafana, or generic format.
    Creates an AlertEvent record, optionally creates a HealthIssue, and triggers RCA.
    """
    body = await request.json()
    return await _process_webhook_alert(body)


@app.post("/api/webhooks/alert/{source}")
async def api_webhook_alert_explicit(source: str, request: Request):
    """Receive an alert with explicit source type.

    Args:
        source: One of datadog, pagerduty, grafana, prometheus, cloudwatch, generic.
    """
    valid_sources = {"datadog", "pagerduty", "grafana", "prometheus", "cloudwatch", "generic"}
    if source.lower() not in valid_sources:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Valid: {', '.join(sorted(valid_sources))}",
        )
    body = await request.json()
    return await _process_webhook_alert(body, source=source.lower())


@app.get("/api/webhooks/alert/events", response_model=List[AlertEventResponse])
async def api_list_alert_events(
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List recent alert events from webhooks."""
    with get_db_session() as session:
        query = session.query(AlertEvent).order_by(AlertEvent.received_at.desc())
        if source:
            query = query.filter_by(source=source)
        if status:
            query = query.filter_by(status=status)
        events = query.offset(offset).limit(limit).all()
        return [AlertEventResponse.model_validate(e) for e in events]


@app.get("/api/webhooks/alert/events/{event_id}", response_model=AlertEventResponse)
async def api_get_alert_event(event_id: int):
    """Get a specific alert event by ID."""
    with get_db_session() as session:
        event = session.query(AlertEvent).filter_by(id=event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Alert event not found")
        return AlertEventResponse.model_validate(event)


@app.get("/api/providers")
async def api_list_providers():
    """List configured monitoring providers and their status."""
    from agenticops.integrations import list_provider_names
    return list_provider_names()


async def _process_webhook_alert(body: dict, source: str = "") -> JSONResponse:
    """Process an inbound webhook alert: parse, dedup, create HealthIssue, trigger RCA."""
    if settings.alert_pipeline_mode == "channel_driven":
        raise HTTPException(
            status_code=503,
            detail="Event-driven pipeline disabled (mode=channel_driven)",
        )

    from agenticops.config import generate_trace_id, set_trace_id
    from agenticops.integrations.parsers import parse_alert
    from agenticops.integrations.alert_processor import process_alert

    # Generate trace_id at alert entry point
    trace_id = generate_trace_id()
    set_trace_id(trace_id)

    try:
        alert = parse_alert(body, source=source)
    except Exception as e:
        logger.warning("Failed to parse webhook alert: %s", e)
        raise HTTPException(status_code=400, detail=f"Failed to parse alert: {e}")

    result = process_alert(alert, trace_id=trace_id)

    if result.action == "error":
        raise HTTPException(status_code=500, detail=result.message)

    is_dedup = result.action == "deduplicated"
    return JSONResponse(
        status_code=200 if is_dedup else 201,
        content={
            "message": result.message,
            "alert_event_id": result.alert_event_id,
            "health_issue_id": result.health_issue_id,
            "deduplicated": is_dedup,
            "trace_id": trace_id,
        },
    )


# ============================================================================
# FixPlan API Endpoints
# ============================================================================


@app.get("/api/fix-plans", response_model=List[FixPlanResponse])
async def api_list_fix_plans(
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    health_issue_id: Optional[int] = None,
    account_id: Optional[int] = Query(None),
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """List fix plans with filtering."""
    with get_db_session() as session:
        query = session.query(FixPlan).order_by(FixPlan.created_at.desc())

        if status:
            query = query.filter_by(status=status)
        if risk_level:
            query = query.filter_by(risk_level=risk_level)
        if health_issue_id:
            query = query.filter_by(health_issue_id=health_issue_id)
        if account_id is not None:
            query = query.join(HealthIssue).filter(HealthIssue.account_id == account_id)

        plans = query.offset(offset).limit(limit).all()
        # Resolve account_id from related HealthIssue
        issue_ids = {p.health_issue_id for p in plans}
        issue_accounts: dict[int, Optional[int]] = {}
        if issue_ids:
            rows = session.query(HealthIssue.id, HealthIssue.account_id).filter(HealthIssue.id.in_(issue_ids)).all()
            issue_accounts = {iid: aid for iid, aid in rows}
        results = []
        for p in plans:
            resp = FixPlanResponse.model_validate(p)
            resp.account_id = issue_accounts.get(p.health_issue_id)
            results.append(resp)
        return results


@app.get("/api/fix-plans/{plan_id}", response_model=FixPlanResponse)
async def api_get_fix_plan(plan_id: int):
    """Get fix plan by ID."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        resp = FixPlanResponse.model_validate(plan)
        issue = session.query(HealthIssue.account_id).filter_by(id=plan.health_issue_id).scalar()
        resp.account_id = issue
        return resp


@app.post("/api/fix-plans", response_model=FixPlanResponse, status_code=201)
async def api_create_fix_plan(data: FixPlanCreate):
    """Create a new fix plan."""
    with get_db_session() as session:
        # Validate health_issue_id exists
        issue = session.query(HealthIssue).filter_by(id=data.health_issue_id).first()
        if not issue:
            raise HTTPException(status_code=400, detail="Health issue not found")

        # Validate rca_result_id exists
        rca = session.query(RCAResult).filter_by(id=data.rca_result_id).first()
        if not rca:
            raise HTTPException(status_code=400, detail="RCA result not found")

        # Guard: reject ANY non-terminal plan (including drafts).
        # Unlike generate-fix-plan (which delegates to SRE agent with
        # in-place update), direct API creation should not silently replace.
        from agenticops.models import FIXPLAN_TERMINAL_STATUSES
        active = (
            session.query(FixPlan)
            .filter_by(health_issue_id=data.health_issue_id)
            .filter(FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES))
            .first()
        )
        if active:
            raise HTTPException(
                status_code=409,
                detail=f"Issue #{data.health_issue_id} already has active FixPlan #{active.id} ({active.status}). "
                       f"Complete or reject it before creating a new one.",
            )

        plan = FixPlan(
            health_issue_id=data.health_issue_id,
            rca_result_id=data.rca_result_id,
            risk_level=data.risk_level,
            title=data.title,
            summary=data.summary,
            steps=data.steps,
            rollback_plan=data.rollback_plan,
            estimated_impact=data.estimated_impact,
            pre_checks=data.pre_checks,
            post_checks=data.post_checks,
        )
        session.add(plan)
        session.flush()
        return FixPlanResponse.model_validate(plan)


@app.put("/api/fix-plans/{plan_id}", response_model=FixPlanResponse)
async def api_update_fix_plan(plan_id: int, data: FixPlanUpdate):
    """Update a fix plan."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(plan, key, value)

        session.flush()
        return FixPlanResponse.model_validate(plan)


@app.put("/api/fix-plans/{plan_id}/approve", response_model=FixPlanResponse)
async def api_approve_fix_plan(plan_id: int, approved_by: str = Body(..., embed=True)):
    """Approve a fix plan with risk-level enforcement.

    L2/L3 plans require human approval — agent: prefixed approvers are rejected.
    Already approved or rejected plans return 400.
    """
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")

        if plan.status == "approved":
            raise HTTPException(status_code=400, detail="Fix plan is already approved")
        if plan.status == "rejected":
            raise HTTPException(status_code=400, detail="Fix plan was rejected. Create a new plan instead")

        # L2/L3 risk gate: reject agent-initiated approvals
        if plan.risk_level in ("L2", "L3") and approved_by.startswith("agent:"):
            raise HTTPException(
                status_code=403,
                detail=f"L2/L3 fix plans require human approval. Agent '{approved_by}' cannot approve risk level {plan.risk_level}",
            )

        plan.status = "approved"
        plan.approved_by = approved_by
        plan.approved_at = datetime.now(timezone.utc)

        # Sync HealthIssue status
        issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first()
        if issue:
            issue.status = "fix_approved"

        # Capture plan_id before session closes
        approved_plan_id = plan.id

        session.flush()
        response = FixPlanResponse.model_validate(plan)

    # Chain to auto-execute (outside DB session)
    try:
        from agenticops.services.pipeline_service import trigger_auto_execute
        trigger_auto_execute(approved_plan_id)
    except Exception:
        logger.warning("Failed to trigger auto-execute for plan #%d", approved_plan_id, exc_info=True)

    return response


@app.delete("/api/fix-plans/{plan_id}", status_code=204)
async def api_delete_fix_plan(plan_id: int):
    """Delete a fix plan."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        session.delete(plan)


# ============================================================================
# Fix Execution API Endpoints (L4 Auto Operation)
# ============================================================================


@app.post("/api/fix-plans/{plan_id}/execute", response_model=FixExecutionResponse, status_code=202)
async def api_execute_fix_plan(plan_id: int, executed_by: str = Body(default="api_user", embed=True)):
    """Trigger execution of an approved fix plan.

    Creates a FixExecution record in 'pending' status. The actual execution
    is handled asynchronously by the executor agent.
    """
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")

        if plan.status != "approved":
            raise HTTPException(
                status_code=400,
                detail=f"Fix plan status is '{plan.status}', must be 'approved' to execute",
            )

        if not settings.executor_enabled:
            raise HTTPException(
                status_code=403,
                detail="Executor is disabled. Set AIOPS_EXECUTOR_ENABLED=true to enable",
            )

        # Mark plan as executing
        plan.status = "executing"

        execution = FixExecution(
            fix_plan_id=plan_id,
            health_issue_id=plan.health_issue_id,
            status="pending",
            executed_by=executed_by,
        )
        session.add(execution)
        session.flush()
        return FixExecutionResponse.model_validate(execution)


@app.get("/api/fix-executions", response_model=List[FixExecutionResponse])
async def api_list_fix_executions(
    fix_plan_id: Optional[int] = None,
    health_issue_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = 0,
):
    """List fix executions with optional filters."""
    with get_db_session() as session:
        query = session.query(FixExecution).order_by(FixExecution.created_at.desc())

        if fix_plan_id is not None:
            query = query.filter_by(fix_plan_id=fix_plan_id)
        if health_issue_id is not None:
            query = query.filter_by(health_issue_id=health_issue_id)
        if status:
            query = query.filter_by(status=status)

        executions = query.offset(offset).limit(limit).all()
        return [FixExecutionResponse.model_validate(e) for e in executions]


@app.get("/api/fix-executions/{execution_id}", response_model=FixExecutionResponse)
async def api_get_fix_execution(execution_id: int):
    """Get a specific fix execution with step-level results."""
    with get_db_session() as session:
        execution = session.query(FixExecution).filter_by(id=execution_id).first()
        if not execution:
            raise HTTPException(status_code=404, detail="Fix execution not found")
        return FixExecutionResponse.model_validate(execution)


@app.get("/api/health-issues/{issue_id}/executions", response_model=List[FixExecutionResponse])
async def api_list_issue_executions(issue_id: int):
    """List all fix executions for a specific health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        executions = (
            session.query(FixExecution)
            .filter_by(health_issue_id=issue_id)
            .order_by(FixExecution.created_at.desc())
            .all()
        )
        return [FixExecutionResponse.model_validate(e) for e in executions]


@app.get("/api/health-issues/{issue_id}/timeline")
async def api_get_issue_timeline(issue_id: int):
    """Get the pipeline event timeline for a health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

    from agenticops.services.pipeline_events import get_timeline
    return get_timeline(issue_id)


@app.get("/api/trace/{trace_id}")
async def api_get_trace(trace_id: str):
    """Get all artifacts linked to a pipeline trace ID."""
    from agenticops.models import PipelineEvent

    with get_db_session() as session:
        # Find linked HealthIssues
        issues = session.query(HealthIssue).filter_by(trace_id=trace_id).all()
        issue_ids = [i.id for i in issues]
        issues_data = [HealthIssueResponse.from_issue(i).model_dump(mode="json") for i in issues]

        # Find linked AlertEvents
        alert_events = session.query(AlertEvent).filter_by(trace_id=trace_id).all()
        alerts_data = [
            {
                "id": a.id, "source": a.source, "external_id": a.external_id,
                "severity": a.severity, "title": a.title,
                "health_issue_id": a.health_issue_id, "status": a.status,
                "received_at": a.received_at.isoformat() if a.received_at else None,
                "trace_id": a.trace_id,
            }
            for a in alert_events
        ]

        # Find PipelineEvents for all linked issues
        timeline = []
        if issue_ids:
            events = (
                session.query(PipelineEvent)
                .filter(PipelineEvent.health_issue_id.in_(issue_ids))
                .order_by(PipelineEvent.created_at.asc())
                .all()
            )
            timeline = [
                {
                    "id": e.id, "health_issue_id": e.health_issue_id,
                    "event_type": e.event_type, "stage": e.stage,
                    "status": e.status, "actor": e.actor,
                    "duration_ms": e.duration_ms,
                    "detail": json.loads(e.detail) if e.detail else None,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "trace_id": e.trace_id,
                }
                for e in events
            ]

    return {
        "trace_id": trace_id,
        "health_issues": issues_data,
        "alert_events": alerts_data,
        "timeline": timeline,
    }


@app.post("/api/fix-executions/{execution_id}/cancel")
async def api_cancel_execution(execution_id: int):
    """Cancel a running fix execution."""
    if _executor_service.cancel_execution(execution_id):
        return {"status": "cancelled", "execution_id": execution_id}
    raise HTTPException(status_code=400, detail="Execution not found or not in running state")


@app.get("/api/executor/status")
async def api_executor_status():
    """Get executor service status."""
    return {
        "enabled": settings.executor_enabled,
        "running": _executor_service.is_running,
        "active_executions": _executor_service.active_count,
        "poll_interval": settings.executor_poll_interval,
        "auto_resolve": settings.executor_auto_resolve,
    }


# ============================================================================
# Knowledge Base API Endpoints
# ============================================================================


@app.post("/api/rag/pipeline/{health_issue_id}")
async def api_run_rag_pipeline(health_issue_id: int):
    """Manually trigger RAG pipeline for a health issue."""
    if not settings.rag_pipeline_enabled:
        raise HTTPException(status_code=400, detail="RAG pipeline is disabled")

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

    from agenticops.pipeline.rag_pipeline import run_rag_pipeline

    result = run_rag_pipeline(health_issue_id)
    return {
        "health_issue_id": result.health_issue_id,
        "success": result.success,
        "action": result.action,
        "sop_path": result.sop_path,
        "sop_filename": result.sop_filename,
        "similarity_score": result.similarity_score,
        "embed_status": result.embed_status,
        "validation_passed": result.validation_passed,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "steps": result.steps,
    }


@app.post("/api/kb/distill/{health_issue_id}")
async def api_distill_case(health_issue_id: int):
    """Manually trigger case distillation for a health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

    from agenticops.tools.kb_tools import distill_case_study

    result = distill_case_study(health_issue_id)
    return {"health_issue_id": health_issue_id, "result": result}


@app.get("/api/kb/sops")
async def api_list_sops(status: Optional[str] = None):
    """List SOPs with lifecycle metadata. Auto-backfills from filesystem if DB is empty."""
    from agenticops.tools.kb_tools import _parse_frontmatter

    sops = []
    with get_db_session() as session:
        # Auto-backfill: import any SOP files on disk that are missing from DB
        if settings.sops_dir.exists():
            existing_names = {r[0] for r in session.query(SOPRecord.filename).all()}
            for f in sorted(settings.sops_dir.glob("*.md")):
                if f.name in existing_names:
                    continue
                try:
                    content = f.read_text(encoding="utf-8")
                    metadata, _ = _parse_frontmatter(content)
                    record = SOPRecord(
                        filename=f.name,
                        resource_type=metadata.get("resource_type", ""),
                        issue_pattern=(metadata.get("issue_pattern", "") or "")[:500],
                        severity=metadata.get("severity", "medium"),
                        status="review",
                        quality_score=0.5,
                        file_path=str(f),
                    )
                    session.add(record)
                except Exception:
                    pass

        query = session.query(SOPRecord).order_by(SOPRecord.updated_at.desc())
        if status:
            query = query.filter_by(status=status)
        records = query.all()

        for r in records:
            preview = ""
            try:
                path = Path(r.file_path)
                if path.exists():
                    content = path.read_text(encoding="utf-8")
                    _, body = _parse_frontmatter(content)
                    preview = body[:200] if body else ""
            except Exception:
                pass
            sops.append({
                "id": r.id,
                "filename": r.filename,
                "resource_type": r.resource_type,
                "issue_pattern": r.issue_pattern,
                "severity": r.severity,
                "status": r.status,
                "quality_score": r.quality_score,
                "application_count": r.application_count,
                "success_count": r.success_count,
                "approved_by": r.approved_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "preview": preview,
            })
    return {"count": len(sops), "sops": sops}


@app.get("/api/kb/sops/{sop_id}")
async def api_get_sop(sop_id: int):
    """Get SOP detail with full content."""
    with get_db_session() as session:
        record = session.query(SOPRecord).filter_by(id=sop_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="SOP not found")
        content = ""
        try:
            path = Path(record.file_path)
            if path.exists():
                content = path.read_text(encoding="utf-8")
        except Exception:
            pass
        return {
            "id": record.id,
            "filename": record.filename,
            "resource_type": record.resource_type,
            "issue_pattern": record.issue_pattern,
            "severity": record.severity,
            "status": record.status,
            "quality_score": record.quality_score,
            "application_count": record.application_count,
            "success_count": record.success_count,
            "source_issue_id": record.source_issue_id,
            "approved_by": record.approved_by,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
            "content": content,
        }


@app.post("/api/kb/sops/{sop_id}/approve")
async def api_approve_sop(sop_id: int, body: dict = Body(...)):
    """Approve an SOP (transition to active)."""
    approved_by = body.get("approved_by", "admin")
    with get_db_session() as session:
        record = session.query(SOPRecord).filter_by(id=sop_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="SOP not found")
        try:
            validate_sop_transition(record.status, "active")
        except (InvalidSOPTransition, ValueError) as e:
            raise HTTPException(status_code=409, detail=str(e))
        record.status = "active"
        record.approved_by = approved_by
        record.reviewed_at = datetime.now(timezone.utc)
    return {"status": "active", "approved_by": approved_by}


@app.post("/api/kb/sops/{sop_id}/reject")
async def api_reject_sop(sop_id: int):
    """Reject an SOP (transition to archived)."""
    with get_db_session() as session:
        record = session.query(SOPRecord).filter_by(id=sop_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="SOP not found")
        try:
            validate_sop_transition(record.status, "archived")
        except (InvalidSOPTransition, ValueError) as e:
            raise HTTPException(status_code=409, detail=str(e))
        record.status = "archived"
        record.reviewed_at = datetime.now(timezone.utc)
    return {"status": "archived"}


@app.post("/api/kb/sops/{sop_id}/deprecate")
async def api_deprecate_sop(sop_id: int):
    """Deprecate an active SOP."""
    with get_db_session() as session:
        record = session.query(SOPRecord).filter_by(id=sop_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="SOP not found")
        try:
            validate_sop_transition(record.status, "deprecated")
        except (InvalidSOPTransition, ValueError) as e:
            raise HTTPException(status_code=409, detail=str(e))
        record.status = "deprecated"
    return {"status": "deprecated"}


@app.post("/api/kb/sops/backfill")
async def api_backfill_sops():
    """Backfill existing SOP files into SOPRecord table."""
    from agenticops.tools.kb_tools import _parse_frontmatter

    sops_dir = settings.sops_dir
    if not sops_dir.exists():
        return {"backfilled": 0, "skipped": 0}

    backfilled = 0
    skipped = 0
    with get_db_session() as session:
        for f in sorted(sops_dir.glob("*.md")):
            existing = session.query(SOPRecord).filter_by(filename=f.name).first()
            if existing:
                skipped += 1
                continue
            try:
                content = f.read_text(encoding="utf-8")
                metadata, _ = _parse_frontmatter(content)
                record = SOPRecord(
                    filename=f.name,
                    resource_type=metadata.get("resource_type", ""),
                    issue_pattern=(metadata.get("issue_pattern", "") or "")[:500],
                    severity=metadata.get("severity", "medium"),
                    status="review",
                    quality_score=0.5,
                    file_path=str(f),
                )
                session.add(record)
                backfilled += 1
            except Exception:
                skipped += 1
    return {"backfilled": backfilled, "skipped": skipped}


@app.get("/api/kb/cases")
async def api_list_cases():
    """List all case studies in the knowledge base."""
    from agenticops.tools.kb_tools import _parse_frontmatter

    cases = []
    cases_dir = settings.cases_dir
    if cases_dir.exists():
        for f in sorted(cases_dir.glob("*.md"), reverse=True):
            try:
                content = f.read_text(encoding="utf-8")
                metadata, body = _parse_frontmatter(content)
                cases.append({
                    "filename": f.name,
                    "path": str(f),
                    "case_id": f.stem,
                    "resource_type": metadata.get("resource_type", ""),
                    "severity": metadata.get("severity", ""),
                    "created_at": metadata.get("created_at", ""),
                    "status": metadata.get("status", ""),
                    "size_bytes": f.stat().st_size,
                    "preview": body[:200] if body else "",
                })
            except Exception as e:
                cases.append({"filename": f.name, "error": str(e)})
    return {"count": len(cases), "cases": cases}


@app.get("/api/kb/stats")
async def api_kb_stats():
    """Get knowledge base statistics."""
    sop_count = len(list(settings.sops_dir.glob("*.md"))) if settings.sops_dir.exists() else 0
    case_count = len(list(settings.cases_dir.glob("*.md"))) if settings.cases_dir.exists() else 0

    # Check embedding status
    embedding_status = "disabled"
    vector_count = 0
    if settings.embedding_enabled:
        try:
            from agenticops.kb.vector_store import get_vector_store
            store = get_vector_store()
            vector_count = store.count() if hasattr(store, "count") else 0
            embedding_status = "enabled"
        except Exception:
            embedding_status = "error"

    # SOP lifecycle counts — auto-backfill if DB empty but files exist
    sop_by_status = {"draft": 0, "review": 0, "active": 0, "deprecated": 0, "archived": 0}
    with get_db_session() as session:
        # Backfill any SOP files missing from DB
        if sop_count > 0:
            from agenticops.tools.kb_tools import _parse_frontmatter as _pf
            existing_names = {r[0] for r in session.query(SOPRecord.filename).all()}
            for f in sorted(settings.sops_dir.glob("*.md")):
                if f.name in existing_names:
                    continue
                try:
                    content = f.read_text(encoding="utf-8")
                    metadata, _ = _pf(content)
                    record = SOPRecord(
                        filename=f.name,
                        resource_type=metadata.get("resource_type", ""),
                        issue_pattern=(metadata.get("issue_pattern", "") or "")[:500],
                        severity=metadata.get("severity", "medium"),
                        status="review",
                        quality_score=0.5,
                        file_path=str(f),
                    )
                    session.add(record)
                except Exception:
                    pass
        for row in session.query(SOPRecord.status, func.count()).group_by(SOPRecord.status).all():
            if row[0] in sop_by_status:
                sop_by_status[row[0]] = row[1]

    return {
        "sop_count": sop_count,
        "case_count": case_count,
        "embedding_status": embedding_status,
        "vector_count": vector_count,
        "rag_pipeline_enabled": settings.rag_pipeline_enabled,
        "sop_similarity_threshold": settings.sop_similarity_threshold,
        "sop_by_status": sop_by_status,
        "review_queue_count": sop_by_status["review"],
    }


# ============================================================================
# Report API Endpoints
# ============================================================================




@app.get("/api/reports")
async def api_list_reports(
    report_type: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = 0,
):
    """List reports with filtering."""
    with get_db_session() as session:
        query = session.query(Report).order_by(Report.created_at.desc())

        if report_type:
            query = query.filter_by(report_type=report_type)

        reports = query.offset(offset).limit(limit).all()
        return [_enrich_report(r) for r in reports]


@app.get("/api/reports/{report_id}")
async def api_get_report(report_id: int):
    """Get report by ID."""
    with get_db_session() as session:
        report = session.query(Report).filter_by(id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return _enrich_report(report)


@app.post("/api/reports/generate", response_model=ReportResponse, status_code=201)
async def api_generate_report(request: ReportGenerateRequest):
    """Generate a new report."""
    from agenticops.report import ReportGenerator

    with get_db_session() as session:
        # Get account(s)
        if request.account_name:
            accounts = [session.query(CloudAccount).filter_by(name=request.account_name).first()]
            if not accounts[0]:
                raise HTTPException(status_code=404, detail="Account not found")
        else:
            accounts = session.query(CloudAccount).filter_by(is_enabled=True).all()
            if not accounts:
                raise HTTPException(status_code=404, detail="No enabled accounts")

        # Generate report for each account
        for account in accounts:
            generator = ReportGenerator(account)
            if request.report_type == "daily":
                generator.generate_daily_report()
            elif request.report_type == "inventory":
                generator.generate_inventory_report()
            else:
                raise HTTPException(status_code=400, detail=f"Unknown report type: {request.report_type}")

        # Get the last generated report
        report = (
            session.query(Report)
            .order_by(Report.created_at.desc())
            .first()
        )

        if report:
            return ReportResponse.model_validate(report)
        else:
            raise HTTPException(status_code=500, detail="Report generation failed")


@app.post("/api/reports/from-session", response_model=ReportResponse, status_code=201)
async def api_report_from_session(request: ReportFromSessionRequest):
    """Create a report from a chat session's messages."""
    with get_db_session() as db:
        chat_session = db.query(ChatSession).filter_by(session_id=request.session_id).first()
        if not chat_session:
            raise HTTPException(status_code=404, detail=f"Chat session {request.session_id} not found")

        query = (
            db.query(ChatMessage)
            .filter_by(session_id=chat_session.id)
            .order_by(ChatMessage.created_at.asc())
        )
        if request.message_ids:
            query = query.filter(ChatMessage.id.in_(request.message_ids))

        messages = query.all()
        if not messages:
            raise HTTPException(status_code=404, detail="No messages found for this session")

        markdown_parts = []
        for msg in messages:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S") if msg.created_at else ""
            role_label = msg.role.capitalize() if msg.role else "Unknown"
            markdown_parts.append(f"**{role_label}** ({ts}):\n{msg.content}\n")
        markdown_content = "\n".join(markdown_parts)

        title = request.title or chat_session.name
        summary = request.summary or markdown_content[:200]

        report = Report(
            report_type="conversation",
            title=title,
            summary=summary,
            content_markdown=markdown_content,
            report_metadata={
                "source_session_id": request.session_id,
                "message_count": len(messages),
                "message_ids": [m.id for m in messages],
            },
        )
        db.add(report)
        db.flush()
        return ReportResponse.model_validate(report)


# ============================================================================
# Report Publishing & Subscription API Endpoints
# ============================================================================


@app.post("/api/share", response_model=ShareContentResponse)
async def api_share_content(request: ShareContentRequest):
    """Share content to notification channels, optionally with S3 presigned URL."""
    from agenticops.notify.notifier import NotificationManager

    if not request.subject or not request.body:
        raise HTTPException(status_code=400, detail="subject and body are required")

    presigned_url = None
    notification_body = request.body

    # Upload to S3 for long content or when forced
    if len(request.body) > 4000 or request.upload_to_s3:
        try:
            from agenticops.storage.backend import get_storage_backend

            backend = get_storage_backend()
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in request.subject[:50])
            key = f"shared/{ts}_{safe_name}.md"
            uri = backend.write(key, request.body.encode("utf-8"), content_type="text/markdown")
            presigned_url = backend.presigned_url(uri, expiry=request.expiry_hours * 3600)

            summary = request.body[:500].rstrip()
            if len(request.body) > 500:
                summary += "..."
            notification_body = summary
            if presigned_url:
                notification_body += f"\n\nFull content: {presigned_url}"
        except Exception as e:
            logger.warning("S3 upload failed for share_content, sending directly: %s", e)
            notification_body = request.body[:4000]

    manager = NotificationManager()
    channels = request.channel_names if request.channel_names else None

    try:
        results = await manager.send_notification(
            subject=request.subject,
            body=notification_body,
            channel_names=channels,
        )
    except Exception as e:
        logger.error("Share content failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Share failed: {e}")

    sent = [ch for ch, ok in results.items() if ok]
    failed = [ch for ch, ok in results.items() if not ok]

    return ShareContentResponse(
        success=len(sent) > 0,
        channels_sent=sent,
        channels_failed=failed,
        presigned_url=presigned_url,
    )


@app.post("/api/reports/{report_id}/publish", response_model=ReportPublishResponse)
async def api_publish_report(report_id: int, request: ReportPublishRequest):
    """Publish a report to an sns-report or ses channel (converts to PDF/HTML/DOCX, uploads to S3)."""
    from agenticops.notify.im_config import get_channel
    from agenticops.notify.notifier import SESNotifier, SNSReportNotifier

    # Validate channel
    channel = get_channel(request.channel_name)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{request.channel_name}' not found")
    if channel.channel_type not in ("sns-report", "ses"):
        raise HTTPException(
            status_code=400,
            detail=f"Channel '{request.channel_name}' is type '{channel.channel_type}', expected 'sns-report' or 'ses'",
        )

    # Load report
    with get_db_session() as session:
        report = session.query(Report).filter_by(id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        title = report.title
        summary = report.summary
        content_md = report.content_markdown
        report_type = report.report_type
        report_meta = report.report_metadata or {}

    # Route to appropriate notifier
    if channel.channel_type == "ses":
        notifier = SESNotifier(channel.config)
    else:
        notifier = SNSReportNotifier(channel.config)

    try:
        result = await notifier.send_report(
            report_id=report_id,
            title=title,
            summary=summary,
            content_markdown=content_md,
            report_type=report_type,
            formats=request.formats,
            report_metadata=report_meta,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Report publish failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Publish failed: {e}")

    return ReportPublishResponse(
        report_id=report_id,
        channel_name=request.channel_name,
        formats_generated=result.get("formats", []),
        download_urls=result.get("urls", {}),
        sns_message_id=result.get("message_id"),
    )


@app.post("/api/reports/subscriptions", response_model=ReportSubscriptionResponse)
async def api_subscribe_report(request: ReportSubscribeRequest):
    """Subscribe an email address to an sns-report channel's SNS topic."""
    from agenticops.notify.im_config import get_channel
    from agenticops.notify.notifier import SNSReportNotifier

    channel = get_channel(request.channel_name)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{request.channel_name}' not found")
    if channel.channel_type != "sns-report":
        raise HTTPException(
            status_code=400,
            detail=f"Channel '{request.channel_name}' is not an sns-report channel",
        )

    notifier = SNSReportNotifier(channel.config)
    try:
        result = notifier.subscribe_email(request.email)
    except Exception as e:
        logger.error("Subscribe failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Subscribe failed: {e}")

    return ReportSubscriptionResponse(
        subscription_arn=result["subscription_arn"],
        protocol="email",
        endpoint=request.email,
        status=result["status"],
    )


@app.get("/api/reports/subscriptions", response_model=List[ReportSubscriptionResponse])
async def api_list_report_subscriptions(channel_name: str = Query(...)):
    """List all subscriptions for an sns-report channel."""
    from agenticops.notify.im_config import get_channel
    from agenticops.notify.notifier import SNSReportNotifier

    channel = get_channel(channel_name)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_name}' not found")
    if channel.channel_type != "sns-report":
        raise HTTPException(
            status_code=400,
            detail=f"Channel '{channel_name}' is not an sns-report channel",
        )

    notifier = SNSReportNotifier(channel.config)
    try:
        subs = notifier.list_subscriptions()
    except Exception as e:
        logger.error("List subscriptions failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list subscriptions: {e}")

    return [ReportSubscriptionResponse(**s) for s in subs]


@app.delete("/api/reports/subscriptions/{subscription_arn_b64}")
async def api_unsubscribe_report(subscription_arn_b64: str, request: ReportUnsubscribeRequest):
    """Unsubscribe from an sns-report channel's SNS topic.

    The subscription ARN is base64-encoded in the URL path to avoid slash issues.
    """
    import base64

    from agenticops.notify.im_config import get_channel
    from agenticops.notify.notifier import SNSReportNotifier

    channel = get_channel(request.channel_name)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{request.channel_name}' not found")
    if channel.channel_type != "sns-report":
        raise HTTPException(
            status_code=400,
            detail=f"Channel '{request.channel_name}' is not an sns-report channel",
        )

    try:
        subscription_arn = base64.urlsafe_b64decode(subscription_arn_b64).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subscription ARN encoding")

    notifier = SNSReportNotifier(channel.config)
    success = notifier.unsubscribe(subscription_arn)
    if not success:
        raise HTTPException(status_code=500, detail="Unsubscribe failed")

    return {"status": "unsubscribed", "subscription_arn": subscription_arn}


# ============================================================================
# Authentication API Endpoints
# ============================================================================


















# ============================================================================
# Audit API Endpoints
# ============================================================================










# ============================================================================
# Agent Logs API Endpoints (Token Tracking)
# ============================================================================








# ============================================================================
# Schedule API Endpoints
# ============================================================================


@app.get("/api/schedules", response_model=List[ScheduleResponse])
async def api_list_schedules():
    """List all schedules."""
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as session:
        schedules = session.query(Schedule).order_by(Schedule.created_at.desc()).all()
        return [ScheduleResponse.model_validate(s) for s in schedules]


@app.get("/api/schedules/pipeline-options")
async def api_pipeline_options():
    """Return available pipeline names and AgentChain config schema."""
    return {
        "pipelines": ["FullScan", "Monitoring", "DailyReport", "HealthPatrol", "AgentChain"],
        "agent_chain_config": {
            "prompt": {"type": "string", "required": True, "description": "Task description for the agent"},
            "skills": {"type": "array", "required": False, "description": "Skills to activate"},
            "report_type": {"type": "string", "required": False, "enum": ["daily", "incident", "inventory"]},
            "notify_channels": {"type": "array", "required": False, "description": "Notification channels"},
            "timeout_seconds": {"type": "integer", "required": False, "default": 300},
        },
    }


@app.get("/api/schedules/cron-preview")
async def api_cron_preview(expr: str = ""):
    """Validate a cron expression and return the next 3 run times."""
    from agenticops.scheduler.scheduler import CronParser

    if not expr.strip():
        return {"valid": False, "error": "Empty expression"}
    try:
        parser = CronParser(expr.strip())
        now = datetime.now(timezone.utc)
        runs = []
        t = now
        for _ in range(3):
            t = parser.next_run(t)
            runs.append(t.isoformat())
        return {"valid": True, "next_runs": runs}
    except (ValueError, Exception) as e:
        return {"valid": False, "error": str(e)}


@app.get("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
async def api_get_schedule(schedule_id: int):
    """Get schedule by ID."""
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return ScheduleResponse.model_validate(schedule)


@app.post("/api/schedules", response_model=ScheduleResponse, status_code=201)
async def api_create_schedule(data: ScheduleCreate):
    """Create a new schedule."""
    from agenticops.scheduler.scheduler import Schedule, CronParser

    # Validate cron expression
    try:
        CronParser(data.cron_expression)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {e}")

    with get_db_session() as session:
        existing = session.query(Schedule).filter_by(name=data.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Schedule name already exists")

        schedule = Schedule(
            name=data.name,
            pipeline_name=data.pipeline_name,
            schedule_type=data.schedule_type,
            cron_expression=data.cron_expression,
            account_name=data.account_name,
            is_enabled=data.is_enabled,
            max_retries=data.max_retries,
            config=data.config,
        )
        session.add(schedule)
        session.flush()
        return ScheduleResponse.model_validate(schedule)


@app.put("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
async def api_update_schedule(schedule_id: int, data: ScheduleUpdate):
    """Update a schedule."""
    from agenticops.scheduler.scheduler import Schedule, CronParser

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        update_data = data.model_dump(exclude_unset=True)

        # Validate cron if being updated
        if "cron_expression" in update_data:
            try:
                CronParser(update_data["cron_expression"])
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid cron expression: {e}")

        for key, value in update_data.items():
            setattr(schedule, key, value)

        session.flush()
        return ScheduleResponse.model_validate(schedule)


@app.delete("/api/schedules/{schedule_id}", status_code=204)
async def api_delete_schedule(schedule_id: int):
    """Delete a schedule."""
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        session.delete(schedule)


@app.post("/api/schedules/{schedule_id}/run", status_code=202)
async def api_run_schedule(schedule_id: int, background_tasks: BackgroundTasks):
    """Run a schedule immediately in the background."""
    from agenticops.scheduler.scheduler import Schedule, Scheduler

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        schedule_name = schedule.name
        schedule.last_run_at = datetime.now(timezone.utc)

    def _run_in_background():
        try:
            Scheduler().run_now(schedule_name)
        except Exception as e:
            logger.error(f"Background run_now failed for schedule {schedule_name}: {e}")

    background_tasks.add_task(_run_in_background)
    return {"schedule_id": schedule_id, "status": "accepted"}


@app.get("/api/schedules/{schedule_id}/executions", response_model=List[ScheduleExecutionResponse])
async def api_list_schedule_executions(
    schedule_id: int,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """List execution history for a schedule."""
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        executions = (
            session.query(ScheduleExecution)
            .filter_by(schedule_id=schedule_id)
            .order_by(ScheduleExecution.started_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [ScheduleExecutionResponse.model_validate(e) for e in executions]


@app.get("/api/skills")
async def api_list_skills():
    """Return available agent skills with rich metadata."""
    from agenticops.skills.loader import discover_skills

    skills = discover_skills()
    result = []
    for s in skills:
        refs_dir = s.path / "references"
        ref_count = len(list(refs_dir.glob("*.md"))) if refs_dir.is_dir() else 0
        domain = s.metadata.get("domain", "general")
        result.append({
            "name": s.name,
            "description": s.description,
            "is_draft": s.is_draft,
            "domain": domain,
            "tools": s.tools,
            "ref_count": ref_count,
        })
    return result


@app.get("/api/skills/improvements")
async def api_list_skill_improvements(status: str = "all", limit: int = 50):
    """List skill improvements, optionally filtered by status."""
    from agenticops.skills.improvement_store import list_pending, list_history, list_all
    if status == "pending":
        return list_pending()
    elif status == "history":
        return list_history(limit)
    else:
        return list_all(limit)


@app.get("/api/skills/improvements/history")
async def api_skill_improvements_history(limit: int = 50):
    """Backward-compatible alias."""
    from agenticops.skills.improvement_store import list_history
    return list_history(limit=limit)


@app.post("/api/skills/improvements/batch-dismiss")
async def api_batch_dismiss_improvements(body: dict):
    """Dismiss multiple improvement records by setting status to 'dismissed'."""
    from agenticops.skills.improvement_store import update_improvement
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    results = []
    for record_id in ids:
        updated = update_improvement(record_id, "dismissed")
        results.append({"id": record_id, "dismissed": updated is not None})
    return {"results": results}


@app.get("/api/skills/{name}")
async def api_get_skill(name: str):
    """Return full skill detail including SKILL.md body and references."""
    from agenticops.skills.loader import discover_skills, load_skill_body

    skills = discover_skills()
    skill = None
    for s in skills:
        if s.name == name:
            skill = s
            break
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    body = load_skill_body(name) or ""
    refs_dir = skill.path / "references"
    references = (
        [f.name for f in sorted(refs_dir.glob("*.md"))]
        if refs_dir.is_dir()
        else []
    )
    domain = skill.metadata.get("domain", "general")

    return {
        "name": skill.name,
        "description": skill.description,
        "is_draft": skill.is_draft,
        "domain": domain,
        "tools": skill.tools,
        "ref_count": len(references),
        "references": references,
        "body_markdown": body,
        "metadata": skill.metadata,
    }


@app.post("/api/skills/generate")
async def api_generate_skill(req: dict):
    """Generate a skill from a natural language description (LLM call)."""
    description = req.get("description", "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    from agenticops.skills.evolution import generate_skill_from_description

    result = generate_skill_from_description(description)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    content = result.get("content", "")
    return {
        "name": result["name"],
        "description": result["description"],
        "body_preview": content[:2000],
        "full_content": content,
        "references": result.get("references", {}),
    }


@app.post("/api/skills/draft")
async def api_save_draft_skill(req: dict):
    """Save a generated or imported skill as a draft."""
    name = req.get("name", "").strip()
    description = req.get("description", "").strip()
    content = req.get("content", "").strip()
    if not name or not description or not content:
        raise HTTPException(
            status_code=400, detail="name, description, and content are required"
        )

    from agenticops.skills.evolution import create_draft_skill
    from agenticops.skills.loader import _invalidate_skills_cache

    references = req.get("references") or None
    path = create_draft_skill(name, description, content, references)
    _invalidate_skills_cache()
    return {"name": name, "path": str(path)}


@app.post("/api/skills/import")
async def api_import_skill(file: UploadFile = File(...)):
    """Import a skill from an uploaded .md or .zip file."""
    import tempfile
    import zipfile

    from agenticops.skills.evolution import create_draft_skill
    from agenticops.skills.loader import _invalidate_skills_cache, parse_frontmatter

    filename = file.filename or "upload"
    content_bytes = await file.read()

    if filename.endswith(".md"):
        text = content_bytes.decode("utf-8")
        fm, body = parse_frontmatter(text)
        name = fm.get("name", filename.replace(".md", "").replace("SKILL", "skill"))
        description = fm.get("description", name)
        path = create_draft_skill(name, description, body)
        _invalidate_skills_cache()
        return {"name": name, "path": str(path)}

    elif filename.endswith(".zip"):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "upload.zip"
            zip_path.write_bytes(content_bytes)

            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    if info.filename.startswith("/") or ".." in info.filename:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid path in zip: {info.filename}",
                        )
                    if not info.filename.endswith(".md") and not info.is_dir():
                        raise HTTPException(
                            status_code=400,
                            detail=f"Only .md files allowed in zip, found: {info.filename}",
                        )
                zf.extractall(tmpdir)

            extracted = Path(tmpdir)
            skill_md_files = list(extracted.rglob("SKILL.md"))
            if not skill_md_files:
                raise HTTPException(
                    status_code=400,
                    detail="No SKILL.md found in zip archive",
                )

            skill_md = skill_md_files[0]
            skill_dir = skill_md.parent
            text = skill_md.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(text)
            name = fm.get("name", skill_dir.name)
            description = fm.get("description", name)

            refs_dir = skill_dir / "references"
            references = None
            if refs_dir.is_dir():
                references = {}
                for ref_file in refs_dir.glob("*.md"):
                    references[ref_file.name] = ref_file.read_text(encoding="utf-8")

            path = create_draft_skill(name, description, body, references)
            _invalidate_skills_cache()
            return {"name": name, "path": str(path)}

    else:
        raise HTTPException(
            status_code=400,
            detail="Only .md and .zip files are supported",
        )


@app.delete("/api/skills/{name}")
async def api_delete_skill(name: str):
    """Delete a draft skill. Published skills cannot be deleted via API."""
    from agenticops.skills.loader import discover_skills
    from agenticops.skills.review import reject_draft_skill

    skills = discover_skills()
    for s in skills:
        if s.name == name:
            if not s.is_draft:
                raise HTTPException(
                    status_code=403,
                    detail=f"Skill '{name}' is published and cannot be deleted via API",
                )
            if reject_draft_skill(name):
                return {"deleted": True, "name": name}
            raise HTTPException(status_code=500, detail="Failed to delete skill")
    raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")


@app.put("/api/skills/{name}")
async def api_update_skill(name: str, body: dict = Body(...)):
    """Update a draft skill's SKILL.md content. Only drafts are editable."""
    from agenticops.skills.evolution import update_draft_skill
    from agenticops.skills.loader import _invalidate_skills_cache
    content = body.get("content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    result = update_draft_skill(name, content)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Draft skill '{name}' not found")
    _invalidate_skills_cache()
    return {"updated": True, "name": name, "path": str(result)}


@app.post("/api/skills/{name}/review")
async def api_review_skill(name: str):
    """Get diff data for a draft skill vs its published version."""
    from agenticops.skills.review import review_draft_skill
    result = review_draft_skill(name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Draft skill '{name}' not found or not a draft")
    return result


@app.post("/api/skills/{name}/promote")
async def api_promote_skill(name: str):
    """Promote a draft skill to published. The current published version is backed up."""
    from agenticops.skills.review import promote_skill
    from agenticops.skills.loader import _invalidate_skills_cache
    success = promote_skill(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Draft skill '{name}' not found or promotion failed")
    _invalidate_skills_cache()
    return {"promoted": True, "name": name}


@app.post("/api/skills/{name}/improve")
async def api_improve_skill(name: str, body: dict = Body(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    """Use LLM to auto-improve an existing skill. Creates a draft."""
    from agenticops.services.skill_improvement_service import trigger_skill_improvement, run_skill_improvement
    improvement = body.get("improvement", "")
    if not improvement.strip():
        raise HTTPException(status_code=400, detail="improvement description is required")
    result = trigger_skill_improvement(
        skill_name=name,
        gap_description=improvement,
        trigger=body.get("trigger", "manual"),
        source=body.get("source", "web"),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Schedule LLM generation in background
    background_tasks.add_task(
        run_skill_improvement,
        record_id=result["record_id"],
        skill_name=name,
        gap_description=improvement,
    )

    return result


@app.post("/api/skills/{name}/rollback")
async def api_rollback_skill(name: str):
    """Roll back a published skill to its most recent archived version (multi-gen backup)."""
    from agenticops.skills.review import rollback_skill
    if not rollback_skill(name):
        raise HTTPException(status_code=404, detail=f"No archived version to roll back for '{name}'")
    return {"rolled_back": True, "name": name}


@app.post("/api/skills/{name}/restore")
async def api_restore_skill(name: str):
    """Restore a curator-archived skill from skills/.archive/ back to draft."""
    from agenticops.skills.curator import restore_skill
    if not restore_skill(name):
        raise HTTPException(status_code=404, detail=f"Archived skill '{name}' not found")
    return {"restored": True, "name": name}


# ============================================================================
# Notification API Endpoints
# ============================================================================


@app.get("/api/notifications/channels", response_model=List[NotificationChannelResponse])
async def api_list_notification_channels():
    """List notification channels from channels.yaml. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import load_channels

    channels = load_channels()
    return [
        NotificationChannelResponse(
            name=c.name,
            channel_type=c.channel_type,
            config=c.config,
            severity_filter=c.severity_filter,
            is_enabled=c.is_enabled,
        )
        for c in channels
    ]


@app.get("/api/notifications/channels/{channel_name}", response_model=NotificationChannelResponse)
async def api_get_notification_channel(channel_name: str):
    """Get notification channel by name from channels.yaml."""
    from agenticops.notify.im_config import get_channel

    channel = get_channel(channel_name)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")
    return NotificationChannelResponse(
        name=channel.name,
        channel_type=channel.channel_type,
        config=channel.config,
        severity_filter=channel.severity_filter,
        is_enabled=channel.is_enabled,
    )


@app.post("/api/notifications/channels", response_model=NotificationChannelResponse, status_code=201)
async def api_create_notification_channel(data: NotificationChannelCreate):
    """Create a new notification channel in channels.yaml."""
    from agenticops.notify.im_config import get_channel, save_channel

    existing = get_channel(data.name)
    if existing:
        raise HTTPException(status_code=400, detail="Channel name already exists")

    save_channel(
        name=data.name,
        channel_type=data.channel_type,
        config=data.config,
        is_enabled=data.is_enabled,
        severity_filter=data.severity_filter or None,
    )
    return NotificationChannelResponse(
        name=data.name,
        channel_type=data.channel_type,
        config=data.config,
        severity_filter=data.severity_filter,
        is_enabled=data.is_enabled,
    )


@app.put("/api/notifications/channels/{channel_name}", response_model=NotificationChannelResponse)
async def api_update_notification_channel(channel_name: str, data: NotificationChannelUpdate):
    """Update a notification channel in channels.yaml."""
    from agenticops.notify.im_config import get_channel, save_channel

    channel = get_channel(channel_name)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")

    update_data = data.model_dump(exclude_unset=True)
    new_type = update_data.get("channel_type", channel.channel_type)
    new_config = update_data.get("config", channel.config)
    new_enabled = update_data.get("is_enabled", channel.is_enabled)
    new_severity = update_data.get("severity_filter", channel.severity_filter)

    save_channel(
        name=channel_name,
        channel_type=new_type,
        config=new_config,
        is_enabled=new_enabled,
        severity_filter=new_severity or None,
    )
    return NotificationChannelResponse(
        name=channel_name,
        channel_type=new_type,
        config=new_config,
        severity_filter=new_severity or [],
        is_enabled=new_enabled,
    )


@app.delete("/api/notifications/channels/{channel_name}", status_code=204)
async def api_delete_notification_channel(channel_name: str):
    """Delete a notification channel from channels.yaml."""
    from agenticops.notify.im_config import delete_channel

    if not delete_channel(channel_name):
        raise HTTPException(status_code=404, detail="Notification channel not found")


@app.post("/api/notifications/channels/{channel_name}/test")
async def api_test_notification_channel(channel_name: str, data: NotificationSendRequest):
    """Send a test notification through a channel (from channels.yaml). [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import get_channel
    from agenticops.notify.notifier import NotificationManager

    channel = get_channel(channel_name)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")

    notifier_class = NotificationManager.NOTIFIER_CLASSES.get(channel.channel_type)
    if not notifier_class:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown channel type: {channel.channel_type}",
        )

    try:
        notifier = notifier_class(channel.config)
        success = await notifier.send(
            subject=data.subject,
            body=data.body,
            severity=data.severity,
        )
        status = "sent" if success else "failed"
        return {"status": status, "channel": channel.name}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "failed", "channel": channel.name, "error": str(e)},
        )


@app.get("/api/notifications/logs", response_model=List[NotificationLogResponse])
async def api_list_notification_logs(
    channel_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """List notification logs. [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.notifier import NotificationLog

    with get_db_session() as session:
        query = session.query(NotificationLog).order_by(NotificationLog.sent_at.desc())

        if channel_name:
            query = query.filter_by(channel_name=channel_name)
        if status:
            query = query.filter_by(status=status)

        logs = query.offset(offset).limit(limit).all()
        return [NotificationLogResponse.model_validate(log) for log in logs]


@app.get("/api/notifications/im-apps")
async def api_list_im_apps():
    """Diagnostic endpoint — list configured IM app names (no secrets). [DEPRECATED: use /api/messaging/*]"""
    from agenticops.notify.im_config import list_apps
    return list_apps()


# ============================================================================
# Search API Endpoint
# ============================================================================




# ============================================================================
# Chat API Endpoints
# ============================================================================


@app.post("/api/chat/sessions", response_model=ChatSessionResponse, status_code=201)
async def api_create_chat_session(payload: ChatSessionCreate):
    sid = str(uuid.uuid4())
    name = payload.name or f"Chat {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    with get_db_session() as db:
        row = ChatSession(session_id=sid, name=name)
        db.add(row)
        db.flush()
        return ChatSessionResponse(
            id=row.id, session_id=row.session_id, name=row.name,
            created_at=row.created_at, updated_at=row.updated_at,
            last_activity_at=row.last_activity_at, message_count=0,
            model_id=row.model_id,
        )


@app.get("/api/chat/sessions", response_model=List[ChatSessionResponse])
async def api_list_chat_sessions(
    limit: int = Query(default=50, le=100),
    include_archived: bool = Query(default=False),
):
    with get_db_session() as db:
        query = db.query(ChatSession)
        if not include_archived:
            query = query.filter(ChatSession.archived == False)
        rows = (
            query
            .order_by(ChatSession.last_activity_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for r in rows:
            cnt = db.query(func.count(ChatMessage.id)).filter(
                ChatMessage.session_id == r.id
            ).scalar()
            result.append(ChatSessionResponse(
                id=r.id, session_id=r.session_id, name=r.name,
                created_at=r.created_at, updated_at=r.updated_at,
                last_activity_at=r.last_activity_at, message_count=cnt,
                pinned=r.pinned, starred=r.starred, archived=r.archived,
                model_id=r.model_id,
            ))
        return result


@app.get("/api/chat/sessions/{session_id}", response_model=ChatSessionDetail)
async def api_get_chat_session(session_id: str):
    """Session metadata only. History is fetched via the paginated
    /sessions/{id}/messages endpoint. `messages` is always [] (deprecated)."""
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        cnt = db.query(func.count(ChatMessage.id)).filter(
            ChatMessage.session_id == row.id
        ).scalar()
        return ChatSessionDetail(
            id=row.id, session_id=row.session_id, name=row.name,
            created_at=row.created_at, updated_at=row.updated_at,
            last_activity_at=row.last_activity_at,
            message_count=cnt,
            pinned=row.pinned, starred=row.starred, archived=row.archived,
            messages=[],
        )


@app.get("/api/chat/sessions/{session_id}/messages", response_model=ChatMessagesPage)
async def api_get_chat_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    before: Optional[int] = Query(default=None, description="Return messages with id < before (older page)"),
):
    """Cursor-paginated chat history, newest-first window returned in
    chronological (oldest→newest) order. Cursor = ChatMessage.id."""
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")

        q = db.query(ChatMessage).filter(ChatMessage.session_id == row.id)
        if before is not None:
            q = q.filter(ChatMessage.id < before)
        # Fetch newest `limit + 1` (descending) to detect has_more, then reverse.
        rows_desc = q.order_by(ChatMessage.id.desc()).limit(limit + 1).all()

        has_more = len(rows_desc) > limit
        page = rows_desc[:limit]                 # newest `limit` (still descending)
        page_chrono = list(reversed(page))       # oldest→newest for the client
        next_cursor = page_chrono[0].id if (page_chrono and has_more) else None

        return ChatMessagesPage(
            messages=[ChatMessageResponse(
                id=m.id, role=m.role, content=m.content,
                tool_calls=m.tool_calls, token_usage=m.token_usage,
                trace_id=m.trace_id,
                cost_usd=(m.token_usage or {}).get("cost_usd"),
                attachments=m.attachments, created_at=m.created_at,
            ) for m in page_chrono],
            has_more=has_more,
            next_cursor=next_cursor,
        )


@app.patch("/api/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def api_rename_chat_session(session_id: str, payload: ChatSessionUpdate, background_tasks: BackgroundTasks):
    model_field_set = "model_id" in payload.model_fields_set
    if model_field_set and session_id in _streaming_sessions:
        raise HTTPException(409, "A response is still streaming — stop it before switching models")
    if model_field_set and payload.model_id:
        allowed = _allowed_model_ids()
        if payload.model_id not in allowed:
            raise HTTPException(400, f"Unknown model id. Allowed: {sorted(allowed)[:10]} ...")

    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        if payload.name is not None:
            row.name = payload.name
        if payload.pinned is not None:
            row.pinned = payload.pinned
        if payload.starred is not None:
            row.starred = payload.starred
        # Track whether this request is archiving the session
        archiving = payload.archived is True and not row.archived
        if payload.archived is not None:
            row.archived = payload.archived
        model_changed = False
        if model_field_set:
            new_model = payload.model_id or None  # "" sentinel → NULL (Auto)
            model_changed = new_model != row.model_id
            row.model_id = new_model
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
        cnt = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == row.id).scalar()
        response = ChatSessionResponse(
            id=row.id, session_id=row.session_id, name=row.name,
            created_at=row.created_at, updated_at=row.updated_at,
            last_activity_at=row.last_activity_at, message_count=cnt,
            pinned=row.pinned, starred=row.starred, archived=row.archived,
            model_id=row.model_id,
        )

    # Rebuild this session's agent with the new model on next message
    if model_changed:
        _chat_sessions.remove(session_id)

    # Trigger memory extraction in the background when archiving
    if archiving:
        from agenticops.web.session_manager import _trigger_memory_extraction
        background_tasks.add_task(_trigger_memory_extraction, session_id)

    return response


def _generate_session_title(user_msg: str, assistant_msg: str) -> str | None:
    """Generate a concise session title using the cheap LLM. Returns None on failure."""
    try:
        from agenticops.config import get_bedrock_boto_session

        client = get_bedrock_boto_session().client("bedrock-runtime")
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 30,
            "messages": [{"role": "user", "content": (
                "Generate a concise title (max 6 words) for this conversation. "
                "Reply with ONLY the title, no quotes.\n\n"
                f"User: {user_msg[:500]}\nAssistant: {assistant_msg[:500]}"
            )}],
        })
        resp = client.invoke_model(
            modelId=settings.bedrock_model_id_cheap,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        title = json.loads(resp["body"].read()).get("content", [{}])[0].get("text", "").strip()
        return title if title else None
    except Exception as e:
        logger.warning("Session title generation failed: %s", e)
        return None


@app.delete("/api/chat/sessions/{session_id}", status_code=204)
async def api_delete_chat_session(session_id: str):
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
        db.delete(row)
    _chat_sessions.remove(session_id)


# ============================================================================
# Memory Facts API
# ============================================================================






# ============================================================================
# Memory Experiences API
# ============================================================================




@app.post("/api/chat/sessions/{session_id}/messages")
async def api_send_chat_message(session_id: str, request: Request):
    """Send a message, optionally with a file attachment.

    Accepts:
    - application/json: {"content": "message text"}
    - multipart/form-data: content (text field) + file (optional, repeatable for multiple attachments)
    """
    from agenticops.chat.preprocessor import preprocess_message

    content_type = request.headers.get("content-type", "")
    file_contents: list[tuple[str, str]] = []
    file_images: list[tuple[str, bytes, str]] = []
    file_documents: list[tuple[str, bytes, str, str]] = []
    attachments: list[dict] | None = None

    scan_focus_req: Optional[str] = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        text_content = str(form.get("content", "")).strip()
        scan_focus_req = str(form.get("scan_focus", "")).strip() or None
        uploads = form.getlist("file")
        valid_uploads = [u for u in uploads if hasattr(u, "filename") and u.filename]

        # Server-side cap (defense-in-depth): client enforces 5, but client
        # validation is bypassable (curl/Postman). Each file is read fully into
        # memory below, so bound the batch independent of the client.
        MAX_UPLOAD_FILES = 5
        if len(valid_uploads) > MAX_UPLOAD_FILES:
            raise HTTPException(400, f"Too many files ({len(valid_uploads)}); max {MAX_UPLOAD_FILES}")

        if valid_uploads:
            from agenticops.chat.file_reader import (
                is_image_file, is_document_file,
                read_upload_image_bytes, read_upload_document_bytes,
                read_upload_bytes,
            )
            attachments = []
            for upload in valid_uploads:
                raw = await upload.read()
                if is_image_file(upload.filename):
                    img_bytes, fmt, error = read_upload_image_bytes(upload.filename, raw)
                    if error:
                        raise HTTPException(400, error)
                    if img_bytes and fmt:
                        file_images.append((upload.filename, img_bytes, fmt))
                        attachments.append({"filename": upload.filename, "size": len(raw), "type": "image"})
                elif is_document_file(upload.filename):
                    doc_bytes, fmt, name, error = read_upload_document_bytes(upload.filename, raw)
                    if error:
                        raise HTTPException(400, error)
                    if doc_bytes and fmt and name:
                        file_documents.append((upload.filename, doc_bytes, fmt, name))
                        attachments.append({"filename": upload.filename, "size": len(raw), "type": "document"})
                else:
                    file_text, error = read_upload_bytes(upload.filename, raw)
                    if error:
                        raise HTTPException(400, error)
                    if file_text:
                        file_contents.append((upload.filename, file_text))
                        attachments.append({"filename": upload.filename, "size": len(raw), "type": "text"})

        has_file = file_contents or file_images or file_documents
        if not text_content and not has_file:
            raise HTTPException(400, "Message content or file required")
        if not text_content:
            _names = ", ".join(a["filename"] for a in (attachments or []))
            text_content = f"Please analyze the attached file(s): {_names}"
        user_content = text_content
    else:
        payload = ChatMessageCreate(**(await request.json()))
        user_content = payload.content
        scan_focus_req = payload.scan_focus

    # Intercept /channel command before agent dispatch
    if user_content.strip().lower().startswith(("/channel", "/channels")):
        from agenticops.chat.channel import execute_channel

        ch_result = execute_channel(user_content.strip())

        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row:
                db.add(ChatMessage(session_id=row.id, role="user", content=user_content))
                db.add(ChatMessage(session_id=row.id, role="assistant", content=ch_result.message))
                row.last_activity_at = datetime.now(timezone.utc)

        async def _channel_stream():
            yield {"event": "text", "data": json.dumps({"token": ch_result.message})}
            yield {"event": "done", "data": json.dumps({"input_tokens": 0, "output_tokens": 0})}

        return EventSourceResponse(_channel_stream())

    # Intercept /send_to command before agent dispatch
    if user_content.strip().lower().startswith(("/send_to ", "/sendto ")):
        from agenticops.chat.send_to import execute_send_to

        send_result = execute_send_to(user_content.strip())

        # Persist user message + result
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row:
                db.add(ChatMessage(session_id=row.id, role="user", content=user_content))
                db.add(ChatMessage(session_id=row.id, role="assistant", content=send_result.message))
                row.last_activity_at = datetime.now(timezone.utc)

        async def _send_to_stream():
            yield {"event": "text", "data": json.dumps({"token": send_result.message})}
            yield {"event": "done", "data": json.dumps({"input_tokens": 0, "output_tokens": 0})}

        return EventSourceResponse(_send_to_stream())

    # Preprocess: file injection + reference resolution (returns str or list[ContentBlock])
    enriched_content, _ = preprocess_message(
        user_content, file_contents=file_contents,
        file_images=file_images, file_documents=file_documents,
    )

    # Validate session & persist user message
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        msg = ChatMessage(
            session_id=row.id, role="user", content=user_content,
            attachments=attachments,
        )
        db.add(msg)
        row.last_activity_at = datetime.now(timezone.utc)
        db_session_pk = row.id

    async def _generate():
        # Set scan focus for this request if provided
        if scan_focus_req:
            from agenticops.config import VALID_SCAN_FOCUS, set_scan_focus
            parts = [p.strip().lower() for p in scan_focus_req.split(",") if p.strip()]
            if all(p in VALID_SCAN_FOCUS for p in parts):
                set_scan_focus(scan_focus_req)
        agent = _chat_sessions.get_or_create(session_id)
        # Set trace_id for this chat turn so sub-agent logs are correlated
        from agenticops.config import generate_trace_id, set_trace_id
        _chat_trace_id = generate_trace_id()
        set_trace_id(_chat_trace_id)
        _chat_start_time = time.monotonic()
        accumulated = ""
        tool_calls = []
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_write_tokens = 0
        _streaming_sessions.add(session_id)
        try:
            async for event in agent.stream_async(enriched_content):
                if await request.is_disconnected():
                    logger.info("Client disconnected; stopping stream for session %s", session_id)
                    break
                ev = event if isinstance(event, dict) else event.as_dict() if hasattr(event, "as_dict") else {}
                # Enhanced backend (enhanced_task async-gen) sub-events streamed
                # live via Strands ToolStreamEvent -> existing SSE event types.
                if ev.get("type") == "tool_stream":
                    from agenticops.acp.mapping import tool_stream_to_sse
                    _sse = tool_stream_to_sse(ev)
                    if _sse:
                        if _sse["event"] == "text":
                            accumulated += _sse["data"]["token"]
                        elif _sse["event"] == "tool_start":
                            _n = _sse["data"]["name"]
                            if _n not in [t["name"] for t in tool_calls]:
                                tool_calls.append({"name": _n, "status": "running"})
                        elif _sse["event"] == "tool_end":
                            # already streamed live — mark done so the post-loop
                            # sweep doesn't emit a duplicate tool_end
                            _n = _sse["data"]["name"]
                            for t in tool_calls:
                                if t["name"] == _n:
                                    t["status"] = "done"
                        yield {"event": _sse["event"], "data": json.dumps(_sse["data"])}
                    continue
                # Text token
                if "data" in ev and isinstance(ev["data"], str) and ev["data"]:
                    accumulated += ev["data"]
                    yield {"event": "text", "data": json.dumps({"token": ev["data"]})}
                # Tool use
                if "current_tool_use" in ev:
                    tool_name = ev["current_tool_use"].get("name", "")
                    if tool_name and tool_name not in [t["name"] for t in tool_calls]:
                        tool_calls.append({"name": tool_name, "status": "running"})
                        yield {"event": "tool_start", "data": json.dumps({"name": tool_name})}
                # Completion with result
                if "result" in ev:
                    res = ev["result"]
                    from agenticops.agents.metrics import extract_token_usage
                    _u = extract_token_usage(res)
                    if _u["input"] or _u["output"]:
                        input_tokens = _u["input"]
                        output_tokens = _u["output"]
                        cache_read_tokens = _u.get("cache_read", 0)
                        cache_write_tokens = _u.get("cache_write", 0)
                    # If accumulated text is empty, extract from result
                    if not accumulated and hasattr(res, "__str__"):
                        accumulated = str(res)

            # Mark tools done (skip any already finished live, e.g. enhanced
            # sub-tools that streamed their own tool_end)
            for t in tool_calls:
                if t["status"] == "done":
                    continue
                t["status"] = "done"
                yield {"event": "tool_end", "data": json.dumps({"name": t["name"]})}

            # Persist assistant message (re-verify session still exists to avoid
            # FK violation / orphan if it was deleted mid-stream)
            with get_db_session() as db:
                if db.query(ChatSession).filter(ChatSession.id == db_session_pk).first() is None:
                    logger.info("Session %s deleted mid-stream; skipping assistant persist", session_id)
                else:
                    _tu: dict | None = None
                    if input_tokens:
                        from agenticops.cost import compute_cost
                        _msg_model = _effective_main_model(session_id)
                        _tu = {
                            "input": input_tokens, "output": output_tokens,
                            "cache_read": cache_read_tokens,
                            "cache_write": cache_write_tokens,
                            "model": _msg_model,
                        }
                        _tu["cost_usd"] = compute_cost(_msg_model, _tu)
                    db.add(ChatMessage(
                        session_id=db_session_pk,
                        role="assistant",
                        content=accumulated,
                        tool_calls=tool_calls if tool_calls else None,
                        token_usage=_tu,
                        trace_id=_chat_trace_id,
                    ))

            # Auto-name session after first exchange
            import re as _re
            with get_db_session() as db:
                msg_count = db.query(func.count(ChatMessage.id)).filter(
                    ChatMessage.session_id == db_session_pk
                ).scalar()
                if msg_count == 2:
                    sess = db.query(ChatSession).filter(ChatSession.id == db_session_pk).first()
                    if sess and _re.match(r"^Chat \d{4}-\d{2}-\d{2}", sess.name):
                        title = await asyncio.get_event_loop().run_in_executor(
                            None, _generate_session_title, user_content[:500], accumulated[:500]
                        )
                        if title:
                            sess.name = title
                            sess.updated_at = datetime.now(timezone.utc)
                            yield {"event": "session_renamed", "data": json.dumps({"name": title})}

            # Log main agent call metrics
            try:
                from agenticops.services.agent_log_service import log_agent_call
                _main_model_id = _effective_main_model(session_id)
                log_agent_call(
                    agent_name="main",
                    action="chat",
                    input_summary=user_content[:500],
                    output_summary=accumulated[:500],
                    tool_calls=len(tool_calls),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=int((time.monotonic() - _chat_start_time) * 1000),
                    trace_id=_chat_trace_id,
                    model_id=_main_model_id,
                    actor_type="user",
                    actor_id=getattr(getattr(request, "state", None), "user", None),
                )
            except Exception:
                logger.debug("Failed to log main agent call", exc_info=True)

            yield {
                "event": "done",
                "data": json.dumps({
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }),
            }
        except Exception as e:
            logger.exception("Chat stream error for session %s", session_id)
            # Persist partial assistant reply (if any) WITH error metadata so the
            # UI can distinguish a failed turn from a completed one, and the user
            # message stays for retry. ChatMessage has no status column, so the
            # marker rides in the token_usage JSON.
            err_meta = {"input": input_tokens, "output": output_tokens, "error": str(e)[:500]}
            with get_db_session() as db:
                db.add(ChatMessage(
                    session_id=db_session_pk,
                    role="assistant",
                    content=accumulated or "",
                    tool_calls=tool_calls if tool_calls else None,
                    token_usage=err_meta,
                ))
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
        finally:
            _streaming_sessions.discard(session_id)

    return EventSourceResponse(_generate())


# ============================================================================
# React SPA (served at /app/*)
# ============================================================================

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"

# Mount built SPA assets
if (FRONTEND_DIR / "assets").exists():
    app.mount(
        "/app/assets",
        StaticFiles(directory=str(FRONTEND_DIR / "assets")),
        name="spa-assets",
    )


@app.get("/app/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve dist root files (logo, favicons) or fall back to index.html (SPA routes)."""
    if full_path and "/" not in full_path and ".." not in full_path:
        candidate = (FRONTEND_DIR / full_path).resolve()
        if candidate.is_file() and candidate.parent == FRONTEND_DIR.resolve():
            return FileResponse(str(candidate))
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    raise HTTPException(status_code=404, detail="Frontend not built. Run: cd frontend && npm install && npm run build")


# ============================================================================
# CORS — production origins from AIOPS_CORS_ORIGINS, dev fallback to localhost:5173
# ============================================================================

_cors_origins: list[str] = [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
]
if not _cors_origins and os.getenv("AIOPS_DEV_MODE"):
    _cors_origins = ["http://localhost:5173"]

if _cors_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
        max_age=settings.cors_max_age,
    )


# ============================================================================
# API Authentication Middleware (opt-in via AIOPS_API_AUTH_ENABLED=true)
# ============================================================================

# Public paths that never require authentication
_PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/register"}
_PUBLIC_PREFIXES = ("/app/", "/static/", "/docs", "/openapi.json", "/redoc")

if settings.api_auth_enabled:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class APIAuthMiddleware(BaseHTTPMiddleware):
        """Enforce Bearer token auth on /api/* endpoints when enabled."""

        async def dispatch(self, request, call_next):
            path = request.url.path

            # Skip non-API and public paths
            if not path.startswith("/api/") or path in _PUBLIC_PATHS:
                return await call_next(request)
            if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
                return await call_next(request)
            # Allow OPTIONS for CORS preflight
            if request.method == "OPTIONS":
                return await call_next(request)

            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required. Use 'Authorization: Bearer <token>' header."},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            token = auth_header[7:]
            from agenticops.auth import AuthService

            # Try API key (aiops_*) or session token
            user = None
            if token.startswith("aiops_"):
                result = AuthService.validate_api_key(token)
                if result:
                    user, _ = result
            else:
                user = AuthService.validate_session(token)

            if not user:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or expired token."},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Attach user to request state for downstream use
            request.state.user = user
            return await call_next(request)

    app.add_middleware(APIAuthMiddleware)
    logger.info("API authentication enabled — all /api/* endpoints require Bearer token")


# ============================================================================
# IM Aliases + Local Docs API
# ============================================================================


@app.get("/api/im-aliases")
async def api_list_im_aliases():
    """List all IM aliases."""
    from agenticops.models import IMAlias
    with get_db_session() as db:
        aliases = db.query(IMAlias).order_by(IMAlias.name).all()
        return [
            {
                "id": a.id,
                "name": a.name,
                "platform": a.platform,
                "chat_id": a.chat_id,
                "app_name": a.app_name,
                "description": a.description,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in aliases
        ]


@app.post("/api/im-aliases", status_code=201)
async def api_create_im_alias(request: Request):
    """Create a new IM alias."""
    from agenticops.models import IMAlias
    data = await request.json()
    name = data.get("name", "").strip()
    platform = data.get("platform", "").strip()
    chat_id = data.get("chat_id", "").strip()

    if not name or not platform or not chat_id:
        raise HTTPException(400, "name, platform, and chat_id are required")
    if platform not in ("feishu", "dingtalk", "wecom"):
        raise HTTPException(400, f"Invalid platform '{platform}'. Must be feishu, dingtalk, or wecom")

    with get_db_session() as db:
        existing = db.query(IMAlias).filter_by(name=name).first()
        if existing:
            raise HTTPException(409, f"IM alias '{name}' already exists")
        alias = IMAlias(
            name=name,
            platform=platform,
            chat_id=chat_id,
            app_name=data.get("app_name", "default"),
            description=data.get("description"),
        )
        db.add(alias)
        db.flush()
        return {"id": alias.id, "name": alias.name, "platform": alias.platform}


@app.delete("/api/im-aliases/{alias_id}")
async def api_delete_im_alias(alias_id: int):
    """Delete an IM alias."""
    from agenticops.models import IMAlias
    with get_db_session() as db:
        alias = db.query(IMAlias).filter_by(id=alias_id).first()
        if not alias:
            raise HTTPException(404, "IM alias not found")
        db.delete(alias)
    return {"deleted": True}


@app.get("/api/local-docs")
async def api_list_local_docs(limit: int = 50, offset: int = 0):
    """List tracked local documents."""
    from agenticops.models import LocalDoc
    with get_db_session() as db:
        docs = (
            db.query(LocalDoc)
            .order_by(LocalDoc.updated_at.desc())
            .offset(offset)
            .limit(min(limit, 200))
            .all()
        )
        return [
            {
                "id": d.id,
                "file_path": d.file_path,
                "title": d.title,
                "description": d.description,
                "file_type": d.file_type,
                "size_bytes": d.size_bytes,
                "created_by": d.created_by,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in docs
        ]


@app.get("/api/local-docs/{doc_id}")
async def api_get_local_doc(doc_id: int):
    """Get a specific local document detail."""
    from agenticops.models import LocalDoc
    with get_db_session() as db:
        doc = db.query(LocalDoc).filter_by(id=doc_id).first()
        if not doc:
            raise HTTPException(404, "Local document not found")
        return {
            "id": doc.id,
            "file_path": doc.file_path,
            "title": doc.title,
            "description": doc.description,
            "file_type": doc.file_type,
            "size_bytes": doc.size_bytes,
            "created_by": doc.created_by,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        }


# ============================================================================
# IM Bot Status API
# ============================================================================


@app.get("/api/im/bots")
async def api_im_bots():
    """Return status of each IM bot platform (Feishu/DingTalk/WeCom)."""
    from agenticops.notify.im_config import list_apps

    configured = list_apps()  # {"feishu": ["default"], ...}

    # Count active IM sessions per platform from the lazy singleton
    session_counts: dict[str, int] = {"feishu": 0, "dingtalk": 0, "wecom": 0, "slack": 0}
    if _im_sessions is not None:
        with _im_sessions._lock:
            for key in _im_sessions._agents:
                plat = key.split(":", 1)[0]
                if plat in session_counts:
                    session_counts[plat] += 1

    bots = []

    # --- Feishu (WebSocket mode) ---
    feishu_apps = configured.get("feishu", [])
    if feishu_apps:
        try:
            from agenticops.im.feishu_ws import _feishu_ws_service
            from agenticops.notify.im_config import load_channels as _load_ch
            _ch = _load_ch()
            ws_enabled = settings.feishu_ws_enabled or any(
                c.channel_type == "feishu" and c.is_enabled for c in _ch
            )
            ws_started = _feishu_ws_service is not None and _feishu_ws_service._started
            ws_thread_alive = (
                _feishu_ws_service is not None
                and _feishu_ws_service._thread is not None
                and _feishu_ws_service._thread.is_alive()
            )
            if ws_started and ws_thread_alive:
                status = "connected"
            elif ws_enabled:
                status = "disconnected"
            else:
                status = "not_configured"
        except Exception:
            ws_enabled = False
            ws_started = False
            ws_thread_alive = False
            status = "not_configured"

        bots.append({
            "platform": "feishu",
            "mode": "websocket",
            "apps": feishu_apps,
            "status": status,
            "active_sessions": session_counts["feishu"],
            "ws_enabled": ws_enabled,
            "ws_thread_alive": ws_thread_alive,
        })
    else:
        bots.append({
            "platform": "feishu",
            "mode": "websocket",
            "apps": [],
            "status": "not_configured",
            "active_sessions": 0,
            "ws_enabled": False,
            "ws_thread_alive": False,
        })

    # --- Slack (Socket Mode) ---
    slack_apps = configured.get("slack", [])
    if slack_apps:
        try:
            from agenticops.im.slack_ws import _slack_ws_service
            from agenticops.notify.im_config import load_channels as _load_ch2
            _ch2 = _load_ch2()
            slack_ws_enabled = settings.slack_ws_enabled or any(
                c.channel_type == "slack" and c.is_enabled for c in _ch2
            )
            slack_ws_started = _slack_ws_service is not None and _slack_ws_service._started
            slack_ws_thread_alive = (
                _slack_ws_service is not None
                and _slack_ws_service._thread is not None
                and _slack_ws_service._thread.is_alive()
            )
            if slack_ws_started and slack_ws_thread_alive:
                slack_status = "connected"
            elif slack_ws_enabled:
                slack_status = "disconnected"
            else:
                slack_status = "not_configured"
        except Exception:
            slack_ws_enabled = False
            slack_ws_started = False
            slack_ws_thread_alive = False
            slack_status = "not_configured"

        bots.append({
            "platform": "slack",
            "mode": "websocket",
            "apps": slack_apps,
            "status": slack_status,
            "active_sessions": session_counts["slack"],
            "ws_enabled": slack_ws_enabled,
            "ws_thread_alive": slack_ws_thread_alive,
            "callback_url": "/api/im/slack/callback",
        })
    else:
        bots.append({
            "platform": "slack",
            "mode": "websocket",
            "apps": [],
            "status": "not_configured",
            "active_sessions": 0,
            "ws_enabled": False,
            "ws_thread_alive": False,
            "callback_url": "/api/im/slack/callback",
        })

    # --- DingTalk / WeCom (callback mode) ---
    for plat, callback_path in [("dingtalk", "/api/im/dingtalk/callback"), ("wecom", "/api/im/wecom/callback")]:
        apps = configured.get(plat, [])
        bots.append({
            "platform": plat,
            "mode": "callback",
            "apps": apps,
            "status": "ready" if apps else "not_configured",
            "active_sessions": session_counts[plat],
            "callback_url": callback_path,
        })

    return bots


# ============================================================================
# IM Bidirectional Chat Endpoints (Feishu / DingTalk / WeCom)
# ============================================================================

# Lazy-initialized singleton — created on first IM callback
_im_sessions = None


def _get_im_sessions():
    global _im_sessions
    if _im_sessions is None:
        from agenticops.im.session_manager import IMChatSessionManager
        _im_sessions = IMChatSessionManager(ttl_minutes=60)
        _im_sessions.start_cleanup()
    return _im_sessions


async def _handle_im_message(platform: str, msg) -> None:
    """Process an inbound IM message: run agent → reply via notifier."""
    from agenticops.im.gateway import IMInboundMessage

    # Intercept /channel command before agent dispatch
    content_stripped = msg.content.strip()
    if content_stripped.lower().startswith(("/channel", "/channels")):
        from agenticops.chat.channel import execute_channel
        ch_result = execute_channel(content_stripped)
        response_text = ch_result.message
    # Intercept /send_to command before agent dispatch
    elif content_stripped.lower().startswith(("/send_to ", "/sendto ")):
        from agenticops.chat.send_to import execute_send_to
        send_result = execute_send_to(content_stripped)
        response_text = send_result.message
    else:
        # All messages go through Main Agent.
        # For alert channels, wrap with alert context so Agent understands
        # this is from a monitoring channel and should analyze accordingly.
        im_sessions = _get_im_sessions()
        agent = im_sessions.get_or_create(platform, msg.chat_id, msg.app_name)

        agent_input = content_stripped
        if settings.alert_pipeline_mode not in ("channel_driven", "both"):
            pass  # Channel-driven pipeline disabled — skip alert wrapping
        elif settings.im_alert_detection_enabled:
            try:
                from agenticops.notify.im_config import find_channel_by_chat

                ch = find_channel_by_chat(platform, msg.chat_id)
                is_alert_ctx = False
                if ch and ch.role == "alert":
                    is_alert_ctx = True
                elif ch and ch.alert_senders and msg.sender_id in ch.alert_senders:
                    is_alert_ctx = True

                if is_alert_ctx:
                    from agenticops.im.feishu_ws import _ALERT_CHANNEL_PROMPT
                    alert_prefix = _ALERT_CHANNEL_PROMPT.format(
                        channel_name=ch.name, platform=platform,
                    )
                    agent_input = alert_prefix + content_stripped
            except Exception as e:
                logger.warning("Alert context build error: %s", e)

        try:
            # Set IM origin context so create_health_issue stores it
            from agenticops.config import set_im_origin
            set_im_origin({"platform": platform, "chat_id": msg.chat_id})
            result = agent(agent_input)
            set_im_origin(None)  # clear after agent completes
            response_text = str(result) if result else "No response generated."
        except Exception as e:
            logger.error("IM agent error (%s:%s): %s", platform, msg.chat_id, e)
            response_text = f"Agent error: {e}"

    notifier = _get_im_sessions().get_notifier(platform, msg.chat_id, msg.app_name)

    # Persist messages
    from agenticops.models import ChatSession as ChatSessionModel, ChatMessage as ChatMessageModel
    with get_db_session() as db:
        # Find or create IM chat session
        row = db.query(ChatSessionModel).filter(
            ChatSessionModel.im_platform == platform,
            ChatSessionModel.im_chat_id == msg.chat_id,
        ).first()
        if not row:
            row = ChatSessionModel(
                session_id=f"im-{platform}-{msg.chat_id}",
                name=f"IM {platform} {msg.chat_id[:20]}",
                im_platform=platform,
                im_chat_id=msg.chat_id,
            )
            db.add(row)
            db.flush()
        # Save user message
        db.add(ChatMessageModel(session_id=row.id, role="user", content=msg.content))
        # Save assistant response
        db.add(ChatMessageModel(session_id=row.id, role="assistant", content=response_text))
        row.last_activity_at = datetime.now(timezone.utc)

    # Reply to IM
    if notifier:
        try:
            await notifier.send(subject="", body=response_text, severity=None)
        except Exception as e:
            logger.error("IM reply failed (%s:%s): %s", platform, msg.chat_id, e)


@app.post("/api/im/feishu/callback")
async def api_feishu_callback(request: Request):
    """Feishu Event Subscription callback endpoint."""
    from agenticops.im.feishu_gateway import FeishuGateway

    body = await request.body()
    payload = json.loads(body)

    # URL verification challenge
    if FeishuGateway.is_challenge(payload):
        return FeishuGateway.challenge_response(payload)

    gateway = FeishuGateway()

    # Verify signature
    headers = dict(request.headers)
    if not gateway.verify_callback(body, headers):
        raise HTTPException(403, "Invalid signature")

    msg = gateway.parse_message(payload)
    if msg:
        # Run in background to respond quickly (Feishu expects fast 200)
        import asyncio
        asyncio.ensure_future(_handle_im_message("feishu", msg))

    return {"code": 0}


@app.post("/api/im/slack/callback")
async def api_slack_callback(request: Request):
    """Slack Events API callback endpoint."""
    from agenticops.im.slack_gateway import SlackGateway

    body = await request.body()
    payload = json.loads(body)

    # URL verification challenge
    if SlackGateway.is_challenge(payload):
        return SlackGateway.challenge_response(payload)

    gateway = SlackGateway()

    # Verify signature
    headers = dict(request.headers)
    if not gateway.verify_callback(body, headers):
        raise HTTPException(403, "Invalid signature")

    msg = gateway.parse_message(payload)
    if msg:
        import asyncio
        asyncio.ensure_future(_handle_im_message("slack", msg))

    return {"ok": True}


@app.post("/api/im/dingtalk/callback")
async def api_dingtalk_callback(request: Request):
    """DingTalk robot callback endpoint."""
    from agenticops.im.dingtalk_gateway import DingTalkGateway

    body = await request.body()
    payload = json.loads(body)

    gateway = DingTalkGateway()

    headers = dict(request.headers)
    if not gateway.verify_callback(body, headers):
        raise HTTPException(403, "Invalid signature")

    msg = gateway.parse_message(payload)
    if msg:
        import asyncio
        asyncio.ensure_future(_handle_im_message("dingtalk", msg))

    return {"status": "ok"}


@app.api_route("/api/im/wecom/callback", methods=["GET", "POST"])
async def api_wecom_callback(request: Request):
    """WeCom callback endpoint with AES decryption.

    GET:  URL verification (echostr decryption)
    POST: Message callback
    """
    from agenticops.im.wecom_gateway import WeComGateway

    gateway = WeComGateway()

    # WeCom passes signature params in query string
    params = dict(request.query_params)
    headers_with_params = {
        "msg_signature": params.get("msg_signature", ""),
        "timestamp": params.get("timestamp", ""),
        "nonce": params.get("nonce", ""),
    }

    # URL verification: GET with echostr
    if request.method == "GET":
        echostr = params.get("echostr", "")
        if echostr:
            # Verify signature using empty body for GET
            if not gateway.verify_callback(b"", headers_with_params):
                raise HTTPException(403, "Invalid signature")
            decrypted = gateway.decrypt_echostr(echostr)
            if decrypted:
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse(decrypted)
        raise HTTPException(400, "Missing or invalid echostr")

    # POST: Message callback
    body = await request.body()

    if not gateway.verify_callback(body, headers_with_params):
        raise HTTPException(403, "Invalid signature")

    payload = {
        "xml_body": body.decode("utf-8"),
        **headers_with_params,
    }
    msg = gateway.parse_message(payload)
    if msg:
        import asyncio
        asyncio.ensure_future(_handle_im_message("wecom", msg))

    return ""


# ============================================================================
# Agent Memory API
# ============================================================================


class IssueFeedbackRequest(BaseModel):
    """Schema for issue feedback (false positive / confirmed)."""
    type: str = Field(..., pattern="^(false_positive|confirmed)$")
    note: str = ""
    confidence: int = Field(default=3, ge=1, le=5)


class AgentMemoryResponse(BaseModel):
    """Schema for agent memory entry."""
    agent: str
    filename: str
    type: str
    status: str
    confidence: int
    source: str
    resource_pattern: str = ""
    related_issue_id: Optional[int] = None
    summary: str
    created_at: str
    last_confirmed: str


class AgentMemoryUpdateRequest(BaseModel):
    """Schema for updating an agent memory entry."""
    confidence: Optional[int] = Field(None, ge=1, le=5)
    status: Optional[str] = Field(None, pattern="^(active|archived)$")
    body: Optional[str] = None


@app.post("/api/health-issues/{issue_id}/feedback", status_code=201)
async def api_issue_feedback(issue_id: int, data: IssueFeedbackRequest):
    """Record user feedback on a health issue (false positive / confirmed).

    For false_positive: creates agent memory for detect agent + dismisses issue.
    For confirmed: archives any memory that suppresses this pattern.
    """
    from agenticops.memory.agent_memory import (
        archive_memory,
        save_memory_file,
        search_memories,
    )

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        resource_id = issue.resource_id
        title = issue.title
        description = issue.description
        severity = issue.severity
        source = issue.source

    if data.type == "false_positive":
        # Build resource pattern from issue
        parts = resource_id.split("/") if resource_id else []
        resource_pattern = f"{parts[0]}/*" if parts else ""

        # Build memory body
        body = f"{title}\n\n{description}\n\nMarked as false positive on issue I#{issue_id}."
        if data.note:
            body += f"\nUser note: {data.note}"

        # Create/update detect agent memory
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower().strip())[:50].strip("_")
        filename = f"{slug}.md" if slug else f"issue_{issue_id}_fp.md"

        filepath = save_memory_file(
            agent_name="detect",
            filename=filename,
            memory_type="feedback",
            confidence=data.confidence,
            source="user",
            body=body,
            resource_pattern=resource_pattern,
            related_issue_id=issue_id,
        )

        # Dismiss the issue
        with get_db_session() as session:
            issue = session.query(HealthIssue).filter_by(id=issue_id).first()
            if issue and issue.status not in ("resolved",):
                issue.status = "resolved"

        return {
            "status": "recorded",
            "type": "false_positive",
            "memory_file": filepath.name,
            "agent": "detect",
            "confidence": data.confidence,
        }

    elif data.type == "confirmed":
        # Search for memories that might suppress this pattern
        archived_count = 0
        matches = search_memories(title, agent_name="detect")
        for m in matches:
            if archive_memory("detect", m["filename"]):
                archived_count += 1

        return {
            "status": "recorded",
            "type": "confirmed",
            "archived_memories": archived_count,
        }


@app.get("/api/agent-memory", response_model=List[AgentMemoryResponse])
async def api_list_agent_memories(
    agent: str = "",
    status: str = "active",
):
    """List agent memories with optional filtering."""
    from agenticops.memory.agent_memory import AGENT_NAMES, list_memories

    if agent and agent not in AGENT_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid agent: {agent}")
    if status not in ("active", "archived", "all"):
        raise HTTPException(status_code=400, detail="status must be active, archived, or all")

    memories = list_memories(agent_name=agent, status_filter=status)
    return memories


@app.get("/api/agent-memory/{agent}/{filename}")
async def api_get_agent_memory(agent: str, filename: str):
    """Read a single agent memory file."""
    from agenticops.memory.agent_memory import AGENT_NAMES, _agent_dir, parse_frontmatter

    if agent not in AGENT_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid agent: {agent}")

    filepath = _agent_dir(agent) / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Memory file not found")

    raw = filepath.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)
    return {"agent": agent, "filename": filename, "frontmatter": fm, "body": body}


@app.put("/api/agent-memory/{agent}/{filename}")
async def api_update_agent_memory(agent: str, filename: str, data: AgentMemoryUpdateRequest):
    """Update an agent memory file (confidence, status, body)."""
    from agenticops.memory.agent_memory import (
        AGENT_NAMES,
        _agent_dir,
        _serialize_frontmatter,
        parse_frontmatter,
        update_memory_index,
    )

    if agent not in AGENT_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid agent: {agent}")

    filepath = _agent_dir(agent) / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Memory file not found")

    raw = filepath.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)

    if data.confidence is not None:
        fm["confidence"] = data.confidence
    if data.status is not None:
        fm["status"] = data.status
    if data.body is not None:
        body = data.body

    filepath.write_text(_serialize_frontmatter(fm, body), encoding="utf-8")
    update_memory_index(agent)

    return {"status": "updated", "agent": agent, "filename": filename}


@app.delete("/api/agent-memory/{agent}/{filename}", status_code=204)
async def api_delete_agent_memory(agent: str, filename: str):
    """Archive or delete an agent memory file."""
    from agenticops.memory.agent_memory import AGENT_NAMES, archive_memory

    if agent not in AGENT_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid agent: {agent}")

    if not archive_memory(agent, filename):
        raise HTTPException(status_code=404, detail="Memory file not found")


@app.post("/api/agent-memory/{agent}/{filename}/restore")
async def api_restore_agent_memory(agent: str, filename: str):
    """Restore an archived agent memory back to active."""
    from agenticops.memory.agent_memory import AGENT_NAMES, restore_memory

    if agent not in AGENT_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid agent: {agent}")
    if not restore_memory(agent, filename):
        raise HTTPException(status_code=404, detail="Archived memory not found")
    return {"status": "restored", "agent": agent, "filename": filename}


# ============================================================================
# Run Server Function
# ============================================================================
# Self-Improvement Metrics (MVP-2.0.0)
# ============================================================================


@app.get("/api/metrics/improvement")
async def api_improvement_metrics(days: int = 90, fingerprint: Optional[str] = None):
    """Self-improvement metrics: MTTR by pattern, first-time-fix rate, automation rate."""
    from agenticops.services.metrics_service import get_improvement_metrics

    return get_improvement_metrics(days=days, fingerprint=fingerprint)


# ============================================================================


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the web server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
