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


class TestRunIncrementalPoll:
    def _setup(self, monkeypatch, sess_factory, pollers):
        import agenticops.security.incremental_poll as ip
        monkeypatch.setattr(ip, "get_db_session", sess_factory, raising=False)
        monkeypatch.setattr(ip, "_resolve_security_accounts", lambda: ["acct-a"])
        monkeypatch.setattr(ip, "_enabled_regions", lambda a: ["us-east-1"])
        monkeypatch.setattr(ip, "_reachability_lookup", lambda a: {})
        monkeypatch.setattr(ip, "_SOURCE_POLLERS", pollers)
        return ip

    def test_signals_emitted_and_cursor_advanced(self, monkeypatch, sess_factory):
        from agenticops.security.incremental_poll import SecurityEvent
        ev = SecurityEvent("guardduty", "f-1", "t", "d", "high", "i-1", "Instance",
                           "2026-08-31T02:00:00+00:00")
        ip = self._setup(monkeypatch, sess_factory, {"guardduty": lambda a, r, s: [ev]})
        calls = []
        with patch("agenticops.services.signal_gate.process_signal",
                   side_effect=lambda sig: calls.append(sig) or MagicMock(disposition="promoted")):
            n = ip.run_incremental_poll()
        assert n == 1
        sig = calls[0]
        assert sig.source == "security_poll"
        assert sig.upstream_key == "f-1"
        assert sig.issue_type == "security_finding"
        assert sig.auto_rca is True
        assert sig.detected_by == "security_poll"
        assert sig.kind == "detection"
        assert sig.account_id == "acct-a"
        with sess_factory() as s:
            row = s.query(models.SecurityPollCursor).filter_by(source="guardduty").one()
            assert row.cursor > "2026-08-31"  # advanced to poll_start (now)

    def test_source_failure_does_not_advance_cursor(self, monkeypatch, sess_factory):
        def _boom(a, r, s):
            raise RuntimeError("api down")
        ip = self._setup(monkeypatch, sess_factory, {"guardduty": _boom})
        with patch("agenticops.services.signal_gate.process_signal") as ps:
            n = ip.run_incremental_poll()
        assert n == 0
        ps.assert_not_called()
        with sess_factory() as s:
            assert s.query(models.SecurityPollCursor).count() == 0

    def test_reachability_from_snapshot_attached(self, monkeypatch, sess_factory):
        from agenticops.security.incremental_poll import SecurityEvent
        ev = SecurityEvent("guardduty", "f-2", "t", "d", "high", "i-9", "Instance",
                           "2026-08-31T02:00:00+00:00")
        ip = self._setup(monkeypatch, sess_factory, {"guardduty": lambda a, r, s: [ev]})
        monkeypatch.setattr(ip, "_reachability_lookup", lambda a: {
            "i-9": {"reachability": "reachable", "path": ["internet", "sn-1", "i-9:22"], "port": 22}})
        calls = []
        with patch("agenticops.services.signal_gate.process_signal",
                   side_effect=lambda sig: calls.append(sig) or MagicMock(disposition="promoted")):
            ip.run_incremental_poll()
        assert calls[0].metric_data["reachability"] == "reachable"

    def test_reachability_lookup_reads_latest_snapshot(self, sess_factory, monkeypatch):
        import agenticops.security.incremental_poll as ip
        monkeypatch.setattr(ip, "get_db_session", sess_factory, raising=False)
        with sess_factory() as s:
            s.add(models.SecuritySnapshot(
                account_id="acct-a", provider="aws", overall_score=50.0,
                exposure_paths=[{"resource_id": "sg-1", "port": 22,
                                 "path": ["internet", "sn-1", "i-7:22"],
                                 "reachability": "reachable"}]))
        m = ip._reachability_lookup("acct-a")
        assert m["sg-1"]["reachability"] == "reachable"
        assert m["i-7"]["reachability"] == "reachable"  # instance id from path tail
