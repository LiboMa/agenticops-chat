# MySQL Diagnostics Deep Dive

## InnoDB Internals

InnoDB is the default storage engine for MySQL and the only engine supported by RDS MySQL.
Understanding its internals is essential for diagnosing performance issues.

### Buffer Pool

The InnoDB buffer pool is an in-memory cache for table and index data. It is the single
most important tuning parameter for MySQL performance.

```sql
-- Check buffer pool size and usage
SHOW VARIABLES LIKE 'innodb_buffer_pool_size';
SHOW STATUS LIKE 'Innodb_buffer_pool%';

-- Key metrics to check:
-- Innodb_buffer_pool_read_requests  = logical reads (from buffer pool)
-- Innodb_buffer_pool_reads          = physical reads (from disk)
-- Hit ratio = 1 - (reads / read_requests) -- should be > 99%

-- Calculate hit ratio
SELECT
  (1 - (
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_buffer_pool_reads') /
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_buffer_pool_read_requests')
  )) * 100 AS buffer_pool_hit_ratio;

-- Check buffer pool pages
SHOW STATUS LIKE 'Innodb_buffer_pool_pages%';
-- pages_total  = total pages in buffer pool
-- pages_free   = unused pages (if 0, buffer pool is full)
-- pages_dirty  = modified pages not yet flushed to disk
-- pages_data   = pages containing data
```

### Buffer Pool Tuning for RDS

On RDS, `innodb_buffer_pool_size` is controlled by the parameter group and defaults to
approximately 75% of instance memory. Key parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `innodb_buffer_pool_size` | 75% of RAM | Main data cache |
| `innodb_buffer_pool_instances` | 8 (for >= 1GB pool) | Reduces mutex contention |
| `innodb_buffer_pool_dump_at_shutdown` | ON | Saves buffer pool state |
| `innodb_buffer_pool_load_at_startup` | ON | Warms buffer pool on restart |
| `innodb_change_buffering` | all | Buffers secondary index changes |
| `innodb_change_buffer_max_size` | 25 | % of buffer pool for change buffer |

### InnoDB Row Locking

InnoDB uses row-level locking with two lock types:

```sql
-- Check current locks
SELECT * FROM performance_schema.data_locks;

-- Check lock waits
SELECT * FROM performance_schema.data_lock_waits;

-- Long-form: join to see blocking and waiting queries
SELECT
  r.trx_id AS waiting_trx,
  r.trx_mysql_thread_id AS waiting_thread,
  r.trx_query AS waiting_query,
  b.trx_id AS blocking_trx,
  b.trx_mysql_thread_id AS blocking_thread,
  b.trx_query AS blocking_query
FROM performance_schema.data_lock_waits w
JOIN information_schema.innodb_trx b ON b.trx_id = w.BLOCKING_ENGINE_TRANSACTION_ID
JOIN information_schema.innodb_trx r ON r.trx_id = w.REQUESTING_ENGINE_TRANSACTION_ID;
```

### SHOW ENGINE INNODB STATUS Sections

This command produces a multi-section report. Here is what to look for in each section:

```sql
SHOW ENGINE INNODB STATUS\G
```

| Section | What to Check |
|---------|--------------|
| SEMAPHORES | Mutex waits > 0 = contention; long spin waits = performance issue |
| LATEST DETECTED DEADLOCK | Full deadlock trace -- shows both transactions and the lock conflict |
| TRANSACTIONS | Active transactions, lock waits, undo log entries (high undo = long transactions) |
| FILE I/O | Pending reads/writes; high numbers = I/O bottleneck |
| INSERT BUFFER AND ADAPTIVE HASH INDEX | Change buffer merges; adaptive hash index hit rate |
| BUFFER POOL AND MEMORY | Total/free/dirty pages; pages made young/not young (LRU efficiency) |
| ROW OPERATIONS | Rows inserted/updated/deleted/read per second -- overall throughput |

## Query Cache (Deprecated in 8.0)

MySQL 8.0 removed the query cache entirely. If running MySQL 5.7 on RDS:

```sql
-- Check if query cache is enabled (5.7 only)
SHOW VARIABLES LIKE 'query_cache%';

-- Recommendation: DISABLE it on RDS
-- query_cache_type = 0
-- query_cache_size = 0
-- The query cache causes global mutex contention under write-heavy workloads
```

## Connection Pool Sizing

### Formula for max_connections

```
max_connections = (available_memory - innodb_buffer_pool_size - OS_overhead) / per_connection_memory

Where per_connection_memory ~= sort_buffer_size + read_buffer_size + join_buffer_size + thread_stack
                            ~= 2MB + 256KB + 256KB + 256KB ~= 2.75MB per connection
```

### RDS Defaults by Instance Class

| Instance Class | Memory | Default max_connections |
|---------------|--------|----------------------|
| db.t3.micro | 1 GB | ~66 |
| db.t3.small | 2 GB | ~150 |
| db.t3.medium | 4 GB | ~312 |
| db.r5.large | 16 GB | ~1365 |
| db.r5.xlarge | 32 GB | ~2730 |
| db.r5.2xlarge | 64 GB | ~5461 |

