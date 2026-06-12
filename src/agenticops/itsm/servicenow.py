"""ServiceNow ITSM adapter — Table API (incident) + sn_chg_rest (change).

Verified API facts this adapter encodes (Zurich, 2026):
  * incident.state modern values: New=1, In Progress=2, On Hold=3,
    Resolved=6, Closed=7 — values 4/5 do not exist; never write 7
    (closure is the customer's process / auto-close timer).
  * priority is derived from impact+urgency — set those, not priority.
  * work_notes is a write-only journal field (PATCH appends).
  * change states: New=-5, Assess=-4, Authorize=-3, Scheduled=-2,
    Implement=-1, Review=0, Closed=3, Canceled=4.
  * standard changes are created from a pre-authorized template
    (POST /change/standard/{template_id}) and skip Assess/Authorize —
    this is the ITIL evidence story for L0/L1 auto-fixes.
  * there is NO GET approvals endpoint in sn_chg_rest — poll the
    change record's 'approval' field (not_requested|requested|approved|rejected).
  * close requires close_code ∈ {successful, successful_issues, unsuccessful}.

dry_run mode logs every request it WOULD make and returns synthetic
references — safe for demos and for customers without a dev instance.
"""

from __future__ import annotations

import itertools
import logging
from typing import Optional

import httpx

from agenticops.itsm.base import ITSMAdapter, ITSMResult

logger = logging.getLogger(__name__)

TIMEOUT = 15

# AgenticOps severity → ServiceNow impact/urgency (priority derives from these)
SEVERITY_MAP = {
    "critical": {"impact": "1", "urgency": "1"},
    "high": {"impact": "2", "urgency": "2"},
    "medium": {"impact": "2", "urgency": "3"},
    "low": {"impact": "3", "urgency": "3"},
}

INCIDENT_STATES = {"new": "1", "in_progress": "2", "on_hold": "3", "resolved": "6"}
CHANGE_STATES = {
    "assess": "assess",
    "scheduled": "scheduled",
    "implement": "implement",
    "review": "review",
    "closed": "closed",
    "cancelled": "canceled",
}

_dry_counter = itertools.count(1)


