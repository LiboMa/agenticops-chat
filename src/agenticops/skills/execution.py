"""Execution tools — run commands on remote hosts and Kubernetes clusters.

Two @tool functions:
- run_on_host: Execute shell commands via SSM or SSH (method="auto" climbs the
  human-SRE access ladder: SSM → SSH on failure, with a visible attempt trail)
- run_kubectl: Execute kubectl commands on EKS clusters

Both enforce security classification before execution and are account-addressed:
credentials come ONLY from a registered account (resolved via the provider
layer), never a local profile / ambient chain.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import time
from typing import Any

from strands import tool

from agenticops.skills.security import classify_shell_command, classify_kubectl_command

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 4000
SSM_TIMEOUT = 30
SSH_TIMEOUT = 30
KUBECTL_TIMEOUT = 30

# EC2 instance-id shape (i- followed by 8 or 17 hex chars).
_INSTANCE_ID_RE = re.compile(r"^i-[0-9a-f]{8}([0-9a-f]{9})?$")

# SSM failure classes that warrant an SSH fallback in method="auto".
_SSH_FALLBACK_CLASSES = {
    "InvalidInstanceId", "TargetNotConnected", "AccessDenied", "Timeout", "NoCredentials",
}


def _get_ssm_client(region: str, account: Any) -> Any:
    """Get an SSM client for a registered account. Fail-closed; no ambient fallback.

    Args:
        region: AWS region for the SSM client.
        account: Account snapshot or registered account name.
    """
    from agenticops.credentials.resolver import resolve_account_session

    return resolve_account_session(account, region).client("ssm", region_name=region)


# ── Shell Execution ──────────────────────────────────────────────────


def _resolve_host_account(host_id: str, account: str, region: str):
    """Resolve (account_snapshot, region, source) for an SSM target.

    Order: explicit account → inventory match by instance id → single-account
    default. Region: explicit → inventory → account.regions[0] → us-east-1.
    Raises AccountResolutionError (caller turns it into an error string).
    """
    from agenticops.credentials.resolver import (
        get_account_snapshot,
        find_instance_account,
        resolve_default_account,
        AccountResolutionError,
        ERR_UNKNOWN_ACCOUNT,
        list_enabled_accounts,
    )

    if account:
        snap = get_account_snapshot(account, "aws")
        if snap is None:
            names = ", ".join(sorted(a.name for a in list_enabled_accounts("aws"))) or "(none)"
            raise AccountResolutionError(
                ERR_UNKNOWN_ACCOUNT.format(ref=account, provider="aws", names=names)
            )
        eff_region = region or (snap.regions[0] if snap.regions else "us-east-1")
        return snap, eff_region, "explicit account"

    if _INSTANCE_ID_RE.match(host_id):
        found = find_instance_account(host_id, region)
        if found:
            snap, inv_region = found
            return snap, region or inv_region or (snap.regions[0] if snap.regions else "us-east-1"), "inventory match"

    snap = resolve_default_account("aws")
    eff_region = region or (snap.regions[0] if snap.regions else "us-east-1")
    return snap, eff_region, "default account"


@tool
def run_on_host(
    host_id: str,
    command: str,
    method: str = "auto",
    region: str = "",
    account: str = "",
    require_confirmation: bool = False,
) -> str:
    """Execute a shell command on a remote host via SSM or SSH.

    Use this for host-level diagnostics: checking processes, disk usage,
    network connections, logs, system metrics, etc. Commands are classified
    by security tier — read-only commands run directly, write commands
    require confirmation, dangerous commands are blocked.

    Account is resolved automatically (like a human SRE): explicit account →
    inventory match by instance id → single-account default. Credentials come
    ONLY from a registered account, never a local profile.

    method="auto" (default) climbs the access ladder: for an EC2 instance id it
    tries SSM first; if SSM fails (agent not connected, wrong account, access
    denied, timeout) it classifies the failure and falls back to SSH using the
    instance's inventory IP. The reply shows the full attempt trail.

    Args:
        host_id: EC2 instance ID (i-...) for SSM, or hostname/IP for SSH.
        command: Shell command (e.g., 'ps aux', 'df -h', 'journalctl -u nginx --no-pager -n 50').
        method: 'auto' (default, SSM→SSH ladder), 'ssm', or 'ssh'.
        region: AWS region for SSM. Omit to resolve from inventory / account.
        account: Registered account name. Omit for single-account / inventory match.
        require_confirmation: Set to true to acknowledge a write operation.

    Returns:
        Command output, or error/confirmation message.
    """
    command = command.strip()
    if not command:
        return "Error: Empty command."

    # Security classification — always before any transport.
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

    if method == "ssh":
        return _run_ssh_for_host(host_id, command)

    if method == "ssm":
        from agenticops.credentials.resolver import AccountResolutionError
        try:
            snap, eff_region, _ = _resolve_host_account(host_id, account, region)
        except AccountResolutionError as e:
            return f"Error: {e}"
        ok, text, _ = _execute_ssm(host_id, command, eff_region, snap)
        return text

    if method == "auto":
        return _run_auto_ladder(host_id, command, region, account)

    return f"Error: Unknown method '{method}'. Use 'auto', 'ssm', or 'ssh'."


def _run_auto_ladder(host_id: str, command: str, region: str, account: str) -> str:
    """SSM → SSH access ladder with a visible attempt trail (human-SRE style)."""
    from agenticops.credentials.resolver import AccountResolutionError, get_instance_ips

    # Non-instance-id hosts (hostnames/IPs) go straight to SSH.
    if not _INSTANCE_ID_RE.match(host_id):
        return _run_ssh_for_host(host_id, command)

    try:
        snap, eff_region, source = _resolve_host_account(host_id, account, region)
    except AccountResolutionError as e:
        return f"Error: {e}"

    ok, text, failure_class = _execute_ssm(host_id, command, eff_region, snap)
    if ok:
        return text

    # SSM failed — decide whether to climb to SSH.
    if failure_class not in _SSH_FALLBACK_CLASSES:
        return text

    ips = get_instance_ips(host_id)
    target_ip = (ips or {}).get("private_ip") or (ips or {}).get("public_ip")
    if not target_ip:
        return (
            f"SSM failed: {text}\n"
            f"SSH fallback unavailable: {host_id} is not in inventory with an IP "
            f"(run a scan, or call run_on_host with method='ssh' and the host's IP/hostname)."
        )

    ssh_result = _run_ssh_for_host(target_ip, command)
    return (
        f"SSM failed: {text}\n"
        f"Falling back to SSH {target_ip} ...\n{ssh_result}"
    )


def _execute_ssm(instance_id: str, command: str, region: str, account: Any):
    """Execute via SSM SendCommand. Returns (ok, text, failure_class).

    failure_class classifies transport-level failures so the auto ladder can
    decide whether to fall back to SSH and so the agent gets actionable text.
    """
    from botocore.exceptions import ClientError, BotoCoreError
    from agenticops.credentials.resolver import AccountResolutionError

    acct_name = getattr(account, "name", account)
    try:
        ssm = _get_ssm_client(region, account)
    except AccountResolutionError as e:
        return False, f"SSM credentials unavailable: {e}", "NoCredentials"

    try:
        response = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [command]},
            TimeoutSeconds=SSM_TIMEOUT,
        )
        command_id = response["Command"]["CommandId"]

        status = "Pending"
        result: dict = {}
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
            return True, (output if output else "(no output)"), ""
        if status in ("TimedOut", "Pending"):
            return False, (
                f"SSM command {status} on {instance_id} (account {acct_name}, {region}) — "
                f"transient; retry shortly."
            ), "Timeout"
        stderr = result.get("StandardErrorContent", "").strip()
        if len(stderr) > MAX_OUTPUT_CHARS:
            stderr = stderr[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
        return False, (f"Command {status}. Error: {stderr}" if stderr else f"Command {status}."), "CommandFailed"

    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        return _classify_ssm_error(code, instance_id, acct_name, region)
    except BotoCoreError as e:
        return False, f"SSM transport error on {instance_id} (account {acct_name}, {region}): {e}", "Timeout"
    except Exception as e:
        logger.exception("SSM execution failed for %s", instance_id)
        return False, f"SSM error: {e}", "Unknown"


def _classify_ssm_error(code: str, instance_id: str, acct_name, region: str):
    """Map a botocore SSM error code to (ok=False, actionable_text, failure_class)."""
    if code in ("InvalidInstanceId", "InvalidInstanceID.NotFound"):
        return False, (
            f"SSM InvalidInstanceId: {instance_id} is not registered with SSM in account "
            f"{acct_name} region {region} — the SSM agent may not be installed/running, or the "
            f"instance is in a different account/region. Try a scan to refresh inventory, pass "
            f"account=/region=, or fall back to SSH."
        ), "InvalidInstanceId"
    if code == "TargetNotConnected":
        return False, (
            f"SSM TargetNotConnected: {instance_id} (account {acct_name}, {region}) has the SSM "
            f"agent registered but offline — check `aws ssm describe-instance-information`, the "
            f"instance state, and VPC endpoints / outbound 443. Falling back to SSH if an IP is known."
        ), "TargetNotConnected"
    if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation"):
        return False, (
            f"SSM AccessDenied: the resolved role for account {acct_name} lacks ssm:SendCommand / "
            f"ssm:GetCommandInvocation on {instance_id}."
        ), "AccessDenied"
    if code in ("ThrottlingException", "RequestThrottled", "Throttling"):
        return False, (
            f"SSM throttled on {instance_id} (account {acct_name}, {region}) — transient; retry shortly."
        ), "Timeout"
    return False, (
        f"SSM error {code or '(unknown)'} on {instance_id} (account {acct_name}, {region})."
    ), "Unknown"


def _run_ssh_for_host(host_or_ip: str, command: str) -> str:
    """Resolve SSH transport config (registered ssh account → settings defaults) and run."""
    from agenticops.credentials.resolver import find_ssh_account_for_host
    from agenticops.config import settings

    user = ""
    key_path = ""
    port = 22
    host = host_or_ip

    ssh_acct = find_ssh_account_for_host(host_or_ip)
    if ssh_acct is not None:
        creds = ssh_acct.credentials or {}
        host = creds.get("host", host_or_ip)
        user = creds.get("username", "")
        key_path = creds.get("private_key_path", "")
        port = int(creds.get("port", 22) or 22)

    if not user:
        user = settings.ssh_default_user or ""
    if not key_path:
        key_path = settings.ssh_default_key_path or ""
    bastion = settings.ssh_bastion_host or ""

    return _execute_ssh(host, command, user=user, key_path=key_path, port=port, bastion=bastion)


def _execute_ssh(
    host: str,
    command: str,
    user: str = "",
    key_path: str = "",
    port: int = 22,
    bastion: str = "",
) -> str:
    """Execute a command via SSH (BatchMode, fail-closed on missing key/host)."""
    from agenticops.providers.ssh import _clean_subprocess_env

    ssh_args = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        "-p", str(port),
    ]
    if key_path:
        ssh_args += ["-i", os.path.expanduser(key_path)]
    if bastion:
        ssh_args += ["-J", bastion]
    target = f"{user}@{host}" if user else host
    ssh_args += [target, command]

    try:
        result = subprocess.run(
            ssh_args,
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
            shell=False,
            env=_clean_subprocess_env(),
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if len(stderr) > MAX_OUTPUT_CHARS:
                stderr = stderr[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
            return f"SSH error (exit {result.returncode}) to {target}: {stderr}"

        output = result.stdout.strip()
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
        return output if output else "(no output)"

    except subprocess.TimeoutExpired:
        return f"SSH command timed out after {SSH_TIMEOUT} seconds (target {target})."
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
    account: str = "",
) -> str:
    """Execute a kubectl command on an EKS cluster.

    Use this for Kubernetes diagnostics: checking pods, services, nodes,
    events, logs, etc. Commands are classified by security tier — read-only
    commands run directly, write commands require confirmation, dangerous
    commands are blocked.

    Account is resolved automatically: explicit account → inventory match by
    cluster name → single-account default. Credentials come ONLY from a
    registered account, never a local profile.

    Args:
        cluster_name: EKS cluster name. Leave empty to use the default cluster from config.
        command: kubectl subcommand (e.g., 'get pods', 'describe node ip-10-0-1-5', 'logs pod/my-app -c main --tail=100').
        region: AWS region. Leave empty to resolve from inventory / account.
        namespace: Kubernetes namespace (default: 'default').
        require_confirmation: Set to true to acknowledge a write operation.
        account: Registered account name. Omit for single-account / inventory match.

    Returns:
        kubectl output, or error/confirmation message.
    """
    command = command.strip()
    if not command:
        return "Error: Empty kubectl command."

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

    return _execute_kubectl(cluster_name, command, region, namespace, account)


def _execute_kubectl(
    cluster_name: str, command: str, region: str, namespace: str, account: str = ""
) -> str:
    """Execute kubectl after updating kubeconfig for the EKS cluster."""
    try:
        # If KUBECONFIG env var is set, use it directly (skip update-kubeconfig).
        # This supports pre-configured kubeconfig files (e.g., EKS Lab bastion).
        kubeconfig_path = os.environ.get("KUBECONFIG", "")
        if not kubeconfig_path or not os.path.isfile(kubeconfig_path):
            # No pre-configured kubeconfig — update via aws eks, scoped to a
            # registered account (explicit → inventory by cluster → default).
            # The pre-set KUBECONFIG branch above (EKS-lab / bastion) bypasses this.
            if not cluster_name:
                return "Error: No cluster_name provided and no KUBECONFIG set. Set AIOPS_EKS_CLUSTER_NAME or pass cluster_name."
            from agenticops.credentials.resolver import (
                AccountResolutionError,
                get_account_snapshot,
                find_cluster_account,
                resolve_default_account,
                get_subprocess_env_for_account,
                ERR_UNKNOWN_ACCOUNT,
                list_enabled_accounts,
            )
            try:
                if account:
                    snap = get_account_snapshot(account, "aws")
                    if snap is None:
                        names = ", ".join(sorted(a.name for a in list_enabled_accounts("aws"))) or "(none)"
                        return f"Error: {ERR_UNKNOWN_ACCOUNT.format(ref=account, provider='aws', names=names)}"
                    eff_region = region or (snap.regions[0] if snap.regions else "")
                else:
                    found = find_cluster_account(cluster_name, region)
                    if found:
                        snap, inv_region = found
                        eff_region = region or inv_region or (snap.regions[0] if snap.regions else "")
                    else:
                        snap = resolve_default_account("aws")
                        eff_region = region or (snap.regions[0] if snap.regions else "")
                if not eff_region:
                    return "Error: No region resolved for EKS update-kubeconfig — pass region= or scan inventory."
                eks_env = get_subprocess_env_for_account(snap, eff_region)
            except AccountResolutionError as e:
                return f"Error: {e}"
            region = eff_region
            update_result = subprocess.run(
                ["aws", "eks", "update-kubeconfig", "--name", cluster_name, "--region", region],
                capture_output=True,
                text=True,
                timeout=15,
                shell=False,
                env=eks_env,
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
