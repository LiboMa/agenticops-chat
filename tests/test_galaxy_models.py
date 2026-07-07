"""Galaxy tables register in metadata, create cleanly, and round-trip JSON graph columns."""

import pytest

from agenticops.models import Base, get_session
from agenticops.galaxy.models import GalaxyBuild, GalaxyResourceState, GalaxyGroup


@pytest.fixture
def db_session(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/galaxy_models.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


def test_galaxy_tables_created(db_session):
    from sqlalchemy import inspect
    names = set(inspect(db_session.get_bind()).get_table_names())
    assert {"galaxy_builds", "galaxy_resource_state", "galaxy_groups"} <= names


def test_build_roundtrips_graph_json(db_session):
    b = GalaxyBuild(
        status="completed", trigger="manual",
        rule_graph={"nodes": [{"id": "res:1"}], "edges": [{"source": "res:1", "target": "res:2"}]},
        llm_graph={"edges": [{"source": "res:1", "target": "grp:x", "provenance": "llm"}]},
        node_count=1, edge_count=2,
    )
    db_session.add(b)
    db_session.commit()
    row = db_session.query(GalaxyBuild).first()
    assert row.rule_graph["nodes"][0]["id"] == "res:1"
    assert row.llm_graph["edges"][0]["provenance"] == "llm"


def test_resource_state_and_group(db_session):
    db_session.add(GalaxyResourceState(resource_pk=42, content_hash="abc"))
    db_session.add(GalaxyGroup(slug="1:project:demo", display_name="demo", kind="project", member_count=3))
    db_session.commit()
    assert db_session.query(GalaxyResourceState).filter_by(resource_pk=42).one().content_hash == "abc"
    assert db_session.query(GalaxyGroup).filter_by(slug="1:project:demo").one().kind == "project"


def test_config_defaults_present():
    from agenticops.config import settings
    assert settings.galaxy_enabled is True
    assert settings.galaxy_batch_size == 40
    assert "IAMRole" in settings.galaxy_llm_exclude_types
    assert settings.galaxy_builds_keep == 24
