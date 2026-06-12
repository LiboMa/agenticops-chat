"""GraphStore — SQLite-persisted infrastructure graph.

Uses raw SQL via SQLAlchemy text() for performance (no ORM for graph tables).
Change detection via SHA-256 hash of raw JSON to minimize writes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from agenticops.graph.engine import InfraGraph
from agenticops.graph.types import EdgeAttrs, EdgeType, NodeAttrs, NodeStatus, NodeType
from agenticops.models import get_engine

logger = logging.getLogger(__name__)


def _raw_hash(raw: dict[str, Any]) -> str:
    """Compute a 16-char hex hash of raw JSON for change detection."""
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:16]


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class GraphStore:
    """SQLite-backed persistence for InfraGraph."""

    def __init__(self, engine=None):
        self._engine = engine or get_engine()

    # ── Save ──────────────────────────────────────────────────────────

    def save_graph(
        self,
        graph: InfraGraph,
        scope: str,
        region: str = "",
        account_id: str = "",
    ) -> dict[str, int]:
        """Persist an InfraGraph with upsert semantics.

        Returns:
            dict with keys: nodes_added, nodes_updated, nodes_removed, edges_synced
        """
        now = _utcnow()
        stats = {"nodes_added": 0, "nodes_updated": 0, "nodes_removed": 0, "edges_synced": 0}

        with self._engine.connect() as conn:
            # -- Nodes: upsert with change detection --
            seen_node_ids: set[str] = set()

            for node_id, data in graph.graph.nodes(data=True):
                seen_node_ids.add(node_id)
                raw = data.get("raw", {})
                rhash = _raw_hash(raw)

                # Check if node exists and if hash changed
                row = conn.execute(
                    text("SELECT raw_hash FROM graph_nodes WHERE id = :id"),
                    {"id": node_id},
                ).fetchone()

                if row is None:
                    # Insert new node
                    node_region = raw.get("region", region)
                    node_vpc = raw.get("vpc_id", "")
                    conn.execute(
                        text("""
                            INSERT INTO graph_nodes
                                (id, node_type, label, status, resource_type, raw_json, raw_hash,
                                 vpc_id, region, account_id, updated_at, created_at)
                            VALUES
                                (:id, :node_type, :label, :status, :resource_type, :raw_json, :raw_hash,
                                 :vpc_id, :region, :account_id, :updated_at, :created_at)
                        """),
                        {
                            "id": node_id,
                            "node_type": data.get("node_type", ""),
                            "label": data.get("label", ""),
                            "status": data.get("status", "unknown"),
                            "resource_type": data.get("resource_type", ""),
                            "raw_json": json.dumps(raw),
                            "raw_hash": rhash,
                            "vpc_id": node_vpc,
                            "region": node_region,
                            "account_id": account_id,
                            "updated_at": now,
                            "created_at": now,
                        },
                    )
                    stats["nodes_added"] += 1

                elif row[0] != rhash:
                    # Update only if hash changed
                    node_region = raw.get("region", region)
                    node_vpc = raw.get("vpc_id", "")
                    conn.execute(
                        text("""
                            UPDATE graph_nodes
                            SET node_type = :node_type, label = :label, status = :status,
                                resource_type = :resource_type, raw_json = :raw_json, raw_hash = :raw_hash,
                                vpc_id = :vpc_id, region = :region, account_id = :account_id,
                                updated_at = :updated_at
                            WHERE id = :id
                        """),
                        {
                            "id": node_id,
                            "node_type": data.get("node_type", ""),
                            "label": data.get("label", ""),
                            "status": data.get("status", "unknown"),
                            "resource_type": data.get("resource_type", ""),
                            "raw_json": json.dumps(raw),
                            "raw_hash": rhash,
                            "vpc_id": node_vpc,
                            "region": node_region,
                            "account_id": account_id,
                            "updated_at": now,
                        },
                    )
                    stats["nodes_updated"] += 1
                else:
                    # Touch updated_at even if no change (proves liveness)
                    conn.execute(
                        text("UPDATE graph_nodes SET updated_at = :now WHERE id = :id"),
                        {"now": now, "id": node_id},
                    )

            # -- Remove stale nodes that belong to this scope but are no longer in the graph --
            if scope:
                # Determine scope filter: scope can be a vpc_id or region
                # If scope looks like a VPC ID, filter by vpc_id; otherwise by region
                if scope.startswith("vpc-"):
                    existing_rows = conn.execute(
                        text("SELECT id FROM graph_nodes WHERE vpc_id = :scope"),
                        {"scope": scope},
                    ).fetchall()
                else:
                    existing_rows = conn.execute(
                        text("SELECT id FROM graph_nodes WHERE region = :scope"),
                        {"scope": scope},
                    ).fetchall()

                existing_ids = {r[0] for r in existing_rows}
                stale_ids = existing_ids - seen_node_ids
                if stale_ids:
                    for stale_id in stale_ids:
                        conn.execute(
                            text("DELETE FROM graph_edges WHERE source_id = :id OR target_id = :id"),
                            {"id": stale_id},
                        )
                        conn.execute(
                            text("DELETE FROM graph_nodes WHERE id = :id"),
                            {"id": stale_id},
                        )
                    stats["nodes_removed"] = len(stale_ids)

            # -- Edges: replace all edges for seen nodes --
            # Delete existing edges where both endpoints are in seen_node_ids
            if seen_node_ids:
                # SQLite doesn't support array binding; delete per-edge for safety
                conn.execute(
                    text("DELETE FROM graph_edges WHERE source_id IN (SELECT id FROM graph_nodes WHERE id IN :ids)"),
                    {"ids": tuple(seen_node_ids)},
                ) if False else None  # noqa — see below

                # Bulk delete edges connected to any node in this graph
                for nid in seen_node_ids:
                    conn.execute(
                        text("DELETE FROM graph_edges WHERE source_id = :nid"),
                        {"nid": nid},
                    )

            # Insert all edges from the graph
            for source, target, data in graph.graph.edges(data=True):
                conn.execute(
                    text("""
                        INSERT OR REPLACE INTO graph_edges
                            (source_id, target_id, edge_type, label, state, updated_at)
                        VALUES
                            (:source_id, :target_id, :edge_type, :label, :state, :updated_at)
                    """),
                    {
                        "source_id": source,
                        "target_id": target,
                        "edge_type": data.get("edge_type", ""),
                        "label": data.get("label", ""),
                        "state": data.get("state", ""),
                        "updated_at": now,
                    },
                )
                stats["edges_synced"] += 1

            # -- Snapshot record --
            node_count = graph.graph.number_of_nodes()
            edge_count = graph.graph.number_of_edges()
            conn.execute(
                text("""
                    INSERT INTO graph_snapshots
                        (scope, snapshot_at, node_count, edge_count,
                         nodes_added, nodes_updated, nodes_removed)
                    VALUES
                        (:scope, :snapshot_at, :node_count, :edge_count,
                         :nodes_added, :nodes_updated, :nodes_removed)
                """),
                {
                    "scope": scope,
                    "snapshot_at": now,
                    "node_count": node_count,
                    "edge_count": edge_count,
                    "nodes_added": stats["nodes_added"],
                    "nodes_updated": stats["nodes_updated"],
                    "nodes_removed": stats["nodes_removed"],
                },
            )

            conn.commit()

        logger.info(
            "GraphStore.save_graph scope=%s: +%d ~%d -%d nodes, %d edges",
            scope, stats["nodes_added"], stats["nodes_updated"],
            stats["nodes_removed"], stats["edges_synced"],
        )
        return stats

    # ── Load ──────────────────────────────────────────────────────────

    def load_graph(
        self,
        scope: str = "",
        region: str = "",
        vpc_id: str = "",
        max_age_hours: int = 24,
    ) -> InfraGraph:
        """Load an InfraGraph from the DB.

        Filters by scope/region/vpc_id and max_age_hours.
        """
        graph = InfraGraph()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime("%Y-%m-%d %H:%M:%S")

        with self._engine.connect() as conn:
            # Build WHERE clause
            conditions = ["updated_at >= :cutoff"]
            params: dict[str, Any] = {"cutoff": cutoff}

            if vpc_id:
                conditions.append("vpc_id = :vpc_id")
                params["vpc_id"] = vpc_id
            if region:
                conditions.append("region = :region")
                params["region"] = region
            if scope:
                if scope.startswith("vpc-"):
                    conditions.append("vpc_id = :scope")
                else:
                    conditions.append("region = :scope")
                params["scope"] = scope

            where = " AND ".join(conditions)

            # Load nodes
            node_rows = conn.execute(
                text(f"SELECT id, node_type, label, status, resource_type, raw_json FROM graph_nodes WHERE {where}"),
                params,
            ).fetchall()

            node_ids: set[str] = set()
            for row in node_rows:
                node_id, node_type, label, status, resource_type, raw_json = row
                node_ids.add(node_id)
                try:
                    raw = json.loads(raw_json) if raw_json else {}
                except (json.JSONDecodeError, TypeError):
                    raw = {}

                graph._add_node(
                    node_id,
                    NodeAttrs(
                        node_type=NodeType(node_type) if node_type in NodeType._value2member_map_ else NodeType.VPC,
                        label=label or node_id,
                        status=NodeStatus(status) if status in NodeStatus._value2member_map_ else NodeStatus.UNKNOWN,
                        resource_type=resource_type or "",
                        raw=raw,
                    ),
                )

            # Load edges between loaded nodes
            if node_ids:
                edge_rows = conn.execute(
                    text(
                        "SELECT source_id, target_id, edge_type, label, state "
                        "FROM graph_edges WHERE source_id IN (SELECT id FROM graph_nodes WHERE "
                        f"{where}) OR target_id IN (SELECT id FROM graph_nodes WHERE {where})"
                    ),
                    params,
                ).fetchall()

                for row in edge_rows:
                    source_id, target_id, edge_type, label, state = row
                    # Only add edges where both endpoints are in the loaded graph
                    if source_id in node_ids and target_id in node_ids:
                        graph._add_edge(
                            source_id,
                            target_id,
                            EdgeAttrs(
                                edge_type=EdgeType(edge_type) if edge_type in EdgeType._value2member_map_ else EdgeType.CONTAINS,
                                label=label or "",
                                state=state or "",
                            ),
                        )

        logger.info(
            "GraphStore.load_graph: loaded %d nodes, %d edges",
            graph.graph.number_of_nodes(), graph.graph.number_of_edges(),
        )
        return graph

    # ── Search ────────────────────────────────────────────────────────

    def search_nodes(
        self,
        query: str = "",
        node_type: str = "",
        region: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search graph nodes by label/type/region."""
        conditions = ["1=1"]
        params: dict[str, Any] = {"limit": limit}

        if query:
            conditions.append("(label LIKE :q OR id LIKE :q)")
            params["q"] = f"%{query}%"
        if node_type:
            conditions.append("node_type = :node_type")
            params["node_type"] = node_type
        if region:
            conditions.append("region = :region")
            params["region"] = region

        where = " AND ".join(conditions)

        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT id, node_type, label, status, resource_type, vpc_id, region, account_id, updated_at "
                    f"FROM graph_nodes WHERE {where} ORDER BY updated_at DESC LIMIT :limit"
                ),
                params,
            ).fetchall()

        return [
            {
                "id": r[0],
                "node_type": r[1],
                "label": r[2],
                "status": r[3],
                "resource_type": r[4],
                "vpc_id": r[5],
                "region": r[6],
                "account_id": r[7],
                "updated_at": r[8],
            }
            for r in rows
        ]

    # ── Neighborhood ──────────────────────────────────────────────────

    def get_node_neighborhood(self, node_id: str, depth: int = 2) -> InfraGraph:
        """Load a subgraph around a node up to `depth` hops."""
        graph = InfraGraph()
        visited: set[str] = set()
        frontier: set[str] = {node_id}

        with self._engine.connect() as conn:
            for _ in range(depth + 1):
                if not frontier:
                    break

                new_frontier: set[str] = set()
                for nid in frontier:
                    if nid in visited:
                        continue
                    visited.add(nid)

                    # Load node
                    row = conn.execute(
                        text("SELECT id, node_type, label, status, resource_type, raw_json FROM graph_nodes WHERE id = :id"),
                        {"id": nid},
                    ).fetchone()
                    if row is None:
                        continue

                    node_id_db, node_type, label, status, resource_type, raw_json = row
                    try:
                        raw = json.loads(raw_json) if raw_json else {}
                    except (json.JSONDecodeError, TypeError):
                        raw = {}

                    graph._add_node(
                        node_id_db,
                        NodeAttrs(
                            node_type=NodeType(node_type) if node_type in NodeType._value2member_map_ else NodeType.VPC,
                            label=label or node_id_db,
                            status=NodeStatus(status) if status in NodeStatus._value2member_map_ else NodeStatus.UNKNOWN,
                            resource_type=resource_type or "",
                            raw=raw,
                        ),
                    )

                    # Find neighbors via edges
                    edge_rows = conn.execute(
                        text(
                            "SELECT source_id, target_id, edge_type, label, state "
                            "FROM graph_edges WHERE source_id = :id OR target_id = :id"
                        ),
                        {"id": nid},
                    ).fetchall()

                    for erow in edge_rows:
                        src, tgt, etype, elabel, estate = erow
                        neighbor = tgt if src == nid else src
                        if neighbor not in visited:
                            new_frontier.add(neighbor)

                frontier = new_frontier

            # Now load all edges between visited nodes
            if visited:
                for nid in visited:
                    edge_rows = conn.execute(
                        text(
                            "SELECT source_id, target_id, edge_type, label, state "
                            "FROM graph_edges WHERE source_id = :id OR target_id = :id"
                        ),
                        {"id": nid},
                    ).fetchall()

                    for erow in edge_rows:
                        src, tgt, etype, elabel, estate = erow
                        if src in visited and tgt in visited and not graph.graph.has_edge(src, tgt):
                            graph._add_edge(
                                src,
                                tgt,
                                EdgeAttrs(
                                    edge_type=EdgeType(etype) if etype in EdgeType._value2member_map_ else EdgeType.CONTAINS,
                                    label=elabel or "",
                                    state=estate or "",
                                ),
                            )

        logger.info(
            "GraphStore.get_node_neighborhood(%s, depth=%d): %d nodes, %d edges",
            node_id, depth, graph.graph.number_of_nodes(), graph.graph.number_of_edges(),
        )
        return graph

    # ── Staleness ─────────────────────────────────────────────────────

    def get_stale_nodes(self, ttl_hours: int = 24) -> list[str]:
        """Return IDs of nodes not updated within ttl_hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id FROM graph_nodes WHERE updated_at < :cutoff"),
                {"cutoff": cutoff},
            ).fetchall()
        return [r[0] for r in rows]

    def get_recent_snapshots(self, limit: int = 5) -> list[dict]:
        """Return the most recent graph sync snapshots (topology change history).

        Each entry: {id, scope, snapshot_at, node_count, edge_count,
        nodes_added, nodes_updated, nodes_removed}.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, scope, snapshot_at, node_count, edge_count, "
                    "nodes_added, nodes_updated, nodes_removed "
                    "FROM graph_snapshots ORDER BY id DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [
            {
                "id": r[0],
                "scope": r[1],
                "snapshot_at": r[2],
                "node_count": r[3],
                "edge_count": r[4],
                "nodes_added": r[5],
                "nodes_updated": r[6],
                "nodes_removed": r[7],
            }
            for r in rows
        ]

    def remove_stale_nodes(self, ttl_hours: int = 24) -> int:
        """Delete nodes (and their edges) not updated within ttl_hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._engine.connect() as conn:
            # Delete edges first
            conn.execute(
                text(
                    "DELETE FROM graph_edges WHERE source_id IN "
                    "(SELECT id FROM graph_nodes WHERE updated_at < :cutoff) "
                    "OR target_id IN (SELECT id FROM graph_nodes WHERE updated_at < :cutoff)"
                ),
                {"cutoff": cutoff},
            )
            result = conn.execute(
                text("DELETE FROM graph_nodes WHERE updated_at < :cutoff"),
                {"cutoff": cutoff},
            )
            removed = result.rowcount
            conn.commit()

        if removed:
            logger.info("GraphStore.remove_stale_nodes(ttl=%dh): removed %d nodes", ttl_hours, removed)
        return removed
