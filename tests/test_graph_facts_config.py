"""MVP-2.6.1 Plan A config surface: values live in settings.yaml, config.py is schema only."""
import yaml

from agenticops.config import PROJECT_ROOT, settings

KEYS = (
    "identity_alarm_name_patterns",
    "identity_type_families",
    "graph_query_node_cap",
    "graph_query_edge_cap",
    "graph_query_max_depth",
    "rca_topology_window_before_minutes",
    "rca_topology_window_after_minutes",
)


def test_defaults():
    assert settings.identity_alarm_name_patterns == ["^EKS-(?P<cluster>.+)-[A-Za-z0-9]+-[A-Za-z0-9]+$"]
    assert settings.identity_type_families == {"EKS": ["EKS", "EKS_Cluster"]}
    assert (settings.graph_query_node_cap, settings.graph_query_edge_cap) == (200, 500)
    assert settings.graph_query_max_depth == 2
    assert settings.rca_topology_window_before_minutes == 30
    assert settings.rca_topology_window_after_minutes == 10


def test_yaml_carries_the_values_not_only_the_schema():
    data = yaml.safe_load((PROJECT_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    for key in KEYS:
        assert key in data, f"{key} missing from config/settings.yaml"
        assert data[key] == getattr(settings, key), (
            f"{key}: settings.yaml has {data[key]!r} but settings resolves to {getattr(settings, key)!r}"
        )
