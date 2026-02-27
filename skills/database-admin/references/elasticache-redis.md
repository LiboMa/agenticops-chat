# ElastiCache Redis Deep Dive

## Data Structures

Redis is not just a key-value store -- it supports rich data structures, each with
specific use cases and performance characteristics.

### Strings

The simplest type. Stores text, numbers, or binary data up to 512 MB.

```redis
SET user:123:name "Alice"
GET user:123:name

-- Atomic increment (counters)
INCR page:views:2026-02-27          -- returns incremented value
INCRBY user:123:balance 500         -- increment by amount

-- Expiring keys (caching)
SETEX session:abc123 3600 "user_data"   -- set with 1 hour TTL
TTL session:abc123                       -- check remaining TTL

-- Conditional set (distributed locking)
SET lock:resource NX EX 30    -- set only if not exists, expire in 30s
```

### Hashes

Key-value pairs within a key. Ideal for storing objects.

```redis
HSET user:123 name "Alice" email "alice@example.com" age 30
HGET user:123 name
HGETALL user:123

-- Partial updates (only change specific fields)
HSET user:123 email "newemail@example.com"

-- Atomic field increment
HINCRBY user:123 login_count 1

-- Memory efficient: small hashes (< 128 fields, < 64 bytes per value)
-- are stored as ziplist instead of hashtable
```

### Lists

Ordered sequences. Useful for queues, activity feeds, and recent items.

```redis
-- Queue pattern (FIFO)
LPUSH queue:emails "msg1" "msg2" "msg3"   -- push to left
RPOP queue:emails                          -- pop from right

-- Blocking pop (consumer waits for new items)
BRPOP queue:emails 30    -- block up to 30 seconds

-- Activity feed (keep last N items)
LPUSH feed:user:123 "liked post 456"
LTRIM feed:user:123 0 99    -- keep only last 100 entries
LRANGE feed:user:123 0 9     -- get latest 10 entries
```

### Sets

Unordered collections of unique strings. Good for tagging, tracking unique visitors.

```redis
SADD tags:article:1 "redis" "database" "nosql"
SMEMBERS tags:article:1
SISMEMBER tags:article:1 "redis"    -- O(1) membership check

-- Set operations
SINTER tags:article:1 tags:article:2    -- intersection (common tags)
SUNION tags:article:1 tags:article:2    -- union (all tags)
SDIFF tags:article:1 tags:article:2     -- difference

-- Random member (sampling)
SRANDMEMBER tags:article:1 3    -- 3 random tags
```

### Sorted Sets

Sets with a score for each member. Ordered by score. Essential for leaderboards,
rate limiting, time-series, and priority queues.

```redis
-- Leaderboard
ZADD leaderboard 1500 "player:alice" 1200 "player:bob" 1800 "player:charlie"
ZREVRANGE leaderboard 0 9 WITHSCORES    -- top 10 by score (descending)
ZRANK leaderboard "player:alice"         -- rank (0-based, ascending)
ZREVRANK leaderboard "player:alice"      -- rank (descending)

-- Sliding window rate limiter
ZADD rate:user:123 <timestamp> <request_id>
ZREMRANGEBYSCORE rate:user:123 0 <timestamp - window>
ZCARD rate:user:123    -- count requests in window

-- Time-series data
ZADD metrics:cpu 1709049600 "75.2"
ZADD metrics:cpu 1709049660 "82.1"
ZRANGEBYSCORE metrics:cpu <start_ts> <end_ts> WITHSCORES
```

## Persistence: RDB vs AOF

Redis offers two persistence mechanisms. Understanding the tradeoffs is critical
for data durability.

### RDB (Redis Database Backup)

Point-in-time snapshots saved to disk at configured intervals.

| Setting | Description |
|---------|-------------|
| `save 900 1` | Snapshot after 900s if >= 1 key changed |
| `save 300 10` | Snapshot after 300s if >= 10 keys changed |
| `save 60 10000` | Snapshot after 60s if >= 10000 keys changed |
| `rdbcompression yes` | Compress snapshot with LZF |

**Pros:** Compact files, fast restart, good for backups
**Cons:** Data loss between snapshots (up to save interval)

### AOF (Append Only File)

Logs every write operation. Can replay to reconstruct data.

| Setting | Description |
|---------|-------------|
| `appendonly yes` | Enable AOF |
| `appendfsync always` | fsync every write (safest, slowest) |
| `appendfsync everysec` | fsync every second (recommended) |
| `appendfsync no` | OS decides when to fsync (fastest, least safe) |

