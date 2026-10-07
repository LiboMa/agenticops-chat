"""Parallel multi-account scan engine."""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

from agenticops.scanner.commands import PROVIDER_COMMANDS, AWS_GLOBAL_COMMANDS
from agenticops.scanner.parsers import PARSER_RESOURCE_TYPE, parse_cli_output_checked

logger = logging.getLogger(__name__)


@dataclass
class AccountScanResult:
    account_id: int
    account_name: str
    provider: str
    resources_found: int = 0
    resources_updated: int = 0
    regions_scanned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # (resource_type, region) units whose listing was complete; only these may mark rows absent
    complete_units: list[tuple[str, str]] = field(default_factory=list)
    resources_absent: int = 0


@dataclass
class ScanResult:
    accounts: list[AccountScanResult] = field(default_factory=list)
    total_found: int = 0
    total_updated: int = 0
    duration_s: float = 0.0


def _load_accounts(account_ids: list[int] | None = None) -> list:
    """Load enabled CloudAccounts from DB, return as detached snapshots."""
    from agenticops.models import CloudAccount, get_db_session
    with get_db_session() as db:
        query = db.query(CloudAccount).filter(CloudAccount.is_enabled == True)  # noqa: E712
        if account_ids:
            query = query.filter(CloudAccount.id.in_(account_ids))
        accounts = query.all()
        return [
            SimpleNamespace(
                id=a.id, name=a.name, provider=a.provider,
                credentials=dict(a.credentials or {}),
                regions=list(a.regions or []), labels=dict(a.labels or {}),
            )
            for a in accounts
        ]


def _get_provider_and_tool(acct) -> tuple | None:
    """Resolve provider and CLI tool. Returns (provider, cli_tool) or None."""
    from agenticops.providers.base import get_provider
    try:
        provider = get_provider(acct)
        if provider.resolve_credentials():
            return provider, provider.cli_tool()
    except Exception as e:
        logger.warning("Failed to init provider for %s: %s", acct.name, e)
    return None


def _save_resources(account_id: int, provider: str, resources: list[dict]) -> tuple[int, int]:
    """Save resources to DB. Returns (created, updated)."""
    if not resources:
        return 0, 0
    from agenticops.tools.metadata_tools import save_resources
    result = save_resources(json.dumps(resources), account_id=account_id, provider=provider)
    if not result.startswith("Saved "):
        raise RuntimeError(result)  # the caller must not mark anything absent after a failed save
    created = updated = 0
    if "Saved" in result:
        m = re.search(r"Saved (\d+) new.*updated (\d+)", result)
        if m:
            created, updated = int(m.group(1)), int(m.group(2))
    return created, updated


def scan_one_account(
    acct,
    cli_tool,
    focus: str = "all",
    regions: list[str] | None = None,
) -> tuple[AccountScanResult, list[dict]]:
    """Scan a single account. Returns (result, resources_list).

    Design note: returns the collected resources so the caller can persist
    them via _save_resources, fixing the original gap where resources were
    collected but never saved.
    """
    result = AccountScanResult(
        account_id=acct.id,
        account_name=acct.name,
        provider=acct.provider,
    )

    commands_map = PROVIDER_COMMANDS.get(acct.provider)
    if not commands_map:
        result.errors.append(f"No command map for provider '{acct.provider}'")
        return result, []

    if focus == "all":
        categories = list(commands_map.keys())
    else:
        categories = [c.strip() for c in focus.split(",") if c.strip() in commands_map]

    scan_regions = regions or acct.regions or ["us-east-1"]
    result.regions_scanned = list(scan_regions)
    all_resources: list[dict] = []
    global_done: set[str] = set()

    for category in categories:
        for parser_key, cmd_template in commands_map.get(category, []):
            if parser_key in AWS_GLOBAL_COMMANDS:
                if parser_key in global_done:
                    continue
                global_done.add(parser_key)
                try:
                    raw = cli_tool(command=cmd_template)
                    parsed, complete = parse_cli_output_checked(parser_key, raw, "global")
                    all_resources.extend(parsed)
                    if complete:
                        result.complete_units.append((PARSER_RESOURCE_TYPE[parser_key], "global"))
                except Exception as e:
                    result.errors.append(f"{parser_key}: {e}")
                continue

            for region in scan_regions:
                cmd = cmd_template.format(region=region)
                try:
                    raw = cli_tool(command=cmd)
                    parsed, complete = parse_cli_output_checked(parser_key, raw, region)
                    all_resources.extend(parsed)
                    if complete:
                        result.complete_units.append((PARSER_RESOURCE_TYPE[parser_key], region))
                except Exception as e:
                    result.errors.append(f"{parser_key}/{region}: {e}")

    result.resources_found = len(all_resources)
    return result, all_resources


