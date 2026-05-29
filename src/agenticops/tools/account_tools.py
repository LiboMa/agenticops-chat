"""Cloud Account management tools — Chat/CLI interface.

Manage cloud accounts (AWS/Azure/GCP) via natural language.
Credentials are encrypted at rest via CredentialStore.
Sensitive fields are masked on read, only updatable.
"""

from __future__ import annotations

import json
import logging
from strands import tool

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {"access_key_id", "secret_access_key", "session_token", "role_arn", "external_id", "client_secret"}

# Valid credential source types
_VALID_SOURCE_TYPES = {"environment", "assume_role", "profile", "static_keys"}


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
        source_type = getattr(a, "credential_source_type", "environment") or "environment"
        lines.append(f"\n  {icon} [{a.id}] {a.name}")
        lines.append(f"    Provider: {a.provider} | Source: {source_type} | Regions: {regions} | Status: {status}")
        if a.credentials:
            # Show non-encrypted fields only (role_arn, profile_name, etc.)
            display_creds = {k: v for k, v in a.credentials.items() if k != "_encrypted"}
            masked = _mask_credentials(display_creds)
            if masked:
                cred_str = ", ".join(f"{k}={v}" for k, v in list(masked.items())[:3])
                lines.append(f"    Credentials: {cred_str}")

    return "\n".join(lines)


@tool
def add_cloud_account(
    name: str,
    provider: str,
    credentials_json: str,
    regions: str = "",
    credential_source_type: str = "",
) -> str:
    """Add a new cloud account.

    Args:
        name: Account name (e.g., 'prod-us', 'staging-sg').
        provider: Cloud provider — aws, azure, gcp, alicloud.
        credentials_json: JSON with credentials. For AWS: {"role_arn": "...", "external_id": "..."} or {"access_key_id": "...", "secret_access_key": "..."}.
        regions: Comma-separated regions (e.g., 'us-east-1,ap-southeast-1'). Empty = all.
        credential_source_type: How credentials are resolved — 'environment', 'assume_role', 'profile', or 'static_keys'. Auto-detected if empty.

    Returns:
        Confirmation with masked credentials.
    """
    from agenticops.models import CloudAccount, get_db_session
    from agenticops.credentials.store import get_credential_store

    valid_providers = {"aws", "azure", "gcp", "alicloud"}
    if provider not in valid_providers:
        return f"Invalid provider '{provider}'. Valid: {', '.join(sorted(valid_providers))}"

    try:
        creds = json.loads(credentials_json) if isinstance(credentials_json, str) else credentials_json
    except json.JSONDecodeError as e:
        return f"Invalid credentials_json: {e}"

    region_list = [r.strip() for r in regions.split(",") if r.strip()] if regions else []

    # Auto-detect credential_source_type if not specified
    source_type = credential_source_type
    if not source_type:
        if creds.get("role_arn"):
            source_type = "assume_role"
        elif creds.get("profile_name"):
            source_type = "profile"
        elif creds.get("access_key_id"):
            source_type = "static_keys"
        else:
            source_type = "environment"

    if source_type not in _VALID_SOURCE_TYPES:
        return f"Invalid credential_source_type '{source_type}'. Valid: {', '.join(sorted(_VALID_SOURCE_TYPES))}"

    # Encrypt sensitive credentials before storage
    store = get_credential_store()
    stored_creds = store.encrypt_credentials(creds)

    with get_db_session() as session:
        existing = session.query(CloudAccount).filter_by(name=name).first()
        if existing:
            return f"Account '{name}' already exists (ID: {existing.id}). Use update_cloud_account() to modify."

        account = CloudAccount(
            name=name,
            provider=provider,
            credential_source_type=source_type,
            credentials=stored_creds,
            regions=region_list,
            is_enabled=True,
        )
        session.add(account)
        session.flush()
        aid = account.id

    masked = _mask_credentials(creds)
    backend_name = store.backend_name
    return (
        f"Account '{name}' created (ID: {aid}, provider: {provider}, source: {source_type}).\n"
        f"Credentials: {masked}\n"
        f"Encryption: {backend_name}"
    )


@tool
def update_cloud_account(
    name: str,
    credentials_json: str = "",
    regions: str = "",
    enabled: str = "",
    credential_source_type: str = "",
) -> str:
    """Update an existing cloud account's credentials, regions, or status.

    Only provided fields are updated. Credentials are write-only (masked on read).

    Args:
        name: Account name to update.
        credentials_json: New credentials JSON (replaces existing). Empty = no change.
        regions: New comma-separated regions. Empty = no change.
        enabled: 'true' or 'false'. Empty = no change.
        credential_source_type: New source type. Empty = no change.

    Returns:
        Confirmation with masked credentials.
    """
    from agenticops.models import CloudAccount, get_db_session
    from agenticops.credentials.store import get_credential_store
    from agenticops.credentials.session_factory import get_session_factory

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
            # Encrypt before storage
            store = get_credential_store()
            account.credentials = store.encrypt_credentials(creds)
            updated.append("credentials")

        if credential_source_type:
            if credential_source_type not in _VALID_SOURCE_TYPES:
                return f"Invalid source type '{credential_source_type}'. Valid: {', '.join(sorted(_VALID_SOURCE_TYPES))}"
            account.credential_source_type = credential_source_type
            updated.append("credential_source_type")

        if regions:
            account.regions = [r.strip() for r in regions.split(",") if r.strip()]
            updated.append("regions")

        if enabled:
            account.is_enabled = enabled.lower() in ("true", "1", "yes")
            updated.append("enabled")

        if not updated:
            return "Nothing to update. Provide credentials_json, regions, enabled, or credential_source_type."

    # Invalidate cached session
    get_session_factory().invalidate(name)
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
