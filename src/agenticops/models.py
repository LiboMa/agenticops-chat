"""SQLAlchemy models for AgenticOps."""

from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from typing import Optional, Generator

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
from sqlalchemy.pool import StaticPool

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

        # For SQLite, use StaticPool for thread safety
        # For other databases, use standard pooling
        if settings.database_url.startswith("sqlite"):
            _engine = create_engine(
                settings.database_url,
                echo=False,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    resources: Mapped[list["AWSResource"]] = relationship(back_populates="account")
    monitoring_configs: Mapped[list["MonitoringConfig"]] = relationship(back_populates="account")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    account: Mapped["AWSAccount"] = relationship(back_populates="resources")


# ============================================================================
# Monitoring Configuration (MONITOR)
# ============================================================================


class MonitoringConfig(Base):
    """Monitoring configuration per account/service."""

    __tablename__ = "monitoring_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("aws_accounts.id"))
    service_type: Mapped[str] = mapped_column(String(50))  # e.g., EC2, Lambda
    is_enabled: Mapped[bool] = mapped_column(default=True)
    metrics_config: Mapped[dict] = mapped_column(JSON, default=dict)  # Which metrics to collect
    logs_config: Mapped[dict] = mapped_column(JSON, default=dict)  # Log group patterns
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)  # Alert thresholds
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    account: Mapped["AWSAccount"] = relationship(back_populates="monitoring_configs")


class MetricDataPoint(Base):
    """Stored CloudWatch metric data points."""

    __tablename__ = "metric_data_points"
    __table_args__ = (Index("idx_metric_timestamp", "resource_id", "metric_name", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(100))
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
    resource_id: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(50))
    region: Mapped[str] = mapped_column(String(20))
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
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    health_issue: Mapped["HealthIssue"] = relationship(back_populates="rca_results")


# ============================================================================
# Health Issues (DETECT Agent)
# ============================================================================


# ── HealthIssue State Machine ────────────────────────────────────────

VALID_ISSUE_STATUSES = {
    "open", "investigating", "acknowledged", "root_cause_identified",
    "fix_planned", "fix_approved", "fix_executing", "fix_executed", "resolved",
}

# Allowed transitions: from_status -> {to_status, ...}
_ISSUE_TRANSITIONS: dict[str, set[str]] = {
    "open":                   {"investigating", "acknowledged", "resolved"},
    "investigating":          {"acknowledged", "root_cause_identified", "fix_planned", "resolved"},
    "acknowledged":           {"investigating", "root_cause_identified", "fix_planned", "resolved"},
    "root_cause_identified":  {"fix_planned", "resolved"},
    "fix_planned":            {"fix_approved", "resolved"},
    "fix_approved":           {"fix_executing", "resolved"},
    "fix_executing":          {"fix_executed", "resolved"},
    "fix_executed":           {"resolved"},
    "resolved":               set(),  # terminal state
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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(200))  # AWS resource ID
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
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    detected_by: Mapped[str] = mapped_column(String(50), default="detect_agent")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    health_issue: Mapped["HealthIssue"] = relationship(back_populates="fix_plans")
    rca_result: Mapped["RCAResult"] = relationship()
    fix_executions: Mapped[list["FixExecution"]] = relationship(back_populates="fix_plan")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    fix_plan: Mapped["FixPlan"] = relationship(back_populates="fix_executions")
    health_issue: Mapped["HealthIssue"] = relationship(back_populates="fix_executions")


# ============================================================================
# Agent Audit Log
# ============================================================================


class AgentLog(Base):
    """Agent execution audit trail."""

    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(100))
    input_summary: Mapped[str] = mapped_column(Text)
    output_summary: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    resource_hint: Mapped[str] = mapped_column(String(200), default="")  # best-effort resource ID
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    health_issue_id: Mapped[Optional[int]] = mapped_column(nullable=True)  # linked HealthIssue
    status: Mapped[str] = mapped_column(String(30), default="received")  # received, processed, ignored, error
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatSession(Base):
    """Chat session for web UI."""
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ============================================================================
# Database Session Management
# ============================================================================


def init_db():
    """Initialize database and create all tables.

    Includes migration: if rca_results table has the old anomaly_id column
    (from the deprecated Anomaly FK), drop and recreate it with the new schema.
    """
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

    Base.metadata.create_all(engine)

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
