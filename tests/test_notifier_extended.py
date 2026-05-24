"""Extended tests for agenticops.notify.notifier — boosting coverage from 50% to 75%+.

Covers: SNSReportNotifier, SESNotifier, IMNotifier, FeishuNotifier,
DingTalkNotifier, WeComNotifier, SlackIMNotifier, WebhookNotifier,
NotificationManager.
"""

import asyncio
import json
import time
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock

from agenticops.notify.notifier import (
    SNSReportNotifier,
    SESNotifier,
    IMNotifier,
    FeishuNotifier,
    DingTalkNotifier,
    WeComNotifier,
    SlackIMNotifier,
    WebhookNotifier,
    NotificationManager,
    SlackNotifier,
    EmailNotifier,
    SNSNotifier,
)


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# SNSReportNotifier
# ============================================================================

class TestSNSReportNotifier:
    def _make(self, **overrides):
        cfg = {
            "topic_arn": "arn:aws:sns:us-east-1:123:reports",
            "region": "us-east-1",
            "s3_bucket": "my-bucket",
            "s3_prefix": "reports/",
            "formats": ["html", "markdown"],
        }
        cfg.update(overrides)
        return SNSReportNotifier(cfg)

    def test_init_defaults(self):
        n = self._make()
        assert n.topic_arn == "arn:aws:sns:us-east-1:123:reports"
        assert n.s3_bucket == "my-bucket"
        assert n.url_expiry == 604800
        assert n.formats == ["html", "markdown"]

    def test_init_ses_config(self):
        n = self._make(ses_sender="noreply@test.com", ses_recipients=["a@b.com"])
        assert n.ses_sender == "noreply@test.com"
        assert n.ses_recipients == ["a@b.com"]

    def test_send_no_topic_arn(self):
        n = self._make(topic_arn="")
        assert run_async(n.send("subj", "body")) is False

    def test_send_success(self):
        n = self._make()
        with patch.object(n, "_publish_text"):
            assert run_async(n.send("Alert", "Body", "high")) is True

    def test_send_failure(self):
        n = self._make()
        with patch.object(n, "_publish_text", side_effect=Exception("fail")):
            assert run_async(n.send("Alert", "Body")) is False

    def test_publish_text(self):
        n = self._make()
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            n._publish_text("Alert", "Body", "critical")
            mock_client.publish.assert_called_once()

    def test_build_html_body_with_inline(self):
        n = self._make()
        html = "<html><body><p>Report</p></body></html>"
        result = n._build_html_body("Title", "Summary", {"html": "http://s3/r.html"}, "daily", 1, html)
        assert "Download links" in result
        assert "HTML" in result

    def test_build_html_body_without_inline(self):
        n = self._make()
        result = n._build_html_body("Title", "Summary", {"html": "http://s3/r.html"}, "daily", 1, "")
        assert "<h2>Title</h2>" in result
        assert "Download Links" in result

    def test_send_html_via_ses(self):
        n = self._make(ses_sender="noreply@test.com", ses_recipients=["a@b.com"])
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "msg-123"}
        with patch("boto3.client", return_value=mock_client):
            result = n._send_html_via_ses("Title", "Summary", "<h1>Hi</h1>", "plain")
            assert result == "msg-123"

    def test_publish_report_message_ses_path(self):
        n = self._make(ses_sender="noreply@test.com", ses_recipients=["a@b.com"])
        with patch.object(n, "_send_html_via_ses", return_value="ses-msg-1") as mock_ses:
            result = n._publish_report_message("Title", "Summary", {"html": "url"}, "daily", 1, "<h1>Hi</h1>")
            assert result == "ses-msg-1"
            mock_ses.assert_called_once()

    def test_publish_report_message_sns_fallback(self):
        n = self._make()  # no SES config
        mock_client = MagicMock()
        mock_client.publish.return_value = {"MessageId": "sns-msg-1"}
        with patch("boto3.client", return_value=mock_client):
            result = n._publish_report_message("Title", "Summary", {"html": "url"}, "daily", 1)
            assert result == "sns-msg-1"

    def test_publish_report_message_ses_failure_falls_back_to_sns(self):
        n = self._make(ses_sender="x@y.com", ses_recipients=["a@b.com"])
        mock_client = MagicMock()
        mock_client.publish.return_value = {"MessageId": "sns-fallback"}
        with patch.object(n, "_send_html_via_ses", side_effect=Exception("SES down")):
            with patch("boto3.client", return_value=mock_client):
                result = n._publish_report_message("T", "S", {"html": "u"}, "daily", 1)
                assert result == "sns-fallback"

    def test_upload_to_s3(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://s3/presigned"
        with patch("boto3.client", return_value=mock_client):
            url = n._upload_to_s3("key.html", b"<html>", "text/html")
            assert url == "https://s3/presigned"
            mock_client.put_object.assert_called_once()

    def test_test_connection_success(self):
        n = self._make()
        mock_sns = MagicMock()
        mock_s3 = MagicMock()
        with patch("boto3.client", side_effect=[mock_sns, mock_s3]):
            assert run_async(n.test_connection()) is True

    def test_test_connection_failure(self):
        n = self._make()
        mock_sns = MagicMock()
        mock_sns.get_topic_attributes.side_effect = Exception("nope")
        with patch("boto3.client", return_value=mock_sns):
            assert run_async(n.test_connection()) is False

    def test_subscribe_email(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.subscribe.return_value = {"SubscriptionArn": "pending confirmation"}
        with patch("boto3.client", return_value=mock_client):
            result = n.subscribe_email("test@example.com")
            assert result["status"] == "pending"

    def test_subscribe_email_confirmed(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.subscribe.return_value = {"SubscriptionArn": "arn:aws:sns:us-east-1:123:reports:uuid"}
        with patch("boto3.client", return_value=mock_client):
            result = n.subscribe_email("test@example.com")
            assert result["status"] == "confirmed"

    def test_list_subscriptions(self):
        n = self._make()
        mock_client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Subscriptions": [
                {"SubscriptionArn": "arn:aws:sns:us-east-1:123:reports:uuid", "Protocol": "email", "Endpoint": "a@b.com"},
            ]}
        ]
        mock_client.get_paginator.return_value = paginator
        with patch("boto3.client", return_value=mock_client):
            subs = n.list_subscriptions()
            assert len(subs) == 1
            assert subs[0]["status"] == "confirmed"

    def test_unsubscribe_success(self):
        n = self._make()
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            assert n.unsubscribe("arn:aws:sns:us-east-1:123:reports:uuid") is True

    def test_unsubscribe_failure(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.unsubscribe.side_effect = Exception("fail")
        with patch("boto3.client", return_value=mock_client):
            assert n.unsubscribe("arn:bad") is False

    def test_send_report_skipped_by_type_filter(self):
        n = self._make(report_types=["weekly"])
        result = run_async(n.send_report(1, "T", "S", "# md", "daily"))
        assert result.get("skipped") is True

    def test_send_report_missing_config(self):
        n = self._make(topic_arn="", s3_bucket="")
        n.report_types = []
        with pytest.raises(ValueError):
            run_async(n.send_report(1, "T", "S", "# md", "daily"))



# ============================================================================
# SESNotifier
# ============================================================================

class TestSESNotifier:
    def _make(self, **overrides):
        cfg = {
            "sender": "noreply@test.com",
            "to": ["dest@test.com"],
            "region": "us-east-1",
        }
        cfg.update(overrides)
        return SESNotifier(cfg)

    def test_init(self):
        n = self._make()
        assert n.sender == "noreply@test.com"
        assert n.recipients == ["dest@test.com"]
        assert n.region == "us-east-1"

    def test_init_string_recipients(self):
        n = self._make(to="single@test.com")
        assert n.recipients == ["single@test.com"]

    def test_init_empty_recipients(self):
        n = self._make(to=[])
        assert n.recipients == []

    def test_send_no_sender(self):
        n = self._make(sender="")
        assert run_async(n.send("subj", "body")) is False

    def test_send_no_recipients(self):
        n = self._make(to=[])
        assert run_async(n.send("subj", "body")) is False

    def test_send_success(self):
        n = self._make()
        with patch.object(n, "_send_email", return_value="msg-1"):
            assert run_async(n.send("Alert", "Body", "critical")) is True

    def test_send_with_severity(self):
        n = self._make()
        with patch.object(n, "_send_email", return_value="msg-1") as mock:
            run_async(n.send("Alert", "Body", "high"))
            call_args = mock.call_args
            assert "[HIGH]" in call_args[0][2]  # html_body

    def test_send_without_severity(self):
        n = self._make()
        with patch.object(n, "_send_email", return_value="msg-1"):
            assert run_async(n.send("Alert", "Body")) is True

    def test_send_failure(self):
        n = self._make()
        with patch.object(n, "_send_email", side_effect=Exception("SES down")):
            assert run_async(n.send("Alert", "Body")) is False

    def test_send_email_method(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "msg-123"}
        with patch("boto3.client", return_value=mock_client):
            result = n._send_email("Subject", "plain", "<h1>html</h1>")
            assert result == "msg-123"

    def test_upload_to_s3(self):
        n = self._make(s3_bucket="bucket", s3_region="us-east-1")
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://s3/url"
        with patch("boto3.client", return_value=mock_client):
            url = n._upload_to_s3("k.html", b"data", "text/html")
            assert url == "https://s3/url"

    def test_test_connection_success(self):
        n = self._make()
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client):
            assert run_async(n.test_connection()) is True

    def test_test_connection_no_sender(self):
        n = self._make(sender="")
        assert run_async(n.test_connection()) is False

    def test_test_connection_failure(self):
        n = self._make()
        mock_client = MagicMock()
        mock_client.get_send_quota.side_effect = Exception("no access")
        with patch("boto3.client", return_value=mock_client):
            assert run_async(n.test_connection()) is False


