"""Phase-2 Item4: aws_tools and providers/base must share ONE session-cache dict.

Previously there were two separate module-level dicts holding AWS sessions
(aws_tools._session_cache + providers/base._session_cache, the latter write-only).
They are now the same object, so the provider layer is the single home and
clear_session_cache() / set_cached_session() are authoritative everywhere.
"""
from types import SimpleNamespace

from agenticops.tools import aws_tools
from agenticops.providers import base as provider_base
from agenticops.credentials import resolver


def test_caches_are_the_same_object():
    assert aws_tools._session_cache is provider_base._session_cache


def test_provider_write_visible_to_agent_cache(monkeypatch):
    provider_base.clear_session_cache()
    sentinel = object()
    provider_base.set_cached_session("111111111111:us-east-1", sentinel)
    snap = SimpleNamespace(
        id=1, name="acct", provider="aws",
        credentials={"account_id": "111111111111"}, regions=["us-east-1"], labels={},
        credential_source_type="assume_role",
    )
    monkeypatch.setattr(resolver, "get_account_snapshot", lambda ref, provider="": snap)
    try:
        # explicit account → resolve_account_session finds the provider-written session
        assert aws_tools._get_session("us-east-1", account="111111111111") is sentinel
    finally:
        provider_base.clear_session_cache()
