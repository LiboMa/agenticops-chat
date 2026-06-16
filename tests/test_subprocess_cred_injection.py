"""Subprocess exec paths inject a REGISTERED account's credentials — never ambient.

run_aws_cli / run_aws_cli_readonly / kubectl / ssm build a clean env from a
registered account's session (strip ambient AWS_* + inject frozen creds). There
is NO ambient fallback: a missing/ambiguous/unresolvable account is fail-closed.
Account is resolved explicitly (param → inventory → single-account default), not
via an implicit ContextVar (which never survived a Strands tool boundary).
"""
from types import SimpleNamespace
from unittest import mock

import pytest

from agenticops.credentials import resolver


def _fake_session(key="K", secret="S", token="T"):
    frozen = mock.Mock(access_key=key, secret_key=secret, token=token)
    sess = mock.Mock()
    sess.get_credentials.return_value.get_frozen_credentials.return_value = frozen
    return sess


def _snap(name="prod", account_id="111111111111", regions=("us-east-1",)):
    return SimpleNamespace(
        id=1, name=name, provider="aws",
        credentials={"account_id": account_id}, regions=list(regions), labels={},
        credential_source_type="assume_role",
    )


# ── get_subprocess_env_for_account: strip ambient + inject registered creds ──


def test_env_injects_account_and_strips_ambient(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENT")
    monkeypatch.setenv("AWS_PROFILE", "ambient-profile")
    sess = _fake_session(key="ACCT_KEY", secret="ACCT_SECRET", token="ACCT_TOKEN")
    monkeypatch.setattr(resolver, "resolve_account_session", lambda ref, region=None: sess)

    env = resolver.get_subprocess_env_for_account(_snap(), "us-east-1")
    assert env["AWS_ACCESS_KEY_ID"] == "ACCT_KEY"
    assert env["AWS_SECRET_ACCESS_KEY"] == "ACCT_SECRET"
    assert env["AWS_SESSION_TOKEN"] == "ACCT_TOKEN"
    assert env["AWS_DEFAULT_REGION"] == "us-east-1"
    assert "AWS_PROFILE" not in env  # ambient profile stripped


def test_env_fail_closed_when_account_unresolvable(monkeypatch):
    def boom(ref, region=None):
        raise resolver.AccountResolutionError("nope")
    monkeypatch.setattr(resolver, "resolve_account_session", boom)
    with pytest.raises(resolver.AccountResolutionError):
        resolver.get_subprocess_env_for_account("missing", "us-east-1")


# ── run_aws_cli: account-addressed, no ambient ──────────────────────────────


def test_run_aws_cli_passes_injected_env(monkeypatch):
    from agenticops.tools import aws_cli_tool

    monkeypatch.setattr(
        "agenticops.credentials.resolver.resolve_default_account", lambda provider="aws": _snap()
    )
    monkeypatch.setattr(
        "agenticops.credentials.resolver.get_subprocess_env_for_account",
        lambda target, region=None: {"AWS_ACCESS_KEY_ID": "ACCT_KEY"},
    )

    captured = {}
    def fake_run(args, **kw):
        captured["env"] = kw.get("env")
        return mock.Mock(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("agenticops.tools.aws_cli_tool.subprocess.run", fake_run)

    aws_cli_tool.run_aws_cli("aws ec2 describe-instances --region us-east-1")
    assert captured["env"]["AWS_ACCESS_KEY_ID"] == "ACCT_KEY"


def test_run_aws_cli_fail_closed_on_ambiguous_accounts(monkeypatch):
    from agenticops.tools import aws_cli_tool

    def ambiguous(provider="aws"):
        raise resolver.AccountResolutionError("Multiple enabled aws accounts: a, b")
    monkeypatch.setattr("agenticops.credentials.resolver.resolve_default_account", ambiguous)

    out = aws_cli_tool.run_aws_cli("aws ec2 describe-instances --region us-east-1")
    assert "Multiple enabled aws accounts" in out


# ── SSM client: registered account, fail-closed (no ambient) ────────────────


def test_ssm_client_uses_account_session(monkeypatch):
    from agenticops.skills import execution
    sess = _fake_session()
    monkeypatch.setattr(
        "agenticops.credentials.resolver.resolve_account_session",
        lambda ref, region=None: sess,
    )
    client = execution._get_ssm_client("us-east-1", _snap())
    sess.client.assert_called_once_with("ssm", region_name="us-east-1")
    assert client is sess.client.return_value


def test_ssm_client_fail_closed_when_unresolvable(monkeypatch):
    from agenticops.skills import execution

    def boom(ref, region=None):
        raise resolver.AccountResolutionError("no session")
    monkeypatch.setattr("agenticops.credentials.resolver.resolve_account_session", boom)
    with pytest.raises(resolver.AccountResolutionError):
        execution._get_ssm_client("eu-west-1", "missing")
