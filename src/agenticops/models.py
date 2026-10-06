"""SQLAlchemy models for AgenticOps."""

import json
import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Generator

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
from sqlalchemy.pool import NullPool, StaticPool

from agenticops.config import settings

logger = logging.getLogger(__name__)


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


# Secret-redaction at the DB write boundary: scrub AWS keys / AK-SK / passwords
# / private keys out of every String/Text/JSON column before any flush. Listens
# on the base Session class so all sessionmakers are covered. Idempotent.
from agenticops.security.db_redaction import install_db_redaction  # noqa: E402

install_db_redaction()


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
    # MVP-2.6.1: set by connectors/ingest or scanner/engine when a complete listing no longer sees the row;
    # cleared when a writer sees it again (services/inventory.mark_seen). Rows are never deleted.
    absent_since: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # MVP-2.6.1: set by connectors/ingest when an existing row's content hash moves (never on create); read by
    # graph/evidence as "changed in the RCA window". Rows written only by the scan path stay NULL.
    content_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    account: Mapped["CloudAccount"] = relationship(back_populates="resources")


class ConnectorRun(Base):
    """One pull-connector run over one target (MVP-2.6.1 spec §3.B.2), written by connectors.ingest.

    status: complete (every kind listed completely) | partial (some kind failed or hit the byte cap) |
    failed (nothing collected). per_kind: {resource_type: {"complete": bool, "count": int}}."""

    __tablename__ = "connector_runs"
    __table_args__ = (Index("idx_connector_run_target", "connector", "account_id", "scope", "finished_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connector: Mapped[str] = mapped_column(String(50))
    account_id: Mapped[Optional[int]] = mapped_column(nullable=True)  # cloud_accounts.id
    scope: Mapped[str] = mapped_column(String(200), default="")      # e.g. the cluster name
    trigger: Mapped[str] = mapped_column(String(20))                 # schedule | manual | rca
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10))
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    per_kind: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
    # ── RCA Quality (MVP-2.2.0) ──
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # [{type, ref, summary}]
    evidence_verified: Mapped[Optional[bool]] = mapped_column(nullable=True)  # deterministic check vs tool trace
    critic_verdict: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # supported|weak|refuted|disputed_by_execution
    critic_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    human_verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # correct|incorrect
    human_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # ── Root-cause location (MVP-2.6.1) — observed only: the critic, the gate and auto-fix never read it ──
    location: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # validated candidates + inline path
    location_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="absent")  # valid|partial|invalid|absent
    location_build_id: Mapped[Optional[int]] = mapped_column(nullable=True)  # the graph build the path was checked against
    location_verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # correct|partial|incorrect
    location_verdict_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location_verdict_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

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
    # investigating back-edge: legal RCA re-run on an already-analyzed issue
    "root_cause_identified":  {"investigating", "fix_planned", "resolved", "dismissed"},
    "fix_planned":            {"fix_approved", "resolved", "dismissed"},
    # root_cause_identified back-edges (MVP-2.6.1): the fix never ran (content changed after approval), the run
    # failed, or verification failed / acceptance was rejected — the issue can get a new fix plan
    "fix_approved":           {"fix_executing", "root_cause_identified", "resolved", "dismissed"},
    "fix_executing":          {"fix_executed", "root_cause_identified", "resolved", "dismissed"},
    "fix_executed":           {"root_cause_identified", "resolved", "dismissed"},
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
        Index("idx_health_issue_type", "issue_type"),
        Index("idx_health_issue_resource_ref", "resource_ref"),
        Index("idx_health_issue_anchor_status", "anchor_status"),
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
    # Issue type classification (Signal Gate identity component, MVP-2.2.0)
    issue_type: Mapped[str] = mapped_column(String(40), default="other")
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
    # MVP-2.6.1 graph anchoring (services/identity_resolver): the one physical resource this issue is about
    resource_ref: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cloud_resources.id", ondelete="SET NULL"), nullable=True
    )
    anchor_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # anchored|ambiguous|account_level|unanchored
    anchor_candidates: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {"rule": ..., "candidates": [...]}
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # fault time reported by the source

    # Relationships
    rca_results: Mapped[list["RCAResult"]] = relationship(back_populates="health_issue")
    fix_plans: Mapped[list["FixPlan"]] = relationship(back_populates="health_issue")
    fix_executions: Mapped[list["FixExecution"]] = relationship(back_populates="health_issue")


# ============================================================================
# Change Requests (MVP-2.6.0 Change Management)
# ============================================================================


class ChangeRequest(Base):
    """ITSM change ticket: who wants what changed, reviewed by SRE, approved, executed via a Plan."""

    __tablename__ = "change_requests"
    __table_args__ = (
        Index("idx_change_request_status", "status"),
        Index("idx_change_request_requested_by", "requested_by"),
        Index("idx_change_request_account", "account_id"),
        Index("idx_change_request_created", "created_at"),
        Index("idx_change_request_external", "external_system", "external_ticket_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    justification: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="api")  # chat|web|cli|im|webhook|api
    requested_by: Mapped[str] = mapped_column(String(255))  # actor key, e.g. user:<email> (users.email is 255)
    requester_user_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=True)
    target_hints: Mapped[list] = mapped_column(JSON, default=list)  # raw strings the requester typed (ids/ARNs/names)
    target_resources: Mapped[list] = mapped_column(JSON, default=list)  # GROUNDED only: [{resource_id, resource_type, db_id, region, evidence}]
    requested_change_type: Mapped[str] = mapped_column(String(20), default="normal")  # normal|emergency
    effective_change_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # standard|normal|emergency
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # L0-L3
    action_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # tag|scale|config|network|iam|delete|other
    status: Mapped[str] = mapped_column(String(30), default="draft")
    review_verdict: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)
    review_attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # bumped on every → under_review; keys rollbacks
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    policy_rule: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    policy_action: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approver_user_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approval_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    chat_session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # MVP-2.6.1 (spec §3.D.2): the requester's own steps (fix_plans.steps shape) and where the request came from.
    # external_system / external_ticket_id are external_ref split out for the dedup lookup (indexed together).
    proposed_steps: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    external_ref: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {system, ticket_id, url?, requested_by?}
    external_system: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    external_ticket_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    steps_diff: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # code-computed at review, never by an LLM
    needs_review_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # why it waits for a human verdict

    # Relationships
    plans: Mapped[list["FixPlan"]] = relationship(back_populates="change_request")


