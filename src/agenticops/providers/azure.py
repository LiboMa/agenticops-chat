"""Azure CloudProvider implementation."""

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
    from azure.identity import AzureCliCredential, ClientSecretCredential
    _HAS_AZURE = True
except ImportError:
    AzureCliCredential = None  # type: ignore[assignment,misc]
    ClientSecretCredential = None  # type: ignore[assignment,misc]
    _HAS_AZURE = False

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 4000


class AzureProvider(CloudProvider):
    """Azure cloud provider using azure-identity SDK and az CLI."""

    @property
    def provider_type(self) -> str:
        return "azure"

    def resolve_credentials(self) -> bool:
        """Resolve Azure credentials through the following chain:

        1. credentials has client_id + client_secret + tenant_id → ClientSecretCredential
        2. ARM_* env vars → ClientSecretCredential
        3. empty → AzureCliCredential
        """
        creds = self.account.credentials or {}
        credential = None

        if not _HAS_AZURE:
            logger.warning(
                "azure-identity not installed; Azure provider will rely on az CLI only"
            )
            self._credential = None
            return True

        # 1. Explicit client credentials
        client_id = creds.get("client_id")
        client_secret = creds.get("client_secret")
        tenant_id = creds.get("tenant_id")

        if client_id and client_secret and tenant_id:
            credential = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )

        # 2. ARM_* env vars
        elif (
            os.environ.get("ARM_CLIENT_ID")
            and os.environ.get("ARM_CLIENT_SECRET")
            and os.environ.get("ARM_TENANT_ID")
        ):
            credential = ClientSecretCredential(
                tenant_id=os.environ["ARM_TENANT_ID"],
                client_id=os.environ["ARM_CLIENT_ID"],
                client_secret=os.environ["ARM_CLIENT_SECRET"],
            )

        # 3. AzureCliCredential
        else:
            credential = AzureCliCredential()

        # Validate by requesting a token
        try:
            credential.get_token("https://management.azure.com/.default")
        except Exception as e:
            logger.error("Azure credential validation failed for %s: %s", self.account.name, e)
            return False

        cache_key = f"azure:{self.account.name}:default"
        set_cached_session(cache_key, credential)
        self._credential = credential
        return True

    def sdk_session(self) -> Any:
        """Return the Azure credential object."""
        if not hasattr(self, "_credential"):
            self.resolve_credentials()
        return self._credential

    def cli_tool(self) -> Callable:
        """Return a callable that executes az CLI commands for this account.

        Auto-appends --subscription and --output json.
        """
        account_name = self.account.name
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", account_name)
        creds = self.account.credentials or {}
        subscription_id = creds.get("subscription_id", "")

        def _run_az_cli(command: str) -> str:
            command = command.strip()

            if not command.startswith("az "):
                return "Error: Command must start with 'az '."

            # Shell injection check
            for dangerous in ["|", ";", "&&", "$(", "`", ">", "<"]:
                if dangerous in command:
                    return f"Error: Shell operator '{dangerous}' is not allowed."

            # Auto-append --output json
            if "--output" not in command and "-o " not in command:
                command = f"{command} --output json"

            # Auto-append --subscription
            if subscription_id and "--subscription" not in command:
                command = f"{command} --subscription {subscription_id}"

            try:
                args = shlex.split(command)
            except ValueError as e:
                return f"Error: Invalid command syntax: {e}"

            try:
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_SECONDS,
                    shell=False,
                )
            except subprocess.TimeoutExpired:
                return f"Error: Command timed out after {TIMEOUT_SECONDS}s."
            except FileNotFoundError:
                return "Error: Azure CLI ('az') not found on PATH."

            if result.returncode != 0:
                stderr = result.stderr.strip()[:MAX_OUTPUT_CHARS]
                return f"Error (exit {result.returncode}): {stderr}"

            output = result.stdout.strip()
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
            return output if output else "(no output)"

        _run_az_cli.__name__ = f"run_az_cli_{safe_name}"
        _run_az_cli.__doc__ = (
            f"Execute an Azure CLI command for account '{account_name}'. "
            f"Command must start with 'az '. Returns JSON output."
        )
        return _run_az_cli