# ============================================================================
# IMNotifier Base
# ============================================================================

class _ConcreteIMNotifier(IMNotifier):
    """Concrete subclass for testing IMNotifier base methods."""
    async def send(self, subject, body, severity=None):
        return True
    async def test_connection(self):
        return True

class TestIMNotifier:
    def _make(self):
        n = _ConcreteIMNotifier({"app_name": "test"})
        return n

    def test_token_valid_no_token(self):
        n = self._make()
        n._access_token = ""
        n._token_expires_at = 0.0
        assert n._token_valid() is False

    def test_token_valid_expired(self):
        n = self._make()
        n._access_token = "tok"
        n._token_expires_at = time.monotonic() - 10
        assert n._token_valid() is False

    def test_token_valid_ok(self):
        n = self._make()
        n._access_token = "tok"
        n._token_expires_at = time.monotonic() + 3600
        assert n._token_valid() is True

    def test_cache_token(self):
        n = self._make()
        n._cache_token("new-tok", 7200)
        assert n._access_token == "new-tok"
        assert n._token_expires_at > time.monotonic()

    def test_get_token_cached(self):
        n = self._make()
        n._access_token = "cached"
        n._token_expires_at = time.monotonic() + 3600
        assert run_async(n._get_token()) == "cached"

    def test_get_token_refreshes(self):
        n = self._make()
        n._access_token = ""
        n._token_expires_at = 0.0

        async def fake_acquire():
            n._cache_token("refreshed", 7200)

        n._acquire_token = fake_acquire
        assert run_async(n._get_token()) == "refreshed"

    def test_severity_colors(self):
        assert IMNotifier.SEVERITY_COLORS["critical"] == "red"
        assert IMNotifier.SEVERITY_COLORS["low"] == "blue"



