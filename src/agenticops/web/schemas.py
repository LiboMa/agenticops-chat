"""Pydantic request/response schemas for the AgenticOps Web API.

Mechanically extracted from app.py (no logic change) to shrink app.py and give
routers a dependency-leaf module to import from (avoids app<->router import cycle).
"""

from datetime import datetime
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccountCreate(BaseModel):
    """Schema for creating a cloud account."""
    name: str = Field(..., max_length=100)
    provider: str = Field(..., pattern="^(aws|azure|gcp|alicloud)$")
    credential_source_type: str = Field(default="environment", pattern="^(environment|assume_role|profile|static_keys)$")
    credentials: dict = Field(default_factory=dict)
    regions: List[str] = Field(default_factory=list)
    labels: dict = Field(default_factory=dict)
    is_enabled: bool = True


class AccountUpdate(BaseModel):
    """Schema for updating a cloud account."""
    name: Optional[str] = Field(None, max_length=100)
    credential_source_type: Optional[str] = Field(None, pattern="^(environment|assume_role|profile|static_keys)$")
    credentials: Optional[dict] = None
    regions: Optional[List[str]] = None
    labels: Optional[dict] = None
    is_enabled: Optional[bool] = None


REDACTED_KEYS = {"client_secret", "access_key_secret", "secret_key", "service_account_key", "secret_access_key", "access_key_id", "session_token", "_encrypted"}


class AccountResponse(BaseModel):
    """Schema for account response."""
    id: int
    name: str
    provider: str
    credential_source_type: str = "environment"
    credentials: dict
    regions: List[str]
    labels: dict
    is_enabled: bool
    created_at: datetime
    last_scanned_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def redact_secrets(self):
        if self.credentials:
            self.credentials = {
                k: "***REDACTED***" if k in REDACTED_KEYS else v
                for k, v in self.credentials.items()
            }
        return self


class ResourceResponse(BaseModel):
    """Schema for resource response."""
    id: int
    account_id: int
    provider: str = "aws"
    resource_id: str
    resource_arn: Optional[str] = None
    resource_type: str
    resource_name: Optional[str] = None
    region: str
    status: str
    resource_metadata: dict = Field(default_factory=dict)
    tags: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    scanned_at: Optional[datetime] = None
    absent_since: Optional[datetime] = None  # set when the latest complete scan no longer saw the row
    # The list's health column (MVP-2.7.0 S4): open anchored issues + unknown|notice|warning|critical
    open_issues: int = 0
    health: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_resource(cls, r) -> "ResourceResponse":
        """Build response from CloudResource, mapping field names."""
        raw = r.raw_data if isinstance(getattr(r, "raw_data", None), dict) else {}
        return cls(
            id=r.id,
            account_id=r.account_id,
            provider=getattr(r, "provider", "aws"),
            resource_id=r.resource_id,
            resource_arn=raw.get("Arn") or raw.get("arn") or getattr(r, "resource_arn", None),
            resource_type=r.resource_type,
            resource_name=getattr(r, "name", None) or getattr(r, "resource_name", None),
            region=r.region,
            status=r.status,
            resource_metadata=raw or getattr(r, "resource_metadata", {}),
            tags=r.tags if isinstance(r.tags, dict) else {},
            created_at=r.created_at,
            updated_at=r.updated_at,
            scanned_at=getattr(r, "scanned_at", None),
            absent_since=getattr(r, "absent_since", None),
        )


