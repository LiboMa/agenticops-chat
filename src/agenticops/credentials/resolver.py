"""Account-addressed credential resolution for business/exec paths.

This module is the single resolver for SSM / SSH / kubectl / CLI / probe paths.
It REPLACES the old implicit `_active_account_var` ContextVar (which never
survived a Strands tool boundary — sync tools run under
``asyncio.to_thread`` + ``contextvars.copy_context()``, so writes were
discarded). Account is now an explicit, data-driven property of the *target*:

  explicit `account` arg → inventory lookup by host/cluster id → single-account
  default → fail-closed with an actionable error.

Hard rule (CLAUDE.md 凭证安全铁律): business paths use ONLY registered
CloudAccount credentials resolved through the provider layer. There is NO
silent ambient/local-profile fallback. A registered account whose
``credentials`` declare the ``environment`` source is the ONLY legitimate way
to use the local default chain — and that path is still identity-validated by
``providers/aws.AWSProvider.resolve_credentials`` (GetCallerIdentity).
"""

from __future__ import annotations

import logging
import os
import threading
from types import SimpleNamespace
from typing import Any

from agenticops.providers.base import get_cached_session, set_cached_session

logger = logging.getLogger(__name__)

# Bounded probe: when an instance/cluster is not in inventory, we try at most
# this many regions per account (account.regions, capped) before giving up.
_PROBE_MAX_REGIONS = 5

# Serializes the resolve-miss path (DB lookup + provider.resolve_credentials)
# so concurrent tool threads don't redundantly assume the same role.
_resolve_lock = threading.Lock()


class AccountResolutionError(RuntimeError):
    """No registered account could be resolved. The message is agent-actionable."""


# ── Error-message templates (agent reads these and self-corrects) ────────

ERR_NO_ACCOUNTS = (
    "No enabled {provider} accounts are registered. Register one (Web UI "
    "Settings → Accounts, or the `aiops` account commands) before running "
    "cloud operations. Ambient/local credentials are never used implicitly."
)
ERR_AMBIGUOUS = (
    "Multiple enabled {provider} accounts: {names}. Specify which one with "
    "account='<name>' (or scan inventory so the host/cluster can be matched to "
    "its account automatically)."
)
ERR_UNKNOWN_ACCOUNT = (
    "No enabled account matches '{ref}'. Enabled {provider} accounts: {names}."
)
ERR_RESOLVE_FAILED = (
    "Credential resolution failed for registered account '{name}' ({provider}): "
    "provider returned False (see logs — common causes: expired keys, AssumeRole "
    "denied, GetCallerIdentity account mismatch). Refusing to fall back to "
    "ambient credentials."
)


# ── Account snapshots (DetachedInstanceError-safe) ───────────────────────


def _snapshot(acct: Any) -> SimpleNamespace:
    """Detach a CloudAccount ORM row into a plain snapshot (no lazy loads)."""
    return SimpleNamespace(
        id=acct.id,
        name=acct.name,
        provider=acct.provider,
        credentials=dict(acct.credentials or {}),
        regions=list(acct.regions or []),
        labels=dict(acct.labels or {}),
        credential_source_type=getattr(acct, "credential_source_type", "") or "",
    )


def list_enabled_accounts(provider: str = "") -> list[SimpleNamespace]:
    """Return snapshots of all enabled accounts, optionally filtered by provider."""
    from agenticops.models import CloudAccount, get_db_session

    out: list[SimpleNamespace] = []
    with get_db_session() as db:
        q = db.query(CloudAccount).filter(CloudAccount.is_enabled == True)  # noqa: E712
        if provider:
            q = q.filter(CloudAccount.provider == provider)
        out = [_snapshot(a) for a in q.all()]
    return out


def get_account_snapshot(account_ref: str, provider: str = "") -> SimpleNamespace | None:
    """Match an enabled account by name first, then by credentials.account_id."""
    if not account_ref:
        return None
    ref = str(account_ref).strip()
    accounts = list_enabled_accounts(provider)
    for a in accounts:
        if a.name == ref:
            return a
    for a in accounts:
        if str(a.credentials.get("account_id") or "") == ref:
            return a
    return None


