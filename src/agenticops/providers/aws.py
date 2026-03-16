"""AWS CloudProvider implementation."""

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

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

BLOCKED_PATTERNS = [
    "iam create-user", "iam delete-user", "iam create-access-key",
    "iam attach-", "s3 rm --recursive", "ec2 terminate-instances",
    "organizations create-", "organizations delete-",
    "--force",
]

TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 4000


class AWSProvider(CloudProvider):
    """AWS cloud provider using boto3 and the AWS CLI."""

    @property
    def provider_type(self) -> str:
        return "aws"

    def resolve_credentials(self) -> bool:
        """Resolve AWS credentials through the following chain:

        1. Build base session (profile_name > static keys > default chain)
        2. If role_arn set, use base session's STS to AssumeRole
        3. Validate by calling sts:GetCallerIdentity
        """
        if boto3 is None:
            logger.error("boto3 is required for AWS provider")
            return False

        creds = self.account.credentials or {}

        # Step 1: Build base session for authentication
        if creds.get("profile_name"):
            base_session = boto3.Session(profile_name=creds["profile_name"])
        elif creds.get("access_key_id") and creds.get("secret_access_key"):
            base_session = boto3.Session(
                aws_access_key_id=creds["access_key_id"],
                aws_secret_access_key=creds["secret_access_key"],
                aws_session_token=creds.get("session_token"),
            )
        else:
            base_session = boto3.Session()

        # Step 2: If role_arn set, assume role using base session
        if creds.get("role_arn"):
            try:
                sts = base_session.client("sts")
                resp = sts.assume_role(
                    RoleArn=creds["role_arn"],
                    RoleSessionName=f"agenticops-{self.account.name}",
                )
                assumed = resp["Credentials"]
                session = boto3.Session(
                    aws_access_key_id=assumed["AccessKeyId"],
                    aws_secret_access_key=assumed["SecretAccessKey"],
                    aws_session_token=assumed["SessionToken"],
                )
            except Exception as e:
                logger.error("STS AssumeRole failed for %s: %s", self.account.name, e)
                return False
        else:
            session = base_session

        # Validate by calling STS
        try:
            session.client("sts").get_caller_identity()
        except Exception as e:
            logger.error("AWS credential validation failed for %s: %s", self.account.name, e)
            return False

        # Cache the session
        regions = self.account.regions or ["us-east-1"]
        for region in regions:
            cache_key = f"aws:{self.account.name}:{region}"
            set_cached_session(cache_key, session)

        self._session = session
        return True

    def sdk_session(self) -> Any:
        """Return the boto3 Session (call resolve_credentials first)."""
        if not hasattr(self, "_session"):
            self.resolve_credentials()
        return self._session

    def cli_tool(self) -> Callable:
        """Return a callable that executes AWS CLI commands for this account.

        The function:
        - Validates commands start with 'aws '
        - Blocks dangerous patterns
        - Auto-appends --output json
        - Sets credential env vars from session
        - 30s timeout, 4000 char output limit
        """
        account_name = self.account.name
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", account_name)

        # Capture session credentials if available
        session = self._session if hasattr(self, "_session") else None

        def _run_aws_cli(command: str) -> str:
            nonlocal session
            command = command.strip()

            if not command.startswith("aws "):
                return "Error: Command must start with 'aws '."

            # Shell injection check
            for dangerous in ["|", ";", "&&", "$(", "`", ">", "<"]:
                if dangerous in command:
                    return f"Error: Shell operator '{dangerous}' is not allowed."

            # Blocked pattern check
            cmd_lower = command.lower()
            for pattern in BLOCKED_PATTERNS:
                if pattern.lower() in cmd_lower:
                    return f"Error: Blocked dangerous pattern '{pattern}' in command."

            # Auto-append --output json
            if "--output" not in command:
                command = f"{command} --output json"

            try:
                args = shlex.split(command)
            except ValueError as e:
                return f"Error: Invalid command syntax: {e}"

            # Build env with credentials
            env = os.environ.copy()
            if session:
                try:
                    frozen = session.get_credentials().get_frozen_credentials()
                    env["AWS_ACCESS_KEY_ID"] = frozen.access_key
                    env["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
                    if frozen.token:
                        env["AWS_SESSION_TOKEN"] = frozen.token
                except Exception:
                    pass  # Fall back to ambient credentials

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
                return "Error: AWS CLI ('aws') not found on PATH."

            if result.returncode != 0:
                stderr = result.stderr.strip()[:MAX_OUTPUT_CHARS]
                return f"Error (exit {result.returncode}): {stderr}"

            output = result.stdout.strip()
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
            return output if output else "(no output)"

        _run_aws_cli.__name__ = f"run_aws_cli_{safe_name}"
        _run_aws_cli.__doc__ = (
            f"Execute an AWS CLI command for account '{account_name}'. "
            f"Command must start with 'aws '. Returns JSON output.\n\n"
            f"Args:\n"
            f"    command: The AWS CLI command to execute (must start with 'aws ')."
        )

        from strands import tool as strands_tool
        return strands_tool(_run_aws_cli)
