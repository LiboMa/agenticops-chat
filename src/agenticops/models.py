"""SQLAlchemy models for AgenticOps."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Generator

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
from sqlalchemy.pool import NullPool, StaticPool

from agenticops.config import settings


# ============================================================================
# Singleton Engine and Connection Pool
# ============================================================================

_engine = None


def get_engine():
    """Get or create singleton SQLAlchemy engine with connection pooling."""
    global _engine
    if _engine is None:
        settings.ensure_dirs()

        # For SQLite, use NullPool so each thread gets its own connection
        # (StaticPool shares one connection → InterfaceError under concurrency)
        if settings.database_url.startswith("sqlite"):
            _engine = create_engine(
                settings.database_url,
                echo=False,
                connect_args={"check_same_thread": False},
                poolclass=NullPool,
            )
        else:
            _engine = create_engine(
                settings.database_url,
                echo=False,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
    return _engine


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions with automatic commit/rollback."""
    SessionLocal = sessionmaker(bind=get_engine())
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class ResourceStatus(str, Enum):
    """Resource status enumeration."""

    RUNNING = "running"
    STOPPED = "stopped"
    TERMINATED = "terminated"
    AVAILABLE = "available"
    UNKNOWN = "unknown"


class AnomalySeverity(str, Enum):
    """Anomaly severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================================
# Account Management
# ============================================================================


class AWSAccount(Base):
    """AWS account configuration for cross-account access."""

    __tablename__ = "aws_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    account_id: Mapped[str] = mapped_column(String(12), unique=True)
    role_arn: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    regions: Mapped[list] = mapped_column(JSON, default=list)  # List of enabled regions
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    resources: Mapped[list["AWSResource"]] = relationship(back_populates="account")


# ============================================================================
# Resource Inventory (SCAN)
# ============================================================================


class AWSResource(Base):
    """Scanned AWS resource inventory."""

    __tablename__ = "aws_resources"
    __table_args__ = (
        Index("idx_resource_type_region", "resource_type", "region"),
        Index("idx_resource_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("aws_accounts.id"))
    resource_id: Mapped[str] = mapped_column(String(100))  # AWS resource ID (e.g., i-xxx)
    resource_arn: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(50))  # e.g., EC2, Lambda, RDS
    resource_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    region: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=ResourceStatus.UNKNOWN.value)
    resource_metadata: Mapped[dict] = mapped_column(JSON, default=dict)  # Service-specific attributes
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    managed: Mapped[bool] = mapped_column(default=True)  # opt-in/out of agent monitoring
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    account: Mapped["AWSAccount"] = relationship(back_populates="resources")


# ============================================================================
# Multi-Cloud Account & Resource (replaces AWSAccount / AWSResource)
# ============================================================================


class CloudAccount(Base):
    """Cloud account configuration supporting multiple providers."""

    __tablename__ = "cloud_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(20))  # aws | azure | gcp | alicloud
    is_enabled: Mapped[bool] = mapped_column(default=True)
    credential_source_type: Mapped[str] = mapped_column(String(20), default="environment")  # environment | assume_role | profile | static_keys
    credentials: Mapped[dict] = mapped_column(JSON, default=dict)
    regions: Mapped[list] = mapped_column(JSON, default=list)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    resources: Mapped[list["CloudResource"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    monitoring_configs: Mapped[list["MonitoringConfig"]] = relationship(
        back_populates="cloud_account", foreign_keys="MonitoringConfig.cloud_account_id",
        cascade="all, delete-orphan",
    )


class CloudResource(Base):
    """Scanned cloud resource inventory (multi-provider)."""

    __tablename__ = "cloud_resources"
    __table_args__ = (
        UniqueConstraint("account_id", "provider", "resource_id", name="uq_cloud_resource_acct_prov_rid"),
        Index("idx_cloud_resource_provider", "provider"),
        Index("idx_cloud_resource_type_region", "resource_type", "region"),
        Index("idx_cloud_resource_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"))
    provider: Mapped[str] = mapped_column(String(20))
    region: Mapped[str] = mapped_column(String(30))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(200), default="")
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    managed: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    account: Mapped["CloudAccount"] = relationship(back_populates="resources")


# ============================================================================
# Monitoring Configuration (MONITOR)
# ============================================================================


class MonitoringConfig(Base):
    """Monitoring configuration per account/service."""

    __tablename__ = "monitoring_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[Optional[int]] = mapped_column(nullable=True)  # legacy aws_accounts FK, kept for old rows
    service_type: Mapped[str] = mapped_column(String(50))  # e.g., EC2, Lambda
    is_enabled: Mapped[bool] = mapped_column(default=True)
    metrics_config: Mapped[dict] = mapped_column(JSON, default=dict)  # Which metrics to collect
    logs_config: Mapped[dict] = mapped_column(JSON, default=dict)  # Log group patterns
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)  # Alert thresholds
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Multi-cloud FK
    cloud_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cloud_accounts.id"), nullable=True
    )

    # Relationships
    cloud_account: Mapped[Optional["CloudAccount"]] = relationship(
        back_populates="monitoring_configs", foreign_keys=[cloud_account_id]
    )


class MetricDataPoint(Base):
    """Stored CloudWatch metric data points."""

    __tablename__ = "metric_data_points"
    __table_args__ = (Index("idx_metric_timestamp", "resource_id", "metric_name", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(500))
    metric_namespace: Mapped[str] = mapped_column(String(100))
    metric_name: Mapped[str] = mapped_column(String(100))
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    value: Mapped[float] = mapped_column()
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    statistic: Mapped[str] = mapped_column(String(20), default="Average")


# ============================================================================
# Anomaly Detection (DETECT)
# ============================================================================


class Anomaly(Base):
    """DEPRECATED: Use HealthIssue instead.

    Detected anomalies. This model is kept for backward compatibility with
    existing database records. All new code should use HealthIssue.
    """

    __tablename__ = "anomalies"
    __table_args__ = (Index("idx_anomaly_severity_status", "severity", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(500))
    resource_type: Mapped[str] = mapped_column(String(50))
    region: Mapped[str] = mapped_column(String(50))
    anomaly_type: Mapped[str] = mapped_column(String(50))  # metric_spike, log_error, etc.
    severity: Mapped[str] = mapped_column(String(20), default=AnomalySeverity.MEDIUM.value)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    metric_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    expected_value: Mapped[Optional[float]] = mapped_column(nullable=True)
    actual_value: Mapped[Optional[float]] = mapped_column(nullable=True)
    deviation_percent: Mapped[Optional[float]] = mapped_column(nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, acknowledged, resolved
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    notes: Mapped[list["AnomalyNote"]] = relationship(back_populates="anomaly")


class AnomalyNote(Base):
    """DEPRECATED: Use HealthIssue instead.

    Notes and workflow history for anomalies. This model is kept for backward
    compatibility with existing database records.
    """

    __tablename__ = "anomaly_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id"))
    note_type: Mapped[str] = mapped_column(String(20))  # acknowledge, resolve, comment
    content: Mapped[str] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    anomaly: Mapped["Anomaly"] = relationship(back_populates="notes")


# ============================================================================
# Root Cause Analysis (ANALYZE)
# ============================================================================


class RCAResult(Base):
    """Root Cause Analysis results linked to HealthIssue."""

    __tablename__ = "rca_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    health_issue_id: Mapped[int] = mapped_column(ForeignKey("health_issues.id"))
    root_cause: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(default=0.0)
    contributing_factors: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    fix_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    fix_risk_level: Mapped[str] = mapped_column(String(20), default="unknown")
    sop_used: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    similar_cases: Mapped[list] = mapped_column(JSON, default=list)
    model_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    health_issue: Mapped["HealthIssue"] = relationship(back_populates="rca_results")


# ============================================================================
# Health Issues (DETECT Agent)
# ============================================================================


# ── HealthIssue State Machine ────────────────────────────────────────

VALID_ISSUE_STATUSES = {
    "open", "investigating", "acknowledged", "root_cause_identified",
    "fix_planned", "fix_approved", "fix_executing", "fix_executed", "resolved",
    "dismissed",
}

# Allowed transitions: from_status -> {to_status, ...}
_ISSUE_TRANSITIONS: dict[str, set[str]] = {
    "open":                   {"investigating", "acknowledged", "resolved", "dismissed"},
    "investigating":          {"acknowledged", "root_cause_identified", "fix_planned", "resolved", "dismissed"},
    "acknowledged":           {"investigating", "root_cause_identified", "fix_planned", "resolved", "dismissed"},
    "root_cause_identified":  {"fix_planned", "resolved", "dismissed"},
    "fix_planned":            {"fix_approved", "resolved", "dismissed"},
    "fix_approved":           {"fix_executing", "resolved", "dismissed"},
    "fix_executing":          {"fix_executed", "resolved", "dismissed"},
    "fix_executed":           {"resolved", "dismissed"},
    "resolved":               set(),  # terminal state
    "dismissed":              {"open"},  # can reopen
}


class InvalidStatusTransition(ValueError):
    """Raised when a HealthIssue status transition is not allowed."""


def validate_status_transition(current: str, new: str) -> None:
    """Validate a HealthIssue status transition.

    Args:
        current: Current status value.
        new: Requested new status value.

    Raises:
        InvalidStatusTransition: If the transition is not allowed.
        ValueError: If either status is not a valid status.
    """
    if new not in VALID_ISSUE_STATUSES:
        raise ValueError(f"Invalid status '{new}'. Valid: {', '.join(sorted(VALID_ISSUE_STATUSES))}")
    if current == new:
        return  # no-op is always fine
    allowed = _ISSUE_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise InvalidStatusTransition(
            f"Cannot transition from '{current}' to '{new}'. "
            f"Allowed from '{current}': {', '.join(sorted(allowed)) or 'none (terminal)'}"
        )


class HealthIssue(Base):
    """Detected health issues with lifecycle tracking."""

    __tablename__ = "health_issues"
    __table_args__ = (
        Index("idx_health_issue_severity_status", "severity", "status"),
        Index("idx_health_issue_fingerprint", "fingerprint"),
        Index("idx_health_issue_resource_status", "resource_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(500))  # Cloud resource ID / ARN
    provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # aws|azure|gcp|alicloud
    severity: Mapped[str] = mapped_column(String(20))  # critical, high, medium, low
    source: Mapped[str] = mapped_column(
        String(50)
    )  # cloudwatch_alarm, metric_anomaly, log_pattern, manual
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    alarm_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    metric_data: Mapped[dict] = mapped_column(JSON, default=dict)
    related_changes: Mapped[list] = mapped_column(JSON, default=list)  # CloudTrail events
    status: Mapped[str] = mapped_column(String(30), default="open")
    # Lifecycle: open -> investigating -> root_cause_identified -> fix_planned
    #            -> fix_approved -> fix_executed -> resolved
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    detected_by: Mapped[str] = mapped_column(String(50), default="detect_agent")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Fingerprint deduplication
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    occurrence_count: Mapped[int] = mapped_column(default=1)
    first_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Pipeline trace ID (generated at alert entry, flows through entire lifecycle)
    trace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    # Multi-cloud FK (nullable for backward compat)
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cloud_accounts.id"), nullable=True
    )

    # Relationships
    rca_results: Mapped[list["RCAResult"]] = relationship(back_populates="health_issue")
    fix_plans: Mapped[list["FixPlan"]] = relationship(back_populates="health_issue")
    fix_executions: Mapped[list["FixExecution"]] = relationship(back_populates="health_issue")


# ============================================================================
# Fix Plans (SRE Agent)
# ============================================================================


class FixPlan(Base):
    """Structured fix plans generated by the SRE Agent."""

    __tablename__ = "fix_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    health_issue_id: Mapped[int] = mapped_column(ForeignKey("health_issues.id"))
    rca_result_id: Mapped[int] = mapped_column(ForeignKey("rca_results.id"))
    risk_level: Mapped[str] = mapped_column(String(20))  # L0, L1, L2, L3
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # ordered fix steps
    rollback_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_impact: Mapped[str] = mapped_column(Text, default="")
    pre_checks: Mapped[list] = mapped_column(JSON, default=list)
    post_checks: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    # Lifecycle: draft -> pending_approval -> approved -> executing -> executed | failed | rejected
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    health_issue: Mapped["HealthIssue"] = relationship(back_populates="fix_plans")
    rca_result: Mapped["RCAResult"] = relationship()
    fix_executions: Mapped[list["FixExecution"]] = relationship(back_populates="fix_plan")


# FixPlan status sets for dedup/replace logic
FIXPLAN_TERMINAL_STATUSES = {"executed", "failed", "rejected"}
FIXPLAN_REPLACEABLE_STATUSES = {"draft"}
FIXPLAN_LOCKED_STATUSES = {"pending_approval", "approved", "executing"}


# ============================================================================
# Fix Execution (Executor Agent)
# ============================================================================


class FixExecution(Base):
    """Execution record for an approved fix plan."""

    __tablename__ = "fix_executions"
    __table_args__ = (
        Index("idx_fix_exec_status", "status"),
        Index("idx_fix_exec_plan", "fix_plan_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fix_plan_id: Mapped[int] = mapped_column(ForeignKey("fix_plans.id"))
    health_issue_id: Mapped[int] = mapped_column(ForeignKey("health_issues.id"))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # Lifecycle: pending -> running -> succeeded | failed | rolled_back | aborted
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    executed_by: Mapped[str] = mapped_column(String(100), default="executor_agent")
    pre_check_results: Mapped[list] = mapped_column(JSON, default=list)
    step_results: Mapped[list] = mapped_column(JSON, default=list)
    post_check_results: Mapped[list] = mapped_column(JSON, default=list)
    rollback_results: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    fix_plan: Mapped["FixPlan"] = relationship(back_populates="fix_executions")
    health_issue: Mapped["HealthIssue"] = relationship(back_populates="fix_executions")


# ============================================================================
# Pipeline Event Timeline
# ============================================================================


class PipelineEvent(Base):
    """Timeline event log for HealthIssue lifecycle tracking."""

    __tablename__ = "pipeline_events"
    __table_args__ = (
        Index("idx_pipeline_event_issue", "health_issue_id"),
        Index("idx_pipeline_event_time", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    health_issue_id: Mapped[int] = mapped_column(index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    duration_ms: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    trace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)


# ============================================================================
# Agent Audit Log
# ============================================================================


class AgentLog(Base):
    """Agent execution audit trail."""

    __tablename__ = "agent_logs"
    __table_args__ = (
        Index("idx_agent_log_trace", "trace_id"),
        Index("idx_agent_log_agent_time", "agent_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(100))
    input_summary: Mapped[str] = mapped_column(Text)
    output_summary: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    parent_agent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ============================================================================
# Reports (REPORT)
# ============================================================================


class CaseStudyRecord(Base):
    """Metadata record for distilled case studies.

    Tracks case study lifecycle and links to the markdown file + vector store.
    """

    __tablename__ = "case_study_records"
    __table_args__ = (
        Index("idx_csr_resource_type", "resource_type"),
        Index("idx_csr_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(100), unique=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="")
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="pending_review")
    verified: Mapped[bool] = mapped_column(default=False)
    reuse_count: Mapped[int] = mapped_column(default=0)
    source_issue_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    source_rca_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    efficiency_score: Mapped[float] = mapped_column(default=0.5)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ── SOP Lifecycle State Machine ────────────────────────────────────────

VALID_SOP_STATUSES = {"draft", "review", "active", "deprecated", "archived"}

_SOP_TRANSITIONS: dict[str, set[str]] = {
    "draft":      {"review", "archived"},
    "review":     {"active", "draft", "archived"},
    "active":     {"deprecated"},
    "deprecated": {"active", "archived"},   # can resurrect or archive
    "archived":   set(),                     # terminal
}


class InvalidSOPTransition(ValueError):
    """Raised when an SOP status transition is not allowed."""


def validate_sop_transition(current: str, new: str) -> None:
    """Validate an SOP status transition."""
    if new not in VALID_SOP_STATUSES:
        raise ValueError(f"Invalid SOP status '{new}'. Valid: {', '.join(sorted(VALID_SOP_STATUSES))}")
    if current == new:
        return
    allowed = _SOP_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise InvalidSOPTransition(
            f"Cannot transition SOP from '{current}' to '{new}'. "
            f"Allowed: {', '.join(sorted(allowed)) or 'none (terminal)'}"
        )


class SOPRecord(Base):
    """Metadata record for SOPs with lifecycle tracking."""

    __tablename__ = "sop_records"
    __table_args__ = (
        Index("idx_sop_status", "status"),
        Index("idx_sop_resource_type", "resource_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(200), unique=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="")
    issue_pattern: Mapped[str] = mapped_column(String(500), default="")
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    quality_score: Mapped[float] = mapped_column(default=0.0)
    application_count: Mapped[int] = mapped_column(default=0)
    success_count: Mapped[int] = mapped_column(default=0)
    source_issue_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    file_path: Mapped[str] = mapped_column(String(500), default="")
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Report(Base):
    """Generated reports."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_type: Mapped[str] = mapped_column(String(50))  # daily, weekly, on_demand
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    content_markdown: Mapped[str] = mapped_column(Text)
    content_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    report_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


