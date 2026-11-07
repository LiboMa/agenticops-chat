"""Bedrock's media limits (fixed — never configurable) and the document-name rule.

Measured / documented 2026-11-07: a Converse request takes at most 5 document blocks and 20 image blocks; a
document is at most 4.5 MB, an image at most 3.75 MB and 8000 px per edge; a document `name` may hold only ASCII
letters, digits, single spaces, hyphens, parentheses and square brackets (`report.pdf` and CJK names are refused).
"""
import re

BEDROCK_MAX_DOCUMENTS = 5
BEDROCK_MAX_IMAGES = 20
BEDROCK_MAX_DOCUMENT_BYTES = 4_500_000
BEDROCK_MAX_IMAGE_BYTES = 3_750_000
BEDROCK_MAX_IMAGE_EDGE_PX = 8000
MIN_FREE_DISK_BYTES = 2 * 1024**3

_NAME_MAX = 200
_UNSAFE = re.compile(r"[^A-Za-z0-9()\[\]]+")


def document_name(att_id: str, filename: str, taken: set[str]) -> str:
    """`att-<8 hex of the id>-<safe name>`, unique within `taken` (the name is added to it).

    Every run of characters outside the allowed set (spaces included) becomes one hyphen, so the result never has
    a double space or a dot; a name with nothing usable left is just `att-<id8>`."""
    prefix = f"att-{(att_id or '').replace('-', '')[:8].lower() or '0' * 8}"
    safe = _UNSAFE.sub("-", filename or "").strip("-")
    base = f"{prefix}-{safe}" if safe else prefix
    base = base[:_NAME_MAX].rstrip("-")
    name, n = base, 1
    while name in taken:
        n += 1
        suffix = f"-{n}"
        name = base[:_NAME_MAX - len(suffix)].rstrip("-") + suffix
    taken.add(name)
    return name
