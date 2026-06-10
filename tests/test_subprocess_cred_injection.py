"""Phase-2 Item1: subprocess exec paths inject the ACTIVE account's credentials.

run_aws_cli / run_aws_cli_readonly / kubectl / ssm previously ran with pure
ambient credentials (wrong account in a multi-account setup). They now build a
clean env from the active account's cached session (strip ambient AWS_* + inject
frozen creds), falling back to ambient ONLY when no account context is set
(single-account / local dev — unchanged behavior).
"""
from unittest import mock

import pytest

from agenticops.tools import aws_tools


def setup_function():
    aws_tools._session_cache.clear()
    aws_tools._set_active_account(None)


def teardown_function():
    aws_tools._session_cache.clear()
    aws_tools._set_active_account(None)


def _cache_session(account_id, region="us-east-1", key="K", secret="S", token="T"):
    frozen = mock.Mock(access_key=key, secret_key=secret, token=token)
    sess = mock.Mock()
    sess.get_credentials.return_value.get_frozen_credentials.return_value = frozen
    aws_tools._session_cache[f"{account_id}:{region}"] = sess
    return sess


def test_env_injects_active_account_and_strips_ambient(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENT")
    monkeypatch.setenv("AWS_PROFILE", "ambient-profile")
    _cache_session("111111111111", key="ACCT_KEY", secret="ACCT_SECRET", token="ACCT_TOKEN")
    aws_tools._set_active_account("111111111111")

    env = aws_tools.get_account_subprocess_env()
    assert env["AWS_ACCESS_KEY_ID"] == "ACCT_KEY"
    assert env["AWS_SECRET_ACCESS_KEY"] == "ACCT_SECRET"
    assert env["AWS_SESSION_TOKEN"] == "ACCT_TOKEN"
    assert "AWS_PROFILE" not in env  # ambient profile stripped


def test_env_falls_back_to_ambient_without_account_context(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENT")
    # no active account → unchanged ambient env (single-account/local dev)
    env = aws_tools.get_account_subprocess_env()
    assert env["AWS_ACCESS_KEY_ID"] == "AMBIENT"


def test_env_fail_closed_when_active_account_has_no_session():
    # active account set but nothing cached for it → fail closed, never ambient
    aws_tools._set_active_account("222222222222")
    with pytest.raises(RuntimeError):
        aws_tools.get_account_subprocess_env()


def test_run_aws_cli_passes_injected_env(monkeypatch):
    from agenticops.tools import aws_cli_tool
    _cache_session("111111111111", key="ACCT_KEY")
    aws_tools._set_active_account("111111111111")

    captured = {}
    def fake_run(args, **kw):
        captured["env"] = kw.get("env")
        return mock.Mock(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("agenticops.tools.aws_cli_tool.subprocess.run", fake_run)

    aws_cli_tool.run_aws_cli("aws ec2 describe-instances --region us-east-1")
    assert captured["env"] is not None
    assert captured["env"]["AWS_ACCESS_KEY_ID"] == "ACCT_KEY"


def test_ssm_client_uses_active_account_session():
    from agenticops.skills import execution
    sess = _cache_session("111111111111")
    aws_tools._set_active_account("111111111111")

    client = execution._get_ssm_client("us-east-1")
    sess.client.assert_called_once_with("ssm", region_name="us-east-1")
    assert client is sess.client.return_value


def test_ssm_client_fail_closed_when_account_has_no_session():
    from agenticops.skills import execution
    aws_tools._set_active_account("222222222222")  # nothing cached
    with pytest.raises(RuntimeError):
        execution._get_ssm_client("us-east-1")


def test_ssm_client_ambient_fallback_without_account(monkeypatch):
    from agenticops.skills import execution
    made = {}
    def fake_client(name, **kw):
        made["name"] = name
        made["kw"] = kw
        return object()
    monkeypatch.setattr("boto3.client", fake_client)
    execution._get_ssm_client("eu-west-1")  # no active account → ambient boto3.client
    assert made["name"] == "ssm"
    assert made["kw"]["region_name"] == "eu-west-1"
