"""credentials/kube.kubectl_env_for_cluster (MVP-2.6.1 spec §3.B.4): only the target account's credentials,
a private kubeconfig, never ~/.kube/config, and no ambient fallback."""
import os
import stat
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agenticops.config import settings
from agenticops.credentials.kube import KubeconfigError, kubeconfig_path, kubectl_env_for_cluster
from agenticops.credentials.resolver import AccountResolutionError
from agenticops.run_context import run_context

AMBIENT = {"AWS_ACCESS_KEY_ID": "ambient-access-key-id", "AWS_SECRET_ACCESS_KEY": "ambient-secret",
           "AWS_SESSION_TOKEN": "ambient-token", "AWS_PROFILE": "default", "PATH": "/usr/bin"}


def _aws(pk=1, name="prod", kubeconfigs=None):
    creds = {"account_id": "111111111111"}
    if kubeconfigs is not None:
        creds["kubeconfigs"] = kubeconfigs
    return SimpleNamespace(id=pk, name=name, provider="aws", credentials=creds, regions=["us-east-1"], labels={},
                           credential_source_type="assume_role")


def _session(access="target-access-key-id", secret="target-secret", token="target-token"):
    frozen = SimpleNamespace(access_key=access, secret_key=secret, token=token)
    session = MagicMock()
    session.get_credentials.return_value.get_frozen_credentials.return_value = frozen
    return session


