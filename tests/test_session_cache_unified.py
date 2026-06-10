"""Phase-2 Item4: aws_tools and providers/base must share ONE session-cache dict.

Previously there were two separate module-level dicts holding AWS sessions
(aws_tools._session_cache + providers/base._session_cache, the latter write-only).
They are now the same object, so the provider layer is the single home and
clear_session_cache() / set_cached_session() are authoritative everywhere.
"""
from agenticops.tools import aws_tools
from agenticops.providers import base as provider_base


def test_caches_are_the_same_object():
    assert aws_tools._session_cache is provider_base._session_cache


def test_provider_write_visible_to_agent_cache():
    provider_base.clear_session_cache()
    sentinel = object()
    provider_base.set_cached_session("111111111111:us-east-1", sentinel)
    # agent path sees the provider-written session for that exact account+region
    aws_tools._set_active_account("111111111111")
    try:
        assert aws_tools._get_session("us-east-1") is sentinel
    finally:
        aws_tools._set_active_account(None)
        provider_base.clear_session_cache()
