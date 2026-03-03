"""Execution tools — run commands on remote hosts and Kubernetes clusters.

Two @tool functions:
- run_on_host: Execute shell commands via SSM or SSH
- run_kubectl: Execute kubectl commands on EKS clusters

Both enforce security classification before execution.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time

from strands import tool

from agenticops.skills.security import classify_shell_command, classify_kubectl_command

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 4000
SSM_TIMEOUT = 30
SSH_TIMEOUT = 30
KUBECTL_TIMEOUT = 30


def _get_ssm_client(region: str = "us-east-1"):
    """Get an SSM client using the same pattern as aws_tools."""
    import boto3

    return boto3.client("ssm", region_name=region)


# ── Shell Execution ──────────────────────────────────────────────────


@tool
def run_on_host(
    host_id: str,
    command: str,
    method: str = "ssm",
    region: str = "us-east-1",
    require_confirmation: bool = False,
) -> str:
    """Execute a shell command on a remote host via SSM or SSH.

    Use this for host-level diagnostics: checking processes, disk usage,
    network connections, logs, system metrics, etc. Commands are classified
    by security tier — read-only commands run directly, write commands
    require confirmation, dangerous commands are blocked.

    Args:
        host_id: EC2 instance ID (for SSM) or hostname/IP (for SSH).
        command: Shell command to execute (e.g., 'ps aux', 'df -h', 'journalctl -u nginx --no-pager -n 50').
        method: Execution method — 'ssm' (default, uses AWS Systems Manager) or 'ssh'.
        region: AWS region for SSM (default: us-east-1).
        require_confirmation: Set to true to acknowledge a write operation.

    Returns:
        Command output, or error/confirmation message.
    """
    command = command.strip()
    if not command:
        return "Error: Empty command."

    # Security classification
    tier = classify_shell_command(command)

    if tier == "blocked":
        return (
            f"Error: Command blocked for safety. Dangerous operations like "
            f"'rm -rf /', 'mkfs', 'shutdown', 'reboot', and pipe-to-bash are not allowed. "
            f"Command: {command}"
        )

    if tier in ("write", "unknown") and not require_confirmation:
        return (
            f"This command modifies system state and requires confirmation. "
            f"Classification: {tier}. Command: {command}\n"
            f"Present this to the user and call again with require_confirmation=True after approval."
        )

    if method == "ssm":
        return _execute_ssm(host_id, command, region)
    elif method == "ssh":
        return _execute_ssh(host_id, command)
    else:
        return f"Error: Unknown method '{method}'. Use 'ssm' or 'ssh'."


def _execute_ssm(instance_id: str, command: str, region: str) -> str:
    """Execute a command via SSM SendCommand."""
    try:
        ssm = _get_ssm_client(region)

        response = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [command]},
            TimeoutSeconds=SSM_TIMEOUT,
        )
        command_id = response["Command"]["CommandId"]

        # Poll for completion
        for _ in range(SSM_TIMEOUT):
            time.sleep(1)
            try:
                result = ssm.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id,
                )
                status = result["Status"]
                if status in ("Success", "Failed", "TimedOut", "Cancelled"):
                    break
            except ssm.exceptions.InvocationDoesNotExist:
                continue

        if status == "Success":
            output = result.get("StandardOutputContent", "").strip()
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
            return output if output else "(no output)"
        else:
            stderr = result.get("StandardErrorContent", "").strip()
            if len(stderr) > MAX_OUTPUT_CHARS:
                stderr = stderr[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
            return f"Command {status}. Error: {stderr}" if stderr else f"Command {status}."

    except Exception as e:
        logger.exception("SSM execution failed for %s", instance_id)
        return f"SSM error: {e}"


def _execute_ssh(host: str, command: str) -> str:
    """Execute a command via SSH."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", host, command],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
            shell=False,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if len(stderr) > MAX_OUTPUT_CHARS:
                stderr = stderr[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
            return f"SSH error (exit {result.returncode}): {stderr}"

        output = result.stdout.strip()
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
        return output if output else "(no output)"

    except subprocess.TimeoutExpired:
        return f"SSH command timed out after {SSH_TIMEOUT} seconds."
    except FileNotFoundError:
        return "Error: SSH client not found. Ensure 'ssh' is installed and on PATH."
    except Exception as e:
        logger.exception("SSH execution failed for %s", host)
        return f"SSH error: {e}"


# ── kubectl Execution ────────────────────────────────────────────────


@tool
def run_kubectl(
    cluster_name: str = "",
    command: str = "",
    region: str = "",
    namespace: str = "default",
    require_confirmation: bool = False,
) -> str:
    """Execute a kubectl command on an EKS cluster.

    Use this for Kubernetes diagnostics: checking pods, services, nodes,
    events, logs, etc. Commands are classified by security tier — read-only
    commands run directly, write commands require confirmation, dangerous
    commands are blocked.

    Args:
        cluster_name: EKS cluster name. Leave empty to use the default cluster from config.
        command: kubectl subcommand (e.g., 'get pods', 'describe node ip-10-0-1-5', 'logs pod/my-app -c main --tail=100').
        region: AWS region. Leave empty to use the default region from config.
        namespace: Kubernetes namespace (default: 'default').
        require_confirmation: Set to true to acknowledge a write operation.

    Returns:
        kubectl output, or error/confirmation message.
    """
    from agenticops.config import settings

    command = command.strip()
    if not command:
        return "Error: Empty kubectl command."

    # Apply config defaults for cluster and region
    if not cluster_name:
        cluster_name = settings.eks_cluster_name
    if not region:
        region = settings.eks_cluster_region or settings.bedrock_region or "us-east-1"

    # Security classification
    tier = classify_kubectl_command(command)

    if tier == "blocked":
        return (
            f"Error: kubectl command blocked for safety. Operations like "
            f"'delete namespace kube-system' and 'delete --all --all-namespaces' "
            f"are not allowed. Command: kubectl {command}"
        )

    if tier in ("write", "unknown") and not require_confirmation:
        return (
            f"This kubectl command modifies cluster state and requires confirmation. "
            f"Classification: {tier}. Command: kubectl -n {namespace} {command}\n"
            f"Present this to the user and call again with require_confirmation=True after approval."
        )

    return _execute_kubectl(cluster_name, command, region, namespace)


def _execute_kubectl(cluster_name: str, command: str, region: str, namespace: str) -> str:
    """Execute kubectl after updating kubeconfig for the EKS cluster."""
    try:
        # If KUBECONFIG env var is set, use it directly (skip update-kubeconfig).
        # This supports pre-configured kubeconfig files (e.g., EKS Lab bastion).
        kubeconfig_path = os.environ.get("KUBECONFIG", "")
        if not kubeconfig_path or not os.path.isfile(kubeconfig_path):
            # No pre-configured kubeconfig — update via aws eks
            if not cluster_name:
                return "Error: No cluster_name provided and no KUBECONFIG set. Set AIOPS_EKS_CLUSTER_NAME or pass cluster_name."
            update_result = subprocess.run(
                ["aws", "eks", "update-kubeconfig", "--name", cluster_name, "--region", region],
                capture_output=True,
                text=True,
                timeout=15,
                shell=False,
            )
            if update_result.returncode != 0:
                return f"Failed to update kubeconfig: {update_result.stderr.strip()}"

        # Build kubectl command
        kubectl_cmd = f"kubectl -n {shlex.quote(namespace)} {command}"
        args = shlex.split(kubectl_cmd)

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=KUBECTL_TIMEOUT,
            shell=False,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if len(stderr) > MAX_OUTPUT_CHARS:
                stderr = stderr[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
            return f"kubectl error (exit {result.returncode}): {stderr}"

        output = result.stdout.strip()
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
        return output if output else "(no output)"

    except subprocess.TimeoutExpired:
        return f"kubectl command timed out after {KUBECTL_TIMEOUT} seconds."
    except FileNotFoundError:
        return "Error: kubectl not found. Ensure 'kubectl' is installed and on PATH."
    except Exception as e:
        logger.exception("kubectl execution failed for cluster %s", cluster_name)
        return f"kubectl error: {e}"
