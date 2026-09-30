"""Account-addressed kubectl credentials (MVP-2.6.1 spec §3.B.4), shared by run_kubectl and the K8s connector.

kubectl_env_for_cluster() builds the only env a kubectl subprocess may run with:

- aws account: get_subprocess_env_for_account (every ambient AWS_* stripped, the target account's frozen
  credentials injected) plus KUBECONFIG=<a private file>. The file is either the one registered on the account
  (credentials.kubeconfigs[<cluster>], e.g. an in-cluster service-account kubeconfig) or
  <data_dir>/kube/<account pk>/<credential fingerprint>/<region>/<cluster>.kubeconfig, written by
  `aws eks update-kubeconfig --kubeconfig` under that same env. The fingerprint (credential source type +
  credentials, kubeconfigs excluded) keys the file to the credentials it was generated under, so an account whose
  credentials were re-pointed, or a reused pk, never gets another account's file. The kubeconfig's
  `aws eks get-token` exec plugin inherits the env, so the token is the target account's too.
- kubernetes account: KubernetesProvider._kubectl_env — the account's own, explicitly configured kubeconfig_path.

~/.kube/config and the process KUBECONFIG are never used implicitly or as a fallback, and no shared
current-context is switched. Every failure raises (KubeconfigError / AccountResolutionError); there is no ambient
fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from agenticops.config import settings
from agenticops.credentials.resolver import AccountResolutionError, get_subprocess_env_for_account

UPDATE_TIMEOUT = 15
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")  # fullmatch: "lab\n" is refused
_SHARED = Path("~/.kube/config")


class KubeconfigError(RuntimeError):
    """No private kubeconfig could be produced. Callers report it; nothing falls back to ambient."""


def kubeconfig_path(account: SimpleNamespace, region: str, cluster: str) -> Path:
    """<data_dir>/kube/<account pk>/<credential fingerprint>/<region>/<cluster>.kubeconfig. The pk alone is not an
    account identity (a PUT re-points it, SQLite reuses it), so the fingerprint is part of the key (铁律 #4).
    Region and cluster become path components, so anything that could climb out of the directory is refused."""
    for part in (region, cluster):
        if not _SAFE.fullmatch(part or ""):
            raise KubeconfigError(f"unsafe kubeconfig path component {part!r}")
    return (Path(settings.data_dir) / "kube" / str(int(account.id)) / _fingerprint(account) / region
            / f"{cluster}.kubeconfig")


def _fingerprint(account: SimpleNamespace) -> str:
    """16 hex chars over the credential source and credentials. kubeconfigs is left out: registering a kubeconfig
    for one cluster does not change whose credentials a generated file was made with."""
    material = {"source": account.credential_source_type,
                "credentials": {k: v for k, v in account.credentials.items() if k != "kubeconfigs"}}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:16]


def kubectl_env_for_cluster(account: SimpleNamespace, cluster: str, region: str) -> dict:
    """The env for one kubectl subprocess against `cluster`, carrying only `account`'s credentials.

    `account` is a credentials.resolver snapshot. Raises AccountResolutionError when the account cannot be
    resolved (or the current run is bound to another account) and KubeconfigError when no kubeconfig can be
    produced. For a kubernetes account the env carries KUBECONFIG only, not the account's context: callers pass
    `--context` from account.credentials["context"] themselves (as KubernetesProvider._run_kubectl does)."""
    if account.provider == "kubernetes":
        return _kubernetes_env(account)
    if account.provider != "aws":
        raise AccountResolutionError(
            f"kubectl credentials are not supported for {account.provider} account '{account.name}'")
    kubeconfigs = account.credentials.get("kubeconfigs") or {}
    if not isinstance(kubeconfigs, dict):
        raise KubeconfigError(f"account '{account.name}': credentials.kubeconfigs must map cluster name to path, "
                              f"got {type(kubeconfigs).__name__}")
    env = get_subprocess_env_for_account(account, region)
    registered = kubeconfigs.get(cluster)
    path = _registered(account, cluster, registered) if registered else _generated(account, cluster, region, env)
    env["KUBECONFIG"] = str(path)
    return env


def _kubernetes_env(account: SimpleNamespace) -> dict:
    # resolve_account_session checks the run binding for aws accounts; this path does not go through it.
    from agenticops.run_context import get_run_context
    bound = get_run_context().bound_account_id
    if bound is not None and account.id != bound:
        raise AccountResolutionError(
            f"this run is bound to account id={bound}; refusing to resolve account "
            f"'{account.name}' (id={account.id})")
    from agenticops.providers.kubernetes import KubernetesProvider
    provider = KubernetesProvider(account)
    if not provider.resolve_credentials():
        raise KubeconfigError(f"kubernetes account '{account.name}': kubeconfig_path not configured or file missing")
    return provider._kubectl_env()


def _registered(account: SimpleNamespace, cluster: str, value) -> Path:
    path = Path(str(value))
    if not path.is_absolute() or not path.is_file():
        raise KubeconfigError(
            f"account '{account.name}': kubeconfigs[{cluster!r}] must be an absolute path to an existing file, "
            f"got {value!r}")
    if path.resolve() == _SHARED.expanduser().resolve():
        raise KubeconfigError(f"account '{account.name}': kubeconfigs[{cluster!r}] may not be the shared ~/.kube/config")
    return path


def _generated(account: SimpleNamespace, cluster: str, region: str, env: dict) -> Path:
    path = kubeconfig_path(account, region, cluster)
    try:
        # A future mtime (clock skew, a touched file) is not "fresh": it would otherwise be reused indefinitely.
        if 0 <= time.time() - path.stat().st_mtime < settings.k8s_kubeconfig_max_age_seconds:
            return path
    except FileNotFoundError:
        pass
    root = Path(settings.data_dir) / "kube"
    root.parent.mkdir(parents=True, exist_ok=True)
    for d in (root, path.parents[2], path.parents[1], path.parents[0]):  # kube, <pk>, <fp>, <region>
        d.mkdir(mode=0o700, exist_ok=True)
    # Unique per writer, then os.replace: concurrent generators never see a half-written file.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        try:
            result = subprocess.run(
                ["aws", "eks", "update-kubeconfig", "--name", cluster, "--region", region, "--kubeconfig", str(tmp)],
                capture_output=True, text=True, timeout=UPDATE_TIMEOUT, shell=False, env=env)
        except subprocess.TimeoutExpired:
            raise KubeconfigError(f"aws eks update-kubeconfig timed out after {UPDATE_TIMEOUT}s") from None
        except FileNotFoundError:
            raise KubeconfigError("aws CLI not found on PATH") from None
        if result.returncode != 0:
            raise KubeconfigError(result.stderr.strip()[:2000] or f"aws eks update-kubeconfig exit {result.returncode}")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path