# ============================================================================
# FeishuNotifier
# ============================================================================

class TestFeishuNotifier:
    def _make(self, **overrides):
        cfg = {"chat_id": "oc_xxx", "app_name": "default"}
        cfg.update(overrides)
        return FeishuNotifier(cfg)

    def test_init(self):
        n = self._make()
        assert n.chat_id == "oc_xxx"

    def test_ensure_app_config_from_yaml(self):
        n = self._make()
        mock_app = MagicMock(app_id="aid", app_secret="asec")
        with patch("agenticops.notify.notifier.FeishuNotifier._ensure_app_config") as _:
            pass
        # Direct test
        with patch("agenticops.notify.im_config.get_feishu_app", return_value=mock_app):
            n._app_id = ""
            n._app_secret = ""
            n._ensure_app_config()
            assert n._app_id == "aid"

    def test_ensure_app_config_fallback(self):
        n = self._make(app_id="cfg-id", app_secret="cfg-sec")
        with patch("agenticops.notify.im_config.get_feishu_app", return_value=None):
            n._app_id = ""
            n._app_secret = ""
            n._ensure_app_config()
            assert n._app_id == "cfg-id"

    def test_acquire_token_success(self):
        n = self._make()
        n._app_id = "aid"
        n._app_secret = "asec"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "tenant_access_token": "tok-123", "expire": 7200}

        async def fake_post(*args, **kwargs):
            return mock_resp

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = fake_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            with patch.object(n, "_ensure_app_config"):
                run_async(n._acquire_token())
                assert n._access_token == "tok-123"

    def test_acquire_token_error(self):
        n = self._make()
        n._app_id = "aid"
        n._app_secret = "asec"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 99, "msg": "bad"}
        mock_resp.text = "bad"

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            with patch.object(n, "_ensure_app_config"):
                with pytest.raises(RuntimeError):
                    run_async(n._acquire_token())

    def test_send_no_config(self):
        n = self._make(chat_id="")
        with patch.object(n, "_ensure_app_config"):
            n._app_id = ""
            assert run_async(n.send("subj", "body")) is False

    def test_send_success(self):
        n = self._make()
        n._app_id = "aid"
        n._app_secret = "asec"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0}

        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
                with patch("httpx.AsyncClient") as MockClient:
                    instance = AsyncMock()
                    instance.post = AsyncMock(return_value=mock_resp)
                    instance.__aenter__ = AsyncMock(return_value=instance)
                    instance.__aexit__ = AsyncMock(return_value=False)
                    MockClient.return_value = instance
                    assert run_async(n.send("Alert", "Body", "critical")) is True

    def test_send_api_error(self):
        n = self._make()
        n._app_id = "aid"
        n._app_secret = "asec"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 99, "msg": "error"}
        mock_resp.text = "error"

        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
                with patch("httpx.AsyncClient") as MockClient:
                    instance = AsyncMock()
                    instance.post = AsyncMock(return_value=mock_resp)
                    instance.__aenter__ = AsyncMock(return_value=instance)
                    instance.__aexit__ = AsyncMock(return_value=False)
                    MockClient.return_value = instance
                    assert run_async(n.send("Alert", "Body")) is False

    def test_send_exception(self):
        n = self._make()
        n._app_id = "aid"
        n._app_secret = "asec"

        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, side_effect=Exception("net")):
                assert run_async(n.send("Alert", "Body")) is False

    def test_test_connection_success(self):
        n = self._make()
        with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
            assert run_async(n.test_connection()) is True

    def test_test_connection_failure(self):
        n = self._make()
        with patch.object(n, "_get_token", new_callable=AsyncMock, side_effect=Exception("fail")):
            assert run_async(n.test_connection()) is False


