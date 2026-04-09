"""Tests for agenticops.skills.execution — targeting uncovered lines."""

import subprocess
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── run_on_host ──────────────────────────────────────────────────────

class TestRunOnHost:
    """Cover run_on_host lines 65-91, 96-134, 139-165."""

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
    @patch("agenticops.skills.execution._execute_ssm", return_value="restarted")
    def test_write_with_confirmation(self, mock_exec, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(
            host_id="i-1", command="systemctl restart nginx", require_confirmation=True
        )
        assert result == "restarted"

    @patch("agenticops.skills.execution.classify_shell_command", return_value="unknown")
    def test_unknown_requires_confirmation(self, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-1", command="weird-tool")
        assert "requires confirmation" in result

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    @patch("agenticops.skills.execution._execute_ssm", return_value="output")
    def test_readonly_ssm(self, mock_exec, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-1", command="ps aux")
        assert result == "output"

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    @patch("agenticops.skills.execution._execute_ssh", return_value="ssh output")
    def test_readonly_ssh(self, mock_exec, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="10.0.1.1", command="uptime", method="ssh")
        assert result == "ssh output"

    @patch("agenticops.skills.execution.classify_shell_command", return_value="readonly")
    def test_unknown_method(self, mock_cls):
        from agenticops.skills.execution import run_on_host

        result = run_on_host(host_id="i-1", command="ps", method="ftp")
        assert "Unknown method" in result


# ── _execute_ssm ─────────────────────────────────────────────────────

class TestExecuteSSM:
    """Cover _execute_ssm lines 96-134."""

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

        result = _execute_ssm("i-123", "echo hello", "us-east-1")
        assert result == "hello world"

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

        result = _execute_ssm("i-123", "true", "us-east-1")
        assert result == "(no output)"

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

        result = _execute_ssm("i-123", "badcmd", "us-east-1")
        assert "Failed" in result
        assert "command not found" in result

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

        result = _execute_ssm("i-123", "big", "us-east-1")
        assert "truncated" in result
        assert len(result) < 5000 + 50

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_ssm_exception(self, mock_get_client):
        from agenticops.skills.execution import _execute_ssm

        client = MagicMock()
        client.send_command.side_effect = Exception("SSM unavailable")
        mock_get_client.return_value = client

        result = _execute_ssm("i-123", "ls", "us-east-1")
        assert "SSM error" in result


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
    @patch.dict("os.environ", {}, clear=False)
    def test_kubectl_update_kubeconfig_failure(self, mock_run):
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
