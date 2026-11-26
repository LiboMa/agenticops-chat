"""Tables of the model providers (MVP-2.9.0 N35).

`model_providers`: one row per admin-added provider. The API key and the extra request headers live in `secrets`,
encrypted by the credential store (credentials/store); the column is excluded from the DB secret scrubber
(security/db_redaction), as CloudAccount.credentials is. Bedrock is built in and has no row.

`provider_models`: the models a provider offers — discovered from its list endpoint or added by hand — with what the
code needs to know about each (capabilities, context window, prices). A field an admin set is listed in
`manual_fields` and a refresh never overwrites it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agenticops.models import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ModelProvider(Base):
    __tablename__ = "model_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False)            # openai_compatible | anthropic_compatible
    preset: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    secrets: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)     # encrypted {api_key, extra_headers}
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_test: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class ProviderModel(Base):
    __tablename__ = "provider_models"
    __table_args__ = (UniqueConstraint("provider", "model_id", name="uq_provider_models_provider_model"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(300), nullable=False)
    label: Mapped[str] = mapped_column(String(300), default="")
    purpose: Mapped[str] = mapped_column(String(16), default="chat")        # chat | embedding
    context_window: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    supports_tools: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)   # None = not known / not probed
    tools_probe: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)    # passed | failed
    tools_probe_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    supports_images: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning: Mapped[str] = mapped_column(String(32), default="none")             # catalog.REASONING
    # what a request may carry — the list's word or an admin's, never read off the model's name (review of 2.9.0):
    accepts_temperature: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)   # None = not said: not sent
    prompt_cache: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)          # None = the platform's default
    price_input: Mapped[Optional[float]] = mapped_column(Float, nullable=True)        # USD per 1M tokens
    price_output: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_cache_read: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_cache_write: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="discovered")    # discovered | manual
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_fields: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
