"""MVP-2.6.1 Plan B config surface: values live in settings.yaml, config.py is schema only."""
import yaml

from agenticops.config import PROJECT_ROOT, settings

KEYS = (
    "k8s_kubeconfig_max_age_seconds",
)


def test_defaults():
    assert settings.k8s_kubeconfig_max_age_seconds == 3600


def test_yaml_carries_the_values_not_only_the_schema():
    data = yaml.safe_load((PROJECT_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    for key in KEYS:
        assert key in data, f"{key} missing from config/settings.yaml"
        assert data[key] == getattr(settings, key), (
            f"{key}: settings.yaml has {data[key]!r} but settings resolves to {getattr(settings, key)!r}"
        )
