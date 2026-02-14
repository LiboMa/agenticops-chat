"""Notifier - Multi-channel notification system for AgenticOps."""

import asyncio
import json
import logging
import smtplib
from abc import ABC, abstractmethod
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column

from agenticops.models import Base, get_db_session, init_db

logger = logging.getLogger(__name__)


# ============================================================================
# Notification Models
# ============================================================================


class NotificationChannel(Base):
    """Notification channel configuration."""

    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    channel_type: Mapped[str] = mapped_column(String(20))  # slack, email, sns, webhook
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    severity_filter: Mapped[list] = mapped_column(JSON, default=list)  # ["critical", "high"]
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class NotificationLog(Base):
    """Log of sent notifications."""

    __tablename__ = "notification_logs"
    __table_args__ = (
        Index("idx_notification_log_channel", "channel_id"),
        Index("idx_notification_log_sent", "sent_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("notification_channels.id"))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # sent, failed
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ============================================================================
# Notifier Abstract Base Class
# ============================================================================


class Notifier(ABC):
    """Abstract base class for notification channels."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Send a notification.

        Args:
            subject: Notification subject/title
            body: Notification body/content
            severity: Optional severity level

        Returns:
            True if sent successfully, False otherwise
        """
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test the notification channel connection.

        Returns:
            True if connection is valid
        """
        pass


# ============================================================================
# Slack Notifier
# ============================================================================


class SlackNotifier(Notifier):
    """Slack webhook notifier."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.webhook_url = config.get("webhook_url")
        self.channel = config.get("channel", "#alerts")
        self.username = config.get("username", "AgenticAIOps")
        self.icon_emoji = config.get("icon_emoji", ":robot_face:")

    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Send a Slack notification."""
        if not self.webhook_url:
            logger.error("Slack webhook URL not configured")
            return False

        # Build color based on severity
        color_map = {
            "critical": "#FF0000",
            "high": "#FF6600",
            "medium": "#FFCC00",
            "low": "#0066FF",
        }
        color = color_map.get(severity, "#808080")

        # Build Slack message
        payload = {
            "channel": self.channel,
            "username": self.username,
            "icon_emoji": self.icon_emoji,
            "attachments": [
                {
                    "color": color,
                    "title": subject,
                    "text": body,
                    "footer": "AgenticAIOps",
                    "ts": int(datetime.utcnow().timestamp()),
                }
            ],
        }

        if severity:
            payload["attachments"][0]["fields"] = [
                {"title": "Severity", "value": severity.upper(), "short": True}
            ]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Slack notification failed: {e}")
            return False

    async def test_connection(self) -> bool:
        """Test Slack webhook."""
        return await self.send(
            subject="AgenticAIOps Test",
            body="This is a test notification from AgenticAIOps.",
            severity="low",
        )


# ============================================================================
# Email Notifier
# ============================================================================


class EmailNotifier(Notifier):
    """SMTP email notifier."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.smtp_host = config.get("smtp_host", "localhost")
        self.smtp_port = config.get("smtp_port", 587)
        self.smtp_user = config.get("smtp_user")
        self.smtp_password = config.get("smtp_password")
        self.use_tls = config.get("use_tls", True)
        self.from_email = config.get("from_email", "aiops@localhost")
        self.to_emails = config.get("to_emails", [])

    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Send an email notification."""
        if not self.to_emails:
            logger.error("No recipient emails configured")
            return False

        # Build email
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[AgenticAIOps] {subject}"
        msg["From"] = self.from_email
        msg["To"] = ", ".join(self.to_emails)

        # Plain text body
        text_body = f"{subject}\n\n{body}"
        if severity:
            text_body = f"[{severity.upper()}] {text_body}"

        # HTML body
        severity_color = {
            "critical": "#FF0000",
            "high": "#FF6600",
            "medium": "#FFCC00",
            "low": "#0066FF",
        }.get(severity, "#808080")

        html_body = f"""
        <html>
        <body>
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #4F46E5; color: white; padding: 20px; text-align: center;">
                    <h1 style="margin: 0;">AgenticAIOps Alert</h1>
                </div>
                <div style="padding: 20px; background-color: #f9f9f9;">
                    {"<span style='background-color: " + severity_color + "; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px;'>" + severity.upper() + "</span>" if severity else ""}
                    <h2 style="margin-top: 15px;">{subject}</h2>
                    <p style="color: #666; white-space: pre-wrap;">{body}</p>
                </div>
                <div style="padding: 10px; background-color: #e9e9e9; text-align: center; font-size: 12px; color: #666;">
                    Sent by AgenticAIOps at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
                </div>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            # Run SMTP in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_email, msg)
            return True
        except Exception as e:
            logger.error(f"Email notification failed: {e}")
            return False

    def _send_email(self, msg: MIMEMultipart):
        """Send email via SMTP (blocking)."""
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)

    async def test_connection(self) -> bool:
        """Test SMTP connection."""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._test_smtp)
            return True
        except Exception as e:
            logger.error(f"SMTP test failed: {e}")
            return False

    def _test_smtp(self):
        """Test SMTP connection (blocking)."""
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)


