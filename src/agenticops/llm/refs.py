"""Model references: `<provider>::<model id>`, or a bare Bedrock model id (MVP-2.9.0 N35).

`::` because Bedrock ids hold single colons only (as does Ollama's `qwen3:32b`) and `/` appears in OpenRouter ids and in
ARNs. The value is split at the FIRST `::`: a provider's own model id may contain one. A Bedrock ARN is the one Bedrock
id that holds `::` — a foundation-model ARN's account field is empty (`arn:aws:bedrock:us-east-1::foundation-model/…`)
— so a value starting with `arn:` is always a Bedrock id (`is_ref` is the one test of «a provider reference»).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

REF_SEP = "::"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
RESERVED = frozenset({"bedrock"})


@dataclass(frozen=True)
class ModelRef:
    provider: Optional[str]          # None = Bedrock
    model_id: str

    @property
    def is_bedrock(self) -> bool:
        return self.provider is None


def parse_ref(ref: str) -> ModelRef:
    """A reference as written in a setting. Raises ValueError for a malformed one (an empty value is malformed: callers
    resolve their «default» before asking)."""
    value = (ref or "").strip()
    if not value:
        raise ValueError("empty model reference")
    if not is_ref(value):
        return ModelRef(None, value)
    provider, model_id = value.split(REF_SEP, 1)
    if not NAME_RE.match(provider) or provider in RESERVED:
        raise ValueError(f"not a provider name: {provider!r}")
    if not model_id.strip():
        raise ValueError(f"no model after {provider!r}{REF_SEP}")
    return ModelRef(provider, model_id)


def format_ref(provider: str, model_id: str) -> str:
    return f"{provider}{REF_SEP}{model_id}"


def is_ref(value: str) -> bool:
    """True when the value names a non-Bedrock provider: it holds the separator and is not a Bedrock ARN."""
    v = (value or "").strip()
    return REF_SEP in v and not v.startswith("arn:")
