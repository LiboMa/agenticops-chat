"""Unit tests for agenticops.skills.execution module.

Covers: run_on_host, run_kubectl, _execute_ssm, _execute_ssh, _execute_kubectl.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from types import SimpleNamespace

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

_SNAP = SimpleNamespace(
    id=1, name="acct", provider="aws",
    credentials={"account_id": "111111111111"}, regions=["us-east-1"], labels={},
    credential_source_type="assume_role",
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

    @patch("agenticops.skills.execution._resolve_host_account", return_value=(_SNAP, "us-east-1", "explicit"))
    @patch("agenticops.skills.execution._execute_ssm", return_value=(True, "total 4\ndrwxr-xr-x 2 root root", ""))
    @patch("agenticops.skills.execution.classify_shell_command")
    def test_readonly_command_ssm(self, mock_classify, mock_ssm, mock_resolve):
        mock_classify.return_value = "read"
        result = self._call(host_id="i-0123456789abcdef0", command="ls -la", method="ssm")
        assert "drwxr" in result

    @patch("agenticops.skills.execution._run_ssh_for_host")
    @patch("agenticops.skills.execution.classify_shell_command")
    def test_readonly_command_ssh(self, mock_classify, mock_ssh):
        mock_classify.return_value = "read"
        mock_ssh.return_value = "uptime: 5 days"
        result = self._call(host_id="10.0.1.5", command="uptime", method="ssh")
        assert "5 days" in result

    @patch("agenticops.skills.execution._resolve_host_account", return_value=(_SNAP, "us-east-1", "explicit"))
    @patch("agenticops.skills.execution._execute_ssm", return_value=(True, "nginx reloaded", ""))
    @patch("agenticops.skills.execution.classify_shell_command")
    def test_write_with_confirmation(self, mock_classify, mock_ssm, mock_resolve):
        mock_classify.return_value = "write"
        # `systemctl restart` is a policies.yaml change_required pattern (refused outside an
        # approved plan — see tests/test_command_audit.py); `reload` is a plain confirmed write.
        result = self._call(
            host_id="i-0123456789abcdef0", command="systemctl reload nginx",
            method="ssm", require_confirmation=True
        )
        assert "reloaded" in result

    @patch("agenticops.skills.execution.classify_shell_command")
    def test_invalid_method(self, mock_classify):
        mock_classify.return_value = "read"
        result = self._call(host_id="i-123", command="ls", method="kerberos")
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

        result = _execute_ssm("i-123", "echo hello", "us-east-1", _SNAP)[1]
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

        result = _execute_ssm("i-123", "badcmd", "us-east-1", _SNAP)[1]
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

        result = _execute_ssm("i-123", "true", "us-east-1", _SNAP)[1]
        assert "(no output)" in result

    @patch("agenticops.skills.execution._get_ssm_client")
    def test_exception(self, mock_get_ssm):
        mock_ssm = MagicMock()
        mock_get_ssm.return_value = mock_ssm
        mock_ssm.send_command.side_effect = Exception("Throttled")

        result = _execute_ssm("i-123", "ls", "us-east-1", _SNAP)[1]
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

        result = _execute_ssm("i-123", "cat bigfile", "us-east-1", _SNAP)[1]
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
        mock_exec.return_value = "deployment.apps/my-app scaled"
        # `kubectl delete` is a policies.yaml change_required pattern (refused outside an
        # approved plan — see tests/test_command_audit.py); `scale` is deliberately L1.
        result = self._call(
            command="scale deployment/my-app --replicas=2", cluster_name="c1",
            region="us-east-1", require_confirmation=True
        )
        assert "scaled" in result


# ── _execute_kubectl tests ───────────────────────────────────────────


class TestExecuteKubectl:
    """kubectl runs ONLY with the resolved account's env + private kubeconfig (MVP-2.6.1 spec §3.B.4)."""

    ENV = {"PATH": "/usr/bin", "AWS_ACCESS_KEY_ID": "target-access-key-id", "KUBECONFIG": "/data/kube/1/us-east-1/c1.kubeconfig"}

    def _run(self, mock_run, command="get pods", namespace="default"):
        with patch("agenticops.credentials.resolver.find_cluster_account", return_value=(_SNAP, "us-east-1")), \
             patch("agenticops.credentials.kube.kubectl_env_for_cluster", return_value=dict(self.ENV)) as env_for:
            result = _execute_kubectl("c1", command, "", namespace)
        return result, env_for

    @patch("agenticops.skills.execution.subprocess.run")
    def test_kubectl_gets_the_account_env_and_private_kubeconfig(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="pod/nginx Running", stderr="")
        result, env_for = self._run(mock_run)
        assert "nginx" in result
        env_for.assert_called_once_with(_SNAP, "c1", "us-east-1")
        (args,), kwargs = mock_run.call_args
        assert args == ["kubectl", "-n", "default", "get", "pods"]
        assert kwargs["env"] == self.ENV and kwargs["shell"] is False
        assert mock_run.call_count == 1  # kubeconfig generation is kubectl_env_for_cluster's job

    @patch("agenticops.skills.execution.subprocess.run")
    def test_ambient_kubeconfig_is_no_shortcut(self, mock_run, tmp_path):
        ambient = tmp_path / "ambient.kubeconfig"
        ambient.write_text("apiVersion: v1\n")
        with patch.dict("os.environ", {"KUBECONFIG": str(ambient)}):
            result = _execute_kubectl("", "get pods", "", "default")
        assert "No cluster_name" in result
        assert not mock_run.called

    @patch("agenticops.skills.execution.subprocess.run")
    def test_kubeconfig_failure_is_reported_not_bypassed(self, mock_run):
        from agenticops.credentials.kube import KubeconfigError
        with patch("agenticops.credentials.resolver.find_cluster_account", return_value=(_SNAP, "us-east-1")), \
             patch("agenticops.credentials.kube.kubectl_env_for_cluster", side_effect=KubeconfigError("aws error")):
            result = _execute_kubectl("bad-cluster", "get pods", "us-east-1", "default")
        assert result == "Failed to update kubeconfig: aws error"
        assert not mock_run.called

    @patch("agenticops.skills.execution.subprocess.run")
    def test_account_resolution_failure_is_reported(self, mock_run):
        from agenticops.credentials.resolver import AccountResolutionError
        with patch("agenticops.credentials.resolver.find_cluster_account", return_value=None), \
             patch("agenticops.credentials.resolver.resolve_default_account",
                   side_effect=AccountResolutionError("Multiple enabled aws accounts")):
            result = _execute_kubectl("c1", "get pods", "", "default")
        assert result == "Error: Multiple enabled aws accounts"
        assert not mock_run.called

    @patch("agenticops.skills.execution.subprocess.run")
    def test_kubectl_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: the server doesn't have resource type"
        )
        result, _ = self._run(mock_run, command="get widgets")
        assert "kubectl error" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_kubectl_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="kubectl", timeout=30)
        result, _ = self._run(mock_run)
        assert "timed out" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_kubectl_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result, _ = self._run(mock_run)
        assert "kubectl not found" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result, _ = self._run(mock_run, namespace="empty-ns")
        assert "(no output)" in result

    @patch("agenticops.skills.execution.subprocess.run")
    def test_output_truncation(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="z" * (MAX_OUTPUT_CHARS + 200), stderr=""
        )
        result, _ = self._run(mock_run)
        assert "truncated" in result
