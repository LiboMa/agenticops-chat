"""Audit logging models for AgenticOps."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from agenticops.models import Base


class AuditLog(Base):
    """Audit log entry for tracking system changes."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_log_user", "user_id"),
        Index("idx_audit_log_entity", "entity_type", "entity_id"),
        Index("idx_audit_log_timestamp", "timestamp"),
        Index("idx_audit_log_action", "action"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(nullable=True)  # NULL for system actions
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(50))  # create, update, delete, login, logout, etc.
    entity_type: Mapped[str] = mapped_column(String(50))  # account, resource, anomaly, user, etc.
    entity_id: Mapped[str] = mapped_column(String(100))  # ID of the affected entity
    entity_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # Human-readable name
    details: Mapped[dict] = mapped_column(JSON, default=dict)  # Additional context
    old_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Previous state for updates
    new_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # New state for updates
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # For correlation
