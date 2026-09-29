"""Deterministic issue → inventory anchoring (MVP-2.6.1, spec §3.A.1).

resolve() maps what a signal says about its subject — an account designation, a resource id or ARN, K8s
hints, an alarm name — to ONE physical cloud_resources row, or says honestly why it cannot:

  anchored       exactly one physical resource matched (same-physical duplicate rows are candidates with
                 reason duplicate_of, not ambiguity)
  ambiguous      the first rule with a hit found two or more physical resources; all become candidates
  account_level  the subject is the account itself (root user, CIS control, account-wide setting)
  unanchored     nothing matched, the input names an account we do not manage (rule unknown_account), or
                 an ARN's account contradicts the stated account (rule account_conflict)

Rules run in order; the first one with any hit decides. Every lookup stays inside one account. When the
input names no account at all, each rule runs in every enabled account and only a single physical hit
anchors (and backfills the account) — there is no "the only enabled account" guess. Inventory reads only:
no LLM, no cloud calls.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import and_, or_

from agenticops.config import settings
from agenticops.galaxy.rules import arn_region, dedup_physical, k8s_resource_id, short_id

logger = logging.getLogger(__name__)

ANCHORED = "anchored"
AMBIGUOUS = "ambiguous"
ACCOUNT_LEVEL = "account_level"
UNANCHORED = "unanchored"


@dataclass(frozen=True)
class Anchor:
    status: str
    resource_ref: Optional[int] = None
    account_id: Optional[int] = None
    rule: str = ""
    candidates: list = field(default_factory=list)

    def audit(self) -> dict:
        """The anchor_candidates column value."""
        return {"rule": self.rule, "candidates": list(self.candidates)}


_ARN_ACCOUNT = re.compile(r"^arn:aws[a-z-]*:[^:]*:[^:]*:(\d{12}):")
_ACCOUNT_NUMBER = re.compile(r"\d{12}")
_ACCOUNT_LEVEL = re.compile(
    r"^(?:\d{12}|\d{12}-root|AWS::::Account:\d{12}|arn:aws[a-z-]*:iam::\d{12}:root"
    r"|CIS-[A-Za-z0-9._-]+|root-account(?:-\d{12})?|(?:account|aws-iam)-\d{12})$"
)
_ELB_NAME = re.compile(r"(?:^|loadbalancer/|listener/)(?:app|net|gwy)/(?P<name>[^/]+)/[0-9a-f]+(?:/[0-9a-f]+)?$")
_POD_SUFFIXES = (
    re.compile(r"^(.+)-[a-z0-9]{6,10}-[a-z0-9]{5}$"),  # Deployment pod: <name>-<replicaset hash>-<5>
    re.compile(r"^(.+)-[a-z0-9]{5}$"),                 # DaemonSet / Job pod: <name>-<5>
    re.compile(r"^(.+)-\d+$"),                         # StatefulSet pod: <name>-<ordinal>
)
_WORKLOAD_KINDS = ("Deployment", "StatefulSet", "DaemonSet")
_CLUSTER_TYPES = ("EKS", "EKS_Cluster")
_K8S_PROVIDER = "kubernetes"
_ELB_TYPES = ("ELB",)
_COLUMNS = ("id", "account_id", "region", "resource_type", "resource_id", "name", "scanned_at")

Rule = tuple[str, Callable[[int], list]]


# ── account designations ──────────────────────────────────────────────


def _account_number(credentials) -> Optional[str]:
    creds = credentials if isinstance(credentials, dict) else {}
    number = str(creds.get("account_id") or "").strip()
    if number:
        return number
    m = _ARN_ACCOUNT.match(str(creds.get("role_arn") or ""))
    return m.group(1) if m else None


def account_pk(session, value) -> Optional[int]:
    """Map any account designation to cloud_accounts.id: a primary key (int or digit string), an account name,
    or a 12-digit account number (credentials.account_id, else the role_arn account segment — role_arn is
    stored in plain text). None unless exactly one account matches. Disabled accounts count: an issue still
    belongs to its account."""
    from agenticops.models import CloudAccount

    if value is None or isinstance(value, bool):
        return None
    accounts = session.query(CloudAccount.id, CloudAccount.name, CloudAccount.credentials).all()
    if isinstance(value, int):
        return value if any(a.id == value for a in accounts) else None
    text = str(value).strip()
    if not text:
        return None
    named = [a.id for a in accounts if a.name == text]
    if named:
        return named[0]
    if _ACCOUNT_NUMBER.fullmatch(text):
        numbered = [a.id for a in accounts if _account_number(a.credentials) == text]
        return numbered[0] if len(numbered) == 1 else None
    if text.isdigit():
        pk = int(text)
        return pk if any(a.id == pk for a in accounts) else None
    return None


def _is_account_level(rid: str) -> bool:
    return bool(_ACCOUNT_LEVEL.match(rid) or _ACCOUNT_LEVEL.match(short_id(rid)))


def _stated_account(account_id, hints: dict):
    """The account the caller states outright — explicit, then hint. None = not stated."""
    for value in (account_id, hints.get("account")):
        if value is not None and str(value).strip():
            return value
    return None


def _claimed_account(account_id, hints: dict, rid: str):
    """The account the input itself names, most trusted first: explicit, hint, the ARN account segment, the
    number inside an account-level id. None = the input does not say."""
    stated = _stated_account(account_id, hints)
    if stated is not None:
        return stated
    m = _ARN_ACCOUNT.match(rid)
    if m:
        return m.group(1)
    if rid and _is_account_level(rid):
        m = _ACCOUNT_NUMBER.search(rid)
        if m:
            return m.group(0)
    return None


def _arn_account_conflict(session, pk: int, rid: str) -> Optional[str]:
    """The ARN's account segment when it contradicts account pk's own number, else None. Compared by number,
    not by account_pk(segment): two account rows may share one number. An account whose number is unknown
    (no credentials.account_id, no role_arn) cannot be compared and never conflicts."""
    from agenticops.models import CloudAccount

    m = _ARN_ACCOUNT.match(rid)
    if not m:
        return None
    number = _account_number(session.query(CloudAccount.credentials).filter(CloudAccount.id == pk).scalar())
    return m.group(1) if number and number != m.group(1) else None


def _clean_hints(hints) -> dict:
    if not isinstance(hints, dict):
        return {}
    return {k: str(v).strip() for k, v in hints.items()
            if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip()}


# ── inventory lookups (one account per call) ──────────────────────────


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _rows(session, account: int, region: Optional[str], *criteria) -> list:
    from agenticops.models import CloudResource as R

    q = session.query(*(getattr(R, c) for c in _COLUMNS)).filter(R.account_id == account, *criteria)
    if region:
        q = q.filter(or_(R.region.in_((region, "global", "")), R.region.is_(None)))
    return [dict(r._mapping) for r in q.order_by(R.id)]


def _arn_rows_ending_in(value: str):
    from agenticops.models import CloudResource as R

    esc = _like_escape(value)
    return and_(R.resource_id.like("arn:%"),
                or_(R.resource_id.like(f"%/{esc}", escape="\\"), R.resource_id.like(f"%:{esc}", escape="\\")))


def _id_rows(session, account: int, region: Optional[str], rid: str) -> list:
    """Rules 1–2 as one step: exact id, an ARN input against a short-id row, a short input against an ARN row."""
    from agenticops.models import CloudResource as R

    if rid.startswith("arn:"):
        return _rows(session, account, region, R.resource_id.in_(sorted({rid, short_id(rid)})))
    rows = _rows(session, account, region, or_(R.resource_id == rid, _arn_rows_ending_in(rid)))
    return [r for r in rows if r["resource_id"] == rid or short_id(r["resource_id"]) == rid]


def _inventory_rules(session, rid: str, region: Optional[str]) -> list[Rule]:
    """Rules 1–4."""
    from agenticops.models import CloudResource as R

    if not rid:
        return []
    rules: list[Rule] = [("resource_id", lambda a: _id_rows(session, a, region, rid))]
    m = _ELB_NAME.search(rid)
    if m:
        name = m.group("name")
        rules.append(("elb_arn", lambda a: _rows(session, a, region, R.resource_type.in_(_ELB_TYPES),
                                                 or_(R.resource_id == name, R.name == name))))
    # An ARN name-matches only in full: its last segment ('…/stages/default') is not an identity, and the
    # resource_id rule already does ARN ↔ short-id matching. Non-ARN inputs match as given.
    names = [rid] if rid.startswith("arn:") else sorted({rid, short_id(rid)})
    # A K8s object's name is an identity only inside its cluster + namespace — rule 6 resolves those.
    rules.append(("name", lambda a: _rows(session, a, region, R.name.in_(names), R.provider != _K8S_PROVIDER)))
    return rules


def _pod_bases(pod: str) -> list:
    bases: list = []
    for pattern in _POD_SUFFIXES:
        m = pattern.match(pod)
        if m and m.group(1) not in bases:
            bases.append(m.group(1))
    return bases


def _k8s_rows(session, account: int, region: Optional[str], hints: dict) -> list:
    """Rule 6, most specific first: workload, the pod's workload, a bare pod, service, namespace, the cluster.
    Namespaced lookups need hints.namespace; nothing is guessed."""
    from agenticops.models import CloudResource as R

    cluster, ns = hints["cluster"], hints.get("namespace")
    lookups: list = []
    if ns:
        if hints.get("workload"):
            lookups.append([k8s_resource_id(cluster, k, hints["workload"], ns) for k in _WORKLOAD_KINDS])
        pod = hints.get("pod")
        if pod:
            lookups.append([k8s_resource_id(cluster, k, b, ns) for b in _pod_bases(pod) for k in _WORKLOAD_KINDS])
            lookups.append([k8s_resource_id(cluster, "Pod", pod, ns)])
        if hints.get("service"):
            lookups.append([k8s_resource_id(cluster, "Service", hints["service"], ns)])
        lookups.append([k8s_resource_id(cluster, "Namespace", ns)])
    for ids in lookups:
        rows = _rows(session, account, region, R.resource_id.in_(ids)) if ids else []
        if rows:
            return rows
    rows = _rows(session, account, region, R.resource_type.in_(_CLUSTER_TYPES),
                 or_(R.resource_id == cluster, R.name == cluster, _arn_rows_ending_in(cluster)))
    return [r for r in rows if cluster in (r["resource_id"], r["name"], short_id(r["resource_id"]))]


def _alarm_hints(alarm_name: str, hints: dict) -> Optional[dict]:
    """Rule 7: an identity_alarm_name_patterns match supplies cluster (+ namespace); explicit hints win."""
    if not alarm_name:
        return None
    for pattern in settings.identity_alarm_name_patterns:
        try:
            m = re.match(pattern, alarm_name)
        except re.error:
            logger.warning("identity: invalid identity_alarm_name_patterns entry %r", pattern)
            continue
        groups = m.groupdict() if m else {}
        if groups.get("cluster"):
            merged = dict(hints)
            for key in ("cluster", "namespace"):
                if groups.get(key) and not merged.get(key):
                    merged[key] = groups[key]
            return merged
    return None


def _k8s_rules(session, hints: dict, alarm_name: str, region: Optional[str]) -> list[Rule]:
    """Rules 6–7."""
    rules: list[Rule] = []
    if hints.get("cluster"):
        rules.append(("k8s_hints", lambda a: _k8s_rows(session, a, region, hints)))
    merged = _alarm_hints(alarm_name, hints)
    if merged is not None and merged != hints:
        rules.append(("alarm_name", lambda a: _k8s_rows(session, a, region, merged)))
    return rules


def _first_hit(rules: list[Rule], accounts: list) -> Optional[tuple[str, list]]:
    for rule, find in rules:
        rows = [row for account in accounts for row in find(account)]
        if rows:
            return rule, rows
    return None


def _decide(rule: str, rows: list, families: dict, known: Optional[int]) -> Anchor:
    canon, dups = dedup_physical(rows, families)
    duplicates = [{"ref": d["id"], "account_id": d["account_id"], "reason": "duplicate_of", "of": c["id"]}
                  for d, c in dups]
    accounts = {r["account_id"] for r in canon}
    account = next(iter(accounts)) if len(accounts) == 1 else known
    if len(canon) == 1:
        return Anchor(ANCHORED, resource_ref=canon[0]["id"], account_id=account, rule=rule, candidates=duplicates)
    return Anchor(AMBIGUOUS, account_id=account, rule=rule,
                  candidates=[{"ref": r["id"], "account_id": r["account_id"], "reason": rule} for r in canon]
                  + duplicates)


def resolve(session, *, account_id=None, provider: Optional[str] = None, resource_id: Optional[str] = None,
            hints: Optional[dict] = None, alarm_name: Optional[str] = None) -> Anchor:
    """Anchor one issue subject (the single entry point — Signal Gate, the 2.6.1 backfill and re-anchoring).

    account_id may be a cloud_accounts.id, an account name or a 12-digit number (account_pk maps it).
    provider belongs to the contract but is not a row filter: an EKS cluster's K8s rows live in the owning
    AWS account under provider=kubernetes while the alert about them says aws."""
    from agenticops.models import CloudAccount

    rid = (resource_id or "").strip()
    if rid.lower() == "unknown":
        rid = ""
    clean = _clean_hints(hints)
    claimed = _claimed_account(account_id, clean, rid)
    if claimed is not None:
        pk = account_pk(session, claimed)
        if pk is None:
            return Anchor(UNANCHORED, rule="unknown_account",
                          candidates=[{"account": str(claimed), "reason": "unknown_account"}])
        # A stated account the ARN itself contradicts: the resource lives elsewhere, so nothing here is it.
        conflict = _arn_account_conflict(session, pk, rid) if _stated_account(account_id, clean) is not None else None
        if conflict:
            return Anchor(UNANCHORED, rule="account_conflict",
                          candidates=[{"account": str(claimed), "arn_account": conflict, "reason": "account_conflict"}])
        accounts, known = [pk], pk
    else:
        accounts = [row.id for row in session.query(CloudAccount.id)
                    .filter(CloudAccount.is_enabled.is_(True)).order_by(CloudAccount.id)]
        known = None
    region = arn_region(rid) or clean.get("region") or None

    hit = _first_hit(_inventory_rules(session, rid, region), accounts)
    if hit is None and rid and _is_account_level(rid):
        return Anchor(ACCOUNT_LEVEL, account_id=known, rule=ACCOUNT_LEVEL)
    if hit is None:
        hit = _first_hit(_k8s_rules(session, clean, alarm_name or "", region), accounts)
    if hit is None:
        return Anchor(UNANCHORED, account_id=known, rule="none")
    rule, rows = hit
    return _decide(rule, rows, settings.identity_type_families, known)


def _retry_account(issue):
    """The account a retry must stay inside: the issue's own account, else the account claim its audit
    recorded (candidates[0]["account"] — today unknown_account, account_conflict or a failed anchor).
    None = the signal stated no account."""
    if issue.account_id is not None:
        return issue.account_id
    audit = issue.anchor_candidates
    candidates = audit.get("candidates") if isinstance(audit, dict) else None
    first = candidates[0] if isinstance(candidates, list) and candidates else None
    if isinstance(first, dict) and "account" in first:
        return first["account"]
    return None


def reanchor_open_issues(session) -> int:
    """Retry the OPEN issues the resolver could not place, after every completed build (spec §3.A.1).

    Forward only: an unanchored / ambiguous issue changes only when the new result is anchored or
    account_level, so a shrinking inventory never erases an earlier audit. anchor_status NULL (the backfill
    or _promote failed) takes any result. The retry stays inside the account the signal stated (_retry_account).
    Returns the number of issues changed; the caller commits."""
    from agenticops.models import HealthIssue
    from agenticops.services.signal_gate import OPEN_ISSUE_STATUSES

    issues = (session.query(HealthIssue)
              .filter(HealthIssue.status.in_(OPEN_ISSUE_STATUSES),
                      or_(HealthIssue.anchor_status.in_((UNANCHORED, AMBIGUOUS)),
                          HealthIssue.anchor_status.is_(None)))
              .order_by(HealthIssue.id).all())
    changed = 0
    for issue in issues:
        md = issue.metric_data if isinstance(issue.metric_data, dict) else {}
        anchor = resolve(session, account_id=_retry_account(issue), provider=issue.provider,
                         resource_id=issue.resource_id, hints=md.get("hints"), alarm_name=issue.alarm_name)
        if issue.anchor_status is not None and anchor.status not in (ANCHORED, ACCOUNT_LEVEL):
            continue
        issue.resource_ref = anchor.resource_ref
        issue.anchor_status = anchor.status
        issue.anchor_candidates = anchor.audit()
        if issue.account_id is None and anchor.account_id is not None:
            issue.account_id = anchor.account_id
        changed += 1
    return changed