class ServiceNowAdapter(ITSMAdapter):
    """ServiceNow over Basic auth (integration user) or OAuth bearer token."""

    name = "servicenow"

    def __init__(
        self,
        instance_url: str,
        username: str = "",
        password: str = "",
        token: str = "",
        dry_run: bool = True,
    ):
        self.base = instance_url.rstrip("/")
        self.dry_run = dry_run
        self._auth = (username, password) if username else None
        self._headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    # ── HTTP plumbing ───────────────────────────────────────────────

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> ITSMResult:
        url = f"{self.base}{path}"
        if self.dry_run:
            n = next(_dry_counter)
            logger.info("[ITSM dry-run] %s %s body=%s", method, url, body)
            return ITSMResult(
                ok=True,
                external_id=f"dryrun-sys-{n:04d}",
                external_ref=f"DRY{n:07d}",
                url=url,
                detail={"dry_run": True, "method": method, "path": path, "body": body or {}},
            )
        try:
            resp = httpx.request(
                method, url, json=body, headers=self._headers, auth=self._auth, timeout=TIMEOUT
            )
            if resp.status_code >= 400:
                return ITSMResult.failure(f"{resp.status_code}: {resp.text[:300]}")
            data = (resp.json() or {}).get("result") or {}
            if isinstance(data, list):
                data = data[0] if data else {}
            return ITSMResult(
                ok=True,
                external_id=data.get("sys_id"),
                external_ref=data.get("number"),
                url=f"{self.base}/nav_to.do?uri={path.split('/')[-1]}",
                detail=data if isinstance(data, dict) else {},
            )
        except httpx.HTTPError as e:
            return ITSMResult.failure(f"servicenow request failed: {e}")

    # ── Incident ────────────────────────────────────────────────────

    def create_incident(self, *, title, description, severity, correlation_id, resource_id=None) -> ITSMResult:
        body = {
            "short_description": title[:160],
            "description": description,
            "correlation_id": correlation_id,
            **SEVERITY_MAP.get(severity, SEVERITY_MAP["medium"]),
        }
        if resource_id:
            body["cmdb_ci"] = resource_id  # CI sys_id when CMDB-bound; raw id otherwise
        return self._call("POST", "/api/now/table/incident", body)

    def update_incident_state(self, external_id: str, state: str) -> ITSMResult:
        value = INCIDENT_STATES.get(state)
        if not value:
            return ITSMResult.failure(f"unknown incident state {state!r}")
        return self._call("PATCH", f"/api/now/table/incident/{external_id}", {"state": value})

    def append_worknote(self, external_id: str, note: str) -> ITSMResult:
        # journal field max ~4000 chars per note
        return self._call(
            "PATCH", f"/api/now/table/incident/{external_id}", {"work_notes": note[:4000]}
        )

    def resolve_incident(self, external_id: str, close_notes: str) -> ITSMResult:
        return self._call(
            "PATCH",
            f"/api/now/table/incident/{external_id}",
            {"state": "6", "close_code": "Solved (Permanently)", "close_notes": close_notes[:4000]},
        )

    # ── Change ──────────────────────────────────────────────────────

    def create_change(
        self, *, incident_external_id, change_type, title, description,
        implementation_plan, backout_plan, risk_level, correlation_id,
    ) -> ITSMResult:
        body = {
            "short_description": title[:160],
            "description": description,
            "implementation_plan": implementation_plan[:4000],
            "backout_plan": backout_plan[:4000],
            "justification": f"AgenticOps auto-remediation ({risk_level}); correlation_id={correlation_id}",
        }
        if incident_external_id:
            body["parent_incident"] = incident_external_id
        if change_type == "standard":
            # Real deployments configure a pre-authorized template per fix
            # pattern; without one we fall back to a normal change so the
            # record still exists (fail toward MORE approval, never less).
            template_id = getattr(self, "standard_template_id", "")
            if template_id:
                return self._call("POST", f"/api/sn_chg_rest/v1/change/standard/{template_id}", body)
            logger.info("No standard-change template configured — creating normal change instead")
            return self._call("POST", "/api/sn_chg_rest/v1/change/normal", body)
        if change_type == "emergency":
            return self._call("POST", "/api/sn_chg_rest/v1/change/emergency", body)
        return self._call("POST", "/api/sn_chg_rest/v1/change/normal", body)

    def update_change_state(self, external_id: str, state: str) -> ITSMResult:
        value = CHANGE_STATES.get(state)
        if not value:
            return ITSMResult.failure(f"unknown change state {state!r}")
        return self._call("PATCH", f"/api/sn_chg_rest/v1/change/{external_id}", {"state": value})

    def get_change_approval(self, external_id: str) -> ITSMResult:
        result = self._call(
            "GET",
            f"/api/now/table/change_request/{external_id}?sysparm_fields=state,approval",
        )
        if result.ok:
            if result.detail.get("dry_run"):
                result.detail["approval"] = "approved"  # dry-run flows proceed
            else:
                result.detail["approval"] = result.detail.get("approval", "not_requested")
        return result

    def append_change_worknote(self, external_id: str, note: str) -> ITSMResult:
        return self._call(
            "PATCH", f"/api/sn_chg_rest/v1/change/{external_id}", {"work_notes": note[:4000]}
        )

    def close_change(self, external_id: str, success: bool, notes: str) -> ITSMResult:
        return self._call(
            "PATCH",
            f"/api/sn_chg_rest/v1/change/{external_id}",
            {
                "state": "closed",
                "close_code": "successful" if success else "unsuccessful",
                "close_notes": notes[:4000],
            },
        )
