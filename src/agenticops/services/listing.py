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


# A work item's compact id (MVP-2.9.0): «I12» an issue, «C3» a change request — what the attention list, the activity
# lanes, `agent_steps.item` and «later» carry (the display form is «I#12»). The number rule of `ref_number`: at most
# 9 digits, never 0, ASCII digits only. Every route checks ITEM_PATTERN; code reads one with `parse_item`.
ITEM_ID = r"[IC][1-9][0-9]{0,8}"
ITEM_PATTERN = rf"^{ITEM_ID}$"


def parse_item(item: str) -> Optional[tuple[str, int]]:
    """«I12» → ("I", 12), «C3» → ("C", 3); None for anything else."""
    m = re.fullmatch(r"([IC])([1-9][0-9]{0,8})", item or "", flags=re.ASCII)
    return (m.group(1), int(m.group(2))) if m else None
