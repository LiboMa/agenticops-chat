"""Protected values (MVP-2.7.0 S6): before a report goes to a model for translation, every value that must not
change — code, commands, object / evidence / check references, ARNs and resource ids, IPs, URLs, every number — is
swapped for a numbered placeholder ⟦Pn⟧. The model never sees those values, so it cannot alter them; restore() puts
them back and refuses (ProtectedValuesChanged) unless every placeholder came back exactly once and no other did.
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


def protected_hash(text: str) -> str:
    """The protected values as a multiset: a translation may put them in another order (zh writes the date before
    the time), but never change, drop, add or merge one (S7 live E2E — an in-order hash refused real reports)."""
    return hashlib.sha256("\x1f".join(sorted(protect(text)[1])).encode("utf-8")).hexdigest()
