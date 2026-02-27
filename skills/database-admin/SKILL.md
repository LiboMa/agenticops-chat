---
name: database-admin
description: "Database administration and troubleshooting for RDS (MySQL, PostgreSQL, Oracle, SQL Server), DynamoDB, ElastiCache/Redis — covers slow queries, connection issues, replication lag, deadlocks, storage full, backup/restore, parameter tuning, and performance optimization."
metadata:
  author: agenticops
  version: "1.0"
  domain: data
---

# Database Admin Skill

## Quick Decision Trees

### RDS Connection Issues

1. Check instance status: `aws rds describe-db-instances --db-instance-identifier ID`
2. If "available" but cannot connect:
   - Security group: verify inbound rule allows source IP on correct port (3306/5432/1521/1433)
   - Subnet group: verify instance is in expected VPC/subnets
   - Public accessibility: if connecting from outside VPC, must be enabled + have public IP
   - DNS resolution: try connecting by endpoint hostname, not IP
3. "storage-full" -> immediate action: modify storage or enable autoscaling
4. "incompatible-parameters" -> check parameter group for invalid settings

### Connection Limit Exhaustion

1. Check current connections:
   - MySQL: `SHOW STATUS LIKE 'Threads_connected';`
   - PostgreSQL: `SELECT count(*) FROM pg_stat_activity;`
2. Check max connections:
   - MySQL: `SHOW VARIABLES LIKE 'max_connections';`
   - PostgreSQL: `SHOW max_connections;`
3. Identify idle connections:
   - MySQL: `SHOW PROCESSLIST` -- look for Sleep state with high Time
   - PostgreSQL: `SELECT * FROM pg_stat_activity WHERE state = 'idle' AND query_start < now() - interval '10 minutes';`
4. Fix strategies:
   - Kill idle connections (short-term)
   - Implement connection pooling (PgBouncer, ProxySQL, RDS Proxy)
   - Increase `max_connections` parameter (requires reboot on some engines)
   - Scale up instance class (higher class = higher default max_connections)

### Slow Queries (MySQL)

1. Enable slow query log: `slow_query_log=1`, `long_query_time=1`
2. Check: `SHOW PROCESSLIST` -- look for long-running queries
3. Per-query: `EXPLAIN SELECT ...` -- check for full table scans (type=ALL)
4. Missing indexes: `SHOW INDEX FROM table` + check query WHERE/JOIN columns
5. Buffer pool: `SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read%'` -- hit ratio
6. Lock contention: `SHOW ENGINE INNODB STATUS` -> check TRANSACTIONS section

### Slow Queries (PostgreSQL)

1. `pg_stat_activity` -- check active queries, wait_event_type
2. Per-query: `EXPLAIN (ANALYZE, BUFFERS) SELECT ...`
3. Index usage: `pg_stat_user_indexes` -- check idx_scan count
4. Table bloat: `pg_stat_user_tables` -- check n_dead_tup, last_autovacuum
5. Lock waits: `pg_locks` joined with `pg_stat_activity`

### Replication Lag

1. MySQL: `SHOW SLAVE STATUS` -> check Seconds_Behind_Master
   - High lag: check for long-running queries on replica, I/O thread vs SQL thread
   - Single-threaded replication -> enable parallel replication
2. PostgreSQL: check `pg_stat_replication` on primary, `pg_last_wal_replay_lsn()` on replica
3. RDS Read Replica: CloudWatch `ReplicaLag` metric
4. Common causes:
   - Large transactions on primary (DDL on big tables)
   - Replica undersized (fewer CPU/IOPS than primary)
   - Network latency (cross-AZ or cross-region replicas)
   - Long-running queries on replica blocking replication apply

### DynamoDB Throttling

1. CloudWatch: `ThrottledRequests`, `ConsumedReadCapacityUnits`, `ConsumedWriteCapacityUnits`
2. Hot partition: check item access patterns -- one partition key getting disproportionate traffic
3. Provisioned mode -> consider on-demand or increase RCU/WCU
4. Adaptive capacity may not kick in fast enough for sudden spikes
5. DAX for read-heavy: eliminates read throttling for cached items

### ElastiCache/Redis Issues

1. High memory: `INFO memory` -- used_memory vs maxmemory, eviction policy
2. Connection count: `INFO clients` -- connected_clients vs maxclients
3. Slow commands: `SLOWLOG GET 10` -- check for O(N) commands on large keys
4. Replication: `INFO replication` -- check master_link_status, master_last_io_seconds_ago
5. Cluster mode: `CLUSTER INFO` -- check cluster_state, cluster_slots_assigned

## Common Patterns

### Deadlock Analysis

**MySQL:**
```sql
SHOW ENGINE INNODB STATUS;
-- Look for "LATEST DETECTED DEADLOCK" section
-- Shows both transactions, the locks they held, and the lock they were waiting for
```

**PostgreSQL:**
```sql
-- Find blocked queries
SELECT blocked_locks.pid AS blocked_pid,
       blocked_activity.usename AS blocked_user,
       blocking_locks.pid AS blocking_pid,
       blocking_activity.usename AS blocking_user,
       blocked_activity.query AS blocked_statement,
       blocking_activity.query AS blocking_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
  AND blocking_locks.relation = blocked_locks.relation
  AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

**Common cause:** Transactions acquiring locks in different order across tables.
**Fix:** Ensure all transactions access tables in the same order.

### Backup and Restore

```bash
# RDS automated backup: check configuration
aws rds describe-db-instances --db-instance-identifier ID \
  --query 'DBInstances[*].[BackupRetentionPeriod,PreferredBackupWindow,LatestRestorableTime]'

