"""Graph tools are account-addressed (credential rule 3, MVP-2.6.1): explicit account →
the VPC's inventory account → the single enabled account → fail closed naming the accounts.
A failed topology read is an error, never an empty graph (an empty graph reads as "all clear")."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.graph import api as graph_api
from agenticops.graph import tools as T
from agenticops.models import CloudAccount, CloudResource, init_db
from agenticops.providers.base import _session_cache


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    s = sessionmaker(bind=engine)()

    @contextmanager
    def fake_db():
        yield s

    monkeypatch.setattr("agenticops.models.get_db_session", fake_db)
    _session_cache.clear()
    yield s
    _session_cache.clear()
    s.close()
    engine.dispose()


def _account(db, name, vpc_id=""):
    a = CloudAccount(name=name, provider="aws", is_enabled=True, credentials={}, regions=["r"])
    db.add(a)
    db.flush()
    if vpc_id:
        db.add(CloudResource(account_id=a.id, provider="aws", region="r", resource_type="VPC",
                             resource_id=vpc_id, name=vpc_id, tags={}, raw_data={}))
    db.commit()
    return a


def test_account_resolution_order(db):
    _account(db, "prod", "vpc-1")
    _account(db, "staging")
    assert T._vpc_account("vpc-1", "staging") == "staging"  # explicit first
    assert T._vpc_account("vpc-1", "") == "prod"            # then the VPC's inventory account
    assert T._vpc_account("vpc-9", "") == ""                # else the provider layer's default


def test_enriched_builder_passes_the_resolved_account_down(db):
    _account(db, "prod", "vpc-1")
    topo = json.dumps({"vpc_id": "vpc-1"})
    with patch("agenticops.tools.network_tools.analyze_vpc_topology", return_value=topo) as vt, \
         patch("agenticops.graph.collectors.collect_vpc_compute", return_value={}) as cc:
        T._build_enriched_vpc_graph("r", "vpc-1")
    vt.assert_called_once_with(region="r", vpc_id="vpc-1", account="prod")
    cc.assert_called_once_with("r", "vpc-1", "prod")


def test_ambiguous_account_is_an_error_naming_the_accounts(db):
    _account(db, "prod")
    _account(db, "staging")  # two accounts, the VPC is in neither inventory
    out = json.loads(T.detect_network_anomalies(region="r", vpc_id="vpc-9"))
    assert set(out) == {"error"}
    assert "prod" in out["error"] and "staging" in out["error"]
    out = json.loads(T.analyze_network_segments(region="r"))
    assert set(out) == {"error"}
    assert "prod" in out["error"] and "staging" in out["error"]


_VPC_TOOLS = [
    ("query_reachability", "_build_vpc_graph", {"subnet_id": "s"}),
    ("query_impact_radius", "_build_vpc_graph", {"resource_id": "x"}),
    ("find_network_path", "_build_vpc_graph", {"source": "a", "target": "b"}),
    ("detect_network_anomalies", "_build_vpc_graph", {}),
    ("analyze_dependency_chain", "_build_enriched_vpc_graph", {"fault_node_id": "x"}),
    ("detect_single_points_of_failure", "_build_enriched_vpc_graph", {}),
    ("analyze_capacity_risk", "_build_enriched_vpc_graph", {}),
    ("simulate_edge_removal", "_build_enriched_vpc_graph", {"edge_source": "a", "edge_target": "b"}),
]


@pytest.mark.parametrize("name,builder,extra", _VPC_TOOLS)
def test_every_vpc_tool_takes_an_account(name, builder, extra):
    with patch.object(T, builder, side_effect=RuntimeError("stop")) as b:
        out = json.loads(getattr(T, name)(region="r", vpc_id="v", account="prod", **extra))
    b.assert_called_once_with("r", "v", "prod")
    assert out == {"error": "stop"}


def test_region_tools_take_an_account():
    with patch.object(T, "_build_region_graph", side_effect=RuntimeError("stop")) as b:
        T.analyze_network_segments(region="r", account="prod")
    b.assert_called_once_with("r", "prod")
    with patch.object(T, "_build_multi_region_graph", side_effect=RuntimeError("stop")) as b:
        T.analyze_cross_region_topology(regions="r1,r2", account="prod")
    b.assert_called_once_with("r1,r2", "prod")


def test_graph_api_shares_the_tool_builders():
    assert graph_api._build_vpc_graph is T._build_vpc_graph
    assert graph_api._build_enriched_vpc_graph is T._build_enriched_vpc_graph
