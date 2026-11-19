"""Deterministic cloud security posture collectors (zero LLM).

All AWS calls go through the provider layer (aws_tools._get_client) so each
account uses its own target credentials — never ambient. Every source is
fail-soft: on error it logs a WARNING and returns [], never aborting the round.

A source also says whether it could be read (MVP-2.9.0 N20): each collector takes `health`, a dict it fills as
`{source: {"ok": bool, "error": str}}` under scoring.SOURCES' names — iam, network, s3, ebs, logging.
`collect_posture_checked` returns the findings WITH that record, and scoring turns a failed source's controls into
`undetermined`. A read that was refused is never a result: a bucket whose public-access setting could not be read
is not reported as public, a trail whose status could not be read is not reported as silent — the source is
marked failed instead.
"""
from __future__ import annotations

import csv
import io
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from agenticops.security.scoring import SOURCES

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


@dataclass
class PostureCollection:
    """One account's findings and which sources could be read."""
    findings: list[PostureFinding]
    health: dict[str, dict]      # source -> {"ok": bool, "error": str}

    @property
    def failed_sources(self) -> frozenset[str]:
        return frozenset(s for s, h in self.health.items() if not h.get("ok"))

    @property
    def status(self) -> str:
        """complete | partial | failed (failed = no source could be read: there is nothing to score)."""
        failed = self.failed_sources
        if not failed:
            return "complete"
        return "failed" if failed >= SOURCES else "partial"


def failure_reason(exc: BaseException) -> str:
    """What is stored and shown about a source that failed: a refused call's error code and operation — never its
    message, which names roles and account numbers — else the exception's class and the start of its text."""
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    if code:
        operation = getattr(exc, "operation_name", "")
        return f"{code} ({operation})" if operation else str(code)
    text = str(exc).strip()
    return (f"{type(exc).__name__}: {text}" if text else type(exc).__name__)[:160]


def _ok(health: dict | None, source: str) -> None:
    if health is not None:
        health[source] = {"ok": True, "error": ""}


def _failed(health: dict | None, source: str, reason: str) -> None:
    if health is not None:
        health[source] = {"ok": False, "error": reason}


def _in_region(region: str, exc: BaseException) -> str:
    return f"{region}: {failure_reason(exc)}" if region else failure_reason(exc)


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


# IAM builds a credential report when asked (at most once in four hours) and answers «not ready» to a read made in
# the same breath — about one hourly run in four (MVP-2.9.0 N27, review). It is asked again, a few seconds apart,
# until it says the report is complete.
REPORT_ASKS, REPORT_WAIT_SECONDS = 8, 2.5
_sleep = time.sleep


def _home_region(account: str) -> str:
    """The region the account-wide sources (IAM, S3, CloudTrail) are read through: the account's own first
    region, so the call stays in the account's PARTITION. They were asked in us-east-1 / the model's region,
    where a China or GovCloud account's credentials are refused (MVP-2.9.0 N27, review)."""
    regions = _enabled_regions(account)
    if regions:
        return regions[0]
    from agenticops.config import settings
    return settings.bedrock_region


def _wait_for_credential_report(iam) -> None:
    """Ask IAM for a credential report until it is complete (bounded). A refused or failing ask is not fatal:
    the report there is — if any — is still read."""
    for ask in range(REPORT_ASKS):
        try:
            state = iam.generate_credential_report().get("State")
        except Exception:
            return
        if state not in ("STARTED", "INPROGRESS"):
            return
        if ask < REPORT_ASKS - 1:
            _sleep(REPORT_WAIT_SECONDS)


def _stale_key_days(row: dict) -> float | None:
    """The age of the oldest access key IN USE that is past the limit — either of the two a user may have. The
    second key was never looked at: a user whose key 1 is off and key 2 is 400 days old passed (review)."""
    ages = [age for n in ("1", "2")
            if row.get(f"access_key_{n}_active") == "true"
            and (age := _age_days(row.get(f"access_key_{n}_last_rotated", ""))) is not None and age > STALE_KEY_DAYS]
    return max(ages) if ages else None


