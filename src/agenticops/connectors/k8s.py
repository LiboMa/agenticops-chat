"""K8s pull connector (MVP-2.6.1 spec §3.B.3): cluster objects into cloud_resources, read-only, no LLM.

- targets(): one per physical cluster — every present EKS / EKS_Cluster inventory row of an enabled aws account,
  collapsed by galaxy.rules.dedup_physical, plus every enabled kubernetes account. K8s ids carry no region, so an
  account with two same-named clusters in different regions is refused rather than merged into one scope.
- collect(): one `kubectl get <kind> -o json` per kind, under credentials.kube.kubectl_env_for_cluster (only the
  target account's credentials, a private kubeconfig). A kind is complete only when kubectl exited 0, stayed under
  k8s_connector_max_output_bytes and returned an item list; anything else makes it partial, and ingest never marks
  a partial kind absent.
- raw_data is exactly galaxy.rules.K8S_RAW_DATA_CONTRACT: a Secret keeps its type only, a ConfigMap its key names
  and a hash, and no annotation is ever stored (last-applied-configuration can carry a whole Secret).
- Pods owned by a workload are not stored; they are rolled up into that workload's pod_summary. A workload gets
  no pod_summary at all when the listings it needs failed — never a false 0/N.
- Errors read "<type> not collected — <why>" (and "cluster <name> not collected — <why>" for the whole target):
  the DB redaction masks "<label>: <value>", and "K8s_Secret: …" would be masked.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from typing import Optional

from agenticops.config import settings
from agenticops.connectors.base import CollectResult, EntityObservation, Target
from agenticops.credentials import kube
from agenticops.credentials.resolver import AccountResolutionError, list_enabled_accounts
from agenticops.galaxy.rules import K8S_KIND_TYPES, dedup_physical, k8s_resource_id, physical_key
from agenticops.models import CloudResource
from agenticops.services.inventory import PRESENT

NAME = "k8s"
PROVIDER = "kubernetes"
CALL_TIMEOUT_SECONDS = 60   # one kubectl listing; the caller's timeout_seconds budget can only shorten it
_STDERR_TAIL = 2000
_CLUSTER_TYPES = ("EKS", "EKS_Cluster")
_SAFE_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")  # a scope is a resource_id segment; fullmatch

# (Kind, kubectl resource) in call order. ReplicaSet is listed only to map pods to their Deployment.
_CALLS = (
    ("Namespace", "namespaces"),
    ("Deployment", "deployments.apps"),
    ("StatefulSet", "statefulsets.apps"),
    ("DaemonSet", "daemonsets.apps"),
    ("ReplicaSet", "replicasets.apps"),
    ("Pod", "pods"),
    ("Service", "services"),
    ("Ingress", "ingresses.networking.k8s.io"),
    ("Node", "nodes"),
    ("ConfigMap", "configmaps"),
    ("Secret", "secrets"),
    ("PersistentVolumeClaim", "persistentvolumeclaims"),
    ("PodDisruptionBudget", "poddisruptionbudgets.policy"),
    ("NetworkPolicy", "networkpolicies.networking.k8s.io"),
)
_CLUSTER_SCOPED = {"Namespace", "Node"}
_WORKLOADS = ("Deployment", "StatefulSet", "DaemonSet")


class K8sConnector:
    name = NAME
    provider = PROVIDER

    def targets(self, session) -> list[Target]:
        families = settings.identity_type_families
        aws = {a.id: a for a in list_enabled_accounts("aws")}
        rows = []
        if aws:
            q = session.query(CloudResource.id, CloudResource.account_id, CloudResource.region,
                              CloudResource.resource_id, CloudResource.resource_type, CloudResource.scanned_at
                              ).filter(CloudResource.account_id.in_(list(aws)),
                                       CloudResource.resource_type.in_(_CLUSTER_TYPES), PRESENT)
            rows = [dict(r._mapping) for r in q]
        canon, _dups = dedup_physical(rows, families)
        regions: dict[tuple, set] = {}
        for row in canon:
            acct_id, region, cluster, _family = physical_key(row, families)
            regions.setdefault((acct_id, cluster), set()).add(region)

        out = []
        for (acct_id, cluster), found in regions.items():
            found = sorted(found)
            refused = ""
            if len(found) > 1:
                refused = (f"cluster {cluster} not collected — account '{aws[acct_id].name}' has {len(found)} "
                           f"clusters by that name ({', '.join(found)}) and K8s ids carry no region")
            out += [Target(account=aws[acct_id], scope=cluster, region=r, refused=refused) for r in found]
        for acct in list_enabled_accounts("kubernetes"):
            out.append(Target(account=acct, scope=str(acct.credentials.get("cluster_name") or acct.name),
                              region=(acct.regions or [""])[0]))
        for t in out:
            if not t.refused and not _SAFE_SCOPE.fullmatch(t.scope):
                t.refused = f"cluster {t.scope!r} not collected — not a safe id segment"
        return sorted(out, key=lambda t: (t.account.id, t.scope, t.region))

    def collect(self, target: Target, *, timeout_seconds: Optional[float] = None) -> CollectResult:
        if target.refused:
            return CollectResult(errors=[target.refused])
        scope = target.scope
        try:
            env = kube.kubectl_env_for_cluster(target.account, scope, target.region)
        except (AccountResolutionError, kube.KubeconfigError) as exc:
            return CollectResult(errors=[f"cluster {scope} not collected — {exc}"])

        base = ["kubectl"]
        context = target.account.credentials.get("context") if target.account.provider == "kubernetes" else ""
        if context:
            base += ["--context", str(context)]
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        cap = settings.k8s_connector_max_output_bytes
        listings: dict[str, Optional[list]] = {}
        errors: list[str] = []
        for kind, resource in _CALLS:
            listings[kind] = None
            label = K8S_KIND_TYPES.get(kind, kind)
            call_timeout = CALL_TIMEOUT_SECONDS
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    errors.append(f"{label} not collected — time budget of {timeout_seconds:g}s exhausted")
                    continue
                call_timeout = min(call_timeout, remaining)
            args = base + ["get", resource] + ([] if kind in _CLUSTER_SCOPED else ["-A"]) + ["-o", "json"]
            try:
                items, why = _list(args, env, call_timeout, cap)
            except FileNotFoundError:
                return CollectResult(errors=[f"cluster {scope} not collected — kubectl not found on PATH"])
            if why:
                errors.append(f"{label} not collected — {why}")
            else:
                listings[kind] = items
        return _build(scope, target.region, listings, errors)


# ── kubectl ───────────────────────────────────────────────────────────────────


def _run_capped(args: list, env: Optional[dict], timeout: float, cap: int) -> tuple[int, bytes, str, str]:
    """(returncode, stdout, stderr tail, problem). Reads at most cap + 1 bytes of stdout; over the cap or past the
    timeout the child's whole process group is killed and problem says why. stderr goes to a temp file, so a
    chatty stderr can never block the child."""
    expired = threading.Event()
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err, env=env,
                                shell=False, start_new_session=True)

        def _kill():
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        def _expire():
            expired.set()
            _kill()

        timer = threading.Timer(timeout, _expire)
        timer.start()
        try:
            out = proc.stdout.read(cap + 1)
            over = len(out) > cap
            if over:
                _kill()
            proc.stdout.close()
            rc = proc.wait()
        finally:
            timer.cancel()
        size = err.seek(0, os.SEEK_END)
        err.seek(max(0, size - _STDERR_TAIL))
        stderr = err.read().decode("utf-8", errors="replace").strip()
    if expired.is_set():
        return rc, out, stderr, f"timed out after {round(timeout, 1):g}s"
    if over:
        return rc, out, stderr, f"output exceeded {cap} bytes"
    return rc, out, stderr, ""


def _list(args: list, env: dict, timeout: float, cap: int) -> tuple[list, str]:
    """(items, "") on a complete listing, ([], why) otherwise."""
    rc, out, stderr, problem = _run_capped(args, env, timeout, cap)
    if problem:
        return [], problem
    if rc != 0:
        return [], f"kubectl exit {rc}: {stderr}" if stderr else f"kubectl exit {rc}"
    try:
        doc = json.loads(out)
    except ValueError:
        return [], "kubectl returned invalid JSON"
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        return [], "kubectl returned no item list"
    return [i for i in items if isinstance(i, dict)], ""


# ── observations ──────────────────────────────────────────────────────────────


def _build(scope: str, region: str, listings: dict, errors: list) -> CollectResult:
    result = CollectResult(errors=errors)
    for kind, _resource in _CALLS:
        if kind != "ReplicaSet":
            result.completeness[(scope, K8S_KIND_TYPES[kind])] = listings[kind] is not None

    pods, replicasets = listings["Pod"], listings["ReplicaSet"]
    rs_deployment = {}
    for rs in replicasets or []:
        md = rs.get("metadata") or {}
        owner = _controller(md)
        if owner.get("kind") == "Deployment":
            rs_deployment[(md.get("namespace"), md.get("name"))] = owner.get("name")
    owned: dict[tuple, list] = {}
    for pod in pods or []:
        md = pod.get("metadata") or {}
        owner = _controller(md)
        ns = md.get("namespace")
        if owner.get("kind") == "ReplicaSet":
            workload = ("Deployment", rs_deployment.get((ns, owner.get("name"))))
        elif owner.get("kind") in ("StatefulSet", "DaemonSet"):
            workload = (owner["kind"], owner.get("name"))
        else:
            continue
        if workload[1]:
            owned.setdefault((ns, *workload), []).append(pod)
    summarise = {"Deployment": pods is not None and replicasets is not None,
                 "StatefulSet": pods is not None, "DaemonSet": pods is not None}

    for kind, _resource in _CALLS:
        if kind == "ReplicaSet":
            continue
        for obj in listings[kind] or []:
            md = obj.get("metadata") or {}
            if kind == "Pod" and md.get("ownerReferences"):
                continue  # rolled up into its workload
            name = md.get("name")
            if not name:
                continue
            ns = None if kind in _CLUSTER_SCOPED else md.get("namespace")
            raw = {"cluster": scope, "namespace": ns, "labels": dict(md.get("labels") or {}), **_fields(kind, obj)}
            if summarise.get(kind):
                raw["pod_summary"] = _pod_summary(owned.get((ns, kind, name), []), raw["replicas"])
            # K8s allows 253-char names, cloud_resources.name holds 200; resource_id keeps the full name
            result.entities.append(EntityObservation(
                provider=PROVIDER, resource_type=K8S_KIND_TYPES[kind],
                resource_id=k8s_resource_id(scope, kind, name, ns), name=name[:200], region=region, raw_data=raw,
                tags={}, status=_status(kind, obj)))
    return result


def _controller(md: dict) -> dict:
    for ref in md.get("ownerReferences") or []:
        if ref.get("controller"):
            return ref
    return {}


def _fields(kind: str, obj: dict) -> dict:
    """The kind-specific raw_data fields (K8S_RAW_DATA_CONTRACT); everything else is dropped."""
    spec, status = obj.get("spec") or {}, obj.get("status") or {}
    if kind in _WORKLOADS:
        template = spec.get("template") or {}
        if kind == "DaemonSet":
            replicas = status.get("desiredNumberScheduled") or 0
        else:
            replicas = 1 if spec.get("replicas") is None else spec["replicas"]   # 0 is a real value
        return {"template_labels": dict((template.get("metadata") or {}).get("labels") or {}),
                "selector": dict((spec.get("selector") or {}).get("matchLabels") or {}),
                "refs": _refs(template.get("spec") or {}), "replicas": replicas,
                "conditions": _conditions(status)}
    if kind == "Pod":
        return {"template_labels": dict((obj.get("metadata") or {}).get("labels") or {}), "selector": {},
                "refs": _refs(spec), "replicas": 1, "conditions": _conditions(status),
                "pod_summary": _pod_summary([obj], 1)}
    if kind == "Service":
        hostnames = {i.get("hostname") for i in (status.get("loadBalancer") or {}).get("ingress") or []}
        return {"selector": dict(spec["selector"]) if spec.get("selector") else None,
                "type": spec.get("type") or "ClusterIP",
                "load_balancer_hostnames": sorted(h for h in hostnames if h)}
    if kind == "Ingress":
        backends = {((spec.get("defaultBackend") or {}).get("service") or {}).get("name")}
        for rule in spec.get("rules") or []:
            for path in (rule.get("http") or {}).get("paths") or []:
                backends.add(((path.get("backend") or {}).get("service") or {}).get("name"))
        return {"backends": sorted(b for b in backends if b)}
    if kind == "Node":
        return {"provider_id": spec.get("providerID")}
    if kind == "ConfigMap":
        data, binary = obj.get("data") or {}, obj.get("binaryData") or {}
        canonical = json.dumps({"data": data, "binaryData": binary}, sort_keys=True, separators=(",", ":"))
        return {"keys": sorted({*data, *binary}), "data_sha256": hashlib.sha256(canonical.encode()).hexdigest()}
    if kind == "Secret":
        return {"type": obj.get("type")}
    if kind == "PersistentVolumeClaim":
        return {"storage_class": spec.get("storageClassName"), "volume_name": spec.get("volumeName")}
    if kind == "PodDisruptionBudget":
        selector, has_expressions = _selector(spec.get("selector"))
        return {"selector": selector, "selector_has_expressions": has_expressions}
    if kind == "NetworkPolicy":
        selector, has_expressions = _selector(spec.get("podSelector"))
        return {"pod_selector": selector, "selector_has_expressions": has_expressions}
    return {}


def _selector(value) -> tuple[Optional[dict], bool]:
    """(matchLabels, has matchExpressions). An absent selector is None; a present empty one ({}) selects all."""
    if value is None:
        return None, False
    return dict(value.get("matchLabels") or {}), bool(value.get("matchExpressions"))


def _conditions(status: dict) -> list:
    return sorted(({"type": c.get("type"), "status": c.get("status"), "reason": c.get("reason")}
                   for c in status.get("conditions") or []), key=lambda c: str(c["type"]))


def _refs(pod_spec: dict) -> dict:
    """ConfigMap / Secret / PVC names a pod spec mounts or reads (volumes, projected sources, envFrom, env)."""
    found = {"configmap": set(), "secret": set(), "pvc": set()}

    def add(key, value):
        if value:
            found[key].add(value)

    for vol in pod_spec.get("volumes") or []:
        add("configmap", (vol.get("configMap") or {}).get("name"))
        add("secret", (vol.get("secret") or {}).get("secretName"))
        add("pvc", (vol.get("persistentVolumeClaim") or {}).get("claimName"))
        for src in (vol.get("projected") or {}).get("sources") or []:
            add("configmap", (src.get("configMap") or {}).get("name"))
            add("secret", (src.get("secret") or {}).get("name"))
    for container in (pod_spec.get("containers") or []) + (pod_spec.get("initContainers") or []):
        for env_from in container.get("envFrom") or []:
            add("configmap", (env_from.get("configMapRef") or {}).get("name"))
            add("secret", (env_from.get("secretRef") or {}).get("name"))
        for env in container.get("env") or []:
            value_from = env.get("valueFrom") or {}
            add("configmap", (value_from.get("configMapKeyRef") or {}).get("name"))
            add("secret", (value_from.get("secretKeyRef") or {}).get("name"))
    return {key: sorted(names) for key, names in found.items()}


def _pod_summary(pods: list, desired) -> dict:
    ready = restarts = 0
    waiting, nodes, terminated = set(), set(), []
    for pod in pods:
        status = pod.get("status") or {}
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions") or []):
            ready += 1
        if (pod.get("spec") or {}).get("nodeName"):
            nodes.add(pod["spec"]["nodeName"])
        for cs in (status.get("containerStatuses") or []) + (status.get("initContainerStatuses") or []):
            restarts += int(cs.get("restartCount") or 0)
            reason = ((cs.get("state") or {}).get("waiting") or {}).get("reason")
            if reason:
                waiting.add(reason)
            for which in ("state", "lastState"):
                term = (cs.get(which) or {}).get("terminated") or {}
                if term.get("reason") and term["reason"] != "Completed":   # a finished init container is normal
                    terminated.append((str(term.get("finishedAt") or ""), term["reason"]))
    return {"ready": ready, "desired": desired, "restarts": restarts,
            "last_termination_reason": max(terminated)[1] if terminated else None,
            "waiting_reasons": sorted(waiting), "nodes": sorted(nodes)}


def _status(kind: str, obj: dict) -> str:
    status = obj.get("status") or {}
    if kind == "Node":
        for c in status.get("conditions") or []:
            if c.get("type") == "Ready":
                return {"True": "Ready", "False": "NotReady"}.get(c.get("status"), "Unknown")
        return "Unknown"
    return str(status.get("phase") or "active")[:30]
