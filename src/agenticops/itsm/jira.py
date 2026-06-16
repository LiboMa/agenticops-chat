"""Jira Service Management ITSM adapter.

Uses the JSM service-desk API for portal-semantic requests (SLAs/approvals)
when service_desk_id+request_type_id are configured, else core Jira issues.
Changes are modeled as linked issues of a configurable type; approval state
reads the JSM approval API (GET .../request/{key}/approval — the bot reads,
humans answer).

dry_run mode mirrors the ServiceNow adapter: logs intended calls, returns
synthetic keys.
"""

from __future__ import annotations

import itertools
import logging
from typing import Optional

import httpx

from agenticops.itsm.base import ITSMAdapter, ITSMResult

logger = logging.getLogger(__name__)

TIMEOUT = 15

SEVERITY_TO_PRIORITY = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

_dry_counter = itertools.count(1)


class JiraAdapter(ITSMAdapter):
    """Jira Cloud (JSM) over Basic auth (email + API token)."""

    name = "jira"

    def __init__(
        self,
        base_url: str,
        email: str = "",
        api_token: str = "",
        project_key: str = "OPS",
        change_issue_type: str = "Change",
        incident_issue_type: str = "Incident",
        dry_run: bool = True,
    ):
        self.base = base_url.rstrip("/")
        self.project_key = project_key
        self.change_issue_type = change_issue_type
        self.incident_issue_type = incident_issue_type
        self.dry_run = dry_run
        self._auth = (email, api_token) if email else None
        self._headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> ITSMResult:
        url = f"{self.base}{path}"
        if self.dry_run:
            n = next(_dry_counter)
            logger.info("[ITSM dry-run] %s %s body=%s", method, url, body)
            return ITSMResult(
                ok=True,
                external_id=f"{self.project_key}-DRY{n}",
                external_ref=f"{self.project_key}-DRY{n}",
                url=url,
                detail={"dry_run": True, "method": method, "path": path, "body": body or {}},
            )
        try:
            resp = httpx.request(
                method, url, json=body, headers=self._headers, auth=self._auth, timeout=TIMEOUT
            )
            if resp.status_code >= 400:
                return ITSMResult.failure(f"{resp.status_code}: {resp.text[:300]}")
            data = resp.json() if resp.content else {}
            key = data.get("key") or data.get("issueKey")
            return ITSMResult(
                ok=True,
                external_id=key,
                external_ref=key,
                url=f"{self.base}/browse/{key}" if key else url,
                detail=data if isinstance(data, dict) else {},
            )
        except httpx.HTTPError as e:
            return ITSMResult.failure(f"jira request failed: {e}")

    @staticmethod
    def _adf(text: str) -> dict:
        """Plain text → Atlassian Document Format."""
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text or " "}]}
            ],
        }

    def _create_issue(self, issue_type: str, title: str, description: str, severity: str, labels: list[str]) -> ITSMResult:
        body = {
            "fields": {
                "project": {"key": self.project_key},
                "issuetype": {"name": issue_type},
                "summary": title[:250],
                "description": self._adf(description),
                "labels": labels,
            }
        }
        return self._call("POST", "/rest/api/3/issue", body)

    # ── Incident ────────────────────────────────────────────────────

    def create_incident(self, *, title, description, severity, correlation_id, resource_id=None) -> ITSMResult:
        labels = ["agenticops", f"corr-{correlation_id}"]
        if resource_id:
            description = f"{description}\n\nResource: {resource_id}"
        return self._create_issue(self.incident_issue_type, title, description, severity, labels)

    def update_incident_state(self, external_id: str, state: str) -> ITSMResult:
        # Workflow transition IDs are instance-specific; a comment records the
        # state change reliably, and customers map transitions via automation.
        return self.append_worknote(external_id, f"AgenticOps state → {state}")

    def append_worknote(self, external_id: str, note: str) -> ITSMResult:
        return self._call(
            "POST",
            f"/rest/api/3/issue/{external_id}/comment",
            {"body": self._adf(note[:30000])},
        )

    def resolve_incident(self, external_id: str, close_notes: str) -> ITSMResult:
        return self.append_worknote(external_id, f"Resolved by AgenticOps.\n\n{close_notes}")

    # ── Change ──────────────────────────────────────────────────────

    def create_change(
        self, *, incident_external_id, change_type, title, description,
        implementation_plan, backout_plan, risk_level, correlation_id,
    ) -> ITSMResult:
        full_desc = (
            f"{description}\n\n"
            f"Change type: {change_type} | Risk: {risk_level}\n\n"
            f"h3. Implementation plan\n{implementation_plan}\n\n"
            f"h3. Backout plan\n{backout_plan}"
        )
        result = self._create_issue(
            self.change_issue_type, title, full_desc, risk_level,
            ["agenticops", "change", f"corr-{correlation_id}", change_type],
        )
        if result.ok and incident_external_id and not self.dry_run:
            self._call(
                "POST",
                "/rest/api/3/issueLink",
                {
                    "type": {"name": "Relates"},
                    "inwardIssue": {"key": result.external_id},
                    "outwardIssue": {"key": incident_external_id},
                },
            )
        return result

    def update_change_state(self, external_id: str, state: str) -> ITSMResult:
        return self.append_worknote(external_id, f"AgenticOps change state → {state}")

    def get_change_approval(self, external_id: str) -> ITSMResult:
        result = self._call(
            "GET", f"/rest/servicedeskapi/request/{external_id}/approval"
        )
        if result.ok:
            if result.detail.get("dry_run"):
                result.detail["approval"] = "approved"
            else:
                decisions = result.detail.get("values") or []
                final = decisions[0].get("finalDecision") if decisions else "pending"
                result.detail["approval"] = {
                    "approved": "approved",
                    "declined": "rejected",
                }.get(final, "requested")
        return result

    def close_change(self, external_id: str, success: bool, notes: str) -> ITSMResult:
        verdict = "successful" if success else "unsuccessful"
        return self.append_worknote(external_id, f"Change closed ({verdict}).\n\n{notes}")