**Pros:** Minimal data loss (at most 1 second with everysec)
**Cons:** Larger files, slower restart (must replay all operations)

### ElastiCache Persistence

```bash
# Check backup configuration
aws elasticache describe-cache-clusters --cache-cluster-id my-cluster \
  --query 'CacheClusters[*].[SnapshotRetentionLimit,SnapshotWindow,PreferredMaintenanceWindow]'

# Create manual snapshot
aws elasticache create-snapshot \
  --cache-cluster-id my-cluster \
  --snapshot-name "manual-2026-02-27"

# ElastiCache uses RDB snapshots for backups
# AOF is available for replication groups (Multi-AZ)
# backup window should not overlap with maintenance window
```

## Cluster Mode

Redis Cluster distributes data across multiple shards (node groups) for horizontal
scaling.

### Architecture

```
Shard 1: [Master] + [Replica]  -- hash slots 0-5460
Shard 2: [Master] + [Replica]  -- hash slots 5461-10922
Shard 3: [Master] + [Replica]  -- hash slots 10923-16383

Total: 16384 hash slots distributed across shards
Key -> CRC16(key) % 16384 -> assigned to shard owning that slot
```

### Cluster Mode Diagnostics

```redis
CLUSTER INFO
-- cluster_state: ok or fail
-- cluster_slots_assigned: should be 16384
-- cluster_slots_ok: should equal cluster_slots_assigned
-- cluster_known_nodes: total nodes in cluster
-- cluster_size: number of master shards

CLUSTER NODES
-- Shows all nodes, their roles, and slot assignments

CLUSTER SLOTS
-- Shows slot ranges and their master/replica assignments
```

### Common Cluster Issues

| Issue | Symptom | Fix |
|-------|---------|-----|
| Slot coverage gap | cluster_state: fail | Reassign missing slots |
| Unbalanced shards | Some shards hot, others idle | Rebalance slots |
| Cross-slot error | CROSSSLOT Keys in request don't hash to same slot | Use hash tags: `{user:123}:profile` |
| Failover in progress | Temporary unavailability | Wait for automatic failover to complete |

### Hash Tags

Force related keys to the same shard using curly braces:

```redis
-- These all hash to the same slot (based on "user:123")
SET {user:123}:profile "data"
SET {user:123}:settings "data"
SET {user:123}:cart "data"

-- Now multi-key operations work
MGET {user:123}:profile {user:123}:settings
```

## Memory Optimization

### Checking Memory Usage

```redis
INFO memory
-- used_memory: total bytes allocated by Redis
-- used_memory_rss: total bytes allocated by the OS (includes fragmentation)
-- mem_fragmentation_ratio: rss / used_memory (> 1.5 = significant fragmentation)
-- used_memory_peak: historical peak usage
-- maxmemory: configured limit

-- Per-key memory analysis
MEMORY USAGE key_name    -- bytes used by a specific key
DEBUG OBJECT key_name    -- encoding, serialized length

-- Scan for large keys (use in production, not KEYS *)
redis-cli --bigkeys    -- scans and reports largest keys per type
```

### Memory Optimization Techniques

1. **Use appropriate data structures**: Hashes use less memory than separate string keys
2. **Short key names**: `u:123:n` instead of `user:123:name` (saves bytes per key)
3. **Set maxmemory and eviction policy**: Prevent Redis from consuming all memory
4. **Use EXPIRE/TTL**: Automatically remove stale data
5. **Compress values**: Compress large strings before storing
6. **Use integer encoding**: Redis optimizes storage for integer values < 10000

## Key Eviction Policies

When Redis reaches maxmemory, it evicts keys based on the configured policy.

| Policy | Description | Use Case |
|--------|-------------|----------|
| `noeviction` | Return error on writes | Data must not be lost (default) |
| `volatile-lru` | Evict LRU keys with TTL set | Cache with mix of persistent and expiring keys |
| `allkeys-lru` | Evict LRU keys from all keys | Pure cache, all data is replaceable |
| `volatile-lfu` | Evict LFU keys with TTL set | Better than LRU for frequency-biased access |
| `allkeys-lfu` | Evict LFU keys from all keys | Best for pure cache with skewed access patterns |
| `volatile-random` | Evict random keys with TTL | When all cached data has equal value |
| `allkeys-random` | Evict random keys from all | Uniform access pattern cache |
| `volatile-ttl` | Evict keys with shortest TTL | When TTL reflects data importance |