# Point-in-time restore (creates new instance with different endpoint)
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier source-db \
  --target-db-instance-identifier restored-db \
  --restore-time "2026-02-27T10:30:00Z"

# Snapshot restore
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier restored-db \
  --db-snapshot-identifier my-snapshot

# Cross-region: copy snapshot first, then restore
aws rds copy-db-snapshot \
  --source-db-snapshot-identifier arn:aws:rds:us-east-1:123456789012:snapshot:my-snapshot \
  --target-db-snapshot-identifier my-snapshot-copy \
  --region us-west-2
```

**Important:** Restored instances always get a NEW endpoint. Update application
connection strings after restore.

### Storage Full Emergency Response

```bash
# Check current storage
aws rds describe-db-instances --db-instance-identifier ID \
  --query 'DBInstances[*].[AllocatedStorage,DBInstanceClass]'

# Enable storage autoscaling
aws rds modify-db-instance --db-instance-identifier ID \
  --max-allocated-storage 1000

# Immediate storage increase (causes brief I/O pause)
aws rds modify-db-instance --db-instance-identifier ID \
  --allocated-storage 200 --apply-immediately

# MySQL: find large tables
# SELECT table_schema, table_name,
#   ROUND(data_length/1024/1024, 2) AS data_mb,
#   ROUND(index_length/1024/1024, 2) AS index_mb
# FROM information_schema.tables ORDER BY data_length DESC LIMIT 20;

# PostgreSQL: find large tables
# SELECT schemaname, tablename,
#   pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size
# FROM pg_tables ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC LIMIT 20;
```

### Parameter Group Tuning

```bash
# Compare current vs default parameter values
aws rds describe-db-parameters --db-parameter-group-name my-param-group \
  --query 'Parameters[?Source==`user`].[ParameterName,ParameterValue]' --output table

# Modify a parameter (some require reboot)
aws rds modify-db-parameter-group --db-parameter-group-name my-param-group \
  --parameters "ParameterName=max_connections,ParameterValue=500,ApplyMethod=pending-reboot"

# Check which parameters require reboot
aws rds describe-db-parameters --db-parameter-group-name my-param-group \
  --query 'Parameters[?ApplyType==`static`].[ParameterName,ParameterValue]' --output table
```

### RDS Performance Insights

```bash
# Enable Performance Insights
aws rds modify-db-instance --db-instance-identifier ID \
  --enable-performance-insights \
  --performance-insights-retention-period 7

# Query top SQL by load (via API)
aws pi get-resource-metrics \
  --service-type RDS \
  --identifier db-XXXXXXXXXXXXXXXXXXXX \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --metric-queries '[{"Metric": "db.load.avg", "GroupBy": {"Group": "db.sql", "Limit": 10}}]'
```

### RDS Proxy for Connection Pooling

```bash
# Create RDS Proxy
aws rds create-db-proxy \
  --db-proxy-name my-proxy \
  --engine-family MYSQL \
  --auth '[{"AuthScheme":"SECRETS","SecretArn":"arn:aws:secretsmanager:...","IAMAuth":"DISABLED"}]' \
  --role-arn arn:aws:iam::role/rds-proxy-role \
  --vpc-subnet-ids subnet-xxx subnet-yyy

# Register target
aws rds register-db-proxy-targets \
  --db-proxy-name my-proxy \
  --db-instance-identifiers my-db-instance

# Check proxy status
aws rds describe-db-proxies --db-proxy-name my-proxy
aws rds describe-db-proxy-targets --db-proxy-name my-proxy
```

## Monitoring Queries

### Key CloudWatch Metrics for RDS

| Metric | Warning | Critical | Notes |
|--------|---------|----------|-------|
| CPUUtilization | > 70% | > 90% | Sustained high CPU = query optimization needed |
| FreeStorageSpace | < 20% | < 10% | Enable autoscaling before it hits 0 |
| FreeableMemory | < 1 GB | < 256 MB | May need larger instance class |
| DatabaseConnections | > 80% max | > 95% max | Implement connection pooling |
| ReadLatency | > 10ms | > 50ms | Check IOPS, query plans, indexes |
| WriteLatency | > 10ms | > 50ms | Check IOPS, lock contention |
| ReplicaLag | > 30s | > 300s | Check replica sizing, long transactions |
| DiskQueueDepth | > 10 | > 50 | Storage IOPS saturated |
| SwapUsage | > 0 | > 100MB | Instance memory undersized |

### Key CloudWatch Metrics for DynamoDB

| Metric | Warning | Critical |
|--------|---------|----------|
| ThrottledRequests | > 0 | > 100/min |
| ConsumedReadCapacityUnits | > 80% provisioned | > 95% provisioned |
| ConsumedWriteCapacityUnits | > 80% provisioned | > 95% provisioned |
| SystemErrors | > 0 | > 10/min |
| UserErrors | > 100/min | > 1000/min |

### Key Metrics for ElastiCache/Redis

| Metric | Warning | Critical |
|--------|---------|----------|
| EngineCPUUtilization | > 65% | > 90% |
| DatabaseMemoryUsagePercentage | > 80% | > 95% |
| CurrConnections | > 50000 | > 60000 |
| Evictions | > 0 (if unexpected) | sustained > 100/s |
| ReplicationLag | > 1s | > 10s |
| CacheHitRate | < 90% | < 70% |
