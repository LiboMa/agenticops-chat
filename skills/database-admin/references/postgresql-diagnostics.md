# PostgreSQL Diagnostics Deep Dive

## VACUUM and ANALYZE

PostgreSQL uses Multi-Version Concurrency Control (MVCC). Every UPDATE creates a new row
version and marks the old one as dead. VACUUM reclaims space from dead rows. Without it,
tables grow indefinitely ("table bloat").

### How MVCC Creates Dead Tuples

```
UPDATE users SET name = 'Alice' WHERE id = 1;
-- Old row version: (id=1, name='Bob')   -> marked as dead tuple
-- New row version: (id=1, name='Alice')  -> current version
-- Dead tuple is invisible to new transactions but still occupies disk space
```

### Manual VACUUM

```sql
-- Standard VACUUM: reclaims space, updates visibility map (does NOT lock table)
VACUUM users;

-- VACUUM VERBOSE: shows detailed statistics
VACUUM VERBOSE users;

-- VACUUM ANALYZE: reclaims space AND updates statistics
VACUUM ANALYZE users;

-- VACUUM FULL: rewrites entire table, reclaims all space (LOCKS TABLE - use with caution)
VACUUM FULL users;

-- Check when last vacuum/analyze ran
SELECT schemaname, relname, last_vacuum, last_autovacuum, last_analyze, last_autoanalyze,
       n_dead_tup, n_live_tup
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;
```

### Autovacuum Tuning

Autovacuum runs automatically but may need tuning for large or write-heavy tables.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `autovacuum` | on | Master switch |
| `autovacuum_vacuum_threshold` | 50 | Min dead tuples before vacuum |
| `autovacuum_vacuum_scale_factor` | 0.2 | Fraction of table size (20%) |
| `autovacuum_analyze_threshold` | 50 | Min changed tuples before analyze |
| `autovacuum_analyze_scale_factor` | 0.1 | Fraction of table size (10%) |
| `autovacuum_naptime` | 1min | Time between autovacuum checks |
| `autovacuum_max_workers` | 3 | Concurrent autovacuum workers |
| `autovacuum_vacuum_cost_delay` | 2ms | Delay between I/O operations (throttling) |
| `autovacuum_vacuum_cost_limit` | -1 (uses vacuum_cost_limit=200) | I/O cost limit per round |

**Trigger formula:** autovacuum fires when:
`dead_tuples > autovacuum_vacuum_threshold + (autovacuum_vacuum_scale_factor * n_live_tup)`

**Problem with defaults on large tables:** A 100M-row table needs 20M dead tuples (20%)
before autovacuum fires. Set per-table overrides:

```sql
-- Aggressive autovacuum for a high-write table
ALTER TABLE events SET (
  autovacuum_vacuum_scale_factor = 0.01,    -- 1% instead of 20%
  autovacuum_vacuum_threshold = 1000,
  autovacuum_analyze_scale_factor = 0.005,
  autovacuum_vacuum_cost_delay = 0          -- no throttling
);
```

### Detecting Table Bloat

```sql
-- Quick check: dead tuple ratio
SELECT schemaname, relname, n_live_tup, n_dead_tup,
       CASE WHEN n_live_tup > 0
            THEN ROUND(100.0 * n_dead_tup / n_live_tup, 1)
            ELSE 0 END AS dead_pct
FROM pg_stat_user_tables
WHERE n_dead_tup > 10000
ORDER BY n_dead_tup DESC;

-- Detailed bloat estimate using pgstattuple extension
CREATE EXTENSION IF NOT EXISTS pgstattuple;
SELECT * FROM pgstattuple('users');
-- dead_tuple_percent > 20% indicates significant bloat

-- Table size vs estimated live data size
SELECT
  schemaname || '.' || tablename AS table_full_name,
  pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size,
  pg_size_pretty(pg_relation_size(schemaname || '.' || tablename)) AS table_size,
  pg_size_pretty(pg_indexes_size(schemaname || '.' || tablename::regclass)) AS indexes_size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC
LIMIT 20;
```

## Memory Parameters

### shared_buffers

The main shared memory cache for PostgreSQL (analogous to InnoDB buffer pool).

```sql
SHOW shared_buffers;  -- default: 128MB, recommended: 25% of RAM
```

| Instance Memory | shared_buffers |
|----------------|---------------|
| 2 GB | 512 MB |
| 8 GB | 2 GB |
| 16 GB | 4 GB |
| 32 GB | 8 GB |
| 64 GB | 16 GB |

**RDS note:** On RDS, shared_buffers is set via the parameter group. The RDS default is
approximately 25% of instance memory, calculated as `{DBInstanceClassMemory/32768}`.

### effective_cache_size

Not an allocation -- tells the query planner how much memory is available for caching
(shared_buffers + OS page cache). Affects cost estimates for index scans.

```sql
SHOW effective_cache_size;  -- recommended: 75% of RAM
```

### work_mem

Memory allocated per sort/hash operation per query. A complex query with multiple sorts
can use N * work_mem. Setting too high risks OOM with many concurrent queries.

```sql
SHOW work_mem;  -- default: 4MB

-- Calculate safe work_mem:
-- work_mem = (available_memory - shared_buffers) / (max_connections * 2)
-- For 16GB RAM, 4GB shared_buffers, 200 connections:
-- (16384 - 4096) / (200 * 2) = ~30MB

-- Set per-session for a specific heavy query
SET work_mem = '256MB';
SELECT ...;
RESET work_mem;
```

### maintenance_work_mem

Memory for maintenance operations (VACUUM, CREATE INDEX, ALTER TABLE).

