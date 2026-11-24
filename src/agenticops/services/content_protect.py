"""Protected values (MVP-2.7.0 S6): before a report goes to a model for translation, every value that must not
change — code, commands, object / evidence / check references, ARNs and resource ids, IPs, URLs, every number — is
swapped for a numbered placeholder ⟦Pn⟧. The model never sees those values, so it cannot alter them; restore() puts
them back and refuses (ProtectedValuesChanged) unless every placeholder came back exactly once and no other did.
protected_hash() then compares the values as a multiset — and, inside markdown tables, row by row (MVP-2.7.1).
Pure, so tests pin it."""
import hashlib
import re

# ASCII word boundaries: Python's \b treats CJK as word characters, so a value written right next to Chinese text
# ("问题I#12已修复") would not match whole (S6 review). URLs and ARNs end at the first non-ASCII character.
_L, _R = r"(?<![A-Za-z0-9_])", r"(?![A-Za-z0-9_])"
_PATTERNS = [
    r"`{3}.*?`{3}",                                         # fenced code blocks (commands, output)
    r"`[^`\n]+`",                                           # inline code
    r"⟦P\d+⟧",                                              # a placeholder-looking string in the source itself
    r"https?://[!-~]+?(?=[\s)>\],;。，；：）]|[^\x00-\x7f]|$)",  # URLs (ASCII only, trailing punctuation left out)
    _L + r"arn:[A-Za-z0-9-]+:[!-~]+?(?=[\s,;)]|[^\x00-\x7f]|$)",   # ARNs
    _L + r"[IRCP]#\d+" + _R,                                 # object refs: issue, resource, change, plan
    _L + r"E-?\d+" + _R,                                     # evidence refs
    _L + r"pc-\d+" + _R,                                     # post-check ids
    # resource ids — a real one always has a digit; «cluster-admin» / «nat-gateway» are prose (S7 live E2E)
    _L + r"(?:i|vol|sg|subnet|vpc|eni|ami|rtb|igw|nat|db|cluster|snap|lt|eipalloc|acl)-(?=[0-9a-z-]*\d)[0-9a-z][0-9a-z-]*" + _R,
    # an ISO date / datetime is one value, so its parts can never trade places (S7 review)
    _L + r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?" + _R,
    _L + r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?" + _R,        # IPv4 (and CIDR)
    _L + r"[a-z]{2}-[a-z]+-\d" + _R,                         # AWS regions (us-east-1)
    r"\d+(?:[.,:]\d+)*%?",                                  # every remaining number
]
_RX = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.S)
_PH = re.compile(r"⟦P(\d+)⟧")


class ProtectedValuesChanged(ValueError):
    pass


def protect(text: str) -> tuple[str, list[str]]:
    values: list[str] = []

    def _mask(m: re.Match) -> str:
        values.append(m.group(0))
        return f"⟦P{len(values) - 1}⟧"
    return _RX.sub(_mask, text or ""), values


def restore(masked: str, values: list[str]) -> str:
    found = [int(n) for n in _PH.findall(masked)]
    if sorted(found) != list(range(len(values))):
        raise ProtectedValuesChanged(
            f"expected each of {len(values)} protected values once; got {len(found)} placeholders")
    if re.search(r"⟦|⟧", _PH.sub("", masked)):  # a broken placeholder ("⟦P 1⟧") is not quietly kept
        raise ProtectedValuesChanged("a placeholder was altered")
    return _PH.sub(lambda m: values[int(m.group(1))], masked)


# A GFM table's delimiter row: `|---|:--:|`, `--- | ---` (outer pipes optional, at least one inner or outer pipe)
_DELIM = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$|^\s*\|\s*:?-{3,}:?\s*\|\s*$")


_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _cells(row: str) -> list[str]:
    cells = _CELL_SPLIT.split(row)
    if cells and not cells[0].strip():
        cells = cells[1:]   # a leading pipe
    if cells and not cells[-1].strip():
        cells = cells[:-1]  # a trailing pipe
    return cells


def _table_rows(masked: str, values: list[str]) -> list[tuple]:
    """Every markdown table row (header and body, in order) as its cells in order, each cell the sorted tuple of
    the protected values in it. Read on the MASKED text, so a pipe inside code or a fenced block (one placeholder)
    never makes a table or a cell."""
    rows: list[tuple] = []
    lines = masked.split("\n")
    i = 0
    while i < len(lines):
        if i + 1 < len(lines) and "|" in lines[i] and _DELIM.match(lines[i + 1]):
            block = [lines[i]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                block.append(lines[i])
                i += 1
            rows += [tuple(tuple(sorted(values[int(n)] for n in _PH.findall(cell))) for cell in _cells(row))
                     for row in block]
            continue
        i += 1
    return rows


def protected_hash(text: str) -> str:
    """The protected values as a multiset: a translation may put them in another order (zh writes the date before
    the time), but never change, drop, add or merge one (S7 live E2E — an in-order hash refused real reports).
    Inside a markdown table they are also compared row by row and cell by cell (MVP-2.7.1, owner 10-08): a value
    never moves to another cell — of its row or another — out of the table, or into a merged row. Within one cell
    the values may still reorder (zh writes the date before the time), so two values of ONE cell may trade places."""
    masked, values = protect(text)
    rows = "\x1d".join("\x1c".join("\x1f".join(cell) for cell in row) for row in _table_rows(masked, values))
    return hashlib.sha256(("\x1f".join(sorted(values)) + "\x1e" + rows).encode("utf-8")).hexdigest()