def resolve_default_account(provider: str = "aws") -> SimpleNamespace:
    """Resolve the implicit target account for single-account deployments.

    0 enabled → AccountResolutionError; exactly 1 → that account; >1 → error
    listing names (caller must pass account='<name>').
    """
    accounts = list_enabled_accounts(provider)
    if not accounts:
        raise AccountResolutionError(ERR_NO_ACCOUNTS.format(provider=provider))
    if len(accounts) == 1:
        return accounts[0]
    names = ", ".join(sorted(a.name for a in accounts))
    raise AccountResolutionError(ERR_AMBIGUOUS.format(provider=provider, names=names))


# ── Session + subprocess-env resolution ──────────────────────────────────


def _coerce_snapshot(account_ref: str | SimpleNamespace, provider: str = "aws") -> SimpleNamespace:
    """Accept a snapshot or a name/account-id string; return a snapshot."""
    if isinstance(account_ref, SimpleNamespace):
        return account_ref
    snap = get_account_snapshot(account_ref, provider)
    if snap is None:
        names = ", ".join(sorted(a.name for a in list_enabled_accounts(provider))) or "(none)"
        raise AccountResolutionError(
            ERR_UNKNOWN_ACCOUNT.format(ref=account_ref, provider=provider, names=names)
        )
    return snap


def resolve_account_session(account_ref: str | SimpleNamespace, region: str | None = None) -> Any:
    """Return an authenticated boto3 Session for a registered account.

    Fail-closed: a missing account or a provider that fails credential
    resolution raises AccountResolutionError — NEVER ambient credentials.
    Caches under both ``{provider}:{name}:{region}`` and
    ``{account_id}:{region}`` so every reader (CLI/exec/graph) shares one
    auto-refreshing session.
    """
    snap = _coerce_snapshot(account_ref)
    provider = snap.provider
    account_id = str(snap.credentials.get("account_id") or "")
    region_key = region or (snap.regions[0] if snap.regions else "")

    name_key = f"{provider}:{snap.name}:{region_key}"
    id_key = f"{account_id}:{region_key}" if account_id else ""

    cached = get_cached_session(name_key)
    if cached is None and id_key:
        cached = get_cached_session(id_key)
    if cached is not None:
        return cached

    with _resolve_lock:
        # Re-check after acquiring the lock (another thread may have resolved).
        cached = get_cached_session(name_key)
        if cached is None and id_key:
            cached = get_cached_session(id_key)
        if cached is not None:
            return cached

        from agenticops.providers import get_provider

        provider_impl = get_provider(snap)
        if not provider_impl.resolve_credentials():
            raise AccountResolutionError(
                ERR_RESOLVE_FAILED.format(name=snap.name, provider=provider)
            )
        session = provider_impl.sdk_session()
        set_cached_session(name_key, session)
        if id_key:
            set_cached_session(id_key, session)
        return session


