"""Prometheus provider — on-prem/IDC metrics + target inventory.

Credential schema (CloudAccount.credentials):
    {base_url, bearer_token_env?, basic_user?, basic_pass_env?, verify_tls?: true}

Tokens/passwords are referenced by env-var NAME (never stored in DB plaintext).
/api/v1/targets doubles as host inventory: every scraped target = one host.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

import httpx

from agenticops.providers.base import CloudProvider, ResourceRef

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class PrometheusProvider(CloudProvider):
    """Prometheus datasource — Capability.METRICS + INVENTORY (targets)."""

    @property
    def provider_type(self) -> str:
        return "prometheus"

    def resolve_credentials(self) -> bool:
        creds = self.account.credentials or {}
        base_url = (creds.get("base_url") or "").rstrip("/")
        if not base_url:
            logger.error("prometheus account %s: 'base_url' is required", self.account.name)
            return False
        token_env = creds.get("bearer_token_env")
        if token_env and not os.environ.get(token_env):
            logger.error(
                "prometheus account %s: env var %s (bearer token) not set",
                self.account.name, token_env,
            )
            return False
        pass_env = creds.get("basic_pass_env")
        if pass_env and not os.environ.get(pass_env):
            logger.error(
                "prometheus account %s: env var %s (basic password) not set",
                self.account.name, pass_env,
            )
            return False
        self._cfg = {**creds, "base_url": base_url}
        return True

    def sdk_session(self) -> Any:
        if not hasattr(self, "_cfg"):
            if not self.resolve_credentials():
                raise RuntimeError(
                    f"prometheus account {self.account.name}: credential resolution failed"
                )
        return self._cfg

    def _request(self, path: str, params: dict | None = None) -> dict:
        cfg = self.sdk_session()
        headers = {}
        auth = None
        token_env = cfg.get("bearer_token_env")
        if token_env:
            headers["Authorization"] = f"Bearer {os.environ[token_env]}"
        elif cfg.get("basic_user"):
            auth = (cfg["basic_user"], os.environ.get(cfg.get("basic_pass_env", ""), ""))
        resp = httpx.get(
            f"{cfg['base_url']}{path}",
            params=params,
            headers=headers,
            auth=auth,
            timeout=DEFAULT_TIMEOUT,
            verify=cfg.get("verify_tls", True),
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"prometheus error: {body.get('error', 'unknown')}")
        return body["data"]

    def query_metrics(
        self,
        *,
        metric: str,
        start: str,
        end: str,
        target: ResourceRef | None = None,
        period_s: int = 300,
        stat: str = "avg",
    ) -> list[dict]:
        """Run a PromQL range query. `metric` is a full PromQL expression."""
        data = self._request(
            "/api/v1/query_range",
            {"query": metric, "start": start, "end": end, "step": f"{period_s}s"},
        )
        return [
            {"labels": series.get("metric", {}), "points": series.get("values", [])}
            for series in data.get("result", [])
        ]

    def query_instant(self, promql: str) -> list[dict]:
        """Run an instant PromQL query."""
        data = self._request("/api/v1/query", {"query": promql})
        return [
            {"labels": s.get("metric", {}), "value": s.get("value")}
            for s in data.get("result", [])
        ]

    def list_resources(
        self,
        *,
        query: str = "",
        types: list[str] | None = None,
        region: str | None = None,
        limit: int = 500,
    ) -> list[ResourceRef]:
        """Inventory from scrape targets: each healthy target = one host/service."""
        data = self._request("/api/v1/targets")
        refs: list[ResourceRef] = []
        for t in data.get("activeTargets", []):
            if t.get("health") != "up":
                continue
            labels = t.get("labels", {})
            instance = labels.get("instance", "")
            if query and query not in instance and query not in labels.get("job", ""):
                continue
            refs.append(
                ResourceRef(
                    provider="prometheus",
                    account=self.account.name,
                    region="",
                    service="target",
                    rtype=labels.get("job", "unknown"),
                    native_id=t.get("scrapeUrl", instance),
                    name=instance,
                    labels=dict(labels),
                )
            )
            if len(refs) >= limit:
                break
        return refs

    def cli_tool(self) -> Callable:
        """Agent tool: run a PromQL query against this Prometheus."""
        account_name = self.account.name
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", account_name)
        provider = self

        def _run_promql(query: str) -> str:
            query = query.strip()
            if not query:
                return "Error: empty PromQL query."
            try:
                results = provider.query_instant(query)
            except Exception as e:
                return f"Error: {e}"
            if not results:
                return "(no results)"
            lines = []
            for r in results[:50]:
                value = r.get("value")
                val_str = value[1] if isinstance(value, list) and len(value) == 2 else str(value)
                lines.append(f"{r['labels']} => {val_str}")
            return "\n".join(lines)

        _run_promql.__name__ = f"run_promql_{safe_name}"
        _run_promql.__doc__ = (
            f"Run an instant PromQL query against Prometheus datasource '{account_name}' "
            f"(IDC/on-prem metrics). Example: node_memory_MemAvailable_bytes, "
            f"up, rate(node_cpu_seconds_total{{mode='idle'}}[5m]).\n\n"
            f"Args:\n"
            f"    query: The PromQL expression to evaluate."
        )

        from strands import tool as strands_tool
        return strands_tool(_run_promql)
