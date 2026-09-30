"""W2 absent-marking (MVP-2.6.1 Plan B Task 10): scanner/engine marks a row absent only when a complete
listing of its (type, region) unit no longer sees it. Never a truncated, failed, paged or partial listing;
never another region, provider or an ARN row; never after a failed save; never a delete. cli_tool is mocked:
no test here reaches AWS."""
import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticops.models import Base, CloudAccount, CloudResource, get_session
from agenticops.scanner import engine
from agenticops.scanner.parsers import (
    _PARSERS,
    EXPECTED_KEY,
    PARSER_RESOURCE_TYPE,
    parse_cli_output,
    parse_cli_output_checked,
)

ACCT = 1
T0 = datetime(2026, 9, 1, 12, 0)

# One minimal complete listing per parser, each yielding one resource.
SAMPLES = {
    "aws_ec2_instances": {"Reservations": [{"Instances": [{"InstanceId": "i-1"}]}]},
    "aws_lambda_functions": {"Functions": [{"FunctionName": "f1"}]},
    "aws_ecs_clusters": {"clusterArns": ["arn:aws:ecs:us-east-1:111111111111:cluster/c1"]},
    "aws_eks_clusters": {"clusters": ["c1"]},
    "aws_rds_instances": {"DBInstances": [{"DBInstanceIdentifier": "db1"}]},
    "aws_dynamodb_tables": {"TableNames": ["t1"]},
    "aws_elasticache": {"CacheClusters": [{"CacheClusterId": "cc1"}]},
    "aws_s3_buckets": {"Buckets": [{"Name": "b1"}]},
    "aws_ebs_volumes": {"Volumes": [{"VolumeId": "vol-1"}]},
    "aws_vpcs": {"Vpcs": [{"VpcId": "vpc-1"}]},
    "aws_security_groups": {"SecurityGroups": [{"GroupId": "sg-1"}]},
    "aws_load_balancers": {"LoadBalancers": [{"LoadBalancerName": "lb1"}]},
    "aws_subnets": {"Subnets": [{"SubnetId": "subnet-1"}]},
    "aws_iam_roles": {"Roles": [{"RoleName": "r1"}]},
    "aws_autoscaling_groups": {"AutoScalingGroups": [{"AutoScalingGroupName": "asg1"}]},
    "aws_nat_gateways": {"NatGateways": [{"NatGatewayId": "nat-1"}]},
    "aws_route53_zones": {"HostedZones": [{"Id": "/hostedzone/Z1", "Name": "x.com."}]},
    "aws_opensearch_domains": {"DomainNames": [{"DomainName": "d1"}]},
    "aws_efs_file_systems": {"FileSystems": [{"FileSystemId": "fs-1"}]},
    "aws_kms_keys": {"Keys": [{"KeyId": "k1"}]},
}


# ── parse_cli_output_checked ───────────────────────────────────────


def test_the_maps_cover_every_parser():
    assert set(EXPECTED_KEY) == set(PARSER_RESOURCE_TYPE) == set(_PARSERS) == set(SAMPLES)


@pytest.mark.parametrize("parser_key", sorted(SAMPLES))
def test_a_complete_listing_is_complete(parser_key):
    raw = json.dumps(SAMPLES[parser_key])
    resources, complete = parse_cli_output_checked(parser_key, raw, "us-east-1")
    assert complete is True
    assert resources == parse_cli_output(parser_key, raw, "us-east-1")
    assert len(resources) == 1
    assert resources[0]["resource_type"] == PARSER_RESOURCE_TYPE[parser_key]
    assert not resources[0]["resource_id"].startswith("arn:")  # deviation 37: W2 never writes an ARN row


@pytest.mark.parametrize("parser_key,raw", [
    ("aws_ec2_instances", '{"Reservations": []}\n... (truncated)'),
    ("aws_ec2_instances", "Error: timed out after 120s"),
    ("aws_ec2_instances", "Error (exit 1): An error occurred (UnauthorizedOperation)"),
    ("aws_ec2_instances", "(no output)"),
    ("aws_ec2_instances", "[]"),
    ("aws_ec2_instances", '{"Other": []}'),
    ("aws_ec2_instances", '{"Reservations": {}}'),
    ("aws_ec2_instances", '{"Reservations": [], "NextToken": "abc"}'),
    ("aws_route53_zones", '{"HostedZones": [], "IsTruncated": true}'),
    ("aws_ec2_instances", '{"Reservations": [{"Instances": [{}]}]}'),  # the parser raises KeyError
    ("aws_ec2_instances", "not json"),
])
def test_an_incomplete_listing_is_not_complete(parser_key, raw):
    resources, complete = parse_cli_output_checked(parser_key, raw, "us-east-1")
    assert complete is False
    assert resources == parse_cli_output(parser_key, raw, "us-east-1")


