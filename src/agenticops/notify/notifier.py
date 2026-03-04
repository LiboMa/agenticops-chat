"""Notifier - Multi-channel notification system for AgenticOps.

Channel configuration is loaded exclusively from channels.yaml (via im_config).
NotificationLog is stored in the DB for audit purposes.
"""

import asyncio
import json
import logging
import smtplib
import time
from abc import ABC, abstractmethod
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from agenticops.models import Base, get_db_session

logger = logging.getLogger(__name__)


# ============================================================================
# Notification Log (DB — audit only)
# ============================================================================


class NotificationLog(Base):
    """Log of sent notifications."""

    __tablename__ = "notification_logs"
    __table_args__ = (
        Index("idx_notification_log_channel_name", "channel_name"),
        Index("idx_notification_log_sent", "sent_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_name: Mapped[str] = mapped_column(String(100))
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
# SNS Report Notifier — formatted report distribution via S3 + SNS
# ============================================================================


class SNSReportNotifier(Notifier):
    """SNS-backed report distribution — converts reports to PDF/HTML/DOCX,
    uploads to S3 with presigned URLs, publishes download links to email subscribers."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.topic_arn: str = config.get("topic_arn", "")
        self.region: str = config.get("region", "us-east-1")
        self.s3_bucket: str = config.get("s3_bucket", "")
        self.s3_prefix: str = config.get("s3_prefix", "reports/")
        self.s3_region: str = config.get("s3_region", self.region)
        self.url_expiry: int = int(config.get("url_expiry", 604800))  # 7 days
        self.formats: List[str] = config.get("formats", ["html", "markdown"])
        self.report_types: List[str] = config.get("report_types", [])  # empty = all
        # SES config — when set, HTML reports are sent via SES (rendered in email)
        # instead of SNS (which delivers plain text only).
        self.ses_sender: str = config.get("ses_sender", "")
        self.ses_recipients: List[str] = config.get("ses_recipients", [])

    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Plain text fallback — for non-report pipeline notifications.

        Delegates to basic SNS publish (same as SNSNotifier).
        """
        if not self.topic_arn:
            logger.error("SNS topic ARN not configured for sns-report channel")
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._publish_text, subject, body, severity,
            )
            return True
        except Exception as e:
            logger.error(f"SNS report channel text send failed: {e}")
            return False

    def _publish_text(self, subject: str, body: str, severity: Optional[str]) -> None:
        """Publish plain text to SNS (blocking)."""
        import boto3

        client = boto3.client("sns", region_name=self.region)
        message = {
            "default": body,
            "email": f"[{severity.upper() if severity else 'INFO'}] {subject}\n\n{body}",
        }
        client.publish(
            TopicArn=self.topic_arn,
            Subject=f"[AgenticOps] {subject[:100]}",
            Message=json.dumps(message),
            MessageStructure="json",
        )

    async def send_report(
        self,
        report_id: int,
        title: str,
        summary: str,
        content_markdown: str,
        report_type: str,
        formats: Optional[List[str]] = None,
        report_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Full report distribution pipeline.

        1. Filter by report_types config
        2. format_report() → list[FormattedReport]
        3. Upload each format to S3 → presigned URLs
        4. Build email message — inline HTML preferred, download links appended
        5. SNS publish with MessageStructure="json"

        Returns:
            {"formats": [...], "urls": {...}, "message_id": "..."}
        """
        # Filter by configured report types (empty = all)
        if self.report_types and report_type not in self.report_types:
            logger.info(
                "Report type '%s' not in sns-report filter %s — skipping",
                report_type, self.report_types,
            )
            return {"formats": [], "urls": {}, "message_id": None, "skipped": True}

        if not self.topic_arn or not self.s3_bucket:
            raise ValueError("topic_arn and s3_bucket are required for sns-report channel")

        from agenticops.notify.report_formatter import format_report

        use_formats = formats or self.formats
        meta = dict(report_metadata or {})
        meta["report_type"] = report_type
        formatted = format_report(
            title=title,
            content_markdown=content_markdown,
            formats=use_formats,
            report_metadata=meta,
        )

        if not formatted:
            logger.warning("No report formats generated for report #%d", report_id)
            return {"formats": [], "urls": {}, "message_id": None}

        # Extract inline HTML content (used for email body)
        inline_html: str = ""
        for fr in formatted:
            if fr.format == "html":
                inline_html = fr.content.decode("utf-8")
                break

        # Upload to S3 and collect presigned URLs
        loop = asyncio.get_event_loop()
        urls: Dict[str, str] = {}
        generated_formats: List[str] = []

        for fr in formatted:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            s3_key = f"{self.s3_prefix}{report_type}/{date_str}/{report_id}{fr.extension}"
            url = await loop.run_in_executor(
                None, self._upload_to_s3, s3_key, fr.content, fr.content_type,
            )
            urls[fr.format] = url
            generated_formats.append(fr.format)

        # Build and publish SNS message — inline HTML preferred
        message_id = await loop.run_in_executor(
            None, self._publish_report_message,
            title, summary, urls, report_type, report_id, inline_html,
        )

        return {
            "formats": generated_formats,
            "urls": urls,
            "message_id": message_id,
        }

    def _upload_to_s3(self, key: str, content: bytes, content_type: str) -> str:
        """Upload file to S3 and return a presigned download URL."""
        import boto3

        s3 = boto3.client("s3", region_name=self.s3_region)
        s3.put_object(
            Bucket=self.s3_bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.s3_bucket, "Key": key},
            ExpiresIn=self.url_expiry,
        )
        return url

    def _build_html_body(
        self,
        title: str,
        summary: str,
        urls: Dict[str, str],
        report_type: str,
        report_id: int,
        inline_html: str = "",
    ) -> str:
        """Build the HTML body for email delivery (used by both SES and SNS paths)."""
        if inline_html:
            links_html = "".join(
                f'<li><a href="{url}">{fmt.upper()}</a></li>'
                for fmt, url in urls.items()
            )
            download_section = (
                f'<div style="margin-top:32px;padding-top:16px;border-top:1px solid #e2e8f0;">'
                f'<p style="color:#64748b;font-size:0.85rem;">'
                f'Download links (valid {self.url_expiry // 86400} days): '
                f'<ul style="font-size:0.85rem;">{links_html}</ul></p></div>'
            )
            if "</body>" in inline_html:
                return inline_html.replace("</body>", f"{download_section}</body>")
            return inline_html + download_section

        links_html = "".join(
            f'<li><a href="{url}">{fmt.upper()}</a></li>'
            for fmt, url in urls.items()
        )
        return (
            f"<h2>{title}</h2>"
            f"<p><strong>Type:</strong> {report_type} &nbsp; "
            f"<strong>Report ID:</strong> #{report_id}</p>"
            f"<h3>Summary</h3><p>{summary[:1000]}</p>"
            f"<h3>Download Links</h3>"
            f"<p><em>Valid for {self.url_expiry // 86400} days</em></p>"
            f"<ul>{links_html}</ul>"
            f"<hr><p style='color:#999;font-size:12px'>AgenticOps Report Distribution</p>"
        )

    def _send_html_via_ses(
        self,
        title: str,
        summary: str,
        html_body: str,
        plain_body: str,
    ) -> str:
        """Send HTML email via SES. Returns MessageId."""
        import boto3

        client = boto3.client("ses", region_name=self.region)
        resp = client.send_email(
            Source=self.ses_sender,
            Destination={"ToAddresses": self.ses_recipients},
            Message={
                "Subject": {"Data": f"[AgenticOps Report] {title[:80]}", "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": plain_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
        return resp.get("MessageId", "")

    def _publish_report_message(
        self,
        title: str,
        summary: str,
        urls: Dict[str, str],
        report_type: str,
        report_id: int,
        inline_html: str = "",
    ) -> str:
        """Build email message and deliver via SES (HTML) or SNS (plain text).

        When ``ses_sender`` and ``ses_recipients`` are configured, the full
        HTML report is sent via SES so email clients render it properly.
        Otherwise falls back to SNS (plain text only — SNS email protocol
        does not support HTML Content-Type).
        """
        import boto3

        # ── Plain-text body (used by both SES and SNS) ───────────────
        links_text = "\n".join(
            f"  - {fmt.upper()}: {url}" for fmt, url in urls.items()
        )
        plain_body = (
            f"Report: {title}\n"
            f"Type: {report_type}\n"
            f"Report ID: #{report_id}\n\n"
            f"Summary:\n{summary[:1000]}\n\n"
            f"Download Links (valid for {self.url_expiry // 86400} days):\n"
            f"{links_text}\n\n"
            f"-- AgenticOps"
        )

        # ── HTML body ─────────────────────────────────────────────────
        html_body = self._build_html_body(
            title, summary, urls, report_type, report_id, inline_html,
        )

        # ── SES path (HTML email) ────────────────────────────────────
        if self.ses_sender and self.ses_recipients:
            try:
                msg_id = self._send_html_via_ses(title, summary, html_body, plain_body)
                logger.info(
                    "Report HTML email sent via SES to %s (MessageId=%s)",
                    self.ses_recipients, msg_id,
                )
                return msg_id
            except Exception:
                logger.warning(
                    "SES delivery failed — falling back to SNS", exc_info=True,
                )

        # ── SNS fallback (plain text — SNS email doesn't render HTML) ─
        client = boto3.client("sns", region_name=self.region)

        # SNS message size limit is 256 KB
        max_sns_bytes = 250_000
        if len(html_body.encode("utf-8")) > max_sns_bytes:
            logger.warning(
                "Inline HTML too large (%d bytes) — falling back to links only",
                len(html_body.encode("utf-8")),
            )
            html_body = (
                f"<h2>{title}</h2>"
                f"<p>{summary[:1000]}</p>"
                f"<p>Full report too large for inline delivery. "
                f"Please use the download links below.</p>"
                f"<ul>{''.join(f'<li><a href=\"{u}\">{f.upper()}</a></li>' for f, u in urls.items())}</ul>"
            )

        message = {
            "default": plain_body,
            "email": html_body,
        }

        resp = client.publish(
            TopicArn=self.topic_arn,
            Subject=f"[AgenticOps Report] {title[:80]}",
            Message=json.dumps(message),
            MessageStructure="json",
            MessageAttributes={
                "report_type": {
                    "DataType": "String",
                    "StringValue": report_type,
                },
                "report_id": {
                    "DataType": "Number",
                    "StringValue": str(report_id),
                },
            },
        )
        return resp.get("MessageId", "")

    async def test_connection(self) -> bool:
        """Validate SNS topic exists and S3 bucket is writable."""
        try:
            import boto3

            # Check SNS topic
            sns = boto3.client("sns", region_name=self.region)
            sns.get_topic_attributes(TopicArn=self.topic_arn)

            # Check S3 bucket (head_bucket)
            if self.s3_bucket:
                s3 = boto3.client("s3", region_name=self.s3_region)
                s3.head_bucket(Bucket=self.s3_bucket)

            return True
        except Exception as e:
            logger.error(f"SNS report channel test failed: {e}")
            return False

    # -- Subscription management --

    def subscribe_email(self, email: str) -> Dict[str, str]:
        """Subscribe an email address to the SNS topic.

        AWS sends a confirmation email automatically.

        Returns:
            {"subscription_arn": "pending confirmation", "status": "pending"}
        """
        import boto3

        client = boto3.client("sns", region_name=self.region)
        resp = client.subscribe(
            TopicArn=self.topic_arn,
            Protocol="email",
            Endpoint=email,
            ReturnSubscriptionArn=True,
        )
        arn = resp.get("SubscriptionArn", "pending confirmation")
        status = "confirmed" if arn.startswith("arn:") else "pending"
        return {"subscription_arn": arn, "status": status}

    def list_subscriptions(self) -> List[Dict[str, str]]:
        """List all subscriptions on the SNS topic."""
        import boto3

        client = boto3.client("sns", region_name=self.region)
        subs: List[Dict[str, str]] = []
        paginator = client.get_paginator("list_subscriptions_by_topic")
        for page in paginator.paginate(TopicArn=self.topic_arn):
            for sub in page.get("Subscriptions", []):
                status = "confirmed" if sub["SubscriptionArn"].startswith("arn:") else "pending"
                subs.append({
                    "subscription_arn": sub["SubscriptionArn"],
                    "protocol": sub["Protocol"],
                    "endpoint": sub["Endpoint"],
                    "status": status,
                })
        return subs

    def unsubscribe(self, subscription_arn: str) -> bool:
        """Unsubscribe from the SNS topic."""
        import boto3

        try:
            client = boto3.client("sns", region_name=self.region)
            client.unsubscribe(SubscriptionArn=subscription_arn)
            return True
        except Exception as e:
            logger.error(f"SNS unsubscribe failed: {e}")
            return False


# ============================================================================
# IM Notifier Base Class — shared token caching for Feishu/DingTalk/WeCom
# ============================================================================


class IMNotifier(Notifier):
    """Base class for IM platform notifiers with shared token caching."""

    SEVERITY_COLORS = {
        "critical": "red",
        "high": "orange",
        "medium": "yellow",
        "low": "blue",
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.app_name: str = config.get("app_name", "default")
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    def _token_valid(self) -> bool:
        return bool(self._access_token) and time.monotonic() < self._token_expires_at

    def _cache_token(self, token: str, expires_in: int = 7200) -> None:
        self._access_token = token
        # Refresh 5 min early
        self._token_expires_at = time.monotonic() + expires_in - 300

    async def _get_token(self) -> str:
        if self._token_valid():
            return self._access_token
        await self._acquire_token()
        return self._access_token

    async def _acquire_token(self) -> None:
        raise NotImplementedError


# ============================================================================
# Feishu (飞书) Notifier — App API + Interactive Card
# ============================================================================


class FeishuNotifier(IMNotifier):
    """Feishu (Lark) notifier via Open API with Interactive Card messages."""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.chat_id = config.get("chat_id", "")
        # App credentials: lazy-loaded from YAML, fallback to channel config
        self._app_id: str = ""
        self._app_secret: str = ""

    def _ensure_app_config(self) -> None:
        """Load app credentials from YAML config, fallback to channel DB config."""
        if self._app_id and self._app_secret:
            return
        from agenticops.notify.im_config import get_feishu_app
        app = get_feishu_app(self.app_name)
        if app and app.app_id and app.app_secret:
            self._app_id = app.app_id
            self._app_secret = app.app_secret
        else:
            # Backward compat: read from channel config JSON
            self._app_id = self.config.get("app_id", "")
            self._app_secret = self.config.get("app_secret", "")

    async def _acquire_token(self) -> None:
        self._ensure_app_config()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
                timeout=10.0,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Feishu token error: {data.get('msg', resp.text)}")
            self._cache_token(data["tenant_access_token"], data.get("expire", 7200))

    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Send an Interactive Card message to a Feishu group chat."""
        self._ensure_app_config()
        if not (self._app_id and self._app_secret and self.chat_id):
            logger.error("Feishu app_id, app_secret, or chat_id not configured")
            return False

        header_color = self.SEVERITY_COLORS.get(severity, "blue")

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": subject},
                "template": header_color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": body},
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"Severity: {(severity or 'info').upper()} | AgenticAIOps | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                        }
                    ],
                },
            ],
        }

        try:
            token = await self._get_token()
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.BASE_URL}/im/v1/messages",
                    params={"receive_id_type": "chat_id"},
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "receive_id": self.chat_id,
                        "msg_type": "interactive",
                        "content": json.dumps(card),
                    },
                    timeout=10.0,
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"Feishu send error: {data.get('msg', resp.text)}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Feishu notification failed: {e}")
            return False

    async def test_connection(self) -> bool:
        """Validate app credentials by obtaining a tenant token."""
        try:
            await self._get_token()
            return True
        except Exception as e:
            logger.error(f"Feishu test failed: {e}")
            return False