class AnomalyStatusUpdate(BaseModel):
    """Schema for updating anomaly status."""
    status: str = Field(..., pattern="^(open|investigating|acknowledged|root_cause_identified|fix_planned|fix_approved|fix_executing|fix_executed|resolved|dismissed)$")
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
    account_id: Optional[int] = None
    account_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


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
    # RCA quality (MVP-2.2.0)
    evidence: List = Field(default_factory=list)
    evidence_verified: Optional[bool] = None
    critic_verdict: Optional[str] = None
    critic_notes: Optional[str] = None
    human_verdict: Optional[str] = None
    # Root-cause location (MVP-2.6.1)
    location: Optional[dict] = None
    location_status: Optional[str] = None
    location_build_id: Optional[int] = None
    location_verdict: Optional[str] = None
    location_verdict_by: Optional[str] = None
    location_verdict_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ReportResponse(BaseModel):
    """Schema for report response."""
    id: int
    report_type: str
    title: str
    summary: str
    content_markdown: str
    content_html: Optional[str]
    file_path: Optional[str]
    download_url: Optional[str] = None
    report_metadata: dict
    created_at: datetime
    # MVP-2.7.0 S6: the content a rendering is made from, and who may see it (services/report_access)
    content_version: int = 1
    content_hash: Optional[str] = None
    source_language: Optional[str] = None
    visibility: str = "workspace"
    owned_by_me: bool = False
    language_status: dict = Field(default_factory=dict)   # {zh, en} → rendering status (S6)

    model_config = ConfigDict(from_attributes=True)


class TranslationRequest(BaseModel):
    """Prepare renderings of one content version (MVP-2.7.0 S6): ready ones are returned, the rest are queued."""
    model_config = ConfigDict(extra="forbid")
    source_version: int = Field(..., ge=1)
    languages: List[Literal["zh", "en"]] = Field(..., min_length=1, max_length=2)


class ReportGenerateRequest(BaseModel):
    """Schema for report generation request."""
    report_type: str = Field(default="daily", pattern="^(daily|inventory|anomaly|newsletter|conversation|incident|security-review)$")
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


# ============================================================================
# Alert Event Pydantic Models (Webhooks)
# ============================================================================


class AlertEventResponse(BaseModel):
    """Schema for alert event response."""
    id: int
    source: str
    external_id: str
    severity: str
    title: str
    description: str
    resource_hint: str
    health_issue_id: Optional[int]
    status: str
    received_at: datetime
    raw_payload: dict

    model_config = ConfigDict(from_attributes=True)


class HealthIssueCreate(BaseModel):
    """Schema for creating a health issue."""
    resource_id: str = Field(..., max_length=500)
    provider: Optional[str] = Field("aws", pattern="^(aws|azure|gcp|alicloud)$")
    severity: str = Field(..., pattern="^(critical|high|medium|low)$")
    source: str = Field(..., max_length=50)
    title: str = Field(..., max_length=300)
    description: str
    alarm_name: Optional[str] = Field(None, max_length=200)
    metric_data: dict = Field(default_factory=dict)
    related_changes: List = Field(default_factory=list)
    issue_type: Optional[str] = Field(None, max_length=40)


