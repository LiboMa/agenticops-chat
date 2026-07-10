"""AgenticOps E2E client — login, REST helpers, and phase pollers.

Runs from a remote server against a port-forwarded ClusterIP app.
Depends only on `requests` (stdlib + requests) so it needs no repo imports.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests


class PhaseTimeout(Exception):
    """Raised when a phase (perceive/analyze/resolve/record) does not complete in time."""
    def __init__(self, phase: str, detail: str):
        self.phase = phase
        super().__init__(f"[{phase}] {detail}")


class AgenticOpsClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token: Optional[str] = None

    # ---- auth ----
    def login(self, email: str, password: str) -> None:
        r = requests.post(f"{self.base_url}/api/auth/login",
                          json={"email": email, "password": password}, timeout=self.timeout)
        r.raise_for_status()
        self._token = r.json()["token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def get(self, path: str) -> Any:
        r = requests.get(f"{self.base_url}{path}", headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json: Optional[dict] = None) -> Any:
        r = requests.post(f"{self.base_url}{path}", headers=self._headers(),
                          json=json or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    # ---- account registration (idempotent, environment source) ----
    def ensure_account(self, name: str, account_id: str, regions: list[str]) -> None:
        existing = self.get("/api/accounts")
        if any(a.get("name") == name for a in existing):
            return
        self.post("/api/accounts", json={
            "name": name, "provider": "aws",
            "credential_source_type": "environment",
            "credentials": {"account_id": account_id},
            "regions": regions, "is_enabled": True,
        })

    # ---- perception ----
    def send_cloudwatch_alert(self, payload: dict) -> Any:
        return self.post("/api/webhooks/alert/cloudwatch", json=payload)

    def find_recent_issue(self, title_pattern: str, max_age_min: int = 15) -> Optional[int]:
        data = self.get("/api/health-issues?limit=30")
        items = data if isinstance(data, list) else data.get("items", [])
        pat = re.compile(title_pattern, re.IGNORECASE)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_min)
        for it in items:
            if it.get("status") in ("resolved", "closed"):
                continue
            det = it.get("detected_at") or it.get("created_at") or ""
            try:
                dt = datetime.fromisoformat(det.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
            text = f"{it.get('title','')} {it.get('description','')}"
            if pat.search(text):
                return int(it["id"])
        return None

    def wait_for_issue(self, title_pattern: str, timeout_s: int, poll_s: int = 5) -> int:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            found = self.find_recent_issue(title_pattern)
            if found is not None:
                return found
            time.sleep(poll_s)
        raise PhaseTimeout("perceive", f"no HealthIssue matched /{title_pattern}/ in {timeout_s}s")

    # ---- analysis ----
    def has_rca(self, issue_id: int) -> bool:
        rca = self.get(f"/api/health-issues/{issue_id}/rca")
        return bool(rca)

    # ---- resolution ----
    def get_fix_plan(self, issue_id: int) -> Optional[dict]:
        plans = self.get(f"/api/fix-plans?health_issue_id={issue_id}")
        items = plans if isinstance(plans, list) else plans.get("items", [])
        return items[0] if items else None

    def wait_for_status(self, issue_id: int, targets: set[str], timeout_s: int, poll_s: int = 5) -> str:
        deadline = time.monotonic() + timeout_s
        current = ""
        while time.monotonic() < deadline:
            current = self.get(f"/api/health-issues/{issue_id}").get("status", "")
            if current in targets:
                return current
            time.sleep(poll_s)
        raise PhaseTimeout("resolve", f"issue {issue_id} stuck at '{current}', wanted {targets}")

    # ---- record ----
    def get_timeline(self, issue_id: int) -> list[dict]:
        tl = self.get(f"/api/health-issues/{issue_id}/timeline")
        return tl if isinstance(tl, list) else tl.get("timeline", tl.get("events", []))