# ============================================================================
# Fix Plans (SRE Agent)
# ============================================================================


class FixPlan(Base):
    """Structured plans. plan_kind='fix' (from HealthIssue+RCA) or 'change' (from a ChangeRequest)."""

    __tablename__ = "fix_plans"
    __table_args__ = (
        Index("idx_fix_plan_kind", "plan_kind"),
        Index("idx_fix_plan_change_request", "change_request_id"),
        CheckConstraint(
            "(plan_kind = 'fix' AND health_issue_id IS NOT NULL AND rca_result_id IS NOT NULL "
            "AND change_request_id IS NULL) OR "
            "(plan_kind = 'change' AND change_request_id IS NOT NULL AND health_issue_id IS NULL "
            "AND rca_result_id IS NULL)",
            name="ck_fix_plans_origin",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_kind: Mapped[str] = mapped_column(String(10), default="fix", server_default="fix")
    health_issue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("health_issues.id"), nullable=True)
    rca_result_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rca_results.id"), nullable=True)
    change_request_id: Mapped[Optional[int]] = mapped_column(ForeignKey("change_requests.id"), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20))  # L0, L1, L2, L3
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # ordered steps
    rollback_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_impact: Mapped[str] = mapped_column(Text, default="")
    pre_checks: Mapped[list] = mapped_column(JSON, default=list)
    post_checks: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    # Lifecycle (validate_plan_transition): draft -> pending_approval -> approved -> executing -> executed | failed | rejected
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Content identity (MVP-2.6.1, services/plan_content): the version moves when the executable content changes;
    # an approval records the hash and version it approved, and a plan that no longer matches them is not run
    plan_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approved_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approved_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    health_issue: Mapped[Optional["HealthIssue"]] = relationship(back_populates="fix_plans")
    rca_result: Mapped[Optional["RCAResult"]] = relationship()
    change_request: Mapped[Optional["ChangeRequest"]] = relationship(back_populates="plans")
    fix_executions: Mapped[list["FixExecution"]] = relationship(back_populates="fix_plan")


# FixPlan status sets for dedup/replace logic
FIXPLAN_TERMINAL_STATUSES = {"executed", "failed", "rejected"}
FIXPLAN_REPLACEABLE_STATUSES = {"draft"}
FIXPLAN_LOCKED_STATUSES = {"pending_approval", "approved", "executing"}


# ── FixPlan state machine (MVP-2.6.0) ─────────────────────────────────
# Applies to BOTH plan kinds (fix | change). Replaces the direct status
# assignments that used to live in metadata_tools / pipeline_service /
# app.py / cli. Terminal: executed, failed, rejected.

VALID_PLAN_STATUSES = {
    "draft", "pending_approval", "approved", "executing", "executed", "failed", "rejected",
}

PLAN_TRANSITIONS: dict[str, set[str]] = {
    "draft":            {"pending_approval", "approved", "rejected"},
    "pending_approval": {"approved", "rejected"},
    "approved":         {"executing", "rejected"},   # rejected from approved = withdrawn before execution
    "executing":        {"executed", "failed"},
    "executed":         set(),
    "failed":           set(),
    "rejected":         set(),
}


def validate_plan_transition(current: str, new: str) -> None:
    """Validate a FixPlan status transition (raises InvalidStatusTransition / ValueError)."""
    if new not in VALID_PLAN_STATUSES:
        raise ValueError(f"Invalid plan status '{new}'. Valid: {', '.join(sorted(VALID_PLAN_STATUSES))}")
    if current == new:
        return
    allowed = PLAN_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise InvalidStatusTransition(
            f"Cannot transition plan from '{current}' to '{new}'. "
            f"Allowed from '{current}': {', '.join(sorted(allowed)) or 'none (terminal)'}"
        )


class PlanStatusConflict(InvalidStatusTransition):
    """The plan is no longer in the status the caller read — another request moved it first (409)."""


def _persistent_session(obj):
    """The session `obj` is persistent in, or None (a new / detached / unmapped object: nothing to guard)."""
    from sqlalchemy import inspect as sa_inspect
    if not isinstance(obj, Base):  # a stand-in (tests' mocks) has no row to guard; inspect() does not refuse those
        return None
    state = sa_inspect(obj)
    return state.session if state.persistent else None


def transition_plan(plan, new_status: str) -> None:
    """Validate and apply a FixPlan status change; stamps updated_at. A persistent plan moves with
    UPDATE … WHERE status=<the status it was read in> (MVP-2.7.0 S3): 0 rows = a concurrent writer won →
    PlanStatusConflict, so two approvals (or an approve racing a reject) cannot both land."""
    validate_plan_transition(plan.status, new_status)
    now = datetime.now(timezone.utc)
    old = plan.status
    session = _persistent_session(plan) if old != new_status else None
    if session is not None:
        moved = (session.query(type(plan))
                 .filter(type(plan).id == plan.id, type(plan).status == old)
                 .update({"status": new_status, "updated_at": now}, synchronize_session=False))
        if not moved:
            raise PlanStatusConflict(f"Plan #{plan.id} is no longer '{old}' (concurrent transition)")
    plan.status = new_status
    plan.updated_at = now


# ── ChangeRequest (MVP-2.6.0 Change Management) ───────────────────────

VALID_CHANGE_STATUSES = {
    "draft", "under_review", "needs_clarification", "planned", "approved",
    "executing", "needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled",
}
CHANGE_TERMINAL_STATUSES = {"completed", "failed", "rolled_back", "rejected", "cancelled"}

CHANGE_TRANSITIONS: dict[str, set[str]] = {
    "draft":               {"under_review", "cancelled"},
    "under_review":        {"planned", "needs_clarification", "rejected", "draft"},  # draft = watchdog rollback
    "needs_clarification": {"under_review", "cancelled"},
    "planned":             {"approved", "rejected", "cancelled"},
    "approved":            {"executing", "cancelled"},
    "executing":           {"completed", "failed", "rolled_back", "needs_review"},
    "needs_review":        {"completed", "failed"},  # human verdict; a redo is a NEW change request
    "completed":           set(),
    "failed":              set(),
    "rolled_back":         set(),
    "rejected":            set(),
    "cancelled":           set(),
}


