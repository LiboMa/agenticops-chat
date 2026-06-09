"""Bug#1 regression: _get_session must not return another account's session by region."""
import pytest
from agenticops.tools import aws_tools


def setup_function():
    aws_tools._session_cache.clear()
    aws_tools._set_active_account(None)


def test_get_session_does_not_cross_account_by_region():
    # 两个账户,同一 region,各自的 session 对象
    sess_a = object()
    sess_b = object()
    aws_tools._session_cache["111111111111:us-east-1"] = sess_a
    aws_tools._session_cache["222222222222:us-east-1"] = sess_b

    # 当前账户上下文 = B,必须拿到 B,绝不能拿到 A
    aws_tools._set_active_account("222222222222")
    assert aws_tools._get_session("us-east-1") is sess_b


def test_get_session_fail_closed_without_account_context():
    # 缓存里有别的账户的 session,但没有当前账户上下文 → 必须报错,不能返回任意 session
    aws_tools._session_cache["111111111111:us-east-1"] = object()
    aws_tools._set_active_account(None)
    with pytest.raises(RuntimeError):
        aws_tools._get_session("us-east-1")


def test_get_session_account_not_in_cache_raises():
    aws_tools._session_cache["111111111111:us-east-1"] = object()
    aws_tools._set_active_account("222222222222")  # B 没 assume 过
    with pytest.raises(RuntimeError):
        aws_tools._get_session("us-east-1")


def test_web_key_not_returned_to_agent_path():
    # web:region 的 session 绝不能被 agent 的账户上下文命中
    aws_tools._session_cache["web:us-east-1"] = object()
    aws_tools._set_active_account("222222222222")
    with pytest.raises(RuntimeError):
        aws_tools._get_session("us-east-1")
