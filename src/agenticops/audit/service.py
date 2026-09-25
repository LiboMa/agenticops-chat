"""Audit logging service for AgenticOps."""

import logging
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from agenticops.models import get_db_session, init_db
from agenticops.audit.models import AuditLog

logger = logging.getLogger(__name__)

# Process-local marker for AuditService.maybe_prune_daily (one prune per process-day).
_last_prune_date: Optional[date] = None


# ============================================================================
# Action Types
# ============================================================================


class Actions:
    """Standard audit action types."""

    # CRUD operations
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"

    # Authentication
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    PASSWORD_CHANGE = "password_change"

    # API Key operations
    API_KEY_CREATE = "api_key_create"
    API_KEY_REVOKE = "api_key_revoke"

    # Resource operations
    SCAN = "scan"
    DETECT = "detect"
    ANALYZE = "analyze"
    REPORT = "report"

    # Anomaly operations
    ACKNOWLEDGE = "acknowledge"
    RESOLVE = "resolve"

    # Schedule operations
    SCHEDULE_RUN = "schedule_run"
    SCHEDULE_ENABLE = "schedule_enable"
    SCHEDULE_DISABLE = "schedule_disable"

    # Notification operations
    NOTIFY_SEND = "notify_send"

    # ── Change Management (MVP-2.6.0) — dotted names, one per decision ──
    CHANGE_REQUESTED = "change.requested"
    CHANGE_REVIEWED = "change.reviewed"
    CHANGE_CLARIFIED = "change.clarified"
    CHANGE_APPROVED = "change.approved"
    CHANGE_REJECTED = "change.rejected"
    CHANGE_CANCELLED = "change.cancelled"
    CHANGE_EXECUTION_STARTED = "change.execution_started"
    CHANGE_COMPLETED = "change.completed"
    CHANGE_FAILED = "change.failed"
    CHANGE_ROLLED_BACK = "change.rolled_back"
    CHANGE_NEEDS_REVIEW = "change.needs_review"
    PLAN_APPROVED = "plan.approved"
    PLAN_REJECTED = "plan.rejected"
    PLAN_EXECUTE_REQUESTED = "plan.execute_requested"
    AUTHZ_DENIED = "authz.denied"
    AUTHZ_DENIED_SHADOW = "authz.denied_shadow"


# ============================================================================
# Entity Types
# ============================================================================


class EntityTypes:
    """Standard entity types for audit logging."""

    USER = "user"
    API_KEY = "api_key"
    SESSION = "session"
    ACCOUNT = "account"
    RESOURCE = "resource"
    ANOMALY = "anomaly"
    RCA = "rca"
    REPORT = "report"
    SCHEDULE = "schedule"
    NOTIFICATION = "notification"
    SYSTEM = "system"
    CHANGE_REQUEST = "change_request"
    FIX_PLAN = "fix_plan"


# ============================================================================
# Audit Service
# ============================================================================


