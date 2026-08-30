"""Deterministic cloud security posture collectors (zero LLM).

All AWS calls go through the provider layer (aws_tools._get_client) so each
account uses its own target credentials — never ambient. Every source is
fail-soft: on error it logs a WARNING and returns [], never aborting the round.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STALE_KEY_DAYS = 90
SENSITIVE_PORTS = {22: "cis-4.1", 3389: "cis-4.2"}  # SSH / RDP


@dataclass
class PostureFinding:
    category: str        # iam | network | data | logging
    control_id: str      # CIS control this violates, e.g. "cis-1.3"
    resource_id: str
    resource_type: str
    raw_check: str
    severity_hint: str = "medium"


def _get_client(service: str, region: str, account: str = ""):
    """Provider-layer boto3 client for the target account (never ambient)."""
    from agenticops.tools.aws_tools import _get_client as _aws_get_client
    return _aws_get_client(service, region, account)


def _age_days(ts: str) -> float | None:
    """Age in days of an ISO8601 timestamp; None if unparseable/N/A."""
    if not ts or ts in ("N/A", "no_information", "not_supported"):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


def collect_iam_findings(account: str, region: str = "us-east-1") -> list[PostureFinding]:
    """IAM credential-report checks: no-MFA console users (1.10), stale keys
    (1.3), root access key (1.4). Fail-soft."""
    out: list[PostureFinding] = []
    try:
        iam = _get_client("iam", region, account)
        try:
            iam.generate_credential_report()
        except Exception:
            pass  # already generating / exists — get_credential_report still works
        content = iam.get_credential_report().get("Content", b"")
        text = content.decode() if isinstance(content, (bytes, bytearray)) else str(content)
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            user = row.get("user", "")
            is_root = user == "<root_account>"
            if is_root and row.get("access_key_1_active", "false") == "true":
                out.append(PostureFinding("iam", "cis-1.4", user, "IAMRoot",
                                          "root account has an active access key", "high"))
            if is_root:
                continue
            if row.get("password_enabled") == "true" and row.get("mfa_active") == "false":
                out.append(PostureFinding("iam", "cis-1.10", user, "IAMUser",
                                          "console user without MFA", "high"))
            age = _age_days(row.get("access_key_1_last_rotated", ""))
            if row.get("access_key_1_active") == "true" and age is not None and age > STALE_KEY_DAYS:
                out.append(PostureFinding("iam", "cis-1.3", user, "IAMUser",
                                          f"access key not rotated in {int(age)} days"))
    except Exception as e:  # fail-soft
        logger.warning("collect_iam_findings failed for %s: %s", account, e)
        return []
    return out


def collect_posture(account: str) -> list[PostureFinding]:
    """Run every deterministic source, fail-soft, and aggregate."""
    findings: list[PostureFinding] = []
    for fn in (collect_iam_findings, collect_network_findings,
               collect_data_findings, collect_logging_findings):
        try:
            findings.extend(fn(account))
        except Exception as e:
            logger.warning("posture source %s failed for %s: %s",
                           getattr(fn, "__name__", "?"), account, e)
    return findings


def collect_network_findings(account: str) -> list[PostureFinding]:
    return []


def collect_data_findings(account: str) -> list[PostureFinding]:
    return []


def collect_logging_findings(account: str) -> list[PostureFinding]:
    return []
