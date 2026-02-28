"""Web Dashboard - React SPA + API backend."""

import os
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Request, Query, HTTPException, Body
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

from sqlalchemy import func

from agenticops.models import (
    AWSAccount,
    AWSResource,
    Anomaly,
    FixExecution,
    HealthIssue,
    FixPlan,
    RCAResult,
    Report,
    MonitoringConfig,
    ChatSession,
    ChatMessage,
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


def _ensure_aws_session(region: str):
    """Ensure an AWS session exists for the given region.

    If no assumed-role session exists, inject a default boto3 session
    from environment credentials (suitable for local/internal dashboard).
    """
    import boto3
    import agenticops.tools.aws_tools as aws_tools_module

    for key in aws_tools_module._session_cache:
        if key.endswith(f":{region}"):
            return  # Already have a session for this region
    # Inject default credentials session
    session = boto3.Session(region_name=region)
    aws_tools_module._session_cache[f"web:{region}"] = session
    logger.info("Injected default AWS session for region %s", region)


# ============================================================================
# Pydantic Models for API
# ============================================================================


class AccountCreate(BaseModel):
    """Schema for creating an account."""
    name: str = Field(..., max_length=100)
    account_id: str = Field(..., max_length=12)
    role_arn: str = Field(..., max_length=200)
    external_id: Optional[str] = Field(None, max_length=100)
    regions: List[str] = Field(default_factory=lambda: ["us-east-1"])
    is_active: bool = True


class AccountUpdate(BaseModel):
    """Schema for updating an account."""
    name: Optional[str] = Field(None, max_length=100)
    role_arn: Optional[str] = Field(None, max_length=200)
    external_id: Optional[str] = Field(None, max_length=100)
    regions: Optional[List[str]] = None
    is_active: Optional[bool] = None


class AccountResponse(BaseModel):
    """Schema for account response."""
    id: int
    name: str
    account_id: str
    role_arn: str
    external_id: Optional[str]
    regions: List[str]
    is_active: bool
    created_at: datetime
    last_scanned_at: Optional[datetime]

    class Config:
        from_attributes = True


class ResourceResponse(BaseModel):
    """Schema for resource response."""
    id: int
    account_id: int
    resource_id: str
    resource_arn: Optional[str]
    resource_type: str
    resource_name: Optional[str]
    region: str
    status: str
    resource_metadata: dict
    tags: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AnomalyStatusUpdate(BaseModel):
    """Schema for updating anomaly status."""
    status: str = Field(..., pattern="^(open|investigating|acknowledged|root_cause_identified|fix_planned|fix_approved|fix_executing|fix_executed|resolved)$")
    note: Optional[str] = None


class AnomalyResponse(BaseModel):
    """Schema for anomaly response."""
    id: int
    resource_id: str
    resource_type: str
    region: str
    anomaly_type: str
    severity: str
    title: str
    description: str
    metric_name: Optional[str]
    expected_value: Optional[float]
    actual_value: Optional[float]
    deviation_percent: Optional[float]
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class RCAResponse(BaseModel):
    """Schema for RCA response."""
    id: int
    health_issue_id: int
    root_cause: str
    confidence: float
    contributing_factors: List[str]
    recommendations: List[str]
    fix_plan: dict
    fix_risk_level: str
    sop_used: Optional[str]
    similar_cases: List
    model_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class ReportResponse(BaseModel):
    """Schema for report response."""
    id: int
    report_type: str
    title: str
    summary: str
    content_markdown: str
    content_html: Optional[str]
    file_path: Optional[str]
    report_metadata: dict
    created_at: datetime

    class Config:
        from_attributes = True


class ReportGenerateRequest(BaseModel):
    """Schema for report generation request."""
    report_type: str = Field(default="daily", pattern="^(daily|inventory|anomaly)$")
    account_name: Optional[str] = None


class HealthCheckResult(BaseModel):
    """Result of a single health check."""
    status: str  # "ok", "error", "warning"
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    details: Optional[dict] = None


class HealthResponse(BaseModel):
    """Schema for health check response."""
    status: str  # "healthy", "degraded", "unhealthy"
    version: str
    timestamp: datetime
    checks: dict[str, HealthCheckResult] = Field(default_factory=dict)


# ============================================================================
# HealthIssue Pydantic Models
# ============================================================================


class HealthIssueCreate(BaseModel):
    """Schema for creating a health issue."""
    resource_id: str = Field(..., max_length=200)
    severity: str = Field(..., pattern="^(critical|high|medium|low)$")
    source: str = Field(..., max_length=50)
    title: str = Field(..., max_length=300)
    description: str
    alarm_name: Optional[str] = Field(None, max_length=200)
    metric_data: dict = Field(default_factory=dict)
    related_changes: List = Field(default_factory=list)


class HealthIssueUpdate(BaseModel):
    """Schema for updating a health issue."""
    severity: Optional[str] = Field(None, pattern="^(critical|high|medium|low)$")
    title: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(open|investigating|acknowledged|root_cause_identified|fix_planned|fix_approved|fix_executing|fix_executed|resolved)$")
    metric_data: Optional[dict] = None
    related_changes: Optional[List] = None


class HealthIssueResponse(BaseModel):
    """Schema for health issue response."""
    id: int
    resource_id: str
    severity: str
    source: str
    title: str
    description: str
    alarm_name: Optional[str]
    metric_data: dict
    related_changes: list
    status: str
    detected_at: datetime
    detected_by: str
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# FixPlan Pydantic Models
# ============================================================================


class FixPlanCreate(BaseModel):
    """Schema for creating a fix plan."""
    health_issue_id: int
    rca_result_id: int
    risk_level: str = Field(..., pattern="^(L0|L1|L2|L3)$")
    title: str = Field(..., max_length=300)
    summary: str
    steps: List = Field(default_factory=list)
    rollback_plan: dict = Field(default_factory=dict)
    estimated_impact: str = ""
    pre_checks: List = Field(default_factory=list)
    post_checks: List = Field(default_factory=list)


class FixPlanUpdate(BaseModel):
    """Schema for updating a fix plan."""
    risk_level: Optional[str] = Field(None, pattern="^(L0|L1|L2|L3)$")
    title: Optional[str] = Field(None, max_length=300)
    summary: Optional[str] = None
    steps: Optional[List] = None
    rollback_plan: Optional[dict] = None
    estimated_impact: Optional[str] = None
    pre_checks: Optional[List] = None
    post_checks: Optional[List] = None
    status: Optional[str] = Field(None, pattern="^(draft|pending_approval|approved|executing|executed|failed|rejected)$")
    approved_by: Optional[str] = Field(None, max_length=100)


class FixPlanResponse(BaseModel):
    """Schema for fix plan response."""
    id: int
    health_issue_id: int
    rca_result_id: int
    risk_level: str
    title: str
    summary: str
    steps: list
    rollback_plan: dict
    estimated_impact: str
    pre_checks: list
    post_checks: list
    status: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class FixExecutionResponse(BaseModel):
    """Schema for fix execution response."""
    id: int
    fix_plan_id: int
    health_issue_id: int
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    executed_by: str
    pre_check_results: list
    step_results: list
    post_check_results: list
    rollback_results: list
    error_message: Optional[str]
    duration_ms: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Schedule Pydantic Models
# ============================================================================


class ScheduleCreate(BaseModel):
    """Schema for creating a schedule."""
    name: str = Field(..., max_length=100)
    pipeline_name: str = Field(..., max_length=100)
    cron_expression: str = Field(..., max_length=100)
    account_name: Optional[str] = Field(None, max_length=100)
    is_enabled: bool = True
    config: dict = Field(default_factory=dict)


class ScheduleUpdate(BaseModel):
    """Schema for updating a schedule."""
    name: Optional[str] = Field(None, max_length=100)
    pipeline_name: Optional[str] = Field(None, max_length=100)
    cron_expression: Optional[str] = Field(None, max_length=100)
    account_name: Optional[str] = Field(None, max_length=100)
    is_enabled: Optional[bool] = None
    config: Optional[dict] = None


class ScheduleResponse(BaseModel):
    """Schema for schedule response."""
    id: int
    name: str
    pipeline_name: str
    cron_expression: str
    account_name: Optional[str]
    is_enabled: bool
    config: dict
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScheduleExecutionResponse(BaseModel):
    """Schema for schedule execution response."""
    id: int
    schedule_id: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    duration_ms: Optional[int]
    result: dict
    error: Optional[str]

    class Config:
        from_attributes = True


# ============================================================================
# Notification Pydantic Models
# ============================================================================


class NotificationChannelCreate(BaseModel):
    """Schema for creating a notification channel."""
    name: str = Field(..., max_length=100)
    channel_type: str = Field(..., pattern="^(slack|email|sns|webhook)$")
    config: dict = Field(default_factory=dict)
    severity_filter: List[str] = Field(default_factory=list)
    is_enabled: bool = True


class NotificationChannelUpdate(BaseModel):
    """Schema for updating a notification channel."""
    name: Optional[str] = Field(None, max_length=100)
    channel_type: Optional[str] = Field(None, pattern="^(slack|email|sns|webhook)$")
    config: Optional[dict] = None
    severity_filter: Optional[List[str]] = None
    is_enabled: Optional[bool] = None


class NotificationChannelResponse(BaseModel):
    """Schema for notification channel response."""
    id: int
    name: str
    channel_type: str
    config: dict
    severity_filter: list
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NotificationLogResponse(BaseModel):
    """Schema for notification log response."""
    id: int
    channel_id: int
    subject: str
    body: str
    severity: Optional[str]
    status: str
    error: Optional[str]
    sent_at: datetime

    class Config:
        from_attributes = True


class NotificationSendRequest(BaseModel):
    """Schema for sending a test notification."""
    subject: str = "Test notification from AgenticOps"
    body: str = "This is a test notification."
    severity: Optional[str] = "low"


# ============================================================================
# Chat Pydantic Models
# ============================================================================


class ChatSessionCreate(BaseModel):
    name: Optional[str] = None


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    detail_level: Optional[str] = Field(None, description="Agent output detail: concise, medium, or detailed")


class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    tool_calls: Optional[list] = None
    token_usage: Optional[dict] = None
    attachments: Optional[list] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatSessionResponse(BaseModel):
    id: int
    session_id: str
    name: str
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class ChatSessionDetail(ChatSessionResponse):
    messages: List[ChatMessageResponse] = []


# ============================================================================
# Auth Pydantic Models
# ============================================================================


class LoginRequest(BaseModel):
    """Schema for login request."""
    email: str
    password: str


class LoginResponse(BaseModel):
    """Schema for login response."""
    token: str
    user_id: int
    email: str
    name: Optional[str]
    is_admin: bool
    expires_at: datetime


class RegisterRequest(BaseModel):
    """Schema for user registration."""
    email: str
    password: str
    name: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for user response."""
    id: int
    email: str
    name: Optional[str]
    is_admin: bool
    permissions: List[str]
    last_login_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreate(BaseModel):
    """Schema for creating an API key."""
    name: str
    permissions: List[str] = ["read"]
    expires_days: Optional[int] = None


class APIKeyResponse(BaseModel):
    """Schema for API key response."""
    id: int
    name: str
    key_prefix: str
    permissions: List[str]
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreatedResponse(BaseModel):
    """Schema for newly created API key (includes the full key)."""
    id: int
    name: str
    key: str  # Full key - only shown once!
    permissions: List[str]
    expires_at: Optional[datetime]


class PasswordChangeRequest(BaseModel):
    """Schema for password change."""
    old_password: str
    new_password: str

# Initialize FastAPI app
app = FastAPI(
    title="AgenticAIOps Dashboard",
    description="Agent-First Cloud Observability Platform",
    version="0.1.0",
)

# Graph API router
app.include_router(graph_router)

# Chat session manager
_chat_sessions = ChatSessionManager(ttl_minutes=30)
_executor_service = ExecutorService(poll_interval=settings.executor_poll_interval)



# ============================================================================
# Routes
# ============================================================================


@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    init_db()
    _chat_sessions.start_cleanup()
    _executor_service.start()


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    _chat_sessions.stop_cleanup()
    _executor_service.stop()


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


@app.get("/network")
async def network_redirect():
    return RedirectResponse(url="/app/network", status_code=302)


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
# Network API Endpoints
# ============================================================================


@app.get("/api/network/vpcs")
async def api_list_vpcs(request: Request, region: str = Query("us-east-1")):
    """List VPCs in a region (live AWS API call)."""
    try:
        _ensure_aws_session(region)
        from agenticops.tools.network_tools import describe_vpcs

        result = describe_vpcs(region=region)
        vpcs = json.loads(result)
        return JSONResponse({"region": region, "vpcs": vpcs})
    except Exception as e:
        logger.exception("Failed to list VPCs")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/network/region-topology")
async def api_region_topology(request: Request, region: str = Query("us-east-1")):
    """Get region-level topology: VPCs, Transit Gateways, Peering connections."""
    try:
        _ensure_aws_session(region)
        from agenticops.tools.network_tools import describe_region_topology

        result = describe_region_topology(region=region)
        topology = json.loads(result)
        return JSONResponse(topology)
    except Exception as e:
        logger.exception("Failed to get region topology")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/network/vpc-topology")
async def api_vpc_topology(
    request: Request,
    region: str = Query(...),
    vpc_id: str = Query(...),
):
    """Analyze VPC topology (live AWS API call)."""
    try:
        _ensure_aws_session(region)
        from agenticops.tools.network_tools import analyze_vpc_topology

        result = analyze_vpc_topology(region=region, vpc_id=vpc_id)
        topology = json.loads(result)
        return JSONResponse(topology)
    except Exception as e:
        logger.exception("Failed to analyze VPC topology")
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================================
# API Endpoints
# ============================================================================


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
            session.execute("SELECT 1")
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
        sts = boto3.client("sts", region_name=settings.bedrock_region)
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
        timestamp=datetime.utcnow(),
        checks=checks,
    )


@app.get("/api/stats")
async def api_stats():
    """API endpoint for dashboard stats."""
    with get_db_session() as session:
        return {
            "total_resources": session.query(AWSResource).count(),
            "open_anomalies": session.query(HealthIssue).filter_by(status="open").count(),
            "critical_anomalies": session.query(HealthIssue).filter_by(severity="critical", status="open").count(),
            "total_accounts": session.query(AWSAccount).count(),
        }


# ============================================================================
# Account API Endpoints
# ============================================================================


@app.get("/api/accounts", response_model=List[AccountResponse])
async def api_list_accounts():
    """List all AWS accounts."""
    with get_db_session() as session:
        accounts = session.query(AWSAccount).all()
        return [AccountResponse.model_validate(a) for a in accounts]


@app.get("/api/accounts/{account_id}", response_model=AccountResponse)
async def api_get_account(account_id: int):
    """Get account by ID."""
    with get_db_session() as session:
        account = session.query(AWSAccount).filter_by(id=account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return AccountResponse.model_validate(account)


@app.post("/api/accounts", response_model=AccountResponse, status_code=201)
async def api_create_account(account: AccountCreate):
    """Create a new AWS account."""
    with get_db_session() as session:
        # Check if account name or account_id already exists
        existing = session.query(AWSAccount).filter(
            (AWSAccount.name == account.name) | (AWSAccount.account_id == account.account_id)
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Account name or ID already exists")

        db_account = AWSAccount(
            name=account.name,
            account_id=account.account_id,
            role_arn=account.role_arn,
            external_id=account.external_id,
            regions=account.regions,
            is_active=account.is_active,
        )
        session.add(db_account)
        session.flush()  # Get the ID
        return AccountResponse.model_validate(db_account)


@app.put("/api/accounts/{account_id}", response_model=AccountResponse)
async def api_update_account(account_id: int, account: AccountUpdate):
    """Update an existing AWS account."""
    with get_db_session() as session:
        db_account = session.query(AWSAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Account not found")

        update_data = account.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_account, key, value)

        session.flush()
        return AccountResponse.model_validate(db_account)


@app.delete("/api/accounts/{account_id}", status_code=204)
async def api_delete_account(account_id: int):
    """Delete an AWS account."""
    with get_db_session() as session:
        db_account = session.query(AWSAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Account not found")

        session.delete(db_account)


# ============================================================================
# Resource API Endpoints
# ============================================================================


@app.get("/api/resources", response_model=List[ResourceResponse])
async def api_list_resources(
    resource_type: Optional[str] = Query(None, alias="type"),
    region: Optional[str] = None,
    account_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """List resources with filtering."""
    with get_db_session() as session:
        query = session.query(AWSResource)

        if resource_type:
            query = query.filter_by(resource_type=resource_type)
        if region:
            query = query.filter_by(region=region)
        if account_id:
            query = query.filter_by(account_id=account_id)
        if status:
            query = query.filter_by(status=status)

        resources = query.offset(offset).limit(limit).all()
        return [ResourceResponse.model_validate(r) for r in resources]


@app.get("/api/resources/type-counts")
async def api_resource_type_counts():
    """Resource counts grouped by type."""
    with get_db_session() as session:
        rows = (
            session.query(AWSResource.resource_type, func.count())
            .group_by(AWSResource.resource_type)
            .order_by(func.count().desc())
            .all()
        )
        return {rtype: count for rtype, count in rows}


@app.get("/api/resources/{resource_id}", response_model=ResourceResponse)
async def api_get_resource(resource_id: int):
    """Get resource by ID."""
    with get_db_session() as session:
        resource = session.query(AWSResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        return ResourceResponse.model_validate(resource)


# ============================================================================
# Anomaly API Endpoints (Legacy — backed by HealthIssue)
# ============================================================================


def _health_issue_to_anomaly_response(issue: HealthIssue) -> AnomalyResponse:
    """Map a HealthIssue to the legacy AnomalyResponse format."""
    metric_data = issue.metric_data or {}
    return AnomalyResponse(
        id=issue.id,
        resource_id=issue.resource_id,
        resource_type=metric_data.get("resource_type", "unknown"),
        region=metric_data.get("region", "unknown"),
        anomaly_type=issue.source,
        severity=issue.severity,
        title=issue.title,
        description=issue.description,
        metric_name=metric_data.get("metric_name"),
        expected_value=metric_data.get("expected_value"),
        actual_value=metric_data.get("actual_value"),
        deviation_percent=metric_data.get("deviation_percent"),
        status=issue.status,
        detected_at=issue.detected_at,
        resolved_at=issue.resolved_at,
    )


@app.get("/api/anomalies", response_model=List[AnomalyResponse])
async def api_list_anomalies(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
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
        if resource_type:
            query = query.filter(
                HealthIssue.metric_data["resource_type"].as_string() == resource_type
            )

        issues = query.offset(offset).limit(limit).all()
        return [_health_issue_to_anomaly_response(i) for i in issues]


@app.get("/api/anomalies/{anomaly_id}", response_model=AnomalyResponse)
async def api_get_anomaly(anomaly_id: int):
    """Get anomaly by ID (backed by HealthIssue)."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=anomaly_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Anomaly not found")
        return _health_issue_to_anomaly_response(issue)


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
            issue.resolved_at = datetime.utcnow()

        session.flush()
        return _health_issue_to_anomaly_response(issue)


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
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = 0,
):
    """List issues."""
    return await api_list_anomalies(severity, status, resource_type, limit, offset)


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

        issues = query.offset(offset).limit(limit).all()
        return [HealthIssueResponse.model_validate(i) for i in issues]


