"""MVP-2.6.1 Plan C config surface: values live in settings.yaml, config.py is schema only."""
import yaml

from agenticops.config import PROJECT_ROOT, settings

KEYS = (
    "rca_k8s_recollect_min_age_seconds",
    "rca_k8s_recollect_timeout_seconds",
    "policy_graph_impact_enforce",
)


def test_defaults():
    assert settings.rca_k8s_recollect_min_age_seconds == 120
    assert settings.rca_k8s_recollect_timeout_seconds == 60
    assert settings.policy_graph_impact_enforce is False


def test_yaml_carries_the_values_not_only_the_schema():
    data = yaml.safe_load((PROJECT_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    for key in KEYS:
        assert key in data, f"{key} missing from config/settings.yaml"
        assert data[key] == getattr(settings, key), (
            f"{key}: settings.yaml has {data[key]!r} but settings resolves to {getattr(settings, key)!r}"
        )
