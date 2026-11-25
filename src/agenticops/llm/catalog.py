"""The models each provider offers (MVP-2.9.0 N35): what the code knows about one model — `model_row` — and, from
task 3 on, reading a provider's list, adding by hand and editing a model's attributes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class ProviderModelView:
    provider: str
    model_id: str
    label: str = ""
    purpose: str = "chat"                      # chat | embedding
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    supports_tools: Optional[bool] = None      # None = not known
    tools_probe: Optional[str] = None          # passed | failed
    tools_probe_at: Optional[datetime] = None
    supports_images: bool = False
    supports_documents: bool = False
    reasoning: str = "none"                    # none | openai_effort | anthropic_thinking
    price_input: Optional[float] = None        # USD per 1M tokens
    price_output: Optional[float] = None
    price_cache_read: Optional[float] = None
    price_cache_write: Optional[float] = None
    source: str = "discovered"
    enabled: bool = True
    manual_fields: list = field(default_factory=list)


def view_of(row) -> ProviderModelView:
    return ProviderModelView(
        provider=row.provider, model_id=row.model_id, label=row.label or row.model_id, purpose=row.purpose or "chat",
        context_window=row.context_window, max_output_tokens=row.max_output_tokens, supports_tools=row.supports_tools,
        tools_probe=row.tools_probe, tools_probe_at=row.tools_probe_at, supports_images=bool(row.supports_images),
        supports_documents=bool(row.supports_documents), reasoning=row.reasoning or "none",
        price_input=row.price_input, price_output=row.price_output, price_cache_read=row.price_cache_read,
        price_cache_write=row.price_cache_write, source=row.source or "discovered", enabled=bool(row.enabled),
        manual_fields=list(row.manual_fields or []))


def model_row(provider: str, model_id: str) -> Optional[ProviderModelView]:
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    with get_db_session() as s:
        row = s.query(ProviderModel).filter_by(provider=provider, model_id=model_id).first()
        return view_of(row) if row is not None else None
