"""Kubernetes provider — one provider type for EKS/AKS/GKE/k3s/OpenShift.

Credential schema (CloudAccount.credentials):
    {kubeconfig_path?: ~/.kube/config, context?: <name>, namespace?: default}

Auth deltas between clouds are absorbed by kubeconfig exec plugins
(aws eks get-token / kubelogin / gke-gcloud-auth-plugin / client certs),
so this provider only needs KUBECONFIG + context. Cloud credential env
vars are stripped before spawning kubectl; exec plugins re-resolve their
own credentials from the kubeconfig itself.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from typing import Any, Callable

from agenticops.providers.base import CloudProvider, ResourceRef

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60
MAX_OUTPUT = 8000


class KubernetesProvider(CloudProvider):
    """kubeconfig-based cluster — Capability.EXECUTE (kubectl) + INVENTORY."""

    @property
    def provider_type(self) -> str:
        return "kubernetes"

    def resolve_credentials(self) -> bool:
        creds = self.account.credentials or {}
        kubeconfig = os.path.expanduser(creds.get("kubeconfig_path") or "~/.kube/config")
        if not os.path.exists(kubeconfig):
            logger.error(
                "kubernetes account %s: kubeconfig not found at %s",
                self.account.name, kubeconfig,
            )
            return False
        self._cfg = {**creds, "kubeconfig_path": kubeconfig}
        return True

    def sdk_session(self) -> Any:
        if not hasattr(self, "_cfg"):
            if not self.resolve_credentials():
                raise RuntimeError(
                    f"kubernetes account {self.account.name}: credential resolution failed"
                )
        return self._cfg

    def _kubectl_env(self) -> dict:
        cfg = self.sdk_session()
        env = dict(os.environ)
        # Exec plugins (aws eks get-token etc.) resolve their own creds from
        # the kubeconfig; ambient cloud vars must not leak across accounts.
        for key in list(env):
            if key.startswith(("AWS_", "ARM_", "AZURE_", "GOOGLE_", "ALIBABA_CLOUD_", "ALICLOUD_")):
                env.pop(key, None)
        env["KUBECONFIG"] = cfg["kubeconfig_path"]
        return env

    def _run_kubectl(self, command: str, timeout_s: int = DEFAULT_TIMEOUT) -> dict:
        from agenticops.skills.security import classify_kubectl_command

        tier = classify_kubectl_command(command)
        if tier == "blocked":
            return {"rc": -1, "stdout": "", "stderr": f"kubectl command blocked by security policy: {command!r}"}

        cfg = self.sdk_session()
        try:
            args = shlex.split(command)
        except ValueError as e:
            return {"rc": -1, "stdout": "", "stderr": f"Invalid command syntax: {e}"}
        if args and args[0] != "kubectl":
            args = ["kubectl"] + args
        context = cfg.get("context")
        if context and "--context" not in command:
            args += ["--context", context]

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                shell=False,
                env=self._kubectl_env(),
            )
        except subprocess.TimeoutExpired:
            return {"rc": -1, "stdout": "", "stderr": f"Timed out after {timeout_s}s"}
        except FileNotFoundError:
            return {"rc": -1, "stdout": "", "stderr": "kubectl not found on PATH"}

        return {
            "rc": result.returncode,
            "stdout": result.stdout[-MAX_OUTPUT:],
            "stderr": result.stderr[-2000:],
        }

    def execute(self, *, target: ResourceRef | None = None, command: str, timeout_s: int = DEFAULT_TIMEOUT) -> dict:
        return self._run_kubectl(command, timeout_s)

    def list_resources(
        self,
        *,
        query: str = "",
        types: list[str] | None = None,
        region: str | None = None,
        limit: int = 500,
    ) -> list[ResourceRef]:
        """Inventory: nodes + workloads (deploy/sts/ds) across namespaces."""
        kinds = types or ["nodes", "deployments"]
        refs: list[ResourceRef] = []
        for kind in kinds:
            result = self._run_kubectl(f"kubectl get {kind} -A -o json", timeout_s=30)
            if result["rc"] != 0:
                logger.warning(
                    "kubernetes account %s: get %s failed: %s",
                    self.account.name, kind, result["stderr"][:200],
                )
                continue
            try:
                items = json.loads(result["stdout"]).get("items", [])
            except (json.JSONDecodeError, AttributeError):
                continue
            for item in items:
                meta = item.get("metadata", {})
                name = meta.get("name", "")
                if query and query not in name:
                    continue
                namespace = meta.get("namespace", "")
                refs.append(
                    ResourceRef(
                        provider="kubernetes",
                        account=self.account.name,
                        region="",
                        service="k8s",
                        rtype=item.get("kind", kind).lower(),
                        native_id=f"{namespace}/{name}" if namespace else name,
                        name=name,
                        labels=dict(meta.get("labels") or {}),
                    )
                )
                if len(refs) >= limit:
                    return refs
        return refs

    def cli_tool(self) -> Callable:
        """Agent tool: run kubectl against this cluster context."""
        account_name = self.account.name
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", account_name)
        provider = self

        def _run_k8s(command: str) -> str:
            command = command.strip()
            if not command:
                return "Error: empty command."
            result = provider._run_kubectl(command)
            if result["rc"] != 0:
                err = result["stderr"] or result["stdout"]
                return f"Error (exit {result['rc']}): {err}"
            return result["stdout"] or "(no output)"

        _run_k8s.__name__ = f"run_kubectl_{safe_name}"
        _run_k8s.__doc__ = (
            f"Execute a kubectl command on cluster '{account_name}' "
            f"(works for EKS/AKS/GKE/k3s/OpenShift via kubeconfig context). "
            f"Destructive operations are blocked by security policy.\n\n"
            f"Args:\n"
            f"    command: The kubectl command (with or without the 'kubectl' prefix)."
        )

        from strands import tool as strands_tool
        return strands_tool(_run_k8s)