def _mark_absent(account_pk: int, complete_units: list[tuple[str, str]], seen: set[str], now: datetime,
                 started: datetime) -> int:
    """Mark absent the aws rows of each complete (resource_type, region) unit that this scan did not see.

    seen is the whole account's scan: the unique key ignores type and region, so a same-named resource in
    another region shares one row. ARN rows are never marked: no W2 parser emits an ARN, so they were
    written by another path and this listing proves nothing about them. Never deletes. A row some writer
    touched after this listing started (scanned_at >= started) is left alone: this scan's seen set is stale
    for it."""
    from sqlalchemy import func, or_

    from agenticops.models import CloudResource, get_db_session
    from agenticops.services.inventory import mark_unseen_absent

    marked = 0
    with get_db_session() as s:
        for resource_type, region in complete_units:
            marked += mark_unseen_absent(
                s, account_id=account_pk, provider="aws", resource_type=resource_type, seen=seen, now=now,
                criteria=(CloudResource.region == region, func.substr(CloudResource.resource_id, 1, 4) != "arn:",
                          or_(CloudResource.scanned_at.is_(None), CloudResource.scanned_at < started)),
            )
    return marked


async def scan_accounts_parallel(
    account_ids: list[int] | None = None,
    focus: str = "all",
    regions: list[str] | None = None,
) -> ScanResult:
    """Scan multiple accounts in parallel using their CLI tools."""
    start = time.time()
    accounts = _load_accounts(account_ids)

    if not accounts:
        return ScanResult(duration_s=time.time() - start)

    account_tools: list[tuple] = []
    for acct in accounts:
        pair = _get_provider_and_tool(acct)
        if pair:
            _, cli_tool = pair
            account_tools.append((acct, cli_tool))
        else:
            logger.warning("Skipping account %s: credentials failed", acct.name)

    if not account_tools:
        return ScanResult(duration_s=time.time() - start)

    async def _scan_and_save(acct, cli_tool):
        started = datetime.now(timezone.utc)
        acct_result, resources = await asyncio.to_thread(
            scan_one_account, acct, cli_tool, focus, regions
        )
        if resources:
            try:
                created, updated = await asyncio.to_thread(
                    _save_resources, acct.id, acct.provider, resources
                )
            except RuntimeError as e:
                acct_result.errors.append(f"save: {e}")
                return acct_result  # nothing is marked absent after a failed save
            acct_result.resources_updated = updated
        if acct_result.complete_units:
            now = datetime.now(timezone.utc)
            seen = {r["resource_id"] for r in resources}
            try:
                acct_result.resources_absent = await asyncio.to_thread(
                    _mark_absent, acct.id, acct_result.complete_units, seen, now, started
                )
            except Exception as e:
                logger.warning("scan %s: absent marking failed: %s", acct.name, e)
                acct_result.errors.append(f"absent: {e}")
        return acct_result

    results = await asyncio.gather(*[
        _scan_and_save(acct, tool) for acct, tool in account_tools
    ])

    scan_result = ScanResult(
        accounts=list(results),
        total_found=sum(r.resources_found for r in results),
        total_updated=sum(r.resources_updated for r in results),
        duration_s=round(time.time() - start, 2),
    )
    return scan_result
