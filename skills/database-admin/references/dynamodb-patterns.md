# DynamoDB Patterns Deep Dive

## Partition Key Design

The partition key is the single most important design decision in DynamoDB. A bad
partition key leads to hot partitions, throttling, and uneven capacity utilization.

### Principles of Good Partition Keys

1. **High cardinality**: Many distinct values (user IDs, order IDs, device IDs)
2. **Uniform distribution**: Requests spread evenly across partitions
3. **Known at query time**: You must know the PK to query efficiently

### Bad Partition Key Examples

| Key | Problem | Better Alternative |
|-----|---------|-------------------|
| `status` (active/inactive) | Only 2 values, massive hot partition | Use status as SK, use entity ID as PK |
| `date` (2026-02-27) | Today's partition gets all writes | Composite: `date#shard_N` with random shard suffix |
| `region` (us-east-1) | Few values, uneven distribution | Use resource ID as PK, region as attribute |
| `type` (order/payment) | Few values | Use entity ID as PK, type as SK prefix |

### Write Sharding for Hot Keys

When a single key receives too many writes, shard it:

```python
import random

# Write: add random suffix
shard = random.randint(0, 9)
pk = f"DATE#2026-02-27#SHARD#{shard}"

# Read: scatter-gather across all shards
for shard in range(10):
    pk = f"DATE#2026-02-27#SHARD#{shard}"
    # query each shard and merge results
```

### Partition Internals

Each partition supports:
- 3,000 RCU (Read Capacity Units)
- 1,000 WCU (Write Capacity Units)
- 10 GB of data

DynamoDB automatically splits partitions when these limits are exceeded. But the split
does not help if all traffic goes to the same partition key.

```bash
# Check partition key distribution via CloudWatch Contributor Insights
aws dynamodb update-contributor-insights \
  --table-name MyTable \
  --contributor-insights-action ENABLE

# View top partition keys by throttled requests
aws cloudwatch get-metric-data \
  --metric-data-queries '[{
    "Id": "throttled",
    "MetricStat": {
      "Metric": {
        "Namespace": "AWS/DynamoDB",
        "MetricName": "ThrottledRequests",
        "Dimensions": [{"Name": "TableName", "Value": "MyTable"}]
      },
      "Period": 300,
      "Stat": "Sum"
    }
  }]' \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)
```

## GSI and LSI Strategies

### Global Secondary Indexes (GSI)

GSIs are separate tables with their own partition key and sort key. They have independent
capacity (can be provisioned separately from the base table).

```bash
# Check GSI status and capacity
aws dynamodb describe-table --table-name MyTable \
  --query 'Table.GlobalSecondaryIndexes[*].[IndexName,IndexStatus,ProvisionedThroughput]'
```

**GSI best practices:**
- Use sparse indexes: only items with the GSI key attribute are indexed
- Project only needed attributes to reduce index size and cost
- GSI capacity must match query load (independent throttling)
- Max 20 GSIs per table

### Local Secondary Indexes (LSI)

LSIs share the base table's partition key but have a different sort key. They share
capacity with the base table and must be created at table creation time.

**LSI limitations:**
- Max 5 per table
- Must be created at table creation (cannot add later)
- 10 GB partition limit includes LSI data
- Share capacity with base table

### Index Strategy Decision Tree

1. Need to query by a completely different key? -> **GSI**
2. Need to sort base table items differently? -> **LSI** (if table not yet created) or **GSI**
3. Need to query across partitions? -> **GSI** (LSIs are partition-scoped)
4. Need independent throughput? -> **GSI** (LSIs share base table capacity)
5. Infrequent queries on large datasets? -> Consider **Scan with filter** (cheaper than maintaining an index)

## Single-Table Design

Single-table design stores multiple entity types in the same DynamoDB table, using
composite keys to model relationships.

### Example: E-Commerce Application

```
PK                  | SK                      | Entity     | Attributes
--------------------|-------------------------|------------|------------------
USER#123            | PROFILE                 | User       | name, email
USER#123            | ORDER#2026-02-27#001    | Order      | total, status
USER#123            | ORDER#2026-02-27#001#ITEM#1 | OrderItem | product, qty
PRODUCT#ABC         | METADATA                | Product    | name, price
PRODUCT#ABC         | REVIEW#USER#123         | Review     | rating, text
```

### Access Patterns

| Pattern | Key Condition |
|---------|--------------|
| Get user profile | PK = USER#123, SK = PROFILE |
| Get user's orders | PK = USER#123, SK begins_with ORDER# |
| Get order items | PK = USER#123, SK begins_with ORDER#2026-02-27#001#ITEM# |
| Get product reviews | PK = PRODUCT#ABC, SK begins_with REVIEW# |

### When NOT to Use Single-Table Design

- Team unfamiliar with DynamoDB (steep learning curve)
- Access patterns will change frequently (rigid schema)
- Need ad-hoc queries (use a relational database instead)
- Complex aggregations across entities (use DynamoDB + analytics service)

## Read/Write Capacity Modes

