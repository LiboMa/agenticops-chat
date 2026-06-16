"""Tests for credentials/resolver — account-addressed resolution + inventory lookup.

Covers: resolve_default_account (0/1/N), resolve_account_session (by name /
account_id / unknown / resolve-fail / cache-hit), get_subprocess_env_for_account
(strip + inject), find_instance_account (inventory + probe + miss),
find_cluster_account, get_instance_ips, and find_ssh_account_for_host.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.models import Base, CloudAccount, CloudResource, init_db
from agenticops.credentials import resolver
from agenticops.providers.base import _session_cache


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _patch_db(db_session, monkeypatch):
    """Route resolver DB lookups to the in-memory test session; clear cache."""
    @contextmanager
    def fake_db():
        yield db_session

    monkeypatch.setattr("agenticops.models.get_db_session", fake_db)
    _session_cache.clear()
    yield
    _session_cache.clear()


def _add_account(db, name, account_id, provider="aws", regions=("us-east-1",), enabled=True, creds=None):
    c = dict(creds or {})
    c.setdefault("account_id", account_id)
    c.setdefault("role_arn", f"arn:aws:iam::{account_id}:role/Ops")
    a = CloudAccount(name=name, provider=provider, is_enabled=enabled, credentials=c, regions=list(regions))
    db.add(a)
    db.commit()
    return a


def _add_resource(db, account, resource_id, rtype="EC2", region="us-east-1", raw=None):
    r = CloudResource(
        account_id=account.id, provider="aws", region=region,
        resource_type=rtype, resource_id=resource_id, name="", raw_data=raw or {}, tags={},
    )
    db.add(r)
    db.commit()
    return r


def _fake_session(key="K", secret="S", token="T"):
    frozen = MagicMock(access_key=key, secret_key=secret, token=token)
    sess = MagicMock()
    sess.get_credentials.return_value.get_frozen_credentials.return_value = frozen
    return sess


# ── resolve_default_account ──────────────────────────────────────────────


def test_default_account_zero_raises(db_session):
    with pytest.raises(resolver.AccountResolutionError) as e:
        resolver.resolve_default_account("aws")
    assert "No enabled" in str(e.value)


def test_default_account_single(db_session):
    _add_account(db_session, "prod", "111")
    snap = resolver.resolve_default_account("aws")
    assert snap.name == "prod"


def test_default_account_ambiguous_lists_names(db_session):
    _add_account(db_session, "prod", "111")
    _add_account(db_session, "staging", "222")
    with pytest.raises(resolver.AccountResolutionError) as e:
        resolver.resolve_default_account("aws")
    assert "prod" in str(e.value) and "staging" in str(e.value)


# ── resolve_account_session ──────────────────────────────────────────────


def test_resolve_session_by_name(db_session, monkeypatch):
    _add_account(db_session, "prod", "111")
    sess = _fake_session()
    prov = MagicMock()
    prov.resolve_credentials.return_value = True
    prov.sdk_session.return_value = sess
    monkeypatch.setattr("agenticops.providers.get_provider", lambda snap: prov)

    out = resolver.resolve_account_session("prod", "us-east-1")
    assert out is sess
    # cached under both key shapes
    assert _session_cache.get("aws:prod:us-east-1") is sess
    assert _session_cache.get("111:us-east-1") is sess


def test_resolve_session_by_account_id(db_session, monkeypatch):
    _add_account(db_session, "prod", "111")
    sess = _fake_session()
    prov = MagicMock()
    prov.resolve_credentials.return_value = True
    prov.sdk_session.return_value = sess
    monkeypatch.setattr("agenticops.providers.get_provider", lambda snap: prov)

    out = resolver.resolve_account_session("111", "us-east-1")
    assert out is sess


def test_resolve_session_unknown_lists_names(db_session):
    _add_account(db_session, "prod", "111")
    with pytest.raises(resolver.AccountResolutionError) as e:
        resolver.resolve_account_session("ghost", "us-east-1")
    assert "prod" in str(e.value)


def test_resolve_session_fail_closed_when_provider_false(db_session, monkeypatch):
    _add_account(db_session, "prod", "111")
    prov = MagicMock()
    prov.resolve_credentials.return_value = False
    monkeypatch.setattr("agenticops.providers.get_provider", lambda snap: prov)

    with pytest.raises(resolver.AccountResolutionError) as e:
        resolver.resolve_account_session("prod", "us-east-1")
    assert "resolution failed" in str(e.value).lower()


def test_resolve_session_cache_hit_skips_provider(db_session, monkeypatch):
    _add_account(db_session, "prod", "111")
    sess = _fake_session()
    _session_cache["aws:prod:us-east-1"] = sess
    prov = MagicMock()
    monkeypatch.setattr("agenticops.providers.get_provider", lambda snap: prov)

    out = resolver.resolve_account_session("prod", "us-east-1")
    assert out is sess
    prov.resolve_credentials.assert_not_called()


# ── get_subprocess_env_for_account ───────────────────────────────────────


def test_env_strips_ambient_and_injects(db_session, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "ambient")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENT")
    sess = _fake_session(key="ACCT", secret="SEC", token="TOK")
    monkeypatch.setattr(resolver, "resolve_account_session", lambda ref, region=None: sess)

    env = resolver.get_subprocess_env_for_account("prod", "eu-west-1")
    assert env["AWS_ACCESS_KEY_ID"] == "ACCT"
    assert env["AWS_SECRET_ACCESS_KEY"] == "SEC"
    assert env["AWS_SESSION_TOKEN"] == "TOK"
    assert env["AWS_DEFAULT_REGION"] == "eu-west-1"
    assert "AWS_PROFILE" not in env


# ── find_instance_account ────────────────────────────────────────────────


def test_find_instance_inventory_hit(db_session):
    a = _add_account(db_session, "prod", "111", regions=["us-east-1"])
    _add_resource(db_session, a, "i-0123456789abcdef0", region="us-east-1")
    found = resolver.find_instance_account("i-0123456789abcdef0")
    assert found is not None
    snap, region = found
    assert snap.name == "prod"
    assert region == "us-east-1"


def test_find_instance_inventory_hit_by_arn(db_session):
    a = _add_account(db_session, "prod", "111", regions=["us-east-1"])
    _add_resource(db_session, a, "arn:aws:ec2:us-east-1:111:instance/i-0123456789abcdef0")
    found = resolver.find_instance_account("i-0123456789abcdef0")
    assert found is not None and found[0].name == "prod"


def test_find_instance_probe_fallback(db_session, monkeypatch):
    from botocore.exceptions import ClientError
    _add_account(db_session, "prod", "111", regions=["us-east-1"])
    _add_account(db_session, "staging", "222", regions=["us-west-2"])

    def fake_resolve(snap, region):
        sess = MagicMock()
        ec2 = MagicMock()
        if snap.name == "prod":
            ec2.describe_instances.side_effect = ClientError(
                {"Error": {"Code": "InvalidInstanceID.NotFound", "Message": "no"}}, "DescribeInstances"
            )
        else:
            ec2.describe_instances.return_value = {"Reservations": [{"Instances": [{"InstanceId": "i-x"}]}]}
        sess.client.return_value = ec2
        return sess

    monkeypatch.setattr(resolver, "resolve_account_session", fake_resolve)
    found = resolver.find_instance_account("i-0aaaabbbbccccdddd0")
    assert found is not None
    assert found[0].name == "staging"


def test_find_instance_miss(db_session, monkeypatch):
    from botocore.exceptions import ClientError
    _add_account(db_session, "prod", "111", regions=["us-east-1"])

    def fake_resolve(snap, region):
        sess = MagicMock()
        ec2 = MagicMock()
        ec2.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceID.NotFound", "Message": "no"}}, "DescribeInstances"
        )
        sess.client.return_value = ec2
        return sess

    monkeypatch.setattr(resolver, "resolve_account_session", fake_resolve)
    assert resolver.find_instance_account("i-0000000000000dead") is None


# ── find_cluster_account ─────────────────────────────────────────────────


def test_find_cluster_inventory_hit(db_session):
    a = _add_account(db_session, "prod", "111", regions=["us-east-1"])
    _add_resource(db_session, a, "my-cluster", rtype="EKS", region="us-east-1")
    found = resolver.find_cluster_account("my-cluster")
    assert found is not None and found[0].name == "prod"


# ── get_instance_ips ─────────────────────────────────────────────────────


def test_get_instance_ips(db_session):
    a = _add_account(db_session, "prod", "111")
    _add_resource(db_session, a, "i-0123456789abcdef0", raw={"private_ip": "10.0.1.5", "public_ip": "54.1.2.3"})
    ips = resolver.get_instance_ips("i-0123456789abcdef0")
    assert ips == {"private_ip": "10.0.1.5", "public_ip": "54.1.2.3"}


def test_get_instance_ips_none_when_absent(db_session):
    a = _add_account(db_session, "prod", "111")
    _add_resource(db_session, a, "i-0123456789abcdef0", raw={})
    assert resolver.get_instance_ips("i-0123456789abcdef0") is None


# ── find_ssh_account_for_host ────────────────────────────────────────────


def test_find_ssh_account_by_host(db_session):
    _add_account(db_session, "bastion", "0", provider="ssh", regions=[],
                 creds={"host": "10.0.0.9", "username": "ubuntu"})
    snap = resolver.find_ssh_account_for_host("10.0.0.9")
    assert snap is not None and snap.name == "bastion"


def test_find_ssh_account_miss(db_session):
    assert resolver.find_ssh_account_for_host("10.0.0.9") is None
