"""PARK-S1 (MVP-2.6.1 Task 14): the business session cache is keyed by a credential fingerprint.

resolve_account_session re-reads the account snapshot on every call, so a re-pointed credential (role ARN, keys,
profile, source type) is a different cache key and a miss — no invalidation hook, in any process. kubeconfigs is
left out of the fingerprint: registering a kubeconfig does not change whose credentials a session carries.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.credentials import kube, resolver
from agenticops.credentials.resolver import AccountResolutionError
from agenticops.models import CloudAccount, init_db
from agenticops.providers.base import _session_cache
from agenticops.run_context import run_context

# credentials/kube._fingerprint at 82efa10 for _snap() — pins the hash material.
PINNED_FP = "9a79b772debd2cfb"


@pytest.fixture(autouse=True)
def _clean_cache():
    _session_cache.clear()
    yield
    _session_cache.clear()


def _snap(pk=1, name="prod", account_id="111111111111", role="Ops", source="assume_role",
          regions=("us-east-1",), kubeconfigs=None):
    creds = {"account_id": account_id, "role_arn": f"arn:aws:iam::{account_id}:role/{role}"}
    if not account_id:
        creds.pop("account_id")
    if kubeconfigs is not None:
        creds["kubeconfigs"] = kubeconfigs
    return SimpleNamespace(id=pk, name=name, provider="aws", credentials=creds, regions=list(regions), labels={},
                           credential_source_type=source)


class _FakeProvider:
    """Counts provider builds; every build hands out a fresh session sentinel."""

    def __init__(self):
        self.built = []

    def __call__(self, snap):
        self.built.append(snap)
        return SimpleNamespace(resolve_credentials=lambda: True, sdk_session=lambda: object())


@pytest.fixture
def provider(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr("agenticops.providers.get_provider", fake)
    return fake


def test_same_snapshot_twice_is_one_session(provider):
    first = resolver.resolve_account_session(_snap(), "us-east-1")
    assert resolver.resolve_account_session(_snap(), "us-east-1") is first
    assert len(provider.built) == 1


def test_repointed_credential_is_a_new_session(provider):
    old = resolver.resolve_account_session(_snap(role="Ops"), "us-east-1")
    new = resolver.resolve_account_session(_snap(role="OpsV2"), "us-east-1")  # same name + region, new role_arn
    assert new is not old
    assert len(provider.built) == 2
    # the original credential still maps to its own cached session
    assert resolver.resolve_account_session(_snap(role="Ops"), "us-east-1") is old
    assert len(provider.built) == 2


def test_source_type_change_alone_is_a_new_session(provider):
    old = resolver.resolve_account_session(_snap(source="assume_role"), "us-east-1")
    new = resolver.resolve_account_session(_snap(source="static_keys"), "us-east-1")
    assert new is not old
    assert len(provider.built) == 2


def test_kubeconfigs_change_alone_reuses_the_session(provider):
    first = resolver.resolve_account_session(_snap(), "us-east-1")
    again = resolver.resolve_account_session(_snap(kubeconfigs={"lab": "/abs/lab.kubeconfig"}), "us-east-1")
    assert again is first
    assert len(provider.built) == 1


def test_two_regions_are_two_entries(provider):
    east = resolver.resolve_account_session(_snap(regions=("us-east-1", "eu-west-1")), "us-east-1")
    west = resolver.resolve_account_session(_snap(regions=("us-east-1", "eu-west-1")), "eu-west-1")
    assert east is not west
    assert len(provider.built) == 2
    assert resolver.session_cache_keys(_snap(), "us-east-1") != resolver.session_cache_keys(_snap(), "eu-west-1")


def test_kube_fingerprint_is_the_resolver_fingerprint():
    plain = _snap()
    with_kc = _snap(kubeconfigs={"lab": "/abs/lab.kubeconfig"})
    assert kube._fingerprint(plain) == resolver.credential_fingerprint(plain) == PINNED_FP
    assert kube._fingerprint(with_kc) == resolver.credential_fingerprint(with_kc) == PINNED_FP


def test_key_format():
    snap = _snap()
    assert resolver.session_cache_keys(snap, "us-east-1") == (
        f"aws:prod:us-east-1:{PINNED_FP}", f"111111111111:us-east-1:{PINNED_FP}")
    # region None → the account's first region, as before
    assert resolver.session_cache_keys(snap, None) == resolver.session_cache_keys(snap, "us-east-1")


def test_no_account_id_means_no_id_key():
    name_key, id_key = resolver.session_cache_keys(_snap(account_id=""), "us-east-1")
    assert id_key == ""
    assert name_key.startswith("aws:prod:us-east-1:")


def test_binding_refusal_precedes_the_cache_lookup(provider):
    a, b = _snap(pk=1, name="acctA", account_id="111"), _snap(pk=2, name="acctB", account_id="222")
    for key in resolver.session_cache_keys(b, "us-east-1"):
        _session_cache[key] = object()  # B's session, cached under its fingerprinted keys
    with run_context(bound_account_id=a.id):
        with pytest.raises(AccountResolutionError):
            resolver.resolve_account_session(b, "us-east-1")
    assert provider.built == []


def test_assume_role_prewarms_the_key_readers_compute(provider, monkeypatch):
    """aws_tools.assume_role builds its own snapshot: it must carry credential_source_type, so the session it
    pre-warms sits under the key every later reader computes from the same account row."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    db = sessionmaker(bind=engine)()
    db.add(CloudAccount(name="prod", provider="aws", is_enabled=True, credential_source_type="assume_role",
                        credentials={"account_id": "111111111111", "role_arn": "arn:aws:iam::111111111111:role/Ops"},
                        regions=["us-east-1"]))
    db.commit()

    @contextmanager
    def fake_db():
        yield db

    monkeypatch.setattr("agenticops.models.get_db_session", fake_db)
    from agenticops.tools.aws_tools import assume_role

    try:
        result = assume_role(account_id="111111111111", role_arn="arn:aws:iam::111111111111:role/Ops",
                             region="us-east-1")
        assert "Credentials resolved" in result
        name_key, id_key = resolver.session_cache_keys(resolver.get_account_snapshot("prod"), "us-east-1")
        assert {name_key, id_key} <= set(_session_cache)
        # a later reader addressing the account by name gets the pre-warmed session, with no second build
        assert resolver.resolve_account_session("prod", "us-east-1") is _session_cache[name_key]
        assert len(provider.built) == 1
    finally:
        db.close()
        engine.dispose()
