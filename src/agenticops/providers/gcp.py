"""GCP CloudProvider implementation."""

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
    import google.auth as google_auth
    from google.oauth2 import service_account as google_service_account
    _HAS_GOOGLE = True
except ImportError:
    google_auth = None  # type: ignore[assignment]
    google_service_account = None  # type: ignore[assignment]
    _HAS_GOOGLE = False

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30


class GCPProvider(CloudProvider):
    """GCP cloud provider using google-auth SDK and gcloud CLI."""

    @property
    def provider_type(self) -> str:
        return "gcp"

    def resolve_credentials(self) -> bool:
        """Resolve GCP credentials through the following chain:

        1. credentials.service_account_key → from_service_account_info
        2. GOOGLE_* env vars → Application Default Credentials
        3. empty → google.auth.default()
        """
        creds = self.account.credentials or {}
        credential = None

        if not _HAS_GOOGLE:
            logger.warning(
                "google-auth not installed; GCP provider will rely on gcloud CLI only"
            )
            self._credential = None
            return True

        # 1. Service account key (dict)
        sa_key = creds.get("service_account_key")
        if sa_key and isinstance(sa_key, dict):
            try:
                credential = google_service_account.Credentials.from_service_account_info(sa_key)
            except Exception as e:
                logger.error("GCP service account key failed for %s: %s", self.account.name, e)
                return False

        # 2 & 3. ADC or default chain
        else:
            try:
                credential, project = google_auth.default()
            except Exception as e:
                logger.error("GCP default credentials failed for %s: %s", self.account.name, e)
                return False

        cache_key = f"gcp:{self.account.name}:default"
        set_cached_session(cache_key, credential)
        self._credential = credential
        return True

    def sdk_session(self) -> Any:
        """Return the Google auth credential object."""
        if not hasattr(self, "_credential"):
            self.resolve_credentials()
        return self._credential

    def cli_tool(self) -> Callable:
        """Return a callable that executes gcloud CLI commands for this account.

        Auto-appends --project and --format json.
        """
        account_name = self.account.name
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", account_name)
        creds = self.account.credentials or {}
        project_id = creds.get("project_id", "")

        def _run_gcloud_cli(command: str) -> str:
            command = command.strip()

            if not command.startswith("gcloud "):
                return "Error: Command must start with 'gcloud '."

            # Shell injection check
            for dangerous in ["|", ";", "&&", "$(", "`", ">", "<"]:
                if dangerous in command:
                    return f"Error: Shell operator '{dangerous}' is not allowed."

            # Auto-append --format json
            if "--format" not in command:
                command = f"{command} --format json"

            # Auto-append --project
            if project_id and "--project" not in command:
                command = f"{command} --project {project_id}"

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
                return "Error: Google Cloud CLI ('gcloud') not found on PATH."

            if result.returncode != 0:
                stderr = result.stderr.strip()
                return f"Error (exit {result.returncode}): {stderr}"

            output = result.stdout.strip()
            from agenticops.config import settings
            limit = settings.cli_max_output_chars
            if limit > 0 and len(output) > limit:
                output = output[:limit] + "\n... (truncated)"
            return output if output else "(no output)"

        _run_gcloud_cli.__name__ = f"run_gcloud_{safe_name}"
        _run_gcloud_cli.__doc__ = (
            f"Execute a gcloud CLI command for account '{account_name}'. "
            f"Command must start with 'gcloud '. Returns JSON output.\n\n"
            f"Args:\n"
            f"    command: The gcloud CLI command to execute (must start with 'gcloud ')."
        )

        from strands import tool as strands_tool
        return strands_tool(_run_gcloud_cli)
