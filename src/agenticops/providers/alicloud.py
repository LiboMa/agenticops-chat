"""Alicloud (Alibaba Cloud) CloudProvider implementation."""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from typing import Any, Callable

from agenticops.providers.base import (
    CloudProvider,
    get_cached_session,
    set_cached_session,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 200_000


class AlicloudProvider(CloudProvider):
    """Alibaba Cloud provider using aliyun CLI."""

    @property
    def provider_type(self) -> str:
        return "alicloud"

    def resolve_credentials(self) -> bool:
        """Resolve Alicloud credentials through the following chain:

        1. credentials.assume_role → RAM Role (set base creds, warn if no access_key_id)
        2. credentials.access_key_id + access_key_secret → static
        3. credentials.profile_name → aliyun CLI profile
        4. ALIBABA_CLOUD_* env vars
        5. empty → ECS RAM Role
        """
        creds = self.account.credentials or {}
        resolved: dict[str, str] = {}

        # 1. Assume role
        if creds.get("assume_role"):
            role_cfg = creds["assume_role"]
            ak = creds.get("access_key_id") or role_cfg.get("access_key_id")
            sk = creds.get("access_key_secret") or role_cfg.get("access_key_secret")
            if not ak:
                logger.warning(
                    "Alicloud assume_role for %s: no access_key_id provided, "
                    "STS AssumeRole may fail without base credentials",
                    self.account.name,
                )
            resolved = {
                "access_key_id": ak or "",
                "access_key_secret": sk or "",
                "role_arn": role_cfg.get("role_arn", ""),
                "role_session_name": role_cfg.get("session_name", f"agenticops-{self.account.name}"),
            }

        # 2. Static credentials
        elif creds.get("access_key_id") and creds.get("access_key_secret"):
            resolved = {
                "access_key_id": creds["access_key_id"],
                "access_key_secret": creds["access_key_secret"],
            }

        # 3. Profile name (used by aliyun CLI directly)
        elif creds.get("profile_name"):
            resolved = {"profile_name": creds["profile_name"]}

        # 4. ALIBABA_CLOUD_* env vars
        elif os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID"):
            resolved = {
                "access_key_id": os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", ""),
                "access_key_secret": os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", ""),
            }

        # 5. ECS RAM Role — no explicit credentials needed
        else:
            resolved = {}

        cache_key = f"alicloud:{self.account.name}:default"
        set_cached_session(cache_key, resolved)
        self._resolved_creds = resolved
        return True

    def sdk_session(self) -> Any:
        """Return the resolved credentials dict."""
        if not hasattr(self, "_resolved_creds"):
            self.resolve_credentials()
        return self._resolved_creds

    def cli_tool(self) -> Callable:
        """Return a callable that executes aliyun CLI commands for this account.

        Auto-appends --region. Sets ALIBABA_CLOUD_* env vars.
        """
        account_name = self.account.name
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", account_name)
        regions = self.account.regions or []
        default_region = regions[0] if regions else "cn-hangzhou"
        resolved = self._resolved_creds if hasattr(self, "_resolved_creds") else {}

        def _run_aliyun_cli(command: str) -> str:
            command = command.strip()

            if not command.startswith("aliyun "):
                return "Error: Command must start with 'aliyun '."

            # Shell injection check
            for dangerous in ["|", ";", "&&", "$(", "`", ">", "<"]:
                if dangerous in command:
                    return f"Error: Shell operator '{dangerous}' is not allowed."

            # Auto-append --region
            if "--region" not in command:
                command = f"{command} --region {default_region}"

            try:
                args = shlex.split(command)
            except ValueError as e:
                return f"Error: Invalid command syntax: {e}"

            # Build env with credentials
            env = os.environ.copy()
            if resolved.get("access_key_id"):
                env["ALIBABA_CLOUD_ACCESS_KEY_ID"] = resolved["access_key_id"]
            if resolved.get("access_key_secret"):
                env["ALIBABA_CLOUD_ACCESS_KEY_SECRET"] = resolved["access_key_secret"]

            try:
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_SECONDS,
                    shell=False,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                return f"Error: Command timed out after {TIMEOUT_SECONDS}s."
            except FileNotFoundError:
                return "Error: Alicloud CLI ('aliyun') not found on PATH."

            if result.returncode != 0:
                stderr = result.stderr.strip()[:MAX_OUTPUT_CHARS]
                return f"Error (exit {result.returncode}): {stderr}"

            output = result.stdout.strip()
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
            return output if output else "(no output)"

        _run_aliyun_cli.__name__ = f"run_aliyun_cli_{safe_name}"
        _run_aliyun_cli.__doc__ = (
            f"Execute an Alicloud CLI command for account '{account_name}'. "
            f"Command must start with 'aliyun '. Returns output text.\n\n"
            f"Args:\n"
            f"    command: The Alicloud CLI command to execute (must start with 'aliyun ')."
        )

        from strands import tool as strands_tool
        return strands_tool(_run_aliyun_cli)
