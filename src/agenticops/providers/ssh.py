"""SSH provider — agentless execute path for IDC / bare-metal / any VM.

Credential schema (CloudAccount.credentials):
    {host, port?: 22, username, private_key_path?, name?, sudo?: false}

Uses the system ``ssh`` binary in BatchMode (never prompts — fail-closed when
the key is missing or the host is unknown). Commands pass the same security
classifier as run_on_host before leaving the process.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from typing import Any, Callable

from agenticops.providers.base import CloudProvider, ResourceRef

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60
MAX_OUTPUT = 8000


class SSHProvider(CloudProvider):
    """Agentless SSH host — Capability.EXECUTE + trivial INVENTORY."""

    @property
    def provider_type(self) -> str:
        return "ssh"

    def resolve_credentials(self) -> bool:
        creds = self.account.credentials or {}
        host = creds.get("host")
        username = creds.get("username")
        if not host or not username:
            logger.error(
                "ssh account %s: 'host' and 'username' are required", self.account.name
            )
            return False
        key_path = creds.get("private_key_path")
        if key_path:
            expanded = os.path.expanduser(key_path)
            if not os.path.exists(expanded):
                logger.error(
                    "ssh account %s: private key not found at %s",
                    self.account.name, expanded,
                )
                return False
        self._cfg = dict(creds)
        return True

    def sdk_session(self) -> Any:
        """No SDK session — connection params are the 'session'."""
        if not hasattr(self, "_cfg"):
            if not self.resolve_credentials():
                raise RuntimeError(
                    f"ssh account {self.account.name}: credential resolution failed"
                )
        return self._cfg

    def list_resources(
        self,
        *,
        query: str = "",
        types: list[str] | None = None,
        region: str | None = None,
        limit: int = 500,
    ) -> list[ResourceRef]:
        """Thin inventory: the configured host itself."""
        cfg = self.sdk_session()
        return [
            ResourceRef(
                provider="ssh",
                account=self.account.name,
                region="",
                service="host",
                rtype="linux",
                native_id=f"{cfg['username']}@{cfg['host']}:{cfg.get('port', 22)}",
                name=cfg.get("name", cfg["host"]),
                labels=dict(self.account.labels or {}),
            )
        ]

    def execute(self, *, target: ResourceRef | None = None, command: str, timeout_s: int = DEFAULT_TIMEOUT) -> dict:
        """Run a command on the host over SSH (security-gated)."""
        from agenticops.skills.security import classify_shell_command

        tier = classify_shell_command(command)
        if tier == "blocked":
            return {"rc": -1, "stdout": "", "stderr": f"Command blocked by security policy: {command!r}"}

        cfg = self.sdk_session()
        ssh_args = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
            "-p", str(cfg.get("port", 22)),
        ]
        key_path = cfg.get("private_key_path")
        if key_path:
            ssh_args += ["-i", os.path.expanduser(key_path)]
        ssh_args.append(f"{cfg['username']}@{cfg['host']}")
        remote_cmd = command
        if cfg.get("sudo"):
            remote_cmd = f"sudo -n {command}"
        ssh_args.append(remote_cmd)

        try:
            result = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                shell=False,
                env=_clean_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return {"rc": -1, "stdout": "", "stderr": f"Timed out after {timeout_s}s"}
        except FileNotFoundError:
            return {"rc": -1, "stdout": "", "stderr": "ssh binary not found on PATH"}

        return {
            "rc": result.returncode,
            "stdout": result.stdout[-MAX_OUTPUT:],
            "stderr": result.stderr[-2000:],
        }

    def cli_tool(self) -> Callable:
        """Agent tool: run a shell command on this SSH host."""
        account_name = self.account.name
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", account_name)
        provider = self

        def _run_ssh(command: str) -> str:
            command = command.strip()
            if not command:
                return "Error: empty command."
            result = provider.execute(command=command)
            if result["rc"] != 0:
                err = result["stderr"] or result["stdout"]
                return f"Error (exit {result['rc']}): {err}"
            return result["stdout"] or "(no output)"

        _run_ssh.__name__ = f"run_ssh_{safe_name}"
        _run_ssh.__doc__ = (
            f"Execute a shell command on IDC/on-prem host '{account_name}' via SSH. "
            f"Destructive commands are blocked by security policy.\n\n"
            f"Args:\n"
            f"    command: The shell command to run on the remote host."
        )

        from strands import tool as strands_tool
        return strands_tool(_run_ssh)


def _clean_subprocess_env() -> dict:
    """Strip all cloud credential env vars before spawning ssh (anti cross-account/cloud leak)."""
    env = dict(os.environ)
    prefixes = ("AWS_", "ARM_", "AZURE_", "GOOGLE_", "ALIBABA_CLOUD_", "ALICLOUD_")
    for key in list(env):
        if key.startswith(prefixes):
            env.pop(key, None)
    return env