def collect_iam_findings(account: str, region: str = "", health: dict | None = None) -> list[PostureFinding]:
    """IAM credential-report checks: no-MFA console users (1.10), stale keys
    (1.3), root access key (1.4). Fail-soft."""
    out: list[PostureFinding] = []
    try:
        iam = _get_client("iam", region or _home_region(account), account)
        _wait_for_credential_report(iam)
        content = iam.get_credential_report().get("Content", b"")
        text = content.decode() if isinstance(content, (bytes, bytearray)) else str(content)
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            user = row.get("user", "")
            is_root = user == "<root_account>"
            if is_root and "true" in (row.get("access_key_1_active"), row.get("access_key_2_active")):
                out.append(PostureFinding("iam", "cis-1.4", user, "IAMRoot",
                                          "root account has an active access key", "high"))
            if is_root:
                continue
            if row.get("password_enabled") == "true" and row.get("mfa_active") == "false":
                out.append(PostureFinding("iam", "cis-1.10", user, "IAMUser",
                                          "console user without MFA", "high"))
            age = _stale_key_days(row)
            if age is not None:
                out.append(PostureFinding("iam", "cis-1.3", user, "IAMUser",
                                          f"access key not rotated in {int(age)} days"))
    except Exception as e:  # fail-soft
        logger.warning("collect_iam_findings failed for %s: %s", account, e)
        _failed(health, "iam", failure_reason(e))
        return []
    _ok(health, "iam")
    return out


def collect_posture_checked(account: str) -> PostureCollection:
    """Run every deterministic source, fail-soft, and return the findings with each source's health."""
    findings: list[PostureFinding] = []
    health: dict[str, dict] = {}
    for fn, sources in ((collect_iam_findings, ("iam",)), (collect_network_findings, ("network",)),
                        (collect_data_findings, ("s3", "ebs")), (collect_logging_findings, ("logging",))):
        try:
            findings.extend(fn(account, health=health))
        except Exception as e:
            logger.warning("posture source %s failed for %s: %s",
                           getattr(fn, "__name__", "?"), account, e)
            for source in sources:
                health.setdefault(source, {"ok": False, "error": failure_reason(e)})
        for source in sources:      # a source that returned without a word was read
            health.setdefault(source, {"ok": True, "error": ""})
    return PostureCollection(findings, health)


def collect_posture(account: str) -> list[PostureFinding]:
    """The findings alone (fail-soft, aggregated) — see collect_posture_checked for which sources were read."""
    return collect_posture_checked(account).findings


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


def collect_network_findings(account: str, health: dict | None = None) -> list[PostureFinding]:
    """SG open-surface: 0.0.0.0/0 (or ::/0) ingress to sensitive ports. Fail-soft."""
    out: list[PostureFinding] = []
    region = ""
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
        # What was read before the failure is kept (N27, review): a group seen open to the world in region 1 is a
        # violation whatever happened in region 3 — thrown away, the account read «0 reachable paths». The source
        # is still marked failed: what was NOT read is not known to be clean.
        logger.warning("collect_network_findings failed for %s: %s", account, e)
        _failed(health, "network", _in_region(region, e))
        return out
    _ok(health, "network")
    return out


def _bucket_public(cfg: dict) -> bool:
    """A bucket is public-capable if any of the 4 public-access-block flags is off."""
    pab = cfg.get("PublicAccessBlockConfiguration", {})
    return not all([
        pab.get("BlockPublicAcls", False), pab.get("IgnorePublicAcls", False),
        pab.get("BlockPublicPolicy", False), pab.get("RestrictPublicBuckets", False),
    ])


_NO_PUBLIC_ACCESS_BLOCK = "NoSuchPublicAccessBlockConfiguration"   # the one answer that means «none configured»