def test_an_unknown_parser_key_is_not_complete():
    assert parse_cli_output_checked("aws_nope", '{"Things": []}', "us-east-1") == ([], False)


# ── scan_accounts_parallel on a real (temporary) DB ────────────────


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/scan.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(id=ACCT, name="global", provider="aws", is_enabled=True, credentials={}))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _row(s, rid, rtype="EC2", region="us-east-1", provider="aws", absent_since=None):
    r = CloudResource(account_id=ACCT, provider=provider, region=region, resource_type=rtype, resource_id=rid,
                      name=rid, tags={}, raw_data={}, status="running", scanned_at=T0, absent_since=absent_since)
    s.add(r)
    s.commit()
    return r.id


def _absent(s, pk):
    s.expire_all()
    return s.get(CloudResource, pk).absent_since


def _ec2(*ids):
    return json.dumps({"Reservations": [{"Instances": [{"InstanceId": i} for i in ids]}]})


def _cli(outputs):
    """A mocked cli_tool: outputs maps "<service> <operation>@<region|global>" to the raw CLI text.
    Every other call fails the way the real cli_tool does, so its unit is never complete."""
    def run(command):
        parts = command.split()
        region = parts[parts.index("--region") + 1] if "--region" in parts else "global"
        return outputs.get(f"{parts[1]} {parts[2]}@{region}", "Error (exit 254): not mocked")
    return MagicMock(side_effect=run)


def _scan(cli, focus="computing", regions=("us-east-1",)):
    acct = SimpleNamespace(id=ACCT, name="global", provider="aws", credentials={}, regions=list(regions),
                           labels={})
    with patch("agenticops.scanner.engine._load_accounts", return_value=[acct]), \
         patch("agenticops.scanner.engine._get_provider_and_tool", return_value=(MagicMock(), cli)):
        return asyncio.run(engine.scan_accounts_parallel(focus=focus)).accounts[0]


def test_a_complete_unit_marks_only_unseen_rows(db):
    live, gone = _row(db, "i-live"), _row(db, "i-gone")
    out = _scan(_cli({"ec2 describe-instances@us-east-1": _ec2("i-live")}))
    assert ("EC2", "us-east-1") in out.complete_units
    assert out.resources_absent == 1
    assert _absent(db, live) is None
    assert _absent(db, gone) is not None


def test_a_truncated_unit_marks_nothing_and_warns(db, caplog):
    gone = _row(db, "i-gone")
    with caplog.at_level(logging.WARNING, logger="agenticops.scanner.parsers"):
        out = _scan(_cli({"ec2 describe-instances@us-east-1": _ec2("i-live") + "\n... (truncated)"}))
    assert out.complete_units == [] and out.resources_absent == 0
    assert _absent(db, gone) is None
    assert any("truncated" in r.getMessage() for r in caplog.records)


def test_another_region_is_left_alone(db):
    east, west = _row(db, "i-east"), _row(db, "i-west", region="us-west-2")
    _scan(_cli({"ec2 describe-instances@us-east-1": _ec2()}))
    assert _absent(db, east) is not None
    assert _absent(db, west) is None


def test_kubernetes_rows_are_untouched(db):
    """Deviation 11: marking is limited to provider="aws"."""
    k8s = _row(db, "lab/Deployment/default/web", rtype="K8s_Deployment", provider="kubernetes")
    clash = _row(db, "lab/EC2/web", provider="kubernetes")  # same type and region: only provider differs
    _scan(_cli({"ec2 describe-instances@us-east-1": _ec2()}))
    assert _absent(db, k8s) is None
    assert _absent(db, clash) is None


def test_arn_rows_are_untouched(db):
    arn = _row(db, "arn:aws:ec2:us-east-1:111111111111:instance/i-arn")
    short = _row(db, "i-gone")
    _scan(_cli({"ec2 describe-instances@us-east-1": _ec2()}))
    assert _absent(db, arn) is None
    assert _absent(db, short) is not None