@app.get("/api/health-issues/{issue_id}", response_model=HealthIssueResponse)
async def api_get_health_issue(issue_id: int):
    """Get health issue by ID."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")
        return HealthIssueResponse.model_validate(issue)


@app.post("/api/health-issues", response_model=HealthIssueResponse, status_code=201)
async def api_create_health_issue(data: HealthIssueCreate):
    """Create a new health issue. Auto-triggers RCA in background."""
    with get_db_session() as session:
        issue = HealthIssue(
            resource_id=data.resource_id,
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
            update_data["resolved_at"] = datetime.utcnow()

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
# FixPlan API Endpoints
# ============================================================================


@app.get("/api/fix-plans", response_model=List[FixPlanResponse])
async def api_list_fix_plans(
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    health_issue_id: Optional[int] = None,
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

        plans = query.offset(offset).limit(limit).all()
        return [FixPlanResponse.model_validate(p) for p in plans]


@app.get("/api/fix-plans/{plan_id}", response_model=FixPlanResponse)
async def api_get_fix_plan(plan_id: int):
    """Get fix plan by ID."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        return FixPlanResponse.model_validate(plan)


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
        plan.approved_at = datetime.utcnow()

        # Sync HealthIssue status
        issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first()
        if issue:
            issue.status = "fix_approved"

        session.flush()
        return FixPlanResponse.model_validate(plan)


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
async def api_list_sops():
    """List all SOPs in the knowledge base."""
    from agenticops.tools.kb_tools import _parse_frontmatter

    sops = []
    sops_dir = settings.sops_dir
    if sops_dir.exists():
        for f in sorted(sops_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8")
                metadata, body = _parse_frontmatter(content)
                sops.append({
                    "filename": f.name,
                    "path": str(f),
                    "resource_type": metadata.get("resource_type", ""),
                    "issue_pattern": metadata.get("issue_pattern", ""),
                    "severity": metadata.get("severity", ""),
                    "last_updated": metadata.get("last_updated", ""),
                    "size_bytes": f.stat().st_size,
                    "preview": body[:200] if body else "",
                })
            except Exception as e:
                sops.append({"filename": f.name, "error": str(e)})
    return {"count": len(sops), "sops": sops}


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

    return {
        "sop_count": sop_count,
        "case_count": case_count,
        "embedding_status": embedding_status,
        "vector_count": vector_count,
        "rag_pipeline_enabled": settings.rag_pipeline_enabled,
        "sop_similarity_threshold": settings.sop_similarity_threshold,
    }


# ============================================================================
# Report API Endpoints
# ============================================================================


@app.get("/api/reports", response_model=List[ReportResponse])
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
        return [ReportResponse.model_validate(r) for r in reports]


@app.get("/api/reports/{report_id}", response_model=ReportResponse)
async def api_get_report(report_id: int):
    """Get report by ID."""
    with get_db_session() as session:
        report = session.query(Report).filter_by(id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return ReportResponse.model_validate(report)


@app.post("/api/reports/generate", response_model=ReportResponse, status_code=201)
async def api_generate_report(request: ReportGenerateRequest):
    """Generate a new report."""
    from agenticops.report import ReportGenerator

    with get_db_session() as session:
        # Get account if specified
        account = None
        if request.account_name:
            account = session.query(AWSAccount).filter_by(name=request.account_name).first()
            if not account:
                raise HTTPException(status_code=404, detail="Account not found")
        else:
            account = session.query(AWSAccount).filter_by(is_active=True).first()

        generator = ReportGenerator(account)

        if request.report_type == "daily":
            content = generator.generate_daily_report()
        elif request.report_type == "inventory":
            content = generator.generate_inventory_report()
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


# ============================================================================
# Authentication API Endpoints
# ============================================================================


@app.post("/api/auth/register", response_model=UserResponse, status_code=201)
async def api_register(request_data: RegisterRequest):
    """Register a new user."""
    from agenticops.auth import AuthService

    try:
        user = AuthService.create_user(
            email=request_data.email,
            password=request_data.password,
            name=request_data.name,
        )
        return UserResponse.model_validate(user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login", response_model=LoginResponse)
async def api_login(request: Request, request_data: LoginRequest):
    """Login and get a session token."""
    from agenticops.auth import AuthService
    from datetime import timedelta

    user = AuthService.authenticate(request_data.email, request_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Get client info
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Create session
    token = AuthService.create_session(user.id, ip_address, user_agent)

    return LoginResponse(
        token=token,
        user_id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        expires_at=datetime.utcnow() + timedelta(hours=AuthService.SESSION_DURATION_HOURS),
    )


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    """Logout and invalidate the session."""
    from agenticops.auth import AuthService

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        AuthService.invalidate_session(token)

    return {"message": "Logged out successfully"}


@app.get("/api/users/me", response_model=UserResponse)
async def api_get_current_user(request: Request):
    """Get the currently authenticated user."""
    from agenticops.auth import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Extract credentials from header
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return UserResponse.model_validate(user)


@app.put("/api/users/me/password")
async def api_change_password(request: Request, request_data: PasswordChangeRequest):
    """Change the current user's password."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not AuthService.update_password(user.id, request_data.old_password, request_data.new_password):
        raise HTTPException(status_code=400, detail="Invalid current password")

    return {"message": "Password changed successfully"}


@app.post("/api/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
async def api_create_api_key(request: Request, request_data: APIKeyCreate):
    """Create a new API key for the current user."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Create API key
    key = AuthService.create_api_key(
        user_id=user.id,
        name=request_data.name,
        permissions=request_data.permissions,
        expires_days=request_data.expires_days,
    )

    # Get the created key info
    with get_db_session() as session:
        from agenticops.auth.models import APIKey
        api_key = session.query(APIKey).filter_by(user_id=user.id).order_by(APIKey.created_at.desc()).first()

        return APIKeyCreatedResponse(
            id=api_key.id,
            name=api_key.name,
            key=key,  # Full key - only shown once!
            permissions=api_key.permissions,
            expires_at=api_key.expires_at,
        )


@app.get("/api/api-keys", response_model=List[APIKeyResponse])
async def api_list_api_keys(request: Request):
    """List API keys for the current user."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    keys = AuthService.list_api_keys(user.id)
    return [APIKeyResponse.model_validate(k) for k in keys]


@app.delete("/api/api-keys/{key_id}", status_code=204)
async def api_revoke_api_key(request: Request, key_id: int):
    """Revoke an API key."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not AuthService.revoke_api_key(key_id, user.id):
        raise HTTPException(status_code=404, detail="API key not found")


# ============================================================================
# Audit API Endpoints
# ============================================================================


class AuditLogResponse(BaseModel):
    """Schema for audit log response."""
    id: int
    timestamp: datetime
    user_id: Optional[int]
    user_email: Optional[str]
    action: str
    entity_type: str
    entity_id: str
    entity_name: Optional[str]
    details: dict
    old_values: Optional[dict]
    new_values: Optional[dict]
    ip_address: Optional[str]

    class Config:
        from_attributes = True


@app.get("/api/audit", response_model=List[AuditLogResponse])
async def api_list_audit_logs(
    request: Request,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[int] = None,
    hours: int = Query(24, le=720),
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """List audit log entries (requires admin)."""
    from agenticops.auth import get_current_user
    from agenticops.audit import AuditService
    from fastapi.security import HTTPAuthorizationCredentials
    from datetime import timedelta

    # Get current user (admin required)
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    start_time = datetime.utcnow() - timedelta(hours=hours)

    logs = AuditService.query(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        start_time=start_time,
        limit=limit,
        offset=offset,
    )

    return [AuditLogResponse.model_validate(log) for log in logs]


@app.get("/api/audit/entity/{entity_type}/{entity_id}", response_model=List[AuditLogResponse])
async def api_get_entity_audit(
    request: Request,
    entity_type: str,
    entity_id: str,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """Get audit history for a specific entity."""
    from agenticops.auth import get_current_user
    from agenticops.audit import AuditService
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(request, credentials)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    else:
        raise HTTPException(status_code=401, detail="Authentication required")

    logs = AuditService.get_entity_history(
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )

    return [AuditLogResponse.model_validate(log) for log in logs]


@app.get("/api/audit/stats")
async def api_get_audit_stats(request: Request, hours: int = Query(24, le=720)):
    """Get audit statistics (requires admin)."""
    from agenticops.auth import get_current_user
    from agenticops.audit import AuditService
    from fastapi.security import HTTPAuthorizationCredentials
    from datetime import timedelta

    # Get current user (admin required)
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    start_time = datetime.utcnow() - timedelta(hours=hours)

    return {
        "period_hours": hours,
        "total_events": AuditService.count_actions(start_time=start_time),
        "creates": AuditService.count_actions(action="create", start_time=start_time),
        "updates": AuditService.count_actions(action="update", start_time=start_time),
        "deletes": AuditService.count_actions(action="delete", start_time=start_time),
        "logins": AuditService.count_actions(action="login", start_time=start_time),
        "login_failures": AuditService.count_actions(action="login_failed", start_time=start_time),
    }


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
    from agenticops.scheduler.scheduler import Schedule

    # Validate cron expression
    try:
        from croniter import croniter
        croniter(data.cron_expression)
    except (ImportError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {e}")

    with get_db_session() as session:
        existing = session.query(Schedule).filter_by(name=data.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Schedule name already exists")

        schedule = Schedule(
            name=data.name,
            pipeline_name=data.pipeline_name,
            cron_expression=data.cron_expression,
            account_name=data.account_name,
            is_enabled=data.is_enabled,
            config=data.config,
        )
        session.add(schedule)
        session.flush()
        return ScheduleResponse.model_validate(schedule)


@app.put("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
async def api_update_schedule(schedule_id: int, data: ScheduleUpdate):
    """Update a schedule."""
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        update_data = data.model_dump(exclude_unset=True)

        # Validate cron if being updated
        if "cron_expression" in update_data:
            try:
                from croniter import croniter
                croniter(update_data["cron_expression"])
            except (ImportError, ValueError) as e:
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


@app.post("/api/schedules/{schedule_id}/run", response_model=ScheduleExecutionResponse)
async def api_run_schedule(schedule_id: int):
    """Run a schedule immediately."""
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        # Create execution record
        execution = ScheduleExecution(
            schedule_id=schedule_id,
            status="running",
        )
        session.add(execution)
        session.flush()

        # Update schedule last_run_at
        schedule.last_run_at = datetime.utcnow()

        try:
            from agenticops.scheduler.scheduler import Scheduler
            scheduler = Scheduler()
            result = scheduler.run_pipeline(schedule.pipeline_name, schedule.account_name, schedule.config)

            execution.status = "completed"
            execution.completed_at = datetime.utcnow()
            execution.duration_ms = int((execution.completed_at - execution.started_at).total_seconds() * 1000)
            execution.result = {"output": str(result)} if result else {}
        except Exception as e:
            execution.status = "failed"
            execution.completed_at = datetime.utcnow()
            execution.duration_ms = int((execution.completed_at - execution.started_at).total_seconds() * 1000)
            execution.error = str(e)

        session.flush()
        return ScheduleExecutionResponse.model_validate(execution)


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


# ============================================================================
# Notification API Endpoints
# ============================================================================


@app.get("/api/notifications/channels", response_model=List[NotificationChannelResponse])
async def api_list_notification_channels():
    """List notification channels."""
    from agenticops.notify.notifier import NotificationChannel

    with get_db_session() as session:
        channels = session.query(NotificationChannel).order_by(NotificationChannel.created_at.desc()).all()
        return [NotificationChannelResponse.model_validate(c) for c in channels]


@app.get("/api/notifications/channels/{channel_id}", response_model=NotificationChannelResponse)
async def api_get_notification_channel(channel_id: int):
    """Get notification channel by ID."""
    from agenticops.notify.notifier import NotificationChannel

    with get_db_session() as session:
        channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Notification channel not found")
        return NotificationChannelResponse.model_validate(channel)


@app.post("/api/notifications/channels", response_model=NotificationChannelResponse, status_code=201)
async def api_create_notification_channel(data: NotificationChannelCreate):
    """Create a new notification channel."""
    from agenticops.notify.notifier import NotificationChannel

    with get_db_session() as session:
        existing = session.query(NotificationChannel).filter_by(name=data.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Channel name already exists")

        channel = NotificationChannel(
            name=data.name,
            channel_type=data.channel_type,
            config=data.config,
            severity_filter=data.severity_filter,
            is_enabled=data.is_enabled,
        )
        session.add(channel)
        session.flush()
        return NotificationChannelResponse.model_validate(channel)


@app.put("/api/notifications/channels/{channel_id}", response_model=NotificationChannelResponse)
async def api_update_notification_channel(channel_id: int, data: NotificationChannelUpdate):
    """Update a notification channel."""
    from agenticops.notify.notifier import NotificationChannel

    with get_db_session() as session:
        channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Notification channel not found")

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(channel, key, value)

        session.flush()
        return NotificationChannelResponse.model_validate(channel)


@app.delete("/api/notifications/channels/{channel_id}", status_code=204)
async def api_delete_notification_channel(channel_id: int):
    """Delete a notification channel."""
    from agenticops.notify.notifier import NotificationChannel

    with get_db_session() as session:
        channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Notification channel not found")
        session.delete(channel)


@app.post("/api/notifications/channels/{channel_id}/test")
async def api_test_notification_channel(channel_id: int, data: NotificationSendRequest):
    """Send a test notification through a channel."""
    from agenticops.notify.notifier import NotificationChannel, NotificationLog, Notifier

    with get_db_session() as session:
        channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Notification channel not found")

        try:
            notifier = Notifier()
            notifier.send(
                channel_id=channel_id,
                subject=data.subject,
                body=data.body,
                severity=data.severity,
            )
            return {"status": "sent", "channel": channel.name}
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"status": "failed", "channel": channel.name, "error": str(e)},
            )


@app.get("/api/notifications/logs", response_model=List[NotificationLogResponse])
async def api_list_notification_logs(
    channel_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """List notification logs."""
    from agenticops.notify.notifier import NotificationLog

    with get_db_session() as session:
        query = session.query(NotificationLog).order_by(NotificationLog.sent_at.desc())

        if channel_id:
            query = query.filter_by(channel_id=channel_id)
        if status:
            query = query.filter_by(status=status)

        logs = query.offset(offset).limit(limit).all()
        return [NotificationLogResponse.model_validate(log) for log in logs]


# ============================================================================
# Chat API Endpoints
# ============================================================================


@app.post("/api/chat/sessions", response_model=ChatSessionResponse, status_code=201)
async def api_create_chat_session(payload: ChatSessionCreate):
    sid = str(uuid.uuid4())
    name = payload.name or f"Chat {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    with get_db_session() as db:
        row = ChatSession(session_id=sid, name=name)
        db.add(row)
        db.flush()
        return ChatSessionResponse(
            id=row.id, session_id=row.session_id, name=row.name,
            created_at=row.created_at, updated_at=row.updated_at,
            last_activity_at=row.last_activity_at, message_count=0,
        )


@app.get("/api/chat/sessions", response_model=List[ChatSessionResponse])
async def api_list_chat_sessions(
    limit: int = Query(default=50, le=100),
):
    with get_db_session() as db:
        rows = (
            db.query(ChatSession)
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
            ))
        return result


@app.get("/api/chat/sessions/{session_id}", response_model=ChatSessionDetail)
async def api_get_chat_session(session_id: str):
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == row.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        return ChatSessionDetail(
            id=row.id, session_id=row.session_id, name=row.name,
            created_at=row.created_at, updated_at=row.updated_at,
            last_activity_at=row.last_activity_at,
            message_count=len(msgs),
            messages=[ChatMessageResponse(
                id=m.id, role=m.role, content=m.content,
                tool_calls=m.tool_calls, token_usage=m.token_usage,
                created_at=m.created_at,
            ) for m in msgs],
        )


@app.delete("/api/chat/sessions/{session_id}", status_code=204)
async def api_delete_chat_session(session_id: str):
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
        db.delete(row)
    _chat_sessions.remove(session_id)


@app.post("/api/chat/sessions/{session_id}/messages")
async def api_send_chat_message(session_id: str, request: Request):
    """Send a message, optionally with a file attachment.

    Accepts:
    - application/json: {"content": "message text"}
    - multipart/form-data: content (text field) + file (optional)
    """
    from agenticops.chat.preprocessor import preprocess_message

    content_type = request.headers.get("content-type", "")
    file_contents: list[tuple[str, str]] = []
    file_images: list[tuple[str, bytes, str]] = []
    file_documents: list[tuple[str, bytes, str, str]] = []
    attachments: list[dict] | None = None

    detail_level_req: Optional[str] = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        text_content = str(form.get("content", "")).strip()
        detail_level_req = str(form.get("detail_level", "")).strip() or None
        upload = form.get("file")

        if upload and hasattr(upload, "filename") and upload.filename:
            from agenticops.chat.file_reader import (
                is_image_file, is_document_file,
                read_upload_image_bytes, read_upload_document_bytes,
                read_upload_bytes,
            )
            raw = await upload.read()

            if is_image_file(upload.filename):
                img_bytes, fmt, error = read_upload_image_bytes(upload.filename, raw)
                if error:
                    raise HTTPException(400, error)
                if img_bytes and fmt:
                    file_images.append((upload.filename, img_bytes, fmt))
                    attachments = [{"filename": upload.filename, "size": len(raw), "type": "image"}]
            elif is_document_file(upload.filename):
                doc_bytes, fmt, name, error = read_upload_document_bytes(upload.filename, raw)
                if error:
                    raise HTTPException(400, error)
                if doc_bytes and fmt and name:
                    file_documents.append((upload.filename, doc_bytes, fmt, name))
                    attachments = [{"filename": upload.filename, "size": len(raw), "type": "document"}]
            else:
                file_text, error = read_upload_bytes(upload.filename, raw)
                if error:
                    raise HTTPException(400, error)
                if file_text:
                    file_contents.append((upload.filename, file_text))
                    attachments = [{"filename": upload.filename, "size": len(raw), "type": "text"}]

        has_file = file_contents or file_images or file_documents
        if not text_content and not has_file:
            raise HTTPException(400, "Message content or file required")
        if not text_content:
            text_content = f"Please analyze the attached file: {upload.filename}"
        user_content = text_content
    else:
        payload = ChatMessageCreate(**(await request.json()))
        user_content = payload.content
        detail_level_req = payload.detail_level

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
        row.last_activity_at = datetime.utcnow()
        db_session_pk = row.id

    async def _generate():
        # Set detail level for this request if provided
        if detail_level_req:
            from agenticops.config import VALID_DETAIL_LEVELS, set_detail_level
            if detail_level_req in VALID_DETAIL_LEVELS:
                set_detail_level(detail_level_req)
        agent = _chat_sessions.get_or_create(session_id)
        accumulated = ""
        tool_calls = []
        input_tokens = 0
        output_tokens = 0
        try:
            async for event in agent.stream_async(enriched_content):
                ev = event if isinstance(event, dict) else event.as_dict() if hasattr(event, "as_dict") else {}
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
                    if hasattr(res, "metrics"):
                        inv = getattr(res.metrics, "latest_agent_invocation", None)
                        if inv and hasattr(inv, "usage"):
                            input_tokens = inv.usage.get("inputTokens", 0)
                            output_tokens = inv.usage.get("outputTokens", 0)
                    # If accumulated text is empty, extract from result
                    if not accumulated and hasattr(res, "__str__"):
                        accumulated = str(res)

            # Mark tools done
            for t in tool_calls:
                t["status"] = "done"
                yield {"event": "tool_end", "data": json.dumps({"name": t["name"]})}

            # Persist assistant message
            with get_db_session() as db:
                db.add(ChatMessage(
                    session_id=db_session_pk,
                    role="assistant",
                    content=accumulated,
                    tool_calls=tool_calls if tool_calls else None,
                    token_usage={"input": input_tokens, "output": output_tokens} if input_tokens else None,
                ))

            yield {
                "event": "done",
                "data": json.dumps({
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }),
            }
        except Exception as e:
            logger.exception("Chat stream error for session %s", session_id)
            yield {"event": "error", "data": json.dumps({"message": str(e)})}

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
    """SPA fallback — serve index.html for all /app/* routes."""
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
# Run Server Function
# ============================================================================


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the web server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