def validate_change_transition(current: str, new: str) -> None:
    """Validate a ChangeRequest status transition (raises InvalidStatusTransition / ValueError)."""
    if new not in VALID_CHANGE_STATUSES:
        raise ValueError(f"Invalid change status '{new}'. Valid: {', '.join(sorted(VALID_CHANGE_STATUSES))}")
    if current == new:
        return
    allowed = CHANGE_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise InvalidStatusTransition(
            f"Cannot transition change from '{current}' to '{new}'. "
            f"Allowed from '{current}': {', '.join(sorted(allowed)) or 'none (terminal)'}"
        )


def transition_change(cr, new_status: str) -> None:
    """Validate and apply a ChangeRequest status change; stamps updated_at / closed_at."""
    validate_change_transition(cr.status, new_status)
    cr.status = new_status
    now = datetime.now(timezone.utc)
    cr.updated_at = now
    if new_status in CHANGE_TERMINAL_STATUSES:
        cr.closed_at = now


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
    health_issue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("health_issues.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # Lifecycle: pending -> running -> succeeded | failed | rolled_back | aborted
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    executed_by: Mapped[str] = mapped_column(String(255), default="executor_agent")
    pre_check_results: Mapped[list] = mapped_column(JSON, default=list)
    step_results: Mapped[list] = mapped_column(JSON, default=list)
    post_check_results: Mapped[list] = mapped_column(JSON, default=list)
    rollback_results: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(default=0)
    # MVP-2.6.1 verification (services/verification.py): passed | failed | pending_acceptance, and why.
    # NULL = no verdict (a run closed without a result: cancel / watchdog / crash, or a pre-2.6.1 row).
    verification_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    verification_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The human acceptance of a pending_acceptance run (the identity-bound actor key, when, and why)
    accepted_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    acceptance_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    fix_plan: Mapped["FixPlan"] = relationship(back_populates="fix_executions")
    health_issue: Mapped[Optional["HealthIssue"]] = relationship(back_populates="fix_executions")


# ============================================================================
# Pipeline Event Timeline
# ============================================================================


class PipelineEvent(Base):
    """Timeline event log for HealthIssue AND ChangeRequest lifecycles (exactly one id set)."""

    __tablename__ = "pipeline_events"
    __table_args__ = (
        Index("idx_pipeline_event_issue", "health_issue_id"),
        Index("idx_pipeline_event_change", "change_request_id"),
        Index("idx_pipeline_event_time", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    health_issue_id: Mapped[Optional[int]] = mapped_column(nullable=True, index=True)
    change_request_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    duration_ms: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    trace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)


# ============================================================================
# Command Audit (MVP-2.6.0) — tool-layer ledger of write-tier commands
# ============================================================================


class CommandAudit(Base):
    """One row per write/unknown/blocked command attempt made by run_aws_cli / run_on_host /
    run_kubectl / run_skill_script. Read-only commands are NOT recorded."""

    __tablename__ = "command_audits"
    __table_args__ = (
        Index("idx_command_audit_created", "created_at"),
        Index("idx_command_audit_actor", "actor"),
        Index("idx_command_audit_outcome", "outcome"),
        Index("idx_command_audit_plan", "fix_plan_id"),
        Index("idx_command_audit_change", "change_request_id"),
        Index("idx_command_audit_trace", "trace_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    actor: Mapped[str] = mapped_column(String(255), default="system")
    actor_user_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    agent_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tool: Mapped[str] = mapped_column(String(30))  # run_aws_cli|run_on_host|run_kubectl|run_skill_script
    tier: Mapped[str] = mapped_column(String(10))  # write|unknown|blocked|script
    account: Mapped[str] = mapped_column(String(100), default="")
    region: Mapped[str] = mapped_column(String(30), default="")
    target: Mapped[str] = mapped_column(String(200), default="")  # host id / cluster / skill
    command: Mapped[str] = mapped_column(Text)  # redacted
    outcome: Mapped[str] = mapped_column(String(10))  # executed|refused|blocked|error
    reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # confirmation|change_required|...
    exit_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    output_excerpt: Mapped[str] = mapped_column(Text, default="")  # redacted, <= 2000 chars
    duration_ms: Mapped[int] = mapped_column(default=0)
    trace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    fix_plan_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    change_request_id: Mapped[Optional[int]] = mapped_column(nullable=True)


# ============================================================================
# ITSM Links (MVP-2.0.0)
# ============================================================================


class ITSMLink(Base):
    """Mapping of an internal entity to its external ITSM record (idempotency key).

    entity_type: health_issue | fix_plan
    record_type: incident | change
    """

    __tablename__ = "itsm_links"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", "system", "record_type",
            name="uq_itsm_link_entity_system",
        ),
        Index("idx_itsm_link_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int] = mapped_column()
    system: Mapped[str] = mapped_column(String(30))  # servicenow | jira
    record_type: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(200))   # sys_id / issue key
    external_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # INC0010002 / OPS-42
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


# ============================================================================
# Agent Audit Log
# ============================================================================


class AgentLog(Base):
    """Agent execution audit trail."""

    __tablename__ = "agent_logs"
    __table_args__ = (
        Index("idx_agent_log_trace", "trace_id"),
        Index("idx_agent_log_agent_time", "agent_name", "created_at"),
        Index("idx_agent_log_actor_time", "actor_type", "created_at"),
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
    cache_write_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    actor_type: Mapped[str] = mapped_column(String(20), default="system")
    actor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    parent_agent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    """Signal ledger row — every inbound event (webhook alert, agent detection,
    REST create, resolution notice) with its Signal Gate disposition.

    Historically webhook-only ("alert event"); MVP-2.2.0 generalizes it into
    the unified Signal record behind the Signals view.
    """

    __tablename__ = "alert_events"
    __table_args__ = (
        Index("idx_alert_source_dedup", "source", "external_id"),
        Index("idx_alert_fingerprint_time", "fingerprint", "received_at"),
        Index("idx_alert_disposition", "disposition"),
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
    # ── Signal Gate (MVP-2.2.0) ──
    kind: Mapped[str] = mapped_column(String(20), default="alert")  # alert|detection|resolution|manual
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # structured identity v2
    resource_id: Mapped[str] = mapped_column(String(500), default="")  # normalized resource ID
    account_id: Mapped[str] = mapped_column(String(100), default="")
    issue_type: Mapped[str] = mapped_column(String(40), default="other")
    disposition: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # promoted|merged|noise|error
    disposition_reason: Mapped[str] = mapped_column(String(200), default="")
    gate_evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # rules hit, candidates, LLM verdict


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

    # Per-session main-agent model override; NULL = Auto (follow global config)
    model_id: Mapped[Optional[str]] = mapped_column(String(200), default=None)

    # Per-session effort (thinking) override: off|standard|deep; NULL = Auto
    effort: Mapped[Optional[str]] = mapped_column(String(20), default=None)

    # Who may see it (MVP-2.7.0, services/chat_access): `private` = its owner and admins, `workspace` = everyone.
    # NULL owner = no single owner — pre-2.7.0 rows, and sessions made with auth off, from IM or from the CLI.
    owner_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    visibility: Mapped[str] = mapped_column(String(16), default="workspace", server_default="workspace")


class Installation(Base):
    """This installation's non-secret identity (MVP-2.7.0, `deployment_id` in GET /api/ui/bootstrap): one row,
    random, kept in the database so it survives a container whose data_dir is ephemeral."""
    __tablename__ = "installation"

    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    deployment_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ChatMessage(Base):
    """Individual message in a chat session."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    attachments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Suggestion chips extracted from the reply tail (MVP-2.0.1); NULL = none
    suggestions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
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


# DEPRECATED (frozen cycle② 2026-05-31): kept for existing data/endpoints; no new writes.
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


# DEPRECATED (frozen cycle② 2026-05-31): kept for existing data/endpoints; no new writes.
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


# ── MVP-2.6.0 migration helpers ───────────────────────────────────────

_NULLABLE_ORIGIN_COLUMNS: dict[str, tuple[str, ...]] = {
    "fix_plans": ("health_issue_id", "rca_result_id"),
    "fix_executions": ("health_issue_id",),
    "pipeline_events": ("health_issue_id",),
}

# table → {column: extra DDL clause or None}. The column TYPE is deliberately not spelled
# here: it is compiled from the ORM column for the engine's dialect (SQLite DATETIME vs
# PostgreSQL TIMESTAMP WITHOUT TIME ZONE), so both paths share one source of truth.
_ADD_COLUMNS_2_6_0: dict[str, dict[str, Optional[str]]] = {
    "fix_plans": {
        "plan_kind": "DEFAULT 'fix'",
        "change_request_id": None,
        "rejected_by": None,
        "rejected_at": None,
        "rejection_reason": None,
        "updated_at": None,
    },
    "pipeline_events": {"change_request_id": None},
    "audit_logs": {"actor": None},
    "change_requests": {"review_attempt": "DEFAULT 0 NOT NULL"},
}

# Actor-key columns (`user:<email>`; users.email is String(255)) widened from VARCHAR(100) in the fix wave (M-2).
# SQLite ignores VARCHAR lengths (no rebuild); PostgreSQL gets a metadata-only ALTER COLUMN TYPE per column.
_ACTOR_KEY_COLUMNS_2_6_0: dict[str, tuple[str, ...]] = {
    "fix_plans": ("approved_by", "rejected_by"),
    "fix_executions": ("executed_by",),
    "change_requests": ("requested_by", "reviewed_by", "approved_by", "rejected_by"),
    "command_audits": ("actor", "on_behalf_of"),
    "audit_logs": ("actor",),
}
_ACTOR_KEY_WIDTH = 255

_INDEXES_2_6_0: tuple[tuple[str, str, str], ...] = (  # (table, index, column)
    ("fix_plans", "idx_fix_plan_kind", "plan_kind"),
    ("fix_plans", "idx_fix_plan_change_request", "change_request_id"),
    ("pipeline_events", "idx_pipeline_event_change", "change_request_id"),
    ("audit_logs", "ix_audit_logs_actor", "actor"),
)

_CK_FIX_PLANS_ORIGIN_SQL = (
    "(plan_kind = 'fix' AND health_issue_id IS NOT NULL AND rca_result_id IS NOT NULL AND change_request_id IS NULL) OR "
    "(plan_kind = 'change' AND change_request_id IS NOT NULL AND health_issue_id IS NULL AND rca_result_id IS NULL)"
)

# Once per process per database URL (I-2): init_db() is a runtime hot path, so the 2.6.0 pass must not
# re-issue its DDL/DML on every call. Marked only after a SUCCESSFUL pass — a failure retries next time.
_migrated_2_6_0_urls: set[str] = set()
_migrate_2_6_0_lock = threading.Lock()


def _add_column_ddl(dialect, table_name: str, col: str, extra: Optional[str]) -> str:
    """`<col> <type>[ <extra>]` for ADD COLUMN, type compiled from the ORM column for `dialect`."""
    col_type = Base.metadata.tables[table_name].c[col].type.compile(dialect=dialect)
    return f"{col} {col_type}" + (f" {extra}" if extra else "")


def _sqlite_notnull_columns(engine, table_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {r[1] for r in rows if r[3]}


def _backup_sqlite_file(engine) -> Optional[str]:
    """Snapshot the SQLite file to <db>.bak-pre-2.6.0 once (before the first table rebuild).

    An online backup (sqlite3.Connection.backup — a consistent snapshot even while another process is
    mid-write; a plain file copy can tear in rollback-journal mode) written to a temp name in the same
    directory and published with os.replace, so the final name is never a half-written file.
    Idempotent: an existing backup is kept as is."""
    import shutil
    import sqlite3
    import tempfile
    db_path = engine.url.database
    if not db_path or db_path == ":memory:":
        return None
    bak = f"{db_path}.bak-pre-2.6.0"
    if os.path.exists(bak) or not os.path.exists(db_path):
        return bak
    fd, tmp = tempfile.mkstemp(prefix=".bak-pre-2.6.0.", dir=os.path.dirname(os.path.abspath(db_path)))
    os.close(fd)
    try:
        src, dst = sqlite3.connect(db_path), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        shutil.copymode(db_path, tmp)  # mkstemp gives 0600; keep the database file's own mode (as copy2 did)
        os.replace(tmp, bak)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info("Pre-2.6.0 database backup written to %s", bak)
    return bak


def _sqlite_rebuild_table(engine, table) -> None:
    """sqlite.org 'other kinds of ALTER': create <t>__new from the ORM metadata (no indexes),
    copy the common columns, drop the old table (drops its indexes), rename new → old name
    (this direction leaves other tables' FK references pointing at the surviving name), then
    recreate the indexes. FK enforcement is off in this project, so no PRAGMA dance is needed."""
    from sqlalchemy import MetaData

    tmp_name = f"{table.name}__new"
    tmp_meta = MetaData()
    tmp_table = table.to_metadata(tmp_meta, name=tmp_name)
    for idx in list(tmp_table.indexes):
        tmp_table.indexes.discard(idx)
    # The CREATE TABLE DDL resolves each FK target through tmp_meta, so the referenced
    # tables must exist there as metadata copies (nothing is emitted for them).
    for fk in table.foreign_keys:
        if fk.column.table.name not in tmp_meta.tables:
            fk.column.table.to_metadata(tmp_meta)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {tmp_name}"))
        tmp_table.create(conn)
        old_cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table.name})")).fetchall()}
        common = [c.name for c in table.columns if c.name in old_cols]
        cols_sql = ", ".join(common)
        conn.execute(text(f"INSERT INTO {tmp_name} ({cols_sql}) SELECT {cols_sql} FROM {table.name}"))
        conn.execute(text(f"DROP TABLE {table.name}"))
        conn.execute(text(f"ALTER TABLE {tmp_name} RENAME TO {table.name}"))
        for idx in table.indexes:
            idx.create(conn)
    logger.info("Rebuilt table %s with relaxed NOT NULL constraints (MVP-2.6.0)", table.name)


def _pg_migration_statements(insp, dialect, existing_constraints: set[str]) -> list[str]:
    """PostgreSQL DDL/DML for MVP-2.6.0, gated on the live catalog (`insp` = sqlalchemy.inspect(engine)):
    only what is missing is emitted, so a migrated database gets an EMPTY list — no ACCESS EXCLUSIVE lock
    is taken for work already done. `existing_constraints` are the constraint names on fix_plans
    (pg_constraint scoped by conrelid). Pure: no connection, nothing executed."""
    stmts: list[str] = []

    def columns(table: str) -> dict[str, dict]:
        return {c["name"]: c for c in insp.get_columns(table)}

    # 1. plan-lineage columns become nullable (change plans have no issue / RCA)
    for table, names in _NULLABLE_ORIGIN_COLUMNS.items():
        if not insp.has_table(table):
            continue
        existing = columns(table)
        for col in names:
            if col in existing and not existing[col]["nullable"]:
                stmts.append(f"ALTER TABLE {table} ALTER COLUMN {col} DROP NOT NULL")
    # 2. new columns (types compiled from the ORM for this dialect)
    for table, spec in _ADD_COLUMNS_2_6_0.items():
        if not insp.has_table(table):
            continue
        existing = columns(table)
        for col, extra in spec.items():
            if col not in existing:
                stmts.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {_add_column_ddl(dialect, table, col, extra)}")
    # 3. fix_plans: plan_kind backfill + NOT NULL (M-3), FK to change_requests (M-3), origin CHECK
    if insp.has_table("fix_plans"):
        plan_kind = columns("fix_plans").get("plan_kind")
        if plan_kind is None or plan_kind["nullable"]:  # just added above, or left nullable by an earlier 2.6.0 run
            stmts.append("UPDATE fix_plans SET plan_kind = 'fix' WHERE plan_kind IS NULL")
            stmts.append("ALTER TABLE fix_plans ALTER COLUMN plan_kind SET NOT NULL")
        fks = insp.get_foreign_keys("fix_plans")
        if not any(fk.get("constrained_columns") == ["change_request_id"] for fk in fks):
            stmts.append("ALTER TABLE fix_plans ADD CONSTRAINT fix_plans_change_request_id_fkey "
                         "FOREIGN KEY (change_request_id) REFERENCES change_requests (id)")
        if "ck_fix_plans_origin" not in existing_constraints:
            stmts.append(f"ALTER TABLE fix_plans ADD CONSTRAINT ck_fix_plans_origin CHECK ({_CK_FIX_PLANS_ORIGIN_SQL})")
    # 4. actor-key columns → VARCHAR(255) (M-2; widening varchar is metadata-only on PostgreSQL)
    for table, names in _ACTOR_KEY_COLUMNS_2_6_0.items():
        if not insp.has_table(table):
            continue
        existing = columns(table)
        for col in names:
            length = getattr(existing[col]["type"], "length", None) if col in existing else None
            if length is not None and length < _ACTOR_KEY_WIDTH:
                stmts.append(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE VARCHAR({_ACTOR_KEY_WIDTH})")
    # 5. indexes
    for table, index, col in _INDEXES_2_6_0:
        if insp.has_table(table) and index not in {ix["name"] for ix in insp.get_indexes(table)}:
            stmts.append(f"CREATE INDEX IF NOT EXISTS {index} ON {table}({col})")
    return stmts


def _migrate_2_6_0(engine) -> None:
    """Idempotent MVP-2.6.0 schema migration (runs after create_all) — once per process per database URL.
    Raises on failure (init_db never starts on a half-migrated schema) and then retries on the next call."""
    key = str(engine.url)
    with _migrate_2_6_0_lock:
        if key in _migrated_2_6_0_urls:
            return
        _run_migrate_2_6_0(engine)
        _migrated_2_6_0_urls.add(key)


def _run_migrate_2_6_0(engine) -> None:
    insp = inspect(engine)
    dialect = engine.dialect.name
    if dialect == "sqlite":
        tables = {"fix_plans": FixPlan.__table__, "fix_executions": FixExecution.__table__,
                  "pipeline_events": PipelineEvent.__table__}
        needs_rebuild = [
            name for name, cols in _NULLABLE_ORIGIN_COLUMNS.items()
            if insp.has_table(name) and any(c in _sqlite_notnull_columns(engine, name) for c in cols)
        ]
        if needs_rebuild:
            _backup_sqlite_file(engine)
            for name in needs_rebuild:
                _sqlite_rebuild_table(engine, tables[name])
            insp = inspect(engine)
        # Any column still missing (e.g. table rebuilt by an older run) → plain ADD COLUMN
        for tbl, cols in _ADD_COLUMNS_2_6_0.items():
            if not insp.has_table(tbl):
                continue
            existing = {c["name"] for c in insp.get_columns(tbl)}
            with engine.begin() as conn:
                for col, extra in cols.items():
                    if col not in existing:
                        conn.execute(text(
                            f"ALTER TABLE {tbl} ADD COLUMN {_add_column_ddl(engine.dialect, tbl, col, extra)}"
                        ))
                if tbl == "fix_plans":
                    conn.execute(text("UPDATE fix_plans SET plan_kind = 'fix' WHERE plan_kind IS NULL"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fix_plan_kind ON fix_plans(plan_kind)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fix_plan_change_request ON fix_plans(change_request_id)"))
                if tbl == "pipeline_events":
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_pipeline_event_change ON pipeline_events(change_request_id)"))
                if tbl == "audit_logs":
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_logs_actor ON audit_logs(actor)"))
    elif dialect == "postgresql":
        with engine.begin() as conn:
            existing_constraints: set[str] = set()
            if insp.has_table("fix_plans"):
                existing_constraints = {r[0] for r in conn.execute(text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'fix_plans'::regclass"
                )).fetchall()}
            for stmt in _pg_migration_statements(insp, engine.dialect, existing_constraints):
                conn.execute(text(stmt))


# ── MVP-2.6.1 migration: graph anchoring columns + relation-build marker ──────────────────────────────
# New tables (resource_relations) are already made by init_db's create_all; on an existing table create_all
# skips both the table and its indexes, so this pass only adds columns and indexes, then runs backfills.
# Plans B/C/D append their own columns/indexes to these two tables instead of adding migration functions.
_ADD_COLUMNS_2_6_1: dict[str, dict[str, Optional[str]]] = {
    "health_issues": {
        "resource_ref": "REFERENCES cloud_resources(id) ON DELETE SET NULL",
        "anchor_status": None,
        "anchor_candidates": None,
        "observed_at": None,
    },
    "cloud_resources": {"absent_since": None, "content_changed_at": None},
    "galaxy_builds": {"rules_published_at": None},
    "rca_results": {"location": None, "location_status": None, "location_build_id": None, "location_verdict": None,
                    "location_verdict_by": None, "location_verdict_at": None},
    "fix_plans": {"plan_version": "NOT NULL DEFAULT 1", "content_hash": None, "approved_hash": None,
                  "approved_version": None},
    "change_requests": {"proposed_steps": None, "external_ref": None, "external_system": None,
                        "external_ticket_id": None, "steps_diff": None, "needs_review_reason": None},
    "fix_executions": {"verification_status": None, "verification_reason": None, "accepted_by": None,
                       "accepted_at": None, "acceptance_note": None},
}

_INDEXES_2_6_1: tuple[tuple[str, str, str], ...] = (  # (table, index, columns)
    ("health_issues", "idx_health_issue_resource_ref", "resource_ref"),
    ("health_issues", "idx_health_issue_anchor_status", "anchor_status"),
    ("change_requests", "idx_change_request_external", "external_system, external_ticket_id"),
)

_migrated_2_6_1_urls: set[str] = set()
_migrate_2_6_1_lock = threading.Lock()


def _statements_2_6_1(insp, dialect) -> list[str]:
    """DDL still needed to bring an existing database to the 2.6.1 shape. Pure (inspector + dialect in,
    statements out) so the PostgreSQL branch is testable without a server; empty once migrated."""
    guard = " IF NOT EXISTS" if dialect.name == "postgresql" else ""
    stmts: list[str] = []
    for tbl, cols in _ADD_COLUMNS_2_6_1.items():
        if not insp.has_table(tbl):
            continue
        existing = {c["name"] for c in insp.get_columns(tbl)}
        for col, extra in cols.items():
            if col not in existing:
                stmts.append(f"ALTER TABLE {tbl} ADD COLUMN{guard} {_add_column_ddl(dialect, tbl, col, extra)}")
    for tbl, index, cols in _INDEXES_2_6_1:
        if insp.has_table(tbl) and index not in {ix["name"] for ix in insp.get_indexes(tbl)}:
            stmts.append(f"CREATE INDEX IF NOT EXISTS {index} ON {tbl}({cols})")
    return stmts


def _backfill_anchors_2_6_1(engine) -> None:
    """Spec §4 backfill 2: anchor every issue that has never been through the resolver. Column-level query and
    UPDATE, so a later release's HealthIssue columns (added after this runs) cannot break it. A NULL account
    stays inside the account the issue's signal stated (issue_account_claim, as reanchor_open_issues does).
    Fail-soft: an anchor is an enrichment — a failure logs and leaves anchor_status NULL for
    reanchor_open_issues."""
    try:
        from agenticops.services.identity_resolver import issue_account_claim, resolve

        with Session(engine) as session:
            rows = session.query(
                HealthIssue.id, HealthIssue.resource_id, HealthIssue.account_id, HealthIssue.provider,
                HealthIssue.alarm_name, HealthIssue.metric_data, HealthIssue.anchor_candidates,
            ).filter(HealthIssue.anchor_status.is_(None)).all()
            for row in rows:
                md = row.metric_data if isinstance(row.metric_data, dict) else {}
                claim, search_all = issue_account_claim(session, row.id, row.account_id, row.anchor_candidates)
                anchor = resolve(session, account_id=claim, provider=row.provider, resource_id=row.resource_id,
                                 hints=md.get("hints"), alarm_name=row.alarm_name, search_all_accounts=search_all)
                values = {"resource_ref": anchor.resource_ref, "anchor_status": anchor.status,
                          "anchor_candidates": anchor.audit()}
                if row.account_id is None and anchor.account_id is not None:
                    values["account_id"] = anchor.account_id
                session.query(HealthIssue).filter(HealthIssue.id == row.id).update(values, synchronize_session=False)
                if "account_id" in values:
                    _restamp_hashed_plans_2_6_1(session, row.id, anchor.account_id)
            session.commit()
    except Exception as exc:
        logger.warning("MVP-2.6.1 anchor backfill skipped: %s", exc)


def _restamp_hashed_plans_2_6_1(session, issue_id: int, account_id: int) -> None:
    """plan_content.restamp_issue_plans, column-level like the backfills: the account is plan content, so a live
    plan hashed before its issue had one gets the next version. An unhashed plan is left to
    _backfill_plan_hashes_2_6_1 (it hashes with this account, and gives an approved plan its approved hash)."""
    from agenticops.services.plan_content import content_hash

    rows = session.query(FixPlan.id, FixPlan.plan_version, FixPlan.content_hash, FixPlan.steps, FixPlan.rollback_plan,
                         FixPlan.pre_checks, FixPlan.post_checks, FixPlan.risk_level).filter(
        FixPlan.health_issue_id == issue_id, FixPlan.content_hash.isnot(None),
        FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES)).all()
    for row in rows:
        digest = content_hash(steps=row.steps, rollback_plan=row.rollback_plan, pre_checks=row.pre_checks,
                              post_checks=row.post_checks, account_id=account_id, risk_level=row.risk_level)
        if digest != row.content_hash:
            session.query(FixPlan).filter(FixPlan.id == row.id).update(
                {"content_hash": digest, "plan_version": (row.plan_version or 1) + 1}, synchronize_session=False)


def _backfill_location_status_2_6_1(engine) -> None:
    """Spec §4 backfill 3: an RCA saved before 2.6.1 gave no location. Fail-soft like the anchor backfill."""
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE rca_results SET location_status = 'absent' WHERE location_status IS NULL"))
    except Exception as exc:
        logger.warning("MVP-2.6.1 location_status backfill skipped: %s", exc)


def _backfill_plan_hashes_2_6_1(engine) -> None:
    """Spec §4 / §3.D.1: hash every plan saved before 2.6.1; an approved or executing one also gets that hash as
    its approved hash, so it can still run. Fail-soft like the backfills above — a plan left without an approved
    hash is refused at the execution gate (fail-closed) and needs a new approval."""
    try:
        from agenticops.services.plan_content import content_hash

        with Session(engine) as session:
            rows = (
                session.query(FixPlan.id, FixPlan.status, FixPlan.plan_version, FixPlan.steps, FixPlan.rollback_plan,
                              FixPlan.pre_checks, FixPlan.post_checks, FixPlan.risk_level,
                              HealthIssue.account_id.label("issue_account"),
                              ChangeRequest.account_id.label("change_account"))
                .outerjoin(HealthIssue, HealthIssue.id == FixPlan.health_issue_id)
                .outerjoin(ChangeRequest, ChangeRequest.id == FixPlan.change_request_id)
                .filter(FixPlan.content_hash.is_(None)).all()
            )
            for row in rows:
                digest = content_hash(steps=row.steps, rollback_plan=row.rollback_plan, pre_checks=row.pre_checks,
                                      post_checks=row.post_checks, risk_level=row.risk_level,
                                      account_id=row.change_account if row.change_account is not None else row.issue_account)
                values = {"content_hash": digest}
                if row.status in ("approved", "executing"):
                    values.update(approved_hash=digest, approved_version=row.plan_version or 1)
                session.query(FixPlan).filter(FixPlan.id == row.id).update(values, synchronize_session=False)
            session.commit()
    except Exception as exc:
        logger.warning("MVP-2.6.1 plan hash backfill skipped: %s", exc)


# MVP-2.7.0: chat session ownership. Existing rows become workspace sessions with no owner (unchanged reach).
_ADD_COLUMNS_2_7_0: dict[str, dict[str, Optional[str]]] = {
    "chat_sessions": {"owner_user_id": None, "visibility": "NOT NULL DEFAULT 'workspace'"},
}
_migrated_2_7_0_urls: set[str] = set()
_migrate_2_7_0_lock = threading.Lock()


def _statements_2_7_0(insp, dialect) -> list[str]:
    """DDL still needed for the 2.7.0 shape; pure like _statements_2_6_1, empty once migrated."""
    guard = " IF NOT EXISTS" if dialect.name == "postgresql" else ""
    stmts: list[str] = []
    for tbl, cols in _ADD_COLUMNS_2_7_0.items():
        if not insp.has_table(tbl):
            continue
        existing = {c["name"] for c in insp.get_columns(tbl)}
        for col, extra in cols.items():
            if col not in existing:
                stmts.append(f"ALTER TABLE {tbl} ADD COLUMN{guard} {_add_column_ddl(dialect, tbl, col, extra)}")
    return stmts


def _run_migrate_2_7_0(engine) -> None:
    stmts = _statements_2_7_0(inspect(engine), engine.dialect)
    if stmts:
        with engine.begin() as conn:
            for stmt in stmts:
                conn.execute(text(stmt))


def _migrate_2_7_0(engine) -> None:
    """Idempotent MVP-2.7.0 migration — once per process per database URL; a DDL failure raises."""
    key = str(engine.url)
    with _migrate_2_7_0_lock:
        if key in _migrated_2_7_0_urls:
            return
        _run_migrate_2_7_0(engine)
        _migrated_2_7_0_urls.add(key)


def _run_migrate_2_6_1(engine) -> None:
    stmts = _statements_2_6_1(inspect(engine), engine.dialect)
    if stmts:
        with engine.begin() as conn:
            for stmt in stmts:
                conn.execute(text(stmt))
    # Backfills (spec §4), each fail-soft. Plans B/C/D append theirs after this line.
    _backfill_anchors_2_6_1(engine)
    _backfill_location_status_2_6_1(engine)
    _backfill_plan_hashes_2_6_1(engine)


def _migrate_2_6_1(engine) -> None:
    """Idempotent MVP-2.6.1 migration — once per process per database URL. DDL failures raise (init_db never
    starts on a half-migrated schema) and retry on the next call."""
    key = str(engine.url)
    with _migrate_2_6_1_lock:
        if key in _migrated_2_6_1_urls:
            return
        _run_migrate_2_6_1(engine)
        _migrated_2_6_1_urls.add(key)


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

    # Migration: composite index on chat_messages for cursor pagination.
    # chat_messages had NO indexes; this makes (session_id, id) range scans
    # for the paginated /messages endpoint efficient. Idempotent.
    if insp.has_table("chat_messages"):
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chat_message_session_id "
                "ON chat_messages(session_id, id)"
            ))
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

    # Migration (MVP-2.2.0): Signal Gate ledger columns on alert_events
    if insp.has_table("alert_events"):
        columns = {col["name"] for col in insp.get_columns("alert_events")}
        if "disposition" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE alert_events ADD COLUMN kind VARCHAR(20) DEFAULT 'alert'"))
                conn.execute(text("ALTER TABLE alert_events ADD COLUMN fingerprint VARCHAR(64)"))
                conn.execute(text("ALTER TABLE alert_events ADD COLUMN resource_id VARCHAR(500) DEFAULT ''"))
                conn.execute(text("ALTER TABLE alert_events ADD COLUMN account_id VARCHAR(100) DEFAULT ''"))
                conn.execute(text("ALTER TABLE alert_events ADD COLUMN issue_type VARCHAR(40) DEFAULT 'other'"))
                conn.execute(text("ALTER TABLE alert_events ADD COLUMN disposition VARCHAR(20)"))
                conn.execute(text("ALTER TABLE alert_events ADD COLUMN disposition_reason VARCHAR(200) DEFAULT ''"))
                conn.execute(text("ALTER TABLE alert_events ADD COLUMN gate_evidence JSON"))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_alert_fingerprint_time "
                    "ON alert_events(fingerprint, received_at)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_alert_disposition ON alert_events(disposition)"
                ))
                conn.commit()

    # Migration (MVP-2.2.0): issue_type on health_issues
    if insp.has_table("health_issues"):
        columns = {col["name"] for col in insp.get_columns("health_issues")}
        if "issue_type" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE health_issues ADD COLUMN issue_type VARCHAR(40) DEFAULT 'other'"))
                conn.execute(text("UPDATE health_issues SET issue_type = 'other' WHERE issue_type IS NULL"))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_health_issue_type ON health_issues(issue_type)"
                ))
                conn.commit()

    # Migration (MVP-2.2.0): RCA quality columns on rca_results
    if insp.has_table("rca_results"):
        columns = {col["name"] for col in insp.get_columns("rca_results")}
        if "evidence_verified" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE rca_results ADD COLUMN evidence JSON"))
                conn.execute(text("ALTER TABLE rca_results ADD COLUMN evidence_verified BOOLEAN"))
                conn.execute(text("ALTER TABLE rca_results ADD COLUMN critic_verdict VARCHAR(30)"))
                conn.execute(text("ALTER TABLE rca_results ADD COLUMN critic_notes TEXT"))
                conn.execute(text("ALTER TABLE rca_results ADD COLUMN human_verdict VARCHAR(10)"))
                conn.execute(text("ALTER TABLE rca_results ADD COLUMN human_note TEXT"))
                conn.execute(text("ALTER TABLE rca_results ADD COLUMN verified_at DATETIME"))
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

    # Migration: add cost/actor columns to agent_logs
    if insp.has_table("agent_logs"):
        cols = {c["name"] for c in insp.get_columns("agent_logs")}
        more = []
        if "cache_write_tokens" not in cols:
            more.append("ALTER TABLE agent_logs ADD COLUMN cache_write_tokens INTEGER DEFAULT 0")
        if "cost_usd" not in cols:
            more.append("ALTER TABLE agent_logs ADD COLUMN cost_usd FLOAT DEFAULT 0")
        if "actor_type" not in cols:
            more.append("ALTER TABLE agent_logs ADD COLUMN actor_type VARCHAR(20) DEFAULT 'system'")
        if "actor_id" not in cols:
            more.append("ALTER TABLE agent_logs ADD COLUMN actor_id VARCHAR(100)")
        if more:
            with engine.connect() as conn:
                for stmt in more:
                    conn.execute(text(stmt))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_log_actor_time ON agent_logs(actor_type, created_at)"))
                conn.commit()

    # Migration: add trace_id to chat_messages
    if insp.has_table("chat_messages"):
        cols = {c["name"] for c in insp.get_columns("chat_messages")}
        if "trace_id" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN trace_id VARCHAR(36)"))
                conn.commit()

    # Migration: add per-session model / effort overrides to chat_sessions if missing
    if insp.has_table("chat_sessions"):
        columns = {col["name"] for col in insp.get_columns("chat_sessions")}
        with engine.connect() as conn:
            if "model_id" not in columns:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN model_id VARCHAR(200)"))
            if "effort" not in columns:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN effort VARCHAR(20)"))
            conn.commit()

    # Migration: add suggestion-chips column to chat_messages if missing
    if insp.has_table("chat_messages"):
        cols = {c["name"] for c in insp.get_columns("chat_messages")}
        if "suggestions" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN suggestions JSON"))
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
    import agenticops.galaxy.models  # noqa: F401 — register galaxy_* tables in Base metadata

    Base.metadata.create_all(engine)
    # MVP-2.6.0: relax plan-lineage NOT NULLs (table rebuild on SQLite), add change columns.
    # Raises on failure on purpose — never start on a half-migrated schema.
    _migrate_2_6_0(engine)

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

    # MVP-2.6.1: graph anchoring columns + relation-build marker; runs last so every legacy column it reads exists.
    _migrate_2_6_1(engine)
    # MVP-2.7.0: chat session owner + visibility; this installation's id.
    _migrate_2_7_0(engine)
    _ensure_installation(engine)

    return engine


def _ensure_installation(engine) -> None:
    """Create the one Installation row if it is missing; a concurrent first start loses the insert, not the id."""
    import secrets
    from sqlalchemy.exc import IntegrityError
    s = Session(bind=engine)
    try:
        if s.get(Installation, 1) is None:
            s.add(Installation(id=1, deployment_id=secrets.token_hex(12)))
            s.commit()
    except IntegrityError:
        s.rollback()
    finally:
        s.close()


def deployment_id() -> str:
    s = get_session()
    try:
        row = s.get(Installation, 1)
        return row.deployment_id if row else ""
    finally:
        s.close()


def get_session() -> Session:
    """Get a new database session.

    Note: Prefer using get_db_session() context manager for automatic
    commit/rollback handling.
    """
    SessionLocal = sessionmaker(bind=get_engine())
    return SessionLocal()


# ============================================================================
# Cloud Security Review (MVP-2.5.0)
# ============================================================================


class SecuritySnapshot(Base):
    """Point-in-time security posture snapshot (time series)."""

    __tablename__ = "security_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="aws")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    category_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    exposure_paths: Mapped[list] = mapped_column(JSON, default=list)
    cis_results: Mapped[dict] = mapped_column(JSON, default=dict)


class SecurityRecommendation(Base):
    """Evidence-grounded security recommendation (advisor output)."""

    __tablename__ = "security_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("security_snapshots.id"), nullable=True, index=True
    )
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(256))
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    critic_verdict: Mapped[str] = mapped_column(String(16), default="")  # supported|weak|refuted
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|acknowledged|dismissed|applied


class SecurityPollCursor(Base):
    """Incremental-poll cursor per (account, source, region) — ISO8601 string."""

    __tablename__ = "security_poll_cursors"
    __table_args__ = (
        UniqueConstraint("account_id", "source", "region", name="uq_security_poll_cursor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32))  # guardduty | securityhub | cloudtrail
    region: Mapped[str] = mapped_column(String(32))
    cursor: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
