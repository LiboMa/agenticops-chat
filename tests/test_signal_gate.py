"""Signal Gate (MVP-2.2.0) — identity, classification, L1 rules, L2 LLM fallback.

Run:
    pytest tests/test_signal_gate.py -v
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from agenticops.models import (
    AlertEvent,
    Base,
    HealthIssue,
    RCAResult,
    get_session,
    validate_status_transition,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def db_session(tmp_path):
    """Temporary SQLite database (same pattern as test_fix_plan_consolidation)."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/test_signal_gate.db"

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def gate_settings():
    """Pin gate settings to spec defaults for deterministic tests."""
    from agenticops.config import settings

    saved = {
        k: getattr(settings, k)
        for k in (
            "signal_gate_enabled", "signal_gate_llm_enabled",
            "signal_gate_confidence_min", "noise_flap_threshold",
            "noise_flap_window_minutes", "resource_dedup_enabled",
            "dedup_resolved_cooldown_minutes", "issue_exclude_patterns",
        )
    }
    settings.signal_gate_enabled = True
    settings.signal_gate_llm_enabled = True
    settings.signal_gate_confidence_min = 0.7
    settings.noise_flap_threshold = 3
    settings.noise_flap_window_minutes = 30
    settings.resource_dedup_enabled = True
    settings.dedup_resolved_cooldown_minutes = 60
    settings.issue_exclude_patterns = []
    yield settings
    for k, v in saved.items():
        setattr(settings, k, v)


def _sig(**kw):
    from agenticops.services.signal_gate import SignalInput

    defaults = dict(
        source="webhook_prometheus",
        title="High CPU on i-abc123",
        description="CPU above 90%",
        severity="high",
        resource_id="i-abc123",
        account_id="123456789012",
        provider="aws",
        issue_type="cpu_spike",
        upstream_key="promfp001",
        kind="alert",
        auto_rca=False,
    )
    defaults.update(kw)
    return SignalInput(**defaults)


def _process(sig):
    """process_signal with RCA/notify side-effects stubbed out."""
    from agenticops.services import signal_gate

    with patch("agenticops.services.rca_service.trigger_auto_rca"), \
         patch("agenticops.services.notification_service.notify_issue_created"):
        return signal_gate.process_signal(sig)


# ── Schema / migration surface ────────────────────────────────────────


class TestSchema:
    def test_new_columns_roundtrip(self, db_session):
        evt = AlertEvent(
            source="webhook_prometheus", external_id="x1", severity="high",
            title="t", kind="detection", fingerprint="f" * 64,
            resource_id="i-1", account_id="acct", issue_type="cpu_spike",
            disposition="noise", disposition_reason="flapping",
            gate_evidence={"rule": "flapping"},
        )
        issue = HealthIssue(
            resource_id="i-1", severity="high", source="s", title="t",
            description="d", issue_type="cpu_spike",
        )
        db_session.add_all([evt, issue])
        db_session.flush()
        rca = RCAResult(
            health_issue_id=issue.id, root_cause="rc", confidence=0.5,
            evidence=[{"type": "metric", "ref": "CPUUtilization", "summary": "s"}],
            evidence_verified=False, critic_verdict="weak",
        )
        db_session.add(rca)
        db_session.commit()

        assert db_session.query(AlertEvent).filter_by(disposition="noise").count() == 1
        assert db_session.query(HealthIssue).filter_by(issue_type="cpu_spike").count() == 1
        got = db_session.query(RCAResult).first()
        assert got.evidence[0]["ref"] == "CPUUtilization"
        assert got.evidence_verified is False

    def test_rca_rerun_transition_legal(self):
        validate_status_transition("root_cause_identified", "investigating")


# ── Identity & classification ─────────────────────────────────────────


