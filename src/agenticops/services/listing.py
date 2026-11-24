"""Small helpers shared by the list and search endpoints."""

import re
from typing import Optional


def like_pattern(term: str) -> str:
    """`term` as a LIKE pattern that matches it anywhere, literally: `%` and `_` in what a person typed are
    characters, not wildcards. Use with `.ilike(pattern, escape="\\")`."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def ref_number(term: str, letters: str, *, bare: bool = True) -> Optional[int]:
    """«I#12», «i12», «12» → 12 for letters="Ii"; None when the text is not a reference of that kind. `bare=False`:
    the letter is required («R#7» is a resource's inventory number, a plain «7» is not). The number is a database
    id: at most 9 digits, never 0, ASCII digits only."""
    m = re.fullmatch(rf"[{letters}]{'?' if bare else ''}#?([1-9][0-9]{{0,8}})", term.strip(), flags=re.ASCII)
    return int(m.group(1)) if m else None
