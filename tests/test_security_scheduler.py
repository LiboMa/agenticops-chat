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
