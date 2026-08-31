# tests/test_security_poll.py
"""Stage 4: cursor-based incremental security polling."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops import models


@pytest.fixture
def sess_factory():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def _sess():
        s = Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return _sess


class TestCursorStore:
    def test_get_cursor_default_is_recent_iso(self, sess_factory):
        from agenticops.security.incremental_poll import _get_cursor
        with sess_factory() as s:
            cur = _get_cursor(s, "acct-a", "guardduty", "us-east-1")
        dt = datetime.fromisoformat(cur)
        age = datetime.now(timezone.utc) - dt
        assert timedelta(hours=23) < age < timedelta(hours=25)  # ~24h backfill

    def test_set_then_get_roundtrip(self, sess_factory):
        from agenticops.security.incremental_poll import _get_cursor, _set_cursor
        with sess_factory() as s:
            _set_cursor(s, "acct-a", "guardduty", "us-east-1", "2026-08-31T01:00:00+00:00")
        with sess_factory() as s:
            assert _get_cursor(s, "acct-a", "guardduty", "us-east-1") == "2026-08-31T01:00:00+00:00"

    def test_set_cursor_upserts_single_row(self, sess_factory):
        from agenticops.security.incremental_poll import _set_cursor
        with sess_factory() as s:
            _set_cursor(s, "acct-a", "securityhub", "us-east-1", "2026-08-31T01:00:00+00:00")
        with sess_factory() as s:
            _set_cursor(s, "acct-a", "securityhub", "us-east-1", "2026-08-31T02:00:00+00:00")
        with sess_factory() as s:
            rows = s.query(models.SecurityPollCursor).all()
            assert len(rows) == 1
            assert rows[0].cursor == "2026-08-31T02:00:00+00:00"


def _gd_finding(fid, sev, updated="2026-08-31T02:00:00.000Z", instance="i-1"):
    return {
        "Id": fid, "Severity": sev, "UpdatedAt": updated,
        "Title": "Recon:EC2/PortProbeUnprotectedPort",
        "Description": "EC2 instance has an unprotected port probed.",
        "Resource": {"ResourceType": "Instance",
                     "InstanceDetails": {"InstanceId": instance}},
    }


class TestGuardDutyPoller:
    def _client(self, findings):
        gd = MagicMock()
        gd.list_detectors.return_value = {"DetectorIds": ["det-1"]}
        paginator = MagicMock()
        paginator.paginate.return_value = [{"FindingIds": [f["Id"] for f in findings]}]
        gd.get_paginator.return_value = paginator
        gd.get_findings.return_value = {"Findings": findings}
        return gd

    def test_maps_finding_to_security_event(self):
        from agenticops.security.incremental_poll import poll_guardduty
        gd = self._client([_gd_finding("f-1", 8.0)])
        with patch("agenticops.security.incremental_poll._get_client", return_value=gd):
            out = poll_guardduty("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00")
        assert len(out) == 1
        ev = out[0]
        assert ev.source == "guardduty"
        assert ev.event_id == "f-1"
        assert ev.severity == "high"
        assert ev.resource_id == "i-1"
        assert ev.occurred_at == "2026-08-31T02:00:00.000Z"

    def test_severity_bands(self):
        from agenticops.security.incremental_poll import _gd_severity
        assert _gd_severity(9.1) == "critical"
        assert _gd_severity(7.0) == "high"
        assert _gd_severity(4.5) == "medium"
        assert _gd_severity(2.0) == "low"

    def test_no_detector_returns_empty(self):
        from agenticops.security.incremental_poll import poll_guardduty
        gd = MagicMock()
        gd.list_detectors.return_value = {"DetectorIds": []}
        with patch("agenticops.security.incremental_poll._get_client", return_value=gd):
            assert poll_guardduty("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00") == []

    def test_api_error_propagates(self):
        from agenticops.security.incremental_poll import poll_guardduty
        gd = MagicMock()
        gd.list_detectors.side_effect = RuntimeError("boom")
        with patch("agenticops.security.incremental_poll._get_client", return_value=gd):
            with pytest.raises(RuntimeError):
                poll_guardduty("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00")


def _sh_finding(fid, label, updated="2026-08-31T02:00:00Z"):
    return {"Id": fid, "UpdatedAt": updated,
            "Title": "S3 bucket public", "Description": "Bucket allows public read.",
            "Severity": {"Label": label},
            "Resources": [{"Id": "arn:aws:s3:::b1", "Type": "AwsS3Bucket"}]}


class TestSecurityHubPoller:
    def _client(self, findings):
        sh = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Findings": findings}]
        sh.get_paginator.return_value = paginator
        return sh

    def test_maps_finding(self):
        from agenticops.security.incremental_poll import poll_securityhub
        sh = self._client([_sh_finding("arn:f1", "HIGH")])
        with patch("agenticops.security.incremental_poll._get_client", return_value=sh):
            out = poll_securityhub("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00")
        assert out[0].source == "securityhub"
        assert out[0].severity == "high"
        assert out[0].resource_id == "arn:aws:s3:::b1"

    def test_informational_maps_to_low(self):
        from agenticops.security.incremental_poll import poll_securityhub
        sh = self._client([_sh_finding("arn:f2", "INFORMATIONAL")])
        with patch("agenticops.security.incremental_poll._get_client", return_value=sh):
            out = poll_securityhub("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00")
        assert out[0].severity == "low"

    def test_filters_include_active_new_and_cursor(self):
        from agenticops.security.incremental_poll import poll_securityhub
        sh = self._client([])
        with patch("agenticops.security.incremental_poll._get_client", return_value=sh):
            poll_securityhub("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00")
        filters = sh.get_paginator.return_value.paginate.call_args.kwargs["Filters"]
        assert filters["RecordState"] == [{"Value": "ACTIVE", "Comparison": "EQUALS"}]
        assert filters["WorkflowStatus"] == [{"Value": "NEW", "Comparison": "EQUALS"}]
        assert filters["UpdatedAt"][0]["Start"] == "2026-08-31T00:00:00+00:00"


def _ct_event(name, eid="e-1", when=None, username="alice"):
    return {"EventId": eid, "EventName": name, "Username": username,
            "EventTime": when or datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc),
            "Resources": [{"ResourceName": "trail-1", "ResourceType": "AWS::CloudTrail::Trail"}]}


class TestCloudTrailPoller:
    def _client(self, events):
        ct = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Events": events}]
        ct.get_paginator.return_value = paginator
        return ct

    def test_high_risk_event_captured(self):
        from agenticops.security.incremental_poll import poll_cloudtrail
        ct = self._client([_ct_event("StopLogging")])
        with patch("agenticops.security.incremental_poll._get_client", return_value=ct):
            out = poll_cloudtrail("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00")
        assert len(out) == 1
        assert out[0].source == "cloudtrail"
        assert out[0].severity == "high"
        assert "StopLogging" in out[0].title
        assert out[0].resource_id == "trail-1"

    def test_benign_event_filtered_out(self):
        from agenticops.security.incremental_poll import poll_cloudtrail
        ct = self._client([_ct_event("DescribeInstances")])
        with patch("agenticops.security.incremental_poll._get_client", return_value=ct):
            out = poll_cloudtrail("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00")
        assert out == []

    def test_username_fallback_resource(self):
        from agenticops.security.incremental_poll import poll_cloudtrail
        ev = _ct_event("CreateAccessKey")
        ev["Resources"] = []
        ct = self._client([ev])
        with patch("agenticops.security.incremental_poll._get_client", return_value=ct):
            out = poll_cloudtrail("acct-a", "us-east-1", "2026-08-31T00:00:00+00:00")
        assert out[0].resource_id == "alice"
