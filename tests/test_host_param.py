"""The host a command is sent to is a host — never an option of the ssh client (MVP-2.9.0 N30).

Found while planning N30 (a review of the code, not an incident): `run_on_host` handed a `host_id` that is no
instance id to ssh as it stood, with nothing in front. `host_id="-oProxyCommand=<anything>"` made the ssh client on
the machine AgenticOps runs on execute `<anything>` — and the call's own command (`uptime`) was a read, so nothing
asked and nothing was written to the ledger. Every agent that holds run_on_host could do it.
"""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agenticops.skills.execution import _execute_ssh, _host_refusal, run_on_host

NOT_HOSTS = [
    "-oProxyCommand=touch /tmp/x", "-oProxyCommand=id", "-F/tmp/cfg", "-J evil", "--", "-", "-i",
    " 10.0.1.5", "10.0.1.5 ", "web 1", "web\t1", "web\n1", "web;id", "$(id)", "`id`", "web|id", "a=b", "web/1",
    "user@-oProxyCommand=id", "-l root@10.0.1.5", "-x@10.0.1.5", "@10.0.1.5", "user@", "", "   ",
    "'web'", '"web"', "web&", "web>x", "x" * 300,
]
HOSTS = ["i-0123456789abcdef0", "i-12345678", "10.0.1.5", "web-1", "web-1.internal.example.com", "WEB01",
         "fe80::1", "2001:db8::10", "ec2-user@10.0.1.5", "ubuntu@web-1.internal", "svc_ops@host-1", "a"]


@pytest.mark.parametrize("host", NOT_HOSTS)
def test_what_is_not_a_host_is_refused(host):
    assert _host_refusal(host)


@pytest.mark.parametrize("host", HOSTS)
def test_a_host_is_let_through(host):
    assert _host_refusal(host) is None


@pytest.mark.parametrize("host", NOT_HOSTS)
def test_run_on_host_sends_nothing_anywhere_for_such_a_host(host):
    with patch("agenticops.skills.execution.subprocess.run") as run, \
            patch("agenticops.skills.execution._run_auto_ladder") as ladder, \
            patch("agenticops.skills.execution._run_ssh_for_host") as ssh, \
            patch("agenticops.skills.execution._execute_ssm") as ssm:
        for method in ("auto", "ssh", "ssm"):
            out = run_on_host(host_id=host, command="uptime", method=method)
            assert out.startswith("Error:") and "host_id" in out
    assert not (run.called or ladder.called or ssh.called or ssm.called)


def test_the_refusal_comes_before_anything_else_is_decided():
    # a confirmed write to such a «host» is refused for the host, not asked about
    with patch("agenticops.skills.execution._run_auto_ladder") as ladder:
        out = run_on_host(host_id="-oProxyCommand=id", command="systemctl restart nginx", require_confirmation=True)
    assert out.startswith("Error:") and "host_id" in out and not ladder.called


def test_a_real_host_still_goes_out():
    with patch("agenticops.skills.execution._run_auto_ladder", return_value="up 5 days") as ladder:
        assert run_on_host(host_id="10.0.1.5", command="uptime") == "up 5 days"
    assert ladder.called


@pytest.mark.parametrize("host", ["-oProxyCommand=id", "-F/tmp/cfg", "web 1", ""])
def test_the_ssh_call_itself_refuses_too(host):
    with patch("agenticops.skills.execution.subprocess.run") as run:
        out = _execute_ssh(host, "uptime")
    assert out.startswith("Error:") and not run.called


def test_the_user_is_checked_like_the_host():
    with patch("agenticops.skills.execution.subprocess.run") as run:
        out = _execute_ssh("10.0.1.5", "uptime", user="-oProxyCommand=id")
    assert out.startswith("Error:") and not run.called


def test_options_end_before_the_host_on_the_ssh_command_line():
    with patch("agenticops.skills.execution.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        _execute_ssh("10.0.1.5", "uptime", user="ops", key_path="/k", port=2222, bastion="jump.example.com")
    argv = run.call_args[0][0]
    assert argv[0] == "ssh" and argv[-3:] == ["--", "ops@10.0.1.5", "uptime"]
    assert run.call_args[1]["shell"] is False
    # the options are all before the «--»
    assert all(not a.startswith("-") for a in argv[argv.index("--") + 1:])


def test_a_timeout_and_a_missing_client_still_read_as_before():
    with patch("agenticops.skills.execution.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=30)):
        assert "timed out" in _execute_ssh("10.0.1.5", "sleep 999")
    with patch("agenticops.skills.execution.subprocess.run", side_effect=FileNotFoundError()):
        assert "SSH client not found" in _execute_ssh("10.0.1.5", "ls")
