"""Tests for agenticops.skills.execution — targeting uncovered lines."""

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── run_on_host ──────────────────────────────────────────────────────

_SNAP = SimpleNamespace(
    id=1, name="acct", provider="aws",
    credentials={"account_id": "111111111111"}, regions=["us-east-1"], labels={},
    credential_source_type="assume_role",
)


class TestRunOnHost:
    """run_on_host gating + method routing (auto / ssm / ssh)."""

    def test_empty_command(self):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-1", command="  ")
        assert "Empty command" in result

    @patch("agenticops.skills.execution.classify_shell_command", return_value="blocked")
    def test_blocked_command(self, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-1", command="rm -rf /")
        assert "blocked" in result.lower()

    @patch("agenticops.skills.execution.classify_shell_command", return_value="write")
    def test_write_requires_confirmation(self, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-1", command="systemctl restart nginx")
        assert "requires confirmation" in result

    @patch("agenticops.skills.execution.classify_shell_command", return_value="write")
    @patch("agenticops.skills.execution._resolve_host_account", return_value=(_SNAP, "us-east-1", "explicit"))
    @patch("agenticops.skills.execution._execute_ssm", return_value=(True, "restarted", ""))
    def test_write_with_confirmation_ssm(self, mock_exec, mock_resolve, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(
            host_id="i-0123456789abcdef0", command="systemctl restart nginx",
            method="ssm", require_confirmation=True,
        )
        assert result == "restarted"

    @patch("agenticops.skills.execution.classify_shell_command", return_value="unknown")
    def test_unknown_requires_confirmation(self, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-1", command="weird-tool")
        assert "requires confirmation" in result

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    @patch("agenticops.skills.execution._resolve_host_account", return_value=(_SNAP, "us-east-1", "explicit"))
    @patch("agenticops.skills.execution._execute_ssm", return_value=(True, "output", ""))
    def test_explicit_ssm(self, mock_exec, mock_resolve, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-0123456789abcdef0", command="ps aux", method="ssm")
        assert result == "output"

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    @patch("agenticops.skills.execution._run_ssh_for_host", return_value="ssh output")
    def test_explicit_ssh(self, mock_ssh, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="10.0.1.1", command="uptime", method="ssh")
        assert result == "ssh output"

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    def test_unknown_method(self, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-1", command="ps", method="kerberos")
        assert "Unknown method" in result

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    @patch("agenticops.skills.execution._run_ssh_for_host", return_value="ssh-only output")
    def test_auto_non_instance_goes_ssh(self, mock_ssh, mock_cls):
        from agenticops.skills.execution import run_on_host

        # A hostname (not an i-... id) → auto ladder uses SSH directly.
        result = run_on_host(host_id="db.internal", command="uptime", method="auto")
        assert result == "ssh-only output"

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    @patch("agenticops.skills.execution._resolve_host_account", return_value=(_SNAP, "us-east-1", "inventory match"))
    @patch("agenticops.skills.execution._execute_ssm", return_value=(False, "SSM TargetNotConnected: ...", "TargetNotConnected"))
    @patch("agenticops.credentials.resolver.get_instance_ips", return_value={"private_ip": "10.0.1.5", "public_ip": None})
    @patch("agenticops.skills.execution._run_ssh_for_host", return_value="uptime: 5 days")
    def test_auto_ssm_fails_falls_back_to_ssh(self, mock_ssh, mock_ips, mock_exec, mock_resolve, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-0123456789abcdef0", command="uptime", method="auto")
        assert "SSM failed" in result
        assert "10.0.1.5" in result
        assert "uptime: 5 days" in result
        mock_ssh.assert_called_once_with("10.0.1.5", "uptime")

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    @patch("agenticops.skills.execution._resolve_host_account", return_value=(_SNAP, "us-east-1", "inventory match"))
    @patch("agenticops.skills.execution._execute_ssm", return_value=(False, "SSM TargetNotConnected: ...", "TargetNotConnected"))
    @patch("agenticops.credentials.resolver.get_instance_ips", return_value=None)
    def test_auto_ssm_fails_no_ip_for_ssh(self, mock_ips, mock_exec, mock_resolve, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-0123456789abcdef0", command="uptime", method="auto")
        assert "SSM failed" in result
        assert "SSH fallback unavailable" in result


# ── _execute_ssm ─────────────────────────────────────────────────────

class TestExecuteSSM:
    """_execute_ssm returns (ok, text, failure_class) with error classification."""

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_ssm_success(self, mock_get_client):
        from agenticops.skills.execution import _execute_ssm

        client = MagicMock()
        client.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
        client.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "hello world",
        }
        mock_get_client.return_value = client

        ok, text, cls = _execute_ssm("i-123", "echo hello", "us-east-1", _SNAP)
        assert ok is True
        assert text == "hello world"

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_ssm_success_no_output(self, mock_get_client):
        from agenticops.skills.execution import _execute_ssm

        client = MagicMock()
        client.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
        client.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "",
        }
        mock_get_client.return_value = client

        ok, text, cls = _execute_ssm("i-123", "true", "us-east-1", _SNAP)
        assert text == "(no output)"

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_ssm_failed_with_stderr(self, mock_get_client):
        from agenticops.skills.execution import _execute_ssm

        client = MagicMock()
        client.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
        client.get_command_invocation.return_value = {
            "Status": "Failed",
            "StandardErrorContent": "command not found",
        }
        mock_get_client.return_value = client

        ok, text, cls = _execute_ssm("i-123", "badcmd", "us-east-1", _SNAP)
        assert ok is False
        assert "Failed" in text
        assert "command not found" in text

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_ssm_invalid_instance_id_classified(self, mock_get_client):
        from agenticops.skills.execution import _execute_ssm
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.send_command.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceId", "Message": "bad"}}, "SendCommand"
        )
        mock_get_client.return_value = client

        ok, text, cls = _execute_ssm("i-123", "ls", "us-east-1", _SNAP)
        assert ok is False
        assert cls == "InvalidInstanceId"
        assert "InvalidInstanceId" in text

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_ssm_access_denied_classified(self, mock_get_client):
        from agenticops.skills.execution import _execute_ssm
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.send_command.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "SendCommand"
        )
        mock_get_client.return_value = client

        ok, text, cls = _execute_ssm("i-123", "ls", "us-east-1", _SNAP)
        assert cls == "AccessDenied"
        assert "ssm:SendCommand" in text

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_ssm_truncates_long_output(self, mock_get_client):
        from agenticops.skills.execution import _execute_ssm

        client = MagicMock()
        client.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
        client.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "x" * 5000,
        }
        mock_get_client.return_value = client

        ok, text, cls = _execute_ssm("i-123", "big", "us-east-1", _SNAP)
        assert "truncated" in text
        assert len(text) < 5000 + 50

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_ssm_exception(self, mock_get_client):
        from agenticops.skills.execution import _execute_ssm

        client = MagicMock()
        client.send_command.side_effect = Exception("SSM unavailable")
        mock_get_client.return_value = client

        ok, text, cls = _execute_ssm("i-123", "ls", "us-east-1", _SNAP)
        assert ok is False
        assert "SSM error" in text


# ── _execute_ssh ─────────────────────────────────────────────────────

class TestExecuteSSH:
    """Cover _execute_ssh lines 139-165."""

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ssh_success(self, mock_run):
        from agenticops.skills.execution import _execute_ssh

        mock_run.return_value = MagicMock(returncode=0, stdout="uptime: 5 days", stderr="")
        result = _execute_ssh("10.0.1.1", "uptime")
        assert "5 days" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ssh_success_empty_output(self, mock_run):
        from agenticops.skills.execution import _execute_ssh

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = _execute_ssh("10.0.1.1", "true")
        assert result == "(no output)"

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ssh_error(self, mock_run):
        from agenticops.skills.execution import _execute_ssh

        mock_run.return_value = MagicMock(returncode=1, stderr="Permission denied")
        result = _execute_ssh("10.0.1.1", "ls /root")
        assert "SSH error" in result
        assert "Permission denied" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ssh_timeout(self, mock_run):
        from agenticops.skills.execution import _execute_ssh

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=30)
        result = _execute_ssh("10.0.1.1", "sleep 999")
        assert "timed out" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ssh_not_found(self, mock_run):
        from agenticops.skills.execution import _execute_ssh

        mock_run.side_effect = FileNotFoundError()
        result = _execute_ssh("10.0.1.1", "ls")
        assert "SSH client not found" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ssh_generic_exception(self, mock_run):
        from agenticops.skills.execution import _execute_ssh

        mock_run.side_effect = OSError("network unreachable")
        result = _execute_ssh("10.0.1.1", "ls")
        assert "SSH error" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ssh_truncates_stderr(self, mock_run):
        from agenticops.skills.execution import _execute_ssh

        mock_run.return_value = MagicMock(returncode=1, stderr="E" * 5000)
        result = _execute_ssh("10.0.1.1", "fail")
        assert "truncated" in result


# ── run_kubectl ──────────────────────────────────────────────────────

class TestRunKubectl:
    """Cover run_kubectl lines 196-217, 222-269."""

    def test_empty_kubectl_command(self):
        from agenticops.skills.execution import run_kubectl

        result = run_kubectl(command="  ")
        assert "Empty kubectl command" in result

    @patch("agenticops.skills.execution.classify_kubectl_command", return_value="blocked")
    def test_blocked_kubectl(self, mock_cls):
        from agenticops.skills.execution import run_kubectl

        result = run_kubectl(command="delete namespace kube-system")
        assert "blocked" in result.lower()

    @patch("agenticops.skills.execution.classify_kubectl_command", return_value="write")
    def test_write_kubectl_requires_confirmation(self, mock_cls):
        from agenticops.skills.execution import run_kubectl

        result = run_kubectl(command="delete pod my-pod")
        assert "requires confirmation" in result

    @patch("agenticops.skills.execution.classify_kubectl_command", return_value="readonly")
    @patch("agenticops.skills.execution._execute_kubectl", return_value="NAME  READY  STATUS")
    def test_readonly_kubectl(self, mock_exec, mock_cls):
        from agenticops.skills.execution import run_kubectl

        result = run_kubectl(cluster_name="my-cluster", command="get pods", region="us-east-1")
        assert "NAME" in result


# ── _execute_kubectl ─────────────────────────────────────────────────

class TestExecuteKubectl:
    """Cover _execute_kubectl lines 222-269."""

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/kubeconfig"}, clear=False)
    def test_kubectl_with_kubeconfig_env(self, mock_run):
        from agenticops.skills.execution import _execute_kubectl

        # Make the file "exist"
        with patch("os.path.isfile", return_value=True):
            mock_run.return_value = MagicMock(returncode=0, stdout="pod/app Running")
            result = _execute_kubectl("", "get pods", "", "default")
            assert "pod/app" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {}, clear=False)
    def test_kubectl_no_cluster_no_kubeconfig(self, mock_run):
        from agenticops.skills.execution import _execute_kubectl

        # Remove KUBECONFIG if present
        import os
        os.environ.pop("KUBECONFIG", None)
        result = _execute_kubectl("", "get pods", "", "default")
        assert "No cluster_name" in result or "Error" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch("agenticops.credentials.resolver.get_subprocess_env_for_account", return_value={})
    @patch("agenticops.credentials.resolver.find_cluster_account", return_value=(_SNAP, "us-east-1"))
    @patch.dict("os.environ", {}, clear=False)
    def test_kubectl_update_kubeconfig_failure(self, mock_find, mock_env, mock_run):
        from agenticops.skills.execution import _execute_kubectl

        import os
        os.environ.pop("KUBECONFIG", None)
        mock_run.return_value = MagicMock(
            returncode=1, stderr="cluster not found"
        )
        result = _execute_kubectl("bad-cluster", "get pods", "us-east-1", "default")
        assert "Failed to update kubeconfig" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/kubeconfig"}, clear=False)
    def test_kubectl_error_exit_code(self, mock_run):
        from agenticops.skills.execution import _execute_kubectl

        with patch("os.path.isfile", return_value=True):
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            result = _execute_kubectl("", "get pods -n nope", "", "nope")
            assert "kubectl error" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/kubeconfig"}, clear=False)
    def test_kubectl_timeout(self, mock_run):
        from agenticops.skills.execution import _execute_kubectl

        with patch("os.path.isfile", return_value=True):
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="kubectl", timeout=30)
            result = _execute_kubectl("", "get pods", "", "default")
            assert "timed out" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/kubeconfig"}, clear=False)
    def test_kubectl_not_found(self, mock_run):
        from agenticops.skills.execution import _execute_kubectl

        with patch("os.path.isfile", return_value=True):
            mock_run.side_effect = FileNotFoundError()
            result = _execute_kubectl("", "get pods", "", "default")
            assert "kubectl not found" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/kubeconfig"}, clear=False)
    def test_kubectl_generic_exception(self, mock_run):
        from agenticops.skills.execution import _execute_kubectl

        with patch("os.path.isfile", return_value=True):
            mock_run.side_effect = RuntimeError("oops")
            result = _execute_kubectl("", "version", "", "default")
            assert "kubectl error" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/kubeconfig"}, clear=False)
    def test_kubectl_empty_output(self, mock_run):
        from agenticops.skills.execution import _execute_kubectl

        with patch("os.path.isfile", return_value=True):
            mock_run.return_value = MagicMock(returncode=0, stdout="  ", stderr="")
            result = _execute_kubectl("", "get pods", "", "default")
            assert result == "(no output)"
