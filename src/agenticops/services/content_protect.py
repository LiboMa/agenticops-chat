"""Protected values (MVP-2.7.0 S6): before a report goes to a model for translation, every value that must not
change — code, commands, object / evidence / check references, ARNs and resource ids, IPs, URLs, every number — is
swapped for a numbered placeholder ⟦Pn⟧. The model never sees those values, so it cannot alter them; restore() puts
them back and refuses (ProtectedValuesChanged) unless every placeholder came back exactly once and no other did.
Pure, so tests pin it."""
import hashlib
import re

_PATTERNS = [
    r"`{3}.*?`{3}",                                         # fenced code blocks (commands, output)
    r"`[^`\n]+`",                                           # inline code
    r"⟦P\d+⟧",                                              # a placeholder-looking string in the source itself
    r"https?://[^\s)>\]]+",                                 # URLs
    r"\barn:[A-Za-z0-9-]+:[^\s,;)]+",                       # ARNs
    r"\b[IRCP]#\d+\b",                                      # object refs: issue, resource, change, plan
    r"\bE-?\d+\b",                                          # evidence refs
    r"\bpc-\d+\b",                                          # post-check ids
    r"\b(?:i|vol|sg|subnet|vpc|eni|ami|rtb|igw|nat|db|cluster|snap|lt|eipalloc|acl)-[0-9a-z][0-9a-z-]*\b",
    r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b",            # IPv4 (and CIDR)
    r"\b[a-z]{2}-[a-z]+-\d\b",                              # AWS regions (us-east-1)
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
    return hashlib.sha256("\x1f".join(protect(text)[1]).encode("utf-8")).hexdigest()