class SignalResponse(BaseModel):
    """Schema for a Signal (gated alert_events row)."""
    id: int
    received_at: datetime
    kind: str = "alert"
    source: str
    title: str
    severity: str
    issue_type: str = "other"
    resource_id: str = ""
    disposition: Optional[str] = None
    disposition_reason: str = ""
    gate_evidence: dict = Field(default_factory=dict)
    health_issue_id: Optional[int] = None
    trace_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


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
    provider: Optional[str] = None
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
    trace_id: Optional[str] = None
    occurrence_count: int = 1
    merged_alerts: List = Field(default_factory=list)
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    issue_type: str = "other"
    # The anchor (MVP-2.6.1): the resource it resolved to, or why not — IssueDetail's anchor badge reads these
    resource_ref: Optional[int] = None
    anchor_status: Optional[str] = None
    anchor_candidates: Optional[dict] = None
    observed_at: Optional[datetime] = None
    # What the viewer may do here (MVP-2.7.0 S4: "note"), from ui_actions.route_allows — the detail route fills it
    available_actions: List[dict] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("anchor_candidates", mode="before")
    @classmethod
    def _candidates_or_none(cls, value):
        """A non-dict value (a legacy or hand-edited row) reads as None, as graph/api and graph/evidence read it —
        one such row must not 500 every issue list. On the model, so model_validate callers get it too."""
        return value if isinstance(value, dict) else None

    @classmethod
    def from_issue(cls, issue, account_name: Optional[str] = None) -> "HealthIssueResponse":
        """Build response, extracting merged_alerts from metric_data."""
        md = issue.metric_data if isinstance(issue.metric_data, dict) else {}
        return cls(
            id=issue.id,
            resource_id=issue.resource_id,
            provider=getattr(issue, "provider", None),
            severity=issue.severity,
            source=issue.source,
            title=issue.title,
            description=issue.description,
            alarm_name=issue.alarm_name,
            metric_data=issue.metric_data or {},
            related_changes=issue.related_changes or [],
            status=issue.status,
            detected_at=issue.detected_at,
            detected_by=issue.detected_by,
            resolved_at=issue.resolved_at,
            trace_id=getattr(issue, "trace_id", None),
            occurrence_count=issue.occurrence_count or 1,
            merged_alerts=md.get("merged_alerts", []),
            account_id=issue.account_id,
            account_name=account_name,
            issue_type=getattr(issue, "issue_type", "other") or "other",
            resource_ref=issue.resource_ref,
            anchor_status=issue.anchor_status,
            anchor_candidates=issue.anchor_candidates,
            observed_at=issue.observed_at,
        )


class IssueNoteRequest(BaseModel):
    """A note on an issue (MVP-2.7.0 S4). The author is the session actor, never the body — extra fields are refused.
    The 8000-character limit and the trim are services/issue_notes.clean_note's; this cap only bounds the body."""
    model_config = ConfigDict(extra="forbid")
    content: str = Field(..., max_length=8100)


class IssueNote(BaseModel):
    event_id: int
    health_issue_id: int
    content: str
    actor: str
    created_at: datetime


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
    """Content-only update. Status changes go through /approve, /reject, /execute.
    `status: "rejected"` is still accepted as a DEPRECATED alias for POST /reject (old UI);
    the handler answers 400 for any other status value. Identity is never read from the body."""
    model_config = ConfigDict(extra="forbid")
    risk_level: Optional[str] = Field(None, pattern="^(L0|L1|L2|L3)$")
    title: Optional[str] = Field(None, max_length=300)
    summary: Optional[str] = None
    steps: Optional[List] = None
    rollback_plan: Optional[dict] = None
    estimated_impact: Optional[str] = None
    pre_checks: Optional[List] = None
    post_checks: Optional[List] = None
    content_hash: Optional[str] = Field(None, max_length=64,
                                        description="content_hash of the plan as read; required with any content field "
                                                    "(422 without, 409 when the plan changed since)")
    status: Optional[str] = Field(None, description="DEPRECATED alias for POST /reject (only 'rejected' is accepted)")


class FixPlanApproveBody(BaseModel):
    content_hash: str = Field(..., max_length=64,
                              description="content_hash of the plan as reviewed; a plan changed since (or an empty "
                                          "hash) is refused (409)")
    approved_by: Optional[str] = Field(None, max_length=100, description="Legacy claimed name; audited, never trusted")
    reason: Optional[str] = Field(None, max_length=2000)


class FixPlanRejectBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class FixPlanResponse(BaseModel):
    """Schema for fix plan response."""
    id: int
    plan_kind: str = "fix"
    health_issue_id: Optional[int] = None
    rca_result_id: Optional[int] = None
    change_request_id: Optional[int] = None
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
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    account_id: Optional[int] = None
    plan_version: int = 1
    content_hash: Optional[str] = None
    approved_hash: Optional[str] = None
    approved_version: Optional[int] = None
    # MVP-2.7.0 S3 read context (never part of the content hash)
    issue_title: Optional[str] = None
    issue_status: Optional[str] = None
    target: Optional[dict] = None   # {resource_id, resource_ref, anchor_status, resource_type, region} of its issue
    available_actions: List[dict] = Field(default_factory=list)   # services/ui_actions.plan_actions

    model_config = ConfigDict(from_attributes=True)

    @field_validator("steps", "pre_checks", "post_checks", "rollback_plan", mode="before")
    @classmethod
    def _decode_legacy_json(cls, value, info):
        """Legacy rows hold these JSON columns as JSON *strings* (an agent passed pre-encoded JSON); decode
        them so one such row cannot 500 every fix-plan list. Undecodable text is kept, wrapped, not dropped.
        The same function gives the verdict its post-checks, so the page and the verdict count the same ones."""
        from agenticops.services.verification import decode_legacy_json
        return decode_legacy_json(value, dict if info.field_name == "rollback_plan" else list)


class FixExecutionResponse(BaseModel):
    """Schema for fix execution response."""
    id: int
    fix_plan_id: int
    health_issue_id: Optional[int] = None
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
    verification_status: Optional[str] = None
    verification_reason: Optional[str] = None
    accepted_by: Optional[str] = None
    accepted_at: Optional[datetime] = None
    acceptance_note: Optional[str] = None
    created_at: datetime
    # One row per declared post-check of this run's own plan, then stray results (verification.bind_results):
    # {check_id, check, result_status, results, problem: null|missing|duplicate|undeclared|unbound}
    post_check_binding: list = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="wrap")
    @classmethod
    def _bind_post_checks(cls, value, handler):
        """Read from a FixExecution row, pair its results with its plan's checks — the same function the
        verdict uses, so the page shows exactly what a reason like "no result for post-check pc-2" means."""
        model = handler(value)
        plan = getattr(value, "fix_plan", None)
        if plan is not None and not model.post_check_binding:
            from agenticops.services.verification import bind_results
            model.post_check_binding = bind_results(plan.post_checks, model.post_check_results)
        return model


class ExecutionAcceptBody(BaseModel):
    """A human's verdict on an execution pending acceptance; the identity is the authenticated session."""
    decision: str = Field(..., pattern="^(accepted|rejected)$")
    reason: str = Field(..., min_length=1, max_length=2000)


# ============================================================================
# Schedule Pydantic Models
# ============================================================================


class ScheduleCreate(BaseModel):
    """Schema for creating a schedule."""
    name: str = Field(..., max_length=100)
    pipeline_name: str = Field(..., max_length=100)
    schedule_type: str = Field(default="recurring", pattern="^(recurring|one_time)$")
    cron_expression: str = Field(..., max_length=100)
    account_name: Optional[str] = Field(None, max_length=100)
    is_enabled: bool = True
    max_retries: int = Field(default=0, ge=0, le=5)
    config: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_agent_chain(self):
        if self.pipeline_name == "AgentChain" and not self.config.get("prompt"):
            raise ValueError("AgentChain requires a 'prompt' field in config")
        return self


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
    schedule_type: str = "recurring"
    cron_expression: str
    account_name: Optional[str]
    is_enabled: bool
    max_retries: int = 0
    config: dict
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Notification Pydantic Models
# ============================================================================


class NotificationChannelCreate(BaseModel):
    """Schema for creating/updating a notification channel (YAML-backed)."""
    name: str = Field(..., max_length=100)
    channel_type: str = Field(..., pattern="^(slack|email|ses|sns|sns-report|feishu|dingtalk|wecom|webhook)$")
    config: dict = Field(default_factory=dict)
    severity_filter: List[str] = Field(default_factory=list)
    is_enabled: bool = True


class NotificationChannelUpdate(BaseModel):
    """Schema for updating a notification channel (YAML-backed)."""
    channel_type: Optional[str] = Field(None, pattern="^(slack|email|ses|sns|sns-report|feishu|dingtalk|wecom|webhook)$")
    config: Optional[dict] = None
    severity_filter: Optional[List[str]] = None
    is_enabled: Optional[bool] = None


