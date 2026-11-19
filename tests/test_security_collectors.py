from unittest.mock import MagicMock, patch

from agenticops.security.collectors import (
    PostureFinding, collect_iam_findings, collect_network_findings,
    collect_data_findings, collect_logging_findings, collect_posture,
)


def _cred_report_csv(rows: list[str]) -> bytes:
    header = ("user,arn,user_creation_time,password_enabled,password_last_used,"
              "password_last_changed,mfa_active,access_key_1_active,"
              "access_key_1_last_rotated")
    return ("\n".join([header] + rows)).encode()


class TestIamCollector:
    def test_no_mfa_console_user_flagged(self):
        # console user (password_enabled true) without MFA -> cis-1.10 finding
        rows = ["alice,arn:...:user/alice,2020-01-01T00:00:00+00:00,true,2020-01-02T00:00:00+00:00,"
                "2020-01-01T00:00:00+00:00,false,false,N/A"]
        client = MagicMock()
        client.get_credential_report.return_value = {"Content": _cred_report_csv(rows)}
        with patch("agenticops.security.collectors._get_client", return_value=client):
            out = collect_iam_findings("acct-a")
        assert any(f.control_id == "cis-1.10" and f.resource_id == "alice" for f in out)

    def test_root_access_key_flagged(self):
        rows = ["<root_account>,arn:aws:iam::1:root,2019-01-01T00:00:00+00:00,true,"
                "2020-01-01T00:00:00+00:00,2019-01-01T00:00:00+00:00,true,true,2019-01-01T00:00:00+00:00"]
        client = MagicMock()
        client.get_credential_report.return_value = {"Content": _cred_report_csv(rows)}
        with patch("agenticops.security.collectors._get_client", return_value=client):
            out = collect_iam_findings("acct-a")
        assert any(f.control_id == "cis-1.4" for f in out)

    def test_collector_fail_soft_returns_empty(self):
        client = MagicMock()
        client.generate_credential_report.side_effect = RuntimeError("boom")
        client.get_credential_report.side_effect = RuntimeError("boom")
        with patch("agenticops.security.collectors._get_client", return_value=client):
            out = collect_iam_findings("acct-a")
        assert out == []


class TestCollectPostureOrchestrator:
    def test_one_source_failure_does_not_abort_others(self):
        good = [PostureFinding("network", "cis-4.1", "sg-1", "SecurityGroup", "0.0.0.0/0:22")]
        with patch("agenticops.security.collectors.collect_iam_findings", side_effect=RuntimeError("x")), \
             patch("agenticops.security.collectors.collect_network_findings", return_value=good), \
             patch("agenticops.security.collectors.collect_data_findings", return_value=[]), \
             patch("agenticops.security.collectors.collect_logging_findings", return_value=[]):
            out = collect_posture("acct-a")
        assert out == good  # iam blew up, network survived