def collect_data_findings(account: str, health: dict | None = None) -> list[PostureFinding]:
    """S3 public access (cis-2.1) + unencrypted EBS volumes (cis-enc) — two sources, each fail-soft."""
    out: list[PostureFinding] = []
    # S3 is global-ish: enumerate once, through a region of the account's own partition.
    try:
        s3 = _get_client("s3", _home_region(account), account)
        buckets = s3.list_buckets().get("Buckets", [])
        unread: list[str] = []
        for b in buckets:
            name = b.get("Name", "")
            try:
                cfg = s3.get_public_access_block(Bucket=name)
            except Exception as e:
                response = getattr(e, "response", None)
                if isinstance(response, dict) and response.get("Error", {}).get("Code") == _NO_PUBLIC_ACCESS_BLOCK:
                    out.append(PostureFinding("data", "cis-2.1", name, "S3Bucket",
                                              "no public-access-block configured", "high"))
                else:   # refused, throttled, timed out: this bucket was not read — that is not «public»
                    unread.append(failure_reason(e))
                continue
            if _bucket_public(cfg):
                out.append(PostureFinding("data", "cis-2.1", name, "S3Bucket",
                                          "bucket public access not fully blocked", "high"))
        if unread:
            logger.warning("collect_data_findings(s3): %d of %d buckets could not be read for %s: %s",
                           len(unread), len(buckets), account, unread[0])
            _failed(health, "s3", f"{len(unread)} of {len(buckets)} buckets could not be read: {unread[0]}")
        else:
            _ok(health, "s3")
    except Exception as e:
        logger.warning("collect_data_findings(s3) failed for %s: %s", account, e)
        _failed(health, "s3", failure_reason(e))
    # EBS encryption per region.
    region = ""
    try:
        for region in _enabled_regions(account):
            ec2 = _get_client("ec2", region, account)
            for page in ec2.get_paginator("describe_volumes").paginate():
                for vol in page.get("Volumes", []):
                    if not vol.get("Encrypted", False):
                        out.append(PostureFinding("data", "cis-enc", vol.get("VolumeId", ""),
                                                  "EBSVolume", "volume not encrypted at rest"))
        _ok(health, "ebs")
    except Exception as e:
        logger.warning("collect_data_findings(ebs) failed for %s: %s", account, e)
        _failed(health, "ebs", _in_region(region, e))
    return out


def collect_logging_findings(account: str, health: dict | None = None) -> list[PostureFinding]:
    """CloudTrail: at least one multi-region trail actively logging (cis-3.1). Fail-soft."""
    try:
        ct = _get_client("cloudtrail", _home_region(account), account)
        trails = ct.describe_trails().get("trailList", [])
        unread = ""
        for t in trails:
            if not t.get("IsMultiRegionTrail"):
                continue
            try:
                if ct.get_trail_status(Name=t.get("TrailARN") or t.get("Name")).get("IsLogging"):
                    _ok(health, "logging")
                    return []  # a compliant trail exists
            except Exception as e:
                unread = unread or failure_reason(e)
                continue
        if unread:   # a trail that may well be logging could not be asked: «no trail is logging» is not known
            logger.warning("collect_logging_findings: a trail's status could not be read for %s: %s", account, unread)
            _failed(health, "logging", f"a trail's status could not be read: {unread}")
            return []
        _ok(health, "logging")
        return [PostureFinding("logging", "cis-3.1", "account", "CloudTrail",
                               "no multi-region trail actively logging", "high")]
    except Exception as e:
        logger.warning("collect_logging_findings failed for %s: %s", account, e)
        _failed(health, "logging", failure_reason(e))
        return []


def collect_network_acls(account: str, region: str, vpc_id: str = "") -> dict[str, dict]:
    """Return {subnet_id: {nacl_id, inbound:[entry], outbound:[entry]}}, entries
    sorted by rule_number ascending. Fail-soft (returns {} on error)."""
    by_subnet: dict[str, dict] = {}
    try:
        ec2 = _get_client("ec2", region, account)
        filters = [{"Name": "vpc-id", "Values": [vpc_id]}] if vpc_id else []
        resp = ec2.describe_network_acls(Filters=filters) if filters else ec2.describe_network_acls()
        for acl in resp.get("NetworkAcls", []):
            inbound, outbound = [], []
            for e in sorted(acl.get("Entries", []), key=lambda x: x.get("RuleNumber", 32767)):
                pr = e.get("PortRange") or {}
                item = {
                    "rule_number": e.get("RuleNumber"),
                    "protocol": str(e.get("Protocol", "-1")),
                    "cidr": e.get("CidrBlock", ""),
                    "action": e.get("RuleAction", "deny"),
                    "port_from": pr.get("From"),
                    "port_to": pr.get("To"),
                }
                (outbound if e.get("Egress") else inbound).append(item)
            for assoc in acl.get("Associations", []):
                sid = assoc.get("SubnetId")
                if sid:
                    by_subnet[sid] = {"nacl_id": acl.get("NetworkAclId"),
                                      "inbound": inbound, "outbound": outbound}
    except Exception as e:
        logger.warning("collect_network_acls failed for %s/%s: %s", account, region, e)
        return {}
    return by_subnet