### Provisioned Mode

```bash
# Set provisioned capacity
aws dynamodb update-table --table-name MyTable \
  --provisioned-throughput ReadCapacityUnits=100,WriteCapacityUnits=50

# Enable auto-scaling
aws application-autoscaling register-scalable-target \
  --service-namespace dynamodb \
  --resource-id "table/MyTable" \
  --scalable-dimension "dynamodb:table:ReadCapacityUnits" \
  --min-capacity 5 --max-capacity 1000

aws application-autoscaling put-scaling-policy \
  --service-namespace dynamodb \
  --resource-id "table/MyTable" \
  --scalable-dimension "dynamodb:table:ReadCapacityUnits" \
  --policy-name "ReadAutoScale" \
  --policy-type "TargetTrackingScaling" \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 70.0,
    "PredefinedMetricSpecification": {
      "PredefinedMetricType": "DynamoDBReadCapacityUtilization"
    }
  }'
```

### On-Demand Mode

```bash
# Switch to on-demand (can only switch once per 24 hours)
aws dynamodb update-table --table-name MyTable \
  --billing-mode PAY_PER_REQUEST
```

**When to use on-demand:**
- Unpredictable workloads
- New tables with unknown traffic patterns
- Spiky traffic (peaks >> average)
- Cost is acceptable (typically 6-7x more expensive per request than provisioned)

## DAX (DynamoDB Accelerator)

DAX is an in-memory cache for DynamoDB that provides microsecond read latency.

### DAX Behavior

| Operation | DAX Behavior |
|-----------|-------------|
| GetItem | Cache hit -> return from cache; miss -> read from DynamoDB, cache result |
| Query | Cache hit (by exact parameters) -> return; miss -> query DynamoDB, cache |
| PutItem/UpdateItem/DeleteItem | Write-through: update DynamoDB first, then invalidate cache |
| BatchGetItem | Each item checked individually in cache |
| Scan | Always goes to DynamoDB (not cached) |

### DAX Cluster Sizing

```bash
# Check DAX cluster status
aws dax describe-clusters --cluster-names my-dax-cluster

# Key metrics to monitor
# CPUUtilization: > 70% -> add nodes
# CacheMemoryUtilization: > 80% -> larger node type
# ItemCacheHitCount vs ItemCacheMissCount: hit rate should be > 90%
# QueryCacheHitCount vs QueryCacheMissCount
# EstimatedDbSize: if approaching node memory, items will be evicted
```

## Streams and Lambda

DynamoDB Streams capture item-level changes for event-driven architectures.

```bash
# Enable streams
aws dynamodb update-table --table-name MyTable \
  --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES

# Stream view types:
# KEYS_ONLY       - only the key attributes
# NEW_IMAGE        - the entire item after the change
# OLD_IMAGE        - the entire item before the change
# NEW_AND_OLD_IMAGES - both before and after (most common)
```

### Common Stream Patterns

1. **Materialized views**: Stream changes to a GSI table for different access patterns
2. **Cross-region replication**: Before global tables, streams powered replication
3. **Audit logging**: Capture all changes for compliance
4. **Event sourcing**: Stream to EventBridge or SNS for downstream processing
5. **Aggregation**: Lambda computes running totals, counters

## TTL (Time to Live)

TTL automatically deletes items after a specified timestamp, at no cost.

```bash
# Enable TTL on a table
aws dynamodb update-table-time-to-live \
  --table-name MyTable \
  --time-to-live-specification Enabled=true,AttributeName=expires_at

# The expires_at attribute must contain a Unix epoch timestamp (seconds)
# Items are typically deleted within 48 hours of expiration
# Expired items still appear in queries until actually deleted
# TTL deletes generate stream events (useful for cleanup triggers)
```

## Global Tables

Multi-region, fully replicated tables with active-active writes.

```bash
# Create a global table (table must exist in source region first)
aws dynamodb create-global-table \
  --global-table-name MyGlobalTable \
  --replication-group RegionName=us-east-1 RegionName=eu-west-1

# Check replication status
aws dynamodb describe-global-table --global-table-name MyGlobalTable

# Conflict resolution: last writer wins (based on timestamp)
# Cross-region replication latency: typically < 1 second
```

## Backup Strategies

```bash
# On-demand backup (instant, no performance impact)
aws dynamodb create-backup --table-name MyTable --backup-name "manual-2026-02-27"

# List backups
aws dynamodb list-backups --table-name MyTable

# Restore from backup (creates new table)
aws dynamodb restore-table-from-backup \
  --target-table-name MyTable-Restored \
  --backup-arn arn:aws:dynamodb:us-east-1:123456789012:table/MyTable/backup/...

# Point-in-time recovery (continuous backups, restore to any second in last 35 days)
aws dynamodb update-continuous-backups --table-name MyTable \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true

aws dynamodb restore-table-to-point-in-time \
  --source-table-name MyTable \
  --target-table-name MyTable-PITR-Restore \
  --restore-date-time "2026-02-26T15:00:00Z"
```
