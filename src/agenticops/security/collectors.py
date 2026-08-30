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


def _enabled_regions(account: str) -> list[str]:
    """Enabled regions for an account, read from its CloudAccount snapshot
    (resolver.get_account_snapshot). Falls back to the configured default region
    when the account lists none."""
    try:
        from agenticops.credentials.resolver import get_account_snapshot
        snap = get_account_snapshot(account, "aws")
        if snap and snap.regions:
            return list(snap.regions)
    except Exception as e:
        logger.warning("enabled-regions lookup failed for %s: %s", account, e)
    from agenticops.config import settings
    return [settings.bedrock_region]


def _port_in_range(port: int, frm, to) -> bool:
    if frm is None or to is None:  # all ports
        return True
    try:
        return int(frm) <= port <= int(to)
    except (TypeError, ValueError):
        return False


def _rule_open_to_internet(rule: dict) -> bool:
    for r in rule.get("IpRanges", []):
        if r.get("CidrIp") == "0.0.0.0/0":
            return True
    for r in rule.get("Ipv6Ranges", []):
        if r.get("CidrIpv6") == "::/0":
            return True
    return False


def collect_network_findings(account: str) -> list[PostureFinding]:
    """SG open-surface: 0.0.0.0/0 (or ::/0) ingress to sensitive ports. Fail-soft."""
    out: list[PostureFinding] = []
    try:
        for region in _enabled_regions(account):
            ec2 = _get_client("ec2", region, account)
            for sg in ec2.describe_security_groups().get("SecurityGroups", []):
                gid = sg.get("GroupId", "")
                for rule in sg.get("IpPermissions", []):
                    if not _rule_open_to_internet(rule):
                        continue
                    proto = rule.get("IpProtocol", "-1")
                    for port, control_id in SENSITIVE_PORTS.items():
                        if proto in ("-1", "tcp") and _port_in_range(port, rule.get("FromPort"), rule.get("ToPort")):
                            out.append(PostureFinding(
                                "network", control_id, gid, "SecurityGroup",
                                f"0.0.0.0/0 ingress to port {port}", "high"))
    except Exception as e:
        logger.warning("collect_network_findings failed for %s: %s", account, e)
        return []
    return out


def _bucket_public(cfg: dict) -> bool:
    """A bucket is public-capable if any of the 4 public-access-block flags is off."""
    pab = cfg.get("PublicAccessBlockConfiguration", {})
    return not all([
        pab.get("BlockPublicAcls", False), pab.get("IgnorePublicAcls", False),
        pab.get("BlockPublicPolicy", False), pab.get("RestrictPublicBuckets", False),
    ])


def collect_data_findings(account: str) -> list[PostureFinding]:
    """S3 public access (cis-2.1) + unencrypted EBS volumes (cis-enc). Fail-soft."""
    out: list[PostureFinding] = []
    # S3 is global-ish: enumerate once via the default region client.
    try:
        from agenticops.config import settings
        s3 = _get_client("s3", settings.bedrock_region, account)
        for b in s3.list_buckets().get("Buckets", []):
            name = b.get("Name", "")
            try:
                cfg = s3.get_public_access_block(Bucket=name)
                if _bucket_public(cfg):
                    out.append(PostureFinding("data", "cis-2.1", name, "S3Bucket",
                                              "bucket public access not fully blocked", "high"))
            except Exception:
                # No PAB configured at all == public-capable.
                out.append(PostureFinding("data", "cis-2.1", name, "S3Bucket",
                                          "no public-access-block configured", "high"))
    except Exception as e:
        logger.warning("collect_data_findings(s3) failed for %s: %s", account, e)
    # EBS encryption per region.
    try:
        for region in _enabled_regions(account):
            ec2 = _get_client("ec2", region, account)
            for page in ec2.get_paginator("describe_volumes").paginate():
                for vol in page.get("Volumes", []):
                    if not vol.get("Encrypted", False):
                        out.append(PostureFinding("data", "cis-enc", vol.get("VolumeId", ""),
                                                  "EBSVolume", "volume not encrypted at rest"))
    except Exception as e:
        logger.warning("collect_data_findings(ebs) failed for %s: %s", account, e)
    return out


def collect_logging_findings(account: str) -> list[PostureFinding]:
    """CloudTrail: at least one multi-region trail actively logging (cis-3.1). Fail-soft."""
    try:
        from agenticops.config import settings
        ct = _get_client("cloudtrail", settings.bedrock_region, account)
        trails = ct.describe_trails().get("trailList", [])
        for t in trails:
            if not t.get("IsMultiRegionTrail"):
                continue
            try:
                if ct.get_trail_status(Name=t.get("TrailARN") or t.get("Name")).get("IsLogging"):
                    return []  # a compliant trail exists
            except Exception:
                continue
        return [PostureFinding("logging", "cis-3.1", "account", "CloudTrail",
                               "no multi-region trail actively logging", "high")]
    except Exception as e:
        logger.warning("collect_logging_findings failed for %s: %s", account, e)
        return []
