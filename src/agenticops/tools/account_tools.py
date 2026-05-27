"""Cloud Account management tools — Chat/CLI interface.

Manage cloud accounts (AWS/Azure/GCP) via natural language.
Sensitive credentials (AK/SK, role_arn) are masked on read, only updatable.
"""

from __future__ import annotations

import json
import logging
from strands import tool

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {"access_key_id", "secret_access_key", "session_token", "role_arn", "external_id", "client_secret"}


def _mask_credentials(creds: dict) -> dict:
    """Mask sensitive credential fields — show last 4 chars only."""
    masked = {}
    for k, v in creds.items():
        if k.lower() in _SENSITIVE_KEYS or any(s in k.lower() for s in ("secret", "token", "key", "password")):
            masked[k] = f"****{str(v)[-4:]}" if v and len(str(v)) >= 4 else "****"
        else:
            masked[k] = v
    return masked


@tool
def list_cloud_accounts() -> str:
    """List all configured cloud accounts with masked credentials.

    Returns:
        Formatted list of accounts with provider, regions, status.
    """
    from agenticops.models import CloudAccount, get_db_session

    with get_db_session() as session:
        accounts = session.query(CloudAccount).order_by(CloudAccount.name).all()

    if not accounts:
        return "No cloud accounts configured. Use add_cloud_account() to add one."

    lines = [f"Cloud Accounts ({len(accounts)}):"]
    for a in accounts:
        status = "enabled" if a.is_enabled else "disabled"
        icon = "✓" if a.is_enabled else "○"
        regions = ", ".join(a.regions[:3]) if a.regions else "all"
        if len(a.regions) > 3:
            regions += f" (+{len(a.regions) - 3})"
        lines.append(f"\n  {icon} [{a.id}] {a.name}")
        lines.append(f"    Provider: {a.provider} | Regions: {regions} | Status: {status}")
        if a.credentials:
            masked = _mask_credentials(a.credentials)
            cred_str = ", ".join(f"{k}={v}" for k, v in list(masked.items())[:3])
            lines.append(f"    Credentials: {cred_str}")

    return "\n".join(lines)


@tool
def add_cloud_account(
    name: str,
    provider: str,
    credentials_json: str,
    regions: str = "",
) -> str:
    """Add a new cloud account.

    Args:
        name: Account name (e.g., 'prod-us', 'staging-sg').
        provider: Cloud provider — aws, azure, gcp, alicloud.
        credentials_json: JSON with credentials. For AWS: {"role_arn": "...", "external_id": "..."} or {"access_key_id": "...", "secret_access_key": "..."}.
        regions: Comma-separated regions (e.g., 'us-east-1,ap-southeast-1'). Empty = all.

    Returns:
        Confirmation with masked credentials.
    """
    from agenticops.models import CloudAccount, get_db_session

    valid_providers = {"aws", "azure", "gcp", "alicloud"}
    if provider not in valid_providers:
        return f"Invalid provider '{provider}'. Valid: {', '.join(sorted(valid_providers))}"

    try:
        creds = json.loads(credentials_json) if isinstance(credentials_json, str) else credentials_json
    except json.JSONDecodeError as e:
        return f"Invalid credentials_json: {e}"

    region_list = [r.strip() for r in regions.split(",") if r.strip()] if regions else []

    with get_db_session() as session:
        existing = session.query(CloudAccount).filter_by(name=name).first()
        if existing:
            return f"Account '{name}' already exists (ID: {existing.id}). Use update_cloud_account() to modify."

        account = CloudAccount(
            name=name,
            provider=provider,
            credentials=creds,
            regions=region_list,
            is_enabled=True,
        )
        session.add(account)
        session.flush()
        aid = account.id

    masked = _mask_credentials(creds)
    return f"Account '{name}' created (ID: {aid}, provider: {provider}). Credentials: {masked}"


@tool
def update_cloud_account(
    name: str,
    credentials_json: str = "",
    regions: str = "",
    enabled: str = "",
) -> str:
    """Update an existing cloud account's credentials, regions, or status.

    Only provided fields are updated. Credentials are write-only (masked on read).

    Args:
        name: Account name to update.
        credentials_json: New credentials JSON (replaces existing). Empty = no change.
        regions: New comma-separated regions. Empty = no change.
        enabled: 'true' or 'false'. Empty = no change.

    Returns:
        Confirmation with masked credentials.
    """
    from agenticops.models import CloudAccount, get_db_session

    with get_db_session() as session:
        account = session.query(CloudAccount).filter_by(name=name).first()
        if not account:
            return f"Account '{name}' not found."

        updated = []
        if credentials_json:
            try:
                creds = json.loads(credentials_json) if isinstance(credentials_json, str) else credentials_json
            except json.JSONDecodeError as e:
                return f"Invalid credentials_json: {e}"
            account.credentials = creds
            updated.append("credentials")

        if regions:
            account.regions = [r.strip() for r in regions.split(",") if r.strip()]
            updated.append("regions")

        if enabled:
            account.is_enabled = enabled.lower() in ("true", "1", "yes")
            updated.append("enabled")

        if not updated:
            return "Nothing to update. Provide credentials_json, regions, or enabled."

    return f"Account '{name}' updated: {', '.join(updated)}."


@tool
def remove_cloud_account(name: str) -> str:
    """Remove a cloud account.

    Args:
        name: Account name to remove.

    Returns:
        Confirmation.
    """
    from agenticops.models import CloudAccount, get_db_session

    with get_db_session() as session:
        account = session.query(CloudAccount).filter_by(name=name).first()
        if not account:
            return f"Account '{name}' not found."
        session.delete(account)

    return f"Account '{name}' removed."
