"""G13 — a change run/review is bound to its account at the credential choke point (MVP-2.6.0).

resolve_account_session is the single funnel every account-addressed reader/executor passes through.
Under run_context(bound_account_id=X) it must resolve ONLY account X and fail closed on any other —
BEFORE the session cache, so a cached other-account session cannot slip through. find_instance_account's
probe loop already swallows AccountResolutionError, so a bound probe simply skips the accounts it may
not touch (it never raises).
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.credentials import resolver
from agenticops.credentials.resolver import AccountResolutionError
from agenticops.models import CloudAccount, init_db
from agenticops.providers.base import _session_cache
from agenticops.run_context import run_context


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _patch_db(db_session, monkeypatch):
    @contextmanager
    def fake_db():
        yield db_session

    monkeypatch.setattr("agenticops.models.get_db_session", fake_db)
    _session_cache.clear()
    yield
    _session_cache.clear()


def _add_account(db, name, account_id, regions=("us-east-1",)):
    c = {"account_id": account_id, "role_arn": f"arn:aws:iam::{account_id}:role/Ops"}
    a = CloudAccount(name=name, provider="aws", is_enabled=True, credentials=c, regions=list(regions))
    db.add(a)
    db.commit()
    return a


def _fake_session():
    frozen = MagicMock(access_key="K", secret_key="S", token="T")
    sess = MagicMock()
    sess.get_credentials.return_value.get_frozen_credentials.return_value = frozen
    return sess


@pytest.fixture
def two_accounts(db_session, monkeypatch):
    """Accounts A and B both enabled; the provider always resolves to a fresh stub session (no network)."""
    a = _add_account(db_session, "acctA", "111")
    b = _add_account(db_session, "acctB", "222")
    prov = MagicMock()
    prov.resolve_credentials.return_value = True
    prov.sdk_session.side_effect = lambda: _fake_session()
    monkeypatch.setattr("agenticops.providers.get_provider", lambda snap: prov)
    return a, b, prov


# ── (a) bound to A, resolving B raises even when B is cached ──────────────


def test_bound_to_a_refuses_b_even_when_cached(two_accounts):
    a, b, _ = two_accounts
    _session_cache["aws:acctB:us-east-1"] = _fake_session()  # a cached OTHER-account session
    _session_cache["222:us-east-1"] = _session_cache["aws:acctB:us-east-1"]
    with run_context(bound_account_id=a.id):
        with pytest.raises(AccountResolutionError) as e:
            resolver.resolve_account_session("acctB", "us-east-1")
        msg = str(e.value)
        assert f"id={a.id}" in msg and "acctB" in msg and f"id={b.id}" in msg
        # the bound account itself still resolves
        assert resolver.resolve_account_session("acctA", "us-east-1") is not None


# ── (b) unbound is unchanged: both resolve ────────────────────────────────


def test_unbound_resolves_both(two_accounts):
    assert resolver.resolve_account_session("acctA", "us-east-1") is not None
    assert resolver.resolve_account_session("acctB", "us-east-1") is not None


# ── (c) get_subprocess_env_for_account funnels through the choke point ─────


def test_subprocess_env_for_other_account_refused_when_bound(two_accounts):
    a, _, _ = two_accounts
    with run_context(bound_account_id=a.id):
        with pytest.raises(AccountResolutionError):
            resolver.get_subprocess_env_for_account("acctB", "us-east-1")
        env = resolver.get_subprocess_env_for_account("acctA", "us-east-1")
        assert env["AWS_ACCESS_KEY_ID"] == "K"


# ── (d) a describe_* tool and the SSM client both funnel through it ────────


def test_describe_and_ssm_for_other_account_refused_when_bound(two_accounts):
    from agenticops.skills.execution import _get_ssm_client
    from agenticops.tools.aws_tools import describe_ec2

    a, _, _ = two_accounts
    with run_context(bound_account_id=a.id):
        out = describe_ec2(region="us-east-1", account="acctB")  # describe wraps the error as a string
        assert "bound to account" in out
        with pytest.raises(AccountResolutionError):
            _get_ssm_client("us-east-1", "acctB")  # raises before .client("ssm") is ever built


# ── (e) an instance probe under a binding skips the accounts it may not touch ─


def test_instance_probe_under_binding_skips_unbound(db_session, monkeypatch):
    """find_instance_account probes each enabled account through the REAL resolver; its loop does
    `except AccountResolutionError: break`, so under bound(A) it probes A (miss) then hits B's binding
    refusal and stops — never building B's session, never raising. The instance sits only on B, so a
    bound run returns 'not found'. On BASE (no binding) the probe reaches B and returns it — the RED."""
    from botocore.exceptions import ClientError

    a = _add_account(db_session, "acctA", "111")
    _add_account(db_session, "acctB", "222")

    def make_session(hit):
        sess = MagicMock()
        ec2 = MagicMock()
        if hit:
            ec2.describe_instances.return_value = {"Reservations": [{"Instances": [{"InstanceId": "i-x"}]}]}
        else:
            ec2.describe_instances.side_effect = ClientError(
                {"Error": {"Code": "InvalidInstanceID.NotFound", "Message": "no"}}, "DescribeInstances")
        sess.client.return_value = ec2
        return sess

    sessions = [make_session(hit=False), make_session(hit=True)]  # A misses; B WOULD hit if reached
    prov = MagicMock()
    prov.resolve_credentials.return_value = True
    prov.sdk_session.side_effect = lambda: sessions.pop(0)
    monkeypatch.setattr("agenticops.providers.get_provider", lambda snap: prov)

    with run_context(bound_account_id=a.id):
        found = resolver.find_instance_account("i-0aaaabbbbccccdddd0")
    assert found is None          # bound to A: the instance is only on B → not found, and it never raised
    assert len(sessions) == 1     # only A's session was ever built; B was skipped at the break, never probed