```sql
SHOW maintenance_work_mem;  -- default: 64MB, recommended: 512MB-2GB
-- Only one maintenance operation uses this at a time per autovacuum worker
```

## pg_stat_statements

The most important extension for query performance analysis. Tracks execution statistics
for all SQL statements.

### Setup

```sql
-- Enable the extension (requires shared_preload_libraries on RDS)
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- RDS: add pg_stat_statements to shared_preload_libraries in parameter group
-- (requires reboot)
```

### Key Queries

```sql
-- Top 10 queries by total time (the biggest optimization targets)
SELECT
  query,
  calls,
  total_exec_time::numeric(12,2) AS total_time_ms,
  mean_exec_time::numeric(12,2) AS avg_time_ms,
  rows,
  shared_blks_hit + shared_blks_read AS total_blocks,
  CASE WHEN shared_blks_hit + shared_blks_read > 0
    THEN ROUND(100.0 * shared_blks_hit / (shared_blks_hit + shared_blks_read), 1)
    ELSE 100 END AS cache_hit_pct
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;

-- Top 10 queries by number of calls (most frequent)
SELECT query, calls, mean_exec_time::numeric(12,2) AS avg_ms, rows
FROM pg_stat_statements
ORDER BY calls DESC
LIMIT 10;

-- Queries with worst cache hit ratio (hitting disk)
SELECT query, calls,
  shared_blks_hit, shared_blks_read,
  ROUND(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0), 1) AS hit_pct
FROM pg_stat_statements
WHERE shared_blks_hit + shared_blks_read > 100
ORDER BY hit_pct ASC
LIMIT 10;

-- Reset statistics (do this periodically to get fresh data)
SELECT pg_stat_statements_reset();
```

## Query Plan Nodes

Understanding EXPLAIN output requires knowing what each plan node means.

### Scan Types

| Node | Description | Performance |
|------|-------------|-------------|
| Seq Scan | Full table scan, reads every row | Slow on large tables |
| Index Scan | Uses index to find rows, then fetches from table | Fast for selective queries |
| Index Only Scan | All data from index (covering index) | Fastest -- no table access |
| Bitmap Index Scan | Builds bitmap of matching pages, then reads pages | Good for moderate selectivity |
| TID Scan | Direct access by physical row ID | Very fast, rare in practice |

### Join Types

| Node | Description | When Used |
|------|-------------|-----------|
| Nested Loop | For each row in outer, scan inner | Small result sets, indexed inner |
| Hash Join | Build hash table from inner, probe with outer | Medium-large joins, no usable index |
| Merge Join | Sort both sides, merge in order | Large sorted datasets |

### Other Important Nodes

| Node | Description | Watch For |
|------|-------------|-----------|
| Sort | In-memory or on-disk sort | "Sort Method: external merge" = disk sort (increase work_mem) |
| Hash | Build hash table for join | "Batches: N" with N > 1 = spilling to disk |
| Aggregate | GROUP BY, COUNT, SUM, etc | High row counts = slow aggregation |
| Limit | LIMIT clause | OK if combined with index scan; bad with Sort (sorts all then limits) |
| Materialize | Caches subquery results | Large materialized sets = memory pressure |

### Reading EXPLAIN ANALYZE Output

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT ...;

-- Key metrics in output:
-- actual time=START..END  - milliseconds for first row and all rows
-- rows=N                  - actual rows returned (compare to planned)
-- loops=N                 - number of times this node executed
-- Buffers: shared hit=N   - pages read from shared_buffers (cache)
-- Buffers: shared read=N  - pages read from disk
-- Planning Time: Xms      - time to generate the plan
-- Execution Time: Xms     - total execution time
```

## Connection Pooling with PgBouncer

PgBouncer is a lightweight connection pooler that sits between the application and
PostgreSQL. It is critical for applications with many short-lived connections.

### Pool Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| session | Connection assigned for entire client session | Apps using session-level features (LISTEN/NOTIFY, prepared statements) |
| transaction | Connection assigned per transaction | Most common; best balance of pooling and compatibility |
| statement | Connection assigned per statement | Maximum pooling; no multi-statement transactions |

### Key PgBouncer Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_client_conn` | 100 | Max client connections to PgBouncer |
| `default_pool_size` | 20 | Connections per user/database pair |
| `min_pool_size` | 0 | Minimum connections to keep warm |
| `reserve_pool_size` | 0 | Extra connections for burst |
| `reserve_pool_timeout` | 5s | Wait before using reserve pool |
| `server_idle_timeout` | 600s | Close idle server connections |
| `query_wait_timeout` | 120s | Max wait for a server connection |

### Monitoring PgBouncer

```sql
-- Connect to PgBouncer admin console (usually port 6432)
-- SHOW STATS: per-database statistics
-- SHOW POOLS: pool status per user/database
-- SHOW CLIENTS: connected client sessions
-- SHOW SERVERS: backend PostgreSQL connections

-- Key things to watch:
-- cl_active vs cl_waiting: waiting > 0 means pool exhaustion
-- sv_active vs sv_idle: all active + waiting clients = need more pool size
-- avg_query_time: if increasing, backend is slow
```

### RDS Proxy as Alternative

RDS Proxy provides managed connection pooling without running PgBouncer:

```bash
# Check RDS Proxy connections
aws rds describe-db-proxy-targets --db-proxy-name my-proxy \
  --query 'Targets[*].[Endpoint,Port,TargetHealth.State]'

# CloudWatch metrics for RDS Proxy
# DatabaseConnectionsCurrentlySessionPinned - pinned connections reduce pooling efficiency
# DatabaseConnections - active connections to RDS
# ClientConnections - connections from app to proxy
# QueryRequests - queries per second through proxy
```