# ============================================================================
# DingTalkNotifier
# ============================================================================

class TestDingTalkNotifier:
    def _make(self, **overrides):
        cfg = {"chat_id": "cid_xxx", "app_name": "default"}
        cfg.update(overrides)
        return DingTalkNotifier(cfg)

    def test_init(self):
        n = self._make()
        assert n.chat_id == "cid_xxx"

    def test_ensure_app_config_from_yaml(self):
        n = self._make()
        mock_app = MagicMock(app_key="ak", app_secret="as")
        with patch("agenticops.notify.im_config.get_dingtalk_app", return_value=mock_app):
            n._app_key = ""
            n._app_secret = ""
            n._ensure_app_config()
            assert n._app_key == "ak"

    def test_ensure_app_config_fallback(self):
        n = self._make(app_key="cfg-k", app_secret="cfg-s")
        with patch("agenticops.notify.im_config.get_dingtalk_app", return_value=None):
            n._app_key = ""
            n._app_secret = ""
            n._ensure_app_config()
            assert n._app_key == "cfg-k"

    def test_send_no_config(self):
        n = self._make(chat_id="")
        with patch.object(n, "_ensure_app_config"):
            n._app_key = ""
            assert run_async(n.send("subj", "body")) is False

    def test_send_success(self):
        n = self._make()
        n._app_key = "ak"
        n._app_secret = "as"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"processQueryKey": "pqk-123"}

        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
                with patch("httpx.AsyncClient") as MockClient:
                    instance = AsyncMock()
                    instance.post = AsyncMock(return_value=mock_resp)
                    instance.__aenter__ = AsyncMock(return_value=instance)
                    instance.__aexit__ = AsyncMock(return_value=False)
                    MockClient.return_value = instance
                    assert run_async(n.send("Alert", "Body", "high")) is True

    def test_send_api_error(self):
        n = self._make()
        n._app_key = "ak"
        n._app_secret = "as"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errcode": 99}

        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
                with patch("httpx.AsyncClient") as MockClient:
                    instance = AsyncMock()
                    instance.post = AsyncMock(return_value=mock_resp)
                    instance.__aenter__ = AsyncMock(return_value=instance)
                    instance.__aexit__ = AsyncMock(return_value=False)
                    MockClient.return_value = instance
                    assert run_async(n.send("Alert", "Body")) is False

    def test_send_exception(self):
        n = self._make()
        n._app_key = "ak"
        n._app_secret = "as"
        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, side_effect=Exception("net")):
                assert run_async(n.send("A", "B")) is False

    def test_test_connection_success(self):
        n = self._make()
        with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
            assert run_async(n.test_connection()) is True

    def test_test_connection_failure(self):
        n = self._make()
        with patch.object(n, "_get_token", new_callable=AsyncMock, side_effect=Exception("fail")):
            assert run_async(n.test_connection()) is False



