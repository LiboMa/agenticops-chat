"""Command audit — tool-layer ledger of write-tier command attempts (MVP-2.6.0).

record_command() is called by run_aws_cli / run_on_host / run_kubectl / run_skill_script and — through
guarded_run() — by every provider-scoped CLI tool (provider_aws_cli, provider_ssh, provider_kubectl,
provider_azure_cli, provider_gcp_cli, provider_alicloud_cli) for every write|unknown|blocked attempt
(executed, refused, blocked, error). It reads the Run Context for attribution and is FAIL-SOFT: a
failure is logged (WARNING once per process, debug afterwards) and never changes the tool's return
value. Read-only commands are deliberately not recorded (volume).
"""

from __future__ import annotations

import logging
import re
import shlex
import time
from typing import Callable, Optional

from agenticops.models import get_db_session

logger = logging.getLogger(__name__)

EXCERPT_LIMIT = 2000
VALID_OUTCOMES = {"executed", "refused", "blocked", "error"}

_warned_once = False


def _cut(value, width: int) -> Optional[str]:
    """Truncate to the column width (models.CommandAudit). PostgreSQL raises on overflow — and the
    fail-soft wrapper would then swallow it, leaving a command that ran with NO row."""
    return None if value is None else str(value)[:width]


def record_command(
    *,
    tool: str,
    tier: str,
    command: str,
    outcome: str,
    account: str = "",
    region: str = "",
    target: str = "",
    exit_code: Optional[int] = None,
    output_excerpt: str = "",
    duration_ms: int = 0,
    reason: str = "",
) -> None:
    global _warned_once
    try:
        from agenticops.config import settings
        if not getattr(settings, "command_audit_enabled", True):
            return
        if outcome not in VALID_OUTCOMES:
            outcome = "error"
        from agenticops.models import CommandAudit
        from agenticops.run_context import get_run_context
        from agenticops.security import redact_secrets

        ctx = get_run_context()
        row = CommandAudit(
            actor=_cut(ctx.actor or "system", 255), actor_user_id=ctx.actor_user_id,
            on_behalf_of=_cut(ctx.on_behalf_of, 255), agent_name=_cut(ctx.agent_name, 50),
            tool=_cut(tool, 30), tier=_cut(tier, 10), account=_cut(account or "", 100),
            region=_cut(region or "", 30), target=_cut(target or "", 200),
            command=redact_secrets(command or "")[:10000], outcome=outcome,
            reason=_cut(reason or None, 50), exit_code=exit_code,
            output_excerpt=redact_secrets(output_excerpt or "")[:EXCERPT_LIMIT], duration_ms=int(duration_ms or 0),
            trace_id=_cut(ctx.trace_id, 20), fix_plan_id=ctx.fix_plan_id, change_request_id=ctx.change_request_id,
        )
        with get_db_session() as db:
            db.add(row)
        try:
            from agenticops.audit.service import AuditService
            AuditService.maybe_prune_daily()
        except Exception:
            pass
    except Exception:
        # A permanently broken ledger must be visible once, not flood the log on every command.
        log = logger.debug if _warned_once else logger.warning
        _warned_once = True
        log("command audit write failed (tool=%s outcome=%s)", tool, outcome, exc_info=True)


def approved_plan_in_context() -> Optional[int]:
    """The Run Context's plan id when that plan is approved/executing, else None."""
    try:
        from agenticops.models import FixPlan
        from agenticops.run_context import get_run_context
        pid = get_run_context().fix_plan_id
        if not pid:
            return None
        with get_db_session() as db:
            status = db.query(FixPlan.status).filter_by(id=pid).scalar()
        return pid if status in ("approved", "executing") else None
    except Exception:
        return None


def change_required_refusal(command: str, pattern: str) -> str:
    return (
        f"This command matches the high-risk pattern '{pattern}' (config/policies.yaml change_required) and "
        f"can only run inside an approved plan. Open a change request instead: in Chat type "
        f"/change <what you want changed>, or use the Web UI Plans & Changes → New change request. "
        f"Command: {command}"
    )


