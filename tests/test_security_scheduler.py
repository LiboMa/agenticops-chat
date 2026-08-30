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
    def test_run_posture_snapshot_stub_returns_int(self):
        from agenticops.security.posture_snapshot import run_posture_snapshot
        assert run_posture_snapshot() == 0

    def test_run_incremental_poll_stub_returns_int(self):
        from agenticops.security.incremental_poll import run_incremental_poll
        assert run_incremental_poll() == 0

    def test_cron_from_interval_minutes(self):
        # helper mirrors galaxy seed's <60 -> */N, >=60 -> 0 */(N//60)
        from agenticops.security.posture_snapshot import cron_from_interval
        assert cron_from_interval(10) == "*/10 * * * *"
        assert cron_from_interval(60) == "0 */1 * * *"
        assert cron_from_interval(120) == "0 */2 * * *"
        assert cron_from_interval(0) == "*/1 * * * *"  # clamp to >=1
