from agenticops.config import settings


class TestSecurityConfig:
    def test_security_config_defaults(self):
        assert settings.security_review_enabled is True
        assert settings.security_poll_interval_minutes == 10
        assert settings.security_posture_interval_minutes == 60
        assert settings.security_reachability_nacl_enabled is True
        assert settings.security_advisor_enabled is True
        assert settings.security_advisor_critic_enabled is True
        assert settings.security_snapshot_retention_days == 90
        assert settings.security_model_id == ""


class TestSecurityJobStubs:
    def test_run_posture_snapshot_no_accounts_returns_zero(self):
        # Hermetic: no enabled accounts -> loop body never runs -> 0, zero AWS I/O.
        from unittest.mock import patch
        from agenticops.security import posture_snapshot
        with patch.object(posture_snapshot, "_resolve_security_accounts", return_value=[]):
            assert posture_snapshot.run_posture_snapshot() == 0

    def test_run_posture_snapshot_writes_one_per_account(self):
        # Hermetic: mock the whole I/O boundary (account resolve + collector + scorer
        # + DB session) so no live cross-account AWS calls. Asserts the real body's
        # orchestration: N accounts -> N SecuritySnapshot writes, returns N.
        from unittest.mock import patch, MagicMock
        from agenticops.security import posture_snapshot
        result = MagicMock(overall_score=90, category_scores={}, metrics={}, cis_results={})
        sess = MagicMock()
        cm = MagicMock()
        cm.__enter__.return_value = sess
        cm.__exit__.return_value = False
        with patch.object(posture_snapshot, "_resolve_security_accounts",
                          return_value=["acct-a", "acct-b"]), \
             patch.object(posture_snapshot, "collect_posture", return_value=[]) as m_collect, \
             patch.object(posture_snapshot, "score", return_value=result), \
             patch.object(posture_snapshot, "get_db_session", return_value=cm):
            n = posture_snapshot.run_posture_snapshot()
        assert n == 2
        assert m_collect.call_count == 2
        assert sess.add.call_count == 2

    def test_run_posture_snapshot_isolates_per_account_failure(self):
        # The docstring promises per-account failure isolation: one account's collector
        # raising must not abort the others. bad -> raises, good -> writes. Returns 1.
        from unittest.mock import patch, MagicMock
        from agenticops.security import posture_snapshot
        result = MagicMock(overall_score=90, category_scores={}, metrics={}, cis_results={})
        sess = MagicMock()
        cm = MagicMock()
        cm.__enter__.return_value = sess
        cm.__exit__.return_value = False

        def collect_side_effect(account):
            if account == "bad":
                raise RuntimeError("boom")
            return []

        with patch.object(posture_snapshot, "_resolve_security_accounts",
                          return_value=["bad", "good"]), \
             patch.object(posture_snapshot, "collect_posture", side_effect=collect_side_effect), \
             patch.object(posture_snapshot, "score", return_value=result), \
             patch.object(posture_snapshot, "get_db_session", return_value=cm):
            n = posture_snapshot.run_posture_snapshot()
        assert n == 1
        assert sess.add.call_count == 1

    def test_run_incremental_poll_returns_int(self):
        from unittest.mock import patch
        from agenticops.security import incremental_poll
        # Hermetic: no enabled accounts -> zero emissions, no AWS/DB access.
        with patch.object(incremental_poll, "_resolve_security_accounts", return_value=[]):
            assert incremental_poll.run_incremental_poll() == 0

    def test_cron_from_interval_minutes(self):
        # helper mirrors galaxy seed's <60 -> */N, >=60 -> 0 */(N//60)
        from agenticops.security.posture_snapshot import cron_from_interval
        assert cron_from_interval(10) == "*/10 * * * *"
        assert cron_from_interval(60) == "0 */1 * * *"
        assert cron_from_interval(120) == "0 */2 * * *"
        assert cron_from_interval(0) == "*/1 * * * *"  # clamp to >=1
