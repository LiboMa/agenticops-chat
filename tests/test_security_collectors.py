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
