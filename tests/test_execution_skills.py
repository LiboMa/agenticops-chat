"""Unit tests for agenticops.skills.execution module.

Covers: run_on_host, run_kubectl, _execute_ssm, _execute_ssh, _execute_kubectl.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from agenticops.skills.execution import (
    run_on_host,
    run_kubectl,
    _execute_ssm,
    _execute_ssh,
    _execute_kubectl,
    MAX_OUTPUT_CHARS,
    SSM_TIMEOUT,
    SSH_TIMEOUT,
    KUBECTL_TIMEOUT,
)


# ── run_on_host tests ────────────────────────────────────────────────


class TestRunOnHost:
    def _call(self, **kwargs):
        return run_on_host._tool_func(**kwargs)

    def test_empty_command(self):
        result = self._call(host_id="i-123", command="")
        assert "Empty command" in result

    @patch("agenticops.skills.execution.classify_shell_command")
    def test_blocked_command(self, mock_classify):
        mock_classify.return_value = "blocked"
        result = self._call(host_id="i-123", command="rm -rf /")
        assert "blocked" in result.lower()

    @patch("agenticops.skills.execution.classify_shell_command")
    def test_write_command_needs_confirmation(self, mock_classify):
        mock_classify.return_value = "write"
        result = self._call(host_id="i-123", command="systemctl restart nginx")
        assert "requires confirmation" in result
        assert "require_confirmation=True" in result

    @patch("agenticops.skills.execution.classify_shell_command")
    def test_unknown_command_needs_confirmation(self, mock_classify):
        mock_classify.return_value = "unknown"
        result = self._call(host_id="i-123", command="some-custom-tool")
        assert "requires confirmation" in result

    @patch("agenticops.skills.execution._execute_ssm")
    @patch("agenticops.skills.execution.classify_shell_command")
    def test_readonly_command_ssm(self, mock_classify, mock_ssm):
        mock_classify.return_value = "read"
        mock_ssm.return_value = "total 4\ndrwxr-xr-x 2 root root"
        result = self._call(host_id="i-123", command="ls -la", method="ssm")
        assert "drwxr" in result

    @patch("agenticops.skills.execution._execute_ssh")
    @patch("agenticops.skills.execution.classify_shell_command")
    def test_readonly_command_ssh(self, mock_classify, mock_ssh):
        mock_classify.return_value = "read"
        mock_ssh.return_value = "uptime: 5 days"
        result = self._call(host_id="10.0.1.5", command="uptime", method="ssh")
        assert "5 days" in result

    @patch("agenticops.skills.execution._execute_ssm")
    @patch("agenticops.skills.execution.classify_shell_command")
    def test_write_with_confirmation(self, mock_classify, mock_ssm):
        mock_classify.return_value = "write"
        mock_ssm.return_value = "nginx restarted"
        result = self._call(
            host_id="i-123", command="systemctl restart nginx",
            require_confirmation=True
        )
        assert "restarted" in result

    @patch("agenticops.skills.execution.classify_shell_command")
    def test_invalid_method(self, mock_classify):
        mock_classify.return_value = "read"
        result = self._call(host_id="i-123", command="ls", method="telnet")
        assert "Unknown method" in result


# ── _execute_ssm tests ───────────────────────────────────────────────


class TestExecuteSSM:
    @patch("agenticops.skills.execution.time.sleep")
    @patch("agenticops.skills.execution._get_ssm_client")
    def test_success(self, mock_get_ssm, mock_sleep):
        mock_ssm = MagicMock()
        mock_get_ssm.return_value = mock_ssm
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "Hello from host\n",
        }

        result = _execute_ssm("i-123", "echo hello", "us-east-1")
        assert "Hello from host" in result

    @patch("agenticops.skills.execution.time.sleep")
    @patch("agenticops.skills.execution._get_ssm_client")
    def test_failure(self, mock_get_ssm, mock_sleep):
        mock_ssm = MagicMock()
        mock_get_ssm.return_value = mock_ssm
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-456"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Failed",
            "StandardErrorContent": "command not found\n",
        }

        result = _execute_ssm("i-123", "badcmd", "us-east-1")
        assert "Failed" in result
        assert "command not found" in result

    @patch("agenticops.skills.execution.time.sleep")
    @patch("agenticops.skills.execution._get_ssm_client")
    def test_empty_output(self, mock_get_ssm, mock_sleep):
        mock_ssm = MagicMock()
        mock_get_ssm.return_value = mock_ssm
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-789"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "",
        }

        result = _execute_ssm("i-123", "true", "us-east-1")
        assert "(no output)" in result

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_exception(self, mock_get_ssm):
        mock_ssm = MagicMock()
        mock_get_ssm.return_value = mock_ssm
        mock_ssm.send_command.side_effect = Exception("Throttled")

        result = _execute_ssm("i-123", "ls", "us-east-1")
        assert "SSM error" in result

    @patch("agenticops.skills.execution.time.sleep")
    @patch("agenticops.skills.execution._get_ssm_client")
    def test_output_truncation(self, mock_get_ssm, mock_sleep):
        mock_ssm = MagicMock()
        mock_get_ssm.return_value = mock_ssm
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-big"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "x" * (MAX_OUTPUT_CHARS + 500),
        }

        result = _execute_ssm("i-123", "cat bigfile", "us-east-1")
        assert "truncated" in result


# ── _execute_ssh tests ───────────────────────────────────────────────


class TestExecuteSSH:
    @patch("agenticops.skills.execution.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="5 days uptime\n", stderr="")
        result = _execute_ssh("10.0.1.5", "uptime")
        assert "5 days" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Permission denied")
        result = _execute_ssh("10.0.1.5", "cat /etc/shadow")
        assert "SSH error" in result
        assert "Permission denied" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=30)
        result = _execute_ssh("10.0.1.5", "sleep 999")
        assert "timed out" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ssh_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = _execute_ssh("10.0.1.5", "ls")
        assert "SSH client not found" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = _execute_ssh("10.0.1.5", "true")
        assert "(no output)" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_output_truncation(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="y" * (MAX_OUTPUT_CHARS + 100), stderr=""
        )
        result = _execute_ssh("10.0.1.5", "cat bigfile")
        assert "truncated" in result


# ── run_kubectl tests ────────────────────────────────────────────────


class TestRunKubectl:
    def _call(self, **kwargs):
        return run_kubectl._tool_func(**kwargs)

    def test_empty_command(self):
        result = self._call(command="")
        assert "Empty kubectl command" in result

    @patch("agenticops.skills.execution.classify_kubectl_command")
    def test_blocked_command(self, mock_classify):
        mock_classify.return_value = "blocked"
        result = self._call(command="delete namespace kube-system")
        assert "blocked" in result.lower()

    @patch("agenticops.skills.execution.classify_kubectl_command")
    def test_write_needs_confirmation(self, mock_classify):
        mock_classify.return_value = "write"
        result = self._call(command="delete pod my-pod", namespace="default")
        assert "requires confirmation" in result

    @patch("agenticops.skills.execution._execute_kubectl")
    @patch("agenticops.skills.execution.classify_kubectl_command")
    def test_read_command(self, mock_classify, mock_exec):
        mock_classify.return_value = "read"
        mock_exec.return_value = "NAME  READY  STATUS\nmy-pod  1/1  Running"
        result = self._call(command="get pods", cluster_name="my-cluster", region="us-east-1")
        assert "Running" in result

    @patch("agenticops.skills.execution._execute_kubectl")
    @patch("agenticops.skills.execution.classify_kubectl_command")
    def test_write_with_confirmation(self, mock_classify, mock_exec):
        mock_classify.return_value = "write"
        mock_exec.return_value = 'pod "my-pod" deleted'
        result = self._call(
            command="delete pod my-pod", cluster_name="c1",
            region="us-east-1", require_confirmation=True
        )
        assert "deleted" in result


# ── _execute_kubectl tests ───────────────────────────────────────────


class TestExecuteKubectl:
    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/fake-kubeconfig"})
    @patch("os.path.isfile", return_value=True)
    def test_with_kubeconfig_env(self, mock_isfile, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="pod/nginx Running", stderr="")
        result = _execute_kubectl("", "get pods", "", "default")
        assert "nginx" in result
        # Should NOT call aws eks update-kubeconfig
        assert mock_run.call_count == 1  # only the kubectl call

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_no_kubeconfig_no_cluster(self, mock_run):
        result = _execute_kubectl("", "get pods", "", "default")
        assert "No cluster_name" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_update_kubeconfig_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="aws error", stdout="")
        result = _execute_kubectl("bad-cluster", "get pods", "us-east-1", "default")
        assert "Failed to update kubeconfig" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/fake"})
    @patch("os.path.isfile", return_value=True)
    def test_kubectl_error(self, mock_isfile, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: the server doesn't have resource type"
        )
        result = _execute_kubectl("", "get widgets", "", "default")
        assert "kubectl error" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/fake"})
    @patch("os.path.isfile", return_value=True)
    def test_kubectl_timeout(self, mock_isfile, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="kubectl", timeout=30)
        result = _execute_kubectl("", "get pods", "", "default")
        assert "timed out" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/fake"})
    @patch("os.path.isfile", return_value=True)
    def test_kubectl_not_found(self, mock_isfile, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = _execute_kubectl("", "get pods", "", "default")
        assert "kubectl not found" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/fake"})
    @patch("os.path.isfile", return_value=True)
    def test_empty_output(self, mock_isfile, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = _execute_kubectl("", "get pods", "", "empty-ns")
        assert "(no output)" in result

    @patch("agenticops.skills.execution.subprocess.run")
    @patch.dict("os.environ", {"KUBECONFIG": "/tmp/fake"})
    @patch("os.path.isfile", return_value=True)
    def test_output_truncation(self, mock_isfile, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="z" * (MAX_OUTPUT_CHARS + 200), stderr=""
        )
        result = _execute_kubectl("", "get pods", "", "default")
        assert "truncated" in result
