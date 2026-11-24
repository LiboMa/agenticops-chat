"""The fault-propagation registry and NewUI's map share one table (MVP-2.9.0).

NewUI draws a direction on a relation only when the registry knows one. The map's copy lives in the front end
(newui/lib/world/relations.ts) and is checked against the same file by vitest — so a relation type added here, or a
direction changed, fails a test on one side until the other follows."""
import json
from pathlib import Path

from agenticops.graph import relations

TABLE = json.loads((Path(__file__).parent / "fixtures" / "relation_propagation.json").read_text())["propagation"]


def test_the_registry_is_exactly_the_shared_table():
    assert relations.PROPAGATION == TABLE


def test_every_direction_is_one_of_the_four():
    assert set(TABLE.values()) <= {relations.FORWARD, relations.REVERSE, relations.BOTH, relations.NONE}
    assert relations.propagation("no_such_relation") == relations.NONE