```sql
-- Check current vs max connections
SHOW STATUS LIKE 'Threads_connected';
SHOW STATUS LIKE 'Max_used_connections';  -- high watermark since startup
SHOW VARIABLES LIKE 'max_connections';

-- If Max_used_connections is close to max_connections, increase it
-- or implement connection pooling (ProxySQL, RDS Proxy)
```

## Slow Query Log Analysis

### Enabling on RDS

Set these in the parameter group:

```
slow_query_log = 1
long_query_time = 1          # log queries taking > 1 second
log_queries_not_using_indexes = 1  # log queries without index usage
log_slow_admin_statements = 1      # log slow DDL too
```

### Analyzing Slow Queries

```bash
# Download slow query log from RDS
aws rds download-db-log-file-portion \
  --db-instance-identifier ID \
  --log-file-name slowquery/mysql-slowquery.log \
  --output text > /tmp/slow.log

# Use mysqldumpslow to summarize (built into mysql client)
mysqldumpslow -s t -t 20 /tmp/slow.log   # top 20 by total time
mysqldumpslow -s c -t 20 /tmp/slow.log   # top 20 by count
mysqldumpslow -s at -t 20 /tmp/slow.log  # top 20 by avg time
```

### EXPLAIN Output Reference

```sql
EXPLAIN SELECT * FROM orders WHERE customer_id = 42 AND status = 'pending';
```

| Column | Good Values | Bad Values |
|--------|------------|------------|
| type | const, eq_ref, ref, range | ALL (full table scan), index (full index scan) |
| possible_keys | Shows candidate indexes | NULL = no usable index |
| key | Index being used | NULL = no index used |
| rows | Low number | High number relative to table size |
| Extra | Using index (covering index) | Using filesort, Using temporary |

### Index Optimization

```sql
-- Find unused indexes (candidates for removal)
SELECT s.table_schema, s.table_name, s.index_name, s.column_name
FROM information_schema.statistics s
LEFT JOIN performance_schema.table_io_waits_summary_by_index_usage u
  ON s.table_schema = u.OBJECT_SCHEMA
  AND s.table_name = u.OBJECT_NAME
  AND s.index_name = u.INDEX_NAME
WHERE u.COUNT_READ = 0 AND s.index_name != 'PRIMARY'
ORDER BY s.table_schema, s.table_name;

-- Find tables without primary key (bad for replication)
SELECT t.table_schema, t.table_name
FROM information_schema.tables t
LEFT JOIN information_schema.table_constraints c
  ON t.table_schema = c.table_schema
  AND t.table_name = c.table_name
  AND c.constraint_type = 'PRIMARY KEY'
WHERE t.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
  AND c.constraint_name IS NULL
  AND t.table_type = 'BASE TABLE';

-- Find duplicate indexes
SELECT a.table_schema, a.table_name, a.index_name, a.column_name,
       b.index_name AS duplicate_index
FROM information_schema.statistics a
JOIN information_schema.statistics b
  ON a.table_schema = b.table_schema
  AND a.table_name = b.table_name
  AND a.column_name = b.column_name
  AND a.seq_in_index = b.seq_in_index
  AND a.index_name != b.index_name
ORDER BY a.table_schema, a.table_name, a.index_name;
```

## Common RDS MySQL Parameters

### Performance Parameters

| Parameter | Default | Recommended | Notes |
|-----------|---------|-------------|-------|
| `innodb_buffer_pool_size` | 75% RAM | 75-80% RAM | Largest performance lever |
| `innodb_log_file_size` | 128MB | 1-2GB | Larger = better write performance, longer recovery |
| `innodb_flush_log_at_trx_commit` | 1 | 1 (durability) or 2 (performance) | 2 risks 1s of data loss |
| `innodb_io_capacity` | 200 | Match IOPS provisioned | Controls background flushing rate |
| `innodb_io_capacity_max` | 2000 | 2x innodb_io_capacity | Burst flush rate |
| `innodb_read_io_threads` | 4 | 16 | Parallel read threads |
| `innodb_write_io_threads` | 4 | 16 | Parallel write threads |
| `table_open_cache` | 4000 | 4000-8000 | Cached open table handles |
| `thread_cache_size` | 8 | 16-64 | Reuse threads for new connections |

### Replication Parameters

| Parameter | Default | Recommended | Notes |
|-----------|---------|-------------|-------|
| `binlog_format` | ROW | ROW | Required for RDS; safest for replication |
| `sync_binlog` | 1 | 1 | Durable binlog writes (performance cost) |
| `slave_parallel_workers` | 0 | 4-16 | Parallel replication threads |
| `slave_parallel_type` | DATABASE | LOGICAL_CLOCK | Better parallelism |
| `slave_preserve_commit_order` | OFF | ON | Maintain commit ordering |

### Monitoring Parameters

| Parameter | Default | Recommended | Notes |
|-----------|---------|-------------|-------|
| `performance_schema` | ON | ON | Required for Performance Insights |
| `slow_query_log` | OFF | ON | Essential for query analysis |
| `long_query_time` | 10 | 1 | 10 seconds is too long |
| `log_queries_not_using_indexes` | OFF | ON | Find missing indexes |
| `innodb_monitor_enable` | (none) | all | Enable all InnoDB metrics |
