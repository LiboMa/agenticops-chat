---
name: elasticsearch
description: "Elasticsearch and OpenSearch cluster operations and troubleshooting — covers cluster health (red/yellow/green), shard allocation failures, slow queries and DSL optimization, index lifecycle management, JVM heap pressure, circuit breakers, snapshot/restore, reindex operations, and node diagnostics."
metadata:
  author: agenticops
  version: "1.0"
  domain: data
---

# Elasticsearch Skill

## Quick Decision Trees

### Cluster Health Red

1. Check cluster health: `GET _cluster/health`
2. If `status: red` → unassigned PRIMARY shards exist
3. Identify: `GET _cluster/allocation/explain`
   - `NO_VALID_SHARD_COPY` → data node lost, check node status
   - `ALLOCATION_FAILED` → disk full, corrupt shard, incompatible mapping
   - `NODE_LEFT` → node crashed or was removed
4. List unassigned shards:
   ```
   GET _cat/shards?v&h=index,shard,prirep,state,unassigned.reason&s=state
   ```
5. If node lost permanently:
   - Accept data loss: `POST _cluster/reroute` with `allocate_stale_primary` or `allocate_empty_primary`
   - Restore from snapshot if available
6. If disk full → free disk space or adjust watermark settings

**Escalation path:**

```
Cluster RED
  |
  +-- All data nodes reachable?
  |     +-- Yes → check disk watermarks, allocation explain
  |     +-- No  → recover nodes first, check systemd/docker logs
  |
  +-- Was there a recent deployment?
  |     +-- Mapping conflict? → check index template + reindex
  |     +-- Version mismatch? → rolling restart in correct order
  |
  +-- Snapshot available?
        +-- Yes → restore missing indices from snapshot
        +-- No  → allocate_stale_primary (accepts potential data loss)
```

### Cluster Health Yellow

1. Check: `GET _cluster/health` → `status: yellow` means unassigned REPLICA shards
2. Common causes:
   - Single-node cluster → replicas can never allocate (set `number_of_replicas: 0`)
   - Not enough nodes → need at least N+1 nodes for N replicas
   - Disk watermark hit → replicas won't allocate on full nodes
   - Allocation filtering → check `index.routing.allocation.*` settings
3. Check: `GET _cat/allocation?v` — see shard distribution per node
4. Check: `GET _cluster/settings?include_defaults&filter_path=*.cluster.routing.allocation.disk*`
5. If transient after node restart → wait for recovery; monitor with `GET _cat/recovery?v&active_only`

### Shard Allocation Failures

1. Diagnose: `GET _cluster/allocation/explain`
2. Common reasons:
   - `max_retries_exceeded` → `POST _cluster/reroute?retry_failed`
   - `disk_threshold_exceeded` → increase disk or adjust watermarks:
     ```
     PUT _cluster/settings
     {"transient": {"cluster.routing.allocation.disk.watermark.low": "85%",
                     "cluster.routing.allocation.disk.watermark.high": "90%",
                     "cluster.routing.allocation.disk.watermark.flood_stage": "95%"}}
     ```
   - `too_many_shards_on_node` → increase `cluster.max_shards_per_node` or reduce shard count
   - `awareness_zone` → rack/zone awareness blocking allocation
3. Rebalance stuck: `GET _cat/shards?v&s=state` → check INITIALIZING/RELOCATING count
4. Force allocation (dangerous): `POST _cluster/reroute` with allocate commands

### Slow Queries / DSL Optimization

1. Enable slow log:
   ```
   PUT my-index/_settings
   {"index.search.slowlog.threshold.query.warn": "5s",
    "index.search.slowlog.threshold.query.info": "2s",
    "index.search.slowlog.threshold.fetch.warn": "1s"}
   ```
2. Profile a query:
   ```
   GET my-index/_search
   {"profile": true, "query": {"match": {"field": "value"}}}
   ```
3. Check query patterns:
   - `wildcard` on `text` fields → use `keyword` sub-field
   - Leading wildcard (`*foo`) → extremely slow, consider ngram tokenizer
   - Deep `nested` queries → flatten if possible
   - Large `terms` arrays → use `terms` lookup from another index
   - `script_score` on every doc → pre-compute and store as field
4. Check fielddata usage: `GET _cat/fielddata?v` — high fielddata = text field aggregation
5. Expensive queries circuit breaker: check `indices.query.bool.max_clause_count`

### JVM Heap Pressure

1. Check: `GET _nodes/stats/jvm`
   - `heap_used_percent` > 75% sustained → investigate
   - `heap_used_percent` > 85% → immediate action needed
2. Check GC pressure: `GET _nodes/stats/jvm` → `gc.collectors.old.collection_count`
   - Frequent old GC (> 10/min) → heap too small or too much data in heap
3. Common causes:
   - Too many shards → merge small indices, increase shard size
   - Fielddata on text fields → use `keyword` type for aggregations
   - Large aggregations → use `composite` aggregation with pagination
   - Parent-child/nested joins → flatten data model
   - Too many open contexts → check `GET _nodes/stats/indices/search` → `open_contexts`
4. Fix strategies:
   - Increase heap (max 50% of RAM, max 31 GB for compressed oops)
   - Reduce shard count (target: 20-40 shards per GB heap)
   - Use `doc_values: true` (default) instead of fielddata
   - Circuit breakers: check `GET _nodes/stats/breaker`

### Circuit Breakers Tripping