class TestFingerprintV2:
    def _fp(self, **kw):
        from agenticops.services.signal_gate import compute_fingerprint_v2

        d = dict(account_id="a", provider="aws", resource_id="i-1",
                 issue_type="cpu_spike", upstream_key="k1", title="")
        d.update(kw)
        return compute_fingerprint_v2(**d)

    def test_title_drift_same_identity(self):
        assert self._fp(title="CPU 91% spike") == self._fp(title="CPU 97% sustained!!")

    def test_components_change_identity(self):
        base = self._fp()
        assert self._fp(resource_id="i-2") != base
        assert self._fp(issue_type="memory_pressure") != base
        assert self._fp(upstream_key="k2") != base

    def test_title_fallback_when_no_resource_or_key(self):
        a = self._fp(resource_id="", upstream_key="", title="Disk 91% full")
        b = self._fp(resource_id="", upstream_key="", title="Disk 97% full")
        c = self._fp(resource_id="", upstream_key="", title="IAM key exposed")
        assert a == b
        assert a != c


class TestClassifyIssueType:
    def test_classification(self):
        from agenticops.services.signal_gate import classify_issue_type

        assert classify_issue_type("High CPU", metric="CPUUtilization") == "cpu_spike"
        assert classify_issue_type("", alertname="NetworkFlapDetected") == "network_flap"
        assert classify_issue_type("Security group 0.0.0.0/0 on port 22") == "security_exposure"
        assert classify_issue_type("Disk usage 95% on /data") == "disk_full"
        assert classify_issue_type("certificate expires in 5 days") == "cert_expiry"
        assert classify_issue_type("something entirely novel") == "other"


# ── L1 deterministic rules ────────────────────────────────────────────


class TestL1Rules:
    def test_promote_then_exact_fingerprint_merge(self, db_session, gate_settings):
        d1 = _process(_sig())
        assert (d1.disposition, d1.created) == ("promoted", True)

        d2 = _process(_sig(title="High CPU on i-abc123 (repeat)"))
        assert (d2.disposition, d2.reason) == ("merged", "exact_fingerprint")
        assert d2.issue_id == d1.issue_id

        issue = db_session.get(HealthIssue, d1.issue_id)
        assert issue.occurrence_count == 2
        assert db_session.query(AlertEvent).count() == 2

    def test_exclude_pattern_noise(self, db_session, gate_settings):
        gate_settings.issue_exclude_patterns = [r"(?i)maintenance window"]
        d = _process(_sig(title="Maintenance window CPU blip"))
        assert (d.disposition, d.reason) == ("noise", "excluded_pattern")
        assert d.issue_id is None
        assert db_session.query(HealthIssue).count() == 0
        row = db_session.query(AlertEvent).one()
        assert row.disposition == "noise"

    def test_resolved_cooldown_merges(self, db_session, gate_settings):
        d1 = _process(_sig())
        issue = db_session.get(HealthIssue, d1.issue_id)
        issue.status = "resolved"
        issue.resolved_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db_session.commit()

        d2 = _process(_sig())
        assert (d2.disposition, d2.reason) == ("merged", "resolved_cooldown")
        assert d2.issue_id == d1.issue_id
        assert db_session.query(HealthIssue).count() == 1

    def test_flapping_noise_after_threshold(self, db_session, gate_settings):
        # resolved long ago so cooldown doesn't swallow; flap counted on signals
        d1 = _process(_sig())
        issue = db_session.get(HealthIssue, d1.issue_id)
        issue.status = "resolved"
        issue.resolved_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db_session.commit()

        _process(_sig())   # 2nd signal in window → new issue (promoted)
        # resolve it again to keep flapping visible to rule
        for i in db_session.query(HealthIssue).filter(HealthIssue.status != "resolved"):
            i.status = "resolved"
            i.resolved_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db_session.commit()

        d3 = _process(_sig())  # 3rd same-fingerprint signal within window → flap threshold hit
        assert (d3.disposition, d3.reason) == ("noise", "flapping")
        assert db_session.query(AlertEvent).filter_by(disposition="noise").count() == 1

    def test_resource_type_merge_requires_same_type(self, db_session, gate_settings):
        d1 = _process(_sig(upstream_key="kA", title="CPU way high"))
        # same resource+type, different wording/key → resource_type_merge
        d2 = _process(_sig(upstream_key="kB", title="CPU pegged at 99", source="cloudwatch_alarm"))
        assert (d2.disposition, d2.reason) == ("merged", "resource_type_merge")
        assert d2.issue_id == d1.issue_id
        # same resource, DIFFERENT type → not L1-merged (promotes; L2 disabled here)
        gate_settings.signal_gate_llm_enabled = False
        d3 = _process(_sig(upstream_key="kC", issue_type="security_exposure",
                           title="port 22 open to world"))
        assert d3.disposition == "promoted"

    def test_resolution_kind_updates_never_creates(self, db_session, gate_settings):
        d1 = _process(_sig())
        d2 = _process(_sig(kind="resolution", title="[RESOLVED] High CPU"))
        assert d2.disposition == "merged"
        assert d2.reason == "resolution_update"
        assert d2.issue_id == d1.issue_id
        assert db_session.query(HealthIssue).count() == 1
        # orphan resolution → noise, still no issue
        d3 = _process(_sig(kind="resolution", upstream_key="other-key",
                           resource_id="i-zzz", title="[RESOLVED] whatever"))
        assert (d3.disposition, d3.reason) == ("noise", "orphan_resolution")
        assert db_session.query(HealthIssue).count() == 1