class NotificationChannelResponse(BaseModel):
    """Schema for notification channel response (YAML-backed)."""
    name: str
    channel_type: str
    config: dict
    severity_filter: list
    is_enabled: bool


class NotificationLogResponse(BaseModel):
    """Schema for notification log response."""
    id: int
    channel_name: str
    subject: str
    body: str
    severity: Optional[str]
    status: str
    error: Optional[str]
    sent_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationSendRequest(BaseModel):
    """Schema for sending a test notification."""
    subject: str = "Test notification from AgenticOps"
    body: str = "This is a test notification."
    severity: Optional[str] = "low"


# -- Report Publishing Models -----------------------------------------------


class ShareContentRequest(BaseModel):
    """Request to share content to notification channels."""
    subject: str
    body: str
    channel_names: List[str] = Field(default_factory=list)
    upload_to_s3: bool = False
    expiry_hours: int = Field(default=72, ge=1, le=168)


class ShareContentResponse(BaseModel):
    """Response from content sharing."""
    success: bool
    channels_sent: List[str] = Field(default_factory=list)
    channels_failed: List[str] = Field(default_factory=list)
    presigned_url: Optional[str] = None


class ReportPublishRequest(BaseModel):
    """Request to publish a report via an sns-report or ses channel. MVP-2.7.0 S6: pinned to one version and
    language (every language asked for must be ready); the Idempotency-Key header makes a repeat send nothing."""
    channel_name: str
    formats: Optional[List[str]] = None  # None = use channel defaults
    version: int = Field(..., ge=1)
    language: Literal["zh", "en", "zh-en"]


class ReportPublishResponse(BaseModel):
    """Response from report publishing."""
    report_id: int
    channel_name: str
    formats_generated: List[str]
    download_urls: Dict[str, str]
    sns_message_id: Optional[str] = None


class ReportSubscribeRequest(BaseModel):
    """Request to subscribe an email to an sns-report channel."""
    channel_name: str
    email: str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")


class ReportSubscriptionResponse(BaseModel):
    """A single subscription entry."""
    subscription_arn: str
    protocol: str
    endpoint: str
    status: str


class ReportUnsubscribeRequest(BaseModel):
    """Request to unsubscribe from an sns-report channel."""
    channel_name: str


# ============================================================================
# Chat Pydantic Models
# ============================================================================


class SearchResultItem(BaseModel):
    id: int
    title: str
    subtitle: str = ""
    entity_type: str
    status: Optional[str] = None
    severity: Optional[str] = None
    report_type: Optional[str] = None
    parent_id: Optional[int] = None
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class SearchResponse(BaseModel):
    query: str
    results: dict


class ReportFromSessionRequest(BaseModel):
    session_id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    message_ids: Optional[List[int]] = None
    format: str = Field(default="markdown", pattern="^(markdown|html|pdf|docx)$")


class EntityRefIn(BaseModel):
    """What a chat is about (MVP-2.7.0 S5): an issue or a change; the server reads the rest from the object."""
    model_config = ConfigDict(extra="forbid")
    entity_type: Literal["health_issue", "change_request"]
    entity_id: int = Field(..., ge=1)


class ChatContextIn(BaseModel):
    """A chat's context (services/chat_context): a linked object, or none (an independent request), and an account.
    A linked object's account is its own — a different account_id here is refused (409)."""
    model_config = ConfigDict(extra="forbid")
    primary: Optional[EntityRefIn] = None
    account_id: Optional[int] = Field(None, ge=1)
    region: Optional[str] = Field(None, max_length=80)


class ChatSessionCreate(BaseModel):
    name: Optional[str] = None
    context: Optional[ChatContextIn] = None


class ChatSessionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    pinned: Optional[bool] = None
    starred: Optional[bool] = None
    archived: Optional[bool] = None
    # "" = set Auto (stored NULL); omitted = don't change; non-empty = validated model id
    model_id: Optional[str] = None
    # "" = set Auto (stored NULL); omitted = don't change; else off|standard|deep
    effort: Optional[str] = None
    # Who sees the session (MVP-2.7.0): only its owner or an admin may change it
    visibility: Optional[Literal["private", "workspace"]] = None
    # The chat's context (S5): changeable until the first message is sent (409 context_locked after)
    context: Optional[ChatContextIn] = None


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    scan_focus: Optional[str] = Field(None, description="Resource focus: computing,networking,databases,storage,security,billing,all")
    # MVP-2.7.0 S5 (services/chat_dispatch): the sender's id for this message — a repeat is replayed or refused,
    # never run twice. Multipart sends carry it as a form field of the same name.
    client_message_id: str = Field(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    tool_calls: Optional[list] = None
    token_usage: Optional[dict] = None
    trace_id: Optional[str] = None
    cost_usd: Optional[float] = None
    attachments: Optional[list] = None
    suggestions: Optional[list] = None
    created_at: datetime
    # S5: accepted|running|completed|failed|interrupted (None on older rows = completed)
    client_message_id: Optional[str] = None
    dispatch_state: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ChatSessionResponse(BaseModel):
    id: int
    session_id: str
    name: str
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    message_count: int = 0
    pinned: bool = False
    starred: bool = False
    archived: bool = False
    # Per-session main-agent model override; None = Auto (follow global config)
    model_id: Optional[str] = None
    # Per-session effort (thinking) override; None = Auto
    effort: Optional[str] = None
    # MVP-2.7.0: private = its owner and admins; workspace = everyone. owned_by_me is for the caller.
    visibility: str = "workspace"
    owned_by_me: bool = False
    # Whether the caller may rename / pin / archive / switch model / delete it (owner or admin; anyone for an
    # ownerless session) — reading and sending only need it to be visible
    can_manage: bool = True
    # S5: {primary: {entity_type, entity_id, ref, title} | null, account_id, account_name, region, scope_locked}
    context: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


class ChatSessionDetail(ChatSessionResponse):
    # DEPRECATED: history now comes from GET /sessions/{id}/messages (paginated).
    # Kept for type stability; the detail endpoint always returns [].
    messages: List[ChatMessageResponse] = []


class ChatMessagesPage(BaseModel):
    """One page of chat messages, ordered oldest→newest (chronological).

    Cursor is ChatMessage.id (monotonic). `next_cursor` is the id to pass as
    `before` to fetch the immediately-older page; null when no older page exists.
    """
    messages: List[ChatMessageResponse] = []
    has_more: bool = False
    next_cursor: Optional[int] = None


class MemoryFactResponse(BaseModel):
    id: int
    category: str
    key: str
    value: str
    confidence_score: float
    source_session_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemoryExperienceResponse(BaseModel):
    id: int
    session_id: str
    memory_type: str
    content_text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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


class AuditLogResponse(BaseModel):
    """Schema for audit log response."""
    id: int
    timestamp: datetime
    user_id: Optional[int]
    user_email: Optional[str]
    actor: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    entity_name: Optional[str]
    details: dict
    old_values: Optional[dict]
    new_values: Optional[dict]
    ip_address: Optional[str]

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Change Management (MVP-2.6.0)
# ============================================================================


class ChangeProposedStep(BaseModel):
    """One of the requester's own steps (the fix_plans.steps shape; caps mirror services/change_steps)."""
    action: str = Field("", max_length=500)
    command: str = Field(..., min_length=1, max_length=2000)


class ChangeExternalRef(BaseModel):
    """The ticket in another system a request came from (caps mirror change_service._external_ref)."""
    system: str = Field(..., pattern="^[a-z0-9_-]{1,50}$")
    ticket_id: str = Field(..., min_length=1, max_length=200)
    url: Optional[str] = Field(None, max_length=1000, pattern="^[Hh][Tt][Tt][Pp][Ss]?://")
    requested_by: Optional[str] = Field(None, max_length=255)


class ChangeRequestCreate(BaseModel):
    # Caps mirror change_service.create_change_request so an over-cap body is 422 at validation, before
    # the service is entered (title 300 / description 8000 / justification 2000 / 20 targets, 200 chars each).
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, max_length=8000)
    account_name: Optional[str] = None
    targets: List[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=20)
    requested_change_type: str = Field("normal", pattern="^(normal|emergency)$")
    justification: str = Field("", max_length=2000)
    proposed_steps: Optional[List[ChangeProposedStep]] = Field(None, max_length=50)
    external_ref: Optional[ChangeExternalRef] = None