# ============================================================================
# WeComNotifier
# ============================================================================

class TestWeComNotifier:
    def _make(self, **overrides):
        cfg = {"touser": "@all", "app_name": "default"}
        cfg.update(overrides)
        return WeComNotifier(cfg)

    def test_init(self):
        n = self._make()
        assert n.touser == "@all"

    def test_init_group_mode(self):
        n = self._make(chatid="group-123")
        assert n.chatid == "group-123"

    def test_ensure_app_config_from_yaml(self):
        n = self._make()
        mock_app = MagicMock(corp_id="cid", corp_secret="cs", agent_id=1000)
        with patch("agenticops.notify.im_config.get_wecom_app", return_value=mock_app):
            n._corp_id = ""
            n._corp_secret = ""
            n._ensure_app_config()
            assert n._corp_id == "cid"
            assert n._agent_id == 1000

    def test_ensure_app_config_fallback(self):
        n = self._make(corp_id="fc", corp_secret="fs", agent_id=2000)
        with patch("agenticops.notify.im_config.get_wecom_app", return_value=None):
            n._corp_id = ""
            n._corp_secret = ""
            n._ensure_app_config()
            assert n._corp_id == "fc"
            assert n._agent_id == 2000

    def test_acquire_token_success(self):
        n = self._make()
        n._corp_id = "cid"
        n._corp_secret = "cs"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errcode": 0, "access_token": "wc-tok", "expires_in": 7200}

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            with patch.object(n, "_ensure_app_config"):
                run_async(n._acquire_token())
                assert n._access_token == "wc-tok"

    def test_acquire_token_error(self):
        n = self._make()
        n._corp_id = "cid"
        n._corp_secret = "cs"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errcode": 40001, "errmsg": "invalid"}

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            with patch.object(n, "_ensure_app_config"):
                with pytest.raises(RuntimeError):
                    run_async(n._acquire_token())

    def test_send_no_config(self):
        n = self._make()
        with patch.object(n, "_ensure_app_config"):
            n._corp_id = ""
            assert run_async(n.send("subj", "body")) is False

    def test_send_user_mode_success(self):
        n = self._make()
        n._corp_id = "cid"
        n._corp_secret = "cs"
        n._agent_id = 1000
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errcode": 0}

        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
                with patch("httpx.AsyncClient") as MockClient:
                    instance = AsyncMock()
                    instance.post = AsyncMock(return_value=mock_resp)
                    instance.__aenter__ = AsyncMock(return_value=instance)
                    instance.__aexit__ = AsyncMock(return_value=False)
                    MockClient.return_value = instance
                    assert run_async(n.send("Alert", "Body", "critical")) is True

    def test_send_group_mode_success(self):
        n = self._make(chatid="group-123")
        n._corp_id = "cid"
        n._corp_secret = "cs"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errcode": 0}

        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
                with patch("httpx.AsyncClient") as MockClient:
                    instance = AsyncMock()
                    instance.post = AsyncMock(return_value=mock_resp)
                    instance.__aenter__ = AsyncMock(return_value=instance)
                    instance.__aexit__ = AsyncMock(return_value=False)
                    MockClient.return_value = instance
                    assert run_async(n.send("Alert", "Body")) is True

    def test_send_api_error(self):
        n = self._make()
        n._corp_id = "cid"
        n._corp_secret = "cs"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errcode": 40001, "errmsg": "invalid"}

        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
                with patch("httpx.AsyncClient") as MockClient:
                    instance = AsyncMock()
                    instance.post = AsyncMock(return_value=mock_resp)
                    instance.__aenter__ = AsyncMock(return_value=instance)
                    instance.__aexit__ = AsyncMock(return_value=False)
                    MockClient.return_value = instance
                    assert run_async(n.send("Alert", "Body")) is False

    def test_send_exception(self):
        n = self._make()
        n._corp_id = "cid"
        n._corp_secret = "cs"
        with patch.object(n, "_ensure_app_config"):
            with patch.object(n, "_get_token", new_callable=AsyncMock, side_effect=Exception("net")):
                assert run_async(n.send("A", "B")) is False

    def test_test_connection_success(self):
        n = self._make()
        with patch.object(n, "_get_token", new_callable=AsyncMock, return_value="tok"):
            assert run_async(n.test_connection()) is True

    def test_test_connection_failure(self):
        n = self._make()
        with patch.object(n, "_get_token", new_callable=AsyncMock, side_effect=Exception("fail")):
            assert run_async(n.test_connection()) is False


