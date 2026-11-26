"""One rule for a work item's compact id «I12» / «C3» (review of MVP-2.9.0): `services/listing.ITEM_PATTERN`
checks it on every route, `parse_item` reads it — the same number rule as `ref_number` (≤ 9 digits, never 0, ASCII)."""
import re

import pytest


@pytest.mark.parametrize("text,parsed", [
    ("I12", ("I", 12)), ("C3", ("C", 3)), ("I999999999", ("I", 999999999)),
    ("I0", None), ("I012", None), ("I1234567890", None), ("i12", None), ("X12", None), ("I#12", None),
    ("I\u0663", None), (" I12", None), ("I12 ", None), ("", None), ("I", None),
])
def test_parse_item(text, parsed):
    from agenticops.services.listing import ITEM_PATTERN, parse_item
    assert parse_item(text) == parsed
    assert bool(re.fullmatch(ITEM_PATTERN.strip("^$"), text)) is (parsed is not None)


def test_every_ui_route_checks_the_one_pattern():
    """No route of web/routers/ui.py writes its own item-id regex."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "src/agenticops/web/routers/ui.py").read_text()
    assert "[IC][1-9]" not in src