# ============================================================================
# Local Documents (tracked files from write_local_file)
# ============================================================================


class LocalDoc(Base):
    """Tracks files written by the write_local_file agent tool."""

    __tablename__ = "local_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String(500), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_type: Mapped[str] = mapped_column(String(50))  # extension: md, json, yaml, txt...
    size_bytes: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[str] = mapped_column(String(100), default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


# ============================================================================
# IM Aliases (friendly names → IM chat IDs)
# ============================================================================


class IMAlias(Base):
    """Maps friendly names to IM platform chat IDs for /send_to."""

    __tablename__ = "im_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    platform: Mapped[str] = mapped_column(String(20))  # feishu / dingtalk / wecom
    chat_id: Mapped[str] = mapped_column(String(200))
    app_name: Mapped[str] = mapped_column(String(100), default="default")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


# ============================================================================
# Chat Sessions (Web UI)
# ============================================================================


class AlertEvent(Base):
    """Inbound alert event from external monitoring systems."""

    __tablename__ = "alert_events"
    __table_args__ = (
        Index("idx_alert_source_dedup", "source", "external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))  # datadog, pagerduty, grafana, cloudwatch, generic
    external_id: Mapped[str] = mapped_column(String(200))  # dedup key from source
    severity: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    resource_hint: Mapped[str] = mapped_column(String(500), default="")  # best-effort resource ID
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    health_issue_id: Mapped[Optional[int]] = mapped_column(nullable=True)  # linked HealthIssue
    status: Mapped[str] = mapped_column(String(30), default="received")  # received, processed, ignored, error
    received_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    trace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)


class ChatSession(Base):
    """Chat session for web UI and IM bidirectional chat."""
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    im_platform: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # feishu|dingtalk|wecom|None
    im_chat_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # IM group chat ID
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Session metadata: pin/star/archive
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class ChatMessage(Base):
    """Individual message in a chat session."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    attachments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class SessionSummary(Base):
    """Rolling conversation summary generated when the sliding window trims messages."""
    __tablename__ = "session_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    summary_text: Mapped[str] = mapped_column(Text)
    message_range_start: Mapped[int] = mapped_column(Integer)  # ChatMessage.id
    message_range_end: Mapped[int] = mapped_column(Integer)    # ChatMessage.id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentMemoryFact(Base):
    """跨会话结构化事实记忆（key-value 形式）。"""
    __tablename__ = "agent_memory_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(50))  # user_preference, infra_context, team_info
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.8)
    source_session_id: Mapped[str] = mapped_column(String(36))  # ChatSession.session_id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("category", "key", name="uq_fact_category_key"),
    )


class AgentMemory(Base):
    """跨会话向量化经验记忆。"""
    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36))  # ChatSession.session_id
    memory_type: Mapped[str] = mapped_column(String(20))  # problem, root_cause, solution
    content_text: Mapped[str] = mapped_column(Text)
    embedding_vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)  # numpy array as BLOB
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


# ============================================================================
# Database Session Management
# ============================================================================


def init_db(engine=None):
    """Initialize database and create all tables.

    Args:
        engine: Optional SQLAlchemy engine. If None, uses the singleton
                engine from get_engine().

    Includes migration: if rca_results table has the old anomaly_id column
    (from the deprecated Anomaly FK), drop and recreate it with the new schema.
    """
    if engine is None:
        engine = get_engine()

    # Migration: detect old rca_results schema and recreate
    insp = inspect(engine)
    if insp.has_table("rca_results"):
        columns = {col["name"] for col in insp.get_columns("rca_results")}
        if "anomaly_id" in columns and "health_issue_id" not in columns:
            # Old schema — drop and let create_all rebuild
            RCAResult.__table__.drop(engine, checkfirst=True)

    # Migration: add 'managed' column to aws_resources if missing
    if insp.has_table("aws_resources"):
        columns = {col["name"] for col in insp.get_columns("aws_resources")}
        if "managed" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE aws_resources ADD COLUMN managed BOOLEAN DEFAULT 1")
                )
                conn.commit()

    # Migration: add 'attachments' column to chat_messages if missing
    if insp.has_table("chat_messages"):
        columns = {col["name"] for col in insp.get_columns("chat_messages")}
        if "attachments" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE chat_messages ADD COLUMN attachments JSON")
                )
                conn.commit()

    # Migration: add IM chat columns to chat_sessions if missing
    if insp.has_table("chat_sessions"):
        columns = {col["name"] for col in insp.get_columns("chat_sessions")}
        if "im_platform" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN im_platform VARCHAR(20)"))
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN im_chat_id VARCHAR(200)"))
                conn.commit()

    # Migration: add pinned/starred/archived columns to chat_sessions if missing
    if insp.has_table("chat_sessions"):
        columns = {col["name"] for col in insp.get_columns("chat_sessions")}
        if "pinned" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN pinned BOOLEAN DEFAULT 0"))
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN starred BOOLEAN DEFAULT 0"))
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN archived BOOLEAN DEFAULT 0"))
                conn.commit()

    # Migration: add fingerprint dedup columns to health_issues if missing
    if insp.has_table("health_issues"):
        columns = {col["name"] for col in insp.get_columns("health_issues")}
        if "fingerprint" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE health_issues ADD COLUMN fingerprint VARCHAR(64)"))
                conn.execute(text("ALTER TABLE health_issues ADD COLUMN occurrence_count INTEGER DEFAULT 1"))
                conn.execute(text("ALTER TABLE health_issues ADD COLUMN first_seen DATETIME"))
                conn.execute(text("ALTER TABLE health_issues ADD COLUMN last_seen DATETIME"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_health_issue_fingerprint ON health_issues(fingerprint)"))
                conn.commit()

    # Migration: add composite index for resource-based dedup
    if insp.has_table("health_issues"):
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_health_issue_resource_status "
                "ON health_issues(resource_id, status)"
            ))
            conn.commit()

    # Migration: add trace_id columns to health_issues, pipeline_events, alert_events
    for tbl in ("health_issues", "pipeline_events", "alert_events"):
        if insp.has_table(tbl):
            columns = {col["name"] for col in insp.get_columns(tbl)}
            if "trace_id" not in columns:
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN trace_id VARCHAR(20)"))
                    if tbl != "alert_events":
                        conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_trace_id ON {tbl}(trace_id)"))
                    conn.commit()

    # Migration: notification_logs channel_id → channel_name (YAML-only channels)
    if insp.has_table("notification_logs"):
        columns = {col["name"] for col in insp.get_columns("notification_logs")}
        if "channel_name" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE notification_logs ADD COLUMN channel_name VARCHAR(100) DEFAULT ''"))
                # Backfill from old channel_id if notification_channels table exists
                if insp.has_table("notification_channels") and "channel_id" in columns:
                    conn.execute(text(
                        "UPDATE notification_logs SET channel_name = "
                        "(SELECT name FROM notification_channels WHERE notification_channels.id = notification_logs.channel_id) "
                        "WHERE channel_name = '' AND channel_id IS NOT NULL"
                    ))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notification_log_channel_name ON notification_logs(channel_name)"))
                conn.commit()

    # Migration: add account_id column to health_issues if missing
    if insp.has_table("health_issues"):
        columns = {col["name"] for col in insp.get_columns("health_issues")}
        if "account_id" not in columns:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE health_issues ADD COLUMN account_id INTEGER REFERENCES cloud_accounts(id)"
                ))
                conn.commit()

    # Migration: add cloud_account_id to monitoring_configs if missing
    if insp.has_table("monitoring_configs"):
        columns = {col["name"] for col in insp.get_columns("monitoring_configs")}
        if "cloud_account_id" not in columns:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE monitoring_configs ADD COLUMN cloud_account_id INTEGER REFERENCES cloud_accounts(id)"
                ))
                conn.commit()

    # Migration: add token tracking columns to agent_logs
    if insp.has_table("agent_logs"):
        cols = {c["name"] for c in insp.get_columns("agent_logs")}
        new_cols = []
        if "trace_id" not in cols:
            new_cols.append("ALTER TABLE agent_logs ADD COLUMN trace_id VARCHAR(36)")
        if "parent_agent" not in cols:
            new_cols.append("ALTER TABLE agent_logs ADD COLUMN parent_agent VARCHAR(50)")
        if "cache_read_tokens" not in cols:
            new_cols.append("ALTER TABLE agent_logs ADD COLUMN cache_read_tokens INTEGER DEFAULT 0")
        if "model_id" not in cols:
            new_cols.append("ALTER TABLE agent_logs ADD COLUMN model_id VARCHAR(100)")
        if new_cols:
            with engine.connect() as conn:
                for stmt in new_cols:
                    conn.execute(text(stmt))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_log_trace ON agent_logs(trace_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_log_agent_time ON agent_logs(agent_name, created_at)"))
                conn.commit()

    # Migration: add provider column to health_issues if missing, backfill 'aws'
    if insp.has_table("health_issues"):
        columns = {col["name"] for col in insp.get_columns("health_issues")}
        if "provider" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE health_issues ADD COLUMN provider VARCHAR(20)"))
                conn.execute(text("UPDATE health_issues SET provider = 'aws' WHERE provider IS NULL"))
                conn.commit()

    # Migration: widen resource_id columns for multi-cloud support (PostgreSQL only;
    # SQLite ignores VARCHAR length so ALTER TYPE is not needed there)
    is_postgres = not str(engine.url).startswith("sqlite")
    if is_postgres:
        _pg_widen = [
            ("health_issues", "resource_id", "VARCHAR(500)"),
            ("metric_data_points", "resource_id", "VARCHAR(500)"),
            ("anomalies", "resource_id", "VARCHAR(500)"),
            ("anomalies", "region", "VARCHAR(50)"),
            ("alert_events", "resource_hint", "VARCHAR(500)"),
        ]
        for tbl, col, new_type in _pg_widen:
            if insp.has_table(tbl):
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE {new_type}"))
                    conn.commit()

    # Migration: add schedule_type and max_retries columns to schedules if missing
    if insp.has_table("schedules"):
        columns = {col["name"] for col in insp.get_columns("schedules")}
        if "schedule_type" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE schedules ADD COLUMN schedule_type VARCHAR(20) DEFAULT 'recurring'"))
                conn.commit()
        if "max_retries" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE schedules ADD COLUMN max_retries INTEGER DEFAULT 0"))
                conn.commit()

    # Migration: add retry_count column to schedule_executions if missing
    if insp.has_table("schedule_executions"):
        columns = {col["name"] for col in insp.get_columns("schedule_executions")}
        if "retry_count" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE schedule_executions ADD COLUMN retry_count INTEGER DEFAULT 0"))
                conn.commit()

    # Migration: add credential_source_type column to cloud_accounts if missing
    if insp.has_table("cloud_accounts"):
        columns = {col["name"] for col in insp.get_columns("cloud_accounts")}
        if "credential_source_type" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE cloud_accounts ADD COLUMN credential_source_type VARCHAR(20) DEFAULT 'environment'"))
                conn.commit()

    # Migration: backfill credential_source_type from existing credentials content
    if insp.has_table("cloud_accounts"):
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, credentials, credential_source_type FROM cloud_accounts "
                "WHERE credential_source_type = 'environment' OR credential_source_type IS NULL"
            )).fetchall()
            for row in rows:
                creds = row[1] if isinstance(row[1], dict) else (json.loads(row[1]) if row[1] else {})
                if not creds:
                    continue
                # Infer the correct source type from credential content
                inferred = "environment"
                if creds.get("role_arn"):
                    inferred = "assume_role"
                elif creds.get("profile_name"):
                    inferred = "profile"
                elif creds.get("access_key_id") or creds.get("secret_access_key") or creds.get("_encrypted"):
                    inferred = "static_keys"
                if inferred != "environment":
                    conn.execute(text(
                        "UPDATE cloud_accounts SET credential_source_type = :stype WHERE id = :id"
                    ), {"stype": inferred, "id": row[0]})
            conn.commit()

    # Ensure all ORM models are registered in metadata before create_all
    import agenticops.auth.models  # noqa: F401
    import agenticops.audit.models  # noqa: F401
    import agenticops.scheduler.scheduler  # noqa: F401
    import agenticops.notify.notifier  # noqa: F401

    Base.metadata.create_all(engine)

    # Migration: migrate AWSAccount rows → CloudAccount (if aws_accounts exists and cloud_accounts is empty)
    # Re-inspect after create_all to see newly created tables
    insp = inspect(engine)
    if insp.has_table("aws_accounts") and insp.has_table("cloud_accounts"):
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM cloud_accounts")).scalar()
            if count == 0:
                aws_count = conn.execute(text("SELECT COUNT(*) FROM aws_accounts")).scalar()
                if aws_count > 0:
                    conn.execute(text("""
                        INSERT INTO cloud_accounts (name, provider, is_enabled, credentials, regions, labels, created_at, last_scanned_at)
                        SELECT name, 'aws', is_active, json_object('account_id', account_id, 'role_arn', role_arn, 'external_id', external_id),
                               regions, '{}', created_at, last_scanned_at
                        FROM aws_accounts
                    """))
                    conn.commit()

    # Migration: migrate AWSResource rows → CloudResource (if aws_resources exists and cloud_resources is empty)
    if insp.has_table("aws_resources") and insp.has_table("cloud_resources"):
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM cloud_resources")).scalar()
            if count == 0:
                aws_count = conn.execute(text("SELECT COUNT(*) FROM aws_resources")).scalar()
                if aws_count > 0:
                    conn.execute(text("""
                        INSERT INTO cloud_resources (account_id, provider, region, resource_type, resource_id, name, tags, raw_data, status, managed, created_at, updated_at)
                        SELECT ca.id, 'aws', ar.region, ar.resource_type, ar.resource_id,
                               COALESCE(ar.resource_name, ''), ar.tags, ar.resource_metadata,
                               ar.status, ar.managed, ar.created_at, ar.updated_at
                        FROM aws_resources ar
                        JOIN aws_accounts aa ON ar.account_id = aa.id
                        JOIN cloud_accounts ca ON ca.name = aa.name
                    """))
                    conn.commit()

    # Migration: rename old tables to _legacy_* (keep data, stop confusion)
    # Also drop their indexes — SQLite index names are global, so they would
    # collide with identical indexes on the fresh aws_accounts/aws_resources
    # tables that create_all produces from the still-existing ORM classes.
    if insp.has_table("aws_accounts") and not insp.has_table("_legacy_aws_accounts"):
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE aws_accounts RENAME TO _legacy_aws_accounts"))
            conn.commit()
    if insp.has_table("aws_resources") and not insp.has_table("_legacy_aws_resources"):
        with engine.connect() as conn:
            conn.execute(text("DROP INDEX IF EXISTS idx_resource_type_region"))
            conn.execute(text("DROP INDEX IF EXISTS idx_resource_account"))
            conn.execute(text("ALTER TABLE aws_resources RENAME TO _legacy_aws_resources"))
            conn.commit()
    # If legacy tables already exist, make sure stale indexes are gone so
    # create_all can recreate the (empty) aws_resources table without conflict
    if insp.has_table("_legacy_aws_resources"):
        with engine.connect() as conn:
            conn.execute(text("DROP INDEX IF EXISTS idx_resource_type_region"))
            conn.execute(text("DROP INDEX IF EXISTS idx_resource_account"))
            conn.commit()

    # Ensure graph tables exist (used by GraphStore, raw SQL for performance)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unknown',
                resource_type TEXT DEFAULT '',
                raw_json TEXT DEFAULT '{}',
                raw_hash TEXT DEFAULT '',
                vpc_id TEXT DEFAULT '',
                region TEXT DEFAULT '',
                account_id TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                label TEXT DEFAULT '',
                state TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_id, target_id, edge_type)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS graph_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL DEFAULT '',
                snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                node_count INTEGER DEFAULT 0,
                edge_count INTEGER DEFAULT 0,
                nodes_added INTEGER DEFAULT 0,
                nodes_updated INTEGER DEFAULT 0,
                nodes_removed INTEGER DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON graph_nodes(node_type)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_graph_nodes_region ON graph_nodes(region)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_graph_nodes_vpc ON graph_nodes(vpc_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_graph_nodes_updated ON graph_nodes(updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id)"))
        conn.commit()

    # Ensure case_vectors table exists (used by SQLiteVectorStore,
    # created via raw SQL to keep vector storage decoupled from ORM)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS case_vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                vector BLOB NOT NULL,
                resource_type TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(case_id, field_name)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_cv_field_resource
            ON case_vectors(field_name, resource_type)
        """))
        conn.commit()

    return engine


def get_session() -> Session:
    """Get a new database session.

    Note: Prefer using get_db_session() context manager for automatic
    commit/rollback handling.
    """
    SessionLocal = sessionmaker(bind=get_engine())
    return SessionLocal()
