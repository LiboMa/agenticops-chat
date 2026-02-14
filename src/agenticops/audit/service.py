"""Audit logging service for AgenticOps."""

import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from agenticops.models import get_db_session, init_db
from agenticops.audit.models import AuditLog

logger = logging.getLogger(__name__)


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
    ) -> AuditLog:
        """Create an audit log entry.

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

        Returns:
            Created AuditLog instance
        """
        init_db()

        with get_db_session() as session:
            audit_log = AuditLog(
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                entity_name=entity_name,
                user_id=user_id,
                user_email=user_email,
                details=details or {},
                old_values=old_values,
                new_values=new_values,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
            )
            session.add(audit_log)
            session.flush()

            logger.info(
                f"Audit: {action} {entity_type}/{entity_id} by user {user_email or user_id or 'system'}"
            )

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

            return query.offset(offset).limit(limit).all()

    @staticmethod
    def get_entity_history(
        entity_type: str,
        entity_id: str,
        limit: int = 50,
    ) -> List[AuditLog]:
        """Get the audit history for a specific entity.

        Args:
            entity_type: Type of entity
            entity_id: ID of the entity
            limit: Maximum records to return

        Returns:
            List of AuditLog entries for the entity
        """
        return AuditService.query(
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit,
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
        start_time = datetime.utcnow() - timedelta(days=days)
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
        start_time = datetime.utcnow() - timedelta(hours=hours)
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
        cutoff = datetime.utcnow() - timedelta(days=days)

        with get_db_session() as session:
            count = session.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete()
            return count


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