# ============================================================================
# DingTalk (钉钉) Notifier — Open API + Markdown Card
# ============================================================================


class DingTalkNotifier(IMNotifier):
    """DingTalk notifier via Open API with Markdown group messages."""

    TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
    SEND_URL = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.chat_id = config.get("chat_id", "")  # openConversationId
        self._app_key: str = ""
        self._app_secret: str = ""

    def _ensure_app_config(self) -> None:
        if self._app_key and self._app_secret:
            return
        from agenticops.notify.im_config import get_dingtalk_app
        app = get_dingtalk_app(self.app_name)
        if app and app.app_key and app.app_secret:
            self._app_key = app.app_key
            self._app_secret = app.app_secret
        else:
            self._app_key = self.config.get("app_key", "")
            self._app_secret = self.config.get("app_secret", "")

    async def _acquire_token(self) -> None:
        self._ensure_app_config()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.TOKEN_URL,
                json={"appKey": self._app_key, "appSecret": self._app_secret},
                timeout=10.0,
            )
            data = resp.json()
            token = data.get("accessToken")
            if not token:
                raise RuntimeError(f"DingTalk token error: {data}")
            self._cache_token(token, data.get("expireIn", 7200))

    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Send a Markdown message to a DingTalk group chat."""
        self._ensure_app_config()
        if not (self._app_key and self._app_secret and self.chat_id):
            logger.error("DingTalk app_key, app_secret, or chat_id not configured")
            return False

        sev_label = (severity or "info").upper()
        md_content = f"### [{sev_label}] {subject}\n\n{body}\n\n---\n*AgenticAIOps | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*"

        try:
            token = await self._get_token()
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.SEND_URL,
                    headers={"x-acs-dingtalk-access-token": token},
                    json={
                        "msgParam": json.dumps({"title": subject, "text": md_content}),
                        "msgKey": "sampleMarkdown",
                        "openConversationId": self.chat_id,
                        "robotCode": self._app_key,
                    },
                    timeout=10.0,
                )
                data = resp.json()
                if "processQueryKey" not in data:
                    logger.error(f"DingTalk send error: {data}")
                    return False
                return True
        except Exception as e:
            logger.error(f"DingTalk notification failed: {e}")
            return False

    async def test_connection(self) -> bool:
        """Validate app credentials by obtaining an access token."""
        try:
            await self._get_token()
            return True
        except Exception as e:
            logger.error(f"DingTalk test failed: {e}")
            return False


# ============================================================================
# WeCom (企业微信) Notifier — App API + TextCard
# ============================================================================


class WeComNotifier(IMNotifier):
    """WeCom (WeChat Work) notifier via App API with TextCard messages."""

    TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
    APPCHAT_SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/appchat/send"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.touser = config.get("touser", "")  # user mode: "@all" or "user1|user2"
        self.chatid = config.get("chatid", "")  # group chat mode
        self._corp_id: str = ""
        self._corp_secret: str = ""
        self._agent_id: int = 0

    def _ensure_app_config(self) -> None:
        if self._corp_id and self._corp_secret:
            return
        from agenticops.notify.im_config import get_wecom_app
        app = get_wecom_app(self.app_name)
        if app and app.corp_id and app.corp_secret:
            self._corp_id = app.corp_id
            self._corp_secret = app.corp_secret
            self._agent_id = app.agent_id
        else:
            self._corp_id = self.config.get("corp_id", "")
            self._corp_secret = self.config.get("corp_secret", "")
            self._agent_id = int(self.config.get("agent_id", 0))

    async def _acquire_token(self) -> None:
        self._ensure_app_config()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self.TOKEN_URL,
                params={"corpid": self._corp_id, "corpsecret": self._corp_secret},
                timeout=10.0,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                raise RuntimeError(f"WeCom token error: {data.get('errmsg', data)}")
            self._cache_token(data["access_token"], data.get("expires_in", 7200))

    async def send(self, subject: str, body: str, severity: Optional[str] = None) -> bool:
        """Send a TextCard message via WeCom."""
        self._ensure_app_config()
        if not (self._corp_id and self._corp_secret):
            logger.error("WeCom corp_id or corp_secret not configured")
            return False

        sev_label = (severity or "info").upper()
        description = f"<div class=\"gray\">{sev_label}</div><div class=\"normal\">{body[:500]}</div>"

        try:
            token = await self._get_token()

            if self.chatid:
                # Group chat mode
                payload = {
                    "chatid": self.chatid,
                    "msgtype": "textcard",
                    "textcard": {
                        "title": subject,
                        "description": description,
                        "btntxt": "View Detail",
                    },
                }
                url = f"{self.APPCHAT_SEND_URL}?access_token={token}"
            else:
                # User message mode
                payload = {
                    "touser": self.touser or "@all",
                    "msgtype": "textcard",
                    "agentid": self._agent_id,
                    "textcard": {
                        "title": subject,
                        "description": description,
                        "url": "https://agenticops.local",
                        "btntxt": "View Detail",
                    },
                }
                url = f"{self.SEND_URL}?access_token={token}"

            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10.0)
                data = resp.json()
                if data.get("errcode") != 0:
                    logger.error(f"WeCom send error: {data.get('errmsg', data)}")
                    return False
                return True
        except Exception as e:
            logger.error(f"WeCom notification failed: {e}")
            return False

    async def test_connection(self) -> bool:
        """Validate app credentials by obtaining an access token."""
        try:
            await self._get_token()
            return True
        except Exception as e:
            logger.error(f"WeCom test failed: {e}")
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
# Notification Manager — reads channels from YAML (channels.yaml)
# ============================================================================


class NotificationManager:
    """Manager for sending notifications across multiple channels.

    All channel configuration is loaded from channels.yaml (via im_config).
    No DB reads for channel config — DB is only used for NotificationLog audit.
    """

    NOTIFIER_CLASSES = {
        "slack": SlackNotifier,
        "email": EmailNotifier,
        "sns": SNSNotifier,
        "sns-report": SNSReportNotifier,
        "feishu": FeishuNotifier,
        "dingtalk": DingTalkNotifier,
        "wecom": WeComNotifier,
        "webhook": WebhookNotifier,
    }

    def __init__(self):
        self._notifiers: Dict[str, Notifier] = {}

    def _get_notifier(self, channel_name: str, channel_type: str,
                      config: Dict[str, Any]) -> Optional[Notifier]:
        """Get or create a notifier for a channel (from YAML config)."""
        notifier_class = self.NOTIFIER_CLASSES.get(channel_type)
        if not notifier_class:
            return None

        cache_key = channel_name
        if cache_key not in self._notifiers:
            self._notifiers[cache_key] = notifier_class(config)

        return self._notifiers.get(cache_key)

    def invalidate_cache(self, channel_name: Optional[str] = None) -> None:
        """Invalidate notifier cache (e.g. after YAML config change)."""
        if channel_name:
            self._notifiers.pop(channel_name, None)
        else:
            self._notifiers.clear()

    async def send_notification(
        self,
        subject: str,
        body: str,
        severity: Optional[str] = None,
        channel_names: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """Send notification to all matching channels.

        Loads channels from channels.yaml. Logs results to DB.
        """
        from agenticops.notify.im_config import load_channels

        results = {}
        all_channels = load_channels()

        # Filter to requested channels
        if channel_names:
            channels = [c for c in all_channels if c.name in channel_names and c.is_enabled]
        else:
            channels = [c for c in all_channels if c.is_enabled]

        for channel in channels:
            # Check severity filter
            if severity and channel.severity_filter:
                if severity not in channel.severity_filter:
                    continue

            notifier = self._get_notifier(
                channel.name, channel.channel_type, channel.config,
            )
            if not notifier:
                logger.warning("Unknown channel type: %s", channel.channel_type)
                results[channel.name] = False
                continue

            try:
                success = await notifier.send(subject, body, severity)
                results[channel.name] = success

                # Log notification to DB
                self._log_notification(
                    channel_name=channel.name,
                    subject=subject,
                    body=body,
                    severity=severity,
                    status="sent" if success else "failed",
                )

            except Exception as e:
                logger.error("Notification to '%s' failed: %s", channel.name, e)
                results[channel.name] = False

                self._log_notification(
                    channel_name=channel.name,
                    subject=subject,
                    body=body,
                    severity=severity,
                    status="failed",
                    error=str(e),
                )

        return results

    @staticmethod
    def _log_notification(
        channel_name: str,
        subject: str,
        body: str,
        severity: Optional[str],
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Write a notification log entry to DB."""
        try:
            with get_db_session() as session:
                log = NotificationLog(
                    channel_name=channel_name,
                    subject=subject,
                    body=body[:1000],
                    severity=severity,
                    status=status,
                    error=error,
                )
                session.add(log)
        except Exception as e:
            logger.debug("Failed to write notification log: %s", e)

    async def send_anomaly_notification(self, anomaly) -> Dict[str, bool]:
        """Send notification about an anomaly."""
        subject = f"[{anomaly.severity.upper()}] {anomaly.title}"

        body = (
            f"Anomaly Detected\n\n"
            f"Title: {anomaly.title}\n"
            f"Description: {anomaly.description}\n\n"
            f"Resource: {anomaly.resource_type}/{anomaly.resource_id}\n"
            f"Region: {anomaly.region}\n"
            f"Detected: {anomaly.detected_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
        )
        if anomaly.metric_name:
            body += (
                f"\nMetric: {anomaly.metric_name}\n"
                f"Expected: {anomaly.expected_value}\n"
                f"Actual: {anomaly.actual_value}\n"
            )

        return await self.send_notification(
            subject=subject,
            body=body.strip(),
            severity=anomaly.severity,
        )

    @staticmethod
    async def test_channel(name: str) -> bool:
        """Test a notification channel by name (reads from YAML).

        Args:
            name: Channel name to test

        Returns:
            True if test successful
        """
        from agenticops.notify.im_config import get_channel

        channel = get_channel(name)
        if not channel:
            raise ValueError(f"Channel '{name}' not found in channels.yaml")

        notifier_class = NotificationManager.NOTIFIER_CLASSES.get(channel.channel_type)
        if not notifier_class:
            raise ValueError(f"Unknown channel type: {channel.channel_type}")

        notifier = notifier_class(channel.config)
        return await notifier.test_connection()
