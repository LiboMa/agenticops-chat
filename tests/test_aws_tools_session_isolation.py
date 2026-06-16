"""Regression: _get_session resolves the EXACT registered account, never crosses accounts."""
from types import SimpleNamespace

import pytest

from agenticops.tools import aws_tools
from agenticops.credentials import resolver
from agenticops.providers.base import _session_cache


def setup_function():
    _session_cache.clear()


def teardown_function():
    _session_cache.clear()


def _snap(name, account_id, regions=("us-east-1",)):
    return SimpleNamespace(
        id=1, name=name, provider="aws",
        credentials={"account_id": account_id}, regions=list(regions), labels={},
        credential_source_type="assume_role",
    )


def test_get_session_resolves_explicit_account(monkeypatch):
    sess_a = object()
    sess_b = object()
    # Seed cache the way resolve_account_session writes it (account_id:region).
    _session_cache["111111111111:us-east-1"] = sess_a
    _session_cache["222222222222:us-east-1"] = sess_b
    monkeypatch.setattr(
        resolver, "get_account_snapshot",
        lambda ref, provider="": _snap("acct-b", "222222222222"),
    )

    # cache lookup uses provider:name:region then account_id:region
    assert aws_tools._get_session("us-east-1", account="acct-b") is sess_b


def test_get_session_fail_closed_without_account(monkeypatch):
    # No explicit account and zero enabled accounts → fail-closed (no ambient).
    monkeypatch.setattr(
        resolver, "list_enabled_accounts", lambda provider="": []
    )
    with pytest.raises(resolver.AccountResolutionError):
        aws_tools._get_session("us-east-1")


def test_get_session_unknown_account_raises(monkeypatch):
    monkeypatch.setattr(resolver, "get_account_snapshot", lambda ref, provider="": None)
    monkeypatch.setattr(resolver, "list_enabled_accounts", lambda provider="": [])
    with pytest.raises(resolver.AccountResolutionError):
        aws_tools._get_session("us-east-1", account="ghost")


def test_get_session_single_account_default(monkeypatch):
    sess = object()
    _session_cache["111111111111:us-east-1"] = sess
    snap = _snap("only", "111111111111")
    monkeypatch.setattr(resolver, "list_enabled_accounts", lambda provider="aws": [snap])
    # default account resolves to the single enabled account; cache hit returns it
    assert aws_tools._get_session("us-east-1") is sess
