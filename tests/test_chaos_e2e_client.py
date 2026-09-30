import sys, types, importlib.util, pathlib
import pytest

# Load client.py from infra/ (not a package) by path.
_CLIENT = pathlib.Path(__file__).resolve().parents[1] / "infra/eks-chaos-lab/e2e/client.py"
spec = importlib.util.spec_from_file_location("chaos_e2e_client", _CLIENT)
client_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_mod)
AgenticOpsClient = client_mod.AgenticOpsClient
PhaseTimeout = client_mod.PhaseTimeout


class _FakeResp:
    def __init__(self, status, payload): self.status_code, self._p = status, payload
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


def _mk(monkeypatch, sequence):
    """monkeypatch client.get to return successive payloads from `sequence`."""
    calls = {"i": 0}
    def fake_get(path):
        p = sequence[min(calls["i"], len(sequence) - 1)]
        calls["i"] += 1
        return p
    return calls, fake_get


def test_find_recent_issue_matches_pattern_and_skips_resolved(monkeypatch):
    c = AgenticOpsClient("http://x")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    payload = [
        {"id": 1, "title": "old resolved", "description": "", "status": "resolved", "detected_at": now},
        {"id": 2, "title": "frontend replicas scaled to zero", "description": "", "status": "open", "detected_at": now},
    ]
    monkeypatch.setattr(c, "get", lambda path: payload)
    assert c.find_recent_issue(r"replicas|scaled") == 2


def test_wait_for_status_raises_phasetimeout_named(monkeypatch):
    c = AgenticOpsClient("http://x")
    monkeypatch.setattr(c, "get", lambda path: {"status": "investigating"})
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(client_mod.time, "monotonic", _fake_clock([0, 1, 2, 3, 999]))
    with pytest.raises(PhaseTimeout) as ei:
        c.wait_for_status(5, {"resolved"}, timeout_s=2)
    assert "resolve" in str(ei.value).lower() or ei.value.phase == "resolve"


def _fake_clock(values):
    it = iter(values)
    last = [0]
    def clock():
        try: last[0] = next(it)
        except StopIteration: pass
        return last[0]
    return clock


def _record(monkeypatch, c, accounts):
    """client.get returns `accounts`; post / put calls are recorded as (method, path, json)."""
    calls = []
    monkeypatch.setattr(c, "get", lambda path: accounts)
    monkeypatch.setattr(c, "post", lambda path, json=None, headers=None: calls.append(("POST", path, json)))
    monkeypatch.setattr(c, "put", lambda path, json=None: calls.append(("PUT", path, json)))
    return calls


def test_ensure_account_registers_the_cluster_kubeconfig(monkeypatch):
    """MVP-2.6.1: kubectl uses only a kubeconfig registered on the account, so the chaos-lab account carries it —
    on create, and added to an account created before 2.6.1; an up-to-date account is left alone."""
    kc = {"agenticops-chaos-lab": "/var/run/agenticops/kubeconfig"}
    creds = {"account_id": "111111111111", "kubeconfigs": kc}
    c = AgenticOpsClient("http://x")

    calls = _record(monkeypatch, c, [])
    c.ensure_account("chaos-lab", "111111111111", ["us-east-1"], kubeconfigs=kc)
    assert calls == [("POST", "/api/accounts", {"name": "chaos-lab", "provider": "aws",
                                                "credential_source_type": "environment", "credentials": creds,
                                                "regions": ["us-east-1"], "is_enabled": True})]

    calls = _record(monkeypatch, c, [{"id": 7, "name": "chaos-lab", "credentials": {"account_id": "111111111111"}}])
    c.ensure_account("chaos-lab", "111111111111", ["us-east-1"], kubeconfigs=kc)
    assert calls == [("PUT", "/api/accounts/7", {"credentials": creds})]

    calls = _record(monkeypatch, c, [{"id": 7, "name": "chaos-lab", "credentials": creds}])
    c.ensure_account("chaos-lab", "111111111111", ["us-east-1"], kubeconfigs=kc)
    c.ensure_account("chaos-lab", "111111111111", ["us-east-1"])
    assert calls == []