# ============================================================================
# SNS Notifier
# ============================================================================


class SNSNotifier(Notifier):
    """AWS SNS notifier."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.topic_arn = config.get("topic_arn")
        self.region = config.get("region", "us-east-1")

    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Send an SNS notification."""
        if not self.topic_arn:
            logger.error("SNS topic ARN not configured")
            return False

        try:
            import boto3

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._publish_sns,
                subject,
                body,
                severity,
            )
            return True
        except Exception as e:
            logger.error(f"SNS notification failed: {e}")
            return False

    def _publish_sns(self, subject: str, body: str, severity: Optional[str]):
        """Publish to SNS (blocking)."""
        import boto3

        client = boto3.client("sns", region_name=self.region)

        message = {
            "default": body,
            "email": f"[{severity.upper() if severity else 'INFO'}] {subject}\n\n{body}",
        }

        client.publish(
            TopicArn=self.topic_arn,
            Subject=f"[AgenticAIOps] {subject[:100]}",
            Message=json.dumps(message),
            MessageStructure="json",
            MessageAttributes={
                "severity": {
                    "DataType": "String",
                    "StringValue": severity or "info",
                }
            },
        )

    async def test_connection(self) -> bool:
        """Test SNS connection."""
        try:
            import boto3

            client = boto3.client("sns", region_name=self.region)
            # Get topic attributes to verify it exists
            client.get_topic_attributes(TopicArn=self.topic_arn)
            return True
        except Exception as e:
            logger.error(f"SNS test failed: {e}")
            return False


# ============================================================================
# Webhook Notifier
# ============================================================================


class WebhookNotifier(Notifier):
    """Generic webhook notifier."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.url = config.get("url")
        self.method = config.get("method", "POST")
        self.headers = config.get("headers", {})
        self.template = config.get("template")

    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Send a webhook notification."""
        if not self.url:
            logger.error("Webhook URL not configured")
            return False

        # Build payload
        if self.template:
            # Use custom template
            payload = json.loads(
                self.template
                .replace("{{subject}}", subject)
                .replace("{{body}}", body)
                .replace("{{severity}}", severity or "info")
                .replace("{{timestamp}}", datetime.utcnow().isoformat())
            )
        else:
            # Default payload
            payload = {
                "source": "AgenticAIOps",
                "subject": subject,
                "body": body,
                "severity": severity,
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            async with httpx.AsyncClient() as client:
                if self.method.upper() == "POST":
                    response = await client.post(
                        self.url,
                        json=payload,
                        headers=self.headers,
                        timeout=10.0,
                    )
                else:
                    response = await client.get(
                        self.url,
                        params=payload,
                        headers=self.headers,
                        timeout=10.0,
                    )
                return 200 <= response.status_code < 300
        except Exception as e:
            logger.error(f"Webhook notification failed: {e}")
            return False

    async def test_connection(self) -> bool:
        """Test webhook connection."""
        return await self.send(
            subject="AgenticAIOps Test",
            body="This is a test notification.",
            severity="low",
        )


# ============================================================================
# Notification Manager
# ============================================================================


class NotificationManager:
    """Manager for sending notifications across multiple channels."""

    NOTIFIER_CLASSES = {
        "slack": SlackNotifier,
        "email": EmailNotifier,
        "sns": SNSNotifier,
        "webhook": WebhookNotifier,
    }

    def __init__(self):
        self._notifiers: Dict[str, Notifier] = {}

    def _get_notifier(self, channel: NotificationChannel) -> Optional[Notifier]:
        """Get or create a notifier for a channel."""
        cache_key = f"{channel.id}:{channel.updated_at.isoformat()}"

        if cache_key not in self._notifiers:
            notifier_class = self.NOTIFIER_CLASSES.get(channel.channel_type)
            if notifier_class:
                self._notifiers[cache_key] = notifier_class(channel.config)

        return self._notifiers.get(cache_key)

    async def send_notification(
        self,
        subject: str,
        body: str,
        severity: Optional[str] = None,
        channel_names: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """Send notification to all matching channels.

        Args:
            subject: Notification subject
            body: Notification body
            severity: Severity level for filtering
            channel_names: Optional list of specific channels to use

        Returns:
            Dict mapping channel names to success status
        """
        results = {}

        with get_db_session() as session:
            query = session.query(NotificationChannel).filter_by(is_enabled=True)

            if channel_names:
                query = query.filter(NotificationChannel.name.in_(channel_names))

            channels = query.all()

            for channel in channels:
                # Check severity filter
                if severity and channel.severity_filter:
                    if severity not in channel.severity_filter:
                        continue

                notifier = self._get_notifier(channel)
                if not notifier:
                    logger.warning(f"Unknown channel type: {channel.channel_type}")
                    results[channel.name] = False
                    continue

                try:
                    success = await notifier.send(subject, body, severity)
                    results[channel.name] = success

                    # Log notification
                    log = NotificationLog(
                        channel_id=channel.id,
                        subject=subject,
                        body=body[:1000],  # Truncate body
                        severity=severity,
                        status="sent" if success else "failed",
                    )
                    session.add(log)

                except Exception as e:
                    logger.error(f"Notification to '{channel.name}' failed: {e}")
                    results[channel.name] = False

                    # Log failure
                    log = NotificationLog(
                        channel_id=channel.id,
                        subject=subject,
                        body=body[:1000],
                        severity=severity,
                        status="failed",
                        error=str(e),
                    )
                    session.add(log)

        return results

    async def send_anomaly_notification(self, anomaly) -> Dict[str, bool]:
        """Send notification about an anomaly.

        Args:
            anomaly: Anomaly model instance

        Returns:
            Dict mapping channel names to success status
        """
        subject = f"[{anomaly.severity.upper()}] {anomaly.title}"

        body = f"""
Anomaly Detected

Title: {anomaly.title}
Description: {anomaly.description}

Resource: {anomaly.resource_type}/{anomaly.resource_id}
Region: {anomaly.region}
Detected: {anomaly.detected_at.strftime('%Y-%m-%d %H:%M UTC')}

"""
        if anomaly.metric_name:
            body += f"""
Metric: {anomaly.metric_name}
Expected: {anomaly.expected_value}
Actual: {anomaly.actual_value}
"""

        return await self.send_notification(
            subject=subject,
            body=body.strip(),
            severity=anomaly.severity,
        )

    @staticmethod
    def add_channel(
        name: str,
        channel_type: str,
        config: Dict[str, Any],
        severity_filter: Optional[List[str]] = None,
    ) -> NotificationChannel:
        """Add a new notification channel.

        Args:
            name: Unique channel name
            channel_type: Channel type (slack, email, sns, webhook)
            config: Channel-specific configuration
            severity_filter: List of severities to notify for

        Returns:
            Created NotificationChannel
        """
        init_db()

        with get_db_session() as session:
            existing = session.query(NotificationChannel).filter_by(name=name).first()
            if existing:
                raise ValueError(f"Channel '{name}' already exists")

            channel = NotificationChannel(
                name=name,
                channel_type=channel_type,
                config=config,
                severity_filter=severity_filter or [],
            )
            session.add(channel)
            session.flush()
            return channel

    @staticmethod
    def list_channels() -> List[NotificationChannel]:
        """List all notification channels."""
        init_db()

        with get_db_session() as session:
            return session.query(NotificationChannel).all()

    @staticmethod
    async def test_channel(name: str) -> bool:
        """Test a notification channel.

        Args:
            name: Channel name to test

        Returns:
            True if test successful
        """
        with get_db_session() as session:
            channel = session.query(NotificationChannel).filter_by(name=name).first()
            if not channel:
                raise ValueError(f"Channel '{name}' not found")

            notifier_class = NotificationManager.NOTIFIER_CLASSES.get(channel.channel_type)
            if not notifier_class:
                raise ValueError(f"Unknown channel type: {channel.channel_type}")

            notifier = notifier_class(channel.config)
            return await notifier.test_connection()