# ============================================================================
# SlackIMNotifier
# ============================================================================

class TestSlackIMNotifier:
    def _make(self, **overrides):
        cfg = {"chat_id": "C123", "app_name": "default"}
        cfg.update(overrides)
        return SlackIMNotifier(cfg)

    def test_init(self):
        n = self._make()
        assert n.chat_id == "C123"

    def test_ensure_app_config_from_yaml(self):
        n = self._make()
        mock_app = MagicMock(bot_token="xoxb-test")
        with patch("agenticops.notify.im_config.get_slack_app", return_value=mock_app):
            n._bot_token = ""
            n._ensure_app_config()
            assert n._bot_token == "xoxb-test"

    def test_ensure_app_config_fallback(self):
        n = self._make(bot_token="xoxb-cfg")
        with patch("agenticops.notify.im_config.get_slack_app", return_value=None):
            n._bot_token = ""
            n._ensure_app_config()
            assert n._bot_token == "xoxb-cfg"

    def test_acquire_token(self):
        n = self._make()
        n._bot_token = "xoxb-test"
        with patch.object(n, "_ensure_app_config"):
            run_async(n._acquire_token())
            assert n._access_token == "xoxb-test"

    def test_send_no_config(self):
        n = self._make(chat_id="")
        with patch.object(n, "_ensure_app_config"):
            n._bot_token = ""
            assert run_async(n.send("subj", "body")) is False

    def test_send_success(self):
        n = self._make()
        n._bot_token = "xoxb-test"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        with patch.object(n, "_ensure_app_config"):
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance
                assert run_async(n.send("Alert", "Body", "high")) is True

    def test_send_combines_subject_body(self):
        n = self._make()
        n._bot_token = "xoxb-test"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        with patch.object(n, "_ensure_app_config"):
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance
                run_async(n.send("Title", "Content"))
                call_kwargs = instance.post.call_args.kwargs.get("json") or instance.post.call_args[1].get("json")
                assert "*Title*" in call_kwargs["text"]
                assert "Content" in call_kwargs["text"]

    def test_send_body_only(self):
        n = self._make()
        n._bot_token = "xoxb-test"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        with patch.object(n, "_ensure_app_config"):
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance
                run_async(n.send("", "JustBody"))

    def test_send_api_error(self):
        n = self._make()
        n._bot_token = "xoxb-test"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_resp.text = "error"

        with patch.object(n, "_ensure_app_config"):
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance
                assert run_async(n.send("Alert", "Body")) is False

    def test_send_exception(self):
        n = self._make()
        n._bot_token = "xoxb-test"
        with patch.object(n, "_ensure_app_config"):
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(side_effect=Exception("net"))
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance
                assert run_async(n.send("A", "B")) is False

    def test_test_connection_success(self):
        n = self._make()
        n._bot_token = "xoxb-test"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        with patch.object(n, "_ensure_app_config"):
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance
                assert run_async(n.test_connection()) is True

    def test_test_connection_failure(self):
        n = self._make()
        n._bot_token = "xoxb-test"
        with patch.object(n, "_ensure_app_config"):
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(side_effect=Exception("fail"))
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance
                assert run_async(n.test_connection()) is False



# ============================================================================
# WebhookNotifier
# ============================================================================

class TestWebhookNotifier:
    def _make(self, **overrides):
        cfg = {"url": "https://hooks.example.com/notify", "method": "POST"}
        cfg.update(overrides)
        return WebhookNotifier(cfg)

    def test_init(self):
        n = self._make()
        assert n.url == "https://hooks.example.com/notify"
        assert n.method == "POST"

    def test_init_custom_headers(self):
        n = self._make(headers={"X-Api-Key": "secret"})
        assert n.headers["X-Api-Key"] == "secret"

    def test_send_no_url(self):
        n = self._make(url=None)
        assert run_async(n.send("subj", "body")) is False

    def test_send_post_success(self):
        n = self._make()
        mock_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance
            assert run_async(n.send("Alert", "Body", "high")) is True

    def test_send_get_success(self):
        n = self._make(method="GET")
        mock_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance
            assert run_async(n.send("Alert", "Body")) is True

    def test_send_with_template(self):
        tpl = '{"title": "{{subject}}", "msg": "{{body}}", "sev": "{{severity}}"}'
        n = self._make(template=tpl)
        mock_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance
            assert run_async(n.send("Alert", "Body", "critical")) is True
            payload = instance.post.call_args.kwargs.get("json") or instance.post.call_args[1].get("json")
            assert payload["title"] == "Alert"
            assert payload["sev"] == "critical"

    def test_send_http_error(self):
        n = self._make()
        mock_resp = MagicMock(status_code=500)

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance
            assert run_async(n.send("Alert", "Body")) is False

    def test_send_exception(self):
        n = self._make()
        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=Exception("timeout"))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance
            assert run_async(n.send("A", "B")) is False

    def test_test_connection_delegates_to_send(self):
        n = self._make()
        with patch.object(n, "send", new_callable=AsyncMock, return_value=True):
            assert run_async(n.test_connection()) is True


