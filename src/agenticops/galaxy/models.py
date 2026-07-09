"""Galaxy persistence tables. Registered into agenticops.models.Base metadata."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agenticops.models import Base


class GalaxyBuild(Base):
    """One graph build run (rule layer + llm layer stored together, merged on read)."""

    __tablename__ = "galaxy_builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | completed | failed
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # auto | manual | scan
    full: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    model_id: Mapped[str] = mapped_column(String(200), default="")
    prompt_version: Mapped[str] = mapped_column(String(50), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    dropped_edge_count: Mapped[int] = mapped_column(Integer, default=0)
    rule_graph: Mapped[dict] = mapped_column(JSON, default=dict)  # {"nodes":[...], "edges":[...]}
    llm_graph: Mapped[dict] = mapped_column(JSON, default=dict)   # {"edges":[...]}
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class GalaxyResourceState(Base):
    """Per-resource content hash for incremental (diff) builds."""

    __tablename__ = "galaxy_resource_state"
    __table_args__ = (UniqueConstraint("resource_pk", name="uq_galaxy_resource_state_pk"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_pk: Mapped[int] = mapped_column(Integer, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    last_analyzed_build_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class GalaxyGroup(Base):
    """Group registry — stable slugs across builds (create-or-match)."""

    __tablename__ = "galaxy_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(30), default="untagged")  # project|system|cluster|stack|untagged
    created_by_build: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