def get_subprocess_env_for_account(
    account_ref: str | SimpleNamespace, region: str | None = None
) -> dict[str, str]:
    """Build a subprocess env carrying ONLY this registered account's creds.

    Strips all ambient AWS_* then injects the account's frozen credentials
    (+ AWS_DEFAULT_REGION when region given). No no-context ambient branch.

    NOTE: frozen-at-spawn credentials from an auto-refreshing AssumeRole
    session are fine for the short (≤30s) subprocesses here; do NOT reuse this
    env for long-lived processes — re-resolve instead.
    """
    session = resolve_account_session(account_ref, region)
    frozen = session.get_credentials().get_frozen_credentials()
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env["AWS_ACCESS_KEY_ID"] = frozen.access_key
    env["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
    if frozen.token:
        env["AWS_SESSION_TOKEN"] = frozen.token
    if region:
        env["AWS_DEFAULT_REGION"] = region
    return env


# ── Inventory-driven target → account discovery ──────────────────────────


def _matches_instance_id(resource_id: str, instance_id: str) -> bool:
    """resource_id may be the short id or an ARN ('...:instance/i-...')."""
    if resource_id == instance_id:
        return True
    return resource_id.endswith(f"instance/{instance_id}")


def find_instance_account(
    instance_id: str, region_hint: str = ""
) -> tuple[SimpleNamespace, str] | None:
    """Locate the account+region owning an EC2 instance.

    1) Inventory: CloudResource (provider='aws', EC2) whose resource_id matches.
    2) Probe (hacker-style): describe-instances across enabled AWS accounts ×
       regions; first hit wins. Bounded and logged.
    """
    from agenticops.models import CloudAccount, CloudResource, get_db_session

    # 1) Inventory lookup.
    with get_db_session() as db:
        rows = (
            db.query(CloudResource, CloudAccount)
            .join(CloudAccount, CloudResource.account_id == CloudAccount.id)
            .filter(
                CloudAccount.is_enabled == True,  # noqa: E712
                CloudResource.provider == "aws",
                CloudResource.resource_type == "EC2",
            )
            .all()
        )
        for res, acct in rows:
            if _matches_instance_id(res.resource_id, instance_id):
                logger.info(
                    "find_instance_account: %s matched inventory account=%s region=%s",
                    instance_id, acct.name, res.region,
                )
                return _snapshot(acct), res.region

    # 2) Probe enabled AWS accounts.
    from botocore.exceptions import ClientError

    for snap in list_enabled_accounts("aws"):
        regions = [region_hint] if region_hint else list(snap.regions[:_PROBE_MAX_REGIONS])
        for region in regions:
            if not region:
                continue
            try:
                session = resolve_account_session(snap, region)
                ec2 = session.client("ec2", region_name=region)
                ec2.describe_instances(InstanceIds=[instance_id])
                logger.info(
                    "find_instance_account: %s found via probe account=%s region=%s",
                    instance_id, snap.name, region,
                )
                return snap, region
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in ("InvalidInstanceID.NotFound", "InvalidInstanceID.Malformed"):
                    continue
                logger.debug(
                    "find_instance_account probe error account=%s region=%s: %s",
                    snap.name, region, code,
                )
                continue
            except AccountResolutionError:
                break  # this account can't resolve — skip its regions
            except Exception:
                logger.debug(
                    "find_instance_account probe failed account=%s region=%s",
                    snap.name, region, exc_info=True,
                )
                continue
    return None


def find_cluster_account(
    cluster_name: str, region_hint: str = ""
) -> tuple[SimpleNamespace, str] | None:
    """Locate the account+region owning an EKS cluster (inventory, then probe)."""
    from agenticops.models import CloudAccount, CloudResource, get_db_session

    with get_db_session() as db:
        rows = (
            db.query(CloudResource, CloudAccount)
            .join(CloudAccount, CloudResource.account_id == CloudAccount.id)
            .filter(
                CloudAccount.is_enabled == True,  # noqa: E712
                CloudResource.provider == "aws",
                CloudResource.resource_type == "EKS",
            )
            .all()
        )
        for res, acct in rows:
            if res.resource_id == cluster_name or res.name == cluster_name:
                logger.info(
                    "find_cluster_account: %s matched inventory account=%s region=%s",
                    cluster_name, acct.name, res.region,
                )
                return _snapshot(acct), res.region

    from botocore.exceptions import ClientError

    for snap in list_enabled_accounts("aws"):
        regions = [region_hint] if region_hint else list(snap.regions[:_PROBE_MAX_REGIONS])
        for region in regions:
            if not region:
                continue
            try:
                session = resolve_account_session(snap, region)
                eks = session.client("eks", region_name=region)
                eks.describe_cluster(name=cluster_name)
                logger.info(
                    "find_cluster_account: %s found via probe account=%s region=%s",
                    cluster_name, snap.name, region,
                )
                return snap, region
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in ("ResourceNotFoundException", "NotFoundException"):
                    continue
                continue
            except AccountResolutionError:
                break
            except Exception:
                logger.debug(
                    "find_cluster_account probe failed account=%s region=%s",
                    snap.name, region, exc_info=True,
                )
                continue
    return None


def get_instance_ips(instance_id: str) -> dict | None:
    """Return {'private_ip':..., 'public_ip':...} from inventory, or None."""
    from agenticops.models import CloudResource, get_db_session

    with get_db_session() as db:
        rows = (
            db.query(CloudResource)
            .filter(
                CloudResource.provider == "aws",
                CloudResource.resource_type == "EC2",
            )
            .all()
        )
        for res in rows:
            if _matches_instance_id(res.resource_id, instance_id):
                raw = res.raw_data or {}
                priv = raw.get("private_ip")
                pub = raw.get("public_ip")
                if priv or pub:
                    return {"private_ip": priv, "public_ip": pub}
                return None
    return None


def find_ssh_account_for_host(host_or_ip: str) -> SimpleNamespace | None:
    """Match a registered SSH-provider account by host/IP or name."""
    if not host_or_ip:
        return None
    ref = str(host_or_ip).strip()
    for snap in list_enabled_accounts("ssh"):
        creds = snap.credentials or {}
        if creds.get("host") == ref or snap.name == ref or creds.get("name") == ref:
            return snap
    return None