class ChangeIntakeBody(BaseModel):
    """POST /api/changes/intake (spec §3.D.3). `requested_by` is the external requester's claimed name, kept as
    external_ref.requested_by — never an identity (the requester is webhook:<external_ref.system>)."""
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, max_length=8000)
    justification: str = Field("", max_length=2000)
    account: Optional[str] = None
    target_hints: List[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=20)
    proposed_steps: Optional[List[ChangeProposedStep]] = Field(None, max_length=50)
    external_ref: ChangeExternalRef
    requested_by: Optional[str] = Field(None, max_length=255)


class ChangeRequestResponse(BaseModel):
    """Snapshot of a change request (from change_service.to_dict — timestamps are ISO strings)."""
    id: int
    title: str
    description: str
    justification: str = ""
    source: str
    requested_by: str
    requester_user_id: Optional[int] = None
    requested_at: Optional[str] = None
    account_id: Optional[int] = None
    target_hints: list = Field(default_factory=list)
    target_resources: list = Field(default_factory=list)
    requested_change_type: str = "normal"
    effective_change_type: Optional[str] = None
    risk_level: Optional[str] = None
    action_type: Optional[str] = None
    status: str
    review_verdict: Optional[str] = None
    review_reasons: list = Field(default_factory=list)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    policy_rule: Optional[str] = None
    policy_action: Optional[str] = None
    approved_by: Optional[str] = None
    approver_user_id: Optional[int] = None
    approved_at: Optional[str] = None
    approval_reason: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    closed_at: Optional[str] = None
    trace_id: Optional[str] = None
    chat_session_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    proposed_steps: Optional[list] = None
    external_ref: Optional[dict] = None
    steps_diff: Optional[dict] = None
    needs_review_reason: Optional[str] = None


class ChangeRequestDetail(ChangeRequestResponse):
    plans: List[FixPlanResponse] = Field(default_factory=list)
    executions: List[FixExecutionResponse] = Field(default_factory=list)
    # The LAST policy_decision pipeline event's decision (None before the review reached the policy engine)
    policy_decision: Optional[dict] = None
    available_actions: List[dict] = Field(default_factory=list)  # services/ui_actions.change_actions


class ChangeReasonBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class ChangeApproveBody(ChangeReasonBody):
    content_hash: str = Field(..., max_length=64,
                              description="content_hash of the implementation plan as reviewed (409 when it changed "
                                          "or is empty)")


class ChangeClarifyBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ChangeResolveReviewBody(BaseModel):
    outcome: str = Field(..., pattern="^(completed|failed)$")
    reason: str = Field(..., min_length=1, max_length=2000)


class ChangeTimelineEntry(BaseModel):
    ts: Optional[str] = None
    kind: str  # event | audit
    type: str
    actor: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    detail: Optional[object] = None


class CommandAuditResponse(BaseModel):
    id: int
    created_at: datetime
    actor: str
    on_behalf_of: Optional[str] = None
    agent_name: Optional[str] = None
    tool: str
    tier: str
    account: str = ""
    region: str = ""
    target: str = ""
    command: str
    outcome: str
    reason: Optional[str] = None
    exit_code: Optional[int] = None
    output_excerpt: str = ""
    duration_ms: int = 0
    trace_id: Optional[str] = None
    fix_plan_id: Optional[int] = None
    change_request_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
