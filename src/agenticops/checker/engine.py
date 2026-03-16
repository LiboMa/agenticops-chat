"""Parallel multi-account agentic health check engine."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AccountCheckResult:
    account_id: int
    account_name: str
    provider: str
    agent_output: str = ""
    issues_created: int = 0
    regions_checked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0


@dataclass
class CheckResult:
    accounts: list[AccountCheckResult] = field(default_factory=list)
    total_issues: int = 0
    duration_s: float = 0.0


def _parse_issue_count(output: str) -> int:
    """Extract issue count from detect agent output.

    Best-effort parser — the authoritative issue count lives in the DB.
    Handles several LLM output patterns.
    """
    # Pattern 1: "X issues created/found" or "X health issues"
    m = re.search(r"(\d+)\s+(?:issues?\s+(?:created|found)|health\s+issues?)", output, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Pattern 2: "Found/Detected X issues"
    m = re.search(r"(?:found|detected|identified|discovered)\s+(\d+)\s+issues?", output, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Pattern 3: count individual "Created HealthIssue" lines
    count = len(re.findall(r"[Cc]reated?\s+[Hh]ealth\s*[Ii]ssue", output))
    return count


def _check_one_account(acct, cli_tool, session, scope, deep) -> AccountCheckResult:
    """Spawn a detect agent for one account, invoke it, parse results."""
    from agenticops.agents.detect_agent import _build_detect_agent_for_account
    from agenticops.agents.preamble import invoke_with_retry

    start = time.time()
    result = AccountCheckResult(
        account_id=acct.id,
        account_name=acct.name,
        provider=acct.provider,
        regions_checked=list(acct.regions or []),
    )

    try:
        agent = _build_detect_agent_for_account(
            acct_name=acct.name,
            acct_id=acct.id,
            cli_tool=cli_tool,
            session=session,
        )
        prompt = f"Check health for account '{acct.name}'. Scope={scope}. Deep={deep}."
        output = str(invoke_with_retry(agent, prompt))
        result.agent_output = output
        result.issues_created = _parse_issue_count(output)
    except Exception as e:
        result.errors.append(str(e))

    result.duration_s = round(time.time() - start, 2)
    return result


async def check_accounts_parallel(
    account_ids: list[int] | None = None,
    scope: str = "all",
    deep: bool = False,
) -> CheckResult:
    """Run detect agents in parallel across all enabled accounts.

    Args:
        account_ids: Optional list of account DB IDs to check. None = all enabled.
        scope: Resource type filter (e.g., 'EC2', 'RDS', 'security', 'all').
        deep: If True, pull detailed metrics/logs even for healthy resources.

    Returns:
        CheckResult with per-account results and aggregate issue count.
    """
    start = time.time()

    # Reuse account loading from scanner
    from agenticops.scanner.engine import _load_accounts, _get_provider_and_tool

    accounts = _load_accounts(account_ids)

    if not accounts:
        return CheckResult(duration_s=round(time.time() - start, 2))

    account_tools = []
    for acct in accounts:
        pair = _get_provider_and_tool(acct)
        if pair:
            provider, cli_tool = pair
            account_tools.append((acct, cli_tool, provider.sdk_session()))
        else:
            logger.warning("Skipping account %s: credentials failed", acct.name)

    if not account_tools:
        return CheckResult(duration_s=round(time.time() - start, 2))

    results = await asyncio.gather(*[
        asyncio.to_thread(_check_one_account, acct, cli_tool, session, scope, deep)
        for acct, cli_tool, session in account_tools
    ])

    return CheckResult(
        accounts=list(results),
        total_issues=sum(r.issues_created for r in results),
        duration_s=round(time.time() - start, 2),
    )
