# Elasticsearch Cluster Operations

## Rolling Restart Procedure

When you need to restart cluster nodes (version upgrade, config change, JVM settings):

### 1. Pre-flight Checks

```
# Verify cluster is green
GET _cluster/health

# Check for relocating shards (wait until 0)
GET _cat/shards?v&s=state | grep -E 'RELOCATING|INITIALIZING'

# Record current allocation settings
GET _cluster/settings?flat_settings&filter_path=*.allocation*
```

### 2. Disable Shard Allocation

```
PUT _cluster/settings
{"persistent": {"cluster.routing.allocation.enable": "primaries"}}
```

This prevents the cluster from rebalancing shards while nodes are restarting.

### 3. Flush Synced (ES < 7.6) or Flush

```
# ES >= 7.6 — sync flush is automatic, just do regular flush
POST _flush

# ES < 7.6
POST _flush/synced
```

### 4. Restart Node

```bash
# Systemd
sudo systemctl restart elasticsearch

# Docker
docker restart elasticsearch-node-1

# Verify node rejoins
GET _cat/nodes?v
```

### 5. Re-enable Allocation (after node rejoins)

```
PUT _cluster/settings
{"persistent": {"cluster.routing.allocation.enable": null}}
```

### 6. Wait for Green

```
GET _cluster/health?wait_for_status=green&timeout=5m
```

### 7. Repeat for Next Node

Only proceed to next node after cluster is green.

**Important order:**
- Data nodes first (any order)
- Ingest nodes
- Coordinating-only nodes
- Master-eligible nodes last
- **Active master node absolute last**

## Scaling Operations

### Add Data Node

```bash
# 1. Configure new node with same cluster.name
# elasticsearch.yml:
#   cluster.name: my-cluster
#   node.name: data-node-4
#   node.roles: [data, data_hot]  # or data_warm, data_cold
#   discovery.seed_hosts: ["master-1:9300", "master-2:9300", "master-3:9300"]

# 2. Start node
sudo systemctl start elasticsearch

# 3. Verify join
GET _cat/nodes?v

# 4. Shards will automatically rebalance to new node
GET _cat/allocation?v
```

### Remove Data Node

```bash
# 1. Drain shards from node (moves all shards to other nodes)
PUT _cluster/settings
{"transient": {"cluster.routing.allocation.exclude._name": "data-node-4"}}

# 2. Monitor shard migration
GET _cat/shards?v&h=index,shard,prirep,state,node | grep data-node-4

# 3. Wait until node has 0 shards
GET _cat/allocation?v

# 4. Stop and remove node
sudo systemctl stop elasticsearch

# 5. Clear the exclusion
PUT _cluster/settings
{"transient": {"cluster.routing.allocation.exclude._name": null}}
```

### Scale Master Nodes

Master nodes should always be an **odd number** (3, 5, 7) for quorum.

```
# Check current master
GET _cat/master?v

# Check all master-eligible nodes
GET _cat/nodes?v&h=name,node.role | grep m
```

**Never scale below 3 master-eligible nodes in production.**

## Index Management

### Force Merge (Read-Only Indices)

Reduces segment count, improves search performance. **Only for indices that won't receive writes.**

```
# Merge to 1 segment per shard (best for warm/cold indices)
POST my-index-2026.01/_forcemerge?max_num_segments=1

# Monitor progress
GET _cat/segments/my-index-2026.01?v&h=index,shard,segment,size
```

### Shrink Index (Reduce Shard Count)

```
# 1. Set index read-only and relocate all shards to one node
PUT my-index/_settings
{"index.routing.allocation.require._name": "data-node-1",
 "index.blocks.write": true}

# 2. Wait for relocation
GET _cat/shards/my-index?v

# 3. Shrink (target shards must be a factor of source shards)
POST my-index/_shrink/my-index-shrunk
{"settings": {"index.number_of_shards": 1, "index.number_of_replicas": 1,
              "index.routing.allocation.require._name": null,
              "index.blocks.write": null}}

# 4. Verify and alias
GET _cat/shards/my-index-shrunk?v
POST _aliases
{"actions": [
  {"remove": {"index": "my-index", "alias": "my-alias"}},
  {"add": {"index": "my-index-shrunk", "alias": "my-alias"}}
]}
```

### Split Index (Increase Shard Count)

```
# 1. Set read-only
PUT my-index/_settings
{"index.blocks.write": true}

# 2. Split (target must be a multiple of source shard count)
POST my-index/_split/my-index-split
{"settings": {"index.number_of_shards": 10}}

# 3. Remove write block on new index
PUT my-index-split/_settings
{"index.blocks.write": null}
```

## Troubleshooting Thread Pool Rejections

### Identify Rejections

```
GET _cat/thread_pool?v&h=node_name,name,active,queue,rejected&s=rejected:desc

# Focus on search and write pools
GET _nodes/stats/thread_pool/search,write
```

### Common Fixes

| Pool | Default Queue | Fix |
|------|--------------|-----|
| search | 1000 | Scale up nodes, optimize queries, reduce shard count |
| write | 10000 | Scale up nodes, increase refresh_interval, use bulk API |
| get | 1000 | Add replicas, check hot spotting |

**Do NOT increase queue sizes** — this just delays the problem and increases latency.
Instead, reduce load or add capacity.

### Bulk Indexing Optimization

```json
// Use bulk API (not individual index requests)
POST _bulk
{"index": {"_index": "my-index"}}
{"field": "value1"}
{"index": {"_index": "my-index"}}
{"field": "value2"}

// Optimal bulk size: 5-15 MB per request
// Optimal batch: 1000-5000 documents per bulk
```

For high-throughput indexing:

```
PUT my-index/_settings
{"index.refresh_interval": "30s",       // Default 1s — reduce refresh overhead
 "index.translog.durability": "async",   // Async translog (risk: lose up to 5s on crash)
 "index.translog.sync_interval": "5s"}
```

**Reset after bulk load:**
```
PUT my-index/_settings
{"index.refresh_interval": "1s",
 "index.translog.durability": "request"}
```