class TestNetworkCollector:
    def _sg(self, gid, port):
        return {"GroupId": gid, "GroupName": gid, "IpPermissions": [{
            "IpProtocol": "tcp", "FromPort": port, "ToPort": port,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]}

    def test_open_ssh_flagged_41(self):
        client = MagicMock()
        client.describe_security_groups.return_value = {"SecurityGroups": [self._sg("sg-1", 22)]}
        with patch("agenticops.security.collectors._get_client", return_value=client), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            out = collect_network_findings("acct-a")
        assert any(f.control_id == "cis-4.1" and f.resource_id == "sg-1" for f in out)

    def test_open_rdp_flagged_42(self):
        client = MagicMock()
        client.describe_security_groups.return_value = {"SecurityGroups": [self._sg("sg-2", 3389)]}
        with patch("agenticops.security.collectors._get_client", return_value=client), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            out = collect_network_findings("acct-a")
        assert any(f.control_id == "cis-4.2" for f in out)

    def test_scoped_cidr_not_flagged(self):
        sg = {"GroupId": "sg-3", "GroupName": "sg-3", "IpPermissions": [{
            "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
            "IpRanges": [{"CidrIp": "10.0.0.0/8"}]}]}
        client = MagicMock()
        client.describe_security_groups.return_value = {"SecurityGroups": [sg]}
        with patch("agenticops.security.collectors._get_client", return_value=client), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            out = collect_network_findings("acct-a")
        assert out == []  # not open to the internet


class TestDataLoggingCollectors:
    def test_public_bucket_flagged(self):
        s3 = MagicMock()
        s3.list_buckets.return_value = {"Buckets": [{"Name": "public-b"}]}
        s3.get_public_access_block.return_value = {"PublicAccessBlockConfiguration": {
            "BlockPublicAcls": False, "IgnorePublicAcls": False,
            "BlockPublicPolicy": False, "RestrictPublicBuckets": False}}
        with patch("agenticops.security.collectors._get_client", return_value=s3), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            out = collect_data_findings("acct-a")
        assert any(f.control_id == "cis-2.1" and f.resource_id == "public-b" for f in out)

    def test_unencrypted_ebs_flagged(self):
        client = MagicMock()
        client.list_buckets.return_value = {"Buckets": []}
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Volumes": [{"VolumeId": "vol-1", "Encrypted": False}]}]
        client.get_paginator.return_value = paginator
        with patch("agenticops.security.collectors._get_client", return_value=client), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            out = collect_data_findings("acct-a")
        assert any(f.control_id == "cis-enc" and f.resource_id == "vol-1" for f in out)

    def test_no_multiregion_trail_flagged(self):
        ct = MagicMock()
        ct.describe_trails.return_value = {"trailList": [
            {"Name": "t1", "IsMultiRegionTrail": False, "TrailARN": "arn:t1"}]}
        ct.get_trail_status.return_value = {"IsLogging": True}
        with patch("agenticops.security.collectors._get_client", return_value=ct), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            out = collect_logging_findings("acct-a")
        assert any(f.control_id == "cis-3.1" for f in out)

    def test_multiregion_logging_trail_passes(self):
        ct = MagicMock()
        ct.describe_trails.return_value = {"trailList": [
            {"Name": "t1", "IsMultiRegionTrail": True, "TrailARN": "arn:t1"}]}
        ct.get_trail_status.return_value = {"IsLogging": True}
        with patch("agenticops.security.collectors._get_client", return_value=ct), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            out = collect_logging_findings("acct-a")
        assert out == []


# ── MVP-2.9.0 N20 (2.8.0 S3): which sources could be read ─────────────────────────────────────────────────────

from botocore.exceptions import ClientError  # noqa: E402

from agenticops.security.collectors import collect_posture_checked, failure_reason  # noqa: E402
from agenticops.security.scoring import SOURCES  # noqa: E402


def _client_error(code: str, operation: str, message: str = "User: arn:aws:sts::123456789012:assumed-role/x is not authorized"):
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


class TestCollectionHealth:
    def test_a_source_that_blew_up_is_recorded_and_the_others_are_ok(self):
        good = [PostureFinding("network", "cis-4.1", "sg-1", "SecurityGroup", "0.0.0.0/0:22")]
        with patch("agenticops.security.collectors.collect_iam_findings", side_effect=RuntimeError("x")), \
             patch("agenticops.security.collectors.collect_network_findings", return_value=good), \
             patch("agenticops.security.collectors.collect_data_findings", return_value=[]), \
             patch("agenticops.security.collectors.collect_logging_findings", return_value=[]):
            got = collect_posture_checked("acct-a")
        assert got.findings == good
        assert set(got.health) == set(SOURCES)                      # every source reports, in scoring's own names
        assert got.health["iam"] == {"ok": False, "error": "RuntimeError: x"}
        assert all(got.health[s] == {"ok": True, "error": ""} for s in SOURCES if s != "iam")
        assert got.failed_sources == frozenset({"iam"}) and got.status == "partial"

    def test_status_words(self):
        from agenticops.security.collectors import PostureCollection
        ok, bad = {"ok": True, "error": ""}, {"ok": False, "error": "x"}
        assert PostureCollection([], {s: ok for s in SOURCES}).status == "complete"
        assert PostureCollection([], {s: bad for s in SOURCES}).status == "failed"
        assert PostureCollection([], {**{s: ok for s in SOURCES}, "ebs": bad}).status == "partial"

    def test_the_iam_source_says_it_failed(self):
        client = MagicMock()
        client.generate_credential_report.side_effect = RuntimeError("boom")
        client.get_credential_report.side_effect = _client_error("AccessDenied", "GetCredentialReport")
        health: dict = {}
        with patch("agenticops.security.collectors._get_client", return_value=client):
            assert collect_iam_findings("acct-a", health=health) == []          # fail-soft as before
        assert health == {"iam": {"ok": False, "error": "AccessDenied (GetCredentialReport)"}}

    def test_the_network_source_says_it_failed(self):
        client = MagicMock()
        client.describe_security_groups.side_effect = _client_error("UnauthorizedOperation", "DescribeSecurityGroups")
        health: dict = {}
        with patch("agenticops.security.collectors._get_client", return_value=client), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            assert collect_network_findings("acct-a", health=health) == []
        assert health == {"network": {"ok": False, "error": "us-east-1: UnauthorizedOperation (DescribeSecurityGroups)"}}

    def test_the_two_data_sources_fail_apart(self):
        client = MagicMock()
        client.list_buckets.side_effect = _client_error("AccessDenied", "ListBuckets")
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Volumes": [{"VolumeId": "vol-1", "Encrypted": False}]}]
        client.get_paginator.return_value = paginator
        health: dict = {}
        with patch("agenticops.security.collectors._get_client", return_value=client), \
             patch("agenticops.security.collectors._enabled_regions", return_value=["us-east-1"]):
            out = collect_data_findings("acct-a", health=health)
        assert [f.control_id for f in out] == ["cis-enc"]
        assert health == {"s3": {"ok": False, "error": "AccessDenied (ListBuckets)"}, "ebs": {"ok": True, "error": ""}}

    def test_a_bucket_without_a_public_access_block_is_a_finding(self):
        s3 = MagicMock()
        s3.list_buckets.return_value = {"Buckets": [{"Name": "bare-b"}]}
        s3.get_public_access_block.side_effect = _client_error("NoSuchPublicAccessBlockConfiguration", "GetPublicAccessBlock")
        health: dict = {}
        with patch("agenticops.security.collectors._get_client", return_value=s3), \
             patch("agenticops.security.collectors._enabled_regions", return_value=[]):
            out = collect_data_findings("acct-a", health=health)
        assert [(f.control_id, f.resource_id) for f in out] == [("cis-2.1", "bare-b")]
        assert health["s3"] == {"ok": True, "error": ""}

    def test_a_bucket_that_could_not_be_read_is_not_called_public(self):
        """Any other error used to read as «no public-access-block configured» — a refused read is not a result."""
        s3 = MagicMock()
        s3.list_buckets.return_value = {"Buckets": [{"Name": "locked-b"}, {"Name": "open-b"}]}

        def _pab(Bucket):
            if Bucket == "locked-b":
                raise _client_error("AccessDenied", "GetPublicAccessBlock")
            return {"PublicAccessBlockConfiguration": {}}
        s3.get_public_access_block.side_effect = _pab
        health: dict = {}
        with patch("agenticops.security.collectors._get_client", return_value=s3), \
             patch("agenticops.security.collectors._enabled_regions", return_value=[]):
            out = collect_data_findings("acct-a", health=health)
        assert [f.resource_id for f in out] == ["open-b"]            # what was read is still reported
        assert health["s3"] == {"ok": False, "error": "1 of 2 buckets could not be read: AccessDenied (GetPublicAccessBlock)"}

    def test_a_trail_whose_status_could_not_be_read_is_not_called_silent(self):
        ct = MagicMock()
        ct.describe_trails.return_value = {"trailList": [{"IsMultiRegionTrail": True, "TrailARN": "arn:t1"}]}
        ct.get_trail_status.side_effect = _client_error("AccessDenied", "GetTrailStatus")
        health: dict = {}
        with patch("agenticops.security.collectors._get_client", return_value=ct):
            assert collect_logging_findings("acct-a", health=health) == []
        assert health == {"logging": {"ok": False, "error": "a trail's status could not be read: AccessDenied (GetTrailStatus)"}}

    def test_one_logging_trail_is_enough_whatever_the_others_answer(self):
        ct = MagicMock()
        ct.describe_trails.return_value = {"trailList": [{"IsMultiRegionTrail": True, "TrailARN": "arn:t1"},
                                                         {"IsMultiRegionTrail": True, "TrailARN": "arn:t2"}]}
        ct.get_trail_status.side_effect = [_client_error("AccessDenied", "GetTrailStatus"), {"IsLogging": True}]
        health: dict = {}
        with patch("agenticops.security.collectors._get_client", return_value=ct):
            assert collect_logging_findings("acct-a", health=health) == []
        assert health == {"logging": {"ok": True, "error": ""}}

    def test_no_trail_logging_is_still_a_finding(self):
        ct = MagicMock()
        ct.describe_trails.return_value = {"trailList": [{"IsMultiRegionTrail": True, "TrailARN": "arn:t1"}]}
        ct.get_trail_status.return_value = {"IsLogging": False}
        health: dict = {}
        with patch("agenticops.security.collectors._get_client", return_value=ct):
            out = collect_logging_findings("acct-a", health=health)
        assert [f.control_id for f in out] == ["cis-3.1"] and health["logging"]["ok"] is True

    def test_a_reason_names_the_error_code_not_the_message(self):
        """The message of a refused call names roles and account numbers; the stored reason is the code and the call."""
        assert failure_reason(_client_error("AccessDenied", "ListBuckets")) == "AccessDenied (ListBuckets)"
        assert failure_reason(RuntimeError("x" * 500)) == "RuntimeError: " + "x" * 146      # cut at 160
        assert failure_reason(TimeoutError()) == "TimeoutError"

    def test_collect_posture_is_still_the_plain_list(self):
        good = [PostureFinding("network", "cis-4.1", "sg-1", "SecurityGroup", "0.0.0.0/0:22")]
        with patch("agenticops.security.collectors.collect_iam_findings", return_value=[]), \
             patch("agenticops.security.collectors.collect_network_findings", return_value=good), \
             patch("agenticops.security.collectors.collect_data_findings", return_value=[]), \
             patch("agenticops.security.collectors.collect_logging_findings", return_value=[]):
            assert collect_posture("acct-a") == good