### ElastiCache Eviction Configuration

```bash
# Check current eviction policy
aws elasticache describe-cache-parameters \
  --cache-parameter-group-name my-param-group \
  --query 'Parameters[?ParameterName==`maxmemory-policy`].[ParameterValue]'

# Modify eviction policy (requires parameter group modification)
aws elasticache modify-cache-parameter-group \
  --cache-parameter-group-name my-param-group \
  --parameter-name-values "ParameterName=maxmemory-policy,ParameterValue=allkeys-lfu"

# Monitor evictions
# CloudWatch metric: Evictions (should be 0 for non-cache use cases)
```

**Recommendation:** Use `allkeys-lfu` for most caching use cases. LFU (Least Frequently
Used) is better than LRU (Least Recently Used) because it considers access frequency,
not just recency.

## Connection Management

### Connection Limits

```redis
INFO clients
-- connected_clients: current connections
-- maxclients: maximum allowed (default 65000 on ElastiCache)
-- blocked_clients: clients blocked on BRPOP/BLPOP
-- tracking_clients: clients using server-assisted client-side caching

CONFIG GET maxclients
```

### Connection Best Practices

1. **Use connection pooling**: Never create a new connection per request
2. **Set idle timeout**: `timeout 300` closes idle connections after 5 minutes
3. **Monitor connected_clients**: Alert when approaching maxclients
4. **Use persistent connections**: Avoid TCP handshake overhead
5. **Pipeline commands**: Batch multiple commands in one round-trip

### Connection Pooling Example

```python
import redis

# Create connection pool (reuse across application)
pool = redis.ConnectionPool(
    host='my-cluster.xxxxx.ng.0001.use1.cache.amazonaws.com',
    port=6379,
    max_connections=50,
    socket_connect_timeout=5,
    socket_timeout=5,
    retry_on_timeout=True,
    health_check_interval=30
)

# Get connection from pool
r = redis.Redis(connection_pool=pool)
r.get('key')  # connection returned to pool automatically
```

## Lua Scripting

Lua scripts execute atomically on the Redis server. Useful for complex operations
that need to be atomic.

```redis
-- Atomic compare-and-set
EVAL "
  local current = redis.call('GET', KEYS[1])
  if current == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[2])
    return 1
  end
  return 0
" 1 mykey "expected_value" "new_value"

-- Rate limiter (sliding window, atomic)
EVAL "
  local key = KEYS[1]
  local limit = tonumber(ARGV[1])
  local window = tonumber(ARGV[2])
  local now = tonumber(ARGV[3])
  redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
  local count = redis.call('ZCARD', key)
  if count < limit then
    redis.call('ZADD', key, now, now .. math.random())
    redis.call('EXPIRE', key, window)
    return 1
  end
  return 0
" 1 rate:user:123 100 60 <current_timestamp>
```

**Caution:** Lua scripts block the Redis event loop. Keep them short (< 5ms).
Long scripts can cause timeouts and replication lag.

## Pub/Sub Patterns

Redis Pub/Sub provides fire-and-forget messaging. Messages are not persisted --
subscribers must be connected to receive them.

```redis
-- Publisher
PUBLISH notifications:user:123 "You have a new message"

-- Subscriber
SUBSCRIBE notifications:user:123

-- Pattern subscribe (wildcard)
PSUBSCRIBE notifications:*

-- Channel listing
PUBSUB CHANNELS notifications:*
PUBSUB NUMSUB notifications:user:123
```

### Pub/Sub Limitations

- No message persistence (if subscriber is disconnected, messages are lost)
- No acknowledgment (publisher does not know if anyone received the message)
- All subscribers get all messages (no consumer groups)
- For reliable messaging, use Redis Streams instead

### Redis Streams (Better Alternative)

```redis
-- Add to stream
XADD events * type "order" user_id "123" total "99.99"

-- Read from stream (consumer group for reliable processing)
XGROUP CREATE events mygroup $ MKSTREAM
XREADGROUP GROUP mygroup consumer1 COUNT 10 BLOCK 5000 STREAMS events >

-- Acknowledge processing
XACK events mygroup <message_id>

-- Check pending messages (not yet acknowledged)
XPENDING events mygroup
```
