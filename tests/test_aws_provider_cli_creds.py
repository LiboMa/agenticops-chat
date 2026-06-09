"""Bug#2 regression: cli_tool must strip ambient AWS_* and fail-closed on cred extraction error."""
import types
from unittest import mock

from agenticops.providers.aws import AWSProvider


def _make_provider(session):
    acct = types.SimpleNamespace(id=1, name="acct-b", provider="aws",
                                 credentials={}, regions=["us-east-1"], labels={})
    p = AWSProvider(acct)
    p._session = session
    return p


def test_cli_env_strips_ambient_and_injects_account(monkeypatch):
    # 宿主有残留 ambient 凭证(账户 A)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENT_A")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "AMBIENT_A_SECRET")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "AMBIENT_A_TOKEN")
    monkeypatch.setenv("AWS_PROFILE", "ambient-a")

    frozen = types.SimpleNamespace(access_key="ACCT_B_KEY", secret_key="ACCT_B_SECRET", token="ACCT_B_TOKEN")
    sess = mock.Mock()
    sess.get_credentials.return_value.get_frozen_credentials.return_value = frozen

    captured = {}
    def fake_run(args, **kw):
        captured["env"] = kw.get("env", {})
        return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("agenticops.providers.aws.subprocess.run", fake_run)

    tool = _make_provider(sess).cli_tool()
    tool("aws sts get-caller-identity")
    env = captured["env"]
    assert env["AWS_ACCESS_KEY_ID"] == "ACCT_B_KEY"       # 本账户
    assert env["AWS_SECRET_ACCESS_KEY"] == "ACCT_B_SECRET"
    assert env["AWS_SESSION_TOKEN"] == "ACCT_B_TOKEN"
    assert "AWS_PROFILE" not in env                        # ambient profile 被剥离
    # 没有任何 AMBIENT_A 残留
    assert "AMBIENT_A" not in env.get("AWS_ACCESS_KEY_ID", "")


def test_cli_fail_closed_when_cred_extraction_errors(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENT_A")  # 宿主有 ambient
    sess = mock.Mock()
    sess.get_credentials.return_value.get_frozen_credentials.side_effect = RuntimeError("boom")

    ran = {"called": False}
    def fake_run(args, **kw):
        ran["called"] = True
        return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("agenticops.providers.aws.subprocess.run", fake_run)

    tool = _make_provider(sess).cli_tool()
    out = tool("aws sts get-caller-identity")
    assert "Error" in out                  # 显式报错
    assert ran["called"] is False          # 绝不带着 ambient 凭证执行


def test_cli_fail_closed_when_no_session(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENT_A")

    ran = {"called": False}
    def fake_run(args, **kw):
        ran["called"] = True
        return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("agenticops.providers.aws.subprocess.run", fake_run)

    tool = _make_provider(None).cli_tool()  # 没有 resolved session
    out = tool("aws sts get-caller-identity")
    assert "Error" in out
    assert ran["called"] is False
