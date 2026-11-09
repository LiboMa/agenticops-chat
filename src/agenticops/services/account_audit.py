"""Audit rows for cloud-account changes (2026-11-09: a region edit dropped an account's stored key pair and no row
recorded it). Create, update and delete through the Web API and the agent tools each write one `audit_logs` row in
the caller's transaction. A row carries the account's plain fields and whether secrets are stored, before and after —
never a secret value, never the encrypted blob."""
from __future__ import annotations

from typing import Any

from agenticops.audit.service import AuditService, EntityTypes
from agenticops.credentials.store import audit_view, is_sensitive_key, merge_credentials


def snapshot(account: Any) -> dict:
    view = audit_view(account.credentials)
    return {"name": account.name, "provider": account.provider,
            "credential_source_type": account.credential_source_type,
            "regions": list(account.regions or []), "labels": dict(account.labels or {}),
            "is_enabled": bool(account.is_enabled),
            "credentials": view["fields"], "stored_secrets": view["stored_secrets"]}


def secrets_change(before: dict | None, after: dict | None, incoming: dict | None = None) -> str:
    """kept | replaced | added | removed | none — from the stored credentials before and after an edit and what the
    edit sent (a new secret value counts as replaced, without comparing values)."""
    had, has = audit_view(before)["stored_secrets"], audit_view(after)["stored_secrets"]
    if any(is_sensitive_key(k) for k in merge_credentials(None, incoming)):
        return "replaced" if had else "added"
    if had and not has:
        return "removed"
    return "kept" if had else "none"


def record(session: Any, action: str, account: Any, actor: Any, *, via: str, before: dict | None = None,
           after: dict | None = None, secrets: str | None = None) -> None:
    details: dict = {"via": via}
    if secrets:
        details["secrets"] = secrets
    AuditService.log(action, EntityTypes.ACCOUNT, str(account.id), entity_name=account.name, actor=actor.key,
                     user_id=actor.user_id, details=details, old_values=before, new_values=after, session=session)