# ── L2 LLM gray zone ─────────────────────────────────────────────────


class TestL2Llm:
    def _seed_neighbor(self, db_session, gate_settings):
        d = _process(_sig(upstream_key="kA", issue_type="connectivity",
                          title="Instance unreachable via ssh"))
        return d.issue_id

    def _gray_sig(self):
        # same resource, different type+key wording → L1 misses, L2 triggers
        return _sig(upstream_key="kB", issue_type="network_flap",
                    title="eth0 link flapping on i-abc123")

    def test_llm_merge_high_confidence(self, db_session, gate_settings):
        target = self._seed_neighbor(db_session, gate_settings)
        verdict = json.dumps({"action": "merge", "target_issue_id": target,
                              "confidence": 0.9, "reason": "same NIC fault"})
        with patch("agenticops.services.signal_gate._call_bedrock",
                   return_value=(verdict, {"input": 10, "output": 10})):
            d = _process(self._gray_sig())
        assert (d.disposition, d.reason) == ("merged", "llm_merge")
        assert d.issue_id == target
        row = db_session.query(AlertEvent).order_by(AlertEvent.id.desc()).first()
        assert row.gate_evidence.get("llm", {}).get("confidence") == 0.9

    def test_llm_low_confidence_promotes(self, db_session, gate_settings):
        target = self._seed_neighbor(db_session, gate_settings)
        verdict = json.dumps({"action": "merge", "target_issue_id": target,
                              "confidence": 0.5, "reason": "maybe"})
        with patch("agenticops.services.signal_gate._call_bedrock",
                   return_value=(verdict, {"input": 10, "output": 10})):
            d = _process(self._gray_sig())
        assert d.disposition == "promoted"

    def test_llm_can_never_output_noise(self, db_session, gate_settings):
        self._seed_neighbor(db_session, gate_settings)
        verdict = json.dumps({"action": "noise", "confidence": 0.99, "reason": "drop it"})
        with patch("agenticops.services.signal_gate._call_bedrock",
                   return_value=(verdict, {"input": 10, "output": 10})):
            d = _process(self._gray_sig())
        assert d.disposition == "promoted"  # coerced fail-open

    def test_llm_error_promotes(self, db_session, gate_settings):
        self._seed_neighbor(db_session, gate_settings)
        with patch("agenticops.services.signal_gate._call_bedrock",
                   side_effect=RuntimeError("bedrock down")):
            d = _process(self._gray_sig())
        assert d.disposition == "promoted"


# ── Gate disabled fallback ────────────────────────────────────────────


class TestGateDisabled:
    def test_disabled_keeps_legacy_dedup_only(self, db_session, gate_settings):
        gate_settings.signal_gate_enabled = False
        d1 = _process(_sig())
        d2 = _process(_sig())          # exact fingerprint still merges (legacy parity)
        assert d1.disposition == "promoted"
        assert (d2.disposition, d2.reason) == ("merged", "exact_fingerprint")
        # flapping rule must NOT fire when disabled
        for i in db_session.query(HealthIssue).all():
            i.status = "resolved"
            i.resolved_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db_session.commit()
        d3 = _process(_sig())
        assert d3.disposition == "promoted"