@pytest.fixture
def home(tmp_path, monkeypatch):
    """data_dir and HOME both under tmp_path; the process env holds another account's credentials."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(settings, "k8s_kubeconfig_max_age_seconds", 3600)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(os, "environ", {**AMBIENT, "HOME": str(fake_home)})
    return tmp_path


class _FakeAws:
    """Stands in for `aws eks update-kubeconfig`: writes the --kubeconfig file, records argv and env."""

    def __init__(self, returncode=0, stderr=""):
        self.calls, self.returncode, self.stderr = [], returncode, stderr

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.returncode == 0:
            target = args[args.index("--kubeconfig") + 1]
            with open(target, "w") as f:
                f.write("apiVersion: v1\nkind: Config\n")
        return MagicMock(returncode=self.returncode, stdout="", stderr=self.stderr)


def _patch_resolution(session=None):
    return patch("agenticops.credentials.resolver.resolve_account_session", return_value=session or _session())


def test_aws_env_carries_only_the_target_account_and_a_private_kubeconfig(home):
    fake = _FakeAws()
    with _patch_resolution(), patch("agenticops.credentials.kube.subprocess.run", side_effect=fake):
        env = kubectl_env_for_cluster(_aws(), "lab", "us-east-1")

    path = home / "data" / "kube" / "1" / "us-east-1" / "lab.kubeconfig"
    assert env["KUBECONFIG"] == str(path) and path.is_file()
    assert env["AWS_ACCESS_KEY_ID"] == "target-access-key-id" and env["AWS_SESSION_TOKEN"] == "target-token"
    assert "AWS_PROFILE" not in env and "ambient" not in " ".join(env.values())
    assert env["AWS_DEFAULT_REGION"] == "us-east-1"
    (args, kwargs), = fake.calls
    assert args[:3] == ["aws", "eks", "update-kubeconfig"] and args[args.index("--name") + 1] == "lab"
    assert args[args.index("--region") + 1] == "us-east-1"
    assert os.path.dirname(args[args.index("--kubeconfig") + 1]) == str(path.parent)
    assert kwargs["env"]["AWS_ACCESS_KEY_ID"] == "target-access-key-id" and "AWS_PROFILE" not in kwargs["env"]
    assert kwargs["shell"] is False
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for d in (path.parent, path.parent.parent, path.parent.parent.parent):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert not (home / "home" / ".kube").exists()                       # ~/.kube/config never touched
    assert [p.name for p in path.parent.iterdir()] == ["lab.kubeconfig"]  # no tmp left behind


def test_fresh_kubeconfig_is_reused_and_a_stale_one_regenerated(home):
    fake = _FakeAws()
    with _patch_resolution(), patch("agenticops.credentials.kube.subprocess.run", side_effect=fake):
        kubectl_env_for_cluster(_aws(), "lab", "us-east-1")
        kubectl_env_for_cluster(_aws(), "lab", "us-east-1")
        assert len(fake.calls) == 1
        path = kubeconfig_path(1, "us-east-1", "lab")
        old = path.stat().st_mtime - 3601
        os.utime(path, (old, old))
        kubectl_env_for_cluster(_aws(), "lab", "us-east-1")
    assert len(fake.calls) == 2


def test_accounts_regions_and_clusters_get_separate_files(home):
    fake = _FakeAws()
    with _patch_resolution(), patch("agenticops.credentials.kube.subprocess.run", side_effect=fake):
        paths = {kubectl_env_for_cluster(_aws(pk), cluster, region)["KUBECONFIG"]
                 for pk, cluster, region in [(1, "lab", "us-east-1"), (2, "lab", "us-east-1"),
                                             (1, "lab", "us-west-2"), (1, "lab-2", "us-east-1")]}
    assert len(paths) == 4


def test_generation_failure_raises_and_leaves_nothing(home):
    fake = _FakeAws(returncode=254, stderr="An error occurred (ResourceNotFoundException): No cluster found")
    with _patch_resolution(), patch("agenticops.credentials.kube.subprocess.run", side_effect=fake):
        with pytest.raises(KubeconfigError, match="No cluster found"):
            kubectl_env_for_cluster(_aws(), "lab", "us-east-1")
    assert list(kubeconfig_path(1, "us-east-1", "lab").parent.iterdir()) == []


def test_resolution_failure_propagates_before_any_subprocess(home):
    with patch("agenticops.credentials.resolver.resolve_account_session",
               side_effect=AccountResolutionError("AssumeRole denied")), \
         patch("agenticops.credentials.kube.subprocess.run") as run:
        with pytest.raises(AccountResolutionError, match="AssumeRole denied"):
            kubectl_env_for_cluster(_aws(), "lab", "us-east-1")
    assert not run.called


@pytest.mark.parametrize("cluster,region", [("../etc", "us-east-1"), ("lab", "../../x"), ("", "us-east-1"),
                                            ("lab", ""), ("a/b", "us-east-1")])
def test_unsafe_or_empty_path_components_are_refused(home, cluster, region):
    with _patch_resolution(), patch("agenticops.credentials.kube.subprocess.run") as run:
        with pytest.raises(KubeconfigError):
            kubectl_env_for_cluster(_aws(), cluster, region)
    assert not run.called


def test_registered_kubeconfig_is_used_with_the_account_env(home):
    kc = home / "incluster.kubeconfig"
    kc.write_text("apiVersion: v1\n")
    with _patch_resolution(), patch("agenticops.credentials.kube.subprocess.run") as run:
        env = kubectl_env_for_cluster(_aws(kubeconfigs={"lab": str(kc)}), "lab", "us-east-1")
    assert env["KUBECONFIG"] == str(kc) and env["AWS_ACCESS_KEY_ID"] == "target-access-key-id"
    assert not run.called


def test_registered_kubeconfig_is_only_for_its_cluster(home):
    kc = home / "incluster.kubeconfig"
    kc.write_text("apiVersion: v1\n")
    fake = _FakeAws()
    with _patch_resolution(), patch("agenticops.credentials.kube.subprocess.run", side_effect=fake):
        env = kubectl_env_for_cluster(_aws(kubeconfigs={"lab": str(kc)}), "other", "us-east-1")
    assert env["KUBECONFIG"] == str(kubeconfig_path(1, "us-east-1", "other")) and len(fake.calls) == 1


@pytest.mark.parametrize("value", ["relative/kubeconfig", "/nonexistent/kubeconfig", "~/.kube/config"])
def test_bad_registered_kubeconfig_is_refused(home, value):
    shared = home / "home" / ".kube" / "config"
    if value.startswith("~"):
        shared.parent.mkdir()
        shared.write_text("apiVersion: v1\n")
        value = str(shared)
    with _patch_resolution(), patch("agenticops.credentials.kube.subprocess.run") as run:
        with pytest.raises(KubeconfigError, match="kubeconfigs"):
            kubectl_env_for_cluster(_aws(kubeconfigs={"lab": value}), "lab", "us-east-1")
    assert not run.called


def _k8s(pk=5, kubeconfig=""):
    return SimpleNamespace(id=pk, name="onprem", provider="kubernetes",
                           credentials={"kubeconfig_path": kubeconfig, "context": "ctx"}, regions=[], labels={},
                           credential_source_type="")


def test_kubernetes_account_uses_its_own_kubeconfig_without_cloud_credentials(home):
    kc = home / "onprem.kubeconfig"
    kc.write_text("apiVersion: v1\n")
    env = kubectl_env_for_cluster(_k8s(kubeconfig=str(kc)), "onprem", "")
    assert env["KUBECONFIG"] == str(kc)
    assert not any(k.startswith("AWS_") for k in env)


def test_kubernetes_account_with_a_missing_kubeconfig_fails(home):
    with pytest.raises(KubeconfigError, match="onprem"):
        kubectl_env_for_cluster(_k8s(kubeconfig=str(home / "missing")), "onprem", "")


@pytest.mark.parametrize("creds", [{"context": "ctx"}, {"kubeconfig_path": "", "context": "ctx"}])
def test_kubernetes_account_without_a_kubeconfig_path_never_falls_back_to_the_shared_one(home, creds):
    """An unset kubeconfig_path is a credential failure, not a silent ~/.kube/config (铁律 #2), even when that
    shared file exists; no kubectl or other subprocess is started."""
    from agenticops.providers.kubernetes import KubernetesProvider

    shared = home / "home" / ".kube" / "config"
    shared.parent.mkdir()
    shared.write_text("apiVersion: v1\n")
    acct = SimpleNamespace(id=5, name="onprem", provider="kubernetes", credentials=creds, regions=[], labels={},
                           credential_source_type="")
    with patch("agenticops.providers.kubernetes.subprocess.run") as run:
        with pytest.raises(KubeconfigError, match="onprem"):
            kubectl_env_for_cluster(acct, "onprem", "")
        with pytest.raises(RuntimeError, match="onprem"):
            KubernetesProvider(acct)._run_kubectl("kubectl get pods")
    assert not run.called


def test_a_bound_run_refuses_another_kubernetes_account(home):
    kc = home / "onprem.kubeconfig"
    kc.write_text("apiVersion: v1\n")
    with run_context(bound_account_id=1):
        with pytest.raises(AccountResolutionError, match="bound to account id=1"):
            kubectl_env_for_cluster(_k8s(pk=5, kubeconfig=str(kc)), "onprem", "")


def test_other_providers_are_refused(home):
    acct = SimpleNamespace(id=9, name="az", provider="azure", credentials={}, regions=[], labels={},
                           credential_source_type="")
    with pytest.raises(AccountResolutionError, match="azure"):
        kubectl_env_for_cluster(acct, "aks", "eastus")
