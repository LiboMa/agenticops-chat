import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops.models import Base, SecuritySnapshot, SecurityRecommendation
from agenticops.security.collectors import PostureFinding


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


class TestSecurityModels:
    def test_snapshot_roundtrip(self, session):
        snap = SecuritySnapshot(
            account_id="533267047935", provider="aws", overall_score=72.5,
            category_scores={"iam": 66.6, "network": 50.0},
            metrics={"no_mfa": 3, "open_sg": 2},
            exposure_paths=[{"resource_id": "i-1", "port": 22, "reachability": "reachable"}],
            cis_results={"cis-1.3": "fail", "cis-4.1": "pass"},
        )
        session.add(snap)
        session.commit()
        got = session.query(SecuritySnapshot).one()
        assert got.overall_score == 72.5
        assert got.category_scores["iam"] == 66.6
        assert got.cis_results["cis-1.3"] == "fail"
        assert got.created_at is not None

    def test_recommendation_fk_nullable(self, session):
        rec = SecurityRecommendation(
            account_id="533267047935", category="network",
            title="Restrict SSH", detail="close 0.0.0.0/0:22",
            evidence_refs=["sg-abc"], severity="high",
            critic_verdict="supported", confidence=0.8, status="open",
        )
        session.add(rec)
        session.commit()
        got = session.query(SecurityRecommendation).one()
        assert got.snapshot_id is None
        assert got.evidence_refs == ["sg-abc"]
        assert got.status == "open"


class TestRunPostureSnapshot:
    def test_writes_one_snapshot_per_account(self, monkeypatch):
        import agenticops.security.posture_snapshot as ps
        from agenticops import models

        # in-memory DB shared by the job
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from contextlib import contextmanager
        @contextmanager
        def _sess():
            s = Session()
            try:
                yield s; s.commit()
            finally:
                s.close()

        monkeypatch.setattr(ps, "get_db_session", _sess)
        monkeypatch.setattr(ps, "_resolve_security_accounts", lambda: ["acct-a", "acct-b"])
        monkeypatch.setattr(ps, "collect_posture",
                            lambda a: [PostureFinding("network", "cis-4.1", "sg-1", "SG", "open")])

        n = ps.run_posture_snapshot()
        assert n == 2
        with _sess() as s:
            snaps = s.query(models.SecuritySnapshot).all()
            assert len(snaps) == 2
            assert 0 < snaps[0].overall_score < 100  # one control failed
            assert snaps[0].cis_results["cis-4.1"] == "fail"

    def test_account_failure_is_isolated(self, monkeypatch):
        import agenticops.security.posture_snapshot as ps
        from agenticops import models
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from contextlib import contextmanager
        engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        @contextmanager
        def _sess():
            s = Session()
            try:
                yield s; s.commit()
            finally:
                s.close()
        monkeypatch.setattr(ps, "get_db_session", _sess)
        monkeypatch.setattr(ps, "_resolve_security_accounts", lambda: ["bad", "good"])

        def _collect(a):
            if a == "bad":
                raise RuntimeError("creds failed")
            return []
        monkeypatch.setattr(ps, "collect_posture", _collect)

        n = ps.run_posture_snapshot()
        assert n == 1  # good account still produced a snapshot


import json
from unittest.mock import MagicMock, patch as _patch


class TestAggregateTopology:
    def test_aggregates_across_vpcs(self, monkeypatch):
        import agenticops.security.posture_snapshot as ps
        topo = {"subnets": [{"subnet_id": "sn-1", "type": "public",
                             "default_route_target": "igw-1", "map_public_ip_on_launch": True}],
                "security_group_dependency_map": {
                    "sg-1": {"name": "web", "inbound_rules": [
                        {"protocol": "tcp", "ports": "22", "sources": ["0.0.0.0/0"]}]}}}
        compute = {"ec2_instances": [{"instance_id": "i-1", "state": "running",
                                      "public_ip": "1.2.3.4", "subnet_id": "sn-1",
                                      "security_group_ids": ["sg-1"]}]}
        ec2 = MagicMock()
        ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-1"}]}
        monkeypatch.setattr(ps, "_enabled_regions", lambda a: ["us-east-1"], raising=False)
        with _patch("agenticops.security.posture_snapshot._agg_get_client", return_value=ec2), \
             _patch("agenticops.tools.network_tools.analyze_vpc_topology",
                    return_value=json.dumps(topo)), \
             _patch("agenticops.graph.collectors.collect_vpc_compute", return_value=compute), \
             _patch("agenticops.security.collectors.collect_network_acls",
                    return_value={"sn-1": {"nacl_id": "acl-1", "inbound": [], "outbound": []}}):
            instances, subnets, sgs, nacls = ps._aggregate_topology("acct-a")
        assert instances["i-1"]["subnet_id"] == "sn-1"
        assert subnets["sn-1"]["type"] == "public"
        assert sgs["sg-1"]["inbound_rules"][0]["ports"] == "22"
        assert nacls["sn-1"]["nacl_id"] == "acl-1"

    def test_region_failure_is_isolated(self, monkeypatch):
        import agenticops.security.posture_snapshot as ps
        monkeypatch.setattr(ps, "_enabled_regions", lambda a: ["bad-1", "us-east-1"], raising=False)
        good_ec2 = MagicMock()
        good_ec2.describe_vpcs.return_value = {"Vpcs": []}

        def _client(service, region, account):
            if region == "bad-1":
                raise RuntimeError("region down")
            return good_ec2
        with _patch("agenticops.security.posture_snapshot._agg_get_client", side_effect=_client), \
             _patch("agenticops.security.collectors.collect_network_acls", return_value={}):
            instances, subnets, sgs, nacls = ps._aggregate_topology("acct-a")
        assert (instances, subnets, sgs, nacls) == ({}, {}, {}, {})