# ============================================================================
# NotificationManager
# ============================================================================

class TestNotificationManager:
    def test_init(self):
        nm = NotificationManager()
        assert nm._notifiers == {}

    def test_notifier_classes_registered(self):
        expected = {"slack", "email", "ses", "sns", "sns-report", "feishu", "dingtalk", "wecom", "webhook"}
        assert expected == set(NotificationManager.NOTIFIER_CLASSES.keys())

    def test_get_notifier_slack_webhook(self):
        nm = NotificationManager()
        n = nm._get_notifier("test-slack", "slack", {"webhook_url": "https://hooks.slack.com/x"})
        assert isinstance(n, SlackNotifier)

    def test_get_notifier_slack_bot_auto_select(self):
        nm = NotificationManager()
        n = nm._get_notifier("test-slack-im", "slack", {"chat_id": "C123"})
        assert isinstance(n, SlackIMNotifier)

    def test_get_notifier_email(self):
        nm = NotificationManager()
        n = nm._get_notifier("test-email", "email", {"smtp_host": "smtp.test.com"})
        assert isinstance(n, EmailNotifier)

    def test_get_notifier_unknown_type(self):
        nm = NotificationManager()
        n = nm._get_notifier("test-unknown", "foobar", {})
        assert n is None

    def test_get_notifier_caches(self):
        nm = NotificationManager()
        n1 = nm._get_notifier("ch1", "webhook", {"url": "http://a.com"})
        n2 = nm._get_notifier("ch1", "webhook", {"url": "http://a.com"})
        assert n1 is n2

    def test_invalidate_cache_single(self):
        nm = NotificationManager()
        nm._get_notifier("ch1", "webhook", {"url": "http://a.com"})
        nm._get_notifier("ch2", "webhook", {"url": "http://b.com"})
        nm.invalidate_cache("ch1")
        assert "ch1" not in nm._notifiers
        assert "ch2" in nm._notifiers

    def test_invalidate_cache_all(self):
        nm = NotificationManager()
        nm._get_notifier("ch1", "webhook", {"url": "http://a.com"})
        nm.invalidate_cache()
        assert nm._notifiers == {}

    def test_log_notification_success(self):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        with patch("agenticops.notify.notifier.get_db_session", return_value=mock_session):
            NotificationManager._log_notification("ch1", "subj", "body", "high", "sent")
            mock_session.add.assert_called_once()

    def test_log_notification_db_error(self):
        with patch("agenticops.notify.notifier.get_db_session", side_effect=Exception("db down")):
            # Should not raise
            NotificationManager._log_notification("ch1", "subj", "body", "high", "failed", "err")

    def test_send_notification(self):
        nm = NotificationManager()
        mock_channel = MagicMock()
        mock_channel.name = "test-wh"
        mock_channel.channel_type = "webhook"
        mock_channel.is_enabled = True
        mock_channel.severity_filter = None
        mock_channel.config = {"url": "http://a.com"}

        with patch("agenticops.notify.im_config.load_channels", return_value=[mock_channel]):
            mock_notifier = AsyncMock()
            mock_notifier.send = AsyncMock(return_value=True)
            with patch.object(nm, "_get_notifier", return_value=mock_notifier):
                with patch.object(nm, "_log_notification"):
                    results = run_async(nm.send_notification("Alert", "Body", "high"))
                    assert results["test-wh"] is True

    def test_send_notification_severity_filter(self):
        nm = NotificationManager()
        mock_channel = MagicMock()
        mock_channel.name = "filtered"
        mock_channel.channel_type = "webhook"
        mock_channel.is_enabled = True
        mock_channel.severity_filter = ["critical"]
        mock_channel.config = {"url": "http://a.com"}

        with patch("agenticops.notify.im_config.load_channels", return_value=[mock_channel]):
            with patch.object(nm, "_log_notification"):
                results = run_async(nm.send_notification("Alert", "Body", "low"))
                assert "filtered" not in results

    def test_send_notification_disabled_channel(self):
        nm = NotificationManager()
        mock_channel = MagicMock()
        mock_channel.name = "off"
        mock_channel.is_enabled = False

        with patch("agenticops.notify.im_config.load_channels", return_value=[mock_channel]):
            results = run_async(nm.send_notification("Alert", "Body"))
            assert "off" not in results

    def test_send_notification_channel_names_filter(self):
        nm = NotificationManager()
        ch1 = MagicMock()
        ch1.name = "ch1"
        ch1.channel_type = "webhook"
        ch1.is_enabled = True
        ch1.severity_filter = None
        ch1.config = {"url": "http://a"}
        ch2 = MagicMock()
        ch2.name = "ch2"
        ch2.channel_type = "webhook"
        ch2.is_enabled = True
        ch2.severity_filter = None
        ch2.config = {"url": "http://b"}

        with patch("agenticops.notify.im_config.load_channels", return_value=[ch1, ch2]):
            mock_notifier = AsyncMock()
            mock_notifier.send = AsyncMock(return_value=True)
            with patch.object(nm, "_get_notifier", return_value=mock_notifier):
                with patch.object(nm, "_log_notification"):
                    results = run_async(nm.send_notification("A", "B", channel_names=["ch1"]))
                    assert "ch1" in results
                    assert "ch2" not in results

    def test_send_notification_exception(self):
        nm = NotificationManager()
        mock_channel = MagicMock()
        mock_channel.name = "broken"
        mock_channel.channel_type = "webhook"
        mock_channel.is_enabled = True
        mock_channel.severity_filter = None
        mock_channel.config = {"url": "http://a.com"}

        mock_notifier = AsyncMock()
        mock_notifier.send = AsyncMock(side_effect=Exception("boom"))

        with patch("agenticops.notify.im_config.load_channels", return_value=[mock_channel]):
            with patch.object(nm, "_get_notifier", return_value=mock_notifier):
                with patch.object(nm, "_log_notification"):
                    results = run_async(nm.send_notification("A", "B"))
                    assert results["broken"] is False

    def test_send_anomaly_notification(self):
        nm = NotificationManager()
        anomaly = MagicMock()
        anomaly.severity = "critical"
        anomaly.title = "High CPU"
        anomaly.description = "CPU > 90%"
        anomaly.resource_type = "ec2"
        anomaly.resource_id = "i-123"
        anomaly.region = "us-east-1"
        anomaly.detected_at = datetime(2026, 4, 25, 5, 0, tzinfo=timezone.utc)
        anomaly.metric_name = "CPUUtilization"
        anomaly.expected_value = 50
        anomaly.actual_value = 95

        with patch.object(nm, "send_notification", new_callable=AsyncMock, return_value={"ch1": True}) as mock:
            results = run_async(nm.send_anomaly_notification(anomaly))
            assert results == {"ch1": True}
            mock.assert_called_once()
            args, kwargs = mock.call_args
            subject = kwargs.get("subject", args[0] if args else "")
            assert "CRITICAL" in subject

    def test_send_anomaly_notification_no_metric(self):
        nm = NotificationManager()
        anomaly = MagicMock()
        anomaly.severity = "low"
        anomaly.title = "Something"
        anomaly.description = "Desc"
        anomaly.resource_type = "s3"
        anomaly.resource_id = "bucket-1"
        anomaly.region = "us-west-2"
        anomaly.detected_at = datetime(2026, 4, 25, 5, 0, tzinfo=timezone.utc)
        anomaly.metric_name = None

        with patch.object(nm, "send_notification", new_callable=AsyncMock, return_value={}):
            run_async(nm.send_anomaly_notification(anomaly))

    def test_test_channel_success(self):
        mock_channel = MagicMock()
        mock_channel.channel_type = "webhook"
        mock_channel.config = {"url": "http://a.com"}

        with patch("agenticops.notify.im_config.get_channel", return_value=mock_channel):
            with patch.object(WebhookNotifier, "test_connection", new_callable=AsyncMock, return_value=True):
                assert run_async(NotificationManager.test_channel("test-wh")) is True

    def test_test_channel_not_found(self):
        with patch("agenticops.notify.im_config.get_channel", return_value=None):
            with pytest.raises(ValueError, match="not found"):
                run_async(NotificationManager.test_channel("missing"))

    def test_test_channel_unknown_type(self):
        mock_channel = MagicMock()
        mock_channel.channel_type = "foobar"

        with patch("agenticops.notify.im_config.get_channel", return_value=mock_channel):
            with pytest.raises(ValueError, match="Unknown"):
                run_async(NotificationManager.test_channel("bad-type"))
