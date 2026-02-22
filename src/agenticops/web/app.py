"""Web Dashboard - React SPA + API backend."""

import os
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Request, Query, HTTPException, Body
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

from agenticops.models import (
    AWSAccount,
    AWSResource,
    Anomaly,
    HealthIssue,
    FixPlan,
    RCAResult,
    Report,
    MonitoringConfig,
    get_session,
    get_db_session,
    init_db,
)
from agenticops.config import settings

import json
import logging

from agenticops.graph.api import router as graph_router

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
    status: str = Field(..., pattern="^(open|investigating|root_cause_identified|fix_planned|fix_approved|fix_executed|resolved|acknowledged)$")
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


class HealthResponse(BaseModel):
    """Schema for health check response."""
    status: str
    version: str
    database: str
    timestamp: datetime


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
    status: Optional[str] = Field(None, pattern="^(open|investigating|root_cause_identified|fix_planned|fix_approved|fix_executed|resolved)$")
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
    status: Optional[str] = Field(None, pattern="^(draft|pending_approval|approved|rejected)$")
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



# ============================================================================
# Routes
# ============================================================================


@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    init_db()


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
    from agenticops import __version__

    db_status = "ok"
    try:
        with get_db_session() as session:
            session.execute("SELECT 1")
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="healthy" if db_status == "ok" else "degraded",
        version=__version__,
        database=db_status,
        timestamp=datetime.utcnow(),
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
    limit: int = Query(100, le=500),
    offset: int = 0,
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
    """Update anomaly status (backed by HealthIssue)."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=anomaly_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Anomaly not found")

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


# ============================================================================
# HealthIssue API Endpoints
# ============================================================================


@app.get("/api/health-issues", response_model=List[HealthIssueResponse])
async def api_list_health_issues(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    resource_id: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
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
    """Create a new health issue."""
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
        return HealthIssueResponse.model_validate(issue)


@app.put("/api/health-issues/{issue_id}", response_model=HealthIssueResponse)
async def api_update_health_issue(issue_id: int, data: HealthIssueUpdate):
    """Update a health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        update_data = data.model_dump(exclude_unset=True)

        # Auto-set resolved_at when status transitions to resolved
        if update_data.get("status") == "resolved" and issue.status != "resolved":
            update_data["resolved_at"] = datetime.utcnow()

        for key, value in update_data.items():
            setattr(issue, key, value)

        session.flush()
        return HealthIssueResponse.model_validate(issue)


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


# ============================================================================
# FixPlan API Endpoints
# ============================================================================


@app.get("/api/fix-plans", response_model=List[FixPlanResponse])
async def api_list_fix_plans(
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    health_issue_id: Optional[int] = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
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
    """Approve a fix plan."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")

        plan.status = "approved"
        plan.approved_by = approved_by
        plan.approved_at = datetime.utcnow()

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
    limit: int = Query(100, le=500),
    offset: int = 0,
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
    limit: int = Query(default=50, le=200),
    offset: int = 0,
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
    limit: int = Query(default=100, le=500),
    offset: int = 0,
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
# Dev CORS (only when AIOPS_DEV_MODE is set)
# ============================================================================

if os.getenv("AIOPS_DEV_MODE"):
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ============================================================================
# Run Server Function
# ============================================================================


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the web server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
