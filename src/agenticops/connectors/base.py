"""Connector contract (MVP-2.6.1 spec §3.B.1).

A connector is read-only, account-addressed (credentials only through the provider layer, never ambient) and
LLM-free. It turns one Target into a CollectResult; connectors.ingest.ingest() is the only writer.

RelationObservation (trace / APM / CMDB edges) is specified here but not implemented: the first connector that
observes relations (2.6.2) adds
    RelationObservation(src_resource_id, dst_resource_id, relation_type, evidence: dict, observed_at)
plus a CollectResult.relations list, and ingest() writes them. No code until then (spec §3.B.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional, Protocol

from agenticops.services.signal_gate import SignalInput

# A pulled signal goes to process_signal unchanged, so it is a SignalInput (spec: "交给 process_signal 的 SignalInput").
SignalObservation = SignalInput


@dataclass
class EntityObservation:
    """One inventory row as observed: upserted into cloud_resources by (account_id, provider, resource_id)."""

    provider: str
    resource_type: str
    resource_id: str
    name: str
    region: str
    raw_data: dict
    tags: dict
    status: str


@dataclass
class Target:
    """One collection unit. ``account`` is a credentials.resolver snapshot (id, name, provider, credentials,
    regions); ``scope`` is the resource_id prefix this target owns (for K8s the cluster name: every id is
    '<cluster>/<Kind>/...'), which bounds absent-marking to what this target could have seen."""

    account: SimpleNamespace
    scope: str
    region: str
    refused: str = ""  # non-empty: targets() already knows this unit cannot be collected; collect() returns
    #                    this reason as its only error, so the run is recorded as failed
    tombstone: bool = False  # the scope's container was proven gone by a complete listing: collect() reports
    #                          every kind complete and empty without contacting anything, so its rows go absent


@dataclass
class CollectResult:
    entities: list[EntityObservation] = field(default_factory=list)
    signals: list[SignalObservation] = field(default_factory=list)
    # (scope, resource_type) → True only when that kind was listed completely (call succeeded, under the byte
    # cap). Only complete kinds take part in absent-marking; a kind missing here counts as partial.
    completeness: dict[tuple[str, str], bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class Connector(Protocol):
    name: str       # connector_runs.connector, CLI / API name
    provider: str   # cloud_resources.provider of the rows it owns (absent-marking never leaves it)

    def targets(self, session) -> list[Target]:
        """Account-addressed collection targets, deduplicated to one per physical scope."""
        ...

    def collect(self, target: Target, *, timeout_seconds: Optional[float] = None) -> CollectResult:
        """Read-only, no LLM. Failures are reported in errors / completeness, not raised. `timeout_seconds` is
        what is left of the caller's budget (None = none): a kind the budget cannot reach is reported, not waited on."""
        ...