1. Check: `GET _nodes/stats/breaker`
2. Types:
   - `parent` — total heap usage across all breakers
   - `fielddata` — aggregations on text fields
   - `request` — per-request memory (large aggs, scroll contexts)
   - `inflight_requests` — incoming HTTP request data
3. If `parent` trips → overall heap pressure, see JVM section
4. If `fielddata` trips → switch text field aggregations to keyword
5. Adjust limits (temporary):
   ```
   PUT _cluster/settings
   {"transient": {"indices.breaker.total.limit": "85%",
                   "indices.breaker.fielddata.limit": "50%",
                   "indices.breaker.request.limit": "50%"}}
   ```

### Index Lifecycle Management (ILM)

1. Check ILM status: `GET _ilm/status`
2. Check policy: `GET _ilm/policy/my-policy`
3. Check index ILM state: `GET my-index/_ilm/explain`
   - If `step: ERROR` → `GET my-index/_ilm/explain` shows error details
   - Retry: `POST my-index/_ilm/retry`
4. Common lifecycle phases:
   - `hot` → active indexing, full resources
   - `warm` → read-only, can shrink/force-merge
   - `cold` → infrequent access, searchable snapshots
   - `frozen` → rare access, fully mounted from snapshot
   - `delete` → remove after retention period
5. Force-move index to next phase:
   ```
   POST _ilm/move/my-index
   {"current_step": {"phase": "hot", "action": "complete", "name": "complete"},
    "next_step": {"phase": "warm", "action": "shrink", "name": "shrink"}}
   ```

### Snapshot and Restore

1. Check repository: `GET _snapshot/_all`
2. Check snapshots: `GET _snapshot/my-repo/_all`
3. Create snapshot:
   ```
   PUT _snapshot/my-repo/snap-2026-02-28?wait_for_completion=true
   {"indices": "index-*", "ignore_unavailable": true}
   ```
4. Restore:
   ```
   POST _snapshot/my-repo/snap-2026-02-28/_restore
   {"indices": "index-*",
    "rename_pattern": "(.+)",
    "rename_replacement": "restored_$1"}
   ```
5. Monitor progress: `GET _snapshot/my-repo/snap-2026-02-28/_status`
6. S3 repository setup:
   ```
   PUT _snapshot/s3-repo
   {"type": "s3", "settings": {"bucket": "my-es-backups", "region": "us-east-1"}}
   ```

## Common Patterns

### Node Diagnostics

```
# Cluster overview
GET _cat/nodes?v&h=name,ip,heap.percent,ram.percent,cpu,load_1m,disk.used_percent,node.role

# Hot threads (find CPU-bound operations)
GET _nodes/hot_threads

# Pending tasks
GET _cluster/pending_tasks

# Task management (find long-running tasks)
GET _tasks?actions=*search*&detailed&group_by=parents
```

### Reindex Operations

```
# Reindex with updated mapping
POST _reindex
{"source": {"index": "old-index"},
 "dest": {"index": "new-index"}}

# Reindex with query filter
POST _reindex
{"source": {"index": "old-index", "query": {"range": {"@timestamp": {"gte": "2026-01-01"}}}},
 "dest": {"index": "new-index"}}

# Reindex from remote cluster
POST _reindex
{"source": {"remote": {"host": "https://old-cluster:9200"}, "index": "old-index"},
 "dest": {"index": "new-index"}}

# Monitor reindex progress
GET _tasks?actions=*reindex*&detailed
```

### Template and Mapping Management

```
# Check index template
GET _index_template/my-template

# Check mapping
GET my-index/_mapping

# Add field to existing mapping (non-breaking)
PUT my-index/_mapping
{"properties": {"new_field": {"type": "keyword"}}}

# Check for mapping explosion
GET _cat/indices?v&h=index,docs.count,store.size&s=store.size:desc
```

## AWS OpenSearch Service Specifics

### Service-level Checks

```bash
# Describe domain
aws opensearch describe-domain --domain-name my-domain

# Check domain config
aws opensearch describe-domain-config --domain-name my-domain

# Check service software update
aws opensearch describe-domain --domain-name my-domain \
  --query 'DomainStatus.ServiceSoftwareOptions'

# Check cluster health via endpoint
curl -XGET "https://search-my-domain-xxx.us-east-1.es.amazonaws.com/_cluster/health?pretty"
```

### Key CloudWatch Metrics

| Metric | Warning | Critical | Notes |
|--------|---------|----------|-------|
| ClusterStatus.red | > 0 | sustained | Unassigned primary shards |
| ClusterStatus.yellow | sustained | - | Unassigned replica shards |
| FreeStorageSpace | < 25% | < 10% | Per-node free space |
| JVMMemoryPressure | > 80% | > 92% | May trigger circuit breakers |
| CPUUtilization | > 80% | > 95% | Per-node CPU |
| MasterCPUUtilization | > 50% | > 80% | Dedicated master node |
| ThreadpoolSearchRejected | > 0 | > 100/5min | Search thread pool full |
| ThreadpoolWriteRejected | > 0 | > 100/5min | Write thread pool full |
| AutomatedSnapshotFailure | > 0 | sustained | Backup failure |
| KibanaHealthyNodes | < expected | 0 | Dashboard availability |

### UltraWarm and Cold Storage

```bash
# Migrate index to warm storage
POST _ultrawarm/migration/my-index/_warm

# Check migration status
GET _ultrawarm/migration/my-index/_status

# Move to cold storage
POST _cold/migration/my-index/_cold

# Query across tiers works transparently
GET my-index/_search
{"query": {"match_all": {}}}
```