def test_a_failed_save_marks_nothing(db):
    gone = _row(db, "i-gone")
    with patch("agenticops.tools.metadata_tools.save_resources", return_value="Error saving resources: disk full"):
        out = _scan(_cli({"ec2 describe-instances@us-east-1": _ec2("i-live")}))
    assert out.resources_absent == 0
    assert "save: Error saving resources: disk full" in out.errors
    assert _absent(db, gone) is None


def test_an_empty_complete_listing_marks(db):
    gone = _row(db, "i-gone")
    out = _scan(_cli({"ec2 describe-instances@us-east-1": _ec2()}))
    assert out.resources_found == 0 and out.resources_absent == 1
    assert _absent(db, gone) is not None


def test_a_row_seen_again_returns(db):
    back = _row(db, "i-back", absent_since=T0)
    out = _scan(_cli({"ec2 describe-instances@us-east-1": _ec2("i-back")}))
    assert out.resources_absent == 0
    assert _absent(db, back) is None


def test_a_row_touched_during_the_scan_is_not_marked(db):
    """Ruling PF-e: another writer saw this row after the listing began, so this scan's seen set is stale."""
    touched, gone = _row(db, "i-touched"), _row(db, "i-gone")
    listing = _cli({"ec2 describe-instances@us-east-1": _ec2()})

    def run(command):
        s = get_session()
        s.get(CloudResource, touched).scanned_at = datetime.now(timezone.utc)  # a concurrent writer
        s.commit()
        s.close()
        return listing(command)

    out = _scan(MagicMock(side_effect=run))
    assert out.resources_absent == 1
    assert _absent(db, touched) is None
    assert _absent(db, gone) is not None


def test_rows_are_never_deleted(db):
    for rid in ("i-1", "i-2", "i-3"):
        _row(db, rid)
    _scan(_cli({"ec2 describe-instances@us-east-1": _ec2()}))
    db.expire_all()
    assert db.query(CloudResource).count() == 3
    assert db.query(CloudResource).filter(CloudResource.absent_since.isnot(None)).count() == 3


def test_an_unknown_focus_gives_no_units(db):
    gone = _row(db, "i-gone")
    cli = _cli({"ec2 describe-instances@us-east-1": _ec2()})
    out = _scan(cli, focus="nonsense")
    assert out.complete_units == [] and cli.call_count == 0
    assert _absent(db, gone) is None


def test_a_global_unit_is_recorded_with_region_global(db):
    gone = _row(db, "b-gone", rtype="S3", region="global")
    out = _scan(_cli({"s3api list-buckets@global": json.dumps({"Buckets": [{"Name": "b1"}]})}), focus="storage")
    assert ("S3", "global") in out.complete_units
    assert _absent(db, gone) is not None


def test_a_marking_failure_is_reported_not_raised(db):
    with patch("agenticops.scanner.engine._mark_absent", side_effect=RuntimeError("database is locked")):
        out = _scan(_cli({"ec2 describe-instances@us-east-1": _ec2()}))
    assert "absent: database is locked" in out.errors


# ── surfaces ───────────────────────────────────────────────────────


def _one_account_result(absent):
    from agenticops.scanner.engine import AccountScanResult, ScanResult

    return ScanResult(accounts=[AccountScanResult(account_id=ACCT, account_name="global", provider="aws",
                                                  resources_found=2, resources_updated=1,
                                                  regions_scanned=["us-east-1"], resources_absent=absent)],
                      total_found=2, total_updated=1, duration_s=0.1)


def test_api_scan_carries_resources_absent():
    from starlette.testclient import TestClient

    from agenticops.web.app import app

    with patch("agenticops.scanner.scan_accounts_parallel", new_callable=AsyncMock,
               return_value=_one_account_result(3)), \
         patch("agenticops.web.app._safe_galaxy_rebuild_after_scan"):
        resp = TestClient(app).post("/api/scan", json={})
    assert resp.status_code == 200
    assert resp.json()["accounts"][0]["resources_absent"] == 3


def test_scan_agent_summary_shows_the_absent_count():
    from agenticops.agents.scan_agent import scan_resources

    with patch("agenticops.scanner.scan_accounts_parallel", new_callable=AsyncMock,
               return_value=_one_account_result(3)):
        out = scan_resources()
    assert "global (aws): 2 found, 1 updated, 3 absent, regions=['us-east-1']" in out
