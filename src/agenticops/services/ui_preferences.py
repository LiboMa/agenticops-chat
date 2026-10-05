"""Web workspace preferences (MVP-2.7.0 S2, contract workspace-ui-1).

A user's preferences are one revisioned document: the default home (`resume` = reopen the last allow-listed
place), the locale, the last route and which sidebar groups are open. A user with no row reads the defaults
at revision 1; every write names the revision it read (If-Match) and moves it on by one, so two tabs never
silently overwrite each other — a stale write is refused (412) and the client re-reads.
"""

import re
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from agenticops.auth.models import UserPreferences
from agenticops.models import get_session

HOMES = ("resume", "chat", "issues", "reports")
LOCALES = ("zh", "en")
NAV_GROUPS = ("tools", "administration")
DEFAULTS = {"locale": "en", "home": "resume", "last_route": None, "nav_groups_open": []}
FIELDS = tuple(DEFAULTS)

# The places "resume" may reopen: internal read routes only — no query string, no fragment, no action URL.
# The frontend keeps the same list (lib/home.ts); tests/fixtures/ui_last_route_cases.json pins both.
_ROUTES = (
    re.compile(r"/app/(chat|issues|reports|changes|resources|schedules|skills)(/[A-Za-z0-9][A-Za-z0-9_-]{0,99})?"),
    re.compile(r"/app/(audit|overview|agent-metrics|galaxy|security|settings|signals)"),
)


def allowed_route(route) -> bool:
    return (isinstance(route, str) and len(route) <= 1000
            and any(p.fullmatch(route) for p in _ROUTES))


class PreferencesConflict(Exception):
    """The revision named in If-Match is not the current one."""


def parse_if_match(header: Optional[str]):
    """`"3"`, `W/"3"` or `3` → (3,); a list `"2", "3"` → (2, 3) (any of them may match); `*` → "*";
    missing or malformed → None (ASCII digits only: "²".isdigit() is True but int() refuses it)."""
    if header is None:
        return None
    if header.strip() == "*":
        return "*"
    revisions = []
    for part in header.split(","):
        value = part.strip()
        if value.startswith("W/"):
            value = value[2:]
        value = value.strip('"')
        if not (value.isascii() and value.isdigit()) or int(value) < 1:
            return None
        revisions.append(int(value))
    return tuple(revisions) or None


def etag(revision: int) -> str:
    return f'"{revision}"'


def _doc(revision: int, data: Optional[dict]) -> dict:
    out = {"revision": revision}
    for key, default in DEFAULTS.items():
        out[key] = (data or {}).get(key, default)
    return out


def read(user_id: int) -> dict:
    s = get_session()
    try:
        row = s.get(UserPreferences, user_id)
        return _doc(row.revision, row.data) if row else _doc(1, None)
    finally:
        s.close()


def write(user_id: int, changes: dict, expected) -> dict:
    """Merge `changes` (already validated) into the user's preferences, guarded by `expected`: the revisions
    the caller read (any may match), or "*" to merge regardless of other writers (still never losing their
    fields: the merge is redone on the current document until its compare-and-set wins). Raises
    PreferencesConflict."""
    if isinstance(expected, int):
        expected = (expected,)
    for _ in range(5):
        s = get_session()
        try:
            row = s.get(UserPreferences, user_id)
            current = row.revision if row else 1
            if expected != "*" and current not in expected:
                raise PreferencesConflict(current)
            data = {**(row.data if row else {}), **changes}
            if row is None:
                s.add(UserPreferences(user_id=user_id, revision=2, data=data))
                try:
                    s.commit()
                except IntegrityError:  # another writer created it first
                    s.rollback()
                    if expected != "*":
                        raise PreferencesConflict(current)
                    continue
                return _doc(2, data)
            moved = s.execute(
                update(UserPreferences)
                .where(UserPreferences.user_id == user_id, UserPreferences.revision == current)
                .values(data=data, revision=current + 1)
            ).rowcount
            if moved == 1:
                s.commit()
                return _doc(current + 1, data)
            s.rollback()
            if expected != "*":
                raise PreferencesConflict(current)
        finally:
            s.close()
    raise PreferencesConflict(None)