def guarded_run(
    *,
    tool: str,
    tier: str,
    command: str,
    run: Callable[[], str],
    outcome_of: Callable[[str], tuple],
    account: str = "",
    region: str = "",
    target: str = "",
) -> str:
    """Run a provider CLI tool's command behind the change_required gate and the ledger.

    readonly → run() with nothing recorded. Otherwise a change_required match with no approved plan in
    the Run Context is refused (row: refused/change_required, run() never called); every other attempt
    is run and recorded with the (outcome, exit_code[, reason]) that outcome_of() reads from the reply.
    Callers keep their own blocked / confirmation handling — and its `blocked` row — BEFORE calling this.
    """
    if tier == "readonly":
        return run()
    from agenticops.services.policy_engine import get_policy_engine
    pattern = get_policy_engine().change_required_match(command)
    if pattern and approved_plan_in_context() is None:
        record_command(tool=tool, tier=tier, command=command, outcome="refused", reason="change_required",
                       account=account, region=region, target=target)
        return change_required_refusal(command, pattern)
    t0 = time.monotonic()
    text = run()
    judged = outcome_of(text)
    outcome, exit_code = judged[0], judged[1]
    reason = judged[2] if len(judged) > 2 else ""
    record_command(tool=tool, tier=tier, command=command, outcome=outcome, account=account, region=region,
                   target=target, exit_code=exit_code, output_excerpt=text, reason=reason,
                   duration_ms=int((time.monotonic() - t0) * 1000))
    return text


_CLI_EXIT_RE = re.compile(r"^Error \(exit (?:code )?(-?\d+)\)")
_CLI_FAULT_REASONS = (
    ("Error: Command timed out", "timeout"),
    ("Error: Invalid command syntax", "syntax"),
    ("Error: no resolved session", "no_session"),
    ("Error: failed to resolve credentials", "credentials"),
)


def cli_outcome(text: str) -> tuple[str, Optional[int], str]:
    """(outcome, exit_code, reason) read from a provider CLI tool's reply text.

    `Error (exit N): …` → error with that exit code (a transport's own -1 included); the tools' `Error: …`
    early returns → error, no exit code, reason timeout / syntax / cli_missing / no_session / credentials;
    anything else is the command's own stdout → executed. Text-based like run_aws_cli's _parse_exit: a
    successful command whose stdout begins with "Error:" would be labelled error (the conservative side;
    JSON output never does).
    """
    text = text or ""
    m = _CLI_EXIT_RE.match(text)
    if m:
        return "error", int(m.group(1)), ""
    if text.startswith("Error:"):
        for prefix, reason in _CLI_FAULT_REASONS:
            if text.startswith(prefix):
                return "error", None, reason
        return "error", None, ("cli_missing" if "not found on PATH" in text.split("\n", 1)[0] else "")
    return "executed", 0, ""


_GENERIC_READ_VERBS = ("list", "show", "get", "describe")
_GENERIC_WRITE_VERBS = (
    "delete", "create", "update", "set", "add", "remove", "start", "stop", "restart", "reset", "deallocate",
    "purge", "run", "exec", "apply", "scale", "attach", "detach", "revoke", "assign", "invoke", "deploy", "patch",
    "replace", "restore",
)
_GENERIC_READ_PREFIXES = tuple(f"{v}-" for v in _GENERIC_READ_VERBS)
_GENERIC_WRITE_PREFIXES = tuple(f"{v}-" for v in _GENERIC_WRITE_VERBS)


def generic_cli_tier(command: str) -> str:
    """'readonly' | 'unknown' for CLIs without a dedicated classifier (az / gcloud / aliyun).

    First verb wins: the positional tokens after the program name are walked in order and the FIRST one that
    is a verb decides — a read verb (list / show / get / describe, or `<verb>-…`) → readonly, a mutating verb
    (delete / create / update / set / start / stop / … , or `<verb>-…`) → unknown. Tokens after that verb are
    never consulted, so a resource NAMED `list` or `describe-me` behind a `delete` cannot flip a mutation to
    readonly. Option tokens are skipped; a `--opt value` option also skips its value (a value is never read as
    a verb), a `--opt=value` token is skipped alone. No verb → unknown. Never 'write' or 'blocked': those
    verdicts belong to a real classifier.
    """
    try:
        tokens = shlex.split(command or "")
    except ValueError:
        tokens = (command or "").split()
    skip_next = False
    for token in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            skip_next = "=" not in token
            continue
        word = token.lower()
        if word in _GENERIC_READ_VERBS or word.startswith(_GENERIC_READ_PREFIXES):
            return "readonly"
        if word in _GENERIC_WRITE_VERBS or word.startswith(_GENERIC_WRITE_PREFIXES):
            return "unknown"
    return "unknown"