class AuditService:
    """Service for creating and querying audit logs."""

    @staticmethod
    def log(
        action: str,
        entity_type: str,
        entity_id: str,
        entity_name: Optional[str] = None,
        user_id: Optional[int] = None,
        user_email: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        actor: Optional[str] = None,
        session=None,
    ) -> AuditLog:
        """Create an audit log entry.

        `actor` is the actor key (user:x / cli:x / agent:x / im:p:x). When `session` is given the
        row is added to THAT session and NOT committed — the caller commits it together with the
        state change it audits (decision + state in one transaction). Without `session` the row is
        written in its own transaction (legacy behavior).

        Args:
            action: The action performed (create, update, delete, etc.)
            entity_type: Type of entity affected (user, account, resource, etc.)
            entity_id: ID of the affected entity
            entity_name: Human-readable name of the entity
            user_id: ID of the user who performed the action
            user_email: Email of the user who performed the action
            details: Additional context about the action
            old_values: Previous state (for updates)
            new_values: New state (for updates/creates)
            ip_address: Client IP address
            user_agent: Client user agent string
            request_id: Request correlation ID
            actor: Actor key (user:x / cli:x / agent:x / im:p:x)
            session: Caller's SQLAlchemy session — the row is flushed into it, never committed here

        Returns:
            Created AuditLog instance
        """
        audit_log = AuditLog(
            action=action, entity_type=entity_type, entity_id=str(entity_id), entity_name=entity_name,
            user_id=user_id, user_email=user_email, actor=actor, details=details or {},
            old_values=old_values, new_values=new_values, ip_address=ip_address,
            user_agent=user_agent, request_id=request_id,
        )
        if session is not None:
            session.add(audit_log)
            session.flush()
            return audit_log
        init_db()
        with get_db_session() as db:
            db.add(audit_log)
            db.flush()
            logger.info("Audit: %s %s/%s by %s", action, entity_type, entity_id, actor or user_email or user_id or "system")
            return audit_log

    @staticmethod
    def query(
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        user_id: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLog]:
        """Query audit logs with filtering.

        Args:
            action: Filter by action type
            entity_type: Filter by entity type
            entity_id: Filter by entity ID
            user_id: Filter by user ID
            start_time: Filter by start timestamp
            end_time: Filter by end timestamp
            limit: Maximum records to return
            offset: Pagination offset

        Returns:
            List of matching AuditLog entries
        """
        with get_db_session() as session:
            query = session.query(AuditLog).order_by(AuditLog.timestamp.desc())

            if action:
                query = query.filter_by(action=action)
            if entity_type:
                query = query.filter_by(entity_type=entity_type)
            if entity_id:
                query = query.filter_by(entity_id=str(entity_id))
            if user_id:
                query = query.filter_by(user_id=user_id)
            if start_time:
                query = query.filter(AuditLog.timestamp >= start_time)
            if end_time:
                query = query.filter(AuditLog.timestamp <= end_time)

            rows = query.offset(offset).limit(limit).all()
            for row in rows:
                # detach while loaded — the commit on leaving the block would otherwise expire them
                # (expire_on_commit) and every attribute read after return would raise DetachedInstanceError
                session.expunge(row)
            return rows

    @staticmethod
    def get_entity_history(
        entity_type: str,
        entity_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AuditLog]:
        """Get the audit history for a specific entity.

        Args:
            entity_type: Type of entity
            entity_id: ID of the entity
            limit: Maximum records to return
            offset: Pagination offset

        Returns:
            List of AuditLog entries for the entity
        """
        return AuditService.query(
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def get_user_activity(
        user_id: int,
        days: int = 30,
        limit: int = 100,
    ) -> List[AuditLog]:
        """Get recent activity for a specific user.

        Args:
            user_id: User ID
            days: Number of days to look back
            limit: Maximum records to return

        Returns:
            List of AuditLog entries for the user
        """
        start_time = datetime.now(timezone.utc) - timedelta(days=days)
        return AuditService.query(
            user_id=user_id,
            start_time=start_time,
            limit=limit,
        )

    @staticmethod
    def get_recent_changes(
        entity_type: Optional[str] = None,
        hours: int = 24,
        limit: int = 100,
    ) -> List[AuditLog]:
        """Get recent changes across the system.

        Args:
            entity_type: Optional filter by entity type
            hours: Number of hours to look back
            limit: Maximum records to return

        Returns:
            List of recent AuditLog entries
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        return AuditService.query(
            entity_type=entity_type,
            start_time=start_time,
            limit=limit,
        )

    @staticmethod
    def count_actions(
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """Count audit log entries matching criteria.

        Args:
            action: Filter by action type
            entity_type: Filter by entity type
            start_time: Filter by start timestamp
            end_time: Filter by end timestamp

        Returns:
            Count of matching entries
        """
        with get_db_session() as session:
            query = session.query(AuditLog)

            if action:
                query = query.filter_by(action=action)
            if entity_type:
                query = query.filter_by(entity_type=entity_type)
            if start_time:
                query = query.filter(AuditLog.timestamp >= start_time)
            if end_time:
                query = query.filter(AuditLog.timestamp <= end_time)

            return query.count()

    @staticmethod
    def cleanup_old_logs(days: int = 90) -> int:
        """Delete audit logs older than specified days.

        Args:
            days: Number of days to retain

        Returns:
            Number of deleted entries
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with get_db_session() as session:
            count = session.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete()
            return count

    @staticmethod
    def maybe_prune_daily() -> None:
        """Once per process-day: delete audit_logs + command_audits older than audit_retention_days.

        The day marker is set only after a SUCCESSFUL prune: a failed attempt (DB outage) is logged at
        WARNING and retried on the next call instead of silently skipping retention for a day."""
        global _last_prune_date
        from agenticops.config import settings
        days = int(getattr(settings, "audit_retention_days", 0) or 0)
        today = datetime.now(timezone.utc).date()
        if days <= 0 or _last_prune_date == today:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            from agenticops.models import CommandAudit
            with get_db_session() as db:
                a = db.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete(synchronize_session=False)
                c = db.query(CommandAudit).filter(CommandAudit.created_at < cutoff).delete(synchronize_session=False)
        except Exception:
            logger.warning("audit prune failed — will retry on the next call", exc_info=True)
            return
        _last_prune_date = today
        if a or c:
            logger.info("audit: pruned %d audit_logs + %d command_audits older than %dd", a, c, days)


# ============================================================================
# Decorator for Automatic Audit Logging
# ============================================================================


def log_action(
    action: str,
    entity_type: str,
    get_entity_id: Callable[..., str] = None,
    get_entity_name: Callable[..., str] = None,
) -> Callable:
    """Decorator to automatically log actions.

    Args:
        action: Action type to log
        entity_type: Entity type being affected
        get_entity_id: Function to extract entity ID from function args/result
        get_entity_name: Function to extract entity name from function args/result

    Usage:
        @log_action(Actions.CREATE, EntityTypes.ACCOUNT, lambda result: result.id)
        def create_account(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            try:
                entity_id = get_entity_id(result) if get_entity_id else str(result)
                entity_name = get_entity_name(result) if get_entity_name else None

                AuditService.log(
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                )
            except Exception as e:
                logger.warning(f"Failed to create audit log: {e}")

            return result

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)

            try:
                entity_id = get_entity_id(result) if get_entity_id else str(result)
                entity_name = get_entity_name(result) if get_entity_name else None

                AuditService.log(
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                )
            except Exception as e:
                logger.warning(f"Failed to create audit log: {e}")

            return result

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator
